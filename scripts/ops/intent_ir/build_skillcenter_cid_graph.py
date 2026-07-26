#!/usr/bin/env python3
"""Build or resume the complete CID-keyed SkillCenter knowledge graph."""

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

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_cid_graph import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_NEIGHBOR_K,
    SkillCenterCIDGraphConfig,
    SkillCenterCIDGraphIndex,
    build_skillcenter_cid_graph,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_corpus_bm25 import (  # noqa: E402
    SkillCenterCorpusBM25Index,
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


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
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
            "Build a resumable SQLite property graph whose Skill nodes use "
            "entry_cid primary keys and whose neighbor edges come from BM25."
        )
    )
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--bm25-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--neighbor-k",
        type=_positive_int,
        default=DEFAULT_NEIGHBOR_K,
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=DEFAULT_BATCH_SIZE,
    )
    parser.add_argument("--query-workers", type=_positive_int, default=16)
    parser.add_argument(
        "--max-neighbor-sources",
        type=_non_negative_int,
        default=None,
        help="Optional checkpoint bound; rerun to resume after this many sources.",
    )
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--smoke-query", default="")
    parser.add_argument("--query-k", type=_positive_int, default=5)
    parser.add_argument("--print-progress", action="store_true")
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
    bm25_dir = args.bm25_dir or (
        data_home
        / "ipfs_datasets_py/intent-ir/skillcenter-bm25"
        / args.revision
        / "full-cid"
    )
    output_dir = args.output_dir or (
        data_home
        / "ipfs_datasets_py/intent-ir/skillcenter-graphrag"
        / args.revision
        / "full-cid-bm25"
    )
    graph: SkillCenterCIDGraphIndex | None = None
    if args.verify_only:
        graph = SkillCenterCIDGraphIndex.load(
            output_dir,
            corpus_dir=corpus_dir,
            bm25_dir=bm25_dir,
        )
        result: object = graph.summary
    else:
        def _progress(payload: dict[str, object]) -> None:
            if args.print_progress:
                print(
                    json.dumps({"graph_progress": payload}, sort_keys=True),
                    file=sys.stderr,
                    flush=True,
                )

        result = build_skillcenter_cid_graph(
            corpus_dir,
            bm25_dir,
            output_dir=output_dir,
            config=SkillCenterCIDGraphConfig(
                neighbor_k=args.neighbor_k,
                batch_size=args.batch_size,
                query_workers=args.query_workers,
            ),
            progress_callback=_progress,
            max_neighbor_sources=args.max_neighbor_sources,
        )
    if isinstance(result, dict):
        print(json.dumps({"graph_progress": result}, indent=2, sort_keys=True))
        return 0
    if result.skill_nodes != EXPECTED_FULL_RECORDS:
        raise ValueError(
            "completed graph does not contain every entry_cid Skill node"
        )
    if graph is None:
        graph = SkillCenterCIDGraphIndex.load(
            output_dir,
            corpus_dir=corpus_dir,
            bm25_dir=bm25_dir,
            # A successful build already returned through the same full
            # integrity loader. Avoid scanning the multi-gigabyte SQLite
            # artifact twice just to run the optional smoke query.
            verify_integrity=False,
        )
    payload: dict[str, object] = {"graph": result.to_dict()}
    query = str(args.smoke_query or "").strip()
    if query:
        bm25 = SkillCenterCorpusBM25Index.load(
            bm25_dir,
            verify_integrity=False,
        )
        hits = bm25.search(query, k=args.query_k)
        payload["smoke_query"] = {
            "hits": [
                {
                    **hit.to_dict(),
                    "graph_neighbors": graph.neighbors(
                        hit.entry_cid,
                        k=args.query_k,
                    ),
                }
                for hit in hits
            ],
            "query": query,
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
