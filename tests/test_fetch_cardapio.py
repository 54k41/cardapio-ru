"""Testes das funções puras de scripts/fetch_cardapio.py.

Cobrem os pontos que já quebraram em produção (ou que quebrariam em silêncio):

  - range_of(): leitura do intervalo de datas a partir do nome do arquivo,
    incluindo reenvios, fim de ano e mês impossível ("18-19");
  - pick_current(): qual PDF está vigente, com a regra de domingo 19h30;
  - _group_exec_blocks(): agrupamento das linhas do Executivo, onde split e
    merge errados aparecem como "pratos partidos em dois itens";
  - _join_lines()/_trim_trailing_connector(): "integral Feijão carioca" e
    "couve- flor";
  - carry_over_days(): dias que o PDF novo não cobre mais.

As linhas usadas nos testes de agrupamento são (top, base e texto) copiadas
de PDFs reais do RU — é o que garante que o teste valha algo.
"""

from datetime import date, datetime

import pytest

import fetch_cardapio as fc

BSB = fc.TZ_BSB


# ---------------------------------------------------------------------------
# range_of
# ---------------------------------------------------------------------------
def test_range_of_dates_with_reupload_suffix():
    url = ("https://ru.unb.br/wp-content/uploads/2026/11/"
           "Darcy-Ribeiro-Semana-04-09-11-a-15-11-2.pdf")
    assert fc.range_of(url, today=date(2026, 11, 12)) == (
        date(2026, 11, 9), date(2026, 11, 15))


def test_range_of_short_range_of_the_executivo():
    url = ("https://ru.unb.br/wp-content/uploads/2026/11/"
           "SEMANA-01-16-11-a-19-11.pdf")
    assert fc.range_of(url, today=date(2026, 11, 12)) == (
        date(2026, 11, 16), date(2026, 11, 19))


def test_range_of_impossible_month_falls_back_to_the_only_valid_one():
    # "18-19" no fim: o mês 19 não existe, o intervalo é 14/9 a 18/9
    url = ("https://ru.unb.br/wp-content/uploads/2026/11/"
           "SEMANA-04-14-09-A-18-19.pdf")
    assert fc.range_of(url, today=date(2026, 11, 12)) == (
        date(2026, 9, 14), date(2026, 9, 18))


def test_range_of_full_dates_in_the_name():
    url = ("https://ru.unb.br/wp-content/uploads/2026/09/"
           "Cardapio-14-9-2026-a-20-9-2026.pdf")
    assert fc.range_of(url, today=date(2026, 11, 12)) == (
        date(2026, 9, 14), date(2026, 9, 20))


def test_range_of_week_crossing_new_year_stays_short():
    url = ("https://ru.unb.br/wp-content/uploads/2026/12/"
           "Cardapio-28-12-a-03-01.pdf")
    assert fc.range_of(url, today=date(2026, 12, 20)) == (
        date(2026, 12, 28), date(2027, 1, 3))


def test_range_of_reuploaded_in_january_does_not_cover_the_whole_year():
    url = ("https://ru.unb.br/wp-content/uploads/2027/01/"
           "Cardapio-28-12-a-03-01.pdf")
    start, end = fc.range_of(url, today=date(2027, 1, 5))
    assert (end - start).days < 10


def test_range_of_without_dates_returns_none():
    assert fc.range_of("https://ru.unb.br/wp-content/uploads/2026/11/x.pdf",
                       today=date(2026, 11, 12)) == (None, None)


# ---------------------------------------------------------------------------
# pick_current
# ---------------------------------------------------------------------------
SEM04 = ("https://ru.unb.br/wp-content/uploads/2026/11/"
         "Semana-04-09-11-a-15-11.pdf")
SEM05 = ("https://ru.unb.br/wp-content/uploads/2026/11/"
         "Semana-05-16-11-a-22-11.pdf")


def test_pick_current_prefers_the_pdf_covering_today():
    today = date(2026, 11, 12)          # quarta-feira
    assert fc.pick_current([SEM04, SEM05], today=today) == [SEM04]


