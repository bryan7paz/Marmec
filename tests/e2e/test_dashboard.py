"""E2E tests for the dashboard."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


class TestDashboard:
    """Test dashboard navigation and display."""

    def test_dashboard_loads(self, page_context, base_url):
        """Dashboard page loads successfully."""
        page = page_context.new_page()
        try:
            response = page.goto(base_url, wait_until="domcontentloaded")
            assert response.status == 200
            assert "Marmec" in page.title() or "Dashboard" in page.content()
        finally:
            page.close()

    def test_dashboard_has_sidebar(self, page_context, base_url):
        """Dashboard has navigation sidebar."""
        page = page_context.new_page()
        try:
            page.goto(base_url, wait_until="domcontentloaded")
            sidebar = page.query_selector(".sidebar")
            assert sidebar is not None
        finally:
            page.close()

    def test_dashboard_has_kpi_cards(self, page_context, base_url):
        """Dashboard displays KPI cards."""
        page = page_context.new_page()
        try:
            page.goto(base_url, wait_until="domcontentloaded")
            # Check for KPI elements
            content = page.content()
            assert "Documentos" in content or "Análises" in content
        finally:
            page.close()

    def test_navigation_to_documents(self, page_context, base_url):
        """Can navigate to documents section."""
        page = page_context.new_page()
        try:
            page.goto(base_url, wait_until="domcontentloaded")
            # Click on documents nav link
            page.click("text=Documentos")
            page.wait_for_timeout(500)
            # Verify section is visible
            content = page.content()
            assert "Documentos" in content
        finally:
            page.close()

    def test_navigation_to_pipeline(self, page_context, base_url):
        """Can navigate to pipeline section."""
        page = page_context.new_page()
        try:
            page.goto(base_url, wait_until="domcontentloaded")
            page.click("text=Pipeline")
            page.wait_for_timeout(500)
            content = page.content()
            assert "Pipeline" in content
        finally:
            page.close()

    def test_navigation_to_providers(self, page_context, base_url):
        """Can navigate to providers section."""
        page = page_context.new_page()
        try:
            page.goto(base_url, wait_until="domcontentloaded")
            page.click("text=Provedores IA")
            page.wait_for_timeout(500)
            content = page.content()
            assert "Provedores" in content
        finally:
            page.close()

    def test_navigation_to_settings(self, page_context, base_url):
        """Can navigate to settings section."""
        page = page_context.new_page()
        try:
            page.goto(base_url, wait_until="domcontentloaded")
            page.click("text=Configurações")
            page.wait_for_timeout(500)
            content = page.content()
            assert "Configurações" in content or "Chaves" in content
        finally:
            page.close()
