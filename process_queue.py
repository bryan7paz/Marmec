"""Process all queued documents and persist to the database.

Skips documents whose hash is already persisted (idempotent).
After processing, compacts the queue file (removes processed entries).

Can be run standalone or imported as a module.
"""

from __future__ import annotations

import json
from pathlib import Path

from api import models, persistence
from api.database import Base, SessionLocal, engine
from core.config import logger
from processor import pipeline
from sqlalchemy import select

QUEUE_PATH = Path(__file__).resolve().parent / "data" / "queue.jsonl"


def process_queue() -> int:
    """Process the queue and return the number of records persisted."""
    Base.metadata.create_all(bind=engine)

    records = pipeline.read_queue()
    db = SessionLocal()
    try:
        existing = {
            h for (h,) in db.execute(select(models.RegulatoryAnalysis.documento_hash)).all() if h
        }
    finally:
        db.close()

    processed = 0
    processed_hashes: list[str] = []

    for record in records:
        sha = record.get("sha256", "")
        if sha in existing:
            continue
        try:
            raw = pipeline.process_record(record)
        except pipeline.DocumentoIgnoradoError as exc:
            # Qualidade ruim (sem texto / sem norma): descarta da fila
            logger.warning("Descartando %s: %s", record.get("title"), exc)
            processed_hashes.append(sha)
            continue
        except Exception as exc:
            # Erro transitório (LLM/cota/IO): mantém na fila para retry
            logger.warning("Erro processando %s: %s", record.get("title"), exc)
            continue

        row = persistence.build_row(raw)
        db = SessionLocal()
        try:
            db.add(row)
            db.commit()
        finally:
            db.close()
        processed += 1
        processed_hashes.append(sha)
        logger.info(
            "[ok] %s | %s/%s",
            raw.get("norma") or record.get("title"),
            raw.get("status"),
            raw.get("aplicacao"),
        )

    # Compact queue: remove processed entries
    if QUEUE_PATH.exists() and processed_hashes:
        _compact_queue(processed_hashes)

    logger.info("Processados: %d (fila total: %d)", processed, len(records))
    return processed


def _compact_queue(processed_hashes: list[str]) -> None:
    """Remove processed entries from queue.jsonl."""
    with open(QUEUE_PATH) as f:
        all_lines = [line.strip() for line in f if line.strip()]

    remaining = []
    for line in all_lines:
        entry = json.loads(line)
        if entry.get("sha256", "") not in processed_hashes:
            remaining.append(line)

    with open(QUEUE_PATH, "w") as f:
        for line in remaining:
            f.write(line + "\n")

    logger.info("Fila compactada: %d -> %d entradas", len(all_lines), len(remaining))


if __name__ == "__main__":
    process_queue()
