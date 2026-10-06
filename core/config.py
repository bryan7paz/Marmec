"""Shared configuration, environment loading and validation."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_prompt() -> dict[str, Any]:
    return _load_yaml("prompt.yaml")


def load_env() -> dict[str, str]:
    """Load environment overrides from config/secrets.env if present.

    OS environment variables take precedence over file values.
    """
    env = dict(os.environ)
    env_path = CONFIG_DIR / "secrets.env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key, value.strip())
    return env


_REQUIRED_VARS = ("GOOGLE_API_KEY", "DATABASE_URL")


def validate_env(env: dict[str, str]) -> list[str]:
    """Check that required environment variables are set.

    Returns a list of missing variable names (empty if all OK).
    """
    missing = []
    for var in _REQUIRED_VARS:
        val = env.get(var, "")
        if not val or val.startswith("your_"):
            missing.append(var)
    return missing


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the root pipeline logger."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("regulatory")


logger = setup_logging()
