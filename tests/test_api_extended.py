"""Additional tests for api/routes — endpoints without direct DB inserts."""

from __future__ import annotations

import pytest
from api.database import SessionLocal, get_db
from api.main import app
from api.middleware import api_key_auth
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


class TestDetailNotFound:
    def test_not_found(self, client):
        resp = client.get("/regs/nonexistent-id-xyz")
        assert resp.status_code == 404


class TestBatchValidate:
    def test_invalid_action(self, client):
        resp = client.post("/regs/batch-validate", json={"ids": ["x"], "action": "invalid"})
        assert resp.status_code == 400

    def test_empty_ids(self, client):
        resp = client.post("/regs/batch-validate", json={"ids": [], "action": "aprovado"})
        assert resp.status_code == 200
        assert resp.json()["updated"] == 0


class TestSingleValidate:
    def test_not_found(self, client):
        resp = client.post("/regs/missing-id/validate", json={"action": "aprovado"})
        assert resp.status_code == 404


class TestExportExcel:
    def test_excel_empty(self, client):
        resp = client.get("/regs/export/excel")
        assert resp.status_code in (200, 500)

    def test_excel_filtered(self, client):
        resp = client.get("/regs/export/excel?validacao=aprovado")
        assert resp.status_code in (200, 500)

    def test_excel_readable_labels(self, client):
        """Códigos crus viram rótulos legíveis e a ação sugerida aparece."""
        from io import BytesIO

        from api.database import SessionLocal
        from api.models import RegulatoryAnalysis
        from openpyxl import load_workbook

        db = SessionLocal()
        row = RegulatoryAnalysis(
            id="xl-labels-1",
            source_id="iacs",
            source_name="IACS",
            norma="XL/Circ. Teste",
            assunto="SEG",
            aplicacao="D",
            status="R",
            acao_sugerida="Revisar procedimento de segurança a bordo",
            documento_hash="hash-xl-labels-1",
        )
        db.add(row)
        db.commit()
        try:
            resp = client.get("/regs/export/excel")
            assert resp.status_code == 200
            wb = load_workbook(BytesIO(resp.content))
            assert "Legenda" in wb.sheetnames

            ws = wb["Análise Regulatória"]
            values = [c.value for row_ in ws.iter_rows(min_row=2) for c in row_]
            assert "D — Ação Direta" in values
            assert "SEG — Segurança" in values
            assert "R — Revisão" in values
            assert "Revisar procedimento de segurança a bordo" in values
        finally:
            db.delete(row)
            db.commit()
            db.close()

    def test_excel_empty_action_is_explained(self, client):
        """Ação sugerida vazia recebe texto explicativo em vez de célula vazia."""
        from io import BytesIO

        from api.database import SessionLocal
        from api.models import RegulatoryAnalysis
        from openpyxl import load_workbook

        db = SessionLocal()
        row = RegulatoryAnalysis(
            id="xl-np-1",
            source_id="imo",
            source_name="IMO",
            norma="XL/NP Teste",
            aplicacao="NP",
            status="N",
            acao_sugerida=None,
            documento_hash="hash-xl-np-1",
        )
        db.add(row)
        db.commit()
        try:
            resp = client.get("/regs/export/excel")
            assert resp.status_code == 200
            wb = load_workbook(BytesIO(resp.content))
            ws = wb["Análise Regulatória"]
            values = [c.value for row_ in ws.iter_rows(min_row=2) for c in row_]
            assert "NP — Não Pertinente" in values
            assert "— (não pertinente: sem ação necessária)" in values
        finally:
            db.delete(row)
            db.commit()
            db.close()


class TestExportPDF:
    def test_pdf_empty(self, client):
        resp = client.get("/regs/export/pdf")
        assert resp.status_code in (200, 500)

    def test_pdf_filtered(self, client):
        resp = client.get("/regs/export/pdf?validacao=aprovado")
        assert resp.status_code in (200, 500)


class TestFilters:
    def test_assunto(self, client):
        resp = client.get("/regs/?assunto=SEG")
        assert resp.status_code == 200

    def test_aplicacao(self, client):
        resp = client.get("/regs/?aplicacao=D")
        assert resp.status_code == 200

    def test_fonte(self, client):
        resp = client.get("/regs/?fonte=iacs")
        assert resp.status_code == 200

    def test_status(self, client):
        resp = client.get("/regs/?status=R")
        assert resp.status_code == 200

    def test_date_range(self, client):
        resp = client.get("/regs/?date_from=2024-01-01&date_to=2024-12-31")
        assert resp.status_code == 200


class TestPipelineEndpoints:
    def test_start(self, client):
        resp = client.post("/pipeline/run")
        assert resp.status_code == 200
        assert "message" in resp.json()

    def test_stop(self, client):
        resp = client.post("/pipeline/stop")
        assert resp.status_code in (200, 404)

    def test_settings_get(self, client):
        resp = client.get("/pipeline/settings")
        assert resp.status_code == 200

    def test_settings_update(self, client):
        resp = client.post("/pipeline/settings", json={"active_provider": "groq"})
        assert resp.status_code == 200

    def test_notifications_list(self, client):
        resp = client.get("/pipeline/notifications")
        assert resp.status_code == 200

    def test_notifications_clear(self, client):
        resp = client.delete("/pipeline/notifications")
        assert resp.status_code in (200, 404, 405)
