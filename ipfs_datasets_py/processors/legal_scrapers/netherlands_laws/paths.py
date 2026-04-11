"""Shared paths for Netherlands laws package assets."""

from __future__ import annotations

from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
NETHERLANDS_LAWS_DIR = PACKAGE_DIR
DATASETS_DIR = PACKAGE_DIR / "datasets"
RAW_DATA_DIR = DATASETS_DIR / "raw"
HF_DATA_DIR = DATASETS_DIR / "huggingface"
DOCS_DIR = PACKAGE_DIR / "docs"

REPO_ROOT = PACKAGE_DIR.parents[4]
LEGACY_HF_READY_DIR = REPO_ROOT / "hf_ready"
LEGACY_NL_OUTPUT_DIR = REPO_ROOT / "nl_test_output"
LEGACY_NL_OUTPUT_DOCS_DIR = REPO_ROOT / "nl_test_output_docs"


def ensure_package_dirs() -> None:
    for path in [DATASETS_DIR, RAW_DATA_DIR, HF_DATA_DIR, DOCS_DIR]:
        path.mkdir(parents=True, exist_ok=True)
