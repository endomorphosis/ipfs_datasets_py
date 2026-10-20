#!/usr/bin/env python3
"""Enqueue every justicedao/ipfs_uscode section and autoformalize pending spans.

Reads uscode_parquet/laws.parquet, splits each section into spans, and drains
the DuckDB span cache with the same compiler the supervisor loop uses. The
census between the autoencoder text and the compiler/decompiler, and the
repair goals that census opens, are appended to
justicedao/uscode-autoformal-span-cache. They are not appended to a local
supervisor queue. A compile is not a legal admit. JSONL is not written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
EXCHANGE_INPUT_BATCH_BYTES = 16 * 1024 * 1024
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


def _run_raw_coordinate_ingest(args) -> dict:
    """Replay pinned physical rows and publish one fresh local source catalog."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import (
        capture_uscode_source_documents_from_parquet,
    )
    from ipfs_datasets_py.logic.autoformal.uscode_ingest import (
        inventory_uscode_source_coordinates, uscode_source_coordinates_sha256,
        validate_uscode_source_coordinates,
    )
    from ipfs_datasets_py.logic.autoformal.span_cache import write_fresh_source_coordinate_cache

    captured = capture_uscode_source_documents_from_parquet(
        args.parquet, source_revision=args.source_revision,
        source_path_in_repo=args.source_path_in_repo,
        expected_sha256=args.expected_source_sha256,
        expected_bytes=args.expected_source_bytes, limit=args.limit,
        offset=args.source_row_offset, release_id=args.source_release_id)
    documents = captured["documents"]
    report = inventory_uscode_source_coordinates(
        documents, query="ipfs_uscode", release_id=args.source_release_id)
    report_pin = uscode_source_coordinates_sha256(report)
    validate_uscode_source_coordinates(report, documents,
        expected_report_sha256=report_pin, query="ipfs_uscode",
        release_id=args.source_release_id)
    written = write_fresh_source_coordinate_cache(args.cache, report, documents,
        expected_report_sha256=report_pin, query="ipfs_uscode",
        release_id=args.source_release_id)
    return {"stage": "raw_coordinates_enqueued", "profile": "raw-coordinates-v1",
            "source_file_sha256": captured["source_file_sha256"],
            "source_file_bytes": captured["source_file_bytes"],
            "source_revision": captured["source_revision"],
            "source_path_in_repo": captured["source_path_in_repo"],
            "source_release_id": args.source_release_id,
            "physical_row_offset": captured["physical_row_offset"],
            "documents": len(documents), "spans_enqueued": written["spans_enqueued"],
            "source_coordinates_report_sha256": report_pin, "stats": written["stats"],
            "fresh_catalog": True, "historical_backfill": False,
            "source_authority_authenticated": False, "legal_meaning_verified": False,
            "formalized": False, "admitted": False, "training_authorized": False,
            "parquet_file_byte_mapping_verified": False, "model_executed": False,
            "remote_io_performed": False}


def _checkpoint_agent_id(cache) -> str:
    """One stable id per cache so two machines do not publish over each other."""

    import socket
    import uuid

    meta = getattr(cache, "_meta", None)
    existing = meta("agent_id") if callable(meta) else ""
    instance_id = meta("checkpoint_instance_uuid") if callable(meta) else ""
    if existing and instance_id and str(existing).endswith("-" + str(instance_id)):
        return str(existing)
    host = socket.gethostname().split(".")[0]
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in host)[:7] or "machine"
    instance_id = instance_id or uuid.uuid4().hex
    agent_id = "compile-" + safe + "-" + instance_id
    setter = getattr(cache, "_set_meta", None)
    if callable(setter):
        if existing:
            setter("legacy_checkpoint_agent_id", str(existing))
        setter("checkpoint_instance_uuid", instance_id)
        setter("agent_id", agent_id)
    return agent_id


