"""Multi-provider LLM gateway — supports Google Gemini + any OpenAI-compatible API.

Providers configured in config/llm.yaml with fallback chain.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import yaml

from core.config import logger

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "llm.yaml"

MAX_RETRIES = 3
RETRY_DELAY = 3


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"active": "gemini", "providers": {}}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_env(key: str, fallback: str = "") -> str:
    import os

    if key in os.environ:
        return os.environ[key]
    # secrets.env (config/secrets.env) — chaves salvas no dashboard ficam lá
    from core.config import load_env

    return load_env().get(key, fallback)


# ── Provider implementations ─────────────────────────────────────


def _call_gemini(system_prompt: str, user_prompt: str, model: str, api_key: str) -> dict[str, Any]:
    """Google Gemini via google-generativeai."""
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(
        model,
        generation_config={"response_mime_type": "application/json", "temperature": 0.0},
        system_instruction=system_prompt,
    )
    response = m.generate_content(user_prompt)
    raw = (response.text or "{}").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def _call_openai_compatible(
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """Any OpenAI-compatible API (Groq, NVIDIA, OpenRouter, Cerebras, etc.)."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        temperature=0.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw = response.choices[0].message.content or "{}"
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


# ── Provider registry ────────────────────────────────────────────

PROVIDERS = {
    "gemini": {
        "name": "Google Gemini",
        "env_key": "GOOGLE_API_KEY",
        "call": _call_gemini,
        "needs_base_url": False,
    },
    "groq": {
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "call": _call_openai_compatible,
        "needs_base_url": True,
    },
    "nvidia": {
        "name": "NVIDIA NIM",
        "env_key": "NVIDIA_API_KEY",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "call": _call_openai_compatible,
        "needs_base_url": True,
    },
    "openrouter": {
        "name": "OpenRouter",
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "call": _call_openai_compatible,
        "needs_base_url": True,
    },
    "cerebras": {
        "name": "Cerebras",
        "env_key": "CEREBRAS_API_KEY",
        "base_url": "https://api.cerebras.ai/v1",
        "call": _call_openai_compatible,
        "needs_base_url": True,
    },
    "mistral": {
        "name": "Mistral AI",
        "env_key": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "call": _call_openai_compatible,
        "needs_base_url": True,
    },
    "openai": {
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "call": _call_openai_compatible,
        "needs_base_url": True,
    },
    "custom": {
        "name": "Custom (OpenAI-compatible)",
        "env_key": "CUSTOM_LLM_API_KEY",
        "call": _call_openai_compatible,
        "needs_base_url": True,
    },
}


# ── Public API ───────────────────────────────────────────────────


def generate_structured(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Call the active LLM provider with retry + fallback chain.

    Tries the active provider first, then falls back to others in order.
    """
    cfg = _load_config()
    active = cfg.get("active", "gemini")
    providers_cfg = cfg.get("providers", {})
    fallback_chain = cfg.get("fallback_chain", [])

    # Build execution order: active first, then fallbacks
    chain = [active] + [p for p in fallback_chain if p != active]

    last_exc: Exception | None = None
    for provider_id in chain:
        provider = PROVIDERS.get(provider_id)
        if not provider:
            logger.warning("Provedor desconhecido: %s", provider_id)
            continue

        pcfg = providers_cfg.get(provider_id, {})
        if not pcfg.get("enabled", True):
            continue

        model = pcfg.get("model", "")
        api_key = _get_env(provider["env_key"], pcfg.get("api_key", ""))
        base_url = pcfg.get("base_url", provider.get("base_url", ""))

        if not api_key:
            logger.debug("Provedor %s sem API key, pulando", provider_id)
            continue

        if not model:
            logger.warning("Provedor %s sem modelo configurado", provider_id)
            continue

        logger.info("Tentando provedor: %s (modelo: %s)", provider["name"], model)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                call_fn = provider["call"]
                if provider["needs_base_url"]:
                    result = call_fn(system_prompt, user_prompt, model, api_key, base_url)
                else:
                    result = call_fn(system_prompt, user_prompt, model, api_key)
                logger.info("Sucesso com %s após %d tentativa(s)", provider["name"], attempt)
                return result
            except Exception as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "%s tentativa %d/%d falhou: %s — retry em %ds",
                        provider["name"],
                        attempt,
                        MAX_RETRIES,
                        exc,
                        RETRY_DELAY * attempt,
                    )
                    time.sleep(RETRY_DELAY * attempt)
                else:
                    logger.error(
                        "%s falhou após %d tentativas: %s", provider["name"], MAX_RETRIES, exc
                    )
                    break  # Try next provider in fallback chain

    raise last_exc or RuntimeError("Nenhum provedor LLM disponível")


def list_providers() -> list[dict[str, Any]]:
    """Return available providers with their status."""
    cfg = _load_config()
    active = cfg.get("active", "gemini")
    providers_cfg = cfg.get("providers", {})
    result = []

    for pid, pinfo in PROVIDERS.items():
        pcfg = providers_cfg.get(pid, {})
        api_key = _get_env(pinfo["env_key"], pcfg.get("api_key", ""))
        result.append(
            {
                "id": pid,
                "name": pinfo["name"],
                "enabled": pcfg.get("enabled", True),
                "active": pid == active,
                "configured": bool(api_key),
                "model": pcfg.get("model", ""),
            }
        )
    return result
