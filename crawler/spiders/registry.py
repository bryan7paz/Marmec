"""Spider registry: maps a URL/source config to a concrete spider instance.

Domain-based detection: pasting a ``docs.imo.org`` link requires login,
so it routes to the IMODOCS adapter automatically.
"""

from __future__ import annotations

from typing import Any

from .adapters import ADAPTER_MAP
from .base import BaseSpider
from .html_list import HtmlListSpider
from .login import LoginSpider
from .pdf_list import PdfListSpider
from .sitemap import SitemapSpider

TYPE_MAP: dict[str, type[BaseSpider]] = {
    "html_list": HtmlListSpider,
    "pdf_list": PdfListSpider,
    "sitemap": SitemapSpider,
    "login": LoginSpider,
}

# Domains that need a dedicated adapter (login/portal-specific parsing)


def get_spider(source: dict[str, Any]) -> BaseSpider:
    source_id = source.get("id", "")
    url = source.get("url", "")

    # 1) Adapter registered by source id (legacy config)
    if source_id in ADAPTER_MAP:
        return ADAPTER_MAP[source_id](source)

    # 2) Domain detection (user-pasted URL)
    if "docs.imo.org" in url:
        from .adapters import ImodocsAdapter

        return ImodocsAdapter(source)

    spider_type = source.get("type", "html_list")
    cls = TYPE_MAP.get(spider_type, HtmlListSpider)
    return cls(source)
