# Regulatory Pipeline — Marmec

Pipeline automatizado de monitoramento regulatório marítimo para a **Marmec** (engenharia, consultoria e treinamento — controle regulatório em Brasil e Panamá).

Análise sob demanda de links regulatórios (colar URL + período) → Extração de texto → Análise via LLM → Dashboard de validação humana.

---

## Visão Geral

O sistema monitora automaticamente fontes regulatórias internacionais de embarcações e tubulações submarinas, baixa documentos novos, envia para análise via Inteligência Artificial, e apresenta os resultados em um dashboard para que especialistas validem e tomem ação.

**Fluxo completo:**

```
Link colado + período → Crawler → Download → Queue → LLM → Normalização → Dashboard
   (Nova Análise)   (Playwright) (PDF/HTML) (.jsonl) (Gemini/NVIDIA) (Pydantic)  (Validação)
```

---

## Arquitetura

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   CRAWLER    │───>│  PROCESSOR   │───>│     API      │───>│  DASHBOARD   │
│  (Playwright)│    │    (LLM)     │    │  (FastAPI)   │    │ (Bootstrap)  │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
        │                   │                   │                   │
        v                   v                   v                   v
   data/queue.jsonl    LLM Providers      SQLite / PostgreSQL    Chart.js
```

| Camada | Tecnologia | Função |
|---|---|---|
| Crawler | Playwright + BeautifulSoup | Acessar e baixar documentos |
| Processor | Gemini / NVIDIA | Analisar documentos com IA |
| API | FastAPI + SQLAlchemy | Servir dados e controlar pipeline |
| Dashboard | Bootstrap 5 + Chart.js + HTMX + SSE | Visualizar e validar análises |
| DB | PostgreSQL 16 (ou SQLite automático) | Armazenar resultados |
| Observabilidade | OpenTelemetry | Rastrear requisições |

---

## Pré-requisitos

- Python 3.12+
- pip
- Git

### Opcional (produção)

- PostgreSQL 16 (local ou via Docker)
- Docker + Docker Compose

---

## Instalação e Execução

### Início rápido (1 clique — recomendado)

```bash
# Windows — duplo-clique em:
start.bat

# Linux / macOS:
./start.sh
```

Na **primeira execução** o script roda o setup automaticamente (virtualenv,
dependências, Chromium, `secrets.env`) e depois sobe o servidor em
`http://127.0.0.1:8000`, abrindo o navegador sozinho. Nas execuções seguintes,
só inicia o servidor.

### Somente setup (manual)

```bash
# Windows:
setup.bat

# Linux / macOS:
chmod +x setup.sh && ./setup.sh
```

### O que o setup faz automaticamente

1. Cria virtualenv em `.venv/`
2. Instala todas as dependências (`requirements.txt`)
3. Instala o Chromium do Playwright
4. Copia `config/secrets.env.example` → `config/secrets.env`

### Manual (passo a passo)

```bash
# 1. Clonar o repositório
git clone <repo-url>
cd regulatory-pipeline

# 2. Criar e ativar virtualenv
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Instalar Chromium do Playwright
playwright install chromium

# 5. Configurar credenciais
cp config/secrets.env.example config/secrets.env
# Editar config/secrets.env (ver seção Configuração)

# 6. Rodar testes para verificar
python -m pytest tests/ -v

# 7. Iniciar o servidor
python -m uvicorn api.main:app --port 8000 --reload

# 8. Abrir no navegador
# http://127.0.0.1:8000
```

---

## Configuração

### Banco de Dados

#### SQLite (padrão — para desenvolvimento)

Não precisa de configuração. O sistema cria automaticamente em `data/regulatory.db`.

#### Estrutura da pasta `data/`

```
data/
├── downloads/          ← PDFs/HTML baixados com nome legível
│   └── <fonte>/        ← VOCÊ PODE APAGAR À VONTADE (ou pelo botão em Configurações)
├── regulatory.db       ← banco de dados (NÃO apagar)
├── queue.jsonl         ← fila de processamento
├── logs/               ← notificações
└── backup_*.json       ← backups
```

