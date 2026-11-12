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

- **Editorial UnB (Opção A):** superfície contínua, fio de 1px e acento azul — sem gradientes, sombras ou sobreposição de cartões, e sem emojis (que mudam de forma em cada sistema). Os **7 dias cabem numa linha** de 390 px, sem rolagem lateral, e a refeição inteira cabe na primeira dobra do celular.
- **Seleção de dieta (`Padrão · Ovolacto · Estrito`):** filtra as variantes de prato principal e de complemento publicadas nos PDFs. A preferência fica salva e o seletor some nos campi que publicam um cardápio único (Executivo).
- **Itens burocráticos agrupados:** saladas + molhos, sobremesa + refresco e sopa + torrada viram linhas corridas; o prato principal fica como manchete tipográfica.
- **Consulta rápida:** abre na refeição provável pelo horário de Brasília (café, almoço ou jantar), lembra o último campus, mantém os campi já visitados em memória para troca instantânea e mostra um seletor de semana quando o JSON cobre duas semanas.
- **Extração tolerante a variações de PDF:**
  - *Parser tabelado* para os campi (Darcy, FCTS, FCTE, FUP e FAL), tratando cabeçalhos divididos, colunas deslocadas, células mescladas e valores quebrados em várias linhas (com hifenização e itens listados na mesma célula resolvidos).
  - *Parser espacial* para o Restaurante Executivo (PDF sem grade, organizado por páginas de categoria e colunas de data), que mede a entrelinha de cada coluna para não partir um prato em dois itens.
  - Dias de **FERIADO** no Executivo deixam de virar cinco itens com o texto "FERIADO": o dia aparece com o aviso certo.
- **Descoberta automática da semana vigente:** identifica o PDF correto mesmo com variações de nomenclatura, sufixos de reenvio no WordPress ou pequenos erros de data no nome do arquivo, mantendo link direto para o PDF oficial no rodapé.
- **Semana que muda no meio do caminho:** quando a UnB troca o PDF e some com o da semana em curso (acontece no Executivo), os dias ainda vigentes do JSON anterior são preservados em vez de desaparecerem.
- **Offline e tolerância a falhas:** service worker com *network-first* para os dados e *cache-first* para os estáticos, além do último JSON de cada campus no `localStorage` — funciona no subsolo do ICC/Minhocão. O banner avisa quando os dados são salvos ou de uma semana anterior.
- **Modo escuro e acessibilidade:** `prefers-color-scheme`, `prefers-reduced-motion`, foco visível, abas com semântica ARIA e navegação por setas/Home/End. A fonte Lexend (variável `.woff2`, licença OFL) é auto-hospedada: nenhuma requisição a terceiros.

---

## Estrutura do projeto

```text
cardapio-ru/
├── scripts/
│   └── fetch_cardapio.py         # Descobre e baixa os PDFs oficiais → extrai → gera JSON por campus
├── tests/
│   └── test_fetch_cardapio.py    # Testes das funções puras (datas, escolha do PDF, agrupamento)
├── site/                         # Front-end estático publicado no GitHub Pages
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── sw.js                     # Service worker (offline)
│   ├── fonts/                    # Lexend variável self-hosted + licença OFL
│   └── data/                     # cardapio-<campus>.json versionados e servidos pelo site
├── data/                         # Cache temporário dos PDFs baixados (ignorado pelo Git)
├── build.py                      # Valida os JSONs gerados antes do deploy
├── pyproject.toml                # Metadados + configuração do pytest
├── requirements.txt              # Dependências fixadas (pdfplumber)
└── .github/workflows/update.yml  # Coleta agendada, commit automático e deploy no Pages
```

---

## Como rodar localmente

Requer **Python 3.10+** (recomendado usar [`uv`](https://docs.astral.sh/uv/), mas `pip`/`venv` padrão também funcionam).

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
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python scripts/fetch_cardapio.py
.venv/bin/python build.py
.venv/bin/python -m pytest

# Windows (PowerShell):
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python scripts/fetch_cardapio.py
.venv\Scripts\python build.py
.venv\Scripts\python -m pytest
```

### Testar com um PDF local

Para validar a extração de um arquivo específico sem consultar o site do RU:

```bash
uv run --with pdfplumber python scripts/fetch_cardapio.py --pdf darcy caminho/para/arquivo.pdf
```

### Testes

Os testes cobrem as três peças que já quebraram em produção: `range_of()` e `pick_current()` (qual PDF vale hoje), `_group_exec_blocks()` (o que é um prato e o que é a continuação de um prato) e a limpeza de valores (`integral Feijão`, `couve- flor`). Rodam sem rede e sem PDF, a partir de linhas reais copiadas dos arquivos da UnB:

```bash
python -m pytest
```

---

## Automação (GitHub Actions)

O workflow [`.github/workflows/update.yml`](.github/workflows/update.yml) mantém o site atualizado sozinho, sem necessidade de servidor próprio:

- **Diariamente às 06h00 e às 12h00 (horário de Brasília):** verifica atualizações ou retificações nos PDFs da semana.
- **Domingos às 20h00 (horário de Brasília):** faz a virada automática para o cardápio da semana seguinte logo após as 19h30 (fechamento da entrada do jantar de domingo no RU).
- **Não raspa o ru.unb.br à toa:** um push que mexe **só em `site/**`** valida os JSONs e publica, sem re-raspar os PDFs; o cron só publica quando a coleta realmente trouxe dado novo — nada de deploy vazio.
- **Proteção contra dados vazios:** se a coleta de um campus falhar, os demais continuam sendo atualizados normalmente e o campus com erro preserva o último JSON válido. O `build.py` impede que arquivos vazios ou corrompidos sobrescrevam a versão publicada.
- **Dias que sobrevivem à troca de PDF:** o extrator herda do JSON anterior os dias da semana corrente que o PDF novo não traz mais (a UnB às vezes remove o arquivo da semana em curso).
- **Commit só quando o cardápio muda:** o extrator preserva o `generated_at` quando o conteúdo é idêntico, então o cron não gera commits que apenas alterariam o horário.
- **Testes antes da coleta:** `python -m pytest` roda com as dependências fixadas em [`requirements.txt`](requirements.txt) antes de qualquer scraping.

---

## Licença

Distribuído sob a licença [MIT](LICENSE).

---

## Aviso legal

Projeto independente, sem vínculo oficial com a Universidade de Brasília. Os cardápios estão sujeitos a alterações sem aviso prévio — em caso de dúvida, consulte sempre o link do **PDF oficial** no topo da página ou [ru.unb.br/cardapio](https://ru.unb.br/cardapio/).
