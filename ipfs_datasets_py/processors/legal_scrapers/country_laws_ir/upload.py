"""Hub upload is intentionally not implemented in this local pipeline.

Later publish (operator machine, never from this run):

    export HF_TOKEN=...   # never commit / never echo
    hf upload-large-folder justicedao/ipfs_malta_laws_ir \\
      /workspace/country-laws-ir/releases/ipfs_malta_laws_ir \\
      --repo-type dataset --no-private --num-workers 8 \\
      --exclude "**/__pycache__/**" --exclude "**/*.pyc"
"""

from __future__ import annotations

import os

from pathlib import Path
from typing import Any


def upload_release(local_dir: Path, repo_id: str) -> dict[str, Any]:
    raise RuntimeError(
        "Hub upload is disabled in the local country-laws-ir pipeline. "
        "Publish later with: hf upload-large-folder "
        f"{repo_id} {local_dir} --repo-type dataset --no-private --num-workers 8 "
        '--exclude "**/__pycache__/**" --exclude "**/*.pyc"'
    )