def test_pick_current_on_sunday_before_closing_time_keeps_the_week():
    now = datetime(2026, 11, 15, 18, 0, tzinfo=BSB)
    assert fc.pick_current([SEM04, SEM05], today=now.date(), now=now) == [SEM04]


def test_pick_current_on_sunday_after_1930_switches_to_next_week():
    now = datetime(2026, 11, 15, 20, 0, tzinfo=BSB)
    assert fc.pick_current([SEM04, SEM05], today=now.date(), now=now) == [SEM05]


def test_pick_current_keeps_current_week_when_next_is_not_published():
    now = datetime(2026, 11, 15, 20, 0, tzinfo=BSB)
    assert fc.pick_current([SEM04], today=now.date(), now=now) == [SEM04]


def test_pick_current_falls_back_to_nearest_future_week():
    # 12/11 e a listagem só tem a semana de 16/11 (caso real do Executivo)
    today = date(2026, 11, 12)
    assert fc.pick_current([SEM05], today=today) == [SEM05]


def test_pick_current_falls_back_to_the_most_recent_past_week():
    antiga = ("https://ru.unb.br/wp-content/uploads/2026/10/"
              "Semana-03-02-11-a-08-11.pdf")
    assert fc.pick_current([antiga], today=date(2026, 11, 12)) == [antiga]


def test_pick_current_breaks_ties_by_upload_month():
    velho = ("https://ru.unb.br/wp-content/uploads/2026/10/"
             "Semana-04-09-11-a-15-11.pdf")
    novo = ("https://ru.unb.br/wp-content/uploads/2026/11/"
            "Semana-04-09-11-a-15-11.pdf")
    assert fc.pick_current([velho, novo], today=date(2026, 11, 12)) == [novo]


def test_pick_current_without_links_returns_empty():
    assert fc.pick_current([], today=date(2026, 11, 12)) == []


# ---------------------------------------------------------------------------
# Agrupamento das linhas do Executivo
# ---------------------------------------------------------------------------
def _lines(rows):
    """rows: (texto, top, bottom[, size[, base]]).

    `base` é a linha de base em coordenada de PDF: cresce para CIMA, então o
    padrão é -top (as linhas descem, a base diminui).
    """
    out = []
    for row in rows:
        text, top, bottom = row[0], row[1], row[2]
        size = row[3] if len(row) > 3 else 10.0
        base = row[4] if len(row) > 4 else -top
        out.append({"text": text, "top": top, "bottom": bottom,
                    "size": size, "base": base})
    return out


def _blocks(rows):
    return [fc._tidy(" ".join(ln["text"] for ln in b))
            for b in fc._group_exec_blocks(rows)]


def test_group_exec_keeps_the_molho_list_and_joins_broken_names():
    # coluna de saladas de 16/11 (Executivo): "Ervas" tem pitch irregular e a
    # lista de molhos usa a mesma entrelinha das quebras de linha
    rows = _lines([
        ("Alface crespa", 199.13, 209.12, 10.0, 198.62),
        ("Repolho roxo com", 219.69, 229.65, 10.0, 178.08),
        ("gergelim branco", 231.69, 241.65, 10.0, 166.08),
        ("Abobrinha ralada", 259.51, 269.47, 10.0, 138.26),
        ("Pétalas de", 273.64, 283.60, 10.0, 124.13),
        ("Tomate e", 285.64, 295.60, 10.0, 114.02),
        ("Brócoliss com", 297.64, 307.60, 10.0, 103.25),
        ("Ervas", 309.64, 319.60, 10.0, 88.13),
        ("Salpicão de frango", 319.75, 329.74, 10.0, 78.00),
        ("Tomate fatiado", 331.53, 341.49, 10.0, 66.24),
        ("Molho de pimenta", 344.03, 353.99, 10.0, 53.74),
        ("Molho vinagrete", 356.03, 365.99, 10.0, 41.74),
        ("Molho chipotle", 368.03, 377.99, 10.0, 29.74),
    ])
    assert _blocks(rows) == [
        "Alface crespa",
        "Repolho roxo com gergelim branco",
        "Abobrinha ralada",
        "Pétalas de Tomate e Brócoliss com Ervas",
        "Salpicão de frango",
        "Tomate fatiado",
        "Molho de pimenta",
        "Molho vinagrete",
        "Molho chipotle",
    ]


