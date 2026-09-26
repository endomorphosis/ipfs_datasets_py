#!/usr/bin/env python3
"""Ingest U.S. Code through sparse GraphRAG and queue compiler gaps.

Retrieved documents are compiled. Failed jobs go to the accelerate supervisor
todo loop and a Hugging Face todo package. They are not sent to the
autoencoder, compiler, or decompiler. A compiled row is not a proof.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "0")


def summarize_spans(spans: list[dict[str, Any]]) -> dict[str, Any]:
    status = Counter(str(span.get("status") or "") for span in spans)
    return {
        "span_count": len(spans),
        "status_counts": dict(status),
        "compiled_count": int(status.get("compiled", 0)),
        "gap_count": int(status.get("gap", 0)),
        "roundtrip_ok_count": int(status.get("roundtrip_ok", 0)),
        "formalized": False,
        "admitted": False,
    }


def load_hits(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("hits") or payload.get("documents") or []
        return [dict(item) for item in rows if isinstance(item, dict)]
    raise ValueError("hits file must be a JSON object or array")


def compile_uscode(hits: list[dict[str, Any]], *, query: str = "", release_id: str = "") -> dict[str, Any]:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    from ipfs_datasets_py.logic.autoformal.uscode_ingest import (
        census_uscode_ledger,
        inventory_uscode_documents,
    )

    ledger = inventory_uscode_documents(hits, query=query, release_id=release_id)
    pending = iter(span for span in ledger["spans"] if span["status"] == "uncompiled")
    session = AutoformalSession()

    def one(span_text: str) -> dict[str, Any]:
        span = next(pending)
        if span_text != span["text"]:
            raise ValueError("U.S. Code census callback order changed")
        span["compiler_document_id"] = span["source_span_id"]
        return compile_span(session, span_text, span["compiler_document_id"])

    return census_uscode_ledger(ledger, one)


def resolve_hits(
    hits: list[dict[str, Any]] | None = None,
    *,
    hits_path: Path | None = None,
    searcher: Any | None = None,
    query: str = "",
) -> list[dict[str, Any]]:
    """Load offline hits or retrieve them through sparse GraphRAG."""

    if hits is not None:
        return [dict(item) for item in hits if isinstance(item, dict)]
    if hits_path is not None:
        return load_hits(Path(hits_path))
    if searcher is None:
        raise ValueError("hits, hits_path, or a sparse GraphRAG searcher is required")
    from ipfs_datasets_py.logic.autoformal.uscode_ingest import retrieve_uscode_hits

    return retrieve_uscode_hits(searcher, query)


def agreement_from_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import agreement_from_spans

    return agreement_from_spans(ledger.get("spans") or [])


def run_uscode_autoformal(
    *,
    hits: list[dict[str, Any]] | None = None,
    hits_path: Path | None = None,
    searcher: Any | None = None,
    query: str = "",
    release_id: str = "",
    board_path: Path | None = None,
    huggingface_package: Path | None = None,
    repository_id: str | None = None,
    skip_upload: bool = False,
    dry_run: bool = True,
    approval: Any | None = None,
    publisher: Any | None = None,
    pointer_path: Path | None = None,
    task_source: Any | None = None,
    packet_directory: Path | None = None,
    code_identity: str = "",
    model_identity: str = "",
) -> dict[str, Any]:
    """Retrieve, census, and queue U.S. Code gaps. Does not write JSONL."""

    resolved = resolve_hits(hits, hits_path=hits_path, searcher=searcher, query=query)
    census = compile_uscode(resolved, query=query, release_id=release_id)
    ledger = census["ledger"]
    summary = summarize_spans(ledger["spans"])
    agreement = agreement_from_ledger(ledger)
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import submit_discrepancies

    upload = None
    if not skip_upload and not agreement.get("agrees"):
        if huggingface_package is None:
            raise ValueError("huggingface_package is required unless skip_upload is set")
        from ipfs_datasets_py.huggingface.autoformal_todo import upload_autoformal_todos

        def upload(
            tasks,
            _root=huggingface_package,
            _repo=repository_id,
            _dry_run=dry_run,
            _approval=approval,
            _publisher=publisher,
            _pointer=pointer_path,
        ):
            return upload_autoformal_todos(
                tasks,
                _root,
                repository_id=_repo,
                dry_run=_dry_run,
                approval=_approval,
                publisher=_publisher,
                pointer_path=_pointer,
            )

    native = None
    if task_source is not None and not agreement.get("agrees"):
        from ipfs_datasets_py.logic.autoformal.supervisor_queue import submit_native_discrepancies

        if not (release_id and code_identity and model_identity and packet_directory is not None):
            raise ValueError(
                "native supervisor enqueue requires release_id, code_identity, "
                "model_identity, and packet_directory"
            )

        def native(
            agreement_payload,
            huggingface_locator=None,
            _source=task_source,
            _packets=packet_directory,
            _release=release_id,
            _code=code_identity,
            _model=model_identity,
            _query=query,
        ):
            return submit_native_discrepancies(
                _source,
                agreement_payload,
                packet_directory=Path(_packets),
                release_id=_release,
                code_identity=_code,
                model_identity=_model,
                query=_query,
                huggingface_locator=huggingface_locator,
            )

    receipt = submit_discrepancies(
        agreement,
        board_path=None if agreement.get("agrees") else board_path,
        query=query,
        release_id=release_id,
        upload=upload,
        native=native,
    )
    receipt["admitted"] = False
    receipt["census_error"] = str(census.get("error") or "")
    receipt["census_stopped"] = bool(census.get("stopped"))
    receipt["formalized"] = False
    receipt["hits"] = resolved
    receipt["jsonl_written"] = False
    receipt["ledger"] = ledger
    receipt["spans"] = list(ledger.get("spans") or [])
    receipt["summary"] = summary
    return receipt


def schedule_packaged_todos(pointer: Path, **kwargs: Any) -> dict[str, Any]:
    """Register a packaged Hugging Face todo release on the accelerate queue."""

    from ipfs_datasets_py.logic.autoformal.huggingface_schedule import schedule_from_pointer

    return schedule_from_pointer(pointer, **kwargs)


def main(argv: list[str] | None = None, *, searcher: Any | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hits", type=Path, help="Sparse GraphRAG hit JSON (offline).")
    parser.add_argument("--query", default="", help="Sparse GraphRAG query when retrieving instead of --hits.")
    parser.add_argument("--graphrag-root", type=Path, help="Local pinned sparse GraphRAG release directory.")
    parser.add_argument("--graphrag-repo-id", default="justicedao/ipfs_uscode")
    parser.add_argument("--graphrag-revision", default="", help="Immutable 40-hex release revision.")
    parser.add_argument("--graphrag-cache", type=Path, default=None)
    parser.add_argument("--release-id", default="")
    parser.add_argument(
        "--board",
        type=Path,
        default=REPO_ROOT / "workspace" / "todo-queues" / "uscode-autoformal.todo.md",
    )
    parser.add_argument(
        "--huggingface-package",
        type=Path,
        default=REPO_ROOT / "workspace" / "todo-queues" / "uscode-autoformal-hf",
    )
    parser.add_argument("--repository-id", default="")
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument(
        "--pointer",
        type=Path,
        default=REPO_ROOT / "workspace" / "todo-queues" / "autoformal-todo-release-pointer.json",
    )
    parser.add_argument("--database", type=Path, help="Accelerate DuckDB task database.")
    parser.add_argument("--runtime-root", type=Path, help="Directory for sealed repair packets.")
    parser.add_argument("--code-identity", default="")
    parser.add_argument("--model-identity", default="")
    parser.add_argument(
        "--schedule-queue",
        type=Path,
        default=None,
        help="After packaging, register Hugging Face todos on this accelerate queue file.",
    )
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--max-validation-seconds", type=int, default=None)
    args = parser.parse_args(argv)
    if args.hits is None and searcher is None:
        if not args.query:
            print("provide --hits, or --query with --graphrag-revision")
            return 2
        import re

        if not re.fullmatch(r"[0-9a-f]{40}", str(args.graphrag_revision or "")):
            print("graphrag-revision must be an immutable 40-hex commit")
            return 2
        from ipfs_datasets_py.logic.autoformal.uscode_ingest import pinned_sparse_graphrag_searcher

        searcher = pinned_sparse_graphrag_searcher(
            repo_id=args.graphrag_repo_id,
            revision=args.graphrag_revision,
            release_root=args.graphrag_root,
            cache_dir=args.graphrag_cache,
        )
    if args.hits is not None and not args.hits.is_file():
        print(f"hits file is missing: {args.hits}")
        return 2
    if args.board.exists() or args.board.is_symlink():
        print(f"board already exists; choose a new --board path: {args.board}")
        return 2
    if not args.skip_upload and (args.huggingface_package.exists() or args.huggingface_package.is_symlink()):
        print(f"huggingface package already exists; choose a new --huggingface-package path: {args.huggingface_package}")
        return 2
    started = time.monotonic()
    task_source = None
    packet_directory = None
    if args.database is not None:
        if args.runtime_root is None or not args.code_identity or not args.model_identity or not args.release_id:
            print("native enqueue requires --database, --runtime-root, --release-id, --code-identity, and --model-identity")
            return 2
        from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource

        args.database.parent.mkdir(parents=True, exist_ok=True)
        task_source = DatabaseTaskSource(args.database)
        packet_directory = args.runtime_root / "packets"
    try:
        receipt = run_uscode_autoformal(
            hits_path=args.hits,
            searcher=searcher,
            query=args.query,
            release_id=args.release_id,
            board_path=args.board,
            huggingface_package=args.huggingface_package,
            repository_id=args.repository_id or None,
            skip_upload=args.skip_upload,
            dry_run=True,
            pointer_path=None if args.skip_upload else args.pointer,
            task_source=task_source,
            packet_directory=packet_directory,
            code_identity=args.code_identity,
            model_identity=args.model_identity,
        )
    finally:
        close = getattr(task_source, "close", None)
        if callable(close):
            close()
    summary = receipt["summary"]
    locator = dict(receipt.get("locator") or receipt.get("huggingface", {}).get("locator") or {})
    if args.schedule_queue is not None:
        pointer = Path(
            ((receipt.get("huggingface") or {}).get("pointer") or {}).get("pointer_path")
            or args.pointer
        )
        if args.skip_upload or not pointer.is_file():
            print("schedule-queue requires a Hugging Face pointer; omit --skip-upload")
            return 2
        receipt["scheduled"] = schedule_packaged_todos(
            pointer,
            repo_root=REPO_ROOT,
            board=args.board,
            queue_path=args.schedule_queue,
            package_root=args.huggingface_package,
            max_tokens=args.max_tokens,
            max_validation_seconds=args.max_validation_seconds,
        )
    print(
        f"compiler spans {summary['span_count']} compiled {summary['compiled_count']} "
        f"gaps {summary['gap_count']} elapsed {time.monotonic() - started:.1f}s",
        flush=True,
    )
    print(
        f"formalized=false compiled={summary['compiled_count']} "
        f"supervisor_tasks={receipt.get('task_count', 0)} "
        f"native_inserted={(receipt.get('native_queue') or {}).get('task_count', 0)} "
        f"jsonl_written=false wrote_compiler={receipt.get('wrote_compiler')} "
        f"locator={locator.get('dataset_repo_id', '')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
