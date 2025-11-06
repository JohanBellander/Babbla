"""
Phrase-level audio caching utilities.
"""

from __future__ import annotations

import json
import os
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


@dataclass
class CachedItem:
    pcm: bytes
    sample_rate: int
    created_at: datetime


def make_cache_key(
    *,
    voice_id: str,
    model_id: str,
    stability: float,
    similarity: float,
    chunk_text: str,
) -> str:
    payload = json.dumps(
        {
            "voice_id": voice_id,
            "model_id": model_id,
            "stability": round(float(stability), 4),
            "similarity": round(float(similarity), 4),
            "text": chunk_text,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PhraseCache:
    def __init__(self, cache_dir: str | Path, ttl_seconds: int = 7 * 24 * 3600) -> None:
        self.cache_dir = Path(cache_dir)
        self.ttl = timedelta(seconds=ttl_seconds)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._evict_expired()

    def get(self, key: str) -> Optional[CachedItem]:
        pcm_path, meta_path = self._paths_for_key(key)
        if not meta_path.exists() or not pcm_path.exists():
            return None

        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            created_at = datetime.fromisoformat(data["created_at"])
            sample_rate = int(data["sample_rate"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            self._remove_files(pcm_path, meta_path)
            return None

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        if self._is_expired(created_at):
            self._remove_files(pcm_path, meta_path)
            return None

        try:
            pcm_bytes = pcm_path.read_bytes()
        except OSError:
            self._remove_files(pcm_path, meta_path)
            return None

        return CachedItem(pcm=pcm_bytes, sample_rate=sample_rate, created_at=created_at)

    def put(self, key: str, pcm_bytes: bytes, sample_rate: int) -> None:
        pcm_path, meta_path = self._paths_for_key(key)
        pcm_path.parent.mkdir(parents=True, exist_ok=True)
        pcm_path.write_bytes(pcm_bytes)
        meta_path.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "sample_rate": sample_rate,
                    "byte_len": len(pcm_bytes),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _paths_for_key(self, key: str) -> tuple[Path, Path]:
        shard = key[:2]
        bucket = self.cache_dir / shard
        pcm_path = bucket / f"{key}.pcm"
        meta_path = bucket / f"{key}.json"
        return pcm_path, meta_path

    def _is_expired(self, created_at: datetime) -> bool:
        return datetime.now(timezone.utc) - created_at > self.ttl

    def _remove_files(self, pcm_path: Path, meta_path: Path) -> None:
        for path in (pcm_path, meta_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _evict_expired(self) -> None:
        for meta_file in self.cache_dir.rglob("*.json"):
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                created_at = datetime.fromisoformat(data.get("created_at", ""))
            except (OSError, ValueError, json.JSONDecodeError):
                created_at = datetime.fromtimestamp(0, tz=timezone.utc)

            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            if self._is_expired(created_at):
                pcm_file = meta_file.with_suffix(".pcm")
                self._remove_files(pcm_file, meta_file)

