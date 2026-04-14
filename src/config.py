"""
Configuration loader — reads config.yaml with environment variable substitution.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml


_CONFIG: dict | None = None
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.yaml"


def _substitute_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} patterns with environment variable values."""
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")
    return re.sub(r"\$\{(\w+)}", replacer, value)


def _walk_and_substitute(obj):
    """Recursively substitute env vars in all string values."""
    if isinstance(obj, dict):
        return {k: _walk_and_substitute(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_walk_and_substitute(item) for item in obj]
    elif isinstance(obj, str):
        return _substitute_env_vars(obj)
    return obj


def load_config(path: Path | None = None) -> dict:
    """Load and cache config from YAML file with env var substitution."""
    global _CONFIG
    if _CONFIG is not None and path is None:
        return _CONFIG

    config_path = path or _CONFIG_PATH
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    config = _walk_and_substitute(raw)

    if path is None:
        _CONFIG = config
    return config


def get_config() -> dict:
    """Get cached config, loading if necessary."""
    if _CONFIG is None:
        return load_config()
    return _CONFIG


def get_exchange_config(exchange: str) -> dict:
    """Get config for a specific exchange."""
    cfg = get_config()
    return cfg["exchanges"].get(exchange, {})


def get_scoring_weights() -> dict:
    """Get scoring weight configuration."""
    return get_config()["scoring_weights"]


def get_regime_thresholds() -> dict:
    """Get regime classification thresholds."""
    return get_config()["regime_thresholds"]
