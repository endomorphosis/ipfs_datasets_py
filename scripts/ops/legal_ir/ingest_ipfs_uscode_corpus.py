#!/usr/bin/env python3
"""Enqueue every justicedao/ipfs_uscode section and autoformalize pending spans.

Reads uscode_parquet/laws.parquet, splits each section into spans, and drains
the DuckDB span cache with the same compiler the supervisor loop uses. A
compile is not a legal admit. JSONL is not written.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")


def _documents(parquet: Path, *, limit: int | None, skip: int):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import (
        iter_uscode_records_from_parquet,
    )

    seen = 0
    produced = 0
    for record in iter_uscode_records_from_parquet(parquet, limit=None, batch_size=256):
        if not record.ipfs_cid or not record.text:
            continue
        seen += 1
        if seen <= skip:
            continue
        produced += 1
        if limit is not None and produced > limit:
            break
        yield {
            "entry_cid": record.ipfs_cid,
            "legal_id": f"usc:us:{record.title_number}:{record.section_number}",
            "release_id": "",
            "section": record.section_number,
            "text": record.text,
            "title": record.title_number,
            "canonical_citation": record.citation,
        }


def _parse_document(document: dict) -> list[dict]:
    """Split one section into spans. Does not open DuckDB."""

    from ipfs_datasets_py.logic.autoformal.uscode_ingest import inventory_uscode_documents

    ledger = inventory_uscode_documents(
        [document],
        query="ipfs_uscode",
        release_id=str(document.get("release_id") or ""),
    )
    return list(ledger.get("spans") or [])


def _flush_checkpoint(cache, destination: Path, *, upload: bool, agent_id: str) -> dict:
    """Write the resume checkpoint as parquet and, when asked, publish it."""

    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "resume-checkpoint.parquet"
    cache.register_agent(agent_id, dataset_id="justicedao/ipfs_uscode", role="compile")
    written = cache.write_resume_parquet(path)
    receipt = {
        "admitted": False,
        "formalized": False,
        "jsonl_written": False,
        "local_path": str(path),
        "task_count": written.get("task_count"),
        "uploaded": False,
    }
    if not upload:
        return receipt
    try:
        from huggingface_hub import HfApi

        repo_id = "justicedao/uscode-autoformal-span-cache"
        api = HfApi()
        api.create_repo(repo_id, repo_type="dataset", exist_ok=True)
        api.upload_file(
            path_or_fileobj=str(path),
            path_in_repo="autoformal/uscode/resume-checkpoint.parquet",
            repo_id=repo_id,
            repo_type="dataset",
            commit_message="autoformal uscode resume checkpoint",
        )
        receipt["uploaded"] = True
        receipt["repo_id"] = repo_id
    except Exception as exc:
        receipt["error"] = type(exc).__name__
        print(f"HF upload deferred error={type(exc).__name__}", flush=True)
    return receipt


def enqueue_corpus(
    cache,
    parquet: Path,
    *,
    limit: int | None,
    release_id: str,
    resume: bool,
    upload: bool,
    upload_dir: Path,
) -> dict:
    from concurrent.futures import ProcessPoolExecutor

    from ipfs_datasets_py.logic.autoformal.worker_budget import worker_budget

    skip = 0
    if resume:
        point = cache.checkpoint()
        if point["parquet"] in {"", str(parquet.resolve())}:
            skip = int(point["documents"] or 0)
    print(
        f"RESUME documents={skip} parquet={parquet} admitted=false formalized=false",
        flush=True,
    )
    documents = skip
    spans = 0
    batch: list[dict] = []
    pool_capacity = worker_budget()
    task_budget = pool_capacity
    pool = ProcessPoolExecutor(max_workers=pool_capacity)

    def _commit(rows: list[dict]) -> None:
        nonlocal spans, documents, task_budget
        if not rows:
            return
        task_budget = min(pool_capacity, worker_budget())
        parsed: list[dict] = []
        for offset in range(0, len(rows), task_budget):
            chunk = rows[offset : offset + task_budget]
            for spans_out in pool.map(_parse_document, chunk, chunksize=1):
                parsed.extend(spans_out)
        for row in rows:
            row["release_id"] = release_id
        spans += cache.enqueue(parsed)
        documents = skip + _commit.produced
        cache.save_checkpoint(documents=documents, parquet=str(parquet.resolve()))

    _commit.produced = 0
    try:
        for document in _documents(parquet, limit=limit, skip=skip):
            document["release_id"] = release_id
            batch.append(document)
            _commit.produced += 1
            if len(batch) < 64:
                continue
            _commit(batch)
            batch.clear()
            if documents % 512 == 0:
                print(
                    f"INGEST enqueue documents={documents} spans_new={spans} "
                    f"parse_workers={pool_capacity} parse_task_budget={task_budget} "
                    f"cache={cache.stats()}",
                    flush=True,
                )
                flushed = _flush_checkpoint(cache, upload_dir, upload=upload, agent_id="control-plane")
                print(
                    f"HF checkpoint documents={documents} uploaded={str(flushed.get('uploaded')).lower()} "
                    f"error={flushed.get('error') or 'none'}",
                    flush=True,
                )
        if batch:
            _commit(batch)
            print(
                f"INGEST enqueue documents={documents} spans_new={spans} "
                f"parse_workers={pool_capacity} parse_task_budget={task_budget} "
                f"cache={cache.stats()}",
                flush=True,
            )
    finally:
        pool.shutdown(wait=True, cancel_futures=False)
    return {
        "admitted": False,
        "documents": documents,
        "formalized": False,
        "resumed_from": skip,
        "spans_enqueued": spans,
    }


_WORKER: dict = {}


def _init_worker() -> None:
    """Load the compiler once per process. Workers never open DuckDB."""

    from ipfs_datasets_py.logic.autoformal import AutoformalSession

    _WORKER["session"] = AutoformalSession()
    _WORKER["n"] = 0


def _compile_claimed(item: dict) -> dict:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    _WORKER["n"] = int(_WORKER.get("n") or 0) + 1
    if _WORKER["n"] % 32 == 0 or "session" not in _WORKER:
        _WORKER["session"] = AutoformalSession()
    result = compile_span(_WORKER["session"], str(item.get("text") or ""), str(item.get("source_span_id") or ""))
    status = str(result.get("compiler_status") or result.get("status") or "")
    agrees = status in {"compiled", "roundtrip_ok"}
    rule = result.get("rule") if isinstance(result.get("rule"), dict) else {}
    return {
        "agrees": agrees,
        "decompiled": str(result.get("decompiled") or ""),
        "legal_id": str(item.get("legal_id") or ""),
        "reason": "" if agrees else str(result.get("reason") or "compiler_abstain"),
        "rule": rule,
        "source_span_id": str(item.get("source_span_id") or ""),
        "text": str(item.get("text") or ""),
    }


def drain(
    cache,
    *,
    batch: int,
    path_hashes: dict,
    code_identity: str,
    upload: bool,
    upload_dir: Path,
) -> dict:
    """Owner claims batches from DuckDB; worker processes only compile."""

    from concurrent.futures import ProcessPoolExecutor

    from ipfs_datasets_py.logic.autoformal.worker_budget import worker_budget

    totals = {"processed": 0, "sealed": 0, "gaps": 0, "workers": worker_budget()}
    started = time.monotonic()
    pool = ProcessPoolExecutor(max_workers=totals["workers"], initializer=_init_worker)
    print(
        f"CONTROL owner=duckdb workers={totals['workers']} "
        f"note=workers_do_not_open_the_catalog admitted=false formalized=false",
        flush=True,
    )
    try:
        while True:
            budget = worker_budget()
            if abs(budget - totals["workers"]) >= 2:
                pool.shutdown(wait=True, cancel_futures=False)
                totals["workers"] = budget
                pool = ProcessPoolExecutor(max_workers=budget, initializer=_init_worker)
                print(f"CONTROL scale workers={budget}", flush=True)
            claimed = cache.claim_batch("control-plane", limit=max(batch, budget))
            if not claimed:
                break
            ids = [item["source_span_id"] for item in claimed]
            try:
                results = list(pool.map(_compile_claimed, claimed, chunksize=4))
            except Exception:
                cache.release_claims(ids)
                raise
            receipt = cache.complete_claimed(
                results,
                code_identity=code_identity,
                path_hashes=path_hashes,
            )
            totals["processed"] += len(results)
            totals["sealed"] = int(receipt.get("sealed_total") or 0)
            totals["gaps"] = int(receipt.get("gap_total") or 0)
            stats = cache.stats()
            print(
                f"CENSUS workers={totals['workers']} processed={totals['processed']} "
                f"sealed={stats['sealed']} gaps={stats['gaps']} pending={stats['pending']} "
                f"terms={stats['terms']} elapsed_s={int(time.monotonic() - started)} "
                f"admitted=false formalized=false",
                flush=True,
            )
            if totals["processed"] % 256 == 0:
                flushed = _flush_checkpoint(cache, upload_dir, upload=upload, agent_id="control-plane")
                print(
                    f"HF checkpoint processed={totals['processed']} "
                    f"uploaded={str(flushed.get('uploaded')).lower()} "
                    f"error={flushed.get('error') or 'none'}",
                    flush=True,
                )
    finally:
        pool.shutdown(wait=True, cancel_futures=False)
    totals["admitted"] = False
    totals["formalized"] = False
    totals["jsonl_written"] = False
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch", type=int, default=128)
    parser.add_argument("--release-id", default="ipfs-uscode-5016b86a")
    parser.add_argument("--enqueue-only", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--upload", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--upload-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache, compiler_identity, compiler_path_hashes

    hashes = compiler_path_hashes(ROOT)
    identity = compiler_identity(hashes)
    cache = SpanCache(args.cache)
    upload_dir = args.upload_dir or (args.cache.parent / "hf-checkpoint")
    try:
        released = cache.release_stale_claims()
        if released:
            print(f"RESUME released_claims={released}", flush=True)
        enqueued = enqueue_corpus(
            cache,
            args.parquet,
            limit=args.limit,
            release_id=args.release_id,
            resume=args.resume,
            upload=args.upload,
            upload_dir=upload_dir,
        )
        print(f"INGEST enqueued {json.dumps(enqueued, sort_keys=True)}", flush=True)
        if args.enqueue_only:
            print(json.dumps({"stage": "enqueued", **enqueued, "stats": cache.stats()}, sort_keys=True), flush=True)
            return 0
        drained = drain(
            cache,
            batch=args.batch,
            path_hashes=hashes,
            code_identity=identity,
            upload=args.upload,
            upload_dir=upload_dir,
        )
        print(
            json.dumps(
                {"stage": "census_complete", "enqueued": enqueued, "drained": drained, "stats": cache.stats()},
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
