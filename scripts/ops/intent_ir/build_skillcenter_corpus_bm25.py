#!/usr/bin/env python3
"""Build or verify the complete CID-keyed SkillCenter BM25 index."""

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

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_corpus_bm25 import (  # noqa: E402
    DEFAULT_BUILD_BATCH_SIZE,
    SkillCenterCorpusBM25Index,
    build_skillcenter_corpus_bm25,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.snapshot import (  # noqa: E402
    INSPECTED_SKILLCENTER_PILOT_REVISION,
)


DEFAULT_REVISION = INSPECTED_SKILLCENTER_PILOT_REVISION
EXPECTED_FULL_RECORDS = 216_972


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
            "Build a contentless SQLite FTS5/Okapi BM25 index covering every "
            "entry_cid in the canonical SkillCenter corpus."
        )
    )
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=DEFAULT_BUILD_BATCH_SIZE,
    )
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--smoke-query", default="")
    parser.add_argument("--query-k", type=_positive_int, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    data_home = _xdg_path("XDG_DATA_HOME", "~/.local/share")
    corpus_dir = args.corpus_dir or (
        data_home
        / "ipfs_datasets_py/intent-ir/skillcenter-corpus"
        / args.revision
        / "full"
    )
    output_dir = args.output_dir or (
        data_home
        / "ipfs_datasets_py/intent-ir/skillcenter-bm25"
        / args.revision
        / "full-cid"
    )
    if args.verify_only:
        index = SkillCenterCorpusBM25Index.load(
            output_dir,
            corpus_dir=corpus_dir,
        )
        summary = index.summary
    else:
        summary = build_skillcenter_corpus_bm25(
            corpus_dir,
            output_dir=output_dir,
            batch_size=args.batch_size,
        )
        index = SkillCenterCorpusBM25Index.load(
            output_dir,
            corpus_dir=corpus_dir,
        )
    if summary.indexed_entries != EXPECTED_FULL_RECORDS:
        raise ValueError(
            "full BM25 index does not cover every canonical entry_cid"
        )
    payload: dict[str, object] = {"bm25_index": summary.to_dict()}
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
