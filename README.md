# VoiceCLI

## Overview
VoiceCLI is an experimental ElevenLabs low-latency streaming CLI. The current
codebase provides the project scaffolding, a stubbed provider, configuration
loading, playback plumbing, metrics utilities, and a growing set of automated
tests so future milestones can focus on production integration.

## Features
- Stub ElevenLabs provider that simulates five-frame streaming output
- Sounddevice-backed playback engine with optional WAV mirroring
- Configuration loader with CLI > ENV > `voicecli.toml` > defaults precedence
- Sentence chunker, phrase cache, latency metrics utilities, and streaming controller
- Structured logging with human or JSON output formats
- pytest-based test suite and latency harness script

## Quick Start
1. Create and activate a virtual environment
   ```powershell
   python -m venv .venv
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
   py -m voicecli --dry-run "Hello low latency world"
   ```

## Configuration Precedence
Configuration values are merged in the following order (later entries win):
1. CLI flags (e.g., `--voice`, `--model`, `--stability`)
2. Environment variables (e.g., `VOICECLI_VOICE_ID`, `VOICECLI_STABILITY`)
3. `voicecli.toml` file in the working directory
4. Built-in defaults (voice "Rachel", model `eleven_monolingual_v1`, stability 0.5)

Use the `--dry-run` flag to inspect how configuration resolves without making
provider calls. The `voicecli.config.load_config` function is covered by tests
(`tests/test_config.py`).

## Latency Metrics
The streaming controller records per-chunk timing metrics (synthesis, startup,
inter-chunk gaps). Utilities in `voicecli.metrics` derive p95 and average values.
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
py -m voicecli --dry-run "Structured logging" --json-log
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
