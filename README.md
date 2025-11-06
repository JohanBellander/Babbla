# Babbla

## Overview
Babbla is an experimental ElevenLabs low-latency streaming CLI. The current
codebase provides the project scaffolding, a stubbed provider, configuration
loading, playback plumbing, metrics utilities, and a growing set of automated
tests so future milestones can focus on production integration.

> Repository rename in progress: if the remote is still `voicecli`, first rename it
> in GitHub Settings to `babbla`, then run:
> ```powershell
> git remote set-url origin https://github.com/JohanBellander/babbla.git
> git pull --rebase
> ```
> Existing clones of `voicecli` will continue to work via GitHub's redirect, but
> updating the remote URL avoids an extra redirect hop.

## Features
- Stub ElevenLabs provider that simulates five-frame streaming output
- Sounddevice-backed playback engine with optional WAV mirroring
- Configuration loader with CLI > ENV > `babbla.toml` > defaults precedence
- Sentence chunker, phrase cache, latency metrics utilities, and streaming controller
- Structured logging with human or JSON output formats
- pytest-based test suite and latency harness script

## Quick Start
1. Create and activate a virtual environment
   ```powershell
   py -3 -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
2. Install dependencies and expose the source tree
   ```powershell
   pip install --upgrade pip
   pip install -r requirements.txt
   $env:PYTHONPATH = 'src'
   ```
3. Set your ElevenLabs API key (required when the real provider is integrated)
   ```powershell
   $env:ELEVENLABS_API_KEY = 'xxxxxxxxxxxxxxxxxxxxxxxx'
   ```
4. Run the CLI using the built-in stub provider
   ```powershell
   py -m babbla --dry-run "Hello low latency world"
   ```

### One-liner install (PowerShell)

```powershell
py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install --disable-pip-version-check -e .
```

> Run the one-liner from the project root so `pip` can see the repository files.

Setting up a brand-new machine typically looks like:

```powershell
git clone https://github.com/JohanBellander/babbla.git
Set-Location .\babbla
py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install --disable-pip-version-check -e .
```

### Zero-setup install (fresh machine)

To install the CLI on a computer that does **not** already have the repository,
install straight from GitHub via `pip`:

```powershell
py -3 -m pip install --user --upgrade git+https://github.com/JohanBellander/babbla.git
```

This single command:
- Downloads the Voice project
- Builds it using the bundled `pyproject.toml`
- Installs the `babbla` console script into your user Python environment

After it finishes, verify with:

```powershell
babbla --help
```

> For an isolated install, run the command inside a virtual environment or use
> [`pipx`](https://pypa.github.io/pipx/):
> `pipx install git+https://github.com/JohanBellander/babbla.git`.

## Configuration Precedence
Configuration values are merged in the following order (later entries win):
1. CLI flags (e.g., `--voice`, `--model`, `--stability`)
2. Environment variables (e.g., `BABBLA_VOICE_ID`, `BABBLA_STABILITY`)
3. `babbla.toml` file in the working directory
4. Built-in defaults (voice "Rachel", model `eleven_monolingual_v1`, stability 0.5)

Use the `--dry-run` flag to inspect how configuration resolves without making
provider calls. The `babbla.config.load_config` function is covered by tests
(`tests/test_config.py`).

## Latency Metrics
The streaming controller records per-chunk timing metrics (synthesis, startup,
inter-chunk gaps). Utilities in `babbla.metrics` derive p95 and average values.
The `tools/latency_harness.py` script runs multiple iterations and writes
`latency_report.json` summarising:
- `p95_first_frame_ms`
- `p95_startup_ms`
- `avg_inter_chunk_gap_ms`
- Average first-frame and startup latency

## JSON Logging
Structured event logging supports human and JSON modes. Enable JSON output with
`--json-log` to receive newline-delimited JSON like:
```powershell
py -m babbla --dry-run "Structured logging" --json-log
```
Events include `chunk_start`, `first_frame`, `playback_start`, `chunk_complete`,
`retry`, and `error`. API keys and similar fields are automatically redacted
(e.g., `****abcd`).

## Troubleshooting
- **Audio device errors:** Ensure your sound device is available. The playback
  engine raises a descriptive `AudioDeviceError` if PortAudio cannot open the
  stream.
- **Missing API key:** Set `ELEVENLABS_API_KEY` before running with the real
  provider. Dry-run mode is safe without credentials.
- **Tests fail due to missing dependencies:** Install dev requirements via
  `pip install -r requirements-dev.txt` and re-run `py -m pytest` (remember to
  set `PYTHONPATH=src`).

Refer to `docs/SPECIFICATION.md` for longer-term design details and future
milestones.
