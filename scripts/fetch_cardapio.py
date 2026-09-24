"""
Baixa o cardápio semanal do RU da UnB (ru.unb.br), extrai as tabelas
dos PDFs e gera um JSON por campus para o site.

Suporta dois formatos:
  - Tabelado (Darcy, Ceilândia, Gama, Planaltina, FAL): grade vetorial,
    cabeçalho com datas, rótulos em coluna própria.
  - Executivo: páginas por categoria ("Saladas", "Pratos principais", ...),
    sem grade; datas no topo e itens agrupados por coluna de data.

Uso:
    python scripts/fetch_cardapio.py                    # todos os campi
    python scripts/fetch_cardapio.py darcy executivo    # campi específicos
    python scripts/fetch_cardapio.py --pdf darcy arq.pdf  # PDF local
"""

import json
import re
import sys
import unicodedata
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SITE_DATA = ROOT / "site" / "data"
LISTING_BASE = "https://ru.unb.br"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Fuso de Brasília (UTC-3, sem horário de verão desde 2019)
TZ_BSB = timezone(timedelta(hours=-3))

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

# ---------------------------------------------------------------------------
# Campi suportados
# ---------------------------------------------------------------------------
CAMPUS = {
    "darcy": {
        "name": "Darcy Ribeiro",
        "listing": f"{LISTING_BASE}/cardapio/",
        "pattern": r"Darcy-Ribeiro",
    },
    "executivo": {
        "name": "Restaurante Executivo",
        "listing": f"{LISTING_BASE}/restaurante-executivo/",
        "pattern": r"(?<![^/])SEMANA-",  # PDFs do executivo: SEMANA-04-17-08...
    },
    "fcts": {
        "name": "Ceilândia (FCTS)",
        "listing": f"{LISTING_BASE}/cardapio-ceilandia/",
        "pattern": r"Ceilandia",
    },
    "fcte": {
        "name": "Gama (FCTE)",
        "listing": f"{LISTING_BASE}/cardapio-gama/",
        "pattern": r"Gama",
    },
    "fup": {
        "name": "Planaltina (FUP)",
        "listing": f"{LISTING_BASE}/cardapio-planaltina/",
        "pattern": r"Planaltina",
    },
    "fal": {
        "name": "Fazenda Água Limpa (FAL)",
        "listing": f"{LISTING_BASE}/cardapio-fazenda-agua-limpa/",
        "pattern": r"Fazenda",
    },
}
DEFAULT_CAMPUS = "darcy"

MEAL_KEYS = {"cafe": "cafe da manha", "almoco": "almoco", "jantar": "jantar"}
MEAL_PRETTY = {"cafe": "Café da manhã", "almoco": "Almoço", "jantar": "Jantar"}
MEAL_ORDER = ["cafe", "almoco", "jantar"]

# ---------------------------------------------------------------------------
# Parser de PDFs tabelados (Darcy, FCTS, FCTE, FUP, FAL)
# ---------------------------------------------------------------------------
LABELS = [
    "BEBIDAS", "PANIFICACAO", "OPCAO EXTRA", "GORDURA",
    "COMPLEMENTO PADRAO", "COMPLEMENTO OVOLACTOVEGETARIANO",
    "COMPLEMENTO VEGETARIANO ESTRITO", "FRUTA",
    "SALADA 1", "SALADA 2", "MOLHO PARA SALADA",
    "PRATO PRINCIPAL PADRAO", "PRATO PRINCIPAL OVOLACTOVEGETARIANO",
    "PRATO PRINCIPAL VEGETARIANO ESTRITO",
    "GUARNICAO", "ACOMPANHAMENTOS", "SOBREMESA",
    "BEBIDA (REFRESCO DE)", "SOPA", "TORRADA",
]

