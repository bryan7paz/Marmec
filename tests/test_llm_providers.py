"""Tests for core/llm_providers.py — multi-provider LLM gateway."""

from __future__ import annotations

from unittest.mock import patch

from core.llm_providers import (
    generate_structured,
    list_providers,
)


class TestListProviders:
    def test_returns_list(self):
        result = list_providers()
        assert isinstance(result, list)

    def test_each_entry_has_fields(self):
        result = list_providers()
        for p in result:
            assert "id" in p
            assert "name" in p
            assert "active" in p
            assert "configured" in p


class TestGenerateStructured:
    @patch("core.llm_providers._get_env")
    def test_raises_when_no_provider(self, mock_env):
        mock_env.return_value = ""
        try:
            generate_structured("sys", "usr")
            raise AssertionError("Should have raised")
        except Exception:
            pass


class TestGetEnv:
    def test_reads_os_environ_first(self, monkeypatch):
        monkeypatch.setenv("LLMP_TEST_KEY", "from-os")
        from core.llm_providers import _get_env

        assert _get_env("LLMP_TEST_KEY") == "from-os"

    def test_falls_back_to_secrets_env(self, monkeypatch, tmp_path):
        """Regressão: chaves em config/secrets.env devem ser vistas pelo provedor.

        Antes do fix _get_env lia só os.environ — segredos do dashboard
        nunca chegavam ao provedor (\"Nenhum provedor LLM disponível\").
        """
        monkeypatch.delenv("LLMP_TEST_KEY", raising=False)
        (tmp_path / "secrets.env").write_text("LLMP_TEST_KEY=from-file\n", encoding="utf-8")
        monkeypatch.setattr("core.config.CONFIG_DIR", tmp_path)

        from core.llm_providers import _get_env

        assert _get_env("LLMP_TEST_KEY") == "from-file"

    def test_missing_everywhere_returns_fallback(self, monkeypatch):
        monkeypatch.delenv("LLMP_TEST_KEY", raising=False)
        monkeypatch.setattr("core.config.CONFIG_DIR", __import__("pathlib").Path("/nonexistent"))
        from core.llm_providers import _get_env

        assert _get_env("LLMP_TEST_KEY", "dflt") == "dflt"
