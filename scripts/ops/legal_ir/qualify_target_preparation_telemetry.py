#!/usr/bin/env python3
"""Qualify receipt-only target diagnostics with one normal combined Arrow job.

The prior native receipt freezes three training and three validation inputs.
Targets are regenerated under current source/configuration and consumed through
normal owner verification. Bridge acceptance is observed, never inferred from
ready status. No promotion, publication, model download, or admission occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import copy
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
PRIOR = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan/shared-target-native-20260925.json"
PRIOR_SHA = "98c54695aaa4de0d5cc407edba213c3d5e8a275abc00b8c28b1e87fe09a39012"
PINNED = ROOT / "workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
PINNED_SHA = "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"
PINNED_BYTES = 25895338


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def verify_descriptor(ref):
    if Path(ref["path"]).stat().st_size != ref["bytes"] or sha(ref["path"]) != ref["sha256"]:
        raise ValueError("artifact descriptor changed: " + str(ref["path"]))


def prepare(payload, path):
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import prepare_training_targets
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord, TrainingConfig

    return prepare_training_targets([SampleRecord.from_dict(row) for row in payload["samples"]], path,
        validation_records=[SampleRecord.from_dict(row) for row in payload["validation_samples"]],
        training_config=TrainingConfig.from_dict(payload["training_config"]), artifact_format="bundle")


def run(args, receipt):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import registered_checkpoint_inputs, run_training_jobs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, verify_corpus_job_inputs

    if sha(PRIOR) != PRIOR_SHA:
        raise ValueError("frozen parent receipt changed")
    prior = json.loads(PRIOR.read_bytes())
    if prior["passed"] is not True:
        raise ValueError("parent native qualification did not pass")
    prior_row = prior["combined_arrow_inputs_and_feature_weights"]["jobs"][0]
    prior_worker = prior_row["worker"]
    payload = copy.deepcopy(prior_worker["job_spec"])
    prior_spec = TrainingJobSpec.from_dict(payload)
    if (prior_spec.canonical_sha256 != prior_worker["job_spec_canonical_sha256"]
            or prior_spec.schema_version != "autoencoder-training-job-v7"
            or prior_spec.base_checkpoint.sha256 != PINNED_SHA
            or prior_spec.base_checkpoint.bytes != PINNED_BYTES
            or prior_spec.base_checkpoint_dependencies
            or prior_spec.arrow_feature_weights_artifact is None
            or len(prior_spec.samples) != 3 or len(prior_spec.validation_samples) != 3):
        raise ValueError("parent combined job differs from frozen 3+3 input scope")
    parent_worker_path = Path(prior_spec.output_directory) / "receipt.json"
    parent_worker_ref = {**prior_row["completed"]["worker_receipt_artifact"], "path": str(parent_worker_path)}
    verify_descriptor(parent_worker_ref)
    if json.loads(parent_worker_path.read_bytes()) != prior_worker:
        raise ValueError("parent worker artifact differs from embedded receipt")
    receipt["parent_worker_receipt"] = parent_worker_ref
    receipt["parent_job_spec_canonical_sha256"] = prior_spec.canonical_sha256
    receipt["parent_input_verification"] = verify_corpus_job_inputs(prior_spec)
    receipt["selection"] = copy.deepcopy(prior["selection"])
    receipt["ordered_training_samples"] = payload["samples"]
    receipt["ordered_validation_samples"] = payload["validation_samples"]
    receipt["effective_training_config"] = payload["training_config"]
    receipt["bridge_names"] = payload["training_config"]["legal_ir_bridge_names"]
    receipt["old_target_or_metric_parity_required"] = False
    verify_descriptor({"path": str(PINNED), "sha256": PINNED_SHA, "bytes": PINNED_BYTES})

    tree_paths = require_workspace_logic_tree()
    for name, filename in (("autoencoder", "modal_autoencoder.py"), ("samples", "legal_samples.py"),
                           ("worker", "autoencoder_training_worker.py")):
        tree_paths[name] = str(ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / filename)
    expected_sources = {name: sha(path) for name, path in tree_paths.items()}
    source_paths = {ROOT / name for name in prior["source_hashes"]}
    source_paths.update(Path(path) for path in tree_paths.values())
    source_paths.add(ROOT / "ipfs_datasets_py/logic/autoformal/__init__.py")
    source_paths.add(Path(__file__).resolve())
    receipt["source_hashes"] = {str(path.relative_to(ROOT)): sha(path) for path in sorted(source_paths)}
    write(args.directory / "selection.json", receipt["selection"])

    preparation_started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as executor:
        prepared = executor.submit(prepare, payload, str(args.directory / "targets.bundle")).result()
    receipt["target_preparation_dispatch_seconds"] = time.perf_counter() - preparation_started
    receipt["target_preparation"] = prepared
    preparation_path = args.directory / "target-preparation.json"
    write(preparation_path, prepared)
    if (prepared["sample_count"] != 6 or prepared["legal_ir_target_count"] != 6
            or len(prepared["statuses"]) != 6
            or set(prepared["statuses"].values()) - {"ready", "timeout"}
            or set(prepared["bridge_report_telemetry"]) != set(prepared["statuses"])):
        raise ValueError("preparation must retain all six targets and their actual diagnostic observations")
    receipt["target_status_counts"] = dict(Counter(prepared["statuses"].values()))

    database, artifacts = args.directory / "control.duckdb", args.directory / "artifacts"
    variant_id, run_id, branch = "target-preparation-telemetry", "combined-arrow-telemetry", "qualification"
    staging_started = time.perf_counter()
    with AutoencoderRegistry(database, artifacts) as registry:
        def stage(ref):
            verify_descriptor(ref)
            staged = registry.stage_artifact(ref["path"], ref["sha256"])
            if staged != {key: ref[key] for key in ("sha256", "bytes")}:
                raise ValueError("staged descriptor differs from verified input")
            return staged

        def bound(ref):
            return {**ref, "path": str(registry.artifact_path(ref))}

        base = stage({"path": str(PINNED), "sha256": PINNED_SHA, "bytes": PINNED_BYTES})
        for field in ("corpus_manifest_artifact", "corpus_index_artifact", "embedding_production_artifact",
                      "arrow_embedding_inputs_artifact", "arrow_feature_weights_artifact"):
            payload[field] = bound(stage(payload[field]))
        payload["corpus_source_artifacts"] = [bound(stage(ref)) for ref in payload["corpus_source_artifacts"]]
        staged_targets = stage(prepared["artifact"])
        staged_preparation = registry.stage_artifact(preparation_path, sha(preparation_path))
        receipt["target_preparation_receipt_artifact"] = bound(staged_preparation)
        receipt["target_preparation_receipt_scope"] = (
            "receipt-only diagnostics bound in immutable run metadata; workers consume target bundle/statuses normally")
        variant = {**payload["variant"], "model_variant": variant_id}
        registry.register_variant("variant", variant_id, {**variant,
            "corpus_index_binding": {"selection_sha256": payload["corpus_selection_sha256"],
                "artifact": {key: payload["corpus_index_artifact"][key] for key in ("sha256", "bytes")}},
            "embedding_production_binding": {"artifact": {
                key: payload["embedding_production_artifact"][key] for key in ("sha256", "bytes")}}})
        version = registry.register_version("base", variant_id, base)["version_id"]
        registry.initialize_head("head", variant_id, branch, version)
        receipt["base_version_id"] = version
        receipt["staging_seconds"] = time.perf_counter() - staging_started

        job_started = time.perf_counter()
        payload.update(job_id=run_id, run_id=run_id, variant=variant, base_version_id=version,
            **registered_checkpoint_inputs(registry, version), output_directory=str(args.directory / run_id),
            code_identity="target-preparation-telemetry-current-source", expected_source_sha256=expected_sources,
            target_snapshot_id=prepared["target_snapshot_id"], target_snapshot_artifact=bound(staged_targets))
        spec = TrainingJobSpec.from_dict(payload)
        job_path = args.directory / "combined-arrow.job.json"
        write(job_path, spec.to_dict())
        run_metadata = {"job_spec_sha256": spec.canonical_sha256,
            "job_spec_artifact": registry.stage_artifact(job_path),
            "target_preparation_receipt_artifact": staged_preparation,
            "target_preparation_target_artifact": staged_targets,
            "target_preparation_snapshot_id": prepared["target_snapshot_id"]}
        registry.create_run("create-run", run_id, variant_id, version, run_metadata)
        receipt["run_metadata"] = run_metadata
        receipt["job_preparation_seconds"] = time.perf_counter() - job_started
        receipt["owner_dispatch_performed"] = True
        training_started = time.perf_counter()
        owner = run_training_jobs(registry, [spec], max_workers=1)
        receipt["owner_dispatch_seconds"] = time.perf_counter() - training_started
        receipt["owner_result"] = owner
        if owner["failed"] or len(owner["completed"]) != 1:
            raise ValueError("normal owner-dispatched combined job did not complete")
        completed = owner["completed"][0]
        worker_path = Path(spec.output_directory) / "receipt.json"
        worker = json.loads(worker_path.read_bytes())
        receipt["worker"] = worker
        receipt["worker_receipt_artifact"] = bound(registry.verify_artifact(completed["worker_receipt_artifact"]))
        if (worker["execution_mode"] != "native_training" or worker["source_manifest_verified"] is not True
                or worker["shared_targets_verified"] is not True or worker["shared_target_count"] != 6
                or worker["shared_target_status_counts"] != receipt["target_status_counts"]
                or worker["embedding_input_storage"] != "arrow_mapped_float32"
                or worker["weight_storage"] != "arrow_cow_feature_embeddings"
                or worker["admitted"] is not False or completed["promoted"] is not False):
            raise ValueError("combined native worker verification or target coverage mismatch")
        for phase in ("before", "after"):
            metrics = worker["training_report"][phase]
            if (metrics["legal_ir_target_count"] != 3 or not metrics["legal_ir_losses"]
                    or "deontic" not in metrics["legal_ir_view_family_metrics"]):
                raise ValueError("bridge-on evaluation requires three targets, losses and deontic view metrics")
        if (Path(spec.output_directory) / "candidate.state.json").exists():
            raise ValueError("sparse combined job unexpectedly wrote a full candidate state")
        stages = worker["training_report"]["projection_profile"]["by_stage"]
        evaluate_seconds = stages["before_holdout_evaluation"]["seconds"]
        receipt["timings"] = {
            "target_generation_seconds_for_six": prepared["target_generation_seconds"],
            "target_generation_seconds_per_sample": prepared["target_generation_seconds"] / 6,
            "target_preparation_seconds_for_six": prepared["elapsed_seconds"],
            "target_preparation_seconds_per_sample": prepared["elapsed_seconds"] / 6,
            "owner_dispatch_seconds_per_training_span": receipt["owner_dispatch_seconds"] / 3,
            "worker_seconds": worker["elapsed_seconds"],
            "worker_seconds_per_training_span": worker["elapsed_seconds"] / 3,
            "training_seconds": worker["training_seconds"],
            "training_seconds_per_training_span": worker["training_seconds"] / 3,
            "initial_evaluate_seconds_for_three_validation_samples": evaluate_seconds,
            "initial_evaluate_seconds_per_validation_sample": evaluate_seconds / 3,
            "target_load_seconds": worker["target_load_seconds"],
            "target_artifact_verification_seconds": worker["target_artifact_verification_seconds"],
            "target_hydration_seconds": worker["target_hydration_seconds"],
        }
        receipt["timing_scope"] = (
            "one observed job; target generation/preparation use six samples; training denominators use three; "
            "initial evaluation uses three validation samples; owner dispatch includes durable completion; "
            "staging/preparation excluded from owner timing; OS cache uncontrolled; no historical metric parity asserted")
        receipt["head_unchanged"] = registry.resolve_head(variant_id, branch)["version_id"] == version

    with AutoencoderRegistry(database, artifacts) as registry:
        persisted = registry.get_run(run_id)
        receipt["run_durable_after_restart"] = (
            persisted["status"] == "completed" and persisted["result"] == completed["result"])
        receipt["head_unchanged_after_restart"] = registry.resolve_head(variant_id, branch)["version_id"] == version
        persisted_ref = registry.verify_artifact(persisted["spec"]["target_preparation_receipt_artifact"])
        persisted_bytes = registry.artifact_path(persisted_ref).read_bytes()
        persisted_preparation = json.loads(persisted_bytes)
        persisted_target = registry.verify_artifact(persisted["spec"]["target_preparation_target_artifact"])
        receipt["preparation_receipt_durable_after_restart"] = (
            persisted["spec"] == run_metadata and persisted_ref == staged_preparation
            and persisted_bytes == preparation_path.read_bytes() and persisted_preparation == prepared
            and persisted_target == {key: persisted_preparation["artifact"][key] for key in ("sha256", "bytes")}
            and persisted_preparation["target_snapshot_id"] == persisted["spec"]["target_preparation_snapshot_id"]
            and persisted_preparation["target_snapshot_id"] == worker["target_snapshot_id"]
            and persisted_target == {key: worker["target_snapshot_artifact"][key] for key in ("sha256", "bytes")})
        receipt["worker_receipt_durable_after_restart"] = (
            persisted["result"]["worker_receipt_artifact"] == completed["worker_receipt_artifact"]
            and registry.artifact_path(registry.verify_artifact(persisted["result"]["worker_receipt_artifact"])).read_bytes()
            == worker_path.read_bytes())
    receipt["source_unchanged"] = all(sha(ROOT / path) == digest for path, digest in receipt["source_hashes"].items())
    receipt["pinned_checkpoint_unchanged"] = sha(PINNED) == PINNED_SHA and PINNED.stat().st_size == PINNED_BYTES
    receipt["parent_receipt_unchanged"] = sha(PRIOR) == PRIOR_SHA
    receipt["passed"] = all(receipt[key] for key in (
        "head_unchanged", "head_unchanged_after_restart", "run_durable_after_restart",
        "preparation_receipt_durable_after_restart", "worker_receipt_durable_after_restart",
        "source_unchanged", "pinned_checkpoint_unchanged", "parent_receipt_unchanged"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.directory.exists() or args.output.exists():
        parser.error("use new artifact and receipt paths")
    args.directory = args.directory.resolve()
    args.directory.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    os.environ.update({"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    receipt = {"schema": "target-preparation-telemetry-qualification-v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "passed": False,
        "parent_receipt": {"path": str(PRIOR), "sha256": PRIOR_SHA},
        "owner_dispatch_performed": False, "training_job_count": 1,
        "sample_count": 3, "validation_sample_count": 3, "target_union_count": 6,
        "legal_ir_evaluate_provers": False, "legal_ir_parallel_workers": 1,
        "training_workers": 1, "metric_disk_cache": 0, "use_sample_memory": False,
        "temperature": 0, "native_threads": 1, "projection_update_backend": "python_sparse_batch",
        "control_transport": "local DuckDB owner; Quack and DuckLake are not exercised by this run",
        "admitted": False, "formalized": False, "heldout_canary_qualified": False, "global_holdout_verified": False,
        "promotion_performed": False, "publication_performed": False, "weights_downloaded": False,
        "qualification_scope": "normal owner verification and durable receipt-only diagnostics; bridge acceptance remains observed",
        "target_reuse_scope": "one newly prepared current-source bundle; no historical targets reused",
        "cache_policy": "fresh preparation process and normal spawned worker; metric disk cache disabled; OS cache uncontrolled"}
    started = time.perf_counter()
    try:
        run(args, receipt)
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    receipt["elapsed_seconds"] = time.perf_counter() - started
    receipt["retained_artifact_bytes"] = sum(path.stat().st_size for path in args.directory.rglob("*") if path.is_file())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "error": receipt.get("error")}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
