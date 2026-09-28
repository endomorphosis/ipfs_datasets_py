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
from typing import Any


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


def _checkpoint_agent_id(cache) -> str:
    """One stable id per cache so two machines do not publish over each other."""

    import socket

    meta = getattr(cache, "_meta", None)
    existing = meta("agent_id") if callable(meta) else ""
    if existing:
        return str(existing)
    host = socket.gethostname().split(".")[0]
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in host)[:32] or "machine"
    agent_id = "compile-" + safe
    setter = getattr(cache, "_set_meta", None)
    if callable(setter):
        setter("agent_id", agent_id)
    return agent_id


def _flush_checkpoint(cache, destination: Path, *, upload: bool, agent_id: str) -> dict:
    """Upload one sparse delta. A document tick or claim heartbeat is not uploaded."""

    import hashlib

    delta = cache.sparse_progress_delta()
    receipt = {
        "admitted": False,
        "delta_count": int(delta.get("delta_count") or 0),
        "formalized": False,
        "full_checkpoint_uploaded": False,
        "jsonl_written": False,
        "uploaded": False,
    }
    if not delta.get("rows"):
        receipt["skipped"] = "no_durable_change"
        return receipt
    fingerprints = dict(delta.get("fingerprints") or {})
    update_id = "sparse-" + hashlib.sha256(
        json.dumps(fingerprints, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    safe_agent = "".join(char if char.isalnum() or char in "-_" else "-" for char in agent_id)[:48]
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{safe_agent}-{update_id}.parquet"
    if path.name == "resume-checkpoint.parquet":
        raise ValueError("sparse checkpoint must not replace the full resume checkpoint")
    written = cache.write_sparse_progress_parquet(path, delta["rows"], agent_id=agent_id, update_id=update_id)
    receipt["local_path"] = written["path"]
    receipt["update_id"] = update_id
    if not upload:
        return receipt
    repo_path = f"autoformal/uscode/checkpoints/{safe_agent}/{update_id}.parquet"
    try:
        from huggingface_hub import HfApi

        repo_id = "justicedao/uscode-autoformal-span-cache"
        api = HfApi()
        api.create_repo(repo_id, repo_type="dataset", exist_ok=True)
        api.upload_file(
            path_or_fileobj=str(path),
            path_in_repo=repo_path,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"autoformal sparse checkpoint {update_id}",
        )
        cache.mark_progress_published(fingerprints)
        receipt["uploaded"] = True
        receipt["repo_id"] = repo_id
        receipt["path_in_repo"] = repo_path
    except Exception as exc:
        receipt["error"] = type(exc).__name__
        print(f"HF upload deferred error={type(exc).__name__}", flush=True)
    return receipt


def _poll_remote_checkpoint(cache, *, agent_id: str) -> dict:
    """Download other machines' sparse deltas. Do not pull the full checkpoint."""

    from huggingface_hub import HfApi, hf_hub_download

    repo_id = "justicedao/uscode-autoformal-span-cache"
    prefix = "autoformal/uscode/checkpoints/"
    own = prefix + "".join(char if char.isalnum() or char in "-_" else "-" for char in agent_id)[:48] + "/"
    try:
        api = HfApi()
        files = [
            path for path in api.list_repo_files(repo_id, repo_type="dataset")
            if path.startswith(prefix) and path.endswith(".parquet") and not path.startswith(own)
            and path.rsplit("/", 1)[-1] != "resume-checkpoint.parquet"
        ]
        applied = set(cache.applied_sparse_checkpoints())
        fresh = [path for path in files if path not in applied][:16]
        if not fresh:
            return {"admitted": False, "changed": False, "delta_count": 0, "formalized": False}
        merged_agents = 0
        for repo_path in fresh:
            local = hf_hub_download(repo_id, repo_path, repo_type="dataset")
            merged = cache.upsert_remote_resume(local, agent_id=agent_id)
            cache.remember_sparse_checkpoint(repo_path)
            merged_agents += int(merged.get("agents_imported") or 0)
        return {
            "admitted": False,
            "agents_imported": merged_agents,
            "changed": True,
            "delta_count": len(fresh),
            "formalized": False,
            "full_checkpoint_downloaded": False,
        }
    except Exception as exc:
        print(f"HF poll deferred error={type(exc).__name__}", flush=True)
        return {"changed": False, "error": type(exc).__name__, "admitted": False, "formalized": False}


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
    polled = _poll_remote_checkpoint(cache, agent_id=_checkpoint_agent_id(cache))
    print(
        f"HF poll changed={str(bool(polled.get('changed'))).lower()} "
        f"sealed={polled.get('sealed', 0)} gaps={polled.get('gaps', 0)} "
        f"claimed={polled.get('claimed', 0)} error={polled.get('error') or 'none'}",
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
                polled = _poll_remote_checkpoint(cache, agent_id=_checkpoint_agent_id(cache))
                print(
                    f"HF poll changed={str(bool(polled.get('changed'))).lower()} "
                    f"sealed={polled.get('sealed', 0)} gaps={polled.get('gaps', 0)} "
                    f"claimed={polled.get('claimed', 0)} error={polled.get('error') or 'none'}",
                    flush=True,
                )
                flushed = _flush_checkpoint(cache, upload_dir, upload=upload, agent_id=_checkpoint_agent_id(cache))
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
    """Load the compiler and the codec once per process. Workers never open DuckDB."""

    from ipfs_datasets_py.logic.autoformal import AutoformalSession

    _WORKER["session"] = AutoformalSession()
    _WORKER["n"] = 0


def _compile_claimed(item: dict) -> dict:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    from ipfs_datasets_py.logic.autoformal.repair_report import (
        codec_capture,
        formula_evidence,
        repair_report,
    )

    _WORKER["n"] = int(_WORKER.get("n") or 0) + 1
    if _WORKER["n"] % 32 == 0 or "session" not in _WORKER:
        _WORKER["session"] = AutoformalSession()
    text = str(item.get("text") or "")
    captured = codec_capture(text)
    result = compile_span(_WORKER["session"], str(captured.get("decoded_text") or text), str(item.get("source_span_id") or ""))
    status = str(result.get("compiler_status") or result.get("status") or "")
    agrees = status in {"compiled", "roundtrip_ok"}
    rule = result.get("rule") if isinstance(result.get("rule"), dict) else {}
    # Agreed spans still keep formulas so the consensus rate can count them.
    # The seal stores the compiler rule, not this capsule.
    if agrees:
        repair = {
            "admitted": False,
            "autoencoder": {
                "decoded_text": str(captured.get("decoded_text") or "")[:240],
                "formulas": formula_evidence(captured),
            },
            "citations": [str(cite) for cite in captured.get("citations") or [] if str(cite)][:8],
            "formalized": False,
        }
    else:
        repair = repair_report(compiler=result, autoencoder=captured)
    return {
        "agrees": agrees,
        "cosine_loss": captured.get("cosine_loss"),
        "cosine_similarity": captured.get("cosine_similarity"),
        "cross_entropy_loss": captured.get("cross_entropy_loss"),
        "decompiled": str(result.get("decompiled") or ""),
        "ir_compression_loss": captured.get("ir_compression_loss"),
        "legal_id": str(item.get("legal_id") or ""),
        "reason": "" if agrees else str(result.get("reason") or "compiler_abstain"),
        "reconstruction_loss": captured.get("reconstruction_loss"),
        "repair": repair,
        "rule": rule,
        "source_span_id": str(item.get("source_span_id") or ""),
        "text": text,
    }


def drain(
    cache,
    *,
    batch: int,
    path_hashes: dict,
    code_identity: str,
    upload: bool,
    upload_dir: Path,
    compile_workers: int = 0,
    gap_gateway: Any = None,
    cache_path: Path | None = None,
    supervisor_database: Path | None = None,
) -> dict:
    """Owner claims batches from DuckDB; worker processes only compile."""

    from concurrent.futures import ProcessPoolExecutor

    from ipfs_datasets_py.logic.autoformal.gap_compile_replay import FailureClassLedger
    from ipfs_datasets_py.logic.autoformal.worker_budget import worker_budget

    pinned = max(0, int(compile_workers))
    totals = {"processed": 0, "sealed": 0, "gaps": 0, "workers": pinned or worker_budget()}
    disagreement_ledger = FailureClassLedger()

    def _collect_disagreements(batch_rows: list[dict]) -> None:
        for item in batch_rows:
            census = dict(item.get("census") or {})
            if census.get("train"):
                totals["train_needed"] = True
            if census.get("agree") is True:
                continue
            decoded = str(((item.get("repair") or {}).get("autoencoder") or {}).get("decoded_text") or item.get("text") or "")
            if not decoded.strip():
                continue
            disagreement_ledger.observe(
                {
                    "compiled": False,
                    "compiler_reason": str(item.get("reason") or ""),
                    "legal_id": str(item.get("legal_id") or ""),
                    "output_text": decoded,
                    "repair": dict(item.get("repair") or {}),
                    "source_span_id": str(item.get("source_span_id") or ""),
                }
            )
    started = time.monotonic()
    pool = ProcessPoolExecutor(max_workers=totals["workers"], initializer=_init_worker)
    print(
        f"CONTROL owner=duckdb workers={totals['workers']} pinned={str(bool(pinned)).lower()} "
        f"note=workers_do_not_open_the_catalog admitted=false formalized=false",
        flush=True,
    )
    if gap_gateway is not None:
        gap_gateway.start()
        published = gap_gateway.publish(cache_path or Path("span-cache.duckdb"))
        print(
            f"CONTROL quack endpoint={published['endpoint']} "
            "transport=quack catalog_owner=span-cache "
            "ducklake_activation_held=true admitted=false formalized=false",
            flush=True,
        )
    try:
        while True:
            if gap_gateway is not None:
                gap_gateway.serve(cache)
            budget = pinned or worker_budget()
            if not pinned and abs(budget - totals["workers"]) >= 2:
                if gap_gateway is not None:
                    print(
                        "CONTROL quack keeps the compile pool stable while the owner serves gap reads",
                        flush=True,
                    )
                else:
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
            from ipfs_datasets_py.logic.autoformal.span_agreement import (
                annotate_compiled_batch,
                consensus_summary,
            )

            results = annotate_compiled_batch(results, lake_limit=4)
            consensus = consensus_summary(results)
            rate = consensus["agreement_rate"]
            print(
                "CONSENSUS "
                f"encoded={consensus['encoded']} agree={consensus['agree']} "
                f"disagree={consensus['disagree']} unscored={consensus['unscored']} "
                f"agreement_rate={'' if rate is None else f'{rate:.4f}'} "
                "admitted=false formalized=false",
                flush=True,
            )
            try:
                from ipfs_datasets_py.logic.autoformal.autoencoder_weight_store import record_consensus

                record_consensus(consensus)
            except Exception as exc:
                print(f"CONSENSUS store_error={type(exc).__name__}", flush=True)
            _collect_disagreements(results)
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
            if gap_gateway is not None:
                gap_gateway.serve(cache)
            if totals.get("train_needed") and totals["processed"] % 256 == 0 and not totals.get("canary_trained"):
                from ipfs_datasets_py.logic.autoformal.span_agreement import train_until_canary_improves

                try:
                    canary = train_until_canary_improves(rounds=1)
                except Exception as exc:
                    canary = {"trained": False, "error": type(exc).__name__, "admitted": False, "formalized": False}
                totals["canary_trained"] = True
                print(
                    f"CANARY trained={str(bool(canary.get('trained'))).lower()} "
                    f"improved={str(bool(canary.get('improved'))).lower()} "
                    f"before={canary.get('before')} after={canary.get('after')} "
                    f"admitted=false formalized=false error={canary.get('error') or 'none'}",
                    flush=True,
                )
            if supervisor_database is not None and totals["processed"] % 256 == 0 and disagreement_ledger.class_count():
                from ipfs_datasets_py.logic.autoformal.gap_compile_replay import upsert_failure_goals_through_quack

                try:
                    fed = upsert_failure_goals_through_quack(disagreement_ledger, supervisor_database)
                except Exception as exc:
                    fed = {"ingested": False, "error": type(exc).__name__}
                print(
                    f"GOAL classes={disagreement_ledger.class_count()} ingested={str(bool(fed.get('ingested'))).lower()} "
                    f"admitted=false formalized=false error={fed.get('error') or 'none'}",
                    flush=True,
                )
            if totals["processed"] % 256 == 0:
                polled = _poll_remote_checkpoint(cache, agent_id=_checkpoint_agent_id(cache))
                print(
                    f"HF poll changed={str(bool(polled.get('changed'))).lower()} "
                    f"sealed={polled.get('sealed', 0)} gaps={polled.get('gaps', 0)} "
                    f"claimed={polled.get('claimed', 0)} error={polled.get('error') or 'none'}",
                    flush=True,
                )
                flushed = _flush_checkpoint(cache, upload_dir, upload=upload, agent_id=_checkpoint_agent_id(cache))
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
    parser.add_argument("--compile-workers", type=int, default=0,
                        help="Pin compile processes. 0 keeps the load-and-memory budget.")
    parser.add_argument("--release-id", default="ipfs-uscode-5016b86a")
    parser.add_argument("--enqueue-only", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--upload", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--upload-dir", type=Path, default=None)
    parser.add_argument(
        "--quack-gaps",
        action="store_true",
        help="Serve gap reads on a loopback Quack endpoint. Does not open a second catalog owner.",
    )
    parser.add_argument(
        "--supervisor-database",
        type=Path,
        default=None,
        help="Accelerate supervisor DuckDB for disagreement goals. Not the span cache.",
    )
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
        gateway = None
        if args.quack_gaps:
            from ipfs_datasets_py.duckdb_control.span_cache_quack import SpanCacheQuackGateway

            gateway = SpanCacheQuackGateway()
        drained = drain(
            cache,
            batch=args.batch,
            path_hashes=hashes,
            code_identity=identity,
            upload=args.upload,
            upload_dir=upload_dir,
            compile_workers=args.compile_workers,
            gap_gateway=gateway,
            cache_path=args.cache,
            supervisor_database=args.supervisor_database,
        )
        print(
            json.dumps(
                {"stage": "census_complete", "enqueued": enqueued, "drained": drained, "stats": cache.stats()},
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        if "gateway" in locals() and gateway is not None:
            gateway.close()
        cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