def test_group_exec_merges_line_without_respiro():
    # "Coxa e Sobrecoxa" + "Desossada na Manteiga de Ervas" são UM prato: o
    # PDF digitou as três linhas sem respiro (pitch igual à entrelinha)
    rows = _lines([
        ("Cupim Laqueado", 199.90, 209.85),
        ("Coxa e Sobrecoxa", 219.60, 229.60),
        ("Desossada na Manteiga", 231.60, 241.60),
        ("de Ervas", 243.60, 253.60),
        ("Filé de Peixe ao", 266.80, 276.81),
        ("Molho de Castanha", 278.80, 288.81),
        ("Frango grelhado", 297.50, 307.51),
        ("Bife de soja ao", 320.10, 330.07),
        ("sugo", 332.10, 342.07),
        ("Soja xadrez", 358.10, 368.06),
    ])
    assert _blocks(rows) == [
        "Cupim Laqueado",
        "Coxa e Sobrecoxa Desossada na Manteiga de Ervas",
        "Filé de Peixe ao Molho de Castanha",
        "Frango grelhado",
        "Bife de soja ao sugo",
        "Soja xadrez",
    ]


def test_group_exec_merges_dish_whose_connector_lost_a_letter():
    # no PDF de 16/11 o "a" de "ao" simplesmente não está no texto: a linha
    # termina em "o" e o prato aparecia partido em dois itens
    assert fc._unfinished("Filé de Frango o") is True
    rows = _lines([
        ("Rocambole", 193.15, 203.11),
        ("Recheado", 205.17, 215.13),
        ("Filé de Frango o", 224.44, 234.40),
        ("Molho de Mostarda", 236.44, 246.40),
        ("Costelinha ao", 256.34, 266.30),
        ("molho Barbecue", 268.32, 278.31),
    ])
    assert _blocks(rows) == [
        "Rocambole Recheado",
        "Filé de Frango o Molho de Mostarda",
        "Costelinha ao molho Barbecue",
    ]


def test_group_exec_keeps_items_that_only_look_like_continuation():
    # "Tabule" e "Banoffe" são palavras soltas, mas estão separadas por um
    # respiro grande: precisam continuar sendo itens próprios
    rows = _lines([
        ("Beterraba com", 254.23, 264.19),
        ("milho", 266.23, 276.19),
        ("Tabule", 295.60, 305.56),
        ("Salpicão de frango", 314.08, 324.04),
        ("Pavê de BIS", 227.37, 237.33),
        ("Banoffe", 263.04, 273.03),
    ])
    assert _blocks(rows) == [
        "Beterraba com milho",
        "Tabule",
        "Salpicão de frango",
        "Pavê de BIS",
        "Banoffe",
    ]


def test_group_exec_attaches_description_lines_to_the_item_above():
    rows = _lines([
        ("Picles de pepino", 264.52, 274.48),
        ("Salada Mexicana", 283.75, 293.71),
        ("(Abacate, Tomate Cereja, Milho ,Cebola", 297.39, 303.39, 6.0),
        ("Roxa, Salsinha)", 304.60, 310.60, 6.0),
        ("Salpicão de frango", 316.46, 326.42),
    ])
    assert _blocks(rows) == [
        "Picles de pepino",
        "Salada Mexicana (Abacate, Tomate Cereja, Milho, Cebola Roxa, Salsinha)",
        "Salpicão de frango",
    ]


def test_group_exec_with_empty_input():
    assert fc._group_exec_blocks([]) == []


def test_block_leading_measures_the_column_instead_of_assuming():
    rows = _lines([
        ("a", 100.0, 110.0),
        ("b", 111.0, 121.0),
        ("c", 122.0, 132.0),
        ("d", 145.0, 155.0),
    ])
    assert fc._block_leading(rows) == pytest.approx(11.0, abs=0.01)