LABEL_PRETTY = {
    "BEBIDAS": "Bebidas", "PANIFICACAO": "Panificação", "OPCAO EXTRA": "Opção Extra",
    "GORDURA": "Gordura", "COMPLEMENTO PADRAO": "Complemento Padrão",
    "COMPLEMENTO OVOLACTOVEGETARIANO": "Complemento Ovolactovegetariano",
    "COMPLEMENTO VEGETARIANO ESTRITO": "Complemento Vegetariano Estrito",
    "FRUTA": "Fruta", "SALADA 1": "Salada 1", "SALADA 2": "Salada 2",
    "MOLHO PARA SALADA": "Molho para Salada",
    "PRATO PRINCIPAL PADRAO": "Prato Principal Padrão",
    "PRATO PRINCIPAL OVOLACTOVEGETARIANO": "Prato Principal Ovolactovegetariano",
    "PRATO PRINCIPAL VEGETARIANO ESTRITO": "Prato Principal Vegetariano Estrito",
    "GUARNICAO": "Guarnição", "ACOMPANHAMENTOS": "Acompanhamentos",
    "SOBREMESA": "Sobremesa", "BEBIDA (REFRESCO DE)": "Bebida (Refresco de)",
    "SOPA": "Sopa", "TORRADA": "Torrada",
}


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(s):
    return re.sub(r"\s+", " ", strip_accents(s or "").upper()).strip()


def match_label(text):
    t = norm(text)
    if t.startswith("BEBIDA"):
        return "BEBIDA (REFRESCO DE)"
    best = None
    for lab in LABELS:
        if t.startswith(lab):
            best = lab
    return best


def match_meal(text):
    t = norm(text).replace(" ", "").lower()
    for key, name in MEAL_KEYS.items():
        if name.replace(" ", "") in t:
            return key
    return None


TABLE_CFG = {"vertical_strategy": "lines", "horizontal_strategy": "lines",
             "snap_tolerance": 3, "join_tolerance": 3}


