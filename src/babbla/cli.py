"""
Command-line interface for the Babbla MVP.

The CLI streams a single chunk of text using the ElevenLabs provider and the
sounddevice-backed playback engine. Future beads extend this to multi-chunk
streaming, metrics, caching, and richer error handling.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from .chunker import chunk_text
from .config import load_config
from .elevenlabs_provider import ElevenLabsProvider
from .playback import AudioDeviceError, PlaybackEngine
from .provider_base import AudioFrame
from .errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderError,
)

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="babbla",
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
        help="Path to an optional configuration file (babbla.toml).",
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
        version="babbla 0.0.1-dev",
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
        try:
            data = sys.stdin.read().strip()
        except OSError:
            logger.debug("stdin read failed; returning empty input.")
            return ""
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
    settings = {
        "voice_id": config.voice_id,
        "model_id": config.model_id,
        "stability": config.stability,
        "similarity_boost": config.similarity_boost,
        "style": config.style,
        "rate": config.rate,
    }
    if "optimize_streaming_latency" in config.extra:
        settings["optimize_streaming_latency"] = config.extra["optimize_streaming_latency"]
    return settings


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
    """Entry point invoked by `python -m babbla` or console scripts."""
    parser = create_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.verbose, args.quiet)
    logger.info("Babbla starting up.")
    config = load_config(args)
    logger.debug("Loaded configuration: %s", config)

    if args.list_voices:
        if not _ensure_api_key(config):
            return 2
        provider = _create_provider(config)
        try:
            provider.connect()
            _render_voice_list(provider)
        finally:
            provider.close()
        return 0

    if args.dry_run:
        text = _resolve_input_text(args)
        if not text:
            parser.print_help()
            return 2
        chunks = chunk_text(text, max_chars=config.chunk_max_chars)
        settings = _build_provider_settings(config)
        print("Dry run mode. No synthesis performed.")
        print(
            f"Voice: {settings['voice_id']} | Model: {settings['model_id']} | "
            f"Stability: {settings['stability']} | Similarity: {settings['similarity_boost']}"
        )
        print(f"Chunks: {len(chunks)} total (max_chars={config.chunk_max_chars})")
        for idx, chunk in enumerate(chunks, start=1):
            estimated_frames = max(1, round(len(chunk) / 40))
            print(
                f"  {idx}. length={len(chunk)} chars | estimated_frames={estimated_frames}"
            )
        return 0

    if not _ensure_api_key(config):
        return 2

    text = _resolve_input_text(args)
    if not text:
        parser.print_help()
        return 2

    provider = _create_provider(config)

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
    except ProviderAuthError as exc:
        logger.error("Authentication error: %s", exc)
        print("babbla: ElevenLabs authentication failed. Check your API key.")
        return 2
    except ProviderRateLimitError as exc:
        logger.error("Rate limited by ElevenLabs (retry_after=%s)", getattr(exc, "retry_after", None))
        print("babbla: Rate limited by ElevenLabs. Please wait and try again.")
        return 3
    except (ProviderConnectionError, ProviderNetworkError) as exc:
        logger.error("Network error while streaming: %s", exc)
        print("babbla: Network error while streaming from ElevenLabs.")
        return 3
    except ProviderError as exc:
        logger.error("Provider error: %s", exc)
        print(f"babbla: Provider error - {exc}")
        return 3
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


def _create_provider(config) -> ElevenLabsProvider:
    timeout_seconds = max(0.1, config.timeout_ms / 1000.0)
    optimize_latency = config.extra.get("optimize_streaming_latency", 2)
    return ElevenLabsProvider(
        api_key=config.api_key,
        default_voice_id=config.voice_id,
        default_model_id=config.model_id,
        sample_rate=16_000,
        timeout=timeout_seconds,
        optimize_streaming_latency=int(optimize_latency),
    )


def _ensure_api_key(config) -> bool:
    if config.api_key:
        return True
    logger.error("ElevenLabs API key not provided.")
    print(
        "babbla: ElevenLabs API key is required. "
        "Set ELEVENLABS_API_KEY, add it to babbla.toml, or pass --api-key."
    )
    return False


if __name__ == "__main__":  # pragma: no cover - allows `python cli.py`
    raise SystemExit(main())
