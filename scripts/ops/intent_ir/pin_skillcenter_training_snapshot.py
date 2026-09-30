#!/usr/bin/env python3
"""Pin the Publicus/skillcenter-ir corpus snapshot used for Intent IR training."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.training.skillcenter_campaign import (  # noqa: E402
    DATASET_REPO_ID,
    DATASET_REVISION,
    _SNAPSHOT_ALLOW_PATTERNS,
    cache_root,
    pin_training_snapshot,
)


def _allowed(path: str) -> bool:
    if path in {"manifest.json", "README.md", "indexes/corpus_chunks.parquet"}:
        return True
    return path.startswith("data/corpus/") and path.endswith(".parquet")


def _measure(revision: str) -> int:
    from huggingface_hub import HfApi

    total = 0
    for item in HfApi().list_repo_tree(
        DATASET_REPO_ID,
        revision=revision,
        repo_type="dataset",
        recursive=True,
    ):
        path = str(getattr(item, "path", "") or getattr(item, "rfilename", ""))
        size = getattr(item, "size", None)
        if _allowed(path) and isinstance(size, int) and size > 0:
            total += size
    return total


def _download(revision: str, output_dir: Path) -> Path:
    from huggingface_hub import snapshot_download

    destination = output_dir / "snapshot"
    snapshot_download(
        repo_id=DATASET_REPO_ID,
        repo_type="dataset",
        revision=revision,
        allow_patterns=list(_SNAPSHOT_ALLOW_PATTERNS),
        local_dir=str(destination),
    )
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=DATASET_REVISION)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    output = args.output_dir or cache_root(args.revision)
    receipt = pin_training_snapshot(
        output,
        revision=args.revision,
        measure_bytes=lambda: _measure(args.revision),
        download=lambda destination: _download(args.revision, destination),
    )
    print(
        f"pinned {receipt['dataset_repo_id']}@{receipt['dataset_revision']} "
        f"files={receipt['file_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
