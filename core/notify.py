"""Notification system — logs pipeline events to console/file."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import logger

LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log_event(event_type: str, data: dict[str, Any]) -> None:
    """Log an event to console and to data/logs/notifications.jsonl."""
    _ensure_log_dir()

    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event_type,
        **data,
    }

    # Console log
    if event_type == "pipeline_complete":
        logger.info(
            "NOTIFICAÇÃO: Pipeline concluído — %d documento(s) processado(s), %d novo(s)",
            data.get("processed", 0),
            data.get("new_documents", 0),
        )
    elif event_type == "pipeline_error":
        logger.warning("NOTIFICAÇÃO: Pipeline falhou — %s", data.get("error", "erro desconhecido"))
    elif event_type == "new_documents":
        logger.info(
            "NOTIFICAÇÃO: %d documento(s) novo(s) encontrado(s) em %s",
            data.get("count", 0),
            data.get("source", "desconhecida"),
        )
    elif event_type == "validation":
        logger.info(
            "NOTIFICAÇÃO: Documento %s — %s por %s",
            data.get("doc_id", "?"),
            data.get("action", "?"),
            data.get("validated_by", "?"),
        )
    else:
        logger.info("NOTIFICAÇÃO [%s]: %s", event_type, json.dumps(data, ensure_ascii=False))

    # Persist to file
    log_file = LOG_DIR / "notifications.jsonl"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def notify_pipeline_complete(
    processed: int,
    new_documents: int,
    errors: list[str] | None = None,
    duration_seconds: float = 0,
    crawl_stats: dict[str, int] | None = None,
    reason: str | None = None,
) -> None:
    """Notify when pipeline finishes."""
    _log_event(
        "pipeline_complete",
        {
            "processed": processed,
            "new_documents": new_documents,
            "errors": errors or [],
            "duration_seconds": round(duration_seconds, 2),
            "crawl_stats": crawl_stats,
            "reason": reason,
        },
    )


def notify_pipeline_error(error: str, source: str = "") -> None:
    """Notify when pipeline fails."""
    _log_event("pipeline_error", {"error": error, "source": source})


def notify_new_documents(
    count: int, source: str, documents: list[dict[str, Any]] | None = None
) -> None:
    """Notify when new documents are found."""
    _log_event(
        "new_documents",
        {
            "count": count,
            "source": source,
            "documents": documents or [],
        },
    )


def notify_validation(doc_id: str, action: str, validated_by: str) -> None:
    """Notify when a document is validated."""
    _log_event(
        "validation",
        {
            "doc_id": doc_id,
            "action": action,
            "validated_by": validated_by,
        },
    )


def get_notifications(limit: int = 50) -> list[dict[str, Any]]:
    """Read recent notifications from log file."""
    log_file = LOG_DIR / "notifications.jsonl"
    if not log_file.exists():
        return []

    events = []
    with log_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return events[-limit:]


def clear_notifications() -> int:
    """Clear notification log. Returns number of entries removed."""
    log_file = LOG_DIR / "notifications.jsonl"
    if log_file.exists():
        count = sum(1 for _ in log_file.open())
        log_file.unlink()
        return count
    return 0
