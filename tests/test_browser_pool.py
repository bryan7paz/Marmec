"""Browser pool — reuso do Chromium e fechamento por inatividade (RAM leve)."""

from __future__ import annotations

import asyncio

import pytest
from core import browser
from playwright.async_api import Error as PlaywrightError


def test_browser_idle_close(monkeypatch):
    """Sem uso por BROWSER_IDLE_TIMEOUT o Chromium fecha sozinho; reabre no proximo uso."""
    monkeypatch.setenv("BROWSER_IDLE_TIMEOUT", "0.4")

    async def scenario():
        try:
            async with browser.get_browser() as page:
                assert page is not None
        except PlaywrightError as exc:
            if "doesn't exist" in str(exc) or "playwright install" in str(exc):
                await browser._shutdown()
                return "skip"
            raise
        await asyncio.sleep(1.0)
        assert browser._browser is None, "browser deveria ter fechado por inatividade"

        # reabre no proximo uso
        async with browser.get_browser() as page2:
            assert page2 is not None
        await browser.close_pool()
        return "ok"

    resultado = asyncio.run(scenario())
    if resultado == "skip":
        pytest.skip("navegadores Playwright nao instalados (playwright install chromium)")
