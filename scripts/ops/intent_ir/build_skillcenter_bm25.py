#!/usr/bin/env python3
"""Build and optionally query the verified SkillCenter BM25 pilot index."""

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

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_bm25 import (  # noqa: E402
    DEFAULT_BM25_B,
    DEFAULT_BM25_K1,
    SkillCenterBM25Config,
    SkillCenterBM25Index,
    build_skillcenter_bm25_index,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.pilot import (  # noqa: E402
    SkillCenterPilotManifest,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.snapshot import (  # noqa: E402
    HuggingFaceSkillCenterFetcher,
    SkillCenterSnapshotCache,
)


DEFAULT_MANIFEST = (
    REPOSITORY_ROOT / "tests/fixtures/intent_ir/skillcenter/manifest.json"
)
DEFAULT_PROFILES = ("security-lite", "github-lite")


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a policy-gated SkillCenter BM25 bag-of-words index with "
            "deterministic Parquet documents, terms, and postings."
        )
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=list(DEFAULT_PROFILES),
    )
    parser.add_argument("--k1", type=float, default=DEFAULT_BM25_K1)
    parser.add_argument("--b", type=float, default=DEFAULT_BM25_B)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--smoke-query", default="")
    parser.add_argument("--query-k", type=_positive_int, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    pilot = SkillCenterPilotManifest.from_path(args.manifest)
    unknown_profiles = set(args.profiles) - {
        item.profile for item in pilot.bundles
    }
    if unknown_profiles:
        raise ValueError(
            "unknown pilot profile(s): "
            + ", ".join(sorted(unknown_profiles))
        )
    output_dir = args.output_dir or (
        _xdg_path("XDG_DATA_HOME", "~/.local/share")
        / "ipfs_datasets_py/intent-ir/skillcenter-bm25"
        / pilot.dataset_revision
        / "pilot"
    )
    if args.verify_only:
        index = SkillCenterBM25Index.load(output_dir)
        summary = index.summary
    else:
        cache_dir = args.cache_dir or (
            _xdg_path("XDG_CACHE_HOME", "~/.cache")
            / "ipfs_datasets_py/skillcenter"
        )
        cache = SkillCenterSnapshotCache(
            cache_dir,
            fetcher=HuggingFaceSkillCenterFetcher(
                local_files_only=bool(args.offline)
            ),
        )
        selected = [
            item for item in pilot.bundles if item.profile in args.profiles
        ]
        readers = [
            cache.open_reader(pilot.snapshot_for(bundle))
            for bundle in selected
        ]
        summary = build_skillcenter_bm25_index(
            readers,
            output_dir=output_dir,
            config=SkillCenterBM25Config(k1=args.k1, b=args.b),
        )
        index = SkillCenterBM25Index.load(output_dir)

    payload = {"bm25_index": summary.to_dict()}
    query = str(args.smoke_query or "").strip()
    if query:
        payload["smoke_query"] = {
            "hits": [
                hit.to_dict()
                for hit in index.search(query, k=args.query_k)
            ],
            "query": query,
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
