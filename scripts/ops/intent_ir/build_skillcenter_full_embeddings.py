#!/usr/bin/env python3
"""Build resumable one-vector-per-entry embeddings for all SkillCenter CIDs."""

from __future__ import annotations

import argparse
import hashlib
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

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_corpus import (  # noqa: E402
    SkillCenterCorpusIndex,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_embeddings import (  # noqa: E402
    DEFAULT_EMBEDDING_DEVICE,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
    SkillCenterEmbeddingConfig,
    iter_skillcenter_embedding_rows,
    load_skillcenter_embedding_corpus,
    run_skillcenter_embedding_job,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (  # noqa: E402
    DEFAULT_SKILLCENTER_DATASET_ID,
    SkillCenterBundleReader,
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


def _default_hf_snapshot(dataset_id: str, revision: str) -> Path:
    hf_home = str(os.environ.get("HF_HOME") or "").strip()
    cache = (
        Path(hf_home).expanduser()
        if hf_home
        else Path("~/.cache/huggingface").expanduser()
    )
    return (
        cache
        / "hub"
        / ("datasets--" + dataset_id.replace("/", "--"))
        / "snapshots"
        / revision
    )


def _load_accelerate_router() -> tuple[
    Callable[..., Any],
    Callable[[], dict[str, object]],
]:
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
        "ipfs_accelerate_py.embeddings_router is required"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Embed every canonical SkillCenter entry through the accelerator "
            "router, one vector per entry_cid, in resumable bundle checkpoints."
        )
    )
    parser.add_argument("--dataset-id", default=DEFAULT_SKILLCENTER_DATASET_ID)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--source-dir", type=Path, default=None)
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--bundles",
        nargs="*",
        default=None,
        help="Optional exact SQLite filenames; default processes all 24.",
    )
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--provider", default=DEFAULT_EMBEDDING_PROVIDER)
    parser.add_argument("--device", default=DEFAULT_EMBEDDING_DEVICE)
    parser.add_argument("--source-batch-size", type=_positive_int, default=128)
    parser.add_argument("--router-batch-size", type=_positive_int, default=32)
    parser.add_argument("--router-workers", type=_positive_int, default=1)
    parser.add_argument(
        "--router-response-cache",
        action="store_true",
        help=(
            "Retain per-text vectors in the router's process cache. Disabled "
            "by default because the resumable Parquet checkpoints are the "
            "durable cache and a full run contains 216,972 vectors."
        ),
    )
    parser.add_argument("--input-chars", type=_positive_int, default=4096)
    parser.add_argument(
        "--max-records-per-bundle",
        type=_non_negative_int,
        default=None,
    )
    parser.add_argument("--verify-only", action="store_true")
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
    output_root = args.output_dir or (
        data_home
        / "ipfs_datasets_py/intent-ir/skillcenter-embeddings"
        / args.revision
        / "full-cid"
        / _slug(args.model)
    )
    source_dir = (
        args.source_dir
        if args.source_dir is not None
        else _default_hf_snapshot(args.dataset_id, args.revision)
    ).expanduser()
    sqlite_files = sorted(source_dir.glob("*.sqlite"), key=lambda path: path.name)
    if args.bundles:
        selected = set(args.bundles)
        available = {path.name for path in sqlite_files}
        unknown = selected - available
        if unknown:
            raise ValueError(
                "unknown bundle filename(s): " + ", ".join(sorted(unknown))
            )
        sqlite_files = [path for path in sqlite_files if path.name in selected]
    if not sqlite_files:
        raise ValueError("no SkillCenter SQLite bundles selected")
    config = SkillCenterEmbeddingConfig(
        model_name=args.model,
        provider=args.provider,
        device=args.device,
        source_batch_size=args.source_batch_size,
        chunk_chars=args.input_chars,
        chunk_overlap_chars=0,
        internal_retrieval_all_records=True,
        max_chunks_per_record=1,
    )
    corpus = SkillCenterCorpusIndex.load(corpus_dir, verify_rows=False)
    output_root.mkdir(parents=True, exist_ok=True)
    summaries = []
    router_trace: dict[str, object] = {}
    if args.verify_only:
        for path in sqlite_files:
            bundle_output = output_root / _slug(path.stem)
            manifest = load_skillcenter_embedding_corpus(bundle_output)
            summaries.append(
                {
                    "bundle": path.name,
                    "embedding_manifest": manifest,
                }
            )
    else:
        os.environ["IPFS_ACCELERATE_PY_ROUTER_RESPONSE_CACHE"] = (
            "1" if args.router_response_cache else "0"
        )
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

        for path in sqlite_files:
            reader = SkillCenterBundleReader(
                path,
                dataset_id=args.dataset_id,
                dataset_revision=args.revision,
                repository_file=path.name,
                allow_declared_count_mismatch=True,
            )
            summary = run_skillcenter_embedding_job(
                reader,
                profile=_slug(path.stem),
                output_dir=output_root / _slug(path.stem),
                config=config,
                embedder=_embedder,
                max_records=args.max_records_per_bundle,
            )
            summaries.append(
                {"bundle": path.name, "embedding_run": summary.to_dict()}
            )
            print(
                json.dumps(summaries[-1], sort_keys=True),
                file=sys.stderr,
                flush=True,
            )
        router_trace = get_last_embedding_trace()
    coverage: set[str] = set()
    complete = True
    vector_count = 0
    for path in sqlite_files:
        bundle_output = output_root / _slug(path.stem)
        manifest = load_skillcenter_embedding_corpus(
            bundle_output,
            require_complete=False,
        )
        complete = complete and manifest["status"] == "complete"
        vector_count += int(manifest["vector_count"])
        for row in iter_skillcenter_embedding_rows(
            bundle_output,
            columns=("entry_cid",),
            require_complete=False,
        ):
            entry_cid = str(row["entry_cid"])
            if entry_cid in coverage:
                raise ValueError(f"duplicate embedded entry_cid: {entry_cid}")
            coverage.add(entry_cid)
    if args.bundles is None and complete:
        if coverage != corpus.entry_cids or vector_count != EXPECTED_FULL_RECORDS:
            raise ValueError(
                "complete embedding run does not cover every corpus entry_cid"
            )
    aggregate = {
        "complete": complete,
        "corpus_cid": corpus.manifest["files"]["corpus"]["cid"],
        "corpus_manifest_sha256": hashlib.sha256(
            (corpus.root / "manifest.json").read_bytes()
        ).hexdigest(),
        "covered_entry_cids": len(coverage),
        "dataset_revision": args.revision,
        "model": args.model,
        "primary_key": "entry_cid",
        "selected_bundles": [path.name for path in sqlite_files],
        "vector_count": vector_count,
    }
    print(
        json.dumps(
            {
                "aggregate": aggregate,
                "bundle_runs": summaries,
                "router_trace": router_trace,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
