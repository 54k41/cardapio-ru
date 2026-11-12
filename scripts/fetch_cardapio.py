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
from datetime import date, datetime, time as dtime, timezone, timedelta
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
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
        "listings": [f"{LISTING_BASE}/cardapio/", f"{LISTING_BASE}/cardapio-refeitorio/"],
        "pattern": r"Darcy-Ribeiro",
    },
    "executivo": {
        "name": "Restaurante Executivo",
        "listings": [f"{LISTING_BASE}/restaurante-executivo/"],
        "pattern": r"(?<![^/])SEMANA-",  # PDFs do executivo: SEMANA-04-17-08...
    },
    "fcts": {
        "name": "Ceilândia (FCTS)",
        "listings": [f"{LISTING_BASE}/cardapio-ceilandia/", f"{LISTING_BASE}/cardapio-refeitorio/"],
        "pattern": r"Ceilandia",
    },
    "fcte": {
        "name": "Gama (FCTE)",
        "listings": [f"{LISTING_BASE}/cardapio-gama/", f"{LISTING_BASE}/cardapio-refeitorio/"],
        "pattern": r"Gama",
    },
    "fup": {
        "name": "Planaltina (FUP)",
        "listings": [f"{LISTING_BASE}/cardapio-planaltina/", f"{LISTING_BASE}/cardapio-refeitorio/"],
        "pattern": r"Planaltina",
    },
    "fal": {
        "name": "Fazenda Água Limpa (FAL)",
        "listings": [f"{LISTING_BASE}/cardapio-fazenda-agua-limpa/", f"{LISTING_BASE}/cardapio-refeitorio/"],
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


def url_filename(url):
    """Nome do arquivo de um link, sem a query string.

    O WordPress serve reenvios como "...pdf?ver=2"; manter o "?" no nome
    local quebra o download no Windows (OSError: nome de arquivo inválido).
    """
    return unquote(urlparse(url).path.rsplit("/", 1)[-1])


def local_pdf_name(key, url):
    """Nome do arquivo em data/ para o PDF de `url` (seguro em qualquer SO)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", url_filename(url)).strip(". -")
    return f"{key}-{name or 'cardapio.pdf'}"


# rótulos sem espaços: células estreitas quebram o rótulo no MEIO da
# palavra ("PRATO PRINCIPAL\nOVOLACTOVEGETARIAN\nO"), e norm() vira isso
# em "PRATO PRINCIPAL OVOLACTOVEGETARIAN O" — comparar sem nenhum espaço
_LABEL_KEYS = [(lab, lab.replace(" ", "")) for lab in LABELS]


def match_label(text):
    t = re.sub(r"\s+", "", norm(text))
    best = None
    for lab, key in _LABEL_KEYS:
        if t.startswith(key):
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
            tb = page.find_table(TABLE_CFG)
            if tb is None:
                continue
            table = tb.extract()
            if not table:
                continue

            # --- cabeçalho: datas, possivelmente quebradas em linhas
            #     vizinhas (ex.: Darcy 28/9/2026 numa linha, ao lado de
            #     "COMPOSIÇÃO", e 29/9–4/10 na linha seguinte). Coleta
            #     TODAS as linhas de datas coladas entre si: uma semana
            #     tem no máximo 7 dias, e parar em 4 truncaria um
            #     cabeçalho dividido com 2ª–5ª numa linha e 6ª–domingo
            #     na seguinte.
            header_idx, col_date, last_date_row = None, {}, None
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
                if not mapping:
                    continue
                if header_idx is None:
                    header_idx, last_date_row = i, i
                elif i - last_date_row > 2:
                    break  # datas longe umas das outras: outro trecho da tabela
                for j, iso in mapping.items():
                    col_date.setdefault(j, iso)
                last_date_row = i
                if len(col_date) >= 7:
                    break  # semana completa
            if header_idx is None or len(col_date) < 4:
                continue

            # --- coluna de rótulos: primeira coluna fora do mapa de datas
            #     cujas células casam com rótulos conhecidos em >= 3 linhas
            label_col = None
            for j in range(max(col_date)):
                if j in col_date:
                    continue
                hits = sum(1 for row in table[last_date_row + 1:]
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
            # Nos PDFs com grade deslocada (ex.: Gama) a data fica na coluna
            # j, mas os VALORES caem em j-1. A heurística olha as linhas cujo
            # rótulo é conhecido, porém a decisão é por PÁGINA (maioria das
            # colunas): o deslocamento é estrutural da grade. Decidir por
            # coluna faria um dia vazio (feriado) deslocar só a própria
            # coluna para j-1 — clonando o cardápio do dia anterior no dia
            # fechado (ou exibindo os rótulos quando o feriado é segunda).
            label_rows = [row for row in table[last_date_row + 1:]
                          if len(row) > label_col
                          and match_label(row[label_col] or "")]

            def value_col_for(j):
                n = len(label_rows)
                if j == 0 or n < 3 or j - 1 <= label_col:
                    return j
                empty_at_j = sum(1 for row in label_rows
                                 if not (j < len(row) and str(row[j] or "").strip()))
                filled_prev = sum(1 for row in label_rows
                                  if j - 1 < len(row) and str(row[j - 1] or "").strip())
                if empty_at_j >= n - 1 and filled_prev >= n - 1:
                    return j - 1
                return j

            votes = sum(1 for j in col_date if value_col_for(j) == j - 1)
            shifted = 2 * votes > len(col_date)
            col_value = {j: (j - 1 if shifted else j) for j in col_date}

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

            # --- bbox das células: a origem de uma mescla HORIZONTAL guarda
            #     o bbox que cobre todas as colunas da mescla. É o que
            #     distingue "esta célula vale para o dia X" (ex.: BEBIDAS de
            #     2a a domingo no café) de "esta célula está vazia/None"
            #     (dia sem cardápio, feriado — inclusive mescla na VERTICAL,
            #     que repete o dia anterior): no segundo caso o bbox da
            #     célula vizinha termina na própria borda do dia.
            row_cells = [list(r.cells) for r in tb.rows]
            tb_rows = row_cells[last_date_row + 1:]
            rows = table[last_date_row + 1:]
            first_vcol = min(col_value.values())

            hdr_cells = (row_cells[header_idx]
                         if header_idx < len(row_cells) else [])

            def col_left_edge(j):
                for k in range(min(j, len(hdr_cells) - 1), -1, -1):
                    cell = hdr_cells[k]
                    if cell is not None:
                        return cell[0]
                return None

            day_left = {j: col_left_edge(col_value[j]) for j in col_date}

            def clean(c):
                return re.sub(r"\s+", " ", c or "").strip()

            def cell_at(cells, k):
                return cells[k] if 0 <= k < len(cells) else None

            def merged_cell(cells, bboxes, vcol, j):
                """Texto da célula do dia: a própria, ou a origem de uma
                célula MESCLADA na horizontal — pdfplumber devolve o texto
                só na 1a coluna da mescla e None nas cobertas (ex.: BEBIDAS
                e GORDURA mescladas de 2a a domingo no café, que só
                apareciam na segunda-feira).

                A herança só vale quando o bbox da origem passa da borda
                esquerda do dia consultado. Assim, um dia sem cardápio
                (feriado com a célula mesclada na VERTICAL, que vem como
                None) não herda o prato do dia anterior.
                """
                c = cell_at(cells, vcol)
                if c is not None:
                    return c
                for k in range(vcol - 1, first_vcol - 1, -1):
                    c = cell_at(cells, k)
                    if c is None:
                        continue
                    bbox = bboxes[k] if k < len(bboxes) else None
                    edge = day_left.get(j)
                    if bbox is not None and edge is not None and bbox[2] > edge + 1:
                        return c
                    return None
                return None

            def region_text(row_list, start, end):
                parts = []
                for r in row_list:
                    for k in range(start, len(r) if end is None else min(end, len(r) - 1) + 1):
                        v = clean(r[k] if k < len(r) else None)
                        if v:
                            parts.append(v)
                return " ".join(parts)

            for idx, row in enumerate(rows):
                cells = list(row)  # preserva None: marca células mescladas
                if len(cells) <= label_col:
                    continue
                label = match_label(cells[label_col])
                if not label:
                    continue
                # linhas seguintes sem rótulo podem conter a continuação
                # do valor desta linha (2a linha de BEBIDAS no café; estouro
                # da célula em linhas de grade abaixo)
                nxt = next((k for k in range(idx + 1, len(rows))
                            if len(rows[k]) > label_col
                            and match_label(rows[k][label_col])), None)
                look = range(idx + 1, len(rows) if nxt is None else nxt)

                for j, iso in col_date.items():
                    vcol = col_value[j]
                    start, end = regions[j]
                    lo = max(start, label_col + 1)
                    bboxes = tb_rows[idx] if idx < len(tb_rows) else []
                    raw = merged_cell(cells, bboxes, vcol, j)
                    was_merged = cell_at(cells, vcol) is None
                    value = clean(raw) if raw is not None else ""
                    if not value:
                        # estouro do texto para linhas abaixo, dentro da
                        # região da própria data
                        value = region_text([cells], lo, end)
                    # continuação nas linhas abaixo: em dias cujo valor veio
                    # de célula mesclada, a continuação (ex.: "Café OU Chá"
                    # na 2a linha de BEBIDAS) também costuma estar mesclada;
                    # nos demais, limitada à região do dia para não colar
                    # texto de outro dia
                    cont = ""
                    for k2 in look:
                        if was_merged:
                            t = clean(merged_cell(list(rows[k2]),
                                                  tb_rows[k2] if k2 < len(tb_rows) else [],
                                                  vcol, j))
                        else:
                            t = region_text([rows[k2]], lo, end)
                        if t:
                            cont = f"{cont} {t}".strip()
                    if cont:
                        value = f"{value} / {cont}" if value else cont
                    if not value:
                        continue
                    entries = days.setdefault(iso, {}).setdefault(page_meal, [])
                    if not any(e["label"] == LABEL_PRETTY[label] for e in entries):
                        entries.append({"label": LABEL_PRETTY[label],
                                        "value": value})
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
    "Molhos": "Molho",
    "Pratos principais": "Prato Principal",
    "Guarnições": "Guarnição",
    "Acompanhamentos": "Acompanhamento",
    "Sobremesas": "Sobremesa",
}
EXEC_HEADER_TOP = 178   # palavras acima disso são cabeçalho/logo
EXEC_LINE_TOL = 3.0     # tolerância para agrupar palavras na mesma linha
EXEC_BLOCK_GAP = 4.5    # vão livre (pt) que, quando folgado, separa itens
EXEC_LINE_PITCH = 12.05 # pitch topo-a-topo dentro de UM mesmo item (grade)
EXEC_X_TOL = 2.0        # distância máx. (pt) entre letras da mesma palavra.
                        # O default do pdfplumber (3) cola palavras quando o
                        # texto vem em dois pedaços com pouco espaço entre
                        # eles ("quinoagratinado", "Semifredode", "Batonnetde")

# palavras/pontuação que fecham uma linha mas NÃO fecham o texto do item
EXEC_CONNECTORS = {"de", "da", "do", "das", "dos", "e", "ou", "com", "sem",
                   "ao", "aos", "à", "às", "em", "no", "na", "nos", "nas",
                   "para", "por", "tipo", "sabor", "c/", "s/"}
EXEC_TRAIL = "/,(-:;&"


def _cont_start(text):
    """True se a linha começa como continuação de texto: inicial
    minúscula, parêntese ou aspas (descrições de prato, quebras de frase)."""
    for ch in text:
        if ch.isspace():
            continue
        if ch.isalpha():
            return ch.islower()
        return ch in "(\"'"
    return False


def _unfinished(text):
    """True se a linha termina no meio do item: palavra de ligação no fim
    ("... legumes com", "Ganache de Café e") ou pontuação aberta ("/", "c/")."""
    t = (text or "").rstrip()
    if not t:
        return True
    if t[-1] in EXEC_TRAIL:
        return True
    return t.split()[-1].lower().strip(".,;:") in EXEC_CONNECTORS


def _tidy(text):
    """Conserta os espaços que a extração deixa fora de lugar em listas
    ("( maionese,penne", "milho ,Cebola")."""
    t = re.sub(r"\(\s+", "(", text)
    t = re.sub(r"\s+([,;:.])", r"\1", t)
    t = re.sub(r",(?=\S)", ", ", t)
    return re.sub(r"\s+", " ", t).strip()


def _group_exec_blocks(lines):
    """Agrupa as linhas visuais de uma coluna de data em blocos (itens).

    O espaçamento do PDF é manual: o vão livre entre duas linhas do MESMO
    item vai de ~-0.5 a ~3.4 pt, e entre itens distintos pode até ser
    negativo — nenhum limiar geométrico único separa os dois casos. Combina:
      - tamanho de fonte: linha de descrição (6/8pt) pertence ao item de
        cima; fim da descrição (6/8pt -> 10pt) abre item novo;
      - vão livre > EXEC_BLOCK_GAP ou pitch > EXEC_LINE_PITCH: item novo;
      - linha começando em minúscula/'(': continuação;
      - linha anterior terminando em palavra de ligação ou pontuação aberta
        ("... legumes com", "Chocolate c/"): continuação;
      - linha de uma só palavra ("Gratinado", "Cajá"): continuação do nome
        do prato, que o PDF quebrou em duas linhas;
      - caso contrário: item novo.

    A lista de molhos ("Molho vinagrete"/"Molho de pimenta") usa pitch
    idêntico ao das quebras de linha de um nome comprido ("Mousse de /
    Chocolate c/ / Ganache de Café e / Praliné Amendoim"), por isso o
    critério é o TEXTO da linha anterior, não a geometria.
    """
    n = len(lines)
    if n == 0:
        return []
    item = [ln["size"] >= 9.0 for ln in lines]  # 10pt = prato; 6/8pt = descrição
    trans = [None] * n
    for i in range(1, n):
        gap = lines[i]["top"] - lines[i - 1]["bottom"]
        pitch = lines[i]["top"] - lines[i - 1]["top"]
        if not item[i - 1] and not item[i]:
            trans[i] = "cont"            # duas linhas de descrição
        elif not item[i - 1]:
            trans[i] = "new"             # descrição terminou -> novo item
        elif not item[i]:
            # linha em fonte menor que a do item: quase sempre a descrição do
            # item de cima. Mas um item também pode vir em 8pt ("Salada de
            # batata bolinha"): aí o espaçamento é o de item novo, não o de
            # quebra de linha dentro do mesmo item.
            trans[i] = ("cont" if (_cont_start(lines[i]["text"])
                                   or not (gap > EXEC_BLOCK_GAP
                                           or pitch > EXEC_LINE_PITCH))
                        else "new")
        elif gap > EXEC_BLOCK_GAP or pitch > EXEC_LINE_PITCH:
            trans[i] = "new"
        elif _cont_start(lines[i]["text"]):
            trans[i] = "cont"
        elif _unfinished(lines[i - 1]["text"]):
            trans[i] = "cont"
        elif len(lines[i]["text"].split()) == 1:
            trans[i] = "cont"            # palavra solta: nome do prato partido
        else:
            trans[i] = "new"
    blocks, cur = [], [lines[0]]
    for i in range(1, n):
        if trans[i] == "new":
            blocks.append(cur)
            cur = []
        cur.append(lines[i])
    blocks.append(cur)
    # segurança: bloco que começa como continuação de texto pertence ao
    # bloco anterior (se escapou das regras acima)
    merged = []
    for b in blocks:
        if merged and _cont_start(b[0]["text"]):
            merged[-1].extend(b)
        else:
            merged.append(b)
    return merged


def parse_executivo_pdf(path):
    """Parser do formato Executivo: retorna {data_iso: [{'label','value'}]}."""
    out = {}
    with pdfplumber.open(path) as pdf:
        # datas/bordas de coluna vêm da primeira página (idênticas nas demais)
        p0 = pdf.pages[0]
        dw = [(w["text"], (w["x0"] + w["x1"]) / 2)
              for w in p0.extract_words(x_tolerance=EXEC_X_TOL)
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
            words = page.extract_words(x_tolerance=EXEC_X_TOL, extra_attrs=["size"])
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
                sorted_lines = []
                for key in sorted(lines):
                    lws = sorted(lines[key], key=lambda w: w["x0"])
                    sorted_lines.append({
                        "top": min(w["top"] for w in lws),
                        "bottom": max(w["bottom"] for w in lws),
                        "size": max(w["size"] for w in lws),
                        "text": re.sub(r"\s+", " ", " ".join(w["text"] for w in lws)).strip(),
                    })

                # agrupar linhas consecutivas em blocos (itens)
                for b in _group_exec_blocks(sorted_lines):
                    text = _tidy(" ".join(ln["text"] for ln in b)).strip(" ,;")
                    if len(text) < 2:
                        continue
                    out[isos[j]].append({"label": cat, "value": text})

        # numera itens repetidos do mesmo dia ("Salada 1", "Salada 2", ...)
        # e singulariza o rótulo; categoria com um item só fica no singular
        for iso, items in out.items():
            for it in items:
                # os molhos vêm na página de saladas: rótulo próprio evita
                # "Salada 7 | Molho vinagrete" no site
                if it["label"] == "Saladas" and \
                        it["value"].lower().startswith("molho"):
                    it["label"] = "Molhos"
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
def discover_pdfs(listings, pattern):
    """Agrega os PDFs de uma ou mais páginas de listagem (sem duplicar)."""
    if isinstance(listings, str):
        listings = [listings]
    links, seen = [], set()
    for listing_url in listings:
        try:
            req = Request(listing_url, headers={"User-Agent": UA})
            html = urlopen(req, timeout=30).read().decode("utf-8", "replace")
        except OSError as e:
            # uma listagem fora do ar não pode derrubar o campus inteiro
            # quando a outra listagem já devolveu os PDFs
            print(f"AVISO: falha ao abrir {listing_url}: {e}")
            continue
        # hrefs com aspas simples ou duplas e com query string (".pdf?ver=2")
        for q, u in re.findall(r'href=(["\'])([^"\']+\.pdf(?:\?[^"\']*)?)\1',
                               html, re.I):
            u = urljoin(listing_url, u.replace("http://", "https://"))
            if u not in seen:
                seen.add(u)
                links.append(u)
    return sorted(u for u in links if re.search(pattern, url_filename(u), re.I))


def range_of(url, today=None):
    """Intervalo de datas coberto pelo PDF, inferido do nome do arquivo.

    Formatos conhecidos:
      .../Darcy-Ribeiro-Semana-01-24-8-a-30-8.pdf  -> 24/8 a 30/8 (ano no path)
      .../Cardapio-24-8-2026-a-30-8-2026.pdf       -> idem, com ano explícito
      datas com barras também são aceitas (24/8/2026)

    No formato curto (sem ano nas datas), o ano vem do caminho/nome — mas a
    semana pode cruzar o fim do ano ("...-28-12-a-03-01"). Gera candidatos
    nos anos vizinhos e fica com o intervalo mais próximo da data de
    referência: um PDF de réveillon publicado em dezembro (/2026/12/) não
    pode virar (2026-01-03, 2026-12-28), nem cobrir 360 dias quando reenviado
    em janeiro (/2027/01/).

    A referência é o mês da pasta /uploads/AAAA/MM/ quando ela existe — o PDF
    é publicado para a semana em torno daquela data, não perto de hoje. Sem
    isso, um PDF de setembro de 2026 (/uploads/2026/09/) relido em junho de
    2027 seria projetado para setembro de 2027 e escolhido como "semana
    futura" por pick_current().
    """
    today = today or datetime.now(TZ_BSB).date()
    name = url_filename(url)
    # Sufixo de duplicidade do WordPress ("...-a-04-10-2.pdf", arquivo
    # reenviado): um número solto no fim, após a data de encerramento.
    # Descarta-o quando o restante fecha um par dia-mês válido — assim não
    # confunde com "18-19" (mês inválido, tratado adiante) nem com anos.
    tail = re.split(r"-a-", name, maxsplit=1, flags=re.I)[-1]
    nums = re.findall(r"\d+", tail)
    if len(nums) == 3 and int(nums[1]) <= 12 and int(nums[2]) <= 31:
        name = re.sub(r"-\d{1,2}\.pdf$", ".pdf", name, flags=re.I)
    # ano: procura /2026/ no caminho (padrão WordPress) ou 4 dígitos no nome
    year_match = re.search(r"/(20\d{2})/", url) or re.search(r"(20\d{2})", name)
    year = int(year_match.group(1)) if year_match else today.year

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
        parsed = []
        for d, m in pairs:
            if not (1 <= d <= 31 and 1 <= m <= 12):
                # mês impossível no nome (PDF vigente do executivo:
                # "SEMANA-04-14-09-A-18-19" -> fim é 18/09, não 18/19);
                # se só há um mês válido no intervalo, assume ele
                if m > 12 and len(valid_months) == 1:
                    m = next(iter(valid_months))
                else:
                    continue
            parsed.append((d, m))
        best = None
        # data de referência: o mês da pasta /uploads/AAAA/MM/ (o PDF é
        # publicado para a semana em torno dele) ou, sem pasta de upload,
        # o dia de hoje
        upload = re.search(r"/uploads/(20\d{2})/(\d{1,2})/", url)
        ref = (date(int(upload.group(1)), int(upload.group(2)), 15)
               if upload else today)
        for base in (year - 1, year, year + 1):
            cand, y, prev_m = [], base, None
            for d, m in parsed:
                if prev_m is not None and m < prev_m:
                    y += 1  # mês menor que o anterior: caiu no ano seguinte
                try:
                    cand.append(date(y, m, d))
                except ValueError:
                    pass
                prev_m = m
            if not cand:
                continue
            s, e = min(cand), max(cand)
            dist = (0 if s <= ref <= e
                    else min(abs((s - ref).days), abs((e - ref).days)))
            # empate (ex.: réveillon): fica com o intervalo mais recente
            key = (dist, -s.toordinal())
            if best is None or key < best[0]:
                best = (key, (s, e))
        if best:
            return best[1]
    return (min(ds), max(ds)) if ds else (None, None)


def _upload_recency(url):
    """Ordem de publicação do WordPress: pasta /uploads/AAAA/MM/ e sufixo
    de reenvio ("-2", "-3"...). Desempata PDFs com o mesmo intervalo de
    datas — entre reenvios, a versão mais nova é a que deve prevalecer,
    não a primeira em ordem ASCII."""
    m = re.search(r"/uploads/(\d{4})/(\d{1,2})/", url)
    y, mo = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    name = url_filename(url)
    ver = 0
    tail = re.split(r"-a-", name, maxsplit=1, flags=re.I)[-1]
    nums = re.findall(r"\d+", tail)
    if len(nums) == 3 and int(nums[1]) <= 12 and int(nums[2]) <= 31:
        v = re.search(r"-(\d{1,2})\.pdf$", name, re.I)
        if v:
            ver = int(v.group(1))
    return (y, mo, ver)


def pick_current(links, today=None, now=None):
    """Escolhe o PDF cujo intervalo de datas cobre o dia de referência.

    No domingo, o cardápio da semana atual (que inclui o próprio domingo)
    continua valendo até 19h30 — horário em que fecha a entrada do RU para
    o jantar. Depois disso o alvo passa a ser a segunda-feira seguinte: se
    a UnB já publicou o PDF da semana nova (costuma sair antes do domingo),
    ele entra no ar; caso contrário, mantém o da semana atual.

    Sem cobertura (virada de semana / PDF atrasado), prefere a semana futura
    mais próxima; se não houver, a mais recente já publicada — por data
    inferida, não por ordem alfabética ("Semana-10" ordena antes de
    "Semana-9"). Empates de intervalo (reenvios) ficam com a publicação
    mais recente.
    """
    now = now or datetime.now(TZ_BSB)
    today = today or now.date()
    alvo = today
    if today.weekday() == 6 and now.time() >= dtime(19, 30):
        alvo = today + timedelta(days=1)

    def covers(u, d):
        r = range_of(u, alvo)
        return r[0] is not None and r[0] <= d <= r[1]

    covering = [u for u in links if covers(u, alvo)]
    if covering:
        if alvo != today:
            print(f"Domingo: usando o PDF da semana seguinte (cobre {alvo})")
        return [max(covering, key=lambda u: (range_of(u, alvo)[1],
                                             _upload_recency(u), u))]
    if alvo != today:
        covering = [u for u in links if covers(u, today)]
        if covering:
            print("AVISO: PDF da semana seguinte ainda não publicado; "
                  "usando o da semana atual")
            return [max(covering, key=lambda u: (range_of(u, today)[1],
                                                 _upload_recency(u), u))]
    if not links:
        return []
    futuras = [u for u in links if range_of(u, alvo)[0] is not None
               and range_of(u, alvo)[1] >= alvo]
    if futuras:
        start0 = min(range_of(u, alvo)[0] for u in futuras)
        escolhido = max((u for u in futuras if range_of(u, alvo)[0] == start0),
                        key=lambda u: (_upload_recency(u), u))
        print(f"AVISO: nenhum PDF cobre {alvo}; "
              f"usando a semana futura mais próxima ({escolhido})")
        return [escolhido]
    latest = max(links, key=lambda u: (range_of(u, alvo)[0] or date.min,
                                       _upload_recency(u), u))
    print(f"AVISO: nenhum PDF cobre {alvo}; usando o mais recente ({latest})")
    return [latest]


def download(url, dest):
    req = Request(url, headers={"User-Agent": UA})
    dest.write_bytes(urlopen(req, timeout=60).read())
    return dest


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
JSON_CONTENT_KEYS = ("campus", "campus_name", "meals_order", "meals_names",
                     "sources", "days")


def write_campus_json(out, dest):
    """Grava o JSON do campus.

    Se o conteúdo (fora do generated_at) não mudou, o arquivo anterior fica
    intacto: o git não vê diferença e o cron deixa de commitar toda execução
    só por causa do timestamp — e o rodapé do site continua mostrando a data
    em que o cardápio realmente mudou.
    """
    if dest.exists():
        try:
            old = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            old = None
        if isinstance(old, dict) and all(old.get(k) == out[k]
                                         for k in JSON_CONTENT_KEYS):
            print(f"Conteúdo de {dest.name} inalterado — nada a gravar")
            return
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def week_has_items(week, executivo=False):
    """True se há pelo menos um dia com itens de verdade.

    Um PDF cujo cabeçalho foi lido mas nenhum prato extraído (quebra de
    layout, PDF em imagem) produz dias com listas vazias — publicá-los
    substituiria um JSON válido por um vazio.
    """
    if executivo:
        return any(items for items in week.values())
    return any(items for day in week.values() for items in day.values())


def process_campus(key, cfg, today=None):
    """Baixa o PDF vigente do campus e gera site/data/cardapio-<key>.json."""
    print(f"\n=== {key} ({cfg['name']}) ===")
    print("Descobrindo PDFs em", ", ".join(cfg["listings"]))
    links = discover_pdfs(cfg["listings"], cfg["pattern"])
    print(f"{len(links)} PDF(s):", *("  " + l for l in links), sep="\n")
    chosen = pick_current(links, today=today)
    if not chosen:
        raise RuntimeError(f"nenhum PDF encontrado em {cfg['listings']}")
    print("Usando:", chosen)

    sources, merged = [], {}
    for u in chosen:
        p = DATA_DIR / local_pdf_name(key, u)
        download(u, p)
        src = {"file": p.name, "url": u}

        if key == "executivo":
            week_flat = parse_executivo_pdf(p)
            print(f"{p.name}: {len(week_flat)} dia(s) extraído(s)")
            if not week_has_items(week_flat, executivo=True):
                raise RuntimeError(f"nada extraído de {p}")
            # formato plano -> uma única "refeição"
            week = {iso: {"principal": items} for iso, items in week_flat.items()}
        else:
            week = parse_table_pdf(p)
            print(f"{p.name}: {len(week)} dia(s) extraído(s)")
            if not week_has_items(week):
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
    write_campus_json(out, dest)
    print(f"OK -> {dest} ({len(out['days'])} dias)")
    return out


def main():
    DATA_DIR.mkdir(exist_ok=True)
    args = sys.argv[1:]
    keys = list(CAMPUS)

    if "--pdf" in args:
        # modo teste local: --pdf <campus> <arquivo.pdf>
        i = args.index("--pdf")
        if i + 2 >= len(args):
            sys.exit("Uso: --pdf <campus> <arquivo.pdf>")
        key, path = args[i + 1], Path(args[i + 2])
        if key not in CAMPUS:
            sys.exit(f"Campus desconhecido: {key}. Opções: {list(CAMPUS)}")
        if not path.exists():
            sys.exit(f"PDF não encontrado: {path}")
        cfg = CAMPUS[key]
        parser = parse_executivo_pdf if key == "executivo" else parse_table_pdf
        week = parser(path)
        if not week_has_items(week, executivo=(key == "executivo")):
            sys.exit(f"ERRO: nada extraído de {path} — JSON anterior mantido")
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
        write_campus_json(out, dest)
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
