"""
Audio playback engine implemented with sounddevice.

The engine accepts mono PCM16 frames and streams them to the system's default
output device. Exceptions from PortAudio are mapped to `AudioDeviceError` so the
rest of the application can react consistently.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import sounddevice as sd

from .errors import AudioDeviceError
from .provider_base import AudioFrame
from .wav_saver import WavSink

logger = logging.getLogger(__name__)


class PlaybackEngine:
    """Minimal playback engine that writes PCM16 audio via sounddevice."""

    def __init__(
        self,
        *,
        device: int | str | None = None,
        blocksize: int = 0,
        dtype: str = "int16",
        wav_path: str | Path | None = None,
    ) -> None:
        self._device = device
        self._blocksize = blocksize
        self._dtype = dtype
        self._sample_rate: Optional[int] = None
        self._stream: sd.RawOutputStream | None = None
        self._wav_sink: WavSink | None = WavSink(wav_path) if wav_path else None

    def start(self, sample_rate: int) -> None:
        """Start the underlying sounddevice RawOutputStream."""
        if self._stream is not None:
            raise AudioDeviceError("PlaybackEngine already started.")

        try:
            self._stream = sd.RawOutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype=self._dtype,
                blocksize=self._blocksize,
                device=self._device,
                finished_callback=lambda: logger.debug("Audio stream finished."),
            )
            self._stream.start()
            self._sample_rate = sample_rate
            if self._wav_sink is not None:
                self._wav_sink.start(sample_rate)
            logger.debug(
                "PlaybackEngine started (sample_rate=%s, device=%s)",
                sample_rate,
                self._stream.device,
            )
        except sd.PortAudioError as exc:  # pragma: no cover - hardware dependent
            self._stream = None
            logger.error("Failed to start audio stream: %s", exc)
            raise AudioDeviceError(str(exc)) from exc

    def submit(self, frame: AudioFrame | bytes) -> None:
        """Submit PCM16 audio to the output device."""
        if self._stream is None or self._sample_rate is None:
            raise AudioDeviceError("PlaybackEngine.start() must be called before submit().")

        if isinstance(frame, AudioFrame):
            if frame.sample_rate != self._sample_rate:
                raise AudioDeviceError(
                    f"Frame sample rate {frame.sample_rate} does not match stream {self._sample_rate}."
                )
            pcm_bytes = frame.pcm
        else:
            pcm_bytes = frame

        if len(pcm_bytes) % 2 != 0:
            raise AudioDeviceError("PCM16 payload length must be even (2 bytes per sample).")

        try:
            self._stream.write(pcm_bytes)
            logger.debug("PlaybackEngine wrote %s bytes", len(pcm_bytes))
            if self._wav_sink is not None:
                self._wav_sink.write(pcm_bytes)
        except sd.PortAudioError as exc:  # pragma: no cover - hardware dependent
            logger.error("Audio stream write failed: %s", exc)
            raise AudioDeviceError(str(exc)) from exc

    def flush_and_close(self) -> None:
        """Stop and close the underlying stream."""
        if self._stream is None:
            logger.debug("flush_and_close() called without an active stream.")
            return

        try:
            self._stream.stop()
            self._stream.close()
            logger.debug("PlaybackEngine stream closed.")
        except sd.PortAudioError as exc:  # pragma: no cover - hardware dependent
            logger.error("Failed to close audio stream: %s", exc)
            raise AudioDeviceError(str(exc)) from exc
        finally:
            self._stream = None
            self._sample_rate = None
            if self._wav_sink is not None:
                self._wav_sink.close()

    def attach_wav(self, path: str | Path) -> None:
        """Attach a WAV sink that mirrors submitted audio to disk."""
        self._wav_sink = WavSink(path)