def parse_table_pdf(path):
    """Parser para PDFs com grade: retorna {data_iso: {meal: [{'label','value'}]}}.

    Detecta automaticamente a linha de cabeçalho (datas), a coluna de rótulos
    e a refeição da página (texto vertical), tolerando variações de layout
    entre campi.
    """
    days = {}
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            table = page.extract_table(TABLE_CFG)
            if not table:
                continue

            # --- cabeçalho: linha com >= 4 datas
            header_idx, col_date = None, {}
            for i, row in enumerate(table):
                mapping = {}
                for j, cell in enumerate(row):
                    m = DATE_RE.search(cell or "")
                    if m:
                        d, mo, y = map(int, m.groups())
                        try:
                            mapping[j] = date(y, mo, d).isoformat()
                        except ValueError:
                            pass
                if len(mapping) >= 4:
                    header_idx, col_date = i, mapping
                    break
            if header_idx is None:
                continue

            # --- coluna de rótulos: primeira coluna fora do mapa de datas
            #     cujas células casam com rótulos conhecidos em >= 3 linhas
            label_col = None
            for j in range(max(col_date)):
                if j in col_date:
                    continue
                hits = sum(1 for row in table[header_idx + 1:]
                           if j < len(row) and match_label(row[j] or ""))
                if hits >= 3:
                    label_col = j
                    break
            if label_col is None:
                continue

            # --- refeição da página: texto vertical nas colunas à esquerda
            page_meal = None
            for j in range(0, max(3, label_col)):
                if any(j == dj for dj in col_date):
                    continue
                vertical = " ".join((row[j] or "") for row in table if len(row) > j)
                page_meal = match_meal(vertical) or match_meal(vertical[::-1])
                if page_meal:
                    break
            if not page_meal:
                continue

            # --- linhas de itens
            # Nos PDFs mais recentes o cabeçalho vem em DUAS linhas
            # (row0 = "2ª FEIRA", row1 = "24/8/2026") e a grade cria colunas
            # deslocadas: a data fica na coluna j, mas os VALORES caem em j-1.
            # Decide UMA vez por página, olhando só as linhas cujo rótulo é
            # conhecido (linhas estranhas não podem viciar a detecção):
            # se a coluna da data está vazia em praticamente todas e a
            # anterior preenchida, os valores estão deslocados para j-1.
            label_rows = [row for row in table[header_idx + 1:]
                          if len(row) > label_col
                          and match_label(row[label_col] or "")]

            def value_col_for(j):
                n = len(label_rows)
                if j == 0 or n < 3:
                    return j
                empty_at_j = sum(1 for row in label_rows
                                 if not (j < len(row) and str(row[j] or "").strip()))
                filled_prev = sum(1 for row in label_rows
                                  if j - 1 < len(row) and str(row[j - 1] or "").strip())
                if empty_at_j >= n - 1 and filled_prev >= n - 1:
                    return j - 1
                return j

            col_value = {j: value_col_for(j) for j in col_date}

            # Região de colunas de cada data: da coluna de valor da data até
            # antes da coluna de valor da data seguinte. Textos longos às
            # vezes estouram para linhas de grade ABAIXO da linha do rótulo
            # (e em colunas vizinhas dentro da própria data) — ex.: Gama,
            # "Carne de sol trinchada com / cebola roxa" em duas linhas
            # extra. Essas linhas são recuperadas pela varredura da região.
            date_cols = sorted(col_date)
            regions = {}
            for i, j in enumerate(date_cols):
                start = col_value[j]
                end = (col_value[date_cols[i + 1]] - 1
                       if i + 1 < len(date_cols) else None)
                regions[j] = (start, end)

            rows = table[header_idx + 1:]

            def region_text(row_list, start, end):
                parts = []
                for r in row_list:
                    for k in range(start, len(r) if end is None else min(end, len(r) - 1) + 1):
                        v = re.sub(r"\s+", " ", r[k] or "").strip()
                        if v:
                            parts.append(v)
                return " ".join(parts)

            for idx, row in enumerate(rows):
                cells = [c or "" for c in row]
                if len(cells) <= label_col:
                    continue
                label = match_label(cells[label_col])
                if not label:
                    continue
                # linhas seguintes sem rótulo podem conter a continuação
                # do valor (stouro da célula) desta linha
                nxt = next((k for k in range(idx + 1, len(rows))
                            if len(rows[k]) > label_col
                            and match_label(rows[k][label_col] or "")), None)
                lookahead = rows[idx + 1:] if nxt is None else rows[idx + 1:nxt]
                for j, iso in col_date.items():
                    vcol = col_value[j]
                    value = re.sub(r"\s*\n\s*", " ", cells[vcol]).strip() if vcol < len(cells) else ""
                    if not value:
                        start, end = regions[j]
                        value = region_text([cells] + lookahead,
                                            max(start, label_col + 1), end)
                    if not value:
                        continue
                    entries = days.setdefault(iso, {}).setdefault(page_meal, [])
                    if not any(e["label"] == LABEL_PRETTY[label] for e in entries):
                        entries.append({"label": LABEL_PRETTY[label],
                                        "value": re.sub(r"\s+", " ", value)})
    return days


# ---------------------------------------------------------------------------
# Parser do Restaurante Executivo (sem grade, categorias por página)
# ---------------------------------------------------------------------------
EXEC_CATS = ["Saladas", "Pratos principais", "Guarnições",
             "Acompanhamentos", "Sobremesas"]
# rótulo no singular para o site ("Salada 1", "Salada 2", ... como nos
# PDFs tabelados); categorias sem entrada no mapa ficam como estão
EXEC_SINGULAR = {
    "Saladas": "Salada",
    "Pratos principais": "Prato Principal",
    "Guarnições": "Guarnição",
    "Acompanhamentos": "Acompanhamento",
    "Sobremesas": "Sobremesa",
}
EXEC_HEADER_TOP = 178   # palavras acima disso são cabeçalho/logo
EXEC_LINE_TOL = 3.0     # tolerância para agrupar palavras na mesma linha
EXEC_BLOCK_GAP = 12.0   # gap vertical (pt) que separa dois itens


