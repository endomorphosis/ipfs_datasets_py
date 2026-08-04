"""Compact synthetic USPTO document fixtures for PATLAW-031 extraction tests."""

from __future__ import annotations

from tests.fixtures.uspto.documents.generators import (
    NATIVE_CANARY,
    RECEIPT_CANARY,
    SCANNED_CANARY,
    build_corrupt_pdf,
    build_docx_application,
    build_native_pdf_with_metadata,
    build_oversize_bytes,
    build_password_pdf,
    build_plain_archive,
    build_scanned_image_only_pdf,
    fixture_manifest,
    sha256_hex,
)

__all__ = [
    "NATIVE_CANARY",
    "RECEIPT_CANARY",
    "SCANNED_CANARY",
    "build_corrupt_pdf",
    "build_docx_application",
    "build_native_pdf_with_metadata",
    "build_oversize_bytes",
    "build_password_pdf",
    "build_plain_archive",
    "build_scanned_image_only_pdf",
    "fixture_manifest",
    "sha256_hex",
]
