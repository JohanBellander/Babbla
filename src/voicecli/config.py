"""
Configuration loader merging defaults, config files, environment, and CLI args.
"""

from __future__ import annotations

import argparse
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Tuple

DEFAULT_CONFIG_FILENAME = "voicecli.toml"


@dataclass
class AppConfig:
    """High-level application configuration container."""

    api_key: str | None = None
    voice_id: str = "Rachel"
    model_id: str = "eleven_monolingual_v1"
    chunk_max_chars: int = 200
    prebuffer_ms: int = 80
    stability: float = 0.5
    similarity_boost: float = 0.8
    style: float | None = None
    rate: float | None = None
    cache_dir: str | None = None
    cache_ttl: int = 7 * 24 * 60 * 60
    log_format: str = "human"
    json_log: bool = False
    dry_run: bool = False
    retry_attempts: int = 2
    timeout_ms: int = 10_000
    extra: dict[str, Any] = field(default_factory=dict)


def load_default_config() -> AppConfig:
    """Return default configuration for the CLI."""

    return AppConfig()


def load_config(
    args: argparse.Namespace | None = None,
    *,
    env: Mapping[str, str] | None = None,
    config_file: str | Path | None = None,
) -> AppConfig:
    """
    Load configuration merging defaults, config file, environment, then CLI.

    Precedence: CLI args > environment variables > config file > defaults.
    """

    defaults = load_default_config()
    config_data: dict[str, Any] = {
        key: getattr(defaults, key) for key in _known_fields()
    }
    extras: dict[str, Any] = {}

    resolved_config_path = _resolve_config_path(args, config_file)
    if resolved_config_path is not None:
        file_config, file_extras = _load_from_file(resolved_config_path)
        config_data.update(file_config)
        extras.update(file_extras)

    env_config = _load_from_env(env)
    config_data.update(env_config)

    cli_config = _load_from_cli(args)
    config_data.update(cli_config)

    if config_data.get("json_log"):
        config_data["log_format"] = "json"

    validated = _validate_config(config_data)

    combined_extras = {**extras, **validated.pop("extra", {})}
    if combined_extras:
        validated["extra"] = combined_extras

    return AppConfig(**validated)


def _known_fields() -> set[str]:
    return {f.name for f in fields(AppConfig) if f.init and f.name != "extra"}


def _resolve_config_path(
    args: argparse.Namespace | None, config_file: str | Path | None
) -> Path | None:
    candidate: str | Path | None = None
    if args is not None and getattr(args, "config", None):
        candidate = getattr(args, "config")
    elif config_file is not None:
        candidate = config_file

    if candidate is None:
        default_path = Path(DEFAULT_CONFIG_FILENAME)
        return default_path if default_path.exists() else None

    path = Path(candidate).expanduser()
    return path if path.exists() else None


def _load_from_file(path: Path) -> Tuple[dict[str, Any], dict[str, Any]]:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return {}, {}

    return _partition_known(data)


ENV_KEY_MAP: dict[str, Tuple[str, callable]] = {
    "ELEVENLABS_API_KEY": ("api_key", str),
    "VOICECLI_VOICE_ID": ("voice_id", str),
    "VOICECLI_MODEL_ID": ("model_id", str),
    "VOICECLI_CHUNK_MAX_CHARS": ("chunk_max_chars", int),
    "VOICECLI_PREBUFFER_MS": ("prebuffer_ms", int),
    "VOICECLI_STABILITY": ("stability", float),
    "VOICECLI_SIMILARITY": ("similarity_boost", float),
    "VOICECLI_STYLE": ("style", float),
    "VOICECLI_RATE": ("rate", float),
    "VOICECLI_CACHE_DIR": ("cache_dir", str),
    "VOICECLI_CACHE_TTL": ("cache_ttl", int),
    "VOICECLI_LOG_FORMAT": ("log_format", str),
    "VOICECLI_JSON_LOG": ("json_log", lambda v: str(v).lower() in {"1", "true", "yes"}),
    "VOICECLI_DRY_RUN": ("dry_run", lambda v: str(v).lower() in {"1", "true", "yes"}),
    "VOICECLI_RETRY_ATTEMPTS": ("retry_attempts", int),
    "VOICECLI_TIMEOUT_MS": ("timeout_ms", int),
}


def _load_from_env(env: Mapping[str, str] | None) -> dict[str, Any]:
    source = env if env is not None else os.environ
    result: dict[str, Any] = {}
    for env_key, (config_key, caster) in ENV_KEY_MAP.items():
        if env_key in source and source[env_key] != "":
            result[config_key] = caster(source[env_key])
    return result


CLI_ATTR_MAP: dict[str, Tuple[str, callable]] = {
    "api_key": ("api_key", str),
    "voice": ("voice_id", str),
    "voice_id": ("voice_id", str),
    "model": ("model_id", str),
    "model_id": ("model_id", str),
    "max_chars": ("chunk_max_chars", int),
    "chunk_max_chars": ("chunk_max_chars", int),
    "prebuffer_ms": ("prebuffer_ms", int),
    "stability": ("stability", float),
    "similarity": ("similarity_boost", float),
    "similarity_boost": ("similarity_boost", float),
    "style": ("style", float),
    "rate": ("rate", float),
    "cache_dir": ("cache_dir", str),
    "cache_ttl": ("cache_ttl", int),
    "log_format": ("log_format", str),
    "json_log": ("json_log", bool),
    "dry_run": ("dry_run", bool),
    "retry_attempts": ("retry_attempts", int),
    "timeout": ("timeout_ms", int),
    "timeout_ms": ("timeout_ms", int),
}


def _load_from_cli(args: argparse.Namespace | None) -> dict[str, Any]:
    if args is None:
        return {}

    result: dict[str, Any] = {}
    for attr_name, (config_key, caster) in CLI_ATTR_MAP.items():
        if hasattr(args, attr_name):
            value = getattr(args, attr_name)
            if value is None:
                continue
            if isinstance(value, bool) and caster is bool:
                result[config_key] = value
            else:
                result[config_key] = caster(value)
    return result


def _partition_known(data: Mapping[str, Any]) -> Tuple[dict[str, Any], dict[str, Any]]:
    known: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    known_keys = _known_fields()
    for key, value in data.items():
        if key in known_keys:
            known[key] = value
        else:
            extras[key] = value
    return known, extras


def _validate_config(data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    stability = data.get("stability")
    if stability is not None and not (0.0 <= float(stability) <= 1.0):
        raise ValueError("stability must be between 0.0 and 1.0")

    similarity = data.get("similarity_boost")
    if similarity is not None and not (0.0 <= float(similarity) <= 1.0):
        raise ValueError("similarity_boost must be between 0.0 and 1.0")

    chunk_max_chars = data.get("chunk_max_chars")
    if chunk_max_chars is not None and int(chunk_max_chars) <= 0:
        raise ValueError("chunk_max_chars must be positive")

    prebuffer_ms = data.get("prebuffer_ms")
    if prebuffer_ms is not None and int(prebuffer_ms) < 0:
        raise ValueError("prebuffer_ms must be non-negative")

    cache_ttl = data.get("cache_ttl")
    if cache_ttl is not None and int(cache_ttl) <= 0:
        raise ValueError("cache_ttl must be positive")

    retry_attempts = data.get("retry_attempts")
    if retry_attempts is not None and int(retry_attempts) < 0:
        raise ValueError("retry_attempts must be non-negative")

    timeout_ms = data.get("timeout_ms")
    if timeout_ms is not None and int(timeout_ms) <= 0:
        raise ValueError("timeout_ms must be positive")

    return data

