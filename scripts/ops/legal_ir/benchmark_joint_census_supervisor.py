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
OUT = Path("/tmp/span-joint-router-run")


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


def drain_with_supervisor(database: Path, runtime: Path) -> int:
    """Run the real supervisor once against a clean snapshot of this checkout."""

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
        prepare_code = 0
    else:
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
        prepare_code = prepare.returncode
    if prepare_code != 0:
        return prepare_code
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
        "--repository-root",
        str(snapshot),
        "--interval",
        "5",
        "--implementation-timeout",
        "300",
    ]
    print("stage supervisor drain", flush=True)
    return subprocess.run(command).returncode


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
