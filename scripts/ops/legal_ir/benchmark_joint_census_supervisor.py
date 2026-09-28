#!/usr/bin/env python3
"""Benchmark joint autoencoder and compiler optimization with a live supervisor.

Ingestion scores a few United States Code sentences. The supervisor claims
each census disagreement while later sentences are still being compiled.
The pinned checkpoint is not written, and Hugging Face is not contacted.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")

PINNED = ROOT / "workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
PINNED_SHA = "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"
PARQUET = Path.home() / ".cache/huggingface/hub/datasets--justicedao--ipfs_uscode/snapshots/5016b86a273ce5e4ffd066c5ae9f5fe494dd417e/uscode_parquet/laws.parquet"
OUT = Path(os.environ.get("JOINT_OUT", "/tmp/span-joint-router-run"))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect(limit: int) -> list[dict]:
    import importlib.util

    path = ROOT / "scripts/ops/legal_ir/run_uscode_formal_logic.py"
    spec = importlib.util.spec_from_file_location("uscode_joint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found = []
    for row_index, row in module.iter_sections(PARQUET, start_row=200):
        if str(row.get("title_number") or "") in {"", "1"}:
            continue
        for ordinal, sentence in enumerate(module.formal_sentences(row)):
            lowered = f" {sentence.lower()} "
            if " shall " not in lowered or len(sentence) > 400:
                continue
            if any(token in lowered for token in (" amendment", " means ", " the term ", " provided that")):
                continue
            found.append({
                "legal_id": f"usc:{row.get('title_number')}:{row.get('section_number')}",
                "source_span_id": f"joint-{row_index}-{ordinal}",
                "text": sentence,
            })
            if len(found) >= limit:
                return found
    return found


def decoded_text(text: str) -> str:
    from ipfs_datasets_py.logic.modal.codec import decode_modal_ir_text
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample

    sample = build_us_code_sample(title="10", section="1", text=text)
    modal = getattr(sample, "modal_ir", None)
    if modal is None:
        return ""
    return str(decode_modal_ir_text(modal) or "").strip()


def _prepare_snapshot(runtime: Path):
    import subprocess

    runtime.mkdir(parents=True, exist_ok=True)
    snapshot = runtime / "repair-repository"
    if snapshot.exists() or snapshot.is_symlink():
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=snapshot, text=True,
        )
        if dirty.strip():
            raise RuntimeError("existing repair snapshot is dirty: " + str(snapshot))
        print("stage reuse clean snapshot", flush=True)
        return snapshot
    prepare = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/ops/legal_ir/prepare_autoformal_repair_repository.py"),
            "--destination",
            str(snapshot),
            "--runtime-root",
            str(runtime),
        ],
        check=False,
    )
    if prepare.returncode != 0:
        raise RuntimeError("repair snapshot prepare failed")
    return snapshot


def _launcher():
    import importlib.util

    path = ROOT / "scripts/ops/legal_ir/run_autoformal_supervisor.py"
    spec = importlib.util.spec_from_file_location("autoformal_parallel_launch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _next_shard_alias(database: Path, shard_count: int, shard_index: int) -> str:
    """Prefer this lane's in-progress repair, then its next ready repair."""

    accelerate = "/home/barberb/lift_coding/external/ipfs_accelerate"
    if accelerate in sys.path:
        sys.path.remove(accelerate)
    sys.path.insert(0, accelerate)
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import (
        DatabaseTaskSource,
    )

    shard_of = _launcher().task_alias_shard_index
    with DatabaseTaskSource(database, install_schema=False) as source:
        inflight = [
            task.task_alias
            for task in source.list_tasks(status="in_progress", limit=100).tasks
            if task.body.get("board_namespace") == "uscode-autoformal-repair-v1"
            and shard_of(task.task_alias, shard_count) == shard_index
        ]
        if len(inflight) > 1:
            raise RuntimeError("shard has more than one in-progress repair")
        if inflight:
            return inflight[0]
        ready = [
            task.task_alias
            for task in source.ready_tasks(limit=1000).tasks
            if task.body.get("board_namespace") == "uscode-autoformal-repair-v1"
            and shard_of(task.task_alias, shard_count) == shard_index
        ]
    return ready[0] if ready else ""


def _supervise_once(
    database: Path,
    runtime: Path,
    snapshot: Path,
    *,
    shard_count: int,
    shard_index: int,
    task_id: str,
) -> int:
    import subprocess

    timeout = os.environ.get("JOINT_IMPLEMENTATION_TIMEOUT", "900")
    command = [
        sys.executable,
        str(ROOT / "scripts/ops/legal_ir/run_autoformal_supervisor.py"),
        "--accelerate-root",
        "/home/barberb/lift_coding/external/ipfs_accelerate",
        "--database",
        str(database),
        "--runtime-root",
        str(runtime),
        "supervise",
        "--implement",
        "--once",
        "--task-id",
        task_id,
        "--task-shard-count",
        str(shard_count),
        "--task-shard-index",
        str(shard_index),
        "--repository-root",
        str(snapshot),
        "--interval",
        "5",
        "--implementation-timeout",
        timeout,
    ]
    print(
        f"stage shard {shard_index}/{shard_count} task {task_id}",
        flush=True,
    )
    return subprocess.run(command).returncode