Os downloads são gravados como `data/downloads/<fonte>/<Título do documento> [hash8].pdf`
(nomes inválidos removidos, máx. 80 caracteres). O texto é extraído na hora do
processamento — apagar os arquivos depois não afeta nada, a análise já fica no banco.

#### PostgreSQL (produção)

1. Criar banco e usuário:

```sql
CREATE USER regulatory WITH PASSWORD 'sua_senha';
CREATE DATABASE regulatory OWNER regulatory;
```

2. Configurar em `config/secrets.env`:

```env
DATABASE_URL=postgresql+psycopg2://regulatory:sua_senha@localhost:5432/regulatory
```

> Se `DATABASE_URL` não estiver configurado ou PostgreSQL estiver indisponível, o projeto usa **SQLite automaticamente**.

---

### Provedores LLM

O sistema usa **Google Gemini** e **NVIDIA NIM** (ambos gratuitos). Configure **pelo menos um** para usar o pipeline.

#### Google Gemini (recomendado)

1. Acesse https://aistudio.google.com
2. Vá em **Get API Key**
3. Copie a chave
4. Em `config/secrets.env`:

```env
GOOGLE_API_KEY=sua_chave_aqui
```

5. No dashboard, vá em **Configurações** e cole a chave
6. Vá em **Provedores IA** e clique em **Ativar** no Gemini

#### NVIDIA NIM (gratuito)

1. Acesse https://build.nvidia.com
2. Crie uma conta
3. Vá em **API** → **Generate API Key**
4. Copie a chave (começa com `nvapi-`)
5. Em `config/secrets.env`:

```env
NVIDIA_API_KEY=nvapi-sua_chave_aqui
```

#### Configurar provedor ativo

Em `config/llm.yaml`:

```yaml
active: gemini                  # Provedor ativo
fallback_chain:                 # Ordem de fallback
  - gemini
  - nvidia
```

Ou pelo dashboard: **Provedores IA** → clique em **Ativar** no provedor desejado.

---

### Fontes (busca por link)

Não há fontes fixas: você cola qualquer página de normas em **Nova Análise**
e o sistema extrai os links daquela página. O campo **Fonte** de cada
documento passa a ser o domínio analisado (ex.: `iacs.org.uk`, `mte` para
registros antigos).

Funciona com páginas genéricas de listagem (IACS, IMCA, MTE, Panama, DPC,
portais de circulares, etc.). O filtro de período (de/até) é aplicado
**antes** da análise com IA: links com data visível fora do período são
descartados; links sem data visível entram mesmo assim (a página não mostra
a data — o log informa quantos foram mantidos por esse motivo).

#### IMODOCS (login automático)

Se o link colado for de `docs.imo.org`, o sistema faz login automaticamente
com as credenciais em `config/secrets.env`:

```env
IMODOCS_USER=seu_usuario
IMODOCS_PASSWORD=sua_senha
```

> O IMODOCS requer uma assinatura válida da IMO.

---

## Uso

### 1. Iniciar o servidor

```bash
python -m uvicorn api.main:app --port 8000 --reload
```

### 2. Acessar o Dashboard

Abra o navegador em: **http://127.0.0.1:8000**

### 3. Configurar provedor de IA

1. Clique em **Configurações** no menu lateral
2. Cole a chave de API do provedor escolhido (ex: Gemini)
3. Clique em **Salvar Chaves**
4. Clique em **Provedores IA** no menu lateral
5. Clique em **Ativar** no provedor desejado

### 4. Analisar um link

**Pelo Dashboard:**
1. Clique em **Nova Análise** no menu lateral
2. Cole o link da página com normas (ex.: `https://www.iacs.org.uk/`)
3. Opcionalmente informe o **período** (de/até) — links fora do período são
   descartados antes da análise com IA
4. Clique em **Analisar** e acompanhe o progresso em tempo real via SSE
5. Ao terminar, abra **Documentos** para ver o resultado

**Pelo Terminal:**

```bash
# Analisar um link (crawl + process + persist)
python run_pipeline.py https://www.iacs.org.uk/
python run_pipeline.py https://www.iacs.org.uk/ 2024-01-01 2024-12-31

# Só processar fila (documentos já baixados)
python process_queue.py
```

