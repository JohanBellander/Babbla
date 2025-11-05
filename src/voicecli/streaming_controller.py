"""
Streaming controller orchestrating chunked synthesis and playback.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, List, Optional

from .chunker import chunk_text
from .cache import CachedItem, PhraseCache, make_cache_key
from .errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderNetworkError,
    ProviderRateLimitError,
)
from .logging_utils import EventLogger, create_event_logger
from .metrics import ChunkMetrics, summarise_metrics
from .playback import PlaybackEngine
from .provider_base import AudioFrame, TTSProvider

logger = logging.getLogger(__name__)


class StreamingController:
    def __init__(
        self,
        provider: TTSProvider,
        playback: PlaybackEngine,
        *,
        chunker: Callable[[str, int], List[str]] = chunk_text,
        metrics: Optional[List[ChunkMetrics]] = None,
        phrase_cache: PhraseCache | None = None,
        cache_params: Optional[dict[str, object]] = None,
        clock: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        max_retries: int = 2,
        event_logger: EventLogger | None = None,
    ) -> None:
        self.provider = provider
        self.playback = playback
        self.chunker = chunker
        self.metrics: List[ChunkMetrics] = metrics if metrics is not None else []
        self.cache = phrase_cache
        self.cache_params = cache_params or {}
        self._clock = clock or time.perf_counter
        self._sleep = sleep_fn or time.sleep
        self.max_retries = max_retries
        self.event_logger = event_logger or create_event_logger(logger, "human")
        self.prebuffer_ms = (
            cache_params.get("prebuffer_ms", 80) if cache_params else 80
        )
        self.chunk_max_chars = (
            cache_params.get("chunk_max_chars", 200) if cache_params else 200
        )
        self._recent_metrics: list[ChunkMetrics] = []
        self._recent_underruns: list[bool] = []
        self._pending_underrun = False

    def run(
        self,
        text: str,
        *,
        sample_rate: int,
        max_chars: int | None = None,
        provider_settings: Optional[dict[str, object]] = None,
    ) -> List[ChunkMetrics]:        chunk_limit = max_chars if max_chars is not None else self.chunk_max_chars\n        chunks = self.chunker(text, max_chars=chunk_limit)
        if not chunks:
            logger.warning("No text provided for streaming.")
            return self.metrics

        logger.info("Starting streaming controller for %s chunks.", len(chunks))
        self.provider.connect()
        self.playback.start(sample_rate)

        try:
            previous_chunk_complete: float | None = None
            for index, chunk in enumerate(chunks):
                attempts = 0
                while True:
                    try:
                        metric, underrun = self._process_chunk(
                            index=index,
                            chunk=chunk,
                            sample_rate=sample_rate,
                            provider_settings=provider_settings,
                            previous_chunk_complete=previous_chunk_complete,
                        )
                        self._record_metric(metric, underrun)
                        previous_chunk_complete = metric.chunk_complete
                        break
                    except ProviderAuthError:
                        logger.error("Authentication failed for chunk index=%s", index)
                        self.event_logger.log(
                            "error", level="error", index=index, reason="auth_failed"
                        )
                        raise
                    except ProviderConnectionError:
                        logger.error("Unable to connect to provider for chunk index=%s", index)
                        self.event_logger.log(
                            "error", level="error", index=index, reason="connection_failed"
                        )
                        raise
                    except (ProviderNetworkError, ProviderRateLimitError) as exc:
                        attempts += 1
                        if attempts > self.max_retries:
                            logger.error("Max retries exceeded for chunk index=%s", index)
                            self.event_logger.log(
                                "error",
                                level="error",
                                index=index,
                                reason="max_retries_exceeded",
                                error=exc.__class__.__name__,
                            )
                            raise
                        delay = self._compute_backoff(attempts, getattr(exc, "retry_after", None))
                        self.event_logger.log(
                            "retry",
                            level="warning",
                            index=index,
                            attempt=attempts,
                            delay=round(delay, 3),
                            error=exc.__class__.__name__,
                        )
                        logger.warning(
                            "Transient provider error (%s). Retrying chunk index=%s in %.2fs (attempt %s/%s)",
                            exc.__class__.__name__,
                            index,
                            delay,
                            attempts,
                            self.max_retries,
                        )
                        self._sleep(delay)
        finally:
            self.playback.flush_and_close()
            self.provider.close()

        return self.metrics

    def _compute_cache_key(self, chunk: str, settings: dict[str, object]) -> str | None:
        if not self.cache:
            return None

        params = dict(self.cache_params)
        params.update(settings or {})

        voice_id = str(params.get("voice_id") or "")
        model_id = str(params.get("model_id") or "")
        stability = params.get("stability", params.get("stability_boost", 0.0))
        similarity = params.get("similarity", params.get("similarity_boost", 0.0))

        if not voice_id or not model_id:
            return None

        return make_cache_key(
            voice_id=voice_id,
            model_id=model_id,
            stability=float(stability),
            similarity=float(similarity),
            chunk_text=chunk,
        )

    def _play_cached_item(self, cached: CachedItem, sample_rate: int) -> None:
        slice_samples = max(1, int(sample_rate * 0.1))
        bytes_per_sample = 2  # PCM16
        chunk_size = slice_samples * bytes_per_sample

        for offset in range(0, len(cached.pcm), chunk_size):
            frame_bytes = cached.pcm[offset : offset + chunk_size]
            if not frame_bytes:
                continue
            frame = AudioFrame(pcm=frame_bytes, sample_rate=sample_rate)
            self.playback.submit(frame)

    def _process_chunk(
        self,
        *,
        index: int,
        chunk: str,
        sample_rate: int,
        provider_settings: Optional[dict[str, object]],
        previous_chunk_complete: float | None,
    ) -> tuple[ChunkMetrics, bool]:
        self.event_logger.log("chunk_start", index=index, char_len=len(chunk))
        base_settings = dict(provider_settings or {})
        base_settings["chunk_index"] = index
        cache_key = self._compute_cache_key(chunk, base_settings)

        if cache_key and self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                self.event_logger.log("cache_hit", index=index, key=cache_key[:8])
                request_start = self._clock()
                self._play_cached_item(cached, sample_rate)
                chunk_complete = self._clock()
                underrun_flag = self._consume_pending_underrun()
                if underrun_flag:
                    self.event_logger.log("underrun_detected", index=index)
                return ChunkMetrics(
                    chunk_index=index,
                    char_len=len(chunk),
                    request_start=request_start,
                    first_frame=request_start,
                    playback_start=request_start,
                    chunk_complete=chunk_complete,
                ), underrun_flag
            logger.debug("cache_miss index=%s key=%s", index, cache_key[:8])

        request_start = self._clock()
        first_frame_ts: float | None = None
        playback_start_ts: float | None = None
        buffered_audio = bytearray()

        for frame in self.provider.stream(chunk, settings=base_settings):
            if not isinstance(frame, AudioFrame):
                raise TypeError("Provider must yield AudioFrame instances.")

            now = self._clock()
            if first_frame_ts is None:
                first_frame_ts = now
                self.event_logger.log("first_frame", index=index)
                if previous_chunk_complete is not None:
                    gap_ms = (first_frame_ts - previous_chunk_complete) * 1000.0
                    logger.debug("inter_chunk_gap_ms=%.1f index=%s", gap_ms, index)
            if playback_start_ts is None:
                playback_start_ts = now
                self.event_logger.log("playback_start", index=index)

            self.playback.submit(frame)
            buffered_audio.extend(frame.pcm)

        chunk_complete = self._clock()
        self.event_logger.log("chunk_complete", index=index)

        if cache_key and self.cache and buffered_audio:
            self.cache.put(cache_key, bytes(buffered_audio), sample_rate)

        underrun_flag = self._consume_pending_underrun()
        if underrun_flag:
            self.event_logger.log("underrun_detected", index=index)

        return ChunkMetrics(
            chunk_index=index,
            char_len=len(chunk),
            request_start=request_start,
            first_frame=first_frame_ts or chunk_complete,
            playback_start=playback_start_ts or chunk_complete,
            chunk_complete=chunk_complete,
        ), underrun_flag

    def _compute_backoff(self, attempt: int, retry_after: float | None) -> float:
        base = 0.3 * (2 ** (attempt - 1))
        jitter = random.uniform(0.0, 0.1)
        if retry_after:
            return max(retry_after, base) + jitter
        return base + jitter

    def register_underrun(self) -> None:
        self._pending_underrun = True

    def _consume_pending_underrun(self) -> bool:
        flag = self._pending_underrun
        self._pending_underrun = False
        return flag

    def _record_metric(self, metric: ChunkMetrics, underrun: bool) -> None:
        self._record_metric(metric, underrun)
        self._recent_metrics.append(metric)
        self._recent_underruns.append(underrun)
        if len(self._recent_metrics) > 5:
            self._recent_metrics.pop(0)
        if len(self._recent_underruns) > 5:
            self._recent_underruns.pop(0)
        self._apply_adaptive_logic()

    def _apply_adaptive_logic(self) -> None:
        if self._recent_underruns.count(True) > 2 and self.prebuffer_ms < 200:
            new_prebuffer = min(200, self.prebuffer_ms + 20)
            if new_prebuffer != self.prebuffer_ms:
                self.prebuffer_ms = new_prebuffer
                self.event_logger.log(
                    "adaptive_prebuffer_increase",
                    prebuffer_ms=self.prebuffer_ms,
                )

        if len(self._recent_metrics) >= 5:
            recent = self._recent_metrics[-5:]
            summary = summarise_metrics(recent)
            if summary["p95_first_frame_ms"] > 600:
                new_chunk = max(80, int(self.chunk_max_chars * 0.8))
                if new_chunk < self.chunk_max_chars:
                    self.chunk_max_chars = new_chunk
                    self.event_logger.log(
                        "adaptive_chunk_reduction",
                        chunk_max_chars=self.chunk_max_chars,
                    )










