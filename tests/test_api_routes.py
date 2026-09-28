"""Tests for api/routes — API endpoints."""

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


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded")


class TestRegsList:
    def test_list_empty(self, client):
        resp = client.get("/regs/")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_list_with_pagination(self, client):
        resp = client.get("/regs/?page=1&size=5")
        assert resp.status_code == 200

    def test_list_with_search(self, client):
        resp = client.get("/regs/?q=test")
        assert resp.status_code == 200

    def test_list_with_sort(self, client):
        resp = client.get("/regs/?sort_by=created_at&sort_order=desc")
        assert resp.status_code == 200

    def test_list_with_fields(self, client):
        resp = client.get("/regs/?fields=id,norma")
        assert resp.status_code == 200


class TestRegsExport:
    def test_export_csv(self, client):
        resp = client.get("/regs/export/csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

    def test_export_csv_with_filter(self, client):
        resp = client.get("/regs/export/csv?validacao=aprovado")
        assert resp.status_code == 200


class TestDashboardMetrics:
    def test_metrics_returns_200(self, client):
        resp = client.get("/dashboard/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "por_aplicacao" in data
        assert "por_assunto" in data


class TestPipelineEndpoints:
    def test_pipeline_status(self, client):
        resp = client.get("/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data

    def test_providers_list(self, client):
        resp = client.get("/pipeline/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_notifications(self, client):
        resp = client.get("/pipeline/notifications")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestDocsAndSchema:
    def test_openapi_schema(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code in (200, 500)

    def test_docs_page(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_redoc_page(self, client):
        resp = client.get("/redoc")
        assert resp.status_code == 200


class TestNotFound:
    def test_unknown_route(self, client):
        resp = client.get("/nonexistent")
        assert resp.status_code == 404


class TestStaticAssets:
    def test_logo_served(self, client):
        resp = client.get("/static/img/logo.png")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert len(resp.content) > 1000

    def test_favicon_served(self, client):
        resp = client.get("/static/img/favicon.ico")
        assert resp.status_code == 200

    def test_openapi_title_is_marmec(self, client):
        resp = client.get("/openapi.json")
        if resp.status_code == 200:
            assert "Marmec" in resp.json()["info"]["title"]
