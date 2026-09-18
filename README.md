# UnB — Cardápio RU Darcy Ribeiro (UnB)

Versão simplificada e minimalista do cardápio do RU da UnB, utiliza os PDFs oficiais de
[ru.unb.br/cardapio](https://ru.unb.br/cardapio/).

## Estrutura

```
cardapio-ru/
├── scripts/
│   └── fetch_cardapio.py   # baixa PDFs oficiais → extrai → grava site/data/cardapio-<campus>.json
├── site/                   # front-end estático (index.html + app.js + styles.css)
│   └── data/               # JSONs gerados por campus (publicados no Pages)
├── data/                   # PDFs baixados (não versionado)
├── build.py                # valida os JSONs antes do deploy no Pages
└── .github/workflows/update.yml  # roda 2x/dia e publica no GitHub Pages
```

## Uso rápido

```bash
# 1. ambiente (uma vez)
uv venv .venv && uv pip install --python .venv/Scripts/python.exe pdfplumber

# 2. atualizar o cardápio (descobre o PDF da semana atual sozinho)
.venv/Scripts/python.exe scripts/fetch_cardapio.py                 # todos os campi
.venv/Scripts/python.exe scripts/fetch_cardapio.py darcy executivo # campi específicos

# 3. validar antes de publicar
.venv/Scripts/python.exe build.py

# 4. testar local
cd site && python -m http.server 8080
```

Também é possível converter PDFs locais:
`.venv/Scripts/python.exe scripts/fetch_cardapio.py --pdf darcy caminho/arquivo.pdf`

## Automação (GitHub Actions)

`.github/workflows/update.yml` roda `fetch_cardapio.py` duas vezes por dia,
commita os JSONs atualizados de volta no repositório (autor: `github-actions[bot]`)
e publica no GitHub Pages — o site se mantém sozinho. No domingo, se o PDF da
semana seguinte já foi publicado, o site já mostra a semana nova. Se um campus
falhar, os demais continuam sendo publicados; o campus com falha mantém o JSON
anterior (no repositório e no Pages) — nunca é gravado um arquivo vazio por cima.
