"""
Provider abstraction for text-to-speech backends.

Future work will introduce the ElevenLabs streaming implementation; this module
defines the shared interface that all providers must satisfy so the rest of the
application can remain backend-agnostic.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Iterable, Iterator, Protocol


@dataclass
class AudioFrame:
    """Represents a single chunk of PCM audio data."""

    pcm: bytes
    sample_rate: int


class TTSProvider(abc.ABC):
    """Abstract base class for streaming TTS providers."""

    @abc.abstractmethod
    def connect(self) -> None:
        """Open any connections or allocate resources."""

    @abc.abstractmethod
    def stream(self, text_chunk: str, settings: dict | None = None) -> Iterator[AudioFrame]:
        """Yield AudioFrame objects for the provided text chunk."""

    @abc.abstractmethod
    def list_voices(self, force_refresh: bool = False) -> Iterable[dict]:
        """Return metadata about available voices."""

    @abc.abstractmethod
    def close(self) -> None:
        """Release resources and close connections."""


class PlaybackSink(Protocol):
    """Protocol describing how the playback engine accepts audio frames."""

    def start(self, sample_rate: int) -> None: ...

    def submit(self, frame: AudioFrame) -> None: ...

    def flush_and_close(self) -> None: ...

