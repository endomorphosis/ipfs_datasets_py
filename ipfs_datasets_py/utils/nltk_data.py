"""NLTK data bootstrap utilities.

NLTK ships its models/corpora separately from the Python package. Some parts of
ipfs_datasets_py use tokenizers/taggers/chunkers that require common NLTK data
packages (e.g. punkt, averaged_perceptron_tagger).

We avoid hard failures when the data is missing by attempting a best-effort
download when allowed.

Environment controls:
- IPFS_DATASETS_PY_AUTO_NLTK_DOWNLOAD: default "1" (enabled). Set to "0"/"false"
  to disable downloads.
- IPFS_DATASETS_PY_NLTK_DOWNLOAD_QUIET: default "1".
- IPFS_DATASETS_PY_NLTK_DOWNLOAD_DIR: optional directory for NLTK downloads.
  If not set, NLTK uses its normal search paths (including $NLTK_DATA).

This module never raises on download failures.
"""

from __future__ import annotations

import os
from typing import Iterable, List, Optional, Sequence, Tuple


def _env_truthy(name: str, default: str = "1") -> bool:
    value = os.environ.get(name, default)
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _default_resources() -> Sequence[Tuple[str, str]]:
    # (nltk.data.find path, nltk.download package id)
    return (
        ("tokenizers/punkt", "punkt"),
        ("taggers/averaged_perceptron_tagger", "averaged_perceptron_tagger"),
        ("chunkers/maxent_ne_chunker", "maxent_ne_chunker"),
        ("corpora/words", "words"),
    )


def ensure_nltk_data(
    *,
    resources: Optional[Sequence[Tuple[str, str]]] = None,
    allow_download: Optional[bool] = None,
    quiet: Optional[bool] = None,
    download_dir: Optional[str] = None,
) -> List[str]:
    """Ensure common NLTK datasets are available.

    Returns a list of NLTK package ids that were downloaded.
    """

    try:
        import nltk  # type: ignore
    except Exception:
        return []

    if allow_download is None:
        allow_download = _env_truthy("IPFS_DATASETS_PY_AUTO_NLTK_DOWNLOAD", "1")
    if quiet is None:
        quiet = _env_truthy("IPFS_DATASETS_PY_NLTK_DOWNLOAD_QUIET", "1")
    if download_dir is None:
        download_dir = os.environ.get("IPFS_DATASETS_PY_NLTK_DOWNLOAD_DIR")

    # Avoid downloads during pytest runs (tests should be offline-friendly).
    if os.environ.get("PYTEST_CURRENT_TEST"):
        allow_download = False

    resources_to_check = resources or _default_resources()
    downloaded: List[str] = []

    for find_path, package_id in resources_to_check:
        try:
            nltk.data.find(find_path)
            continue
        except Exception:
            if not allow_download:
                continue
        try:
            ok = nltk.download(package_id, download_dir=download_dir, quiet=bool(quiet))
            if ok:
                downloaded.append(package_id)
        except Exception:
            # Best-effort only.
            continue

    return downloaded
