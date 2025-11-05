from __future__ import annotations

import wave

import pytest

from voicecli.playback import PlaybackEngine
from voicecli.provider_base import AudioFrame
from voicecli.wav_saver import WavSink


def test_wav_header_integrity(tmp_path):
    wav_path = tmp_path / "test.wav"
    sink = WavSink(wav_path)
    sink.start(16000)
    sink.write(b"\x00\x00" * 1600)  # 0.1s of silence at 16kHz
    sink.close()

    with wave.open(str(wav_path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.getnframes() == 1600


def test_wav_duration_with_playback(monkeypatch, tmp_path):
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

    from voicecli import playback as playback_module

    monkeypatch.setattr(playback_module.sd, "RawOutputStream", DummyStream)

    wav_path = tmp_path / "output.wav"
    engine = PlaybackEngine(wav_path=wav_path)
    engine.start(16_000)
    frame = AudioFrame(pcm=b"\x01\x00" * 3200, sample_rate=16_000)  # 0.2s
    engine.submit(frame)
    engine.flush_and_close()

    with wave.open(str(wav_path), "rb") as wav_file:
        duration = wav_file.getnframes() / wav_file.getframerate()
        assert pytest.approx(duration, rel=0.05) == 0.2
    assert len(writes) == 1
