"""Pipeline control endpoints: run, status, SSE stream."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import AsyncGenerator
from pathlib import Path

from core.config import logger
from core.pipeline_state import pipeline_state
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _run_pipeline_background() -> None:
    """Execute crawl + process in a background thread, updating state."""
    from core.notify import notify_new_documents, notify_pipeline_complete, notify_pipeline_error

    pipeline_state.start()
    start_time = time.time()

    try:
        # ── Crawl ──────────────────────────────────────────────────
        pipeline_state.update(step="crawling", current="Iniciando crawler...")
        import asyncio as _asyncio

        from crawler.runner import run_all

        records = _asyncio.run(run_all())

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
        logger.error("Pipeline falhou: %s", exc)
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
def run_pipeline():
    """Trigger a full pipeline run (crawl + process) in the background."""
    if pipeline_state.running:
        return {"ok": False, "error": "Pipeline já está em execução"}

    thread = threading.Thread(target=_run_pipeline_background, daemon=True)
    thread.start()
    return {"ok": True, "message": "Pipeline completo iniciado"}


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
    "SCHEDULE_HOUR",
    "SCHEDULE_TIMEZONE",
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
