#!/usr/bin/env python3
"""Build the complete Hugging Face SkillCenter Parquet release."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_hf_release import (  # noqa: E402
    DEFAULT_RELEASE_REPO_ID,
    add_skillcenter_hf_graph_navigation,
    build_skillcenter_hf_release,
    rebalance_skillcenter_hf_release_vectors,
    validate_skillcenter_hf_release,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.snapshot import (  # noqa: E402
    INSPECTED_SKILLCENTER_PILOT_REVISION,
)


DEFAULT_REVISION = INSPECTED_SKILLCENTER_PILOT_REVISION


def _data_home() -> Path:
    configured = str(os.environ.get("XDG_DATA_HOME") or "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else Path("~/.local/share").expanduser()
    )


def _defaults(revision: str) -> dict[str, Path]:
    base = _data_home() / "ipfs_datasets_py" / "intent-ir"
    return {
        "bm25": base / "skillcenter-bm25" / revision / "full-cid",
        "corpus": base / "skillcenter-corpus" / revision / "full",
        "graph": (
            base
            / "skillcenter-graphrag"
            / revision
            / "full-cid-bm25"
        ),
        "output": (
            base
            / "skillcenter-huggingface"
            / revision
            / "full-cid-zstd"
        ),
        "centroid_output": (
            base
            / "skillcenter-huggingface"
            / revision
            / "full-cid-zstd-centroid-v2"
        ),
        "graph_output": (
            base
            / "skillcenter-huggingface"
            / revision
            / "full-cid-zstd-graph-v3"
        ),
        "vectors": (
            base
            / "skillcenter-vectors"
            / revision
            / "full-cid"
            / "thenlper-gte-small-cuda"
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert complete SkillCenter corpus/BM25/graph/FAISS artifacts "
            "to sharded Zstandard Parquet for Hugging Face"
        )
    )
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--dataset-repo-id", default=DEFAULT_RELEASE_REPO_ID)
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--bm25-dir", type=Path, default=None)
    parser.add_argument("--graph-dir", type=Path, default=None)
    parser.add_argument("--vector-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--rebalance-from",
        type=Path,
        default=None,
        help=(
            "Build a v2 release by hard-linking stable artifacts from this "
            "release and rebuilding only centroid-sorted vector shards."
        ),
    )
    parser.add_argument(
        "--graph-navigation-from",
        type=Path,
        default=None,
        help=(
            "Build a v3 release by hard-linking a v2 release and adding "
            "paged incoming/outgoing graph adjacency artifacts."
        ),
    )
    parser.add_argument(
        "--query-script",
        type=Path,
        default=(
            REPOSITORY_ROOT
            / "scripts"
            / "ops"
            / "intent_ir"
            / "query_skillcenter_hf.py"
        ),
    )
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=(
            REPOSITORY_ROOT / "skills" / "query-skillcenter-hf"
        ),
    )
    parser.add_argument(
        "--semantic-traversal-module",
        type=Path,
        default=(
            REPOSITORY_ROOT
            / "ipfs_datasets_py"
            / "knowledge_graphs"
            / "query"
            / "semantic_traversal.py"
        ),
        help="Reusable traversal module bundled beside the remote client.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate an already completed output without rebuilding.",
    )
    return parser


def _progress(event: Mapping[str, Any]) -> None:
    print(json.dumps(dict(event), sort_keys=True), flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (
        args.rebalance_from is not None
        and args.graph_navigation_from is not None
    ):
        raise SystemExit(
            "--rebalance-from and --graph-navigation-from are mutually "
            "exclusive"
        )
    defaults = _defaults(args.revision)
    output_dir = args.output_dir or (
        defaults["graph_output"]
        if args.graph_navigation_from is not None
        else (
            defaults["centroid_output"]
            if args.rebalance_from is not None
            else defaults["output"]
        )
    )
    if args.validate_only:
        summary = validate_skillcenter_hf_release(output_dir)
    elif args.graph_navigation_from is not None:
        summary = add_skillcenter_hf_graph_navigation(
            args.graph_navigation_from,
            output_dir=output_dir,
            graph_dir=args.graph_dir or defaults["graph"],
            query_script=args.query_script,
            skill_dir=args.skill_dir,
            semantic_traversal_module=args.semantic_traversal_module,
            progress_callback=_progress,
        )
    elif args.rebalance_from is not None:
        summary = rebalance_skillcenter_hf_release_vectors(
            args.rebalance_from,
            output_dir=output_dir,
            corpus_dir=args.corpus_dir or defaults["corpus"],
            vector_dir=args.vector_dir or defaults["vectors"],
            query_script=args.query_script,
            skill_dir=args.skill_dir,
            semantic_traversal_module=args.semantic_traversal_module,
            progress_callback=_progress,
        )
    else:
        summary = build_skillcenter_hf_release(
            args.corpus_dir or defaults["corpus"],
            args.bm25_dir or defaults["bm25"],
            args.graph_dir or defaults["graph"],
            args.vector_dir or defaults["vectors"],
            output_dir=output_dir,
            dataset_repo_id=args.dataset_repo_id,
            query_script=args.query_script,
            skill_dir=args.skill_dir,
            semantic_traversal_module=args.semantic_traversal_module,
            progress_callback=_progress,
        )
    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