### 5. Validar documentos

1. Clique em **Documentos** no menu lateral
2. Use os filtros para encontrar normas específicas
3. Clique em um documento para ver detalhes
4. Clique em **Aprovado** ou **Reprovado** para validar
5. Para validar vários: marque os checkboxes e clique em **Validar Selecionados**

### 6. Exportar dados

**CSV:**
1. Na aba **Documentos**, clique em **Export CSV**
2. Formato pronto para o Excel pt-BR: UTF-8 com BOM (acentos corretos),
   separador `;` e rótulos traduzidos (`SEG — Segurança`, `Pendente`...)
3. Respeita os filtros ativos de **Validação** e **Fonte**

**PDF:** *(opcional — requer `pip install weasyprint` + bibliotecas GTK/Pango do sistema; sem elas o endpoint retorna 503 com aviso)*
1. Acesse: `http://127.0.0.1:8000/regs/export/pdf`
2. PDF profissional com logo Marmec e badges de classificação legíveis

**Excel:**
1. Acesse: `http://127.0.0.1:8000/regs/export/excel`
2. Planilha com rótulos traduzidos, cores, filtros automáticos e
   **aba Legenda** explicando cada código

---

## Dashboard

### Aba Dashboard (Visão Geral)

- **KPIs**: Total de documentos, pendentes, aprovados, reprovados
- **Gráfico por Assunto**: Distribuição das normas por categoria
- **Gráfico por Aplicação**: Direta, Indireta, Não Pertinente
- **Gráfico por Status**: Revisão vs Nova Versão
- **Atividade Recente**: Últimas validações

### Aba Documentos

- **Busca**: texto em norma, requisito, item, itens modificados, ação sugerida e fonte
  - Use **aspas** para frase exata: `"condições análogas à escravidão"`
- **Legenda de cores** no topo da lista (mesmas cores do Excel e do PDF)
- **Filtros**: Assunto, Aplicação, Validação, Fonte (domínios reais do banco)
  e período de publicação (de/até)
- **Colunas**: Norma (fonte + data + título), Classificação (badges legíveis
  `SEG · Segurança`, `I · Ação Indireta`, `N · Nova Versão`), Ação Sugerida
  (fundo amarelo) e Validação
- **Detalhe**: modal com seções — O que é, Classificação, O que muda,
  Ação recomendada e JSON bruto
- **Ações**: Validar individual ou em lote, exportar CSV

### Aba Nova Análise

- **Link**: campo para colar a página de normas (histórico local das últimas URLs)
- **Período (de/até)**: filtra os links **antes** da análise com IA
- **Analisar**: dispara crawl + download + LLM + persistência
- **Processar fila**: reprocessa documentos já baixados
- **Status/Progresso/Log**: atualização em tempo real via SSE

### Aba Fila

- **Documentos pendentes**: Lista de documentos baixados aguardando processamento

### Aba Provedores IA

- **Status**: Quais provedores estão configurados
- **Ativar**: Trocar o provedor ativo
- **Fallback**: Ordem de fallback automático

### Aba Configurações

- **Chaves de API**: Cadastro de chaves dos provedores LLM (Gemini, NVIDIA)
- **Banco de Dados**: `DATABASE_URL` (SQLite padrão, PostgreSQL opcional)
- **IMODOCS**: Credenciais de acesso
- **Downloads**: Quantidade/tamanho dos documentos baixados + botão
  **Limpar downloads** (apaga `data/downloads/`; bloqueia se houver fila pendente)

---

## API REST

