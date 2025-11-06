from __future__ import annotations

import io
from typing import Iterable, Iterator, Optional

import pytest

from babbla import playback
from babbla.elevenlabs_provider import ElevenLabsProvider
from babbla.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)
from babbla.playback import PlaybackEngine


class _DummyResponse:
    def __init__(
        self,
        chunks: Iterable[bytes],
        status_code: int = 200,
        headers: Optional[dict[str, str]] = None,
        text: str = "",
    ) -> None:
        self._chunks = list(chunks)
        self.status_code = status_code
        self.headers = headers or {}
        self._text = text
        self.closed = False

    def iter_content(self, chunk_size: int = 4096) -> Iterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    def close(self) -> None:
        self.closed = True

    @property
    def text(self) -> str:
        return self._text


class _DummySession:
    def __init__(self, response: _DummyResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []
        self.headers: dict[str, str] = {}

    def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.response

    def close(self) -> None:  # pragma: no cover - session close unused in tests
        return None


def test_simulated_stream_returns_5_frames():
    provider = ElevenLabsProvider(simulate=True)
    provider.connect()
    frames = list(provider.stream("Hello world"))

    assert len(frames) == provider.FRAME_COUNT
    assert all(frame.sample_rate == provider.sample_rate for frame in frames)
    assert all(len(frame.pcm) == len(frames[0].pcm) for frame in frames)
    assert any(frame.pcm != b"\x00" * len(frame.pcm) for frame in frames)


def test_simulated_integration_with_playback(monkeypatch):
    writes = []

    class DummyStream:
        def __init__(self, *args, **kwargs):
            self.device = kwargs.get("device", "dummy")

        def start(self):
            return None

        def write(self, data: bytes):
            writes.append(data)

        def stop(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(playback.sd, "RawOutputStream", DummyStream)

    engine = PlaybackEngine()
    provider = ElevenLabsProvider(simulate=True)
    provider.connect()

    engine.start(provider.sample_rate)
    for frame in provider.stream("Integration test text"):
        engine.submit(frame)
    engine.flush_and_close()

    assert len(writes) == provider.FRAME_COUNT
    assert all(len(chunk) > 0 for chunk in writes)


def test_live_stream_yields_frames_from_http_stream():
    frame_bytes = int(
        ElevenLabsProvider.FRAME_DURATION_SEC * ElevenLabsProvider.DEFAULT_SAMPLE_RATE
    ) * 2

    def make_chunk(pattern: bytes, size: int) -> bytes:
        return pattern * (size // len(pattern))

    chunk_a = make_chunk(b"\x01\x02", frame_bytes // 4)  # 1/4 frame
    chunk_b = make_chunk(b"\x03\x04", frame_bytes)       # 1 frame
    chunk_c = make_chunk(b"\x05\x06", frame_bytes)       # 1 frame
    chunk_d = make_chunk(b"\x07\x08", frame_bytes // 8)  # 1/8 frame

    response = _DummyResponse([chunk_a, chunk_b, chunk_c, chunk_d])
    session = _DummySession(response)

    provider = ElevenLabsProvider(
        api_key="test-key",
        default_voice_id="voice-default",
        default_model_id="model-default",
        session=session,
        simulate=False,
    )
    provider.connect()

    frames = list(
        provider.stream(
            "Live test",
            settings={
                "voice_id": "voice-123",
                "model_id": "model-xyz",
                "stability": 0.5,
                "similarity_boost": 0.7,
            },
        )
    )

    assert len(frames) == 3  # two full frames + final remainder
    assert frames[0].sample_rate == provider.sample_rate
    assert len(frames[0].pcm) == frame_bytes
    assert len(frames[1].pcm) == frame_bytes
    assert len(frames[2].pcm) == (frame_bytes // 4) + (frame_bytes // 8)

    assert session.calls, "Expected streaming request to be issued."
    url, kwargs = session.calls[0]
    assert "voice-123" in url
    assert kwargs["json"]["model_id"] == "model-xyz"
    assert kwargs["json"]["voice_settings"]["stability"] == 0.5


def test_live_stream_raises_on_auth_error():
    response = _DummyResponse([], status_code=401, text='{"detail":"Unauthorized"}')
    session = _DummySession(response)
    provider = ElevenLabsProvider(
        api_key="test-key",
        default_voice_id="voice-default",
        session=session,
        simulate=False,
    )
    provider.connect()

    with pytest.raises(ProviderAuthError):
        list(provider.stream("Auth failure", settings={"voice_id": "voice-default"}))


def test_live_stream_raises_on_rate_limit():
    response = _DummyResponse(
        [],
        status_code=429,
        headers={"retry-after": "2.5"},
        text='{"detail":"Too many requests"}',
    )
    session = _DummySession(response)
    provider = ElevenLabsProvider(
        api_key="test-key",
        default_voice_id="voice-default",
        session=session,
        simulate=False,
    )
    provider.connect()

    with pytest.raises(ProviderRateLimitError) as excinfo:
        list(provider.stream("Rate limit", settings={"voice_id": "voice-default"}))

    assert excinfo.value.retry_after == pytest.approx(2.5)


def test_live_stream_error_falls_back_to_provider_error():
    response = _DummyResponse([], status_code=400, text="bad request")
    session = _DummySession(response)
    provider = ElevenLabsProvider(
        api_key="test-key",
        default_voice_id="voice-default",
        session=session,
        simulate=False,
    )
    provider.connect()

    with pytest.raises(ProviderError):
        list(provider.stream("Bad request", settings={"voice_id": "voice-default"}))
