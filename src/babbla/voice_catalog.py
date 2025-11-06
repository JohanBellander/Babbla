"""
Voice catalog retrieval and caching utilities.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional

import requests
from difflib import SequenceMatcher

CACHE_TTL = timedelta(hours=24)
API_URL = "https://api.elevenlabs.io/v1/voices"
BABBLA_HOME = Path(os.getenv("BABBLA_HOME", Path.home() / ".babbla"))
CACHE_FILE = BABBLA_HOME / "voices.json"


def fetch_voices(
    api_key: str | None,
    *,
    force_refresh: bool = False,
    cache_dir: Path | None = None,
    requester: Callable[[str], list[dict[str, object]]] | None = None,
) -> list[dict[str, object]]:
    cache_path = _resolve_cache_path(cache_dir)

    if not force_refresh:
        cached = _load_cache(cache_path)
        if cached is not None:
            return cached

    if api_key is None:
        raise ValueError("API key is required when refresh is requested or cache is empty.")

    fetcher = requester or _fetch_from_api
    voices = fetcher(api_key)
    _write_cache(cache_path, voices)
    return voices


def fuzzy_match(query: str, voices: Iterable[dict[str, object]]) -> str | None:
    query = query.strip()
    if not query:
        return None

    query_lower = query.lower()

    # Direct ID or name match
    for voice in voices:
        voice_id = str(voice.get("voice_id", ""))
        name = str(voice.get("name", ""))
        if voice_id.lower() == query_lower or name.lower() == query_lower:
            return voice_id

    best_id: str | None = None
    best_score = 0.0
    for voice in voices:
        voice_id = str(voice.get("voice_id", ""))
        name = str(voice.get("name", ""))
        name_lower = name.lower()
        score = 0.0
        if query_lower in name_lower:
            # Treat substring containment as at least a moderate match (>=0.5) so
            # short queries like "Liam" match "Liam Prime".
            score = max(len(query_lower) / len(name_lower), 0.5)
        else:
            score = SequenceMatcher(None, query_lower, name_lower).ratio()
        if score > best_score:
            best_score = score
            best_id = voice_id

    return best_id if best_score >= 0.5 else None


def _resolve_cache_path(cache_dir: Path | None) -> Path:
    directory = cache_dir if cache_dir is not None else BABBLA_HOME
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "voices.json"


def _load_cache(path: Path) -> list[dict[str, object]] | None:
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    timestamp_raw = data.get("fetched_at")
    voices = data.get("voices")
    if timestamp_raw is None or not isinstance(voices, list):
        return None

    try:
        fetched_at = datetime.fromisoformat(timestamp_raw)
    except ValueError:
        return None

    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) - fetched_at > CACHE_TTL:
        return None

    return voices


def _write_cache(path: Path, voices: list[dict[str, object]]) -> None:
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "voices": voices,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _fetch_from_api(api_key: str) -> list[dict[str, object]]:
    headers = {"xi-api-key": api_key}
    response = requests.get(API_URL, headers=headers, timeout=10)
    response.raise_for_status()
    payload = response.json()
    voices = payload.get("voices")
    if not isinstance(voices, list):
        return []
    return voices

