#!/usr/bin/env python3
"""Build or verify the full entry_cid-keyed SkillCenter FAISS index."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_cid_vectors import (  # noqa: E402
    SkillCenterCIDVectorIndex,
    build_skillcenter_cid_vector_index,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.snapshot import (  # noqa: E402
    INSPECTED_SKILLCENTER_PILOT_REVISION,
)


DEFAULT_REVISION = INSPECTED_SKILLCENTER_PILOT_REVISION
DEFAULT_MODEL = "thenlper/gte-small"
EXPECTED_FULL_RECORDS = 216_972


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-").lower()
    return slug or "unnamed"


def _xdg_path(environment_name: str, fallback: str) -> Path:
    configured = str(os.environ.get(environment_name) or "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else Path(fallback).expanduser()
    )


def _load_router() -> Callable[..., Any]:
    candidates = (
        None,
        REPOSITORY_ROOT.parent / "ipfs_accelerate_py",
        REPOSITORY_ROOT / "ipfs_accelerate_py",
    )
    for candidate in candidates:
        if candidate is not None:
            package = candidate / "ipfs_accelerate_py/embeddings_router.py"
            if not package.is_file():
                continue
            sys.path.insert(0, str(candidate))
        try:
            module = importlib.import_module(
                "ipfs_accelerate_py.embeddings_router"
            )
            return module.embed_texts_batched
        except (ImportError, AttributeError):
            continue
    raise RuntimeError("ipfs_accelerate_py embeddings router is required")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a FAISS IndexIDMap2 whose canonical metadata primary key "
            "and join key is SkillCenter entry_cid."
        )
    )
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--embedding-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--smoke-query", default="")
    parser.add_argument("--query-k", type=_positive_int, default=5)
    parser.add_argument(
        "--query-device",
        default="cpu",
        help="Device used only to embed --smoke-query (for example cpu or cuda).",
    )
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
    embedding_root = args.embedding_dir or (
        data_home
        / "ipfs_datasets_py/intent-ir/skillcenter-embeddings"
        / args.revision
        / "full-cid"
        / _slug(args.model)
    )
    output_dir = args.output_dir or (
        data_home
        / "ipfs_datasets_py/intent-ir/skillcenter-vectors"
        / args.revision
        / "full-cid"
        / _slug(args.model)
    )
    index: SkillCenterCIDVectorIndex | None = None
    if args.verify_only:
        index = SkillCenterCIDVectorIndex.load(
            output_dir,
            corpus_dir=corpus_dir,
        )
        summary = index.summary
    else:
        embedding_dirs = sorted(
            path.parent
            for path in embedding_root.glob("*/manifest.json")
        )
        summary = build_skillcenter_cid_vector_index(
            corpus_dir,
            embedding_dirs,
            output_dir=output_dir,
        )
    if summary.vector_count != EXPECTED_FULL_RECORDS:
        raise ValueError("FAISS index does not cover every entry_cid")
    payload: dict[str, object] = {"vector_index": summary.to_dict()}
    query = str(args.smoke_query or "").strip()
    if query:
        if index is None:
            # The builder already performed a full post-write reload against
            # the corpus. Reload only the searchable files needed by this
            # optional query instead of repeating corpus coverage validation.
            index = SkillCenterCIDVectorIndex.load(output_dir)
        embed_texts_batched = _load_router()
        vector = embed_texts_batched(
            [query],
            batch_size=1,
            max_workers=1,
            model_name=summary.model_name,
            provider="huggingface",
            device=args.query_device,
            show_progress_bar=False,
        )[0]
        payload["smoke_query"] = {
            "hits": [
                hit.to_dict()
                for hit in index.search_vector(vector, k=args.query_k)
            ],
            "query": query,
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