# ---------------------------------------------------------------------------
# Junção de linhas e limpeza de valores
# ---------------------------------------------------------------------------
def test_join_lines_keeps_hyphenated_word_together():
    assert fc._join_lines("Maionese de couve-\nflor") == "Maionese de couve-flor"


def test_join_lines_separates_listed_items():
    # era "Arroz branco e integral Feijão carioca"
    assert fc._join_lines("Arroz branco e\nintegral\nFeijão carioca") == \
        "Arroz branco e integral / Feijão carioca"


def test_join_lines_keeps_continuations_with_a_space():
    assert fc._join_lines("Lasanha de frango") == "Lasanha de frango"
    assert fc._join_lines("Berinjela recheada com\nquinoa gratinada") == \
        "Berinjela recheada com quinoa gratinada"
    assert fc._join_lines("Pão francês ou\nPão careca ou\nPão integral") == \
        "Pão francês ou Pão careca ou Pão integral"


def test_trim_trailing_connector():
    assert fc._trim_trailing_connector("Pão francês ou Pão careca ou") == \
        "Pão francês ou Pão careca"
    # não mexe em valor curto nem em palavra que fecha a frase
    assert fc._trim_trailing_connector("Carne ao molho de vinho") == \
        "Carne ao molho de vinho"
    assert fc._trim_trailing_connector("Torrada") == "Torrada"


def test_match_label_tolerates_broken_label():
    assert fc.match_label("PRATO PRINCIPAL\nOVOLACTOVEGETARIAN\nO") == \
        "PRATO PRINCIPAL OVOLACTOVEGETARIANO"
    assert fc.match_label("COMPOSIÇÃO") is None


# ---------------------------------------------------------------------------
# Herança de dias do JSON anterior
# ---------------------------------------------------------------------------
def test_carry_over_days_keeps_the_current_week():
    week = {"2026-11-16": {"principal": [{"label": "Salada", "value": "Alface"}]}}
    previous = {
        "2026-11-05": {"principal": [{"label": "Salada", "value": "Velha"}]},
        "2026-11-12": {"principal": [{"label": "Salada", "value": "Alface roxa"}]},
        "2026-11-13": {"principal": [{"label": "Salada", "value": "Tomate"}]},
    }
    merged, kept = fc.carry_over_days(week, previous, date(2026, 11, 12))
    assert kept == ["2026-11-12", "2026-11-13"]
    assert sorted(merged) == ["2026-11-12", "2026-11-13", "2026-11-16"]


def test_carry_over_days_never_overrides_fresh_data():
    week = {"2026-11-12": {"principal": [{"label": "Salada", "value": "Nova"}]}}
    previous = {"2026-11-12": {"principal": [{"label": "Salada", "value": "Antiga"}]}}
    merged, kept = fc.carry_over_days(week, previous, date(2026, 11, 12))
    assert kept == []
    assert merged["2026-11-12"]["principal"][0]["value"] == "Nova"


def test_carry_over_days_does_not_override_holiday():
    week = {"2026-11-20": {"principal": [], "note": "Feriado"}}
    previous = {"2026-11-20": {"principal": [{"label": "Prato", "value": "X"}]}}
    merged, kept = fc.carry_over_days(week, previous, date(2026, 11, 12))
    assert kept == []
    assert merged["2026-11-20"]["note"] == "Feriado"


def test_carry_over_days_tolerates_missing_previous():
    week = {"2026-11-16": {"principal": []}}
    assert fc.carry_over_days(week, None, date(2026, 11, 12)) == (week, [])


# ---------------------------------------------------------------------------
# Validações de conteúdo
# ---------------------------------------------------------------------------
def test_week_has_items_ignores_empty_days():
    assert fc.week_has_items({"2026-11-20": []}, executivo=True) is False
    assert fc.week_has_items({"2026-11-20": [{"label": "x", "value": "y"}]},
                             executivo=True) is True
    assert fc.week_has_items({"2026-11-20": {"almoco": []}}) is False


def test_day_items_ignores_note_key():
    day = {"principal": [{"label": "x", "value": "y"}], "note": "Feriado"}
    assert len(fc.day_items(day)) == 1
