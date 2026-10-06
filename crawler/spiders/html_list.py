"""Generic HTML listing spider backed by Playwright.

Supports per-source config:
  - ``selector``:     CSS selector to scope the link search
  - ``filters``:      list of keywords the anchor text/url must contain
  - ``link_pattern``: regex pattern — only URLs matching this pattern are returned
"""

from __future__ import annotations

import re
from datetime import date
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

    # ── Datas (nome do mês -> número, PT + EN, completo e abreviado) ──
    _MONTH_ALIASES = [
        ("jan", "janeiro", "january"),
        ("fev", "fevereiro", "february", "feb"),
        ("mar", "março", "marco", "march"),
        ("abr", "abril", "april"),
        ("mai", "maio", "may"),
        ("jun", "junho", "june"),
        ("jul", "julho", "july"),
        ("ago", "agosto", "august"),
        ("set", "setembro", "september", "sep"),
        ("out", "outubro", "october", "oct"),
        ("nov", "novembro", "november"),
        ("dez", "dezembro", "december", "dec"),
    ]
    _MONTHS: dict[str, int] = {
        alias: i for i, aliases in enumerate(_MONTH_ALIASES, 1) for alias in aliases
    }

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
                    published_date=self._extract_date(a, text, full_url),
                    source_id=self.source_id,
                )
            )
        return items

    # ── Date extraction ─────────────────────────────────────────────

    def _extract_date(self, anchor, text: str, url: str) -> str | None:
        """Best-effort publication date (``AAAA-MM-DD``) for a link.

        Tries, in order: the anchor text, the surrounding row/card text,
        and finally the URL path (``/2024/05/...``). Returns ``None`` when
        no date is visible — such links are kept (analysis can't discard
        what the portal doesn't show).
        """
        found = self._find_date(text)
        if found:
            return found

        parent = anchor.find_parent(["tr", "li", "article", "div"])
        if parent is not None:
            ctx = parent.get_text(" ", strip=True)
            if len(ctx) <= 500:  # contexto grande = página inteira, ignora
                found = self._find_date(ctx)
                if found:
                    return found

        return self._find_date(url)

    def _find_date(self, text: str) -> str | None:
        """Parse the first valid date found in ``text``."""
        if not text:
            return None

        # AAAA-MM-DD / AAAA/MM/DD
        m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
        if m:
            iso = self._to_iso(m.group(1), m.group(2), m.group(3))
            if iso:
                return iso

        # DD/MM/AAAA (e variações . e -)
        m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", text)
        if m:
            iso = self._to_iso(m.group(3), m.group(2), m.group(1))
            if iso:
                return iso

        # "15 May 2024" / "15 de maio de 2024" / "May 15, 2024"
        month_pat = "|".join(
            sorted({a for al in self._MONTH_ALIASES for a in al}, key=len, reverse=True)
        )
        m = re.search(
            rf"(\d{{1,2}})\s+(?:de\s+)?({month_pat})\.?,?\s+(?:de\s+)?(\d{{4}})",
            text,
            re.IGNORECASE,
        )
        if m:
            month = self._MONTHS.get(m.group(2).lower())
            if month:
                iso = self._to_iso(m.group(3), month, m.group(1))
                if iso:
                    return iso
        m = re.search(rf"({month_pat})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})", text, re.IGNORECASE)
        if m:
            month = self._MONTHS.get(m.group(1).lower())
            if month:
                iso = self._to_iso(m.group(3), month, m.group(2))
                if iso:
                    return iso

        # /2024/05/... (mês na URL, dia = 01)
        m = re.search(r"/(\d{4})/(\d{1,2})(?:/|$)", text)
        if m:
            iso = self._to_iso(m.group(1), m.group(2), 1)
            if iso:
                return iso

        return None

    @staticmethod
    def _to_iso(year: str | int, month: str | int, day: str | int) -> str | None:
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return None

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
