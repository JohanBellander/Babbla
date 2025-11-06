from __future__ import annotations

import math
from array import array

import pytest

from babbla.playback import AudioDeviceError, PlaybackEngine
from babbla.provider_base import AudioFrame


def _sine_wave_pcm(duration_sec: float, sample_rate: int, frequency_hz: float = 440.0) -> bytes:
    total_samples = int(duration_sec * sample_rate)
    amplitude = 0.2 * 32767  # prevent clipping
    samples = array(
        "h",
        (
            int(amplitude * math.sin(2 * math.pi * frequency_hz * n / sample_rate))
            for n in range(total_samples)
        ),
    )
    return samples.tobytes()


def test_playback_tone(tmp_path):
    engine = PlaybackEngine()
    sample_rate = 16_000
    try:
        engine.start(sample_rate)
    except AudioDeviceError as exc:
        pytest.skip(f"Audio device unavailable: {exc}")

    pcm = _sine_wave_pcm(duration_sec=1.0, sample_rate=sample_rate)
    engine.submit(pcm)
    engine.flush_and_close()


def test_submit_requires_start():
    engine = PlaybackEngine()
    with pytest.raises(AudioDeviceError):
        engine.submit(b"\x00\x00")


def test_audio_frame_rate_mismatch():
    engine = PlaybackEngine()
    sample_rate = 8_000
    try:
        engine.start(sample_rate)
    except AudioDeviceError as exc:
        pytest.skip(f"Audio device unavailable: {exc}")

    frame = AudioFrame(pcm=b"\x00\x00\x01\x00", sample_rate=16_000)
    with pytest.raises(AudioDeviceError):
        engine.submit(frame)
    engine.flush_and_close()

