# Arquitetura do Sistema

## Visão Geral

O **Regulatory Pipeline** é um sistema automatizado de monitoramento regulatório para a Marmec, prestadora de controle regulatório (escopo operacional: Brasil e Panamá, pipe-laying). O sistema crawler fontes regulatórias internacionais, processa documentos via LLM, e apresenta resultados em um dashboard para validação humana.

## Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────────────┐
│                         REGULATORY PIPELINE                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│  │  CRAWLER  │───>│PROCESSOR │───>│   API    │───>│DASHBOARD │     │
│  │ (Playwright)│ │  (LLM)   │    │ (FastAPI)│    │(Bootstrap)│     │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘     │
│       │               │               │               │             │
│       v               v               v               v             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│  │  queue    │    │  LLM     │    │ Database │    │  Chart.js│     │
│  │ .jsonl    │    │ Providers│    │(PG/SQLite)│   │  HTMX    │     │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Fluxo de Dados

### 1. Crawler Phase
```
URL colada em Nova Análise (+ período opcional)
    │
    ▼
HtmlListSpider (página genérica)          ImodocsAdapter (docs.imo.org, login)
    │                                          │
    ├─ extrai links + datas visíveis           │
    ├─ filtro de período ANTES do download     │
    │   (sem data → mantido)                   │
    ▼                                          ▼
Download → SHA-256 Dedup → queue.jsonl
```

### 2. Processor Phase
```
queue.jsonl
    │
    ▼
Extract Text (PyMuPDF/BS4)
    │
    ▼
Build Prompt (prompt.yaml)
    │
    ▼
LLM Provider (Gemini/NVIDIA)
    │
    ▼
Normalize (Pydantic Schema)
    │
    ▼
PostgreSQL / SQLite
```

### 3. API Phase
```
FastAPI Endpoints
    │
    ├─ GET  /regs/           (list + search + filter)
    ├─ POST /regs/batch-validate
    ├─ GET  /regs/export/csv
    ├─ GET  /regs/export/pdf
    ├─ GET  /regs/export/excel
    ├─ POST /pipeline/run
    ├─ GET  /pipeline/status
    └─ SSE  /pipeline/stream
```

## Módulos

### core/
Módulo compartilhado com configurações e utilitários.

| Arquivo | Responsabilidade |
|---------|------------------|
| `config.py` | Loading de YAML, env vars, logging |
| `browser.py` | Pool de browsers Playwright |
| `pipeline_state.py` | Singleton thread-safe para estado |
| `llm_providers.py` | Gateway multi-provedor com fallback |
| `notify.py` | Sistema de notificações |

### crawler/
Módulo de crawling com arquitetura extensível.

| Arquivo | Responsabilidade |
|---------|------------------|
| `runner.py` | Orquestrador crawl → download → enqueue |
| `storage.py` | Estado persistente + fila JSONL |
| `downloader.py` | Download com retry (httpx/Playwright) |
| `spiders/base.py` | Interface abstrata BaseSpider |
| `spiders/registry.py` | Registry pattern para spiders |
| `spiders/html_list.py` | Spider genérico para listagens HTML |
| `spiders/login.py` | Spider autenticado (Playwright) |
| `spiders/adapters/imodocs.py` | Adapter customizado IMODOCS |

### processor/
Módulo de processamento via LLM.

| Arquivo | Responsabilidade |
|---------|------------------|
| `pipeline.py` | Queue → Extract → LLM → Normalize |
| `extract.py` | Extração de texto (PDF/HTML) |
| `prompt_builder.py` | Montagem de prompts |
| `normalizer.py` | Validação Pydantic |
| `schema.py` | Modelo RegulatoryAnalysis |

### api/
API REST + Dashboard.

| Arquivo | Responsabilidade |
|---------|------------------|
| `main.py` | App factory, middleware |
| `database.py` | SQLAlchemy engine (PG/SQLite) |
| `models.py` | ORM model |
| `schemas.py` | Pydantic API schemas |
| `routes/regs.py` | CRUD, busca, export |
| `routes/pipeline.py` | Controle do pipeline |
| `routes/dashboard.py` | KPIs e métricas |

## Padrões de Design

### 1. Spider Registry
```python
# crawler/spiders/registry.py
TYPE_MAP = {
    "html_list": HtmlListSpider,
    "login": LoginSpider,
    "sitemap": SitemapSpider,
}
ADAPTER_MAP = {
    "imodocs": ImodocsAdapter,
}
```

### 2. LLM Provider Fallback
```yaml
# config/llm.yaml
active: gemini
fallback_chain:
  - gemini
  - nvidia
```

### 3. Pipeline State Singleton
```python
# core/pipeline_state.py
state = PipelineState()
state.start()
state.update(step="processing", processed=5)
state.finish(ok=True)
```

## Decisões de Design

### SQLite como fallback
O sistema auto-detecta PostgreSQL e faz fallback para SQLite. Isso permite desenvolvimento local sem infraestrutura.

### SHA-256 para dedup
Cada documento é hashead para evitar re-processamento. O hash é baseado em `source_id|title|url`.

### Pydantic para validação
O output do LLM é validado contra um schema Pydantic rígido, garantindo consistência dos dados.

### SSE para progresso
O pipeline usa Server-Sent Events para atualizar o dashboard em tempo real.

## Segurança

- **Local-first**: Sistema projetado para rodar localmente
- **Secrets em arquivo**: `config/secrets.env` (gitignored)
- **Sem auth por padrão**: Adequado para uso interno
- **Rate limit opcional**: Disponível via middleware

## Performance

- **Playwright pool**: Browser reutilizado entre requests
- **Connection pooling**: SQLAlchemy pool para PostgreSQL
- **WAL mode**: SQLite com Write-Ahead Logging para concorrência
- **Background threads**: Pipeline roda em thread separada
