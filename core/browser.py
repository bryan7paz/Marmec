"""Shared Playwright browser pool — reuse one Chromium instance across requests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from core.config import logger

_browser = None
_pw = None
_lock = asyncio.Lock()
_idle_task: asyncio.Task | None = None


def _idle_timeout() -> float:
    """Seconds of inactivity before Chromium is closed to free RAM (0 disables)."""
    try:
        return float(os.environ.get("BROWSER_IDLE_TIMEOUT", "300"))
    except ValueError:
        return 300.0


async def _shutdown() -> None:
    """Close browser and stop the Playwright driver (frees Chromium + node)."""
    global _browser, _pw
    if _browser is not None and _browser.is_connected():
        await _browser.close()
    _browser = None
    if _pw is not None:
        await _pw.stop()
        _pw = None


def _schedule_idle_close() -> None:
    """Close the pooled browser after a period with no active use."""
    global _idle_task
    timeout = _idle_timeout()
    if timeout <= 0:
        return
    if _idle_task and not _idle_task.done():
        _idle_task.cancel()

    async def _closer() -> None:
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return
        await _shutdown()
        logger.info("Browser fechado apos %gs de inatividade (RAM liberada)", timeout)

    _idle_task = asyncio.create_task(_closer())


@asynccontextmanager
async def get_browser() -> AsyncGenerator:
    """Yield a shared Playwright Chromium browser instance.

    Lazily initialised on first use; reused across all subsequent calls.
    A new page is created per call and closed on exit. After
    BROWSER_IDLE_TIMEOUT seconds without use (default 300) the browser is
    closed automatically to keep the app light; it reopens on next use.
    """
    global _browser, _pw, _idle_task
    from playwright.async_api import async_playwright

    async with _lock:
        if _idle_task and not _idle_task.done():
            _idle_task.cancel()
        if _pw is None:
            _pw = await async_playwright().start()
        if _browser is None or not _browser.is_connected():
            logger.info("Iniciando browser pool compartilhado...")
            _browser = await _pw.chromium.launch(headless=True)

    page = await _browser.new_page()
    try:
        yield page
    finally:
        await page.close()
        _schedule_idle_close()


async def close_pool() -> None:
    """Shut down the shared browser pool."""
    global _idle_task
    if _idle_task and not _idle_task.done():
        _idle_task.cancel()
        _idle_task = None
    was_active = _browser is not None or _pw is not None
    await _shutdown()
    if was_active:
        logger.info("Browser pool fechado.")
