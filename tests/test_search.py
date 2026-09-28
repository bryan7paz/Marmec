"""Tests for the advanced search: accents, multi-word AND, quoted phrase."""

from __future__ import annotations

import pytest
from api.database import SessionLocal, get_db
from api.main import app
from api.middleware import api_key_auth
from api.models import RegulatoryAnalysis
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    async def override_auth():
        return None

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[api_key_auth] = override_auth
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def seeded():
    """Insert test rows used by all search tests; clean up afterwards."""
    db = SessionLocal()
    rows = [
        RegulatoryAnalysis(
            id="srch-a",
            source_id="iacs",
            source_name="IACS",
            norma="Segurança Marítima - Novo Requisito",
            acao_sugerida="Revisar procedimento de segurança a bordo",
            documento_hash="hash-srch-a",
        ),
        RegulatoryAnalysis(
            id="srch-b",
            source_id="imo",
            source_name="IMO",
            norma="Circular Radio Accounting",
            requisito="MMC-169",
            documento_hash="hash-srch-b",
        ),
        RegulatoryAnalysis(
            id="srch-c",
            source_id="imo",
            source_name="IMO",
            norma="Radio Resolução",
            itens_modificados="accounting revisado",
            documento_hash="hash-srch-c",
        ),
    ]
    for r in rows:
        db.add(r)
    db.commit()
    db.close()
    yield
    db = SessionLocal()
    for rid in ("srch-a", "srch-b", "srch-c"):
        obj = db.get(RegulatoryAnalysis, rid)
        if obj:
            db.delete(obj)
    db.commit()
    db.close()


def _ids(resp) -> set[str]:
    return {i["id"] for i in resp.json()["items"]}


class TestAccentInsensitive:
    def test_query_without_accent_finds_accented_text(self, client, seeded):
        resp = client.get("/regs/?q=seguranca")
        assert resp.status_code == 200
        assert "srch-a" in _ids(resp)

    def test_query_with_accent_finds_accented_text(self, client, seeded):
        resp = client.get("/regs/", params={"q": "segurança"})
        assert resp.status_code == 200
        assert "srch-a" in _ids(resp)

    def test_query_with_accent_finds_plain_text(self, client, seeded):
        # "Rádio" in norma, query "radio" without accent
        resp = client.get("/regs/", params={"q": "rádio"})
        found = _ids(resp)
        assert "srch-c" in found  # "Radio Resolução" (text has accent)

    def test_uppercase_query(self, client, seeded):
        resp = client.get("/regs/", params={"q": "SEGURANÇA"})
        assert "srch-a" in _ids(resp)


class TestMultiWordAnd:
    def test_words_across_different_fields_match(self, client, seeded):
        # "radio" in norma + "accounting" in itens_modificados (row C)
        resp = client.get("/regs/", params={"q": "radio accounting"})
        found = _ids(resp)
        assert "srch-b" in found  # both words in norma
        assert "srch-c" in found  # words split across fields

    def test_word_missing_excludes_row(self, client, seeded):
        # row A has no "radio" nor "accounting"
        resp = client.get("/regs/", params={"q": "radio accounting"})
        assert "srch-a" not in _ids(resp)

    def test_single_word_still_matches(self, client, seeded):
        resp = client.get("/regs/?q=radio")
        found = _ids(resp)
        assert "srch-b" in found
        assert "srch-c" in found


class TestQuotedPhrase:
    def test_phrase_matches_contiguous_text_only(self, client, seeded):
        # row B has the exact phrase; row C has the words split (not contiguous)
        resp = client.get("/regs/", params={"q": '"radio accounting"'})
        found = _ids(resp)
        assert "srch-b" in found
        assert "srch-c" not in found

    def test_phrase_is_accent_insensitive(self, client, seeded):
        resp = client.get("/regs/", params={"q": '"SEGURANÇA MARÍTIMA"'})
        assert "srch-a" in _ids(resp)


class TestNoMatch:
    def test_nonexistent_term_returns_zero(self, client, seeded):
        resp = client.get("/regs/?q=zzznaoexiste")
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []
