from __future__ import annotations

import io
import json
import logging

import pytest

from voicecli.cache import PhraseCache
from voicecli.errors import ProviderAuthError, ProviderNetworkError, ProviderRateLimitError
from voicecli.logging_utils import LogFormat, create_event_logger
from voicecli.provider_base import AudioFrame, TTSProvider
from voicecli.metrics import ChunkMetrics\nfrom voicecli.streaming_controller import StreamingController


\n\ndef _make_metric(request: float, first: float, playback: float, complete: float, index: int = 0, char_len: int = 50) -> ChunkMetrics:\n    return ChunkMetrics(\n        chunk_index=index,\n        char_len=char_len,\n        request_start=request,\n        first_frame=first,\n        playback_start=playback,\n        chunk_complete=complete,\n    )\nclass SimulatedClock:
    def __init__(self) -> None:
        self._now = 0.0

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        self._now += seconds
        return self._now


class FakeProvider(TTSProvider):
    def __init__(self, clock: SimulatedClock, delays_per_chunk: dict[int, list[float]], sample_rate: int = 16_000):
        self.clock = clock
        self.delays_per_chunk = delays_per_chunk
        self.sample_rate = sample_rate
        self.connected = False
        self.stream_calls = 0

    def connect(self) -> None:
        self.connected = True

    def stream(self, text: str, settings: dict[str, object] | None = None):
        if not self.connected:
            raise RuntimeError("Provider not connected.")
        if settings is None or "chunk_index" not in settings:
            raise ValueError("chunk_index must be supplied in settings.")
        self.stream_calls += 1
        chunk_index = int(settings["chunk_index"])
        for delay in self.delays_per_chunk.get(chunk_index, [0.05]):
            self.clock.advance(delay)
            yield AudioFrame(pcm=b"\x00\x00", sample_rate=self.sample_rate)

    def list_voices(self, force_refresh: bool = False):
        return []

    def close(self) -> None:
        self.connected = False


class FakePlayback:
    def __init__(self) -> None:
        self.started = False
        self.sample_rate = None
        self.frames = []

    def start(self, sample_rate: int) -> None:
        self.started = True
        self.sample_rate = sample_rate

    def submit(self, frame: AudioFrame) -> None:
        if not self.started:
            raise RuntimeError("Playback not started.")
        self.frames.append(frame)

    def flush_and_close(self) -> None:
        self.started = False


def test_streaming_controller_inter_chunk_gap_under_200ms():
    clock = SimulatedClock()
    provider = FakeProvider(
        clock,
        delays_per_chunk={
            0: [0.05, 0.05, 0.05],
            1: [0.1, 0.05, 0.05],
        },
    )
    playback = FakePlayback()
    controller = StreamingController(
        provider,
        playback,
        metrics=[],
        clock=clock.now,
    )

    metrics = controller.run(
        "Sentence one. Sentence two.",
        sample_rate=provider.sample_rate,
        max_chars=30,
    )

    assert len(metrics) == 2
    assert len(playback.frames) == 6

    gap_ms = (metrics[1].first_frame - metrics[0].chunk_complete) * 1000.0
    assert gap_ms <= 200.0
    assert metrics[0].char_len == len("Sentence one.")


def test_streaming_controller_cache_hit(tmp_path):
    clock = SimulatedClock()
    provider = FakeProvider(clock, delays_per_chunk={0: [0.05, 0.05, 0.05]})
    cache = PhraseCache(tmp_path, ttl_seconds=60)
    cache_params = {
        "voice_id": "voice",
        "model_id": "model",
        "stability": 0.5,
        "similarity": 0.8,
    }

    playback = FakePlayback()
    controller = StreamingController(
        provider,
        playback,
        metrics=[],
        phrase_cache=cache,
        cache_params=cache_params,
        clock=clock.now,
    )
    text = "Cache integration test."
    controller.run(
        text,
        sample_rate=provider.sample_rate,
        provider_settings=cache_params,
        max_chars=200,
    )
    first_stream_calls = provider.stream_calls
    assert first_stream_calls == 1

    playback2 = FakePlayback()
    controller2 = StreamingController(
        provider,
        playback2,
        metrics=[],
        phrase_cache=cache,
        cache_params=cache_params,
        clock=clock.now,
    )
    controller2.run(
        text,
        sample_rate=provider.sample_rate,
        provider_settings=cache_params,
        max_chars=200,
    )
    assert provider.stream_calls == first_stream_calls  # no additional provider call
    assert len(playback2.frames) > 0


def test_rate_limit_retry(monkeypatch):
    clock = SimulatedClock()
    delays = []

    def sleep_stub(seconds: float):
        delays.append(seconds)

    class FlakyProvider(TTSProvider):
        def __init__(self):
            self.calls = 0

        def connect(self):
            return None

        def stream(self, text, settings=None):
            self.calls += 1
            if self.calls == 1:
                raise ProviderRateLimitError(retry_after=0.05)
            yield AudioFrame(pcm=b"\x00\x00", sample_rate=16_000)

        def list_voices(self, force_refresh: bool = False):
            return []

        def close(self):
            return None

    provider = FlakyProvider()
    playback = FakePlayback()
    controller = StreamingController(
        provider,
        playback,
        metrics=[],
        clock=clock.now,
        sleep_fn=sleep_stub,
    )

    metrics = controller.run("Retry me", sample_rate=16_000)
    assert len(metrics) == 1
    assert provider.calls == 2
    assert delays and delays[0] >= 0.05


def test_network_retry_stops_after_max(monkeypatch):
    clock = SimulatedClock()
    delays = []

    def sleep_stub(seconds: float):
        delays.append(seconds)

    class BrokenProvider(TTSProvider):
        def connect(self):
            return None

        def stream(self, text, settings=None):
            raise ProviderNetworkError()

        def list_voices(self, force_refresh: bool = False):
            return []

        def close(self):
            return None

    provider = BrokenProvider()
    playback = FakePlayback()
    controller = StreamingController(
        provider,
        playback,
        metrics=[],
        clock=clock.now,
        sleep_fn=sleep_stub,
    )

    with pytest.raises(ProviderNetworkError):
        controller.run("Broken", sample_rate=16_000)

    assert len(delays) == controller.max_retries


def test_auth_failure_no_retry(monkeypatch):
    clock = SimulatedClock()
    delays = []

    def sleep_stub(seconds: float):
        delays.append(seconds)

    class AuthFailProvider(TTSProvider):
        def connect(self):
            return None

        def stream(self, text, settings=None):
            raise ProviderAuthError()

        def list_voices(self, force_refresh: bool = False):
            return []

        def close(self):
            return None

    provider = AuthFailProvider()
    playback = FakePlayback()
    controller = StreamingController(
        provider,
        playback,
        metrics=[],
        clock=clock.now,
        sleep_fn=sleep_stub,
    )

    with pytest.raises(ProviderAuthError):
        controller.run("Auth", sample_rate=16_000)

    assert delays == []


def test_streaming_controller_json_logging(tmp_path):
    clock = SimulatedClock()
    provider = FakeProvider(clock, delays_per_chunk={0: [0.05, 0.05]})
    playback = FakePlayback()

    logger = logging.getLogger("voicecli.jsonlogger")
    logger.setLevel(logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.handlers = [handler]

    event_logger = create_event_logger(logger, LogFormat.JSON)

    controller = StreamingController(
        provider,
        playback,
        metrics=[],
        clock=clock.now,
        event_logger=event_logger,
    )

    controller.run("Json logging test.", sample_rate=provider.sample_rate, max_chars=200)
    handler.flush()
    lines = [line for line in stream.getvalue().splitlines() if line]
    assert any(json.loads(line)["event"] == "chunk_start" for line in lines)
    logger.handlers.clear()

"\n\n\ndef _make_metric(request: float, first: float, playback: float, complete: float, index: int = 0, char_len: int = 50) -> ChunkMetrics:\n    return ChunkMetrics(\n        chunk_index=index,\n        char_len=char_len,\n        request_start=request,\n        first_frame=first,\n        playback_start=playback,\n        chunk_complete=complete,\n    )\n"




def test_adaptive_prebuffer_increase():
    clock = SimulatedClock()
    provider = FakeProvider(clock, delays_per_chunk={0: [0.05]})
    playback = FakePlayback()

    logger = logging.getLogger("adaptive.prebuffer")
    logger.setLevel(logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.handlers = [handler]

    controller = StreamingController(
        provider,
        playback,
        metrics=[],
        cache_params={"prebuffer_ms": 80},
        event_logger=create_event_logger(logger, LogFormat.JSON),
    )

    metric = _make_metric(0.0, 0.1, 0.15, 0.3)
    controller._record_metric(metric, True)
    controller._record_metric(metric, True)
    controller._record_metric(metric, True)

    assert controller.prebuffer_ms == 100
    handler.flush()
    events = [json.loads(line)["event"] for line in stream.getvalue().splitlines() if line]
    assert "adaptive_prebuffer_increase" in events
    logger.handlers.clear()


def test_adaptive_chunk_reduction():
    clock = SimulatedClock()
    provider = FakeProvider(clock, delays_per_chunk={0: [0.05]})
    playback = FakePlayback()

    logger = logging.getLogger("adaptive.chunk")
    logger.setLevel(logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.handlers = [handler]

    controller = StreamingController(
        provider,
        playback,
        metrics=[],
        cache_params={"chunk_max_chars": 200},
        event_logger=create_event_logger(logger, LogFormat.JSON),
    )

    high_latency_metric = _make_metric(0.0, 1.0, 1.05, 1.3)
    for _ in range(5):
        controller._record_metric(high_latency_metric, False)

    assert controller.chunk_max_chars == 160
    handler.flush()
    events = [json.loads(line)["event"] for line in stream.getvalue().splitlines() if line]
    assert "adaptive_chunk_reduction" in events
    logger.handlers.clear()
