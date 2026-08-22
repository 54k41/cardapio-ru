# UnBRU Clone — Cardápio RU Darcy Ribeiro (UnB)

Versão própria e funcional do site unbru.info (que está fora do ar — ver análise
abaixo), consumindo diretamente os PDFs oficiais de
[ru.unb.br/cardapio](https://ru.unb.br/cardapio/).

## Estrutura

```
unbru-clone/
├── scripts/
│   └── fetch_cardapio.py   # baixa PDFs oficiais → extrai → gera data/cardapio.json
├── site/                   # front-end estático (index.html + app.js + styles.css)
├── data/
│   ├── cardapio.json       # gerado pelo script
│   └── *.pdf               # PDFs baixados
├── build.py                # copia data/cardapio.json → site/data/
└── .venv/                  # virtualenv (pdfplumber)
```

## Uso rápido

```bash
# 1. ambiente (uma vez)
uv venv .venv && uv pip install --python .venv/Scripts/python.exe pdfplumber

# 2. atualizar o cardápio (descobre o PDF da semana atual sozinho)
.venv/Scripts/python.exe scripts/fetch_cardapio.py

# 3. publicar
.venv/Scripts/python.exe build.py

# 4. testar local
cd site && python -m http.server 8080
```

Também é possível converter PDFs locais:
`.venv/Scripts/python.exe scripts/fetch_cardapio.py caminho/arquivo.pdf`

## Automação (GitHub Actions)

`.github/workflows/update.yml` roda `fetch_cardapio.py` duas vezes por dia e
publica no GitHub Pages — o site se mantém sozinho.
