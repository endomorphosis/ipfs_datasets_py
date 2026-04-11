"""Netherlands laws assets, packaging helpers, and dataset builders.

This submodule keeps Netherlands-law-specific scrape outputs and downstream
packaging/index artifacts inside the legal scrapers package rather than under
repo-root standalone folders.
"""

from .paths import (
    NETHERLANDS_LAWS_DIR,
    RAW_DATA_DIR,
    HF_DATA_DIR,
    LEGACY_HF_READY_DIR,
    LEGACY_NL_OUTPUT_DIR,
    LEGACY_NL_OUTPUT_DOCS_DIR,
)

__all__ = [
    "NETHERLANDS_LAWS_DIR",
    "RAW_DATA_DIR",
    "HF_DATA_DIR",
    "LEGACY_HF_READY_DIR",
    "LEGACY_NL_OUTPUT_DIR",
    "LEGACY_NL_OUTPUT_DOCS_DIR",
]
