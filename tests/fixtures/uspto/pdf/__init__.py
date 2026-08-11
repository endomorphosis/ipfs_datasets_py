"""Synthetic USPTO-style PDF fixtures for document-foundation tests.

Fixtures are generated on demand (compact recipes) rather than bulk golden dumps.
No private/privileged content is stored; canaries are clearly synthetic.
"""

from .generators import (
    CONFIDENTIAL_CANARY,
    SCANNED_CANARY,
    ROTATED_CANARY,
    build_native_text_pdf,
    build_rotated_scanned_pdf,
    build_scanned_image_only_pdf,
    build_mixed_native_and_image_pdf,
    fixture_manifest,
)

__all__ = [
    "CONFIDENTIAL_CANARY",
    "SCANNED_CANARY",
    "ROTATED_CANARY",
    "build_native_text_pdf",
    "build_rotated_scanned_pdf",
    "build_scanned_image_only_pdf",
    "build_mixed_native_and_image_pdf",
    "fixture_manifest",
]
