"""
Streaming WAV writer for PCM16 mono audio.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO


class WavSink:
    """Incrementally writes PCM16 mono audio to a WAV file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._fh: BinaryIO | None = None
        self._sample_rate: int | None = None
        self._bytes_written: int = 0

    def start(self, sample_rate: int) -> None:
        if self._fh is not None:
            raise RuntimeError("WavSink already started.")
        self._sample_rate = sample_rate
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("wb")
        self._write_header_placeholder(sample_rate)

    def write(self, pcm_bytes: bytes) -> None:
        if self._fh is None or self._sample_rate is None:
            raise RuntimeError("WavSink must be started before writing.")
        if not pcm_bytes:
            return
        self._fh.write(pcm_bytes)
        self._bytes_written += len(pcm_bytes)

    def close(self) -> None:
        if self._fh is None:
            return
        self._finalise_header()
        self._fh.close()
        self._fh = None
        self._sample_rate = None
        self._bytes_written = 0

    # ------------------------------------------------------------------ #
    # Internal helpers

    def _write_header_placeholder(self, sample_rate: int) -> None:
        assert self._fh is not None
        # RIFF header
        self._fh.write(b"RIFF")
        self._fh.write(struct.pack("<I", 0))  # Placeholder for chunk size
        self._fh.write(b"WAVE")
        # fmt chunk
        self._fh.write(b"fmt ")
        self._fh.write(struct.pack("<I", 16))  # PCM fmt chunk length
        self._fh.write(struct.pack("<HHIIHH", 1, 1, sample_rate, sample_rate * 2, 2, 16))
        # data chunk header
        self._fh.write(b"data")
        self._fh.write(struct.pack("<I", 0))  # Placeholder for data size

    def _finalise_header(self) -> None:
        assert self._fh is not None
        data_chunk_size = self._bytes_written
        riff_chunk_size = 36 + data_chunk_size

        self._fh.seek(4)
        self._fh.write(struct.pack("<I", riff_chunk_size))
        self._fh.seek(40)
        self._fh.write(struct.pack("<I", data_chunk_size))
        self._fh.seek(0, 2)  # Seek to end for clarity