def parse_executivo_pdf(path):
    """Parser do formato Executivo: retorna {data_iso: [{'label','value'}]}."""
    out = {}
    with pdfplumber.open(path) as pdf:
        # datas/bordas de coluna vêm da primeira página (idênticas nas demais)
        p0 = pdf.pages[0]
        dw = [(w["text"], (w["x0"] + w["x1"]) / 2) for w in p0.extract_words()
              if DATE_RE.fullmatch(w["text"])]
        if not dw:
            return out
        centers = sorted(c for _, c in dw)
        bounds = ([0.0]
                  + [(a + b) / 2 for a, b in zip(centers, centers[1:])]
                  + [float("inf")])
        isos = []
        for t, _ in sorted(dw, key=lambda x: x[1]):
            d, m, y = t.split("/")
            isos.append(f"{y}-{int(m):02d}-{int(d):02d}")
        for iso in isos:
            out.setdefault(iso, [])

        for i, page in enumerate(pdf.pages):
            words = page.extract_words()
            # categoria: título no topo da página, se casar com uma conhecida
            # (a ordem das páginas no PDF pode mudar); posição como fallback
            top_norm = strip_accents(" ".join(w["text"] for w in words
                                              if w["top"] < EXEC_HEADER_TOP)).lower()
            fallback = EXEC_CATS[i] if i < len(EXEC_CATS) else f"Categoria {i + 1}"
            cat = next((c for c in EXEC_CATS if strip_accents(c).lower() in top_norm),
                       fallback)

            cols = {j: [] for j in range(len(isos))}
            for w in words:
                if w["top"] < EXEC_HEADER_TOP:
                    continue
                xc = (w["x0"] + w["x1"]) / 2
                j = next((k for k in range(len(bounds) - 1)
                          if bounds[k] <= xc < bounds[k + 1]), None)
                if j is not None and j < len(isos):
                    cols[j].append(w)

            for j, ws in cols.items():
                if not ws:
                    continue
                # agrupar palavras em linhas visuais
                lines = {}
                for w in ws:
                    key = next((k for k in lines if abs(k - w["top"]) <= EXEC_LINE_TOL),
                               round(w["top"], 1))
                    lines.setdefault(key, []).append(w)
                sorted_lines = sorted(lines.items())

                # agrupar linhas consecutivas em blocos (itens)
                blocks, cur, last_top = [], [], None
                for top, lws in sorted_lines:
                    if last_top is not None and top - last_top > EXEC_BLOCK_GAP:
                        blocks.append(cur)
                        cur = []
                    cur.append((top, lws))
                    last_top = top
                if cur:
                    blocks.append(cur)

                for b in blocks:
                    parts = []
                    for _, lws in b:
                        lws2 = sorted(lws, key=lambda w: w["x0"])
                        parts.append(" ".join(w["text"] for w in lws2))
                    text = re.sub(r"\s+", " ", " ".join(parts)).strip(" ,;")
                    if len(text) < 2:
                        continue
                    out[isos[j]].append({"label": cat, "value": text})

        # numera itens repetidos do mesmo dia ("Salada 1", "Salada 2", ...)
        # e singulariza o rótulo; categoria com um item só fica no singular
        for iso, items in out.items():
            idxs_by_cat = {}
            for i, it in enumerate(items):
                idxs_by_cat.setdefault(it["label"], []).append(i)
            for cat, idxs in idxs_by_cat.items():
                singular = EXEC_SINGULAR.get(cat, cat)
                if len(idxs) > 1:
                    for n, i in enumerate(idxs, 1):
                        items[i]["label"] = f"{singular} {n}"
                else:
                    items[idxs[0]]["label"] = singular
    return out


# ---------------------------------------------------------------------------
# Descoberta/download
# ---------------------------------------------------------------------------
def discover_pdfs(listing_url, pattern):
    req = Request(listing_url, headers={"User-Agent": UA})
    html = urlopen(req, timeout=30).read().decode("utf-8", "replace")
    links = sorted(set(re.findall(r'href="([^"]*\.pdf)"', html, re.I)))
    links = [urljoin(listing_url, u.replace("http://", "https://")) for u in links]
    return [u for u in links if re.search(pattern, u.split("/")[-1], re.I)]