### Tabela de Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Dashboard web |
| `GET` | `/health` | Health check com DB ping |
| `GET` | `/docs` | Swagger UI (documentação interativa) |
| `GET` | `/redoc` | ReDoc (documentação alternativa) |
| `GET` | `/regs/` | Lista paginada com busca e filtros |
| `GET` | `/regs/{id}` | Detalhe de um registro |
| `POST` | `/regs/{id}/validate` | Validar um registro |
| `POST` | `/regs/batch-validate` | Validar múltiplos registros |
| `GET` | `/regs/export/csv` | Download CSV |
| `GET` | `/regs/export/pdf` | Download PDF formatado |
| `GET` | `/regs/export/excel` | Download Excel (.xlsx) |
| `GET` | `/dashboard/metrics` | KPIs e dados para gráficos |
| `POST` | `/pipeline/run` | Analisar um link `{url, date_from, date_to}` |
| `POST` | `/pipeline/process` | Só processar fila |
| `GET` | `/regs/sources` | Fontes distintas (filtro dinâmico) |
| `GET` | `/pipeline/status` | Estado do pipeline |
| `GET` | `/pipeline/stream` | SSE com progresso em tempo real |
| `GET` | `/pipeline/providers` | Listar provedores LLM |
| `POST` | `/pipeline/providers/{id}/activate` | Ativar provedor |
| `GET` | `/pipeline/settings` | Configurações atuais |
| `POST` | `/pipeline/settings` | Salvar configurações |
| `GET` | `/pipeline/notifications` | Histórico de notificações |
| `POST` | `/pipeline/notifications/clear` | Limpar notificações |
| `GET` | `/pipeline/downloads` | Tamanho da pasta de downloads |
| `POST` | `/pipeline/clear-downloads` | Apagar downloads (bloqueia com fila pendente) |

### Exemplos com curl

#### Listar documentos

```bash
curl http://127.0.0.1:8000/regs/
```

#### Buscar por texto

```bash
curl "http://127.0.0.1:8000/regs/?q=seguranca"
```

#### Filtrar por assunto e aplicação

```bash
curl "http://127.0.0.1:8000/regs/?assunto=SEG&aplicacao=D"
```

#### Busca avançada com data e ordenação

```bash
curl "http://127.0.0.1:8000/regs/?date_from=2024-01-01&date_to=2024-12-31&sort_by=norma&sort_order=asc"
```

#### Exportar CSV

```bash
curl http://127.0.0.1:8000/regs/export/csv -o regulamentacoes.csv
```

#### Exportar PDF

```bash
curl http://127.0.0.1:8000/regs/export/pdf -o regulamentacoes.pdf
```

#### Exportar Excel

```bash
curl http://127.0.0.1:8000/regs/export/excel -o regulamentacoes.xlsx
```

#### Validar um documento

```bash
curl -X POST http://127.0.0.1:8000/regs/ID_DOCUMENTO/validate \
  -H "Content-Type: application/json" \
  -d '{"action": "aprovado", "validated_by": "especialista"}'
```

#### Validar múltiplos documentos

```bash
curl -X POST http://127.0.0.1:8000/regs/batch-validate \
  -H "Content-Type: application/json" \
  -d '{"ids": ["id1", "id2"], "action": "aprovado", "validated_by": "especialista"}'
```

#### Analisar um link

```bash
curl -X POST http://127.0.0.1:8000/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.iacs.org.uk/", "date_from": "2024-01-01", "date_to": "2024-12-31"}'
```

#### Só processar fila

```bash
curl -X POST http://127.0.0.1:8000/pipeline/process
```

#### Verificar status do pipeline

```bash
curl http://127.0.0.1:8000/pipeline/status
```

#### Listar provedores

```bash
curl http://127.0.0.1:8000/pipeline/providers
```

#### Ativar um provedor

```bash
curl -X POST http://127.0.0.1:8000/pipeline/providers/gemini/activate
```

### Exemplos com Python

```python
import httpx

BASE = "http://127.0.0.1:8000"

# Listar documentos
resp = httpx.get(f"{BASE}/regs/")
print(resp.json())

# Buscar
resp = httpx.get(f"{BASE}/regs/", params={"q": "seguranca", "assunto": "SEG"})
print(resp.json())

# Exportar CSV
resp = httpx.get(f"{BASE}/regs/export/csv")
with open("dados.csv", "wb") as f:
    f.write(resp.content)

# Validar documento
resp = httpx.post(
    f"{BASE}/regs/{doc_id}/validate", json={"action": "aprovado", "validated_by": "analista"}
)
print(resp.json())

# Analisar um link
resp = httpx.post(
    f"{BASE}/pipeline/run",
    json={"url": "https://www.iacs.org.uk/", "date_from": "2024-01-01", "date_to": "2024-12-31"},
)
print(resp.json())
```

