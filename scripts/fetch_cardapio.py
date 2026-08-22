"""
Baixa o cardápio semanal do RU Darcy Ribeiro (ru.unb.br), extrai as tabelas
do PDF por geometria (posições das palavras) e gera um JSON para o site.

Uso:
    python scripts/fetch_cardapio.py                 # busca na página oficial
    python scripts/fetch_cardapio.py arquivo.pdf ... # converte PDFs locais
"""

import json
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.request import Request, urlopen

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_JSON = DATA_DIR / "cardapio.json"
LISTING_URL = "https://ru.unb.br/cardapio/"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
FOOTER_RE = re.compile(r"Mesa de apoio|sujeito a altera", re.I)

# Rótulos normalizados (sem acento, maiúsculas)
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
MEAL_KEYS = {"cafe": "cafe da manha", "almoco": "almoco", "jantar": "jantar"}

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
MEAL_PRETTY = {"cafe": "Café da manhã", "almoco": "Almoço", "jantar": "Jantar"}
MEAL_ORDER = ["cafe", "almoco", "jantar"]


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


def parse_pdf(path):
    """Retorna {data_iso: {meal: [{'label','value'}, ...]}}.

    Usa a grade vetorial da tabela (extract_table com strategy='lines'),
    que preserva células multilinha sem vazamento entre linhas/colunas.
    """
    days = {}
    table_cfg = {"vertical_strategy": "lines", "horizontal_strategy": "lines",
                 "snap_tolerance": 3, "join_tolerance": 3}

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            table = page.extract_table(table_cfg)
            if not table:
                continue

            # --- cabeçalho: linha com 'COMPOSIÇÃO' e >= 5 datas
            header_idx, col_date = None, {}
            for i, row in enumerate(table):
                cells = [c or "" for c in row]
                if not any("composi" in norm(c) or "COMPOSIÇÃO" in (c or "").upper() for c in cells):
                    continue
                mapping = {}
                for j, cell in enumerate(cells):
                    m = DATE_RE.search(cell)
                    if m:
                        d, mo, y = map(int, m.groups())
                        try:
                            mapping[j] = date(y, mo, d).isoformat()
                        except ValueError:
                            pass
                if len(mapping) >= 5:
                    header_idx, col_date = i, mapping
                    break
            if header_idx is None:
                continue

            # --- refeição da página: texto vertical na 1ª/2ª coluna
            page_meal = None
            for j in (1, 0, 2):
                vertical = " ".join((row[j] or "") for row in table if len(row) > j)
                page_meal = match_meal(vertical) or match_meal(vertical[::-1])
                if page_meal:
                    break
            if not page_meal:
                continue

            # --- linhas de itens
            for row in table[header_idx + 1:]:
                cells = [c or "" for c in row]
                label_raw = cells[3] if len(cells) > 3 else ""
                label = match_label(label_raw)
                if not label:
                    continue
                text_by_col = {}
                for j, iso in col_date.items():
                    value = re.sub(r"\s*\n\s*", " ", cells[j]).strip() if j < len(cells) else ""
                    if value:
                        text_by_col[iso] = re.sub(r"\s+", " ", value)
                for iso, value in text_by_col.items():
                    entries = days.setdefault(iso, {}).setdefault(page_meal, [])
                    if not any(e["label"] == LABEL_PRETTY[label] for e in entries):
                        entries.append({"label": LABEL_PRETTY[label], "value": value})
    return days


def discover_pdfs():
    req = Request(LISTING_URL, headers={"User-Agent": UA})
    html = urlopen(req, timeout=30).read().decode("utf-8", "replace")
    links = sorted(set(re.findall(r'href="([^"]*Darcy-Ribeiro[^"]*\.pdf)"', html, re.I)))
    return [u.replace("http://", "https://") for u in links]


def pick_current(links, today=None):
    """Escolhe os PDFs cujo intervalo de datas cobre hoje."""
    today = today or date.today()

    def range_of(url):
        ds = []
        for d, m, y in DATE_RE.findall(url.split("/")[-1]):
            try:
                ds.append(date(int(y), int(m), int(d)))
            except ValueError:
                pass
        return (min(ds), max(ds)) if ds else (None, None)

    covering = [u for u in links
                if (lambda r: r[0] and r[0] <= today <= r[1])(range_of(u))]
    return covering[:1] if covering else links[-1:]


def download(url, dest):
    req = Request(url, headers={"User-Agent": UA})
    dest.write_bytes(urlopen(req, timeout=60).read())
    return dest


def main():
    DATA_DIR.mkdir(exist_ok=True)
    sources = []
    merged = {}

    args = sys.argv[1:]
    if args:
        pdfs = [(None, Path(a)) for a in args]
    else:
        print("Descobrindo PDFs em", LISTING_URL)
        links = discover_pdfs()
        print(f"{len(links)} PDF(s) encontrados:", *("  " + l for l in links), sep="\n")
        chosen = pick_current(links)
        print("Usando:", chosen)
        pdfs = []
        for u in chosen:
            p = download(u, DATA_DIR / u.split("/")[-1])
            pdfs.append((u, p))

    for source, path in pdfs:
        week = parse_pdf(path)
        print(f"{path.name}: {len(week)} dia(s) extraido(s)")
        if not week:
            sys.exit(f"ERRO: nada extraído de {path}")
        merged.update(week)
        sources.append({"file": path.name, "url": source})

    out = {
        "campus": "Darcy Ribeiro",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "meals_order": MEAL_ORDER,
        "meals_names": MEAL_PRETTY,
        "sources": sources,
        "days": dict(sorted(merged.items())),
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK -> {OUT_JSON} ({len(out['days'])} dias)")


if __name__ == "__main__":
    main()