def range_of(url):
    """Intervalo de datas coberto pelo PDF, inferido do nome do arquivo.

    Formatos conhecidos:
      .../Darcy-Ribeiro-Semana-01-24-8-a-30-8.pdf  -> 24/8 a 30/8 (ano no path)
      .../Cardapio-24-8-2026-a-30-8-2026.pdf       -> idem, com ano explícito
      datas com barras também são aceitas (24/8/2026)
    """
    name = url.split("/")[-1]
    # ano: procura /2026/ no caminho (padrão WordPress) ou 4 dígitos no nome
    year_match = re.search(r"/(20\d{2})/", url) or re.search(r"(20\d{2})", name)
    year = int(year_match.group(1)) if year_match else datetime.now(TZ_BSB).date().year

    ds = []
    # 1) formato completo d/m/aaaa
    for d, m, y in DATE_RE.findall(name):
        try:
            ds.append(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    # 1b) formato completo com hífens (ex.: "Cardapio-14-9-2026-a-20-9-2026")
    if not ds:
        for d, m, y in re.findall(r"(\d{1,2})-(\d{1,2})-(20\d{2})", name):
            try:
                ds.append(date(int(y), int(m), int(d)))
            except ValueError:
                pass
    # 2) formato curto d-m (ex.: "Semana-04-17-8-A-23-8" -> 17/8 e 23/8)
    if not ds:
        # "17-8" = dia-mês; o sufixo (?!-?\d) garante que o mês não é seguido
        # de outro número (descarta "04-17" do prefixo "Semana-04")
        pairs = [(int(d), int(m))
                 for d, m in re.findall(r"(\d{1,2})-(\d{1,2})(?!-?\d)", name)]
        valid_months = {m for _, m in pairs if 1 <= m <= 12}
        for d, m in pairs:
            if not (1 <= d <= 31 and 1 <= m <= 12):
                # mês impossível no nome (PDF vigente do executivo:
                # "SEMANA-04-14-09-A-18-19" -> fim é 18/09, não 18/19);
                # se só há um mês válido no intervalo, assume ele
                if m > 12 and len(valid_months) == 1:
                    m = next(iter(valid_months))
                else:
                    continue
            try:
                ds.append(date(year, m, d))
            except ValueError:
                pass
    return (min(ds), max(ds)) if ds else (None, None)


def pick_current(links, today=None):
    """Escolhe o PDF cujo intervalo de datas cobre o dia de referência.

    No domingo o alvo passa a ser a segunda-feira seguinte: o cardápio de
    domingo já foi exibido a semana toda e, se a UnB já publicou o PDF da
    semana seguinte (costuma sair antes do domingo), o site mostra a semana
    nova desde cedo. Sem PDF da semana seguinte publicado, mantém o da
    semana atual.

    Sem cobertura (virada de semana / PDF atrasado), prefere a semana futura
    mais próxima; se não houver, a mais recente já publicada — por data
    inferida, não por ordem alfabética ("Semana-10" ordena antes de "Semana-9").
    """
    today = today or datetime.now(TZ_BSB).date()
    alvo = today + timedelta(days=1) if today.weekday() == 6 else today

    def covers(u, d):
        r = range_of(u)
        return r[0] is not None and r[0] <= d <= r[1]

    covering = [u for u in links if covers(u, alvo)]
    if covering:
        if alvo != today:
            print(f"Domingo: usando o PDF da semana seguinte (cobre {alvo})")
        return covering[:1]
    if alvo != today:
        covering = [u for u in links if covers(u, today)]
        if covering:
            print("AVISO: PDF da semana seguinte ainda não publicado; "
                  "usando o da semana atual")
            return covering[:1]
    if not links:
        return []
    futuras = sorted((u for u in links if range_of(u)[0] is not None
                      and range_of(u)[1] >= today),
                     key=lambda u: range_of(u)[0])
    if futuras:
        print(f"AVISO: nenhum PDF cobre {today}; "
              f"usando a semana futura mais próxima ({futuras[0]})")
        return futuras[:1]
    latest = max(links, key=lambda u: (range_of(u)[0] or date.min, u))
    print(f"AVISO: nenhum PDF cobre {today}; usando o mais recente ({latest})")
    return [latest]


def download(url, dest):
    req = Request(url, headers={"User-Agent": UA})
    dest.write_bytes(urlopen(req, timeout=60).read())
    return dest


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def process_campus(key, cfg, today=None):
    """Baixa o PDF vigente do campus e gera site/data/cardapio-<key>.json."""
    print(f"\n=== {key} ({cfg['name']}) ===")
    print("Descobrindo PDFs em", cfg["listing"])
    links = discover_pdfs(cfg["listing"], cfg["pattern"])
    print(f"{len(links)} PDF(s):", *("  " + l for l in links), sep="\n")
    chosen = pick_current(links, today=today)
    if not chosen:
        raise RuntimeError(f"nenhum PDF encontrado em {cfg['listing']}")
    print("Usando:", chosen)

    sources, merged = [], {}
    for u in chosen:
        p = DATA_DIR / f"{key}-{u.split('/')[-1]}"
        download(u, p)
        src = {"file": p.name, "url": u}

        if key == "executivo":
            week_flat = parse_executivo_pdf(p)
            print(f"{p.name}: {len(week_flat)} dia(s) extraído(s)")
            if not week_flat:
                raise RuntimeError(f"nada extraído de {p}")
            # formato plano -> uma única "refeição"
            week = {iso: {"principal": items} for iso, items in week_flat.items()}
        else:
            week = parse_table_pdf(p)
            print(f"{p.name}: {len(week)} dia(s) extraído(s)")
            if not week:
                raise RuntimeError(f"nada extraído de {p}")

        merged.update(week)
        sources.append(src)

    meals_order = ["principal"] if key == "executivo" else MEAL_ORDER
    meals_names = {"principal": "Cardápio"} if key == "executivo" else MEAL_PRETTY

    out = {
        "campus": key,
        "campus_name": cfg["name"],
        "generated_at": datetime.now(TZ_BSB).isoformat(timespec="seconds"),
        "meals_order": meals_order,
        "meals_names": meals_names,
        "sources": sources,
        "days": dict(sorted(merged.items())),
    }
    SITE_DATA.mkdir(exist_ok=True)
    dest = SITE_DATA / f"cardapio-{key}.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK -> {dest} ({len(out['days'])} dias)")
    return out