---

## Docker

### Iniciar com Docker Compose

```bash
# Copiar configuração
cp config/secrets.env.example config/secrets.env
# Editar config/secrets.env

# Subir containers
docker compose up -d

# Ver logs
docker compose logs -f app

# Parar
docker compose down
```

### Serviços

| Serviço | Porta | Descrição |
|---|---|---|
| app | 8000 | Aplicação FastAPI |
| postgres | 5432 | PostgreSQL 16 |

---

## Estrutura do Projeto

```
regulatory-pipeline/
├── core/                       # Config compartilhado
│   ├── config.py               # Env vars, logging, load_prompt
│   ├── browser.py              # Pool compartilhado de Playwright
│   ├── pipeline_state.py       # Estado global do pipeline (thread-safe)
│   ├── llm_providers.py        # Gateway multi-provedor LLM
│   ├── notify.py               # Sistema de notificações
│   └── observability.py        # OpenTelemetry tracing
├── crawler/                    # Módulo de crawl
│   ├── runner.py               # Orquestração: crawl → download → enqueue
│   ├── downloader.py           # Download com retry
│   ├── storage.py              # Nome legível de downloads + fila (dedup hash)
│   ├── migrate.py              # Migra downloads antigos p/ pasta downloads/
│   └── spiders/                # Spiders por tipo de página
│       ├── html_list.py        # Genérico: links + datas (período)
│       ├── login.py            # Login automático (IMODOCS)
│       ├── pdf_list.py         # Só links PDF
│       ├── sitemap.py          # Sitemap/RSS
│       └── adapters/
│           └── imodocs.py      # Adapter IMODOCS
├── processor/                  # Módulo de processamento com LLM
│   ├── pipeline.py             # Fila → Extração → LLM → Normalização
│   ├── gateway.py              # Gateway multi-provedor
│   ├── prompt_builder.py       # Montagem do prompt com regras Marmec
│   ├── normalizer.py           # Validação de enums
│   ├── schema.py               # Pydantic RegulatoryAnalysis
│   └── extract.py              # Extração de texto (PyMuPDF/BS4)
├── api/                        # API REST + Dashboard
│   ├── main.py                 # FastAPI app, CORS, Swagger, health
│   ├── database.py             # SQLAlchemy engine (auto-detect PG/SQLite)
│   ├── models.py               # ORM RegulatoryAnalysis
│   ├── schemas.py              # Pydantic API schemas
│   ├── persistence.py          # build_row + persist
│   ├── middleware.py            # API key auth + rate limiter
│   ├── telemetry.py            # OpenTelemetry middleware
│   ├── routes/
│   │   ├── regs.py             # CRUD, busca, filtros, export (CSV/PDF/Excel)
│   │   ├── pipeline.py         # Run, process, status, SSE, providers, settings
│   │   └── dashboard.py        # Metrics
│   └── templates/
│       ├── dashboard.html      # Dashboard principal
│       ├── pdf_report.html     # Template PDF para export
│       └── index.html          # Dashboard legado
├── config/
│   ├── prompt.yaml             # Prompt com regras Marmec
│   ├── llm.yaml                # Config multi-provedor LLM
│   └── secrets.env.example     # Template de credenciais
├── tests/                      # 203 testes unitários + 27 e2e
│   ├── test_config.py
│   ├── test_schema.py
│   ├── test_normalizer.py
│   ├── test_prompt.py
│   ├── test_persistence.py
│   ├── test_html_list.py
│   ├── test_downloads.py
│   ├── test_integration.py
│   ├── test_schemas_api.py
│   ├── test_middleware.py
│   ├── test_notify.py
│   ├── test_gateway.py
│   ├── test_api_routes.py
│   ├── test_api_extended.py
│   ├── test_llm_providers.py
│   ├── test_telemetry.py
│   ├── test_process_queue.py
│   ├── test_processor_pipeline.py
│   ├── test_runner.py
│   ├── test_search.py
│   └── e2e/                    # 27 testes end-to-end
│       ├── conftest.py
│       ├── test_dashboard.py
│       ├── test_api.py
│       └── test_pipeline.py
├── docs/
│   ├── ARCHITECTURE.md         # Arquitetura do sistema
│   └── DEPLOY.md               # Guia de deploy
├── alembic/                    # Migrations do banco
├── .github/workflows/          # CI/CD
│   ├── ci.yml                  # Testes + lint + security
│   └── quality.yml             # Qualidade de código
├── run_pipeline.py             # Entry point: analisar URL (+ período)
├── process_queue.py            # Entry point: só processar fila
├── start.bat / start.sh        # Início em 1 clique (setup + servidor + navegador)
├── setup.bat / setup.sh        # Setup manual (venv + dependências + Playwright)
├── requirements.txt            # Dependências com versionamento
├── pyproject.toml              # Config ruff, mypy, coverage
├── codecov.yml                 # Config Codecov
├── .pre-commit-config.yaml     # Hooks pré-commit
├── Dockerfile                  # Container da aplicação
├── docker-compose.yml          # App + PostgreSQL
├── Makefile                    # Comandos de desenvolvimento
└── .gitignore
```

