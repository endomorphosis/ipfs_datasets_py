#!/usr/bin/env python3
"""Build or verify the complete CID-keyed SkillCenter Parquet corpus."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_corpus import (  # noqa: E402
    DEFAULT_CORPUS_BATCH_SIZE,
    SkillCenterCorpusIndex,
    build_skillcenter_corpus,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (  # noqa: E402
    DEFAULT_SKILLCENTER_DATASET_ID,
    SkillCenterBundleReader,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.snapshot import (  # noqa: E402
    INSPECTED_SKILLCENTER_PILOT_REVISION,
)


DEFAULT_DATASET_REVISION = INSPECTED_SKILLCENTER_PILOT_REVISION
EXPECTED_FULL_BUNDLE_COUNT = 24
EXPECTED_FULL_PHYSICAL_RECORDS = 216_972


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _xdg_path(environment_name: str, fallback: str) -> Path:
    configured = str(os.environ.get(environment_name) or "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else Path(fallback).expanduser()
    )


def _default_hf_snapshot(dataset_id: str, revision: str) -> Path:
    hf_home = str(os.environ.get("HF_HOME") or "").strip()
    cache = (
        Path(hf_home).expanduser()
        if hf_home
        else Path("~/.cache/huggingface").expanduser()
    )
    repo_slug = "datasets--" + dataset_id.replace("/", "--")
    return cache / "hub" / repo_slug / "snapshots" / revision


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize all 24 SQLite bundles in the pinned SkillCenter "
            "revision into one verified entry_cid-primary-key Parquet corpus."
        )
    )
    parser.add_argument("--dataset-id", default=DEFAULT_SKILLCENTER_DATASET_ID)
    parser.add_argument("--revision", default=DEFAULT_DATASET_REVISION)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help="Pinned Hub snapshot directory containing all SQLite bundles.",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=DEFAULT_CORPUS_BATCH_SIZE,
    )
    parser.add_argument(
        "--expected-bundles",
        type=_positive_int,
        default=EXPECTED_FULL_BUNDLE_COUNT,
    )
    parser.add_argument(
        "--expected-records",
        type=_positive_int,
        default=EXPECTED_FULL_PHYSICAL_RECORDS,
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Fetch the pinned SQLite snapshot if it is not already local.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Rehash and recompute every row identity without rebuilding.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    data_home = _xdg_path("XDG_DATA_HOME", "~/.local/share")
    output_dir = args.output_dir or (
        data_home
        / "ipfs_datasets_py/intent-ir/skillcenter-corpus"
        / args.revision
        / "full"
    )
    if args.verify_only:
        index = SkillCenterCorpusIndex.load(output_dir)
        summary = index.summary
    else:
        source_dir = (
            args.source_dir
            if args.source_dir is not None
            else _default_hf_snapshot(args.dataset_id, args.revision)
        ).expanduser()
        if not source_dir.is_dir() and args.download:
            from huggingface_hub import snapshot_download

            source_dir = Path(
                snapshot_download(
                    repo_id=args.dataset_id,
                    repo_type="dataset",
                    revision=args.revision,
                    allow_patterns=["*.sqlite"],
                    max_workers=8,
                )
            )
        if not source_dir.is_dir():
            raise FileNotFoundError(
                f"pinned snapshot is unavailable: {source_dir}; use --download"
            )
        sqlite_files = sorted(source_dir.glob("*.sqlite"), key=lambda path: path.name)
        if len(sqlite_files) != args.expected_bundles:
            raise ValueError(
                "full-corpus bundle coverage mismatch: "
                f"expected {args.expected_bundles}, found {len(sqlite_files)}"
            )
        readers = [
            SkillCenterBundleReader(
                path,
                dataset_id=args.dataset_id,
                dataset_revision=args.revision,
                repository_file=path.name,
                allow_declared_count_mismatch=True,
            )
            for path in sqlite_files
        ]
        physical_records = sum(reader.inspect().total_skills for reader in readers)
        if physical_records != args.expected_records:
            raise ValueError(
                "full-corpus physical row coverage mismatch: "
                f"expected {args.expected_records}, found {physical_records}"
            )
        summary = build_skillcenter_corpus(
            readers,
            output_dir=output_dir,
            batch_size=args.batch_size,
        )
    if (
        summary.bundle_count != args.expected_bundles
        or summary.source_records != args.expected_records
        or summary.unique_entry_cids != args.expected_records
    ):
        raise ValueError(
            "verified corpus does not have complete one-to-one CID coverage"
        )
    print(json.dumps({"skillcenter_corpus": summary.to_dict()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
