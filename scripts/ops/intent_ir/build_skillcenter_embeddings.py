#!/usr/bin/env python3
"""Build resumable SkillCenter embeddings through ipfs_accelerate_py."""

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

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_embeddings import (  # noqa: E402
    DEFAULT_CHUNK_CHARS,
    DEFAULT_CHUNK_OVERLAP_CHARS,
    DEFAULT_EMBEDDING_DEVICE,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_SOURCE_BATCH_SIZE,
    SkillCenterEmbeddingConfig,
    run_skillcenter_embedding_job,
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


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-").lower()
    return slug or "unnamed"


def _xdg_path(environment_name: str, fallback: str) -> Path:
    configured = str(os.environ.get(environment_name) or "").strip()
    return Path(configured).expanduser() if configured else Path(fallback).expanduser()


def _load_accelerate_router() -> tuple[Callable[..., Any], Callable[[], dict[str, object]]]:
    try:
        module = importlib.import_module("ipfs_accelerate_py.embeddings_router")
        return module.embed_texts_batched, module.get_last_embedding_trace
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
            return module.embed_texts_batched, module.get_last_embedding_trace
        except (ImportError, AttributeError):
            continue
    raise RuntimeError(
        "ipfs_accelerate_py.embeddings_router with embed_texts_batched is required"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Embed one pinned SkillCenter pilot bundle into atomic, resumable "
            "Parquet checkpoints."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Versioned two-bundle SkillCenter pilot manifest.",
    )
    parser.add_argument(
        "--profile",
        choices=("security-lite", "github-lite"),
        default="security-lite",
    )
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--provider", default=DEFAULT_EMBEDDING_PROVIDER)
    parser.add_argument("--device", default=DEFAULT_EMBEDDING_DEVICE)
    parser.add_argument(
        "--source-batch-size",
        type=_positive_int,
        default=DEFAULT_SOURCE_BATCH_SIZE,
    )
    parser.add_argument(
        "--router-batch-size",
        type=_positive_int,
        default=32,
    )
    parser.add_argument(
        "--router-workers",
        type=_positive_int,
        default=1,
    )
    parser.add_argument(
        "--chunk-chars",
        type=_positive_int,
        default=DEFAULT_CHUNK_CHARS,
    )
    parser.add_argument(
        "--chunk-overlap-chars",
        type=_non_negative_int,
        default=DEFAULT_CHUNK_OVERLAP_CHARS,
    )
    parser.add_argument(
        "--max-records",
        type=_non_negative_int,
        default=None,
        help="Process at most this many new source records; omit for the remainder.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Verified immutable bundle cache.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Embedding checkpoint directory.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Require the requested Hub snapshot to already be locally cached.",
    )
    parser.add_argument(
        "--print-progress",
        action="store_true",
        help="Emit router batch progress as JSON on stderr.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    pilot = SkillCenterPilotManifest.from_path(args.manifest)
    bundle = next(item for item in pilot.bundles if item.profile == args.profile)
    snapshot = pilot.snapshot_for(bundle)

    cache_dir = args.cache_dir or (
        _xdg_path("XDG_CACHE_HOME", "~/.cache")
        / "ipfs_datasets_py/skillcenter"
    )
    output_dir = args.output_dir or (
        _xdg_path("XDG_DATA_HOME", "~/.local/share")
        / "ipfs_datasets_py/intent-ir/skillcenter-embeddings"
        / pilot.dataset_revision
        / args.profile
        / _slug(args.model)
    )
    cache = SkillCenterSnapshotCache(
        cache_dir,
        fetcher=HuggingFaceSkillCenterFetcher(
            local_files_only=bool(args.offline)
        ),
    )
    reader = cache.open_reader(snapshot)
    embed_texts_batched, get_last_embedding_trace = _load_accelerate_router()

    def _progress(payload: dict[str, object]) -> None:
        if args.print_progress:
            print(
                json.dumps({"router_progress": payload}, sort_keys=True),
                file=sys.stderr,
                flush=True,
            )

    def _embedder(texts: Sequence[str]) -> object:
        return embed_texts_batched(
            texts,
            batch_size=args.router_batch_size,
            max_workers=args.router_workers,
            model_name=args.model,
            provider=args.provider,
            device=args.device,
            progress_callback=_progress,
            show_progress_bar=False,
        )

    config = SkillCenterEmbeddingConfig(
        model_name=args.model,
        provider=args.provider,
        device=args.device,
        source_batch_size=args.source_batch_size,
        chunk_chars=args.chunk_chars,
        chunk_overlap_chars=args.chunk_overlap_chars,
    )
    summary = run_skillcenter_embedding_job(
        reader,
        profile=args.profile,
        output_dir=output_dir,
        config=config,
        embedder=_embedder,
        max_records=args.max_records,
    )
    print(
        json.dumps(
            {
                "embedding_run": summary.to_dict(),
                "router_trace": get_last_embedding_trace(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
