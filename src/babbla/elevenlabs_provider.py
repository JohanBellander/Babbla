"""
ElevenLabs provider implementation with optional simulation mode.

The provider supports two operating modes:
- **Simulated** (default for tests/tools): generates deterministic PCM16 frames
  so the wider pipeline can be exercised without hitting the network.
- **Live**: streams raw PCM audio from ElevenLabs' HTTP streaming endpoint.
"""

from __future__ import annotations

import logging
import math
from array import array
from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

import requests

from .errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderError,
    ProviderNetworkError,
    ProviderRateLimitError,
)
from .provider_base import AudioFrame, TTSProvider
from .voice_catalog import fetch_voices

logger = logging.getLogger(__name__)


@dataclass
class _StubVoice:
    voice_id: str
    name: str
    description: str


class ElevenLabsProvider(TTSProvider):
    FRAME_COUNT = 5
    FRAME_DURATION_SEC = 0.2
    DEFAULT_SAMPLE_RATE = 16_000
    BASE_URL = "https://api.elevenlabs.io"
    OUTPUT_FORMAT_TEMPLATE = "pcm_{sample_rate}"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_voice_id: str | None = None,
        default_model_id: str = "eleven_monolingual_v1",
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        timeout: float = 10.0,
        optimize_streaming_latency: int = 2,
        session: requests.Session | None = None,
        base_url: str = BASE_URL,
        simulate: bool = False,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive.")

        if not simulate and not api_key:
            raise ValueError("api_key is required when simulate=False.")

        self.api_key = api_key
        self.default_voice_id = default_voice_id
        self.default_model_id = default_model_id
        self.sample_rate = sample_rate
        self.timeout = timeout
        self.optimize_streaming_latency = optimize_streaming_latency
        self.base_url = base_url.rstrip("/")
        self.simulate = simulate

        self._session = session
        self._session_owner = False
        self._connected = False

        self._stub_voices: Sequence[_StubVoice] = (
            _StubVoice("voice_stub_1", "Ava (stub)", "Friendly English voice"),
            _StubVoice("voice_stub_2", "Liam (stub)", "Calm narration voice"),
        )

    # ------------------------------------------------------------------ #
    # Public API

    def connect(self) -> None:
        if self._connected:
            return

        if self.simulate:
            self._connected = True
            logger.debug("ElevenLabsProvider running in simulation mode.")
            return

        if self._session is None:
            self._session = requests.Session()
            self._session_owner = True

        assert self.api_key is not None  # for type-checkers
        self._session.headers.update(
            {
                "xi-api-key": self.api_key,
                "Accept": "application/octet-stream",
            }
        )
        self._connected = True

    def stream(
        self,
        text: str,
        settings: dict[str, object] | None = None,
    ) -> Iterable[AudioFrame]:
        if not self._connected:
            self.connect()

        if self.simulate:
            return self._simulate_stream(text)

        assert self._session is not None
        voice_id, model_id = self._resolve_voice_and_model(settings)
        payload = self._build_payload(text, model_id, settings)
        response = self._start_stream_request(voice_id, payload, settings)

        def iterator() -> Iterator[AudioFrame]:
            buffer = bytearray()
            frame_bytes = int(self.sample_rate * self.FRAME_DURATION_SEC) * 2
            try:
                for chunk in response.iter_content(chunk_size=4096):
                    if not chunk:
                        continue
                    buffer.extend(chunk)
                    while len(buffer) >= frame_bytes:
                        pcm = bytes(buffer[:frame_bytes])
                        del buffer[:frame_bytes]
                        yield AudioFrame(pcm=pcm, sample_rate=self.sample_rate)
                if buffer:
                    # Ensure even number of bytes (16-bit samples)
                    if len(buffer) % 2 != 0:
                        buffer.pop()
                    if buffer:
                        yield AudioFrame(pcm=bytes(buffer), sample_rate=self.sample_rate)
            finally:
                response.close()

        return iterator()

    def list_voices(self, force_refresh: bool = False) -> list[dict[str, object]]:
        if self.simulate:
            return [
                {
                    "voice_id": voice.voice_id,
                    "name": voice.name,
                    "description": voice.description,
                }
                for voice in self._stub_voices
            ]

        if not self.api_key:
            raise ProviderAuthError("API key is required to list voices.")

        return fetch_voices(self.api_key, force_refresh=force_refresh)

    def close(self) -> None:
        self._connected = False
        if self._session is not None and self._session_owner:
            self._session.close()
        self._session = None
        self._session_owner = False

    # ------------------------------------------------------------------ #
    # Live provider helpers

    def _resolve_voice_and_model(
        self, settings: dict[str, object] | None
    ) -> tuple[str, str]:
        voice_id = None
        model_id = self.default_model_id
        if settings:
            voice_id = settings.get("voice_id") or voice_id
            model_id = settings.get("model_id") or model_id

        voice_id = voice_id or self.default_voice_id
        if not voice_id:
            raise ProviderError("No voice_id provided for ElevenLabs streaming request.")

        return str(voice_id), str(model_id)

    def _build_payload(
        self,
        text: str,
        model_id: str,
        settings: dict[str, object] | None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {"text": text, "model_id": model_id}
        voice_settings = {}
        if settings:
            if settings.get("stability") is not None:
                voice_settings["stability"] = float(settings["stability"])
            if settings.get("similarity_boost") is not None:
                voice_settings["similarity_boost"] = float(settings["similarity_boost"])
            if settings.get("style") is not None:
                voice_settings["style"] = float(settings["style"])
            if settings.get("use_speaker_boost") is not None:
                voice_settings["use_speaker_boost"] = bool(settings["use_speaker_boost"])
            if settings.get("rate") is not None:
                # ElevenLabs currently expects speaking_rate in voice_settings.
                voice_settings["speaking_rate"] = float(settings["rate"])

        if voice_settings:
            payload["voice_settings"] = voice_settings

        generation_config = {}
        if settings:
            if settings.get("optimize_streaming_latency") is not None:
                generation_config["optimize_streaming_latency"] = int(
                    settings["optimize_streaming_latency"]
                )
        if generation_config:
            payload["generation_config"] = generation_config

        return payload

    def _start_stream_request(
        self,
        voice_id: str,
        payload: dict[str, object],
        settings: dict[str, object] | None,
    ) -> requests.Response:
        assert self._session is not None
        url = f"{self.base_url}/v1/text-to-speech/{voice_id}/stream"
        params = {
            "output_format": self.OUTPUT_FORMAT_TEMPLATE.format(sample_rate=self.sample_rate),
            "optimize_streaming_latency": (
                int(settings["optimize_streaming_latency"])
                if settings and settings.get("optimize_streaming_latency") is not None
                else self.optimize_streaming_latency
            ),
        }

        try:
            response = self._session.post(
                url,
                params=params,
                json=payload,
                timeout=self.timeout,
                stream=True,
            )
        except requests.exceptions.ConnectTimeout as exc:  # pragma: no cover - depends on network
            raise ProviderConnectionError("Timed out connecting to ElevenLabs.") from exc
        except requests.exceptions.ConnectionError as exc:  # pragma: no cover
            raise ProviderConnectionError("Unable to connect to ElevenLabs.") from exc
        except requests.exceptions.Timeout as exc:  # pragma: no cover
            raise ProviderNetworkError("Timed out waiting for ElevenLabs response.") from exc
        except requests.RequestException as exc:  # pragma: no cover
            raise ProviderNetworkError(str(exc)) from exc

        if response.status_code == 401:
            response.close()
            raise ProviderAuthError("Invalid ElevenLabs API key.")
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            response.close()
            raise ProviderRateLimitError(
                retry_after=float(retry_after) if retry_after else None
            )
        if 500 <= response.status_code < 600:
            response.close()
            raise ProviderNetworkError(
                f"ElevenLabs upstream error (status {response.status_code})."
            )
        if response.status_code >= 400:
            detail = response.text[:256]
            response.close()
            raise ProviderError(f"ElevenLabs request failed ({response.status_code}): {detail}")

        return response

    # ------------------------------------------------------------------ #
    # Simulation helpers

    def _simulate_stream(self, text: str) -> Iterable[AudioFrame]:
        payload = text.strip()
        frame_bytes = self._generate_tone(payload) if payload else self._generate_silence()

        def iterator() -> Iterator[AudioFrame]:
            for _ in range(self.FRAME_COUNT):
                yield AudioFrame(pcm=frame_bytes, sample_rate=self.sample_rate)

        return iterator()

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
