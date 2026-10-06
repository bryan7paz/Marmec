"""Login-based spider for portals that require authentication (e.g. IMODOCS).

Uses Playwright to log in with credentials from the environment (``auth``
block in the source dict, e.g. ``IMODOCS_USER``/``IMODOCS_PASSWORD`` in
``config/secrets.env``), then extracts document links from the page.
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup
from core.config import load_env

from .base import BaseSpider, Item


class LoginSpider(BaseSpider):
    """Logs in and extracts document links."""

    async def fetch_items(self) -> list[Item]:
        from core.browser import get_browser

        env = load_env()
        auth = self.source.get("auth", {})
        user = env.get(auth.get("user_env", "IMODOCS_USER"), "")
        password = env.get(auth.get("password_env", "IMODOCS_PASSWORD"), "")

        if not user or not password:
            raise RuntimeError(f"Credenciais não configuradas para a fonte {self.source_id}")

        login_url = auth.get("login_url", self.url)
        user_sel = auth.get(
            "username_selector", "input[type=text], input[name*=user i], input[name*=login i]"
        )
        pass_sel = auth.get("password_selector", "input[type=password]")
        submit_sel = auth.get("submit_selector", "button[type=submit], input[type=submit]")

        async with get_browser() as page:
            await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.fill(user_sel, user, timeout=10000)
                await page.fill(pass_sel, password, timeout=10000)
                await page.click(submit_sel, timeout=10000)
                await page.wait_for_load_state("networkidle", timeout=30000)
            except Exception as exc:
                raise RuntimeError(f"Falha no login em {self.source_id}: {exc}") from exc

            if self.url != login_url:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=60000)

            html = await page.content()

        return self._extract_links(html)

    def _extract_links(self, html: str) -> list[Item]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[Item] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True)
            if not text or not href.lower().endswith(".pdf"):
                continue
            full_url = urljoin(self.url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            items.append(Item(title=text, url=full_url, source_id=self.source_id))
        return items
