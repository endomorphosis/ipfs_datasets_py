"""Utility helpers shared across the package."""

from .mistral_vibe import (
    MistralVibeInstallResult,
    ensure_mistral_vibe,
    mistral_vibe_auth_available,
    mistral_vibe_auto_install_enabled,
)

__all__ = [
    "MistralVibeInstallResult",
    "ensure_mistral_vibe",
    "mistral_vibe_auth_available",
    "mistral_vibe_auto_install_enabled",
]
