"""Shared fixtures for pdf_processing unit tests.

These tests were migrated from asyncio to anyio. Provide commonly used fixtures
(e.g., `processor`) at the `pdf_processing_` package root so tests outside the
nested `pdf_processor_/...` folders can still resolve them.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor


@pytest.fixture
def processor() -> PDFProcessor:
    """Default PDFProcessor instance for unit tests."""
    return PDFProcessor()


@pytest.fixture
def default_pdf_processor() -> PDFProcessor:
    """Alias fixture used by some generated unit tests."""
    return PDFProcessor()


@pytest.fixture
def valid_metadata() -> dict:
    """Basic metadata payload used by many process_pdf tests."""
    return {
        "source": "test",
        "priority": "high",
        "category": "document",
    }
