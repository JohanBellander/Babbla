"""
Stub ElevenLabs provider that simulates streaming audio frames.

The stub breaks input text into five uniform frames of PCM16 audio so that the
rest of the pipeline can be exercised before the real WebSocket integration is
built.
"""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass
from typing import Iterable, Iterator

from .provider_base import AudioFrame, TTSProvider


@dataclass
class StubVoice:
    """Simple container describing a voice returned by the stub provider."""

    voice_id: str
    name: str
    description: str


class ElevenLabsProvider(TTSProvider):
    FRAME_COUNT = 5
    FRAME_DURATION_SEC = 0.2
    SAMPLE_RATE = 16_000

    def __init__(self, *, sample_rate: int | None = None) -> None:
        self.sample_rate = sample_rate or self.SAMPLE_RATE
        self._connected = False
        self._voices = [
            StubVoice("voice_stub_1", "Ava (stub)", "Friendly English voice"),
            StubVoice("voice_stub_2", "Liam (stub)", "Calm narration voice"),
        ]

    def connect(self) -> None:
        self._connected = True

    def stream(self, text: str, settings: dict[str, object] | None = None) -> Iterable[AudioFrame]:
        if not self._connected:
            self.connect()

        payload = text.strip()
        if not payload:
            frame_bytes = self._generate_silence()
        else:
            frame_bytes = self._generate_tone(payload)

        def iterator() -> Iterator[AudioFrame]:
            for _ in range(self.FRAME_COUNT):
                yield AudioFrame(pcm=frame_bytes, sample_rate=self.sample_rate)

        return iterator()

    def list_voices(self, force_refresh: bool = False) -> list[dict[str, object]]:
        return [
            {"voice_id": voice.voice_id, "name": voice.name, "description": voice.description}
            for voice in self._voices
        ]

    def close(self) -> None:
        self._connected = False

    # --------------------------------------------------------------------- #
    # Internal helpers

    def _generate_silence(self) -> bytes:
        sample_count = int(self.sample_rate * self.FRAME_DURATION_SEC)
        return array("h", [0] * sample_count).tobytes()

    def _generate_tone(self, text: str) -> bytes:
        sample_count = int(self.sample_rate * self.FRAME_DURATION_SEC)
        freq = 220.0 + (hash(text) % 220)
        amplitude = 0.25 * 32767
        samples = array(
            "h",
            (
                int(amplitude * math.sin(2 * math.pi * freq * n / self.sample_rate))
                for n in range(sample_count)
            ),
        )
        return samples.tobytes()

