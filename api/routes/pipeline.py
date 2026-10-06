"""Pipeline control endpoints: analyze a URL, process queue, SSE stream."""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from core.config import logger
from core.pipeline_state import pipeline_state
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class AnalyzeRequest(BaseModel):
    """Body for POST /pipeline/run — analyze documents found at a URL."""

    url: str
    date_from: str | None = None
    date_to: str | None = None


def _validate(body: AnalyzeRequest) -> str | None:
    """Return an error message, or None when the request is valid."""
    parsed = urlparse(body.url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "URL inválida — cole um link começando com http:// ou https://"
    try:
        df = date.fromisoformat(body.date_from) if body.date_from else None
        dt = date.fromisoformat(body.date_to) if body.date_to else None
    except ValueError:
        return "Período inválido — use o formato AAAA-MM-DD"
    if df and dt and df > dt:
        return "Período inválido: data inicial é posterior à final"
    return None


def _analyze_background(body: AnalyzeRequest) -> None:
    """Execute crawl (one URL, period-filtered) + process in a background thread."""
    from core.notify import notify_new_documents, notify_pipeline_complete, notify_pipeline_error

    pipeline_state.start()
    start_time = time.time()

    try:
        df = date.fromisoformat(body.date_from) if body.date_from else None
        dt = date.fromisoformat(body.date_to) if body.date_to else None

        pipeline_state.update(step="crawling", current=f"Analisando {body.url} ...")
        import asyncio as _asyncio

        from core.browser import close_pool
        from crawler.runner import run_source, source_from_url

        source = source_from_url(body.url.strip())

        async def _crawl() -> list[dict]:
            try:
                return await run_source(source, df, dt)
            finally:
                await close_pool()

        records = _asyncio.run(_crawl())

        pipeline_state.update(
            step="crawling_done",
            current=f"{len(records)} documento(s) baixado(s)",
            processed=len(records),
        )

        # Notify new documents
        if records:
            sources = {}
            for r in records:
                src = r.get("source_name", r.get("source_id", "?"))
                sources[src] = sources.get(src, 0) + 1
            for source_name, count in sources.items():
                notify_new_documents(count, source_name)

        if not records:
            pipeline_state.finish(ok=True)
            duration = time.time() - start_time
            notify_pipeline_complete(processed=0, new_documents=0, duration_seconds=duration)
            return

        # ── Process ────────────────────────────────────────────────
        _process_only()

        duration = time.time() - start_time
        state = pipeline_state.snapshot()
        notify_pipeline_complete(
            processed=state.get("processed", 0),
            new_documents=state.get("docs_persisted", 0),
            duration_seconds=duration,
        )

    except Exception as exc:
        logger.error("Análise falhou: %s", exc)
        pipeline_state.add_error(str(exc))
        pipeline_state.finish(ok=False)
        notify_pipeline_error(str(exc))


def _process_only_background() -> None:
    """Execute only queue processing (no crawl) in a background thread."""
    from core.notify import notify_pipeline_complete, notify_pipeline_error

    pipeline_state.start()
    start_time = time.time()

    try:
        _process_only()
        duration = time.time() - start_time
        state = pipeline_state.snapshot()
        notify_pipeline_complete(
            processed=state.get("processed", 0),
            new_documents=state.get("docs_persisted", 0),
            duration_seconds=duration,
        )
    except Exception as exc:
        logger.error("Processamento falhou: %s", exc)
        pipeline_state.add_error(str(exc))
        notify_pipeline_error(str(exc))


def _process_only() -> None:
    """Shared processing logic (called by both full pipeline and process-only)."""
    from process_queue import process_queue

    pipeline_state.update(step="processing", current="Processando fila com Gemini...")
    saved = process_queue()

    pipeline_state.update(
        step="done",
        current=f"{saved} registro(s) persistido(s)",
        docs_persisted=saved,
    )
    pipeline_state.finish(ok=True)


@router.post("/run")
def run_pipeline(body: AnalyzeRequest):
    """Analyze documents found at a URL (optionally period-filtered)."""
    error = _validate(body)
    if error:
        return {"ok": False, "error": error}

    if pipeline_state.running:
        return {"ok": False, "error": "Pipeline já está em execução"}

    thread = threading.Thread(target=_analyze_background, args=(body,), daemon=True)
    thread.start()
    return {"ok": True, "message": "Análise iniciada"}


@router.post("/process")
def process_only():
    """Trigger queue processing only (no crawl) in the background."""
    if pipeline_state.running:
        return {"ok": False, "error": "Pipeline já está em execução"}

    thread = threading.Thread(target=_process_only_background, daemon=True)
    thread.start()
    return {"ok": True, "message": "Processamento da fila iniciado"}


@router.get("/status")
def pipeline_status():
    """Return current pipeline state."""
    from pathlib import Path

    queue_path = Path(__file__).resolve().parent.parent.parent / "data" / "queue.jsonl"
    queue_size = 0
    if queue_path.exists():
        with open(queue_path) as f:
            queue_size = sum(1 for line in f if line.strip())

    snap = pipeline_state.snapshot()
    snap["queue_size"] = queue_size
    return snap


@router.get("/stream")
async def pipeline_stream():
    """SSE endpoint: pushes state updates every second while pipeline runs."""

    async def event_generator() -> AsyncGenerator[str, None]:
        evt = pipeline_state.subscribe()
        try:
            # Send initial state
            snap = pipeline_state.snapshot()
            yield f"data: {json.dumps(snap)}\n\n"

            while True:
                # Wait for state change or timeout (1s keepalive)
                evt.wait(timeout=1.0)
                evt.clear()

                snap = pipeline_state.snapshot()
                yield f"data: {json.dumps(snap)}\n\n"

                # If pipeline finished and we already sent the final state, stop
                if not snap["running"] and snap["step"] == "":
                    break
        finally:
            pipeline_state.unsubscribe(evt)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── LLM Providers ───────────────────────────────────────────────


@router.get("/providers")
def list_providers():
    """List available LLM providers and their status."""
    from core.llm_providers import list_providers as _list

    return _list()


@router.post("/providers/{provider_id}/activate")
def activate_provider(provider_id: str):
    """Set a provider as active in config/llm.yaml."""
    import yaml
    from core.llm_providers import CONFIG_PATH, PROVIDERS

    if provider_id not in PROVIDERS:
        return {"ok": False, "error": f"Provedor '{provider_id}' não existe"}

    cfg = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    cfg["active"] = provider_id
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

    return {"ok": True, "active": provider_id}


# ── Settings (API keys) ─────────────────────────────────────────

SECRETS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "secrets.env"

# Keys that are safe to show (masked) vs sensitive (never return value)
SENSITIVE_KEYS = {
    "GOOGLE_API_KEY",
    "NVIDIA_API_KEY",
    "IMODOCS_PASSWORD",
}
SAFE_KEYS = {
    "DATABASE_URL",
    "IMODOCS_USER",
}


def _read_secrets() -> dict[str, str]:
    """Parse secrets.env into a dict."""
    result = {}
    if not SECRETS_PATH.exists():
        return result
    with open(SECRETS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                result[key.strip()] = val.strip()
    return result


def _write_secrets(data: dict[str, str]) -> None:
    """Write secrets.env preserving comments and structure."""
    lines = []
    if SECRETS_PATH.exists():
        with open(SECRETS_PATH, encoding="utf-8") as f:
            lines = f.readlines()

    # Update existing keys
    keys_written = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in data:
                new_lines.append(f"{key}={data[key]}\n")
                keys_written.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Append new keys
    for key, val in data.items():
        if key not in keys_written:
            new_lines.append(f"{key}={val}\n")

    with open(SECRETS_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def _mask(val: str) -> str:
    """Mask a secret value, showing only last 4 chars."""
    if len(val) <= 8:
        return "****"
    return "*" * (len(val) - 4) + val[-4:]


@router.get("/settings")
def get_settings():
    """Return current settings (secrets masked)."""
    secrets = _read_secrets()
    result = {}
    all_keys = SENSITIVE_KEYS | SAFE_KEYS
    for key in all_keys:
        val = secrets.get(key, "")
        if key in SENSITIVE_KEYS:
            result[key] = {"value": _mask(val) if val else "", "configured": bool(val)}
        else:
            result[key] = {"value": val, "configured": bool(val)}
    return result


@router.post("/settings")
def save_settings(body: dict[str, str]):
    """Save settings to secrets.env. Only updates keys that are sent."""
    # Filter out empty values and masked values
    to_save = {}
    for key, val in body.items():
        if val and not val.startswith("*"):
            to_save[key] = val

    if to_save:
        _write_secrets(to_save)

    return {"ok": True, "saved": list(to_save.keys())}


# ── Notifications ────────────────────────────────────────────────


@router.get("/notifications")
def list_notifications(limit: int = 50):
    """List recent pipeline notifications."""
    from core.notify import get_notifications

    return get_notifications(limit=limit)


@router.post("/notifications/clear")
def clear_notifications():
    """Clear notification history."""
    from core.notify import clear_notifications

    count = clear_notifications()
    return {"ok": True, "cleared": count}


# ── Downloads ────────────────────────────────────────────────────


def _downloads_stats() -> tuple[int, int]:
    """(arquivos, bytes) em data/downloads/."""
    from crawler import storage

    root = storage.DATA_DIR / storage.DOWNLOADS_SUBDIR
    files = total = 0
    if root.is_dir():
        for f in root.rglob("*"):
            if f.is_file():
                files += 1
                total += f.stat().st_size
    return files, total


@router.get("/downloads")
def downloads_info():
    """Tamanho da pasta de downloads (alimenta o botão de limpar)."""
    files, total = _downloads_stats()
    return {"arquivos": files, "bytes": total}


@router.post("/clear-downloads")
def clear_downloads():
    """Apaga todos os documentos baixados (data/downloads/)."""
    from crawler import storage

    queue_path = storage.DATA_DIR / "queue.jsonl"
    pending = 0
    if queue_path.exists():
        pending = sum(
            1 for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()
        )
    if pending:
        return {
            "ok": False,
            "error": (
                f"{pending} documento(s) aguardando processamento — "
                "processe a fila antes de limpar os downloads"
            ),
        }

    files, total = _downloads_stats()
    root = storage.DATA_DIR / storage.DOWNLOADS_SUBDIR
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
    logger.info("Downloads limpos: %d arquivos, %d bytes liberados", files, total)
    return {"ok": True, "arquivos": files, "bytes": total}
