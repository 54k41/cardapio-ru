# Cardápio RU — UnB

Interface web rápida, responsiva e minimalista para consultar o cardápio semanal dos Restaurantes Universitários da **Universidade de Brasília (UnB)**, alimentada automaticamente a partir dos PDFs oficiais publicados em [ru.unb.br](https://ru.unb.br/cardapio/).

🔗 **Acesse:** [unbru.loc.cc](http://unbru.loc.cc/)

---

## Unidades suportadas

É possível alternar pelo seletor no topo da página ou acessar qualquer unidade diretamente pela URL:

| Unidade | Código / Hash | Refeições exibidas |
| :--- | :--- | :--- |
| **Darcy Ribeiro** | [`#darcy`](http://unbru.loc.cc/#darcy) | Café da manhã, Almoço e Jantar |
| **Restaurante Executivo** | [`#executivo`](http://unbru.loc.cc/#executivo) | Cardápio executivo (Almoço) |
| **Ceilândia (FCTS)** | [`#fcts`](http://unbru.loc.cc/#fcts) | Café da manhã, Almoço e Jantar |
| **Gama (FCTE)** | [`#fcte`](http://unbru.loc.cc/#fcte) | Café da manhã, Almoço e Jantar |
| **Planaltina (FUP)** | [`#fup`](http://unbru.loc.cc/#fup) | Café da manhã, Almoço e Jantar |
| **Fazenda Água Limpa (FAL)** | [`#fal`](http://unbru.loc.cc/#fal) | Café da manhã e Almoço |

> As abas de refeição se ajustam automaticamente ao que existe em cada unidade e dia da semana (por exemplo, sábados sem jantar ou unidades sem turno noturno).

---

## Destaques

- **Leitura rápida no celular:** layout leve em HTML, CSS e JS puros, sem frameworks, abrindo direto no dia atual pelo fuso de Brasília (`UTC-3`).
- **Extração tolerante a variações de PDF:**
  - *Parser tabelado* para os campi (Darcy, FCTS, FCTE, FUP e FAL), tratando cabeçalhos divididos, colunas deslocadas e células quebradas em múltiplas linhas.
  - *Parser espacial* para o Restaurante Executivo (PDF sem grade, organizado por páginas de categoria e colunas de data).
- **Descoberta automática da semana vigente:** identifica o PDF correto mesmo com variações de nomenclatura, sufixos de reenvio no WordPress ou pequenos erros de data no nome do arquivo, mantendo link direto para o PDF oficial no topo do site.
- **Funcionamento offline e tolerância a falhas:** salva a última versão carregada de cada campus no `localStorage` e avisa visualmente caso exiba dados em cache ou de semana anterior.

---

## Estrutura do projeto

```text
cardapio-ru/
├── scripts/
│   └── fetch_cardapio.py         # Descobre e baixa os PDFs oficiais → extrai → gera JSON por campus
├── site/                         # Front-end estático publicado no GitHub Pages
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   └── data/                     # cardapio-<campus>.json versionados e servidos pelo site
├── data/                         # Cache temporário dos PDFs baixados (ignorado pelo Git)
├── build.py                      # Valida os JSONs gerados antes do deploy
└── .github/workflows/update.yml  # Coleta agendada, commit automático e deploy no Pages
```

---

## Como rodar localmente

Requer **Python 3.12+** (recomendado usar [`uv`](https://docs.astral.sh/uv/), mas `pip`/`venv` padrão também funcionam).

### Usando `uv`

```bash
# 1. Atualizar todos os campi (baixa os PDFs vigentes automaticamente)
uv run --with pdfplumber python scripts/fetch_cardapio.py

# Ou atualizar apenas unidades específicas
uv run --with pdfplumber python scripts/fetch_cardapio.py darcy executivo

# 2. Validar os JSONs gerados em site/data/
uv run python build.py

# 3. Servir o site localmente em http://localhost:8080
python -m http.server 8080 --directory site
```

### Usando ambiente virtual (`.venv`)

```bash
python -m venv .venv
# Linux / macOS:
.venv/bin/pip install pdfplumber
.venv/bin/python scripts/fetch_cardapio.py
.venv/bin/python build.py

# Windows (PowerShell):
.venv\Scripts\pip install pdfplumber
.venv\Scripts\python scripts/fetch_cardapio.py
.venv\Scripts\python build.py
```

### Testar com um PDF local

Para validar a extração de um arquivo específico sem consultar o site do RU:

```bash
uv run --with pdfplumber python scripts/fetch_cardapio.py --pdf darcy caminho/para/arquivo.pdf
```

---

## Automação (GitHub Actions)

O workflow [`.github/workflows/update.yml`](.github/workflows/update.yml) mantém o site atualizado sozinho, sem necessidade de servidor próprio:

- **Diariamente às 06h00 e às 12h00 (horário de Brasília):** verifica atualizações ou retificações nos PDFs da semana.
- **Domingos às 20h00 (horário de Brasília):** faz a virada automática para o cardápio da semana seguinte logo após as 19h30 (fechamento da entrada do jantar de domingo no RU).
- **Proteção contra dados vazios:** se a coleta de um campus falhar, os demais continuam sendo atualizados normalmente e o campus com erro preserva o último JSON válido. O `build.py` impede que arquivos vazios ou corrompidos sobrescrevam a versão publicada.
- **Commit só quando o cardápio muda:** o extrator preserva o `generated_at` quando o conteúdo é idêntico, então o cron não gera commits que apenas alterariam o horário.

---

## Licença

Distribuído sob a licença [MIT](LICENSE).

---

## Aviso legal

Projeto independente, sem vínculo oficial com a Universidade de Brasília. Os cardápios estão sujeitos a alterações sem aviso prévio — em caso de dúvida, consulte sempre o link do **PDF oficial** no topo da página ou [ru.unb.br/cardapio](https://ru.unb.br/cardapio/).
