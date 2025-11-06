from __future__ import annotations

import pytest

from babbla.provider_base import AudioFrame


class MockProvider:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.calls = 0

    def connect(self):
        return None

    def stream(self, text: str, settings=None):
        self.calls += 1
        yield AudioFrame(pcm=b"\x00\x00" * 160, sample_rate=self.sample_rate)

    def list_voices(self, force_refresh: bool = False):
        return []

    def close(self):
        return None


@pytest.fixture
def mock_provider():
    return MockProvider()