---

## Schema do Banco

Tabela `regulatory_analysis` — 10 colunas regulatórias + metadados:

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | String (PK) | Identificador único |
| `source_id` | String | ID da fonte (iacs, imca, mte, etc.) |
| `source_name` | String | Nome da fonte |
| `documento_hash` | String | Hash SHA-256 do documento |
| `url_origem` | Text | URL original do documento |
| `data_publicacao` | Date | Data de publicação |
| `entrada_em_vigor` | Date | Data de vigência |
| `requisito` | String | Autoridade emissora |
| `norma` | String | Código + título da norma |
| `assunto` | Enum | SEG/INC/COM/NAV/CON/TRI/AMB/NAU/IMO |
| `aplicacao` | Enum | D (direta) / I (indireta) / NP (não pertinente) |
| `status` | Enum | R (revisão) / N (nova) |
| `item` | String | Item específico alterado |
| `itens_modificados` | Text | O que mudou |
| `acao_sugerida` | Text | Ação recomendada (null se NP) |
| `status_validacao` | String | pendente / aprovado / reprovado |
| `created_at` | DateTime | Data de criação do registro |
| `validated_at` | DateTime | Data da validação |
| `validated_by` | String | Quem validou |

### Regra de Pertinência (Marmec)

- **NP**: norma sobre construção naval ou operação exclusivamente fora do Brasil/Panamá
- **EXCEÇÃO**: assuntos gerais (segurança, incêndio, naufrágio, convenções IMO) são pertinentes mesmo globais

---

## Testes

### Rodar todos os testes

```bash
python -m pytest tests/ -v
```

### Rodar só testes unitários (rápido)

```bash
python -m pytest tests/ -v -m "not e2e and not slow"
```

### Rodar testes E2E

```bash
python -m pytest tests/e2e/ -v -m e2e
```

### Cobertura de código

```bash
python -m pytest tests/ --cov=. --cov-report=term-missing --cov-fail-under=60
```

Coverage mínimo exigido: **60%** (configurado em `pyproject.toml`).

### Lint e formatação

```bash
# Verificar lint
ruff check .

# Formatar código
ruff format .

# Verificar formatação (sem alterar)
ruff format --check .
```

---

## Gerar release (para o usuário final)

O usuário final **não precisa dos testes** nem dos arquivos de desenvolvimento.
Gere um zip limpo:

```powershell
# Nome com hash do commit
.\build_release.ps1

# Nome personalizado
.\build_release.ps1 -Nome v1
```

Saída: `dist/regulatory-pipeline-<hash>.zip`.

O script empacota o que está no commit (`git archive`) e **exclui** `tests/`,
`.github/`, `pyproject.toml`, `.pre-commit-config.yaml` e `codecov.yml`.
Depois valida o pacote e **falha** se vazar algo sensível:
`config/secrets.env`, `data/`, `crawler/state/` ou `__pycache__/`.

Para o usuário final, basta:

