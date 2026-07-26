#!/usr/bin/env python3
"""Build and optionally query the verified SkillCenter pilot GraphRAG index."""

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

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_graphrag import (  # noqa: E402
    DEFAULT_NEIGHBOR_K,
    SkillCenterGraphRAGConfig,
    SkillCenterGraphRAGIndex,
    build_skillcenter_graphrag_index,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_bm25 import (  # noqa: E402
    SkillCenterBM25Index,
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


def _load_accelerate_router() -> Callable[..., Any]:
    try:
        module = importlib.import_module("ipfs_accelerate_py.embeddings_router")
        return module.embed_texts_batched
    except (ImportError, AttributeError):
        pass
    candidates = (
        REPOSITORY_ROOT.parent / "ipfs_accelerate_py",
        REPOSITORY_ROOT / "ipfs_accelerate_py",
    )
    for candidate in candidates:
        package = candidate / "ipfs_accelerate_py/embeddings_router.py"
        if not package.is_file():
            continue
        candidate_text = str(candidate)
        if candidate_text in sys.path:
            sys.path.remove(candidate_text)
        sys.path.insert(0, candidate_text)
        for module_name in tuple(sys.modules):
            if module_name == "ipfs_accelerate_py" or module_name.startswith(
                "ipfs_accelerate_py."
            ):
                sys.modules.pop(module_name, None)
        importlib.invalidate_caches()
        try:
            module = importlib.import_module(
                "ipfs_accelerate_py.embeddings_router"
            )
            return module.embed_texts_batched
        except (ImportError, AttributeError):
            continue
    raise RuntimeError(
        "ipfs_accelerate_py.embeddings_router with embed_texts_batched is required"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build an integrity-bound FAISS + corpus-evidence GraphRAG index "
            "from complete SkillCenter embedding checkpoints."
        )
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=list(DEFAULT_PROFILES),
        help="Pilot profiles to combine into one graph snapshot.",
    )
    parser.add_argument("--model", default="thenlper/gte-small")
    parser.add_argument(
        "--neighbor-k",
        type=_positive_int,
        default=DEFAULT_NEIGHBOR_K,
    )
    parser.add_argument(
        "--neighbor-backend",
        choices=("bm25", "embedding"),
        default="bm25",
        help=(
            "Backend used to create graph NEIGHBOR_OF edges. Dense vectors "
            "remain available for query retrieval with either choice."
        ),
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument(
        "--embedding-base-dir",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--bm25-dir",
        type=Path,
        default=None,
        help="Verified BM25 index used when --neighbor-backend=bm25.",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Require source snapshots to already be in the verified cache.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Load and fully verify an existing index without rebuilding.",
    )
    parser.add_argument(
        "--smoke-query",
        default="",
        help="After building, embed this query through the accelerator router.",
    )
    parser.add_argument(
        "--query-k",
        type=_positive_int,
        default=5,
    )
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
    data_home = _xdg_path("XDG_DATA_HOME", "~/.local/share")
    cache_dir = args.cache_dir or (
        _xdg_path("XDG_CACHE_HOME", "~/.cache")
        / "ipfs_datasets_py/skillcenter"
    )
    embedding_base = args.embedding_base_dir or (
        data_home
        / "ipfs_datasets_py/intent-ir/skillcenter-embeddings"
        / pilot.dataset_revision
    )
    bm25_dir = args.bm25_dir or (
        data_home
        / "ipfs_datasets_py/intent-ir/skillcenter-bm25"
        / pilot.dataset_revision
        / "pilot"
    )
    output_name = _slug(args.model)
    if args.neighbor_backend == "bm25":
        output_name += "-bm25"
    output_dir = args.output_dir or (
        data_home
        / "ipfs_datasets_py/intent-ir/skillcenter-graphrag"
        / pilot.dataset_revision
        / output_name
    )

    if args.verify_only:
        index = SkillCenterGraphRAGIndex.load(output_dir)
        summary = index.summary
    else:
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
        embedding_dirs = [
            embedding_base / bundle.profile / _slug(args.model)
            for bundle in selected
        ]
        summary = build_skillcenter_graphrag_index(
            readers,
            embedding_dirs=embedding_dirs,
            output_dir=output_dir,
            bm25_dir=(
                bm25_dir
                if args.neighbor_backend == "bm25"
                else None
            ),
            config=SkillCenterGraphRAGConfig(
                neighbor_k=args.neighbor_k
            ),
        )
        index = SkillCenterGraphRAGIndex.load(output_dir)

    payload: dict[str, Any] = {
        "graphrag_index": summary.to_dict(),
    }
    query = str(args.smoke_query or "").strip()
    if query:
        embed_texts_batched = _load_accelerate_router()

        def _embedder(texts: Sequence[str]) -> object:
            return embed_texts_batched(
                texts,
                batch_size=1,
                max_workers=1,
                model_name=str(index.manifest["embedding_model"]),
                provider=str(index.manifest["embedding_provider"]),
                device=str(index.manifest["embedding_device"]),
                show_progress_bar=False,
            )

        payload["smoke_query"] = {
            "dense_hits": [
                hit.to_dict()
                for hit in index.search_text(
                    query,
                    embedder=_embedder,
                    k=args.query_k,
                )
            ],
            "query": query,
        }
        if str(index.manifest["neighbor_backend"]) == "bm25-okapi":
            bm25_index = SkillCenterBM25Index.load(bm25_dir)
            payload["smoke_query"]["bm25_hits"] = [
                hit.to_dict()
                for hit in bm25_index.search(query, k=args.query_k)
            ]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