def main():
    DATA_DIR.mkdir(exist_ok=True)
    args = sys.argv[1:]
    keys = list(CAMPUS)

    if "--pdf" in args:
        # modo teste local: --pdf <campus> <arquivo.pdf>
        i = args.index("--pdf")
        key, path = args[i + 1], Path(args[i + 2])
        cfg = CAMPUS[key]
        parser = parse_executivo_pdf if key == "executivo" else parse_table_pdf
        week = parser(path)
        if key == "executivo":
            week = {iso: {"principal": items} for iso, items in week.items()}
        out = {
            "campus": key,
            "campus_name": cfg["name"],
            "generated_at": datetime.now(TZ_BSB).isoformat(timespec="seconds"),
            "meals_order": ["principal"] if key == "executivo" else MEAL_ORDER,
            "meals_names": {"principal": "Cardápio"} if key == "executivo" else MEAL_PRETTY,
            "sources": [{"file": path.name, "url": None}],
            "days": dict(sorted(week.items())),
        }
        SITE_DATA.mkdir(exist_ok=True)
        dest = SITE_DATA / f"cardapio-{key}.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK -> {dest} ({len(out['days'])} dias)")
        return

    if args:
        unknown = [a for a in args if a not in CAMPUS]
        if unknown:
            sys.exit(f"Campus desconhecido: {unknown}. Opções: {list(CAMPUS)}")
        keys = args

    today = datetime.now(TZ_BSB).date()
    results = {}
    failures = []
    for k in keys:
        try:
            results[k] = process_campus(k, CAMPUS[k], today=today)
        except Exception as e:
            print(f"ERRO em {k}: {e}")
            failures.append(k)

    if failures:
        print("\nFalhou em:", failures)
        if not results:
            sys.exit(1)  # nenhum campus teve sucesso; não há o que publicar
        print("Seguindo com os campi que tiveram sucesso "
              "(os que falharam mantêm o JSON anterior).")


if __name__ == "__main__":
    main()
