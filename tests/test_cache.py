from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from voicecli.cache import PhraseCache, make_cache_key


def test_cache_key_determinism():
    key1 = make_cache_key(
        voice_id="voice",
        model_id="model",
        stability=0.5,
        similarity=0.8,
        chunk_text="Hello world",
    )
    key2 = make_cache_key(
        voice_id="voice",
        model_id="model",
        stability=0.5,
        similarity=0.8,
        chunk_text="Hello world",
    )
    key3 = make_cache_key(
        voice_id="voice",
        model_id="model",
        stability=0.4,
        similarity=0.8,
        chunk_text="Hello world",
    )

    assert key1 == key2
    assert key1 != key3


def test_store_and_get(tmp_path):
    cache = PhraseCache(tmp_path, ttl_seconds=60)
    key = "abc123"
    pcm = b"\x00\x01" * 100
    cache.put(key, pcm, sample_rate=16000)

    item = cache.get(key)
    assert item is not None
    assert item.pcm == pcm
    assert item.sample_rate == 16000


def test_expired_eviction(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    key = "deadbeef"
    shard_dir = cache_dir / key[:2]
    shard_dir.mkdir()
    pcm_path = shard_dir / f"{key}.pcm"
    meta_path = shard_dir / f"{key}.json"
    pcm_path.write_bytes(b"\x00\x00")
    meta_path.write_text(
        json.dumps(
            {
                "created_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
                "sample_rate": 16000,
                "byte_len": 2,
            }
        ),
        encoding="utf-8",
    )

    cache = PhraseCache(cache_dir, ttl_seconds=60)
    assert cache.get(key) is None
    assert not pcm_path.exists()
    assert not meta_path.exists()
