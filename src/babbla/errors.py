"""
Custom exception hierarchy for Babbla.
"""

from __future__ import annotations

from dataclasses import dataclass


class BabblaError(Exception):
    """Base class for Babbla exceptions."""


class AudioDeviceError(BabblaError):
    """Raised when audio playback or recording fails."""


class ProviderError(BabblaError):
    """Base class for provider-related failures."""


class ProviderConnectionError(ProviderError):
    """Raised when connection to the provider cannot be established."""


@dataclass
class ProviderRateLimitError(ProviderError):
    retry_after: float | None = None


class ProviderAuthError(ProviderError):
    """Raised when authentication with the provider fails."""


class ProviderNetworkError(ProviderError):
    """Raised when transient network issues occur."""