def _flush_checkpoint(cache, destination: Path, *, upload: bool, agent_id: str) -> dict:
    """Upload one sparse delta. A document tick or claim heartbeat is not uploaded."""

    import hashlib

    dataset_id = cache._meta("dataset_id")
    if dataset_id not in {"", "ipfs_uscode", "justicedao/ipfs_uscode"}:
        raise ValueError("checkpoint cache belongs to a different source dataset")
    cache.register_agent(agent_id, dataset_id="justicedao/ipfs_uscode", role="compile")
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
        json.dumps({"schema": "sparse-status/v2", "agent_id": agent_id,
                    "dataset_id": "justicedao/ipfs_uscode", "rows": delta["rows"]},
                   sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
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
        dataset_id = cache._meta("dataset_id")
        if dataset_id not in {"", "ipfs_uscode", "justicedao/ipfs_uscode"}:
            raise ValueError("checkpoint cache belongs to a different source dataset")
        cache.register_agent(agent_id, dataset_id="justicedao/ipfs_uscode", role="compile")
        api = HfApi()
        files = [
            path for path in api.list_repo_files(repo_id, repo_type="dataset")
            if path.startswith(prefix) and path.endswith(".parquet") and not path.startswith(own)
            and path.rsplit("/", 1)[-1] != "resume-checkpoint.parquet"
        ]
        fresh = cache.unapplied_sparse_checkpoints(files, limit=16)
        if not fresh:
            return {"admitted": False, "changed": False, "delta_count": 0, "formalized": False,
                    "advisory_only": True, "quarantined_count": cache.quarantined_sparse_checkpoint_count()}
        merged_agents = 0
        observations = []
        compatible = 0
        for repo_path in fresh:
            local = hf_hub_download(repo_id, repo_path, repo_type="dataset")
            merged = cache.upsert_remote_resume(local, agent_id=agent_id)
            observations.append({"path_in_repo": repo_path, **merged})
            if not merged.get("dataset_matched"):
                with open(local, "rb") as stream:
                    content_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
                cache.quarantine_sparse_checkpoint(
                    repo_path, expected_dataset_id="justicedao/ipfs_uscode", reason="dataset_mismatch",
                    evidence={"content_sha256": content_sha256,
                              "observed_dataset_ids": merged.get("observed_dataset_ids", []),
                              "admitted": False, "formalized": False},
                )
                continue
            compatible += 1
            cache.remember_sparse_checkpoint(repo_path)
            merged_agents += int(merged.get("agents_imported") or 0)
        return {
            "admitted": False,
            "advisory_only": True,
            "agents_imported": merged_agents,
            "changed": compatible > 0,
            "delta_count": compatible,
            "downloaded_count": len(fresh),
            "dataset_mismatch_count": len(fresh) - compatible,
            "quarantined_count": cache.quarantined_sparse_checkpoint_count(),
            "observations": observations,
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
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree

    require_workspace_logic_tree()
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
    captured = codec_capture(text, include_full_evidence=True)
    autoencoder_text = str(captured.get("decoded_text") or "")
    compiler_input = autoencoder_text or text
    result = compile_span(_WORKER["session"], compiler_input, str(item.get("source_span_id") or ""))
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
        "autoencoder_text": autoencoder_text,
        "autoencoder_capture": captured,
        "codec_kind": "DeterministicModalLogicCodec",
        "learned_autoencoder_execution": False,
        "model_identity": "deterministic-modal-codec:no-learned-checkpoint",
        "compiler_input": compiler_input,
        "compiler_input_mode": "decoded" if autoencoder_text else "source_fallback",
        "compiler_result": result,
        "compiler_status": status,
        "source_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source_provenance": {key: item[key] for key in (
            "entry_cid", "canonical_citation", "release_id", "source_provenance_json") if key in item},
        "source_provenance_status": "captured" if any(item.get(key) for key in (
            "entry_cid", "canonical_citation", "source_provenance_json")) else "not_retained_by_span_cache",
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


def _stage_exchange_batch(rows, destination: Path, *, agent_id: str, release_id: str,
                          code_identity: str, path_hashes: dict) -> dict:
    """Persist bounded immutable batches before the catalog marks work complete."""
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import publish_compiled_exchange

    totals = {"census_rows": 0, "goal_rows": 0, "manifests": []}
    def batches():
        batch, size = [], 0
        for row in rows:
            item = {**row, "compiler_path_hashes": dict(path_hashes),
                    "release_id": release_id, "code_identity": code_identity}
            item_size = len(json.dumps(item, ensure_ascii=True, sort_keys=True,
                                       separators=(",", ":"), allow_nan=False).encode())
            if item_size > EXCHANGE_INPUT_BATCH_BYTES:
                raise ValueError("one census capture exceeds the input byte bound")
            if batch and (len(batch) >= 64 or size + item_size > EXCHANGE_INPUT_BATCH_BYTES):
                yield batch
                batch, size = [], 0
            batch.append(item)
            size += item_size
        if batch:
            yield batch

    for batch in batches():
        receipt = publish_compiled_exchange(
            batch, destination, upload=False, agent_id=agent_id,
            release_id=release_id, code_identity=code_identity,
            model_identity="deterministic-modal-codec:no-learned-checkpoint",
        )
        manifest = receipt.get("manifest") or {}
        path = manifest.get("path") if isinstance(manifest, dict) else str(manifest)
        if receipt.get("error") or not path or not Path(path).is_file():
            raise RuntimeError("census/goal batch is not durably staged")
        totals["manifests"].append(path)
        totals["census_rows"] += int(receipt.get("census_rows") or 0)
        totals["goal_rows"] += int(receipt.get("goal_rows") or 0)
    return totals


def _retry_exchange_outbox(destination: Path, *, upload: bool) -> dict:
    """Upload retained manifests without reparsing spans or opening a supervisor."""
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import (
        pending_exchange_manifests, publish_exchange_manifest,
    )

    result = {"uploaded": 0, "failed": 0, "pending": 0}
    for manifest in pending_exchange_manifests(destination):
        result["pending"] += 1
        if not upload:
            continue
        try:
            receipt = publish_exchange_manifest(manifest, upload=True)
            if receipt.get("error"):
                raise RuntimeError(receipt["error"])
            result["uploaded"] += int(receipt.get("uploaded") is True)
        except Exception as exc:
            result["failed"] += 1
            print(f"GOAL upload deferred error={type(exc).__name__} manifest={Path(manifest).name}", flush=True)
    return result


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
    release_id: str = "ipfs-uscode-5016b86a",
) -> dict:
    """Owner claims batches from DuckDB; worker processes only compile.

    Census rows and supervisor goals are written to the span-cache dataset.
    ``supervisor_database`` is not opened.
    """

    from concurrent.futures import ProcessPoolExecutor

    from ipfs_datasets_py.logic.autoformal.worker_budget import worker_budget

    pinned = max(0, int(compile_workers))
    totals = {
        "processed": 0,
        "sealed": 0,
        "gaps": 0,
        "workers": pinned or worker_budget(),
        "goals_enqueued": False,
        "training_executed": False,
    }
    def _note_training(batch_rows: list[dict]) -> None:
        for item in batch_rows:
            census = dict(item.get("census") or {})
            if census.get("train"):
                totals["train_needed"] = True

    def _flush_exchange() -> None:
        flushed = _retry_exchange_outbox(upload_dir / "exchange", upload=upload)
        totals["exchange_upload_failures"] = int(flushed.get("failed") or 0)
        totals["exchange_uploads"] = int(totals.get("exchange_uploads") or 0) + int(flushed.get("uploaded") or 0)

    _flush_exchange()  # Retry durable earlier batches even when no spans remain pending.
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
            _note_training(results)
            try:
                staged = _stage_exchange_batch(
                    results, upload_dir / "exchange", agent_id=_checkpoint_agent_id(cache),
                    release_id=release_id, code_identity=code_identity, path_hashes=path_hashes,
                )
            except Exception:
                cache.release_claims(ids)
                raise
            totals["census_rows"] = int(totals.get("census_rows") or 0) + staged["census_rows"]
            totals["goal_rows"] = int(totals.get("goal_rows") or 0) + staged["goal_rows"]
            # Completion never outruns durable census/goal evidence. Upload can retry independently.
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
            if totals.get("train_needed"):
                totals["training_deferred_to_dataset"] = True
            if supervisor_database is not None and not totals.get("supervisor_notice"):
                totals["supervisor_notice"] = True
                print(
                    "GOAL supervisor_database is not the queue; "
                    "census and goals append to the span-cache dataset "
                    "enqueued=false admitted=false formalized=false",
                    flush=True,
                )
            _flush_exchange()
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
        try:
            _flush_exchange()
        finally:
            pool.shutdown(wait=True, cancel_futures=False)
    totals["admitted"] = False
    totals["formalized"] = False
    totals["goals_enqueued"] = False
    totals["jsonl_written"] = False
    totals["claim_profile"] = "legacy"
    totals["qualified"] = False
    return totals


def _fenced_compiler_preflight() -> tuple[dict, str]:
    """Fenced orchestration is executable only after canonical-tree deployment."""
    canonical = Path("/home/barberb/lift_coding/external/ipfs_datasets").resolve()
    if ROOT.resolve() != canonical:
        raise RuntimeError("fenced-v1 requires reviewed deployment under the canonical workspace tree")
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree, workspace_root
    from ipfs_datasets_py.logic.autoformal.span_cache import compiler_identity, compiler_path_hashes
    if workspace_root().resolve() != canonical:
        raise RuntimeError("fenced-v1 canonical root differs")
    origins = require_workspace_logic_tree()
    if any(not Path(path).resolve().is_relative_to(canonical) for path in origins.values()):
        raise RuntimeError("fenced-v1 compiler, decompiler or parser origin differs")
    hashes = compiler_path_hashes(canonical)
    return hashes, compiler_identity(hashes)


def _compile_claimed_fenced(item: dict) -> dict:
    # Preserve the existing actual compiler/census/Lake path and its criteria.
    from ipfs_datasets_py.logic.autoformal.span_agreement import annotate_compiled_batch
    return annotate_compiled_batch([_compile_claimed(item)], lake_limit=4)[0]


def _run_fenced_cli(args, *, runtime=None) -> dict:
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache, compiler_path_hashes
    from ipfs_datasets_py.logic.autoformal.span_cache_fenced_ingest import load_source_manifest, drain_fenced_manifest
    from ipfs_datasets_py.logic.autoformal.span_ingest_runtime import FencedIngestChildVerifier
    if not isinstance(runtime, FencedIngestChildVerifier):
        raise ValueError("fenced-v1 requires the real native-owned runtime launch barrier")
    runtime.verify()
    spec = runtime.spec
    if (args.cache != Path(spec["cache_path"]) or args.source_manifest != Path(spec["source_manifest_path"])
            or args.release_id != spec["release_id"] or args.upload_dir != Path(spec["attempt_directory"])
            or args.batch != spec["batch_size"] or args.fenced_span_limit != spec["max_spans"]
            or args.fenced_start_index != spec["start_index"] or args.fenced_scan_limit != spec["max_examined"]):
        raise ValueError("fenced CLI arguments differ from the exact native owner launch")
    if args.source_manifest is None:
        raise ValueError("fenced-v1 requires --source-manifest; no revision or source identity is inferred")
    if args.parquet is not None or args.limit is not None or args.upload or args.enqueue_only or args.quack_gaps or args.supervisor_database is not None or not args.resume:
        raise ValueError("fenced-v1 consumes an existing prepared cache; enqueue, upload, remote checkpoint import and supervisor dispatch remain separate reviewed operations")
    hashes, identity = _fenced_compiler_preflight()
    manifest, manifest_ref = load_source_manifest(args.source_manifest)
    if args.release_id != manifest["release_id"]:
        raise ValueError("CLI release ID differs from the explicit source manifest")
    if not args.cache.is_file() or args.cache.is_symlink():
        raise ValueError("fenced-v1 requires an existing regular owner-prepared cache file")
    workers = runtime.launch["workers"]
    if args.compile_workers != workers:
        raise ValueError("compiler workers differ from the native admitted envelope")
    destination = (args.upload_dir or args.cache.parent / "hf-checkpoint") / "exchange"
    cache = SpanCache(args.cache)
    try:
        runtime.configure_cache(cache)
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                 mp_context=multiprocessing.get_context("spawn")) as pool:
            def stage(rows):
                return _stage_exchange_batch(rows, destination, agent_id="fenced-control-plane",
                    release_id=manifest["release_id"], code_identity=identity, path_hashes=hashes)
            def guarded_sources():
                runtime.verify()
                return compiler_path_hashes(ROOT)
            report = drain_fenced_manifest(cache, manifest, worker_pool=pool,
                compile_worker=_compile_claimed_fenced, stage_exchange=stage, exchange_dir=destination,
                code_identity=identity, path_hashes=hashes,
                source_guard=guarded_sources, batch_size=args.batch,
                max_spans=args.fenced_span_limit, start_index=args.fenced_start_index,
                max_examined=args.fenced_scan_limit,
                historical_evidence_roots=[root["path"] for root in runtime.launch["roots"]])
            runtime.verify()
            return {**report, "source_manifest": manifest_ref, "compile_workers": workers,
                    "compiler_tree": str(ROOT), "resource_admission_verified_by_cli": True,
                    "model_executed": False, "kernel_quota_enforced": False,
                    "process_ceiling_verified": False, "constructor_spill_redirect_guaranteed": False,
                    "native_reservation_id": runtime.launch["reservation_id"],
                    "production_state": "selected_native_owned_fenced_cli_not_semantically_qualified"}
    finally:
        cache.close()


