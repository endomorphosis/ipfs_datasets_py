#!/usr/bin/env python3
"""Qualify local registry + independent workers on the pinned three-gate fixture.

Two independent English variants are storage/parallelism evidence, not evidence
of multilingual support, held-out improvement or Lean admission. Each serial
job gets a fresh pool; the parallel pair gets two fresh workers. All candidate
weights and databases live in disposable scratch space. Only the requested
receipt is retained. No Quack/DuckLake deployment or HF upload occurs here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timezone


REPO_ROOT = Path(__file__).resolve().parents[3]
PINNED_STATE = REPO_ROOT / "workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
PINNED_SHA256 = "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"
GATES = (
    ("backup", "Company A shall submit backup report within 10 days unless emergency."),
    ("prohibit", "The agency shall not disclose records."),
    ("minimum", "The officer shall retain the file for at least 20 days."),
)


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _write(path: Path, value: object) -> None:
    with path.open("x") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("receipt already exists; refusing overwrite")
    if _sha256(PINNED_STATE) != PINNED_SHA256:
        raise RuntimeError("pinned checkpoint digest mismatch")
    sys.path.insert(0, str(REPO_ROOT))
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, BRIDGE_NAMES
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import run_training_jobs

    pinned = require_workspace_logic_tree()
    source_paths = list(pinned.values()) + [str(REPO_ROOT / path) for path in (
        "ipfs_datasets_py/duckdb_control/autoencoder_registry.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_worker.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_samples.py",
    )]
    source_hashes = {str(Path(path).relative_to(REPO_ROOT)): _sha256(Path(path)) for path in source_paths}
    expected_source_sha256 = {name: _sha256(Path(path)) for name, path in pinned.items()}
    expected_source_sha256.update({name: _sha256(REPO_ROOT / path) for name, path in {
        "autoencoder": "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py",
        "samples": "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_samples.py",
        "worker": "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_worker.py",
    }.items()})
    code_identity = hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest()
    samples = [{"title": "gate", "section": section, "text": text} for section, text in GATES]
    dataset_identity = hashlib.sha256(json.dumps(samples, sort_keys=True).encode()).hexdigest()
    started = time.perf_counter()
    receipt = {"schema": "autoencoder-control-benchmark-v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
               "admitted": False, "promotion_performed": False, "heldout_canary": False,
               "source_hashes": source_hashes, "state_sha256": PINNED_SHA256,
               "state_bytes": PINNED_STATE.stat().st_size, "sample_count_per_job": 3,
               "bridge_names": list(BRIDGE_NAMES), "legal_ir_evaluate_provers": False,
               "legal_ir_parallel_workers": 1, "metric_disk_cache": 0, "use_sample_memory": False,
               "backend": "python_sparse_batch", "temperature": 0,
               "native_thread_limits": {"OPENBLAS_NUM_THREADS": 1, "OMP_NUM_THREADS": 1},
               "control_transport": "local_owner", "ducklake_materialization": "not_run",
               "native_quack_training_transport": "not_used_by_this_benchmark", "huggingface_upload": False,
               "workload": "two_independent_english_variants_three_in_sample_gate_sentences",
               "cache_policy": "fresh worker process for each job; metric disk cache disabled; OS file cache uncontrolled",
               "modes": {}}
    with tempfile.TemporaryDirectory(prefix="autoencoder-control-benchmark-") as directory:
        scratch = Path(directory)
        database, artifacts = scratch / "control.duckdb", scratch / "artifacts"
        with AutoencoderRegistry(database, artifacts) as registry:
            base_artifact = registry.stage_artifact(PINNED_STATE, expected_sha256=PINNED_SHA256)
            roots = {}
            for label in ("a", "b"):
                variant_id = "english-gate-" + label
                registry.register_variant("variant-" + label, variant_id,
                    {"source_language": "en", "target_formal_language": "typed_deontic_ir", "jurisdiction": "us", "model_variant": variant_id, "parameter_schema": "legacy-json@1"})
                roots[label] = registry.register_version("base-" + label, variant_id, base_artifact)["version_id"]
                registry.initialize_head("initialize-" + label, variant_id, "benchmark", roots[label])
            for mode in ("serial", "parallel"):
                specs = []
                for label in ("a", "b"):
                    run_id = mode + "-" + label
                    spec = TrainingJobSpec.from_dict({
                        "job_id": run_id, "run_id": run_id, "base_version_id": roots[label],
                        "base_checkpoint": {**base_artifact, "path": str(registry.artifact_path(base_artifact))},
                        "output_directory": str(scratch / ("attempt-" + run_id)),
                        "code_identity": code_identity, "dataset_snapshot_id": dataset_identity,
                        "expected_source_sha256": expected_source_sha256,
                        "split_snapshot_id": "in-sample-three-gate-v1", "samples": samples, "validation_samples": samples,
                        "variant": {"model_variant": "english-gate-" + label},
                        "training_config": {"profile_projection": True},
                    })
                    spec_file = scratch / (run_id + ".job.json")
                    _write(spec_file, spec.to_dict())
                    spec_artifact = registry.stage_artifact(spec_file)
                    registry.create_run("create-" + run_id, run_id, "english-gate-" + label, roots[label],
                        {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": spec_artifact})
                    specs.append(spec)
                mode_started = time.perf_counter()
                if mode == "serial":
                    summaries = [run_training_jobs(registry, [spec], max_workers=1) for spec in specs]
                else:
                    summaries = [run_training_jobs(registry, specs, max_workers=2)]
                elapsed = time.perf_counter() - mode_started
                if any(summary["failed"] for summary in summaries):
                    raise RuntimeError(f"{mode} worker failure: {summaries}")
                workers = [json.loads((Path(spec.output_directory) / "receipt.json").read_text()) for spec in specs]
                for worker in workers:
                    report = worker["training_report"]
                    if report["after"]["legal_ir_target_count"] != 3 or report["before"]["legal_ir_target_count"] != 3:
                        raise RuntimeError("bridge coverage changed; not a passing legal-IR benchmark")
                    if worker.get("process_cache_initially_empty") is not True:
                        raise RuntimeError("benchmark requires an initially empty process target cache")
                receipt["modes"][mode] = {"elapsed_seconds": elapsed, "seconds_per_job": elapsed / 2,
                    "seconds_per_training_span": elapsed / 6, "summaries": summaries, "workers": workers}
            heads = [registry.resolve_head("english-gate-" + label, "benchmark") for label in ("a", "b")]
            if [head["version_id"] for head in heads] != [roots["a"], roots["b"]]:
                raise RuntimeError("training unexpectedly promoted a head")
            receipt["heads_unchanged"] = True
        with AutoencoderRegistry(database, artifacts) as reopened:
            receipt["runs_survive_owner_restart"] = all(reopened.get_run(mode + "-" + label)["status"] == "completed" for mode in ("serial", "parallel") for label in ("a", "b"))
        serial, parallel = receipt["modes"]["serial"], receipt["modes"]["parallel"]
        comparisons = []
        for first, second in zip(serial["workers"], parallel["workers"]):
            comparisons.append({
                "variant": first["job_spec"]["variant"]["model_variant"],
                "candidate_bytes_identical": first["candidate"]["sha256"] == second["candidate"]["sha256"],
                "accepted_epochs_identical": first["optimizer_accepted_epochs"] == second["optimizer_accepted_epochs"],
                "before_numeric_metrics_identical": _numbers(first["training_report"]["before"]) == _numbers(second["training_report"]["before"]),
                "after_numeric_metrics_identical": _numbers(first["training_report"]["after"]) == _numbers(second["training_report"]["after"]),
            })
        receipt["parity"] = comparisons
        receipt["fixed_workload_speedup"] = serial["elapsed_seconds"] / parallel["elapsed_seconds"]
        receipt["passed"] = receipt["runs_survive_owner_restart"] and all(all(value is True for key, value in row.items() if key != "variant") for row in comparisons)
    receipt["scratch_removed"] = not scratch.exists()
    receipt["pinned_checkpoint_unchanged"] = _sha256(PINNED_STATE) == PINNED_SHA256
    receipt["elapsed_seconds"] = time.perf_counter() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "fixed_workload_speedup": receipt["fixed_workload_speedup"], "admitted": False}))
    return 0 if receipt["passed"] and receipt["pinned_checkpoint_unchanged"] else 1


def _numbers(value: object, prefix: str = "") -> dict[str, float | int | bool]:
    if isinstance(value, dict):
        return {key: item for name, child in value.items() for key, item in _numbers(child, prefix + "/" + str(name)).items()}
    if isinstance(value, list):
        return {key: item for index, child in enumerate(value) for key, item in _numbers(child, prefix + "/" + str(index)).items()}
    return {prefix: value} if isinstance(value, (int, float, bool)) else {}


if __name__ == "__main__":
    raise SystemExit(main())
