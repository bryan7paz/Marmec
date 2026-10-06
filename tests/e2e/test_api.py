"""E2E tests for the API endpoints."""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.e2e


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_returns_ok(self, api_url):
        """Health endpoint returns status."""
        response = httpx.get(f"{api_url}/health", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded")


class TestRegsAPI:
    """Test regulations API endpoints."""

    def test_list_regs(self, api_url):
        """GET /regs/ returns paginated list."""
        response = httpx.get(f"{api_url}/regs/", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data

    def test_list_regs_with_search(self, api_url):
        """GET /regs/?q= search works."""
        response = httpx.get(f"{api_url}/regs/?q=test", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

    def test_list_regs_with_filters(self, api_url):
        """GET /regs/ with filters works."""
        response = httpx.get(
            f"{api_url}/regs/?assunto=SEG&aplicacao=D&status=R",
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

    def test_list_regs_with_sort(self, api_url):
        """GET /regs/ with sorting works."""
        response = httpx.get(
            f"{api_url}/regs/?sort_by=norma&sort_order=asc",
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()
        assert "sort_by" in data
        assert data["sort_by"] == "norma"

    def test_list_regs_with_date_range(self, api_url):
        """GET /regs/ with date range filter works."""
        response = httpx.get(
            f"{api_url}/regs/?date_from=2024-01-01&date_to=2024-12-31",
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

    def test_list_regs_with_field_selection(self, api_url):
        """GET /regs/ with field selection works."""
        response = httpx.get(
            f"{api_url}/regs/?fields=norma,assunto,status",
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

    def test_export_csv(self, api_url):
        """GET /regs/export/csv returns CSV."""
        response = httpx.get(f"{api_url}/regs/export/csv", timeout=10)
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    def test_export_excel(self, api_url):
        """GET /regs/export/excel returns Excel."""
        response = httpx.get(f"{api_url}/regs/export/excel", timeout=10)
        assert response.status_code == 200
        assert "spreadsheet" in response.headers.get("content-type", "")

    def test_export_pdf(self, api_url):
        """GET /regs/export/pdf returns PDF (503 if weasyprint/GTK optional deps missing)."""
        response = httpx.get(f"{api_url}/regs/export/pdf", timeout=30)
        assert response.status_code in (200, 503)


class TestPipelineAPI:
    """Test pipeline API endpoints."""

    def test_pipeline_status(self, api_url):
        """GET /pipeline/status returns status."""
        response = httpx.get(f"{api_url}/pipeline/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "running" in data
        assert "step" in data

    def test_list_providers(self, api_url):
        """GET /pipeline/providers returns provider list."""
        response = httpx.get(f"{api_url}/pipeline/providers", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_get_settings(self, api_url):
        """GET /pipeline/settings returns settings."""
        response = httpx.get(f"{api_url}/pipeline/settings", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_get_notifications(self, api_url):
        """GET /pipeline/notifications returns notifications."""
        response = httpx.get(f"{api_url}/pipeline/notifications", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
