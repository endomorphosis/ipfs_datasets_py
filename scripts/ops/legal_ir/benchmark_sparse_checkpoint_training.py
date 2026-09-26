#!/usr/bin/env python3
"""Measure sparse persistence and qualify resume/compaction on three gates.

Full and sparse workers use the same complete targets and accepted-patch sink.
No checkpoint download, corpus campaign, promotion, publication or Lean admit.
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

from benchmark_shared_autoencoder_training import GATES, PINNED, PINNED_SHA, ROOT, _sha, _write


def _prepare(records, path):
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import prepare_training_targets
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
    return prepare_training_targets([SampleRecord.from_dict(row) for row in records], path, artifact_format="bundle")


def _inventory(root):
    return {str(path.relative_to(root)): path.stat().st_size for path in root.rglob("*") if path.is_file()}


def _compare(left, right):
    return {
        "materialized_checkpoint_identical": left["candidate_materialized_checkpoint"] == right["candidate_materialized_checkpoint"],
        "candidate_state_identity_identical": left["candidate_state_identity"] == right["candidate_state_identity"],
        "accepted_epochs_identical": left["optimizer_accepted_epochs"] == right["optimizer_accepted_epochs"],
        "complete_before_evaluation_identical": left["training_report"]["before"] == right["training_report"]["before"],
        "complete_after_evaluation_identical": left["training_report"]["after"] == right["training_report"]["after"],
    }


def _run(args, receipt):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import (
        registered_checkpoint_inputs, run_training_jobs, SparseCheckpointPolicy,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, SCHEMA_VERSION
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import resolve_checkpoint

    records = [{"title": "gate", "section": section, "text": text} for section, text in GATES]
    with tempfile.TemporaryDirectory(prefix="sparse-checkpoint-benchmark-") as directory:
        scratch = Path(directory)
        with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as executor:
            prepared = executor.submit(_prepare, records, str(scratch / "targets.bundle")).result()
        receipt["target_preparation"] = prepared
        if len(prepared["statuses"]) != 3 or set(prepared["statuses"].values()) != {"ready"}:
            raise RuntimeError("qualification requires three ready complete targets")
        job_preparation_seconds = {}

        def job(registry, run_id, base_version, storage):
            started = time.perf_counter()
            payload = {
                "schema_version": SCHEMA_VERSION, "job_id": run_id, "run_id": run_id,
                "base_version_id": base_version, **registered_checkpoint_inputs(registry, base_version),
                "output_directory": str(scratch / run_id), "code_identity": "actual-source-file-hashes",
                "dataset_snapshot_id": hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest(),
                "split_snapshot_id": "public-three-gates-in-sample", "samples": records, "validation_samples": records,
                "variant": {"model_variant": "sparse-persistence-fixture"},
                "training_config": {"profile_projection": True}, "capture_sparse_patches": True,
                "candidate_storage": storage, "target_snapshot_id": prepared["target_snapshot_id"],
                "target_snapshot_artifact": {**targets, "path": str(registry.artifact_path(targets))},
            }
            spec = TrainingJobSpec.from_dict(payload)
            path = scratch / (run_id + ".job.json")
            _write(path, spec.to_dict())
            artifact = registry.stage_artifact(path)
            registry.create_run("create-" + run_id, run_id, "english-gate", base_version,
                {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": artifact})
            job_preparation_seconds[run_id] = time.perf_counter() - started
            return spec

        def execute(registry, specs, *, max_workers=1, policy=SparseCheckpointPolicy()):
            before = _inventory(registry.artifact_root)
            started = time.perf_counter()
            result = run_training_jobs(registry, specs, max_workers=max_workers, sparse_checkpoint_policy=policy)
            elapsed = time.perf_counter() - started
            if result["failed"]:
                receipt["failed_owner_result"] = result
                raise RuntimeError("native job failed; see failed_owner_result")
            rows = []
            for spec in specs:
                worker = json.loads((Path(spec.output_directory) / "receipt.json").read_bytes())
                completed = next(row for row in result["completed"] if row["run_id"] == spec.run_id)
                if any(worker["training_report"][stage]["legal_ir_target_count"] != 3 for stage in ("before", "after")):
                    raise RuntimeError("target coverage differs from 3/3")
                if worker["shared_target_status_counts"] != {"ready": 3} or worker["optimizer_accepted_epochs"] != 1:
                    raise RuntimeError("qualification requires three ready targets and one accepted epoch")
                if spec.candidate_storage == "sparse" and (Path(spec.output_directory) / "candidate.state.json").exists():
                    raise RuntimeError("sparse worker wrote a full candidate checkpoint")
                rows.append({
                    "mode": spec.candidate_storage, "worker": worker, "completed": completed,
                    "worker_model_payload_bytes": worker["candidate"]["bytes"] + worker["sparse_patch_bytes"],
                    "full_checkpoint_written_by_worker": (Path(spec.output_directory) / "candidate.state.json").exists(),
                })
            after = _inventory(registry.artifact_root)
            added = {key: size for key, size in after.items() if key not in before}
            batch = {"elapsed_seconds": elapsed, "seconds_per_training_span": elapsed / (3 * len(specs)),
                     "job_preparation_seconds": sum(job_preparation_seconds[spec.run_id] for spec in specs),
                     "prepared_job_end_to_end_seconds": elapsed + sum(job_preparation_seconds[spec.run_id] for spec in specs),
                     "timing_scope": "elapsed_seconds covers dispatch through durable completion; prepared_job_end_to_end_seconds also includes input closure resolution, job construction/staging and run creation; one-time targets/base staging excluded",
                     "training_workers": max_workers, "owner_result": result, "jobs": rows,
                     "new_staged_artifact_bytes": sum(added.values()), "new_staged_artifact_count": len(added),
                     "io_scope": "logical worker model payloads and newly retained staged files; excludes WAL, receipts in worker dirs, job specs and physical device writes"}
            print(json.dumps({"runs": [spec.run_id for spec in specs], "elapsed_seconds": elapsed, "admitted": False}), flush=True)
            return batch

        database, artifacts = scratch / "control.duckdb", scratch / "artifacts"
        first = {}
        with AutoencoderRegistry(database, artifacts) as registry:
            base = registry.stage_artifact(PINNED, PINNED_SHA)
            targets = registry.stage_artifact(prepared["artifact"]["path"], prepared["artifact"]["sha256"])
            registry.register_variant("variant", "english-gate", {
                "source_language": "en", "target_formal_language": "typed_deontic_ir",
                "jurisdiction": "us", "model_variant": "sparse-persistence-fixture"})
            version = registry.register_version("base", "english-gate", base)["version_id"]
            registry.initialize_head("head", "english-gate", "benchmark", version)
            modes = [mode for pair in range(args.pairs) for mode in (("full", "sparse") if pair % 2 == 0 else ("sparse", "full"))]
            for index, mode in enumerate(modes):
                spec = job(registry, f"paired-{index}-{mode}", version, mode)
                batch = execute(registry, [spec])
                receipt["paired_runs"].append(batch)
                row = batch["jobs"][0]
                first.setdefault(mode, row)
                if mode == "sparse" and row["completed"]["result"]["sparse_compaction_performed"]:
                    raise RuntimeError("default first sparse candidate unexpectedly compacted")
            reference = first["full"]["worker"]
            for batch in receipt["paired_runs"]:
                row = batch["jobs"][0]
                parity = _compare(reference, row["worker"])
                receipt["parity"].append({"run_id": row["worker"]["run_id"], **parity})
                if not all(parity.values()):
                    raise RuntimeError("full and sparse paired candidates differ")
            receipt["head_unchanged_before_restart"] = registry.resolve_head("english-gate", "benchmark")["version_id"] == version

        # Reopen the owner before resuming from the stored sparse version.
        with AutoencoderRegistry(database, artifacts) as registry:
            specs = [job(registry, "resume-" + mode, first[mode]["completed"]["version_id"], mode) for mode in ("full", "sparse")]
            resumed = execute(registry, specs, max_workers=2, policy=SparseCheckpointPolicy(max_depth=2))
            receipt["resume_parallel_batch"] = resumed
            left, right = (next(row for row in resumed["jobs"] if row["mode"] == mode) for mode in ("full", "sparse"))
            receipt["resume_parity"] = _compare(left["worker"], right["worker"])
            summary = right["completed"]["result"]
            if not (all(receipt["resume_parity"].values()) and summary["sparse_compaction_performed"] and
                    "max_depth" in summary["sparse_compaction_reasons"] and summary["checkpoint_storage"] == "full_json"):
                raise RuntimeError("resume or forced depth-2 compaction qualification failed")
            compacted_version = right["completed"]["version_id"]
            reference_checkpoint = left["worker"]["candidate_materialized_checkpoint"]
            receipt["compacted_candidate_identical"] = right["completed"]["candidate"] == reference_checkpoint
            receipt["head_unchanged_after_resume"] = registry.resolve_head("english-gate", "benchmark")["version_id"] == version

        with AutoencoderRegistry(database, artifacts) as registry:
            record = registry.get_version(compacted_version)
            def resolver(ref):
                return registry.artifact_path(registry.verify_artifact(ref))
            resolved = resolve_checkpoint(record["artifact"], resolver=resolver)
            receipt["compacted_reopen"] = {
                "version_id": compacted_version, "materialized_checkpoint": resolved.materialized_checkpoint,
                "matches_full_reference": resolved.materialized_checkpoint == reference_checkpoint,
                "depth": resolved.depth, "revision": resolved.state.state_revision,
                "dependency_count": len(registered_checkpoint_inputs(registry, compacted_version)["base_checkpoint_dependencies"]),
            }
            all_rows = [batch["jobs"][0] for batch in receipt["paired_runs"]] + receipt["resume_parallel_batch"]["jobs"]
            receipt["runs_survive_restart"] = all(registry.get_run(row["worker"]["run_id"])["status"] == "completed" for row in all_rows)
        receipt["retained_scratch_bytes_before_cleanup"] = sum(_inventory(scratch).values())
    receipt["scratch_removed"] = not scratch.exists()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=2)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.pairs <= 5:
        parser.error("use a new receipt path and 1–5 paired comparisons")
    sys.path.insert(0, str(ROOT))
    os.environ.update({"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import BRIDGE_NAMES

    paths = list(require_workspace_logic_tree().values()) + [str(Path(__file__).resolve()),
        str(Path(__file__).resolve().with_name("benchmark_shared_autoencoder_training.py"))]
    paths += [str(ROOT / "ipfs_datasets_py" / name) for name in (
        "duckdb_control/autoencoder_registry.py", "huggingface/autoencoder_release.py",
        *("optimizers/logic_theorem_optimizer/" + name for name in (
            "modal_autoencoder.py", "modal_autoencoder_state_version.py", "modal_autoencoder_state_transaction.py",
            "modal_autoencoder_patch_codec.py", "modal_autoencoder_sparse_checkpoint.py",
            "legal_ir_target_snapshot.py", "legal_ir_target_bundle.py", "autoencoder_target_preparation.py",
            "autoencoder_training_worker.py", "autoencoder_training_coordinator.py", "legal_samples.py")),
    )]
    if _sha(PINNED) != PINNED_SHA:
        raise RuntimeError("pinned checkpoint changed")
    started = time.perf_counter()
    receipt = {"schema": "sparse-checkpoint-training-benchmark-v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": False, "admitted": False, "promotion_performed": False, "heldout_canary": False,
        "workload": "three_public_gate_sentences_in_sample", "sample_count_per_job": 3,
        "bridge_names": list(BRIDGE_NAMES), "legal_ir_evaluate_provers": False, "legal_ir_parallel_workers": 1,
        "paired_training_workers": 1, "resume_training_workers": 2, "metric_disk_cache": 0, "use_sample_memory": False,
        "backend": "python_sparse_batch", "temperature": 0, "epochs": 1, "max_seconds": 180,
        "projection_max_update_families": 1, "max_line_search_attempts": 1, "native_threads": 1,
        "state_sha256": PINNED_SHA, "state_bytes": PINNED.stat().st_size,
        "cache_policy": "fresh processes with complete shared bundle targets; generation caches bypassed; shared jobs are target reuse; OS cache uncontrolled",
        "source_hashes": {str(Path(path).relative_to(ROOT)): _sha(path) for path in paths},
        "paired_runs": [], "parity": []}
    try:
        _run(args, receipt)
        receipt["source_unchanged"] = all(_sha(ROOT / name) == digest for name, digest in receipt["source_hashes"].items())
        receipt["pinned_checkpoint_unchanged"] = _sha(PINNED) == PINNED_SHA
        receipt["passed"] = all(receipt[key] for key in (
            "source_unchanged", "pinned_checkpoint_unchanged", "head_unchanged_before_restart", "head_unchanged_after_resume",
            "compacted_candidate_identical", "runs_survive_restart", "scratch_removed")) and (
                receipt["compacted_reopen"]["matches_full_reference"] and receipt["compacted_reopen"]["depth"] == 0 and
                receipt["compacted_reopen"]["revision"] == 0 and receipt["compacted_reopen"]["dependency_count"] == 0)
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    receipt["elapsed_seconds"] = time.perf_counter() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "admitted": False}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
