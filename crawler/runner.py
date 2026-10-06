"""Orchestrates the crawl: detect new items and enqueue downloads.

Links can be filtered by publication period BEFORE downloading/spending
LLM quota: items whose visible date falls outside ``date_from..date_to``
are discarded; items without any visible date are kept (the portal
doesn't show it — analysis can't discard what it can't see).
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from core.browser import close_pool
from core.config import logger

from . import storage
from .downloader import download
from .spiders.base import Item
from .spiders.registry import get_spider


def filter_by_period(
    items: list[Item],
    date_from: date | None,
    date_to: date | None,
) -> tuple[list[Item], dict[str, int]]:
    """Split items by visible publication date.

    Returns ``(kept, stats)`` where stats has ``total``, ``kept``,
    ``discarded`` (out of period) and ``no_date`` (kept, date unknown).
    """
    if not date_from and not date_to:
        return items, {"total": len(items), "kept": len(items), "discarded": 0, "no_date": 0}

    kept: list[Item] = []
    discarded = 0
    no_date = 0

    for it in items:
        if not it.published_date:
            no_date += 1
            kept.append(it)
            continue
        try:
            d = date.fromisoformat(it.published_date)
        except ValueError:
            no_date += 1
            kept.append(it)
            continue
        if date_from and d < date_from:
            discarded += 1
            continue
        if date_to and d > date_to:
            discarded += 1
            continue
        kept.append(it)

    stats = {
        "total": len(items),
        "kept": len(kept),
        "discarded": discarded,
        "no_date": no_date,
    }
    return kept, stats


def source_from_url(url: str) -> dict[str, Any]:
    """Build an ad-hoc source config from a user-pasted URL.

    The source id is the domain, so dedup ("seen") and the "Fonte"
    filter work per analyzed domain.
    """
    from urllib.parse import urlparse

    domain = urlparse(url).netloc.lower().removeprefix("www.")
    return {
        "id": domain,
        "name": domain,
        "url": url,
        "type": "html_list",
    }


async def run_source(
    source: dict[str, Any],
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Run a single source and return the newly enqueued records."""
    source_id = source.get("id", "")
    spider = get_spider(source)

    items: list[Item] = await spider.fetch_items()

    # Período ANTES do download/LLM: descarta o que está fora, mantém
    # links sem data visível
    items, stats = filter_by_period(items, date_from, date_to)
    if date_from or date_to:
        logger.info(
            "Período %s..%s: %d link(s) no período, %d fora, %d sem data (mantidos)",
            date_from or "*",
            date_to or "*",
            stats["kept"] - stats["no_date"],
            stats["discarded"],
            stats["no_date"],
        )

    seen = storage.load_seen(source_id)
    new_records: list[dict[str, Any]] = []
    new_hashes: set[str] = set(seen)

    for it in items:
        d = it.to_dict()
        d["source_name"] = source.get("name", "")
        h = storage.item_hash(d)
        if h in seen:
            continue
        try:
            content = await download(it.url)
        except Exception as exc:
            logger.warning("Download falhou %s: %s", it.url, exc)
            continue
        record = storage.enqueue(d, content)
        if record:
            new_records.append(record)
            new_hashes.add(h)

    storage.save_seen(source_id, new_hashes)
    return new_records


async def _run_and_close(
    source: dict[str, Any],
    date_from: date | None,
    date_to: date | None,
) -> list[dict[str, Any]]:
    try:
        return await run_source(source, date_from, date_to)
    finally:
        await close_pool()


def run(
    url: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Synchronous entry point: crawl one URL, optionally period-filtered."""
    source = source_from_url(url)
    return asyncio.run(_run_and_close(source, date_from, date_to))


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python -m crawler.runner <url> [AAAA-MM-DD [AAAA-MM-DD]]")
        raise SystemExit(1)
    df = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None
    dt = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else None
    records = run(sys.argv[1], df, dt)
    logger.info("Total de documentos novos: %d", len(records))
