"""API key authentication and rate limiting middleware."""

# NOTA: este módulo NÃO usa `from __future__ import annotations`.
# As dependências aqui são instâncias (APIKeyAuth/RateLimiter) usadas via
# Depends()/add_api_route; com anotações postergadas o FastAPI não resolve
# `Request` (sem __globals__ na instância) e exige um query param fantasma
# "request" → 422 em todas as rotas roteadas.

import hashlib
import time
from collections import defaultdict

from core.config import load_env, logger
from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

# ── API Key Auth ─────────────────────────────────────────────────────

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Public endpoints that don't require authentication
PUBLIC_PATHS = {
    "/",
    "/old",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}


def _load_api_keys() -> set[str]:
    """Load allowed API keys from environment."""
    env = load_env()
    keys = set()

    # Single key mode
    single = env.get("API_KEY", "")
    if single and not single.startswith("your_"):
        keys.add(single)

    # Multi-key mode (comma-separated)
    multi = env.get("API_KEYS", "")
    if multi:
        for k in multi.split(","):
            k = k.strip()
            if k and not k.startswith("your_"):
                keys.add(k)

    return keys


def _hash_key(key: str) -> str:
    """Hash an API key for safe comparison."""
    return hashlib.sha256(key.encode()).hexdigest()


class APIKeyAuth:
    """FastAPI dependency for API key authentication."""

    def __init__(self):
        self._keys = _load_api_keys()
        self._key_hashes = {_hash_key(k) for k in self._keys}
        if self._keys:
            logger.info("API Key auth: %d chave(s) configurada(s)", len(self._keys))
        else:
            logger.warning("API Key auth: NENHUMA chave configurada — API aberta")

    async def __call__(
        self,
        request: Request,
        api_key: str | None = Security(API_KEY_HEADER),
    ) -> str | None:
        # Skip auth for public paths
        path = request.url.path
        if path in PUBLIC_PATHS:
            return None

        # If no keys configured, allow all
        if not self._keys:
            return None

        # Validate key
        if not api_key:
            raise HTTPException(
                status_code=401,
                detail="API key required. Pass X-API-Key header.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        key_hash = _hash_key(api_key)
        if key_hash not in self._key_hashes:
            raise HTTPException(
                status_code=403,
                detail="Invalid API key",
            )

        return api_key


# Singleton dependency
api_key_auth = APIKeyAuth()


# ── Rate Limiter ─────────────────────────────────────────────────────


class RateLimiter:
    """Simple in-memory rate limiter using sliding window."""

    def __init__(self, requests_per_minute: int = 60, requests_per_hour: int = 1000):
        self.rpm = requests_per_minute
        self.rph = requests_per_hour
        self._minute_windows: dict[str, list[float]] = defaultdict(list)
        self._hour_windows: dict[str, list[float]] = defaultdict(list)

    def _client_id(self, request: Request) -> str:
        """Get client identifier (IP or API key)."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _cleanup(self, window: list[float], window_seconds: float) -> list[float]:
        """Remove old entries from a window."""
        cutoff = time.time() - window_seconds
        return [t for t in window if t > cutoff]

    def check(self, request: Request) -> None:
        """Check rate limit. Raises 429 if exceeded."""
        client = self._client_id(request)
        now = time.time()

        # Check per-minute limit
        self._minute_windows[client] = self._cleanup(self._minute_windows[client], 60)
        if len(self._minute_windows[client]) >= self.rpm:
            retry_after = int(self._minute_windows[client][0] + 60 - now) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {self.rpm} req/min",
                headers={"Retry-After": str(retry_after)},
            )

        # Check per-hour limit
        self._hour_windows[client] = self._cleanup(self._hour_windows[client], 3600)
        if len(self._hour_windows[client]) >= self.rph:
            retry_after = int(self._hour_windows[client][0] + 3600 - now) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {self.rph} req/hour",
                headers={"Retry-After": str(retry_after)},
            )

        # Record this request
        self._minute_windows[client].append(now)
        self._hour_windows[client].append(now)

    def __call__(self, request: Request) -> None:
        self.check(request)


# Singleton dependency
rate_limiter = RateLimiter()
