"""Process all queued documents and persist to the database.

Skips documents whose hash is already persisted (idempotent).
After processing, compacts the queue file (removes processed entries).

Can be run standalone or imported as a module.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from api import models, persistence
from api.database import Base, SessionLocal, engine
from core.config import logger
from processor import pipeline
from sqlalchemy import select

QUEUE_PATH = Path(__file__).resolve().parent / "data" / "queue.jsonl"


def _to_iso(value: str | None) -> date | None:
    """Parse ``AAAA-MM-DD``, returning None on empty/invalid input."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def process_queue(
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    """Process the queue and return the number of records persisted.

    When a period (``date_from``/``date_to``, AAAA-MM-DD) is given,
    records whose publication date extracted by the AI falls outside the
    period are discarded instead of persisted.
    """
    df = _to_iso(date_from)
    dt = _to_iso(date_to)
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
    filtered_out = 0

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
            # Erro transitório (LLM/cota/IO): mantém na fila para retry.
            # Se o erro indicar que NENHUM provedor LLM está disponível
            # (ex.: todos desabilitados ou fora do ar), descarta o item
            # para não travar a fila para sempre (opção 4).
            msg = str(exc).lower()
            provedor_indisponível = (
                "não foi possível importar google.genai" in msg
                or "nenhum provedor llm disponível" in msg
                or "all providers failed" in msg
                or "503" in msg
                or "404" in msg
                or "unavailable" in msg
                or "not found" in msg
            )
            if provedor_indisponível:
                logger.warning(
                    "Descartando %s (provedor LLM indisponível): %s",
                    record.get("title"),
                    exc,
                )
                processed_hashes.append(sha)
            else:
                logger.warning("Erro processando %s: %s", record.get("title"), exc)
            continue

        row = persistence.build_row(raw)
        # Filtro de período pós-IA: a data extraída pelo LLM agora é
        # conhecida — descarta o que está fora do período solicitado.
        pub = raw.get("data_publicacao")
        if (df or dt) and pub:
            try:
                pd_ = date.fromisoformat(str(pub)[:10])
                out_of_range = (df and pd_ < df) or (dt and pd_ > dt)
            except ValueError:
                out_of_range = False
            if out_of_range:
                logger.info("Descartando %s: fora do período (%s)", record.get("title"), pub)
                processed_hashes.append(sha)
                filtered_out += 1
                continue
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

    logger.info(
        "Processados: %d (fila total: %d, fora do período: %d)",
        processed,
        len(records),
        filtered_out,
    )
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
