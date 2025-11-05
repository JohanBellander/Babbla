"""
Command-line interface for the VoiceCLI MVP.

The CLI currently orchestrates a single-chunk synthesis flow using the stub
ElevenLabs provider and the sounddevice-backed playback engine. Future beads
extend this to multi-chunk streaming, metrics, caching, and real API calls.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from .config import load_config
from .elevenlabs_provider import ElevenLabsProvider
from .playback import AudioDeviceError, PlaybackEngine
from .provider_base import AudioFrame

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="voicecli",
        description=(
            "Convert text to speech using ElevenLabs streaming APIs.\n"
            "This MVP streams a single chunk using the built-in stub provider."
        ),
    )
    text_group = parser.add_mutually_exclusive_group()
    text_group.add_argument(
        "text",
        nargs="?",
        help="Text to synthesize. When omitted, use --file or pipe via STDIN.",
    )
    text_group.add_argument(
        "--file",
        metavar="PATH",
        help="Read input text from a UTF-8 encoded file.",
    )

    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to an optional configuration file (voicecli.toml).",
    )
    parser.add_argument(
        "--api-key",
        dest="api_key",
        help="ElevenLabs API key (overrides environment and config file).",
    )
    parser.add_argument(
        "--voice",
        help="Voice identifier or fuzzy-matched name.",
    )
    parser.add_argument(
        "--model",
        help="Model identifier (default eleven_monolingual_v1).",
    )
    parser.add_argument(
        "--max-chars",
        dest="max_chars",
        type=int,
        help="Maximum characters per chunk (default 200).",
    )
    parser.add_argument(
        "--prebuffer-ms",
        dest="prebuffer_ms",
        type=int,
        help="Initial playback buffer in milliseconds (default 80).",
    )
    parser.add_argument(
        "--stability",
        type=float,
        help="Override voice stability (0..1).",
    )
    parser.add_argument(
        "--similarity",
        type=float,
        help="Override similarity boost (0..1).",
    )
    parser.add_argument(
        "--style",
        type=float,
        help="Style exaggeration control.",
    )
    parser.add_argument(
        "--rate",
        type=float,
        help="Speaking rate multiplier.",
    )
    parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        help="Enable phrase-level cache in the specified directory.",
    )
    parser.add_argument(
        "--cache-ttl",
        dest="cache_ttl",
        type=int,
        help="Cache time-to-live in seconds (default 604800).",
    )
    parser.add_argument(
        "--retry-attempts",
        dest="retry_attempts",
        type=int,
        help="Provider retry attempts on failure (default 2).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        metavar="MS",
        help="Network timeout in milliseconds (default 10000).",
    )
    parser.add_argument(
        "--json-log",
        action="store_true",
        help="Emit logs as JSON lines.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned operations without contacting the provider.",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="List available voices and exit.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="voicecli 0.0.1-dev",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase logging verbosity (repeatable).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress non-essential log output.",
    )
    return parser


def _configure_logging(verbosity: int, quiet: bool) -> None:
    """Configure root logger based on verbosity flags."""
    if quiet:
        level = logging.ERROR
    else:
        level = logging.WARNING
        if verbosity == 1:
            level = logging.INFO
        elif verbosity >= 2:
            level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger.debug("Logging configured (level=%s)", logging.getLevelName(level))


def _resolve_input_text(args: argparse.Namespace) -> str:
    if args.text:
        return args.text

    if args.file:
        path = Path(args.file)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"Failed to read file '{path}': {exc}") from exc

    if not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        if data:
            return data

    return ""


def _render_voice_list(provider: ElevenLabsProvider) -> None:
    voices = provider.list_voices()
    if not voices:
        print("No voices available.")
        return

    print("Available voices:")
    for voice in voices:
        description = voice.get("description", "")
        print(f"- {voice['voice_id']}: {voice['name']} ({description})")


def _build_provider_settings(config) -> dict[str, object]:
    return {
        "voice_id": config.voice_id,
        "model_id": config.model_id,
        "stability": config.stability,
        "similarity_boost": config.similarity_boost,
        "style": config.style,
        "rate": config.rate,
    }


def _stream_single_chunk(
    text: str,
    provider: ElevenLabsProvider,
    playback_engine: PlaybackEngine,
    settings: dict[str, object],
) -> tuple[int, float, float]:
    frame_count = 0
    request_start = time.perf_counter()
    first_frame_ts: float | None = None

    for frame in provider.stream(text, settings=settings):
        if not isinstance(frame, AudioFrame):
            raise TypeError("Provider must yield AudioFrame instances.")
        if frame_count == 0:
            first_frame_ts = time.perf_counter()
        playback_engine.submit(frame)
        frame_count += 1

    total_latency_ms = (time.perf_counter() - request_start) * 1000.0
    first_frame_ms = (
        (first_frame_ts - request_start) * 1000.0 if first_frame_ts else total_latency_ms
    )
    return frame_count, first_frame_ms, total_latency_ms


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point invoked by `python -m voicecli` or console scripts."""
    parser = create_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.verbose, args.quiet)
    logger.info("VoiceCLI starting up.")
    config = load_config(args)
    logger.debug("Loaded configuration: %s", config)

    provider = ElevenLabsProvider()

    if args.list_voices:
        provider.connect()
        _render_voice_list(provider)
        provider.close()
        return 0

    text = _resolve_input_text(args)
    if not text:
        parser.print_help()
        return 2

    if args.dry_run:
        print("Dry run mode. No synthesis performed.")
        print(f"Voice: {config.voice_id} | Model: {config.model_id}")
        print(f"Characters: {len(text)}")
        return 0

    playback_engine = PlaybackEngine()

    try:
        provider.connect()
        playback_engine.start(provider.sample_rate)
        frames, first_frame_ms, total_ms = _stream_single_chunk(
            text,
            provider=provider,
            playback_engine=playback_engine,
            settings=_build_provider_settings(config),
        )
    except AudioDeviceError as exc:
        logger.error("Playback failure: %s", exc)
        return 4
    except Exception as exc:  # pragma: no cover - catch-all for MVP
        logger.exception("Unexpected error during synthesis: %s", exc)
        return 1
    finally:
        playback_engine.flush_and_close()
        provider.close()

    logger.info(
        "Playback finished | frames=%s | first_frame_ms=%.1f | total_ms=%.1f",
        frames,
        first_frame_ms,
        total_ms,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - allows `python cli.py`
    raise SystemExit(main())
