"""Tests for api/middleware.py — auth and rate limiter."""

from __future__ import annotations

import hashlib
import time
from unittest.mock import MagicMock, patch

import pytest
from api.middleware import (
    APIKeyAuth,
    RateLimiter,
    _hash_key,
    _load_api_keys,
)
from fastapi import HTTPException


class TestHashKey:
    def test_returns_sha256(self):
        result = _hash_key("test-key")
        expected = hashlib.sha256(b"test-key").hexdigest()
        assert result == expected

    def test_different_keys_different_hashes(self):
        assert _hash_key("key1") != _hash_key("key2")


class TestLoadApiKeys:
    @patch("api.middleware.load_env")
    def test_no_keys(self, mock_load):
        mock_load.return_value = {}
        assert _load_api_keys() == set()

    @patch("api.middleware.load_env")
    def test_single_key(self, mock_load):
        mock_load.return_value = {"API_KEY": "my-secret-key"}
        assert _load_api_keys() == {"my-secret-key"}

    @patch("api.middleware.load_env")
    def test_ignored_placeholder(self, mock_load):
        mock_load.return_value = {"API_KEY": "your_key_here"}
        assert _load_api_keys() == set()

    @patch("api.middleware.load_env")
    def test_multi_keys(self, mock_load):
        mock_load.return_value = {"API_KEYS": "key1,key2,key3"}
        assert _load_api_keys() == {"key1", "key2", "key3"}

    @patch("api.middleware.load_env")
    def test_multi_keys_with_spaces(self, mock_load):
        mock_load.return_value = {"API_KEYS": " key1 , key2 "}
        assert _load_api_keys() == {"key1", "key2"}

    @patch("api.middleware.load_env")
    def test_single_plus_multi(self, mock_load):
        mock_load.return_value = {"API_KEY": "single", "API_KEYS": "multi1,multi2"}
        result = _load_api_keys()
        assert result == {"single", "multi1", "multi2"}


class TestAPIKeyAuth:
    @patch("api.middleware.load_env")
    def test_no_keys_allows_all(self, mock_load):
        mock_load.return_value = {}
        auth = APIKeyAuth()
        request = MagicMock()
        request.url.path = "/some/path"
        import asyncio

        result = asyncio.run(auth(request, api_key=None))
        assert result is None

    @patch("api.middleware.load_env")
    def test_public_path_skips_auth(self, mock_load):
        mock_load.return_value = {"API_KEY": "secret"}
        auth = APIKeyAuth()
        request = MagicMock()
        request.url.path = "/health"
        import asyncio

        result = asyncio.run(auth(request, api_key=None))
        assert result is None

    @patch("api.middleware.load_env")
    def test_valid_key(self, mock_load):
        mock_load.return_value = {"API_KEY": "secret"}
        auth = APIKeyAuth()
        request = MagicMock()
        request.url.path = "/protected"
        import asyncio

        result = asyncio.run(auth(request, api_key="secret"))
        assert result == "secret"

    @patch("api.middleware.load_env")
    def test_invalid_key_raises_403(self, mock_load):
        mock_load.return_value = {"API_KEY": "secret"}
        auth = APIKeyAuth()
        request = MagicMock()
        request.url.path = "/protected"
        import asyncio

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(auth(request, api_key="wrong"))
        assert exc_info.value.status_code == 403

    @patch("api.middleware.load_env")
    def test_missing_key_raises_401(self, mock_load):
        mock_load.return_value = {"API_KEY": "secret"}
        auth = APIKeyAuth()
        request = MagicMock()
        request.url.path = "/protected"
        import asyncio

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(auth(request, api_key=None))
        assert exc_info.value.status_code == 401


class TestRateLimiter:
    def _make_request(self, client_host="127.0.0.1", forwarded=None):
        request = MagicMock()
        request.client.host = client_host
        request.headers = {}
        if forwarded:
            request.headers["x-forwarded-for"] = forwarded
        return request

    def test_allows_within_limit(self):
        limiter = RateLimiter(requests_per_minute=5, requests_per_hour=100)
        request = self._make_request()
        # Should not raise
        for _ in range(5):
            limiter.check(request)

    def test_exceeds_minute_limit(self):
        limiter = RateLimiter(requests_per_minute=3, requests_per_hour=1000)
        request = self._make_request()
        for _ in range(3):
            limiter.check(request)
        with pytest.raises(HTTPException) as exc_info:
            limiter.check(request)
        assert exc_info.value.status_code == 429

    def test_exceeds_hour_limit(self):
        limiter = RateLimiter(requests_per_minute=1000, requests_per_hour=2)
        request = self._make_request()
        for _ in range(2):
            limiter.check(request)
        with pytest.raises(HTTPException) as exc_info:
            limiter.check(request)
        assert exc_info.value.status_code == 429

    def test_different_clients_independent(self):
        limiter = RateLimiter(requests_per_minute=2, requests_per_hour=100)
        req1 = self._make_request(client_host="1.1.1.1")
        req2 = self._make_request(client_host="2.2.2.2")
        limiter.check(req1)
        limiter.check(req1)
        limiter.check(req2)  # Different client, should work
        with pytest.raises(HTTPException):
            limiter.check(req1)  # Same client, exceeded

    def test_forwarded_for_header(self):
        limiter = RateLimiter(requests_per_minute=1, requests_per_hour=100)
        req1 = self._make_request(forwarded="10.0.0.1, 10.0.0.2")
        req2 = self._make_request(forwarded="20.0.0.1")
        limiter.check(req1)
        with pytest.raises(HTTPException):
            limiter.check(req1)  # Same forwarded IP
        limiter.check(req2)  # Different forwarded IP

    def test_cleanup_removes_old_entries(self):
        limiter = RateLimiter(requests_per_minute=10, requests_per_hour=100)
        request = self._make_request()
        # Manually add old timestamps
        limiter._minute_windows["test"] = [time.time() - 120]  # 2 min ago
        limiter._hour_windows["test"] = [time.time() - 7200]  # 2 hours ago
        # Should not count old entries
        limiter.check(request)
        assert len(limiter._minute_windows["test"]) == 1

    def test_callable(self):
        limiter = RateLimiter(requests_per_minute=10, requests_per_hour=100)
        request = self._make_request()
        # __call__ delegates to check
        limiter(request)


class TestDependenteFantasma:
    """Regressão: Depends(instância) não pode gerar query param `request`.

    Com `from __future__ import annotations` no módulo do middleware, o FastAPI
    não resolve `Request` em instâncias (sem __globals__) e exigia um query
    param fantasma "request" → 422 em toda rota roteada (os testes de rota não
    pegavam porque sobrescrevem a dependência).
    """

    def test_api_key_auth_sem_query_params(self):
        from api.middleware import api_key_auth
        from fastapi.dependencies.utils import get_dependant

        dependant = get_dependant(path="/x", call=api_key_auth)
        assert [p.name for p in dependant.query_params] == []

    def test_rota_rounada_sem_override_retorna_200(self):
        from api.main import app
        from fastapi.testclient import TestClient

        # Sem dependency_overrides — exatamente como em produção
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/regs/?page=1&size=5")
            assert resp.status_code == 200
            assert "items" in resp.json()