def _shard_worker(
    database: Path,
    runtime: Path,
    snapshot: Path,
    *,
    shard_count: int,
    shard_index: int,
) -> int:
    passes = int(os.environ.get("JOINT_TASKS_PER_SHARD", "2"))
    for _ in range(passes):
        alias = _next_shard_alias(database, shard_count, shard_index)
        if not alias:
            print(f"stage shard {shard_index} idle", flush=True)
            return 0
        code = _supervise_once(
            database,
            runtime,
            snapshot,
            shard_count=shard_count,
            shard_index=shard_index,
            task_id=alias,
        )
        if code != 0:
            return code
    return 0


def drain_with_supervisor(database: Path, runtime: Path) -> int:
    """Run repair lanes against one clean snapshot.

    One lane keeps the historical single supervisor. Several lanes hash the
    task alias into strict shards, each with its own execution database, and
    claim at the same time.
    """

    from concurrent.futures import ThreadPoolExecutor

    snapshot = _prepare_snapshot(runtime)
    workers = int(os.environ.get("JOINT_WORKERS", "1"))
    if workers < 1:
        raise RuntimeError("JOINT_WORKERS must be a positive integer")
    if workers == 1:
        alias = _next_shard_alias(database, 1, 0)
        if not alias:
            print("stage supervisor idle", flush=True)
            return 0
        print("stage supervisor drain", flush=True)
        return _supervise_once(
            database, runtime, snapshot, shard_count=1, shard_index=0, task_id=alias,
        )
    print(f"stage parallel supervisor workers={workers}", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _shard_worker,
                database,
                runtime,
                snapshot,
                shard_count=workers,
                shard_index=index,
            )
            for index in range(workers)
        ]
        codes = [future.result() for future in futures]
    failed = [code for code in codes if code != 0]
    return failed[0] if failed else 0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("JOINT_DRAIN_ONLY") == "1":
        return drain_with_supervisor(OUT / "control.duckdb", OUT / "runtime")
    before = _sha(PINNED) if PINNED.is_file() else ""
    spans = collect(int(os.environ.get("JOINT_SENTENCES", "1")))
    print(f"stage collected {len(spans)}", flush=True)
    import ipfs_datasets_py.logic.autoformal.autoencoder_weight_store as weight_store
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import llm_router_generate
    from ipfs_datasets_py.logic.autoformal.joint_benchmark import run_joint_benchmark
    from ipfs_datasets_py.logic.autoformal.span_agreement import train_until_canary_improves

    weight_store.publish_model_update = lambda model, *, improved, path=None: {
        "admitted": False, "delta_count": 0, "formalized": False, "improved": improved, "uploaded": False,
    }
    print("stage autoencoder", flush=True)
    started = time.perf_counter()
    trained = train_until_canary_improves(rounds=1, spans=spans, seed=1)
    train_seconds = time.perf_counter() - started
    print(f"stage joint supervisor rounds={trained.get('rounds')} seconds={train_seconds:.1f}", flush=True)
    joint = run_joint_benchmark(
        spans,
        database=OUT / "control.duckdb",
        packet_directory=OUT / "packets",
        scores=trained.get("after") or {},
        decode=decoded_text,
        round_index=int(trained.get("rounds") or 0),
        generate=llm_router_generate,
    )
    after = _sha(PINNED) if PINNED.is_file() else ""
    receipt = {
        "admitted": False,
        "autoencoder_seconds": train_seconds,
        "below_threshold": trained.get("below_threshold"),
        "claimed": len(joint["claimed"]),
        "enqueued": joint["enqueued"],
        "formalized": False,
        "overlapped": joint["overlapped"],
        "pinned_sha_unchanged": before == after == PINNED_SHA,
        "repair_schema": joint["repair_schema"],
        "schema_gaps": [item["schema_gaps"] for item in joint["claimed"] if item["schema_gaps"]],
        "agrees_with_autoencoder": [item.get("agrees_with_autoencoder") for item in joint["claimed"]],
        "census_rerun": [item.get("census_rerun") for item in joint["claimed"]],
        "repair_reason": [item.get("reason") for item in joint["claimed"]],
        "router_called": [item.get("router_called") for item in joint["claimed"]],
        "schema_ready": joint["schema_ready"],
        "threshold": trained.get("threshold"),
        "training_bridges": trained.get("training_bridges"),
        "training_families": trained.get("training_families"),
        "uploaded": False,
        "wrote_compiler": False,
    }
    (OUT / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True), flush=True)
    if os.environ.get("JOINT_DRAIN", "1") == "1":
        drained = drain_with_supervisor(OUT / "control.duckdb", OUT / "runtime")
        receipt["supervisor_drain_exit"] = drained
        (OUT / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
        if drained != 0:
            return drained
    if not receipt["pinned_sha_unchanged"] or not receipt["schema_ready"] or not receipt["overlapped"]:
        return 2
    if receipt["enqueued"] < 1 or receipt["claimed"] != receipt["enqueued"]:
        return 3
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