def main(argv: list[str] | None = None, *, fenced_runtime=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, help="Required for the legacy source-enqueue path.")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--claim-profile", choices=("legacy", "fenced-v1"), default="legacy",
                        help="Explicit fenced source-manifest profile; legacy helpers remain unqualified.")
    parser.add_argument("--source-ingest-profile", choices=("legacy", "raw-coordinates-v1"),
                        default="legacy", help="Opt-in pinned physical rows into a NEW coordinate-aware catalog.")
    parser.add_argument("--source-revision", help="Raw profile: independent lowercase 40-hex repository commit.")
    parser.add_argument("--source-path-in-repo", help="Raw profile: canonical relative Parquet repository path.")
    parser.add_argument("--expected-source-sha256", help="Raw profile: independent exact local Parquet SHA256.")
    parser.add_argument("--expected-source-bytes", type=int)
    parser.add_argument("--source-release-id", help="Raw profile: explicit source release identity; never inferred from text.")
    parser.add_argument("--source-row-offset", type=int, default=0,
                        help="Raw profile: zero-based physical row ordinal (not legacy valid-document skip).")
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--fenced-span-limit", type=int, default=32,
                        help="Maximum selected fenced spans per invocation (1..4096).")
    parser.add_argument("--fenced-start-index", type=int, default=0,
                        help="Explicit position in this exact source manifest; start at returned next_manifest_index.")
    parser.add_argument("--fenced-scan-limit", type=int, default=256,
                        help="Maximum examined fenced manifest rows per invocation (1..4096).")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch", type=int, default=None)
    parser.add_argument("--compile-workers", type=int, default=0,
                        help="Legacy: 0 uses the load-and-memory budget. Fenced workers are fixed by the native-owned runtime.")
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
        help="Ignored. Census and goals append to the span-cache dataset, not a local supervisor.",
    )
    args = parser.parse_args(argv)
    if args.source_ingest_profile == "raw-coordinates-v1":
        if (args.claim_profile != "legacy" or fenced_runtime is not None
                or args.source_manifest is not None):
            parser.error("raw-coordinates-v1 is a separate source-enqueue profile, not a fenced runtime")
        if (args.parquet is None or args.limit is None or not 1 <= args.limit <= 128
                or not all((args.source_revision, args.source_path_in_repo,
                            args.expected_source_sha256, args.expected_source_bytes,
                            args.source_release_id))):
            parser.error("raw-coordinates-v1 requires --parquet, --limit 1..128, all source pins and --source-release-id")
        if (not args.enqueue_only or args.resume or args.upload or args.upload_dir is not None
                or args.quack_gaps or args.supervisor_database is not None
                or args.batch is not None or args.compile_workers != 0
                or args.release_id != "ipfs-uscode-5016b86a"):
            parser.error("raw-coordinates-v1 requires --enqueue-only --no-resume; compiler, upload and legacy-release options are incompatible")
        report = _run_raw_coordinate_ingest(args)
        print(json.dumps(report, sort_keys=True), flush=True)
        return 0
    if (any(value is not None for value in (args.source_revision, args.source_path_in_repo,
            args.expected_source_sha256, args.expected_source_bytes, args.source_release_id))
            or args.source_row_offset != 0):
        parser.error("raw source pins and physical offsets require --source-ingest-profile raw-coordinates-v1")
    if args.batch is None:
        args.batch = 16 if args.claim_profile == "fenced-v1" else 128
    if args.claim_profile == "fenced-v1":
        report = _run_fenced_cli(args, runtime=fenced_runtime)
        if fenced_runtime is not None:
            from ipfs_datasets_py.logic.autoformal.span_ingest_runtime import stage_child_report
            transport = stage_child_report(report, fenced_runtime.spec, fenced_runtime.launch["reservation_id"])
        else:
            transport = report
        print(json.dumps({"stage": "fenced_census_complete", **transport}, sort_keys=True), flush=True)
        return 0 if not report["held"] else 2
    if fenced_runtime is not None:
        parser.error("native fenced runtime cannot activate the legacy profile")
    if args.parquet is None:
        parser.error("--parquet is required for the legacy profile")
    if args.source_manifest is not None:
        parser.error("--source-manifest requires --claim-profile fenced-v1")
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
            release_id=args.release_id,
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
