"""Deterministic accessibility, privacy, and security validators (UIR-060/069).

Importing this package performs no network/process/hardware action.
"""

from __future__ import annotations

from typing import Final

from .accessibility import UIAccessibilityValidator, validate_accessibility
from .privacy import UIPrivacyValidator, validate_privacy
from .security import UISecurityValidator, validate_security

UIUXIR_INTERNAL_PACKAGES_INTERFACE: Final = "UIUXIRInternalPackages@1"

__all__ = [
    "UIUXIR_INTERNAL_PACKAGES_INTERFACE",
    "UIAccessibilityValidator",
    "UIPrivacyValidator",
    "UISecurityValidator",
    "validate_accessibility",
    "validate_privacy",
    "validate_security",
]
