from __future__ import annotations

from voicecli import playback
from voicecli.elevenlabs_provider import ElevenLabsProvider
from voicecli.playback import PlaybackEngine


def test_stub_stream_returns_5_frames():
    provider = ElevenLabsProvider()
    provider.connect()
    frames = list(provider.stream("Hello world"))

    assert len(frames) == provider.FRAME_COUNT
    assert all(frame.sample_rate == provider.sample_rate for frame in frames)
    assert all(len(frame.pcm) == len(frames[0].pcm) for frame in frames)
    assert any(frame.pcm != b"\x00" * len(frame.pcm) for frame in frames)


def test_stub_integration_with_playback(monkeypatch):
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
    provider = ElevenLabsProvider()
    provider.connect()

    engine.start(provider.sample_rate)
    for frame in provider.stream("Integration test text"):
        engine.submit(frame)
    engine.flush_and_close()

    assert len(writes) == provider.FRAME_COUNT
    assert all(len(chunk) > 0 for chunk in writes)
