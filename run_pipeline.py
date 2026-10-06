"""End-to-end orchestration for a single URL: crawl -> process -> persist.

Run with: python run_pipeline.py <url> [AAAA-MM-DD [AAAA-MM-DD]]

Examples:
    python run_pipeline.py https://www.iacs.org.uk/normas
    python run_pipeline.py https://www.iacs.org.uk/normas 2024-01-01 2024-12-31
"""

from __future__ import annotations

import sys
from datetime import date

from core.config import logger
from crawler import runner
from process_queue import process_queue


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)

    url = sys.argv[1]
    date_from = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None
    date_to = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else None

    new_docs = runner.run(url, date_from, date_to)
    logger.info("[pipeline] %d novo(s) documento(s) baixado(s)", len(new_docs))

    if not new_docs:
        logger.info("[pipeline] nada novo; encerrando.")
        return

    saved = process_queue()
    logger.info("[pipeline] %d registro(s) salvos no banco", saved)


if __name__ == "__main__":
    main()
