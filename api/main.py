"""FastAPI application entry point."""

from __future__ import annotations

from pathlib import Path

from core.config import load_env, logger, validate_env
from core.observability import setup_telemetry
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .database import Base, engine
from .middleware import api_key_auth, rate_limiter
from .routes import dashboard, pipeline, regs
from .telemetry import TelemetryMiddleware

# ── env validation ──────────────────────────────────────────────────
env = load_env()
missing = validate_env(env)
if missing:
    logger.warning("Variáveis de ambiente ausentes: %s", ", ".join(missing))

# ── database ────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# ── observability ───────────────────────────────────────────────────
setup_telemetry()

# ── app ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="Regulatory Pipeline — Marmec",
    description="""
## Sistema de Monitoramento Regulatório Marítimo

Automatiza o monitoramento de normas regulatórias internacionais para operadores de tubulação submarina.

### Funcionalidades
- **Crawler**: Analisa links colados em Nova Análise (período antes da IA)
- **Processor**: Analisa documentos via LLM (Gemini, NVIDIA)
- **Dashboard**: Visualiza, valida e exporta análises regulatórias
- **Export**: CSV, PDF formatado, Excel com formatação profissional

### API
- CRUD completo de análises regulatórias
- Busca avançada com filtros e paginação
- Validação individual e em lote
- Pipeline de processamento com progresso em tempo real (SSE)
- Notificações de eventos do pipeline
    """,
    version="1.0.0",
    contact={"name": "Marmec", "email": "contato@marmec.com.br"},
    license_info={"name": "Proprietário"},
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── static assets (logo, favicon) ──────────────────────────────────
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

app.add_middleware(TelemetryMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(regs.router, dependencies=[Depends(api_key_auth)])
app.include_router(dashboard.router, dependencies=[Depends(api_key_auth)])
app.include_router(pipeline.router, dependencies=[Depends(api_key_auth)])

# Apply rate limiter to all routes
app.add_api_route(
    "/__rate_check__",
    rate_limiter,
    methods=["GET"],
    include_in_schema=False,
)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request):
    return TEMPLATES.TemplateResponse(request, "dashboard.html")


@app.get("/old", response_class=HTMLResponse, include_in_schema=False)
def index_old(request: Request):
    return TEMPLATES.TemplateResponse(request, "index.html")


@app.get("/health", tags=["system"])
def health():
    """Health check do sistema."""
    from sqlalchemy import text

    from .database import SessionLocal

    db_ok = False
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db_ok = True
        finally:
            db.close()
    except Exception:
        pass

    status = "ok" if db_ok else "degraded"
    return {"status": status, "db": "connected" if db_ok else "disconnected"}
