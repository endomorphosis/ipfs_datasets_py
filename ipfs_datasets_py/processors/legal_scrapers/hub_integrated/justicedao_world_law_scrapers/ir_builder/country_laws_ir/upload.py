"""Hub upload is intentionally not implemented in this local pipeline.

Later publish (operator machine, never from this run):

    export HF_TOKEN=...   # never commit / never echo
    hf upload-large-folder justicedao/ipfs_malta_laws_ir \\
      /workspace/country-laws-ir/releases/ipfs_malta_laws_ir \\
      --repo-type dataset --no-private --num-workers 8 \\
      --exclude "**/__pycache__/**" --exclude "**/*.pyc"
"""

from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

from pathlib import Path
from typing import Any


def upload_release(local_dir: Path, repo_id: str) -> dict[str, Any]:
    raise RuntimeError(
        "Hub upload is disabled in the local country-laws-ir pipeline. "
        "Publish later with: hf upload-large-folder "
        f"{repo_id} {local_dir} --repo-type dataset --no-private --num-workers 8 "
        '--exclude "**/__pycache__/**" --exclude "**/*.pyc"'
    )
