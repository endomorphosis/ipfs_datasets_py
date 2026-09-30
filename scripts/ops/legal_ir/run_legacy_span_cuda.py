#!/usr/bin/env python3
"""Resume legacy CUDA diagnostics and independent US Code compilation.

The owner has no campaign-wide deadline. A single resident CUDA model and a
CPU compiler pool read verified source text; only the engine writes its DuckDB.
No training, checkpoint replacement, learned formula claims or Lake admissions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import fcntl
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[3]
RUNNER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
sys.path.insert(0, str(ROOT))
REPOSITORY = "justicedao/uscode-autoformal-span-cache"
PROGRESS = "autoformal/uscode/resume-checkpoint.parquet"
SOURCE_SHA = "4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8"
LEGACY = "/home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/todo-queues/legal-ir-autoencoder-canonical.state.json"
SOURCE = "/home/barberb/.cache/huggingface/hub/datasets--justicedao--ipfs_uscode/snapshots/5016b86a273ce5e4ffd066c5ae9f5fe494dd417e/uscode_parquet/laws.parquet"
LEDGER = ROOT / "workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json"
STOP = False
GPU = None
DEVICE = None
ALLOCATOR_ADMISSION = None


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic(path, value):
    path = Path(path)
    raw = encode(value)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def event(kind, **values):
    print(json.dumps({"event": kind, "at": time.time(), **values}, sort_keys=True), flush=True)


def environment():
    os.environ.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
        IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0", IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE="0",
        IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS="0", IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS="1",
        HF_HUB_DISABLE_PROGRESS_BARS="1",
        TRANSFORMERS_OFFLINE="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
    # Dataset metadata and result delivery are online; no model resolver runs.
    # Hub defaults to TRANSFORMERS_OFFLINE when this is absent. Keep datasets
    # online explicitly while the model resolver remains offline.
    os.environ["HF_HUB_OFFLINE"] = "0"


def stop(signum, frame):
    global STOP
    STOP = True


def _cpu_init():
    environment()
    os.environ["CUDA_VISIBLE_DEVICES"] = ""


def _gpu_init(checkpoint, runtime, batch_size, bridge_workers):
    global GPU, DEVICE, ALLOCATOR_ADMISSION
    environment()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_campaign_resources import CudaDeviceBudget, admit_cuda_device
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_cuda import LegacySpanCUDAWorker
    DEVICE = CudaDeviceBudget(runtime)
    DEVICE.__enter__()
    ALLOCATOR_ADMISSION = admit_cuda_device()
    GPU = LegacySpanCUDAWorker(checkpoint, mode="legacy_mock_diagnostic", max_batch_size=batch_size,
                               legal_ir_parallel_workers=bridge_workers)


def _gpu_ready():
    return {"pid": os.getpid(), "source": GPU.source_identity, "cuda": DEVICE.check(),
            "allocator_admission": ALLOCATOR_ADMISSION}


def _gpu_evaluate(rows, compiled):
    DEVICE.check()
    result = GPU.evaluate_batch(rows, compiler_results=compiled)
    result["device_budget"] = DEVICE.check()
    result["cuda_allocator_admission"] = ALLOCATOR_ADMISSION
    return result


def _compile(row, source_sha):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_cuda import compile_source_span
    return compile_source_span(row, expected_source_sha256=source_sha)


def remote_progress():
    base = "https://huggingface.co/api/datasets/" + REPOSITORY
    def get(url):
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("bounded Hub metadata exceeded")
        return json.loads(raw)
    revision = get(base)["sha"]
    if len(revision) != 40 or any(x not in "0123456789abcdef" for x in revision):
        raise ValueError("invalid Hub revision")
    entries = get(base + "/tree/" + revision + "/autoformal/uscode?limit=100")
    entry = next(row for row in entries if row["path"] == PROGRESS)
    sha = entry["lfs"]["oid"]
    if len(sha) != 64 or any(x not in "0123456789abcdef" for x in sha):
        raise ValueError("invalid progress digest")
    size = entry["size"]
    if type(size) is not int or not 0 < size <= 128 * 1024 * 1024:
        raise ValueError("progress artifact exceeds bound")
    return {"repository": REPOSITORY, "revision": revision, "path": PROGRESS,
            "sha256": sha, "bytes": size}


def download_progress(runtime, descriptor):
    path = runtime / "inputs" / (descriptor["sha256"] + ".parquet")
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        if path.stat().st_size != descriptor["bytes"] or digest_file(path) != descriptor["sha256"]:
            raise ValueError("retained progress artifact changed")
        return path
    temporary = path.with_suffix(".partial")
    url = "https://huggingface.co/datasets/" + REPOSITORY + "/resolve/" + descriptor["revision"] + "/" + PROGRESS
    count = 0
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as stream:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            count += len(block)
            if count > descriptor["bytes"]:
                raise ValueError("progress download exceeds declared bytes")
            stream.write(block)
            h.update(block)
        stream.flush()
        os.fsync(stream.fileno())
    if count != descriptor["bytes"] or h.hexdigest() != descriptor["sha256"]:
        raise ValueError("progress download identity mismatch")
    os.replace(temporary, path)
    return path


def open_queue(path):
    import duckdb
    db = duckdb.connect(str(path))
    db.execute("SET threads=1")
    db.execute("SET memory_limit='1GiB'")
    db.execute("SET max_temp_directory_size='128MiB'")
    db.execute("SET temp_directory = ?", [str(Path(path).parent / "duckdb-temp")])
    db.execute("CREATE TABLE IF NOT EXISTS meta (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)")
    db.execute("""CREATE TABLE IF NOT EXISTS work (
        id VARCHAR PRIMARY KEY, payload VARCHAR NOT NULL, status VARCHAR NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, batch_id VARCHAR, error VARCHAR)""")
    db.execute("""CREATE TABLE IF NOT EXISTS batches (
        id VARCHAR PRIMARY KEY, ids VARCHAR NOT NULL, status VARCHAR NOT NULL,
        manifest VARCHAR, publication VARCHAR, receipt_sha256 VARCHAR)""")
    return db


def meta(db, key, value=None):
    if value is not None:
        db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", [key, json.dumps(value)])
        return value
    row = db.execute("SELECT value FROM meta WHERE key=?", [key]).fetchone()
    return json.loads(row[0]) if row else None


def enqueue(db, batch):
    db.execute("BEGIN")
    try:
        for row in batch["rows"]:
            if hashlib.sha256(row["text"].encode()).hexdigest() != row["source_sha256"]:
                raise ValueError("source identity conflict: text digest")
            identity = hashlib.sha256(encode([row["source_span_id"], row["source_sha256"]])).hexdigest()
            old = db.execute("SELECT payload FROM work WHERE id=?", [identity]).fetchone()
            if old:
                original = json.loads(old[0])
                keys = ("source_span_id", "source_sha256", "legal_id") if original.get("payload_evicted") else ("source_span_id", "source_sha256", "text", "legal_id")
                if any(original[k] != row[k] for k in keys):
                    raise ValueError("source identity conflict")
            else:
                unsupported = len(row["text"]) > 16000 or any(len(row[k]) > 1024 for k in ("source_span_id", "legal_id"))
                db.execute("INSERT INTO work VALUES (?,?,?,0,NULL,?)", [identity, encode(row).decode(),
                    "deferred_input_bounds" if unsupported else "pending",
                    "input exceeds diagnostic worker bound; source retained without truncation" if unsupported else None])
        meta(db, "section_cursor", batch["next_section"])
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def select_batch(db, count):
    rows = db.execute("SELECT id,payload FROM work WHERE status='pending' ORDER BY attempts DESC,id LIMIT ?", [count]).fetchall()
    if not rows:
        return None
    bounded, size = [], 0
    for row in rows:
        size += len(json.loads(row[1])["text"].encode())
        if size > 1024 * 1024:
            break
        bounded.append(row)
    rows = bounded
    batch_id = uuid.uuid4().hex
    ids = [r[0] for r in rows]
    db.execute("BEGIN")
    try:
        db.execute("INSERT INTO batches VALUES (?,?,'running',NULL,NULL,NULL)", [batch_id, json.dumps(ids)])
        db.executemany("UPDATE work SET status='running', attempts=attempts+1,batch_id=? WHERE id=?", [(batch_id, x) for x in ids])
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return batch_id, [json.loads(r[1]) for r in rows]


def exchange_rows(receipt):
    """Preserve measured features without fabricating autoencoder text."""
    observations = []
    shared = {k: v for k, v in receipt.items() if k not in {"rows", "raw_evaluation"}}
    sample_ids = {row.get("sample_id") for row in receipt["rows"]} - {None}
    sample_maps = {k: v for k, v in receipt["raw_evaluation"].items()
                   if isinstance(v, dict) and v and set(v).issubset(sample_ids)}
    for index, row in enumerate(receipt["rows"]):
        compiler = row["compiler"]
        observations.append({"source_span_id": row["source_span_id"], "text": row["text"],
            "legal_id": row["legal_id"], "compiler_result": compiler,
            "decompiled": compiler.get("decompiled", ""),
            "strict_compiler_agreement": bool(compiler.get("roundtrip") is True),
            "reason": compiler.get("reason") or compiler.get("error_code") or "",
            "autoencoder_text": "", "learned_autoencoder_execution": row.get("status") == "diagnostic_observed" and isinstance(row.get("raw_decoder"), dict),
            "learned_formula_generation": False, "autoencoder_observation": row,
            "batch_observation": shared,
            "raw_sample_evaluation": {k: v[row["sample_id"]] for k, v in sample_maps.items()
                if row.get("sample_id") in v},
            "raw_batch_metrics": {k: v for k, v in receipt["raw_evaluation"].items()
                if not isinstance(v, (dict, list))},
            "metric_scope": "legacy_mock_embedding_diagnostic_not_semantic_or_heldout",
            "comparison": {"agrees": False, "reason": "inference_still_failing",
                "capture": {"replicated": False, "learned_text_unavailable": True}},
            "comparison_provenance": {"kind": "legacy_cuda_observation", "producer_source": receipt["producer_source"]},
            # Numeric legacy-vector scores stay nested; text metrics are missing.
            "cosine_similarity": None, "cross_entropy_loss": None, "reconstruction_loss": None,
            "admitted": False, "formalized": False})
        if index == 0:
            observations[-1]["raw_batch_summary"] = {k: v for k, v in receipt["raw_evaluation"].items() if k not in sample_maps}
    return observations


def validate_receipt(db, batch_id, receipt):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_cuda import LEGACY_SHA256
    if (receipt.get("schema_version") != "legacy-span-cuda-diagnostic/v1"
            or receipt.get("mode") != "legacy_mock_diagnostic"
            or receipt.get("checkpoint", {}).get("sha256") != LEGACY_SHA256
            or receipt.get("campaign", {}).get("batch_id") != batch_id
            or any(receipt.get(k) is not False for k in ("admitted", "formalized", "semantic_qualified", "training_executed"))):
        raise ValueError("receipt identity or authority mismatch")
    expected = [json.loads(r[0]) for r in db.execute("SELECT payload FROM work WHERE batch_id=?", [batch_id]).fetchall()]
    actual = receipt.get("rows", [])
    if not expected or len(actual) != len(expected):
        raise ValueError("receipt source count mismatch")
    indexed = {r["source_span_id"]: r for r in expected}
    if len(indexed) != len(actual) or set(indexed) != {r["source_span_id"] for r in actual}:
        raise ValueError("receipt source identity mismatch")
    for row in actual:
        source = indexed[row["source_span_id"]]
        if any(row.get(k) != source[k] for k in ("text", "source_sha256", "legal_id")):
            raise ValueError("receipt source identity mismatch")
        if any(row.get(k) is not False for k in ("admitted", "formalized", "semantic_qualified", "learned_formula_generation")):
            raise ValueError("receipt source authority mismatch")


def stage(db, runtime, batch_id, receipt, agent):
    validate_receipt(db, batch_id, receipt)
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import publish_compiled_exchange
    path = runtime / "receipts" / (batch_id + ".json")
    atomic(path, receipt)
    staged = publish_compiled_exchange(exchange_rows(receipt), runtime / "outbox", upload=False,
        agent_id=agent, release_id="ipfs-uscode-5016b86a",
        code_identity="sha256:" + receipt["producer_source"]["sha256"],
        model_identity="legacy-mock-diagnostic:sha256:" + receipt["checkpoint"]["sha256"])
    db.execute("BEGIN")
    try:
        db.execute("UPDATE batches SET status='staged',manifest=?,receipt_sha256=? WHERE id=?",
                   [staged["manifest"]["path"], digest_file(path), batch_id])
        db.execute("UPDATE work SET status='done',error=NULL WHERE batch_id=?", [batch_id])
        meta(db, "last_batch_metrics", {
            "batch_id": batch_id, "sample_count": receipt["sample_count"],
            "bridges": receipt.get("bridges"), "cuda": receipt.get("cuda"),
            "timings": receipt.get("timings"), "campaign": receipt.get("campaign"),
            "compiler_roundtrip_count": sum(row["compiler"].get("roundtrip") is True for row in receipt["rows"]),
            "compiler_reason_counts": dict(Counter(str(row["compiler"].get("reason") or "") for row in receipt["rows"])),
            "legal_ir_losses": receipt["raw_evaluation"].get("legal_ir_losses"),
            "admitted": False, "formalized": False})
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return staged


def recover(db, runtime, agent):
    for batch_id, in db.execute("SELECT id FROM batches WHERE status='running'").fetchall():
        path = runtime / "receipts" / (batch_id + ".json")
        if path.exists():
            receipt = json.loads(path.read_bytes())
            validate_receipt(db, batch_id, receipt)
            stage(db, runtime, batch_id, receipt, agent)
        else:
            db.execute("UPDATE work SET status='pending',batch_id=NULL,error='interrupted_before_durable_receipt' WHERE batch_id=?", [batch_id])
            db.execute("UPDATE batches SET status='interrupted' WHERE id=?", [batch_id])


def publish_pending(db, upload, runtime=None):
    if not upload:
        return
    if (meta(db, "publication_retry_after") or 0) > time.time():
        return
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import publish_exchange_manifest
    from huggingface_hub import HfApi
    class ObservedHubAPI:
        def __init__(self):
            self.api = HfApi()
        def __getattr__(self, name):
            method = getattr(self.api, name)
            def invoke(*args, **kwargs):
                try:
                    return method(*args, **kwargs)
                except Exception as error:
                    response = getattr(error, "response", None)
                    retry_seconds = None
                    if getattr(response, "status_code", None) == 429:
                        retry = response.headers.get("Retry-After", "300")
                        retry_seconds = max(60, min(3600, int(retry))) if str(retry).isdigit() else 300
                        meta(db, "publication_retry_after", time.time() + retry_seconds)
                    # Never log URLs, credentials or request bodies.
                    event("hub_request_failed", operation=name, error=type(error).__name__,
                          http_status=getattr(response, "status_code", None), retry_seconds=retry_seconds)
                    raise
            return invoke
    api = ObservedHubAPI()
    for batch_id, path in db.execute("SELECT id,manifest FROM batches WHERE status='staged' LIMIT 2").fetchall():
        try:
            receipt = publish_exchange_manifest(path, upload=True, api=api)
        except Exception as error:
            event("publication_deferred", batch_id=batch_id, error=type(error).__name__)
            break
        if receipt.get("uploaded"):
            db.execute("UPDATE batches SET status='published',publication=? WHERE id=?", [encode(receipt).decode(), batch_id])
            event("published", batch_id=batch_id, commit=receipt.get("commit_sha"))
        else:
            event("publication_deferred", batch_id=batch_id, error=receipt.get("error"))
            break
    if runtime is not None and (meta(db, "publication_retry_after") or 0) <= time.time():
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_publication import cleanup_published_batches
        try:
            for cleanup in cleanup_published_batches(db, runtime, api=api):
                batch_id = cleanup["batch_id"]
                event("verified_publication_cleanup", batch_id=batch_id, deleted_bytes=cleanup["deleted_bytes"],
                      commit=cleanup["remote"]["commit_sha"])
            compact_published_payloads(db)
        except Exception as error:
            event("publication_cleanup_deferred", error=type(error).__name__, detail=str(error)[:200])


def compact_published_payloads(db):
    """Retry payload compaction even after a crash following artifact eviction."""
    rows = db.execute("""SELECT w.id,w.payload FROM work w
        JOIN batches b ON b.id=w.batch_id
        JOIN legacy_span_evictions e ON e.batch_id=b.id
        WHERE w.status='done' AND b.status='published' AND e.status='evicted'
        AND coalesce(json_extract_string(w.payload,'$.payload_evicted'),'false')<>'true'
        LIMIT 2048""").fetchall()
    for work_id, payload in rows:
        original = json.loads(payload)
        identity = {k: original[k] for k in ("source_span_id", "source_sha256", "legal_id")}
        identity["payload_evicted"] = True
        db.execute("UPDATE work SET payload=? WHERE id=?", [encode(identity).decode(), work_id])


def status(db, runtime, **extra):
    value = {"schema": "legacy-span-cuda-campaign-status/v1", "updated_at": time.time(),
        "pid": os.getpid(), "overall_timeout_seconds": None, "training_executed": False,
        "diagnostic_representation": "mock:stable-sha256/8", "admitted": False, "formalized": False,
        "work": dict(db.execute("SELECT status,count(*) FROM work GROUP BY status").fetchall()),
        "batches": dict(db.execute("SELECT status,count(*) FROM batches GROUP BY status").fetchall()), **extra}
    value["publication_retry_after"] = meta(db, "publication_retry_after")
    value["last_batch_metrics"] = meta(db, "last_batch_metrics")
    atomic(runtime / "status.json", value)
    return value


def sleep_until_poll(seconds):
    for _ in range(seconds):
        if STOP:
            return
        time.sleep(1)


def storage_backpressure(runtime, limit):
    used = sum(path.stat().st_size for path in runtime.rglob("*") if path.is_file())
    return used > limit * 0.75


def stop_child(child):
    """Bound shutdown cleanup only; productive work has no deadline."""
    if child.poll() is not None:
        return
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()


def engine(args):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_intake import (
        prepare_progress_index, iter_joined_section_batches, progress_coverage)
    runtime = args.runtime_directory
    for name in ("receipts", "outbox", "inputs"):
        (runtime / name).mkdir(exist_ok=True)
    db = open_queue(runtime / "campaign.duckdb")
    identity = {"schema": "legacy-span-cuda-campaign/v1", "checkpoint": str(args.checkpoint.resolve()),
        "source_sha256": SOURCE_SHA, "diagnostic_mode": "legacy_mock_diagnostic", "agent": args.agent_id}
    old = meta(db, "identity")
    if old is not None and old != identity:
        raise ValueError("campaign identity changed; choose a new runtime directory")
    meta(db, "identity", identity)
    status(db, runtime, phase="loading_verified_inputs_and_cuda_model")
    recover(db, runtime, args.agent_id)
    if args.publish_only:
        try:
            if not args.upload:
                raise ValueError("--publish-only requires --upload")
            while db.execute("SELECT count(*) FROM batches WHERE status='staged'").fetchone()[0]:
                before = db.execute("SELECT count(*) FROM batches WHERE status='staged'").fetchone()[0]
                publish_pending(db, True, runtime)
                after = db.execute("SELECT count(*) FROM batches WHERE status='staged'").fetchone()[0]
                if after == before:
                    return 1
            publish_pending(db, True, runtime)
            status(db, runtime, phase="publication_completed")
            return 0
        finally:
            db.execute("CHECKPOINT")
            db.close()
    reconstruction = "historical-64-document-ordinal/v1"
    if meta(db, "intake_reconstruction") != reconstruction:
        # Older intake reset identity ordinals per section. Replay preserves
        # already completed identities and recovers previously missed matches.
        db.execute("BEGIN")
        try:
            meta(db, "section_cursor", 0)
            meta(db, "intake_reconstruction", reconstruction)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    descriptor = meta(db, "progress")
    if descriptor is None:
        descriptor = remote_progress()
        meta(db, "progress", descriptor)
    progress = download_progress(runtime, descriptor)
    index = prepare_progress_index(db, progress, expected_sha256=descriptor["sha256"], repository_revision=descriptor["revision"])
    cursor = meta(db, "section_cursor") or 0
    iterator = iter_joined_section_batches(index, args.source_parquet,
        expected_laws_sha256=SOURCE_SHA, start_section=cursor, section_batch_size=16,
        max_row_group_bytes=2 * 1024**3, max_batch_spans=32768, max_batch_bytes=64 * 1024**2)
    exhausted = False
    completed = 0
    context = multiprocessing.get_context("spawn")
    try:
        with ProcessPoolExecutor(1, mp_context=context, initializer=_gpu_init,
                initargs=(str(args.checkpoint), str(runtime), args.batch_size, args.bridge_workers)) as gpu, \
             ProcessPoolExecutor(args.compiler_workers, mp_context=context, initializer=_cpu_init) as cpu:
            ready = gpu.submit(_gpu_ready).result()
            atomic(runtime / "cuda-ready.json", ready)
            event("cuda_ready", **ready)
            def take_work():
                nonlocal exhausted
                if storage_backpressure(runtime, args.storage_bytes):
                    status(db, runtime, phase="waiting_for_verified_publication_storage")
                    return None
                while not STOP and not exhausted and db.execute("SELECT count(*) FROM work WHERE status='pending'").fetchone()[0] < args.batch_size:
                    if storage_backpressure(runtime, args.storage_bytes):
                        return None
                    try:
                        batch = next(iterator)
                    except StopIteration:
                        exhausted = True
                        atomic(runtime / "intake-coverage.json", progress_coverage(index))
                        break
                    enqueue(db, batch)
                    status(db, runtime, phase="hydrating", section_cursor=batch["next_section"], intake_counts=batch["counts"])
                if STOP:
                    return None
                selected = select_batch(db, args.batch_size)
                if selected is None:
                    return None
                batch_id, rows = selected
                started = time.monotonic()
                futures = [cpu.submit(_compile, row, ready["source"]["sha256"]) for row in rows]
                return batch_id, rows, futures, started

            pending = None
            while not STOP and (args.max_batches == 0 or completed < args.max_batches):
                publish_pending(db, args.upload, runtime)
                if pending is None:
                    pending = take_work()
                if pending is None:
                    pressure = storage_backpressure(runtime, args.storage_bytes)
                    status(db, runtime, phase="waiting_for_verified_publication_storage" if pressure else "waiting_for_source_updates", section_cursor=meta(db, "section_cursor"))
                    if args.max_batches:
                        break
                    sleep_until_poll(args.poll_seconds)
                    if STOP:
                        break
                    if pressure:
                        continue
                    try:
                        latest = remote_progress()
                        if latest["sha256"] != descriptor["sha256"]:
                            progress = download_progress(runtime, latest)
                            fresh_index = prepare_progress_index(db, progress, expected_sha256=latest["sha256"], repository_revision=latest["revision"])
                            db.execute('DROP TABLE "' + index.table + '"')
                            index, descriptor = fresh_index, latest
                            meta(db, "progress", descriptor)
                            meta(db, "section_cursor", 0)
                            iterator = iter_joined_section_batches(index, args.source_parquet, expected_laws_sha256=SOURCE_SHA,
                                section_batch_size=16, max_row_group_bytes=2 * 1024**3,
                                max_batch_spans=32768, max_batch_bytes=64 * 1024**2)
                            exhausted = False
                            for old_input in (runtime / "inputs").glob("*.parquet"):
                                if old_input != progress:
                                    old_input.unlink()
                    except Exception as error:
                        event("source_poll_deferred", error=type(error).__name__)
                    continue
                batch_id, rows, futures, started = pending
                status(db, runtime, phase="compiling", batch_id=batch_id, compiler_workers=args.compiler_workers)
                compiled = {row["source_span_id"]: future.result() for row, future in zip(rows, futures)}
                gpu_future = gpu.submit(_gpu_evaluate, rows, compiled)
                # A bounded second batch compiles while the first uses CUDA.
                pending = take_work() if args.max_batches == 0 or completed + 1 < args.max_batches else None
                status(db, runtime, phase="cuda_evaluation_and_cpu_prefetch", batch_id=batch_id,
                       prefetched_batch=pending[0] if pending else None)
                receipt = gpu_future.result()
                if digest_file(__file__) != RUNNER_SHA256:
                    raise RuntimeError("campaign runner changed during execution; restart required")
                by_id = {row["source_span_id"]: row for row in rows}
                for row in receipt["rows"]:
                    original = by_id[row["source_span_id"]]
                    for key, value in original.items():
                        if key not in row:
                            row[key] = value
                receipt["campaign"] = {"batch_id": batch_id, "progress": descriptor,
                    "runner_sha256": RUNNER_SHA256,
                    "source_sha256": SOURCE_SHA, "compiler_workers": args.compiler_workers,
                    "cpu_cuda_overlap": pending is not None,
                    "whole_batch_seconds": time.monotonic() - started, "inference_only": True}
                stage(db, runtime, batch_id, receipt, args.agent_id)
                completed += 1
                publish_pending(db, args.upload, runtime)
                value = status(db, runtime, phase="running", last_batch=batch_id, last_sample_count=len(rows))
                event("batch_complete", batch_id=batch_id, samples=len(rows), work=value["work"],
                    wall_seconds=receipt["campaign"]["whole_batch_seconds"], admitted=False)
    except BaseException:
        if STOP:
            return 0
        raise
    finally:
        status(db, runtime, phase="stopped" if STOP else "engine_exited")
        db.execute("CHECKPOINT")
        db.close()
    return 0


def arguments(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runtime-directory", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, default=LEGACY)
    p.add_argument("--source-parquet", type=Path, default=SOURCE)
    p.add_argument("--resource-ledger", type=Path, default=LEDGER)
    p.add_argument("--compiler-workers", type=int, default=4)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--bridge-workers", type=int, default=1, help="parallel native target threads within the resident model")
    p.add_argument("--max-batches", type=int, default=0, help="0 runs until explicitly stopped")
    p.add_argument("--poll-seconds", type=int, default=300)
    p.add_argument("--storage-bytes", type=int, default=750_000_000)
    p.add_argument("--memory-mb", type=int, default=12288)
    p.add_argument("--agent-id", default="legacy-cuda-census")
    p.add_argument("--upload", action="store_true")
    p.add_argument("--publish-only", action="store_true", help="deliver retained batches without loading the model")
    p.add_argument("--_engine", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if not 1 <= args.compiler_workers <= 8 or not 1 <= args.bridge_workers <= 8 or not 1 <= args.batch_size <= 32 or args.max_batches < 0 or not 1 <= args.poll_seconds <= 3600:
        p.error("invalid worker, batch or polling bound")
    args.runtime_directory = args.runtime_directory.absolute()
    return args


def main(argv=None):
    environment()
    args = arguments(argv)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if args._engine:
        return engine(args)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_campaign_resources import LegacySpanCampaignResources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import SCHEDULER_LANE, get_global_resource_scheduler
    cpu_slots = 1 if args.publish_only else args.compiler_workers + args.bridge_workers + 1
    memory_mb = min(args.memory_mb, 2048) if args.publish_only else args.memory_mb
    child_slots = 1 if args.publish_only else args.compiler_workers + 4
    config = get_global_resource_scheduler().config
    others = [value for name, value in config.reservations().items() if name != SCHEDULER_LANE.value]
    maximum_cpu = config.total_cpu_slots - sum(value.cpu_slots for value in others)
    maximum_memory = config.total_memory_mb - config.reserved_memory_mb - sum(value.memory_mb for value in others)
    if cpu_slots > maximum_cpu or memory_mb > maximum_memory:
        raise ValueError(f"campaign requests {cpu_slots} CPU slots/{memory_mb} MiB; lane permits {maximum_cpu}/{maximum_memory}")
    if child_slots > config.total_child_process_slots:
        raise ValueError("campaign child slots exceed the host scheduler capacity")
    args.runtime_directory.mkdir(parents=True, exist_ok=True)
    lock = os.open(args.runtime_directory / "owner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource = LegacySpanCampaignResources(args.runtime_directory, args.resource_ledger,
        storage_bytes=args.storage_bytes, memory_mb=memory_mb, cpu_slots=cpu_slots,
        child_process_slots=child_slots)
    child = None
    resource.open()
    try:
        command = [sys.executable, "-B", str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv), "--_engine"]
        child = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
        resource.attach_child(child.pid)
        atomic(args.runtime_directory / "owner.json", {"pid": os.getpid(), "engine_pid": child.pid,
            "overall_timeout_seconds": None, "reservation_id": resource.reservation.reservation_id})
        while child.poll() is None:
            if STOP:
                stop_child(child)
                break
            observation = resource.check_limits()
            atomic(args.runtime_directory / "resource-status.json", observation)
            time.sleep(2)
        return 0 if STOP else (child.returncode or 0)
    finally:
        if child is not None and child.poll() is None:
            stop_child(child)
        if child is not None:
            child.wait()
        try:
            resource.close(artifacts_durable=True)
        except BaseException:
            resource.__exit__(*sys.exc_info())
            raise
        finally:
            os.close(lock)


if __name__ == "__main__":
    raise SystemExit(main())
