# VoiceCLI

This repository hosts an experimental ElevenLabs low-latency streaming CLI. The
current iteration focuses on scaffolding so that subsequent tasks can build out
configuration handling, providers, playback, and metrics.

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
$env:PYTHONPATH = 'src'
py -m voicecli --help
```

The CLI is presently a stub: it sets up argument parsing, logging, and the core
module structure, but it does not contact the ElevenLabs API yet.

## Run Tests

```powershell
pip install -r requirements-dev.txt
$env:PYTHONPATH = 'src'
py -m pytest
```

## Project Layout

- `src/voicecli/cli.py` – CLI entry point and argument parsing scaffold.
- `src/voicecli/config.py` – Configuration loader with precedence (CLI > ENV > file > defaults).
- `src/voicecli/provider_base.py` – Abstract provider definitions.
- `src/voicecli/playback.py` – Placeholder playback engine.
- `requirements.txt` – Runtime dependencies.
- `requirements-dev.txt` – Development dependencies (tests).
- `tests/test_config.py` – Configuration precedence unit tests.

Refer to `docs/SPECIFICATION.md` for the full design and upcoming milestones.