1. Descompactar o zip
2. `pip install -r requirements.txt`
3. `start.bat` (ou `python -m uvicorn api.main:app --port 8000`)
4. Abrir <http://127.0.0.1:8000> e colocar a chave de IA em **Configurações**

---

## Troubleshooting

### Erro: "PostgreSQL indisponível"

**Solução:** O sistema usa SQLite automaticamente. Para usar PostgreSQL, verifique se o serviço está rodando:

```bash
# Docker
docker compose up -d postgres

# Systemd
sudo systemctl status postgresql
```

### Erro: "Playwright não encontrado"

**Solução:** Instale o Chromium:

```bash
playwright install chromium
playwright install-deps  # Linux apenas
```

### Erro: "Quota LLM excedida"

**Solução:** O sistema faz fallback automático para o próximo provedor. Configure mais de um em `config/secrets.env`:

```env
GOOGLE_API_KEY=...
NVIDIA_API_KEY=nvapi-...
```

### Erro: "Credenciais IMODOCS não configuradas"

**Solução:** Configure em `config/secrets.env`:

```env
IMODOCS_USER=seu_usuario
IMODOCS_PASSWORD=sua_senha
```

### Erro: "Módulo não encontrado"

**Solução:** Instale as dependências:

```bash
pip install -r requirements.txt
```

### Ver logs

```bash
# Docker
docker compose logs -f app

# Systemd
journalctl -u regulatory -f

# Terminal (quando roda com uvicorn)
# Os logs aparecem no terminal onde o servidor está rodando
```

### Notificações

Notificações são salvas em `data/logs/notifications.jsonl`:

```bash
# Ver últimas notificações
tail -f data/logs/notifications.jsonl
```

---

## Comandos Úteis (Makefile)

```bash
make install     # Instalar dependências
make test        # Rodar testes
make test-cov    # Testes com coverage
make lint        # Verificar lint
make format      # Formatar código
make run         # Iniciar dashboard
make crawl       # Analisar uma URL (URL=<url>)
make process     # Processar fila
make docker-up   # Iniciar com Docker
make docker-down # Parar Docker
make clean       # Limpar arquivos gerados
make help        # Ver todos os comandos
```

---

## Development Workflow

### Issues

Toda correção, melhoria, refatoração ou nova funcionalidade deve estar
associada a uma Issue no GitHub antes do início da implementação.

A Issue deve descrever:
- objetivo da alteração
- problema ou necessidade
- escopo
- critérios de aceitação, quando aplicável

### Branches

Cada Issue deve ser desenvolvida em uma branch própria.

A branch deve seguir o padrão:

```
feature/<descricao>
fix/<descricao>
refactor/<descricao>
docs/<descricao>
chore/<descricao>
```

Não realizar alterações diretamente na branch `main`.

### Pull Requests

Toda alteração deve ser submetida através de um Pull Request.

O Pull Request deve:
- explicar o que foi alterado
- informar a Issue relacionada
- descrever possíveis impactos
- informar os testes realizados
- destacar alterações relevantes

O PR deve referenciar obrigatoriamente a Issue correspondente.

Exemplo:

```
Closes #123
```

### QA

Antes do merge, as alterações devem ser verificadas de acordo com
os critérios definidos na Issue.

Devem ser executados, quando aplicável:
- testes automatizados (`make test`)
- lint e formatação (`make lint`)
- testes manuais
- validação de funcionalidades existentes
- verificação de possíveis regressões

### Merge

A branch `main` deve receber somente alterações que tenham passado
pelo processo de Pull Request e validação correspondente.

### Deploy

Deploys devem ser realizados a partir de alterações integradas à
branch `main`.

Toda alteração publicada deve ser rastreável ao seu Pull Request
e à Issue correspondente.

### Documentação

Alterações que modificarem comportamento, configuração, API,
estrutura ou funcionamento do sistema devem atualizar a documentação
correspondente (`docs/`, `README.md`, Swagger).

### Histórico

Issues, Pull Requests, commits e releases devem manter uma relação
clara entre requisito, implementação, validação e publicação.

---

## Licença

Uso interno 

