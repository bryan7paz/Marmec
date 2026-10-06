"""Tests for crawler/runner.py — period filter and ad-hoc source building."""

from __future__ import annotations

from datetime import date

from crawler.runner import filter_by_period, source_from_url
from crawler.spiders.base import Item


def _item(title: str, published: str | None) -> Item:
    return Item(title=title, url=f"https://example.com/{title}.pdf", published_date=published)


class TestFilterByPeriod:
    def test_no_period_keeps_everything(self):
        items = [_item("a", "2024-01-01"), _item("b", None)]
        kept, stats = filter_by_period(items, None, None)
        assert len(kept) == 2
        assert stats["discarded"] == 0

    def test_inside_period_kept(self):
        items = [_item("a", "2024-06-15")]
        kept, stats = filter_by_period(items, date(2024, 1, 1), date(2024, 12, 31))
        assert len(kept) == 1
        assert stats["discarded"] == 0

    def test_outside_period_discarded(self):
        items = [_item("old", "2021-05-15"), _item("new", "2024-06-15")]
        kept, stats = filter_by_period(items, date(2024, 1, 1), date(2024, 12, 31))
        assert [i.title for i in kept] == ["new"]
        assert stats == {"total": 2, "kept": 1, "discarded": 1, "no_date": 0}

    def test_no_date_kept(self):
        """Links without a visible date are kept — can't discard the unseen."""
        items = [_item("mystery", None), _item("old", "2020-01-01")]
        kept, stats = filter_by_period(items, date(2024, 1, 1), date(2024, 12, 31))
        assert [i.title for i in kept] == ["mystery"]
        assert stats["no_date"] == 1
        assert stats["discarded"] == 1

    def test_only_from_or_only_to(self):
        items = [_item("a", "2024-06-15"), _item("b", "2024-02-10")]
        kept, _ = filter_by_period(items, date(2024, 5, 1), None)
        assert [i.title for i in kept] == ["a"]
        kept2, _ = filter_by_period(items, None, date(2024, 5, 1))
        assert [i.title for i in kept2] == ["b"]

    def test_garbage_date_treated_as_no_date(self):
        items = [_item("weird", "not-a-date")]
        kept, stats = filter_by_period(items, date(2024, 1, 1), date(2024, 12, 31))
        assert len(kept) == 1
        assert stats["no_date"] == 1

    def test_boundary_dates_included(self):
        items = [_item("first", "2024-01-01"), _item("last", "2024-12-31")]
        kept, _ = filter_by_period(items, date(2024, 1, 1), date(2024, 12, 31))
        assert len(kept) == 2


class TestSourceFromUrl:
    def test_domain_as_id(self):
        src = source_from_url("https://www.iacs.org.uk/normas")
        assert src["id"] == "iacs.org.uk"
        assert src["name"] == "iacs.org.uk"
        assert src["url"] == "https://www.iacs.org.uk/normas"
        assert src["type"] == "html_list"

    def test_strips_www(self):
        assert source_from_url("https://www.example.com/x")["id"] == "example.com"

    def test_keeps_subdomain(self):
        assert source_from_url("https://docs.imo.org/en/Search")["id"] == "docs.imo.org"
