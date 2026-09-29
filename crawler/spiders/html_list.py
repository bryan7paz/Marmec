"""Generic HTML listing spider backed by Playwright.

Supports per-source config:
  - ``selector``:     CSS selector to scope the link search
  - ``filters``:      list of keywords the anchor text/url must contain
  - ``link_pattern``: regex pattern — only URLs matching this pattern are returned
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from .base import BaseSpider, Item


class HtmlListSpider(BaseSpider):
    """Loads a page and extracts candidate document links (pdf/html)."""

    KEYWORDS = [
        "circular",
        "resolution",
        "marine notice",
        "norma",
        "np",
        "dpc",
        "aplic",
        "alteracao",
        "mmc",
        "notice",
        "amendment",
        "update",
    ]

    # Textos de navegação/chrome que nunca são documentos
    BLACKLIST = [
        "ir para",
        "compartilhe",
        "galeria de aplicativos",
        "abrir menu",
        "fechar menu",
    ]

    async def fetch_items(self) -> list[Item]:
        from core.browser import get_browser

        async with get_browser() as page:
            await page.goto(self.url, wait_until="domcontentloaded", timeout=60000)
            html = await page.content()

        return self._extract_links(html)

    def _extract_links(self, html: str) -> list[Item]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        scope_selector = self.source.get("selector")
        root = soup
        if scope_selector:
            root = soup.select_one(scope_selector) or soup

        filters = self.source.get("filters") or []
        link_pattern = self.source.get("link_pattern")
        compiled_pattern = re.compile(link_pattern, re.IGNORECASE) if link_pattern else None

        items: list[Item] = []
        seen: set[str] = set()

        for a in root.find_all("a", href=True):
            href = a["href"]
            if href.startswith(("#", "javascript:", "mailto:")):
                continue
            text = a.get_text(" ", strip=True) or ""
            full_url = urljoin(self.url, href)

            if not text or full_url in seen:
                continue
            if filters and not any(f.lower() in f"{text} {full_url}".lower() for f in filters):
                continue
            if compiled_pattern and not compiled_pattern.search(full_url):
                continue
            if not self._is_candidate(text, full_url):
                continue

            seen.add(full_url)
            items.append(
                Item(
                    title=text,
                    url=full_url,
                    source_id=self.source_id,
                )
            )
        return items

    def _is_candidate(self, text: str, url: str) -> bool:
        lower = f"{text} {url}".lower()
        if any(b in lower for b in self.BLACKLIST):
            return False
        if url.lower().endswith(".pdf") or "pdf" in url.lower():
            return True
        # HTML e demais: exige indício de documento (KEYWORDS) — links de
        # navegação do portal (menus, busca, social) não entram na fila
        has_keyword = any(k in lower for k in self.KEYWORDS)
        return bool(has_keyword and len(text) > 5)
