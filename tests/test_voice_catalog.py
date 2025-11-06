from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from babbla.voice_catalog import fetch_voices, fuzzy_match


def test_cache_logic_returns_fresh_cache(tmp_path):
    cache_file = tmp_path / "voices.json"
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "voices": [{"voice_id": "id_cached", "name": "Cached Voice"}],
    }
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    result = fetch_voices(None, cache_dir=tmp_path)
    assert result == payload["voices"]


def test_force_refresh_updates_cache(tmp_path):
    cache_file = tmp_path / "voices.json"
    stale_payload = {
        "fetched_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        "voices": [{"voice_id": "old", "name": "Old Voice"}],
    }
    cache_file.write_text(json.dumps(stale_payload), encoding="utf-8")

    new_voices = [{"voice_id": "fresh", "name": "Fresh Voice"}]

    def requester(api_key: str):
        assert api_key == "secret"
        return new_voices

    result = fetch_voices("secret", force_refresh=True, cache_dir=tmp_path, requester=requester)
    assert result == new_voices

    stored = json.loads(cache_file.read_text(encoding="utf-8"))
    assert stored["voices"] == new_voices


def test_fuzzy_match():
    voices = [
        {"voice_id": "id_rachel", "name": "Rachel"},
        {"voice_id": "id_liam", "name": "Liam Prime"},
        {"voice_id": "id_ava", "name": "Ava Classic"},
    ]

    assert fuzzy_match("id_liam", voices) == "id_liam"
    assert fuzzy_match("rachel", voices) == "id_rachel"
    assert fuzzy_match("Liam", voices) == "id_liam"
    assert fuzzy_match("Classic", voices) == "id_ava"
    assert fuzzy_match("unknown", voices) is None
