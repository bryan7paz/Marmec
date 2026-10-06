"""Tests for crawler/spiders/html_list.py."""

from __future__ import annotations

from crawler.spiders.html_list import HtmlListSpider


class TestHtmlListSpider:
    def _make_spider(self, **overrides) -> HtmlListSpider:
        source = {"id": "test", "url": "https://example.com/"}
        source.update(overrides.pop("source", {}))
        return HtmlListSpider(source=source, **overrides)

    def test_extract_links_basic(self):
        spider = self._make_spider()
        html = """
        <html><body>
        <a href="/doc1.pdf">Circular 001</a>
        <a href="/doc2.html">Resolution 002</a>
        <a href="/page">About</a>
        </body></html>
        """
        items = spider._extract_links(html)
        urls = [i.url for i in items]
        assert "https://example.com/doc1.pdf" in urls
        assert "https://example.com/doc2.html" in urls

    def test_link_pattern_filters(self):
        spider = self._make_spider(
            source={"id": "test", "url": "https://example.com/", "link_pattern": r"\.pdf$"}
        )
        html = """
        <html><body>
        <a href="/doc1.pdf">Circular 001</a>
        <a href="/page.html">Page</a>
        <a href="/doc2.pdf">Resolution 002</a>
        </body></html>
        """
        items = spider._extract_links(html)
        urls = [i.url for i in items]
        assert all(u.endswith(".pdf") for u in urls)
        assert len(urls) == 2

    def test_filters_keywords(self):
        spider = self._make_spider(
            source={"id": "test", "url": "https://example.com/", "filters": ["circular"]}
        )
        html = """
        <html><body>
        <a href="/c1.pdf">Circular 001</a>
        <a href="/r1.pdf">Resolution 001</a>
        </body></html>
        """
        items = spider._extract_links(html)
        assert len(items) == 1
        assert "Circular" in items[0].title

    def test_no_duplicates(self):
        spider = self._make_spider()
        html = """
        <html><body>
        <a href="/doc.pdf">Doc</a>
        <a href="/doc.pdf">Doc Again</a>
        </body></html>
        """
        items = spider._extract_links(html)
        assert len(items) == 1

    def test_empty_href_ignored(self):
        spider = self._make_spider()
        html = """
        <html><body>
        <a href="">Empty</a>
        <a>No href</a>
        <a href="/doc.pdf">Valid</a>
        </body></html>
        """
        items = spider._extract_links(html)
        assert len(items) == 1

    # ── Date extraction ────────────────────────────────────────────

    def _dates(self, html: str) -> list[str | None]:
        spider = self._make_spider()
        return [i.published_date for i in spider._extract_links(html)]

    def test_date_from_anchor_text_iso(self):
        html = '<a href="/n.pdf">Norma 001 de 2024-05-15</a>'
        assert self._dates(html) == ["2024-05-15"]

    def test_date_from_anchor_text_br(self):
        html = '<a href="/n.pdf">Circular 001 de 15/05/2024</a>'
        assert self._dates(html) == ["2024-05-15"]

    def test_date_from_context_row(self):
        html = """
        <tr><td><a href="/n.pdf">Marine Notice 003</a></td>
            <td>10 May 2023</td></tr>
        """
        assert self._dates(html) == ["2023-05-10"]

    def test_date_from_context_pt_month(self):
        html = '<li><a href="/n.pdf">Norma 9</a> publicada em 3 de março de 2024</li>'
        assert self._dates(html) == ["2024-03-03"]

    def test_date_from_url_path(self):
        html = '<a href="/2024/07/norma.pdf">Resolution 002</a>'
        assert self._dates(html) == ["2024-07-01"]

    def test_no_date_returns_none(self):
        html = '<a href="/n.pdf">Circular 004 sem data</a>'
        assert self._dates(html) == [None]

    def test_invalid_date_returns_none(self):
        html = '<a href="/n.pdf">Circular 32/13/2024</a>'
        assert self._dates(html) == [None]
