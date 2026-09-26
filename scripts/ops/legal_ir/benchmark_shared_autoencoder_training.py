#!/usr/bin/env python3
"""Qualify shared targets and accepted sparse capture on three public gates.

No corpus campaign, publication, promotion, download, or Lean admission. The
pinned checkpoint is read-only. Scratch retains full recovery checkpoints;
patch byte reduction is not a claim of reduced total checkpoint I/O yet.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
PINNED = ROOT / "workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
PINNED_SHA = "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"
GATES = (
    ("backup", "Company A shall submit backup report within 10 days unless emergency."),
    ("prohibit", "The agency shall not disclose records."),
    ("minimum", "The officer shall retain the file for at least 20 days."),
)


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write(path, payload):
    with Path(path).open("x") as stream:
        json.dump(payload, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def _prepare(records, path):
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import prepare_training_targets
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
    return prepare_training_targets([SampleRecord.from_dict(row) for row in records], path)


def _prepare_arrow(path):
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import build_feature_embedding_weights_ipc
    if _sha(PINNED) != PINNED_SHA:
        raise RuntimeError("pinned checkpoint changed before Arrow materialization")
    started = time.perf_counter()
    rows = json.loads(PINNED.read_bytes())["feature_embedding_weights"]
    descriptor = build_feature_embedding_weights_ipc(rows, path, base_checkpoint_sha256=PINNED_SHA)
    return {"descriptor": descriptor, "path": str(path), "elapsed_seconds": time.perf_counter() - started}


def _numbers(value, prefix=""):
    if isinstance(value, dict):
        return {key: number for name, child in value.items()
                for key, number in _numbers(child, prefix + "/" + str(name)).items()}
    if isinstance(value, list):
        return {key: number for index, child in enumerate(value)
                for key, number in _numbers(child, prefix + "/" + str(index)).items()}
    return {prefix: value} if isinstance(value, (int, float, bool)) else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=2)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.pairs <= 5:
        parser.error("use a new receipt path and 1–5 paired comparisons")
    sys.path.insert(0, str(ROOT))
    os.environ.update({"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
                       "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "OPENBLAS_NUM_THREADS": "1",
                       "OMP_NUM_THREADS": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import run_training_jobs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, BRIDGE_NAMES

    source_paths = list(require_workspace_logic_tree().values())
    source_paths += [str(ROOT / "ipfs_datasets_py" / name) for name in (
        "logic/legal_document.py", "duckdb_control/autoencoder_registry.py",
        *("optimizers/logic_theorem_optimizer/" + name for name in (
            "modal_autoencoder.py", "modal_autoencoder_state_version.py",
            "modal_autoencoder_state_transaction.py", "modal_autoencoder_patch_codec.py",
            "modal_autoencoder_arrow_weights.py", "legal_ir_target_snapshot.py",
            "autoencoder_target_preparation.py", "autoencoder_training_worker.py",
            "autoencoder_training_coordinator.py", "legal_samples.py")),
    )]
    if _sha(PINNED) != PINNED_SHA:
        raise RuntimeError("pinned checkpoint changed")
    samples = [{"title": "gate", "section": section, "text": text} for section, text in GATES]
    started = time.perf_counter()
    receipt = {"schema": "shared-target-sparse-training-benchmark-v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "admitted": False,
        "promotion_performed": False, "heldout_canary": False,
        "workload": "three_public_gate_sentences_in_sample", "sample_count": 3,
        "bridge_names": list(BRIDGE_NAMES), "legal_ir_evaluate_provers": False,
        "legal_ir_parallel_workers": 1, "training_workers": 1, "metric_disk_cache": 0,
        "use_sample_memory": False, "backend": "python_sparse_batch", "temperature": 0,
        "max_seconds": 180, "max_line_search_attempts": 1, "projection_max_update_families": 1,
        "epochs": 1, "native_threads": 1, "state_sha256": PINNED_SHA,
        "state_bytes": PINNED.stat().st_size,
        "source_hashes": {str(Path(path).relative_to(ROOT)): _sha(path) for path in source_paths},
        "cache_policy": "fresh process per job; fresh mode constructs targets; shared mode loads sealed targets; OS cache uncontrolled",
        "modes": [], "parity": []}
    with tempfile.TemporaryDirectory(prefix="shared-target-benchmark-") as directory:
        scratch = Path(directory)
        with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as executor:
            preparation = executor.submit(_prepare, samples, str(scratch / "targets.json")).result()
            arrow = executor.submit(_prepare_arrow, str(scratch / "feature-weights.arrow")).result()
        receipt["target_preparation"] = preparation
        receipt["arrow_materialization"] = arrow
        with AutoencoderRegistry(scratch / "control.duckdb", scratch / "artifacts") as registry:
            base = registry.stage_artifact(PINNED, PINNED_SHA)
            targets = registry.stage_artifact(preparation["artifact"]["path"], preparation["artifact"]["sha256"])
            arrow_artifact = registry.stage_artifact(arrow["path"], arrow["descriptor"]["sha256"])
            registry.register_variant("variant", "english-gate", {
                "source_language": "en", "target_formal_language": "typed_deontic_ir",
                "jurisdiction": "us", "model_variant": "shared-target-fixture"})
            version = registry.register_version("base", "english-gate", base)["version_id"]
            registry.initialize_head("head", "english-gate", "benchmark", version)
            modes = [mode for pair in range(args.pairs)
                     for mode in (("fresh", "shared") if pair % 2 == 0 else ("shared", "fresh"))]
            modes.append("shared_sparse")
            modes.append("shared_arrow_sparse")
            for index, mode in enumerate(modes):
                run_id = f"{index}-{mode}"
                payload = {
                    "job_id": run_id, "run_id": run_id, "base_version_id": version,
                    "base_checkpoint": {**base, "path": str(registry.artifact_path(base))},
                    "output_directory": str(scratch / run_id),
                    "code_identity": "actual-file-hashes-in-worker-receipt",
                    "dataset_snapshot_id": hashlib.sha256(json.dumps(samples, sort_keys=True).encode()).hexdigest(),
                    "split_snapshot_id": "public-three-gates-in-sample", "samples": samples, "validation_samples": samples,
                    "variant": {"model_variant": "shared-target-fixture"},
                    "training_config": {"profile_projection": True},
                    "capture_sparse_patches": mode in {"shared_sparse", "shared_arrow_sparse"},
                }
                if mode != "fresh":
                    payload.update(target_snapshot_id=preparation["target_snapshot_id"],
                                   target_snapshot_artifact={**targets, "path": str(registry.artifact_path(targets))})
                if mode == "shared_arrow_sparse":
                    payload["arrow_feature_weights_artifact"] = {**arrow_artifact, "path": str(registry.artifact_path(arrow_artifact))}
                spec = TrainingJobSpec.from_dict(payload)
                job_path = scratch / (run_id + ".job.json")
                _write(job_path, spec.to_dict())
                job_artifact = registry.stage_artifact(job_path)
                registry.create_run("create-" + run_id, run_id, "english-gate", version,
                    {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": job_artifact})
                step_started = time.perf_counter()
                result = run_training_jobs(registry, [spec], max_workers=1)
                elapsed = time.perf_counter() - step_started
                if result["failed"]:
                    raise RuntimeError(f"worker failure: {result['failed']}")
                worker = json.loads((Path(spec.output_directory) / "receipt.json").read_bytes())
                if any(worker["training_report"][stage]["legal_ir_target_count"] != 3 for stage in ("before", "after")):
                    raise RuntimeError("target coverage differs from 3/3")
                receipt["modes"].append({"mode": mode, "elapsed_seconds": elapsed,
                    "seconds_per_training_span": elapsed / 3, "worker": worker,
                    "owner_result": result})
                print(json.dumps({"mode": mode, "elapsed_seconds": elapsed, "admitted": False}), flush=True)
            head = registry.resolve_head("english-gate", "benchmark")
            receipt["head_unchanged"] = head["version_id"] == version
        with AutoencoderRegistry(scratch / "control.duckdb", scratch / "artifacts") as reopened:
            receipt["runs_survive_restart"] = all(reopened.get_run(row["worker"]["run_id"])["status"] == "completed" for row in receipt["modes"])
        baseline = receipt["modes"][0]["worker"]
        for row in receipt["modes"][1:]:
            other = row["worker"]
            receipt["parity"].append({"mode": row["mode"], "run_id": other["run_id"],
                "candidate_bytes_identical": baseline["candidate"]["sha256"] == other["candidate"]["sha256"],
                "accepted_epochs_identical": baseline["optimizer_accepted_epochs"] == other["optimizer_accepted_epochs"],
                "before_numeric_metrics_identical": _numbers(baseline["training_report"]["before"]) == _numbers(other["training_report"]["before"]),
                "after_numeric_metrics_identical": _numbers(baseline["training_report"]["after"]) == _numbers(other["training_report"]["after"]),
            })
        sparse = receipt["modes"][-1]
        receipt["sparse_replay_verified"] = sparse["owner_result"]["completed"][0]["result"]["sparse_replay_verified"]
        receipt["patch_bytes"] = sparse["worker"]["sparse_patch_bytes"]
        receipt["full_candidate_bytes"] = sparse["worker"]["candidate"]["bytes"]
        receipt["checkpoint_io_scope"] = "full candidate anchors still written and staged; patch size is separate"
    receipt["pinned_checkpoint_unchanged"] = _sha(PINNED) == PINNED_SHA
    receipt["elapsed_seconds"] = time.perf_counter() - started
    receipt["passed"] = all(receipt[key] for key in ("head_unchanged", "runs_survive_restart", "sparse_replay_verified", "pinned_checkpoint_unchanged")) and all(
        all(value is True for key, value in row.items() if key not in {"mode", "run_id"}) for row in receipt["parity"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "admitted": False}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
