import argparse
from pathlib import Path

import pytest

from babbla.config import load_config


def _make_args(**overrides):
    defaults = dict(
        config=None,
        api_key=None,
        voice=None,
        voice_id=None,
        model=None,
        model_id=None,
        max_chars=None,
        chunk_max_chars=None,
        prebuffer_ms=None,
        stability=None,
        similarity=None,
        similarity_boost=None,
        style=None,
        rate=None,
        cache_dir=None,
        cache_ttl=None,
        retry_attempts=None,
        timeout=None,
        timeout_ms=None,
        json_log=False,
        dry_run=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_config_precedence_cli_env_file(tmp_path):
    config_path = tmp_path / "babbla.toml"
    config_path.write_text(
        "\n".join(
            [
                'voice_id = "FileVoice"',
                'chunk_max_chars = 150',
                'stability = 0.2',
                'unknown_key = "keep_me"',
            ]
        ),
        encoding="utf-8",
    )

    env = {
        "BABBLA_VOICE_ID": "EnvVoice",
        "BABBLA_CHUNK_MAX_CHARS": "175",
        "BABBLA_STABILITY": "0.4",
    }

    args = _make_args(
        config=str(config_path),
        voice="CliVoice",
        max_chars=200,
        stability=0.6,
    )

    config = load_config(args, env=env)

    assert config.voice_id == "CliVoice"
    assert config.chunk_max_chars == 200
    assert pytest.approx(config.stability, rel=1e-6) == 0.6
    assert config.extra == {"unknown_key": "keep_me"}


def test_config_env_overrides_file(tmp_path):
    config_path = tmp_path / "babbla.toml"
    config_path.write_text('model_id = "file_model"\n', encoding="utf-8")

    env = {"BABBLA_MODEL_ID": "env_model"}
    args = _make_args(config=str(config_path))

    config = load_config(args, env=env)

    assert config.model_id == "env_model"


def test_config_validation_enforces_bounds():
    args = _make_args(stability=1.5)
    with pytest.raises(ValueError):
        load_config(args, env={})

    args = _make_args(similarity=1.2)
    with pytest.raises(ValueError):
        load_config(args, env={})


def test_json_log_flag_sets_format():
    args = _make_args(json_log=True)
    config = load_config(args, env={})

    assert config.json_log is True
    assert config.log_format == "json"

