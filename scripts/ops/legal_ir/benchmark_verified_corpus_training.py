#!/usr/bin/env python3
"""Qualify source-bound diagnostic batches and checkpoint inventory preparation.

Three public gates only. No corpus campaign, downloads, promotion, publication,
or Lean admission. The archived restart12 checkpoint is read-only.
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
import statistics
import sys
import tempfile
import time

from benchmark_shared_autoencoder_training import GATES, PINNED, PINNED_SHA, ROOT, _sha, _write
from benchmark_sparse_checkpoint_training import _compare, _inventory, _prepare


def _run(args, receipt):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import (
        registered_checkpoint_inputs, run_training_jobs,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
        SourceArtifact, SourceSpan, SourceSampleRecord, build_corpus_manifest,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import resolve_checkpoint

    records = [{"title": "gate", "section": section, "text": text} for section, text in GATES]
    with tempfile.TemporaryDirectory(prefix="verified-corpus-benchmark-") as directory:
        scratch = Path(directory)
        source = scratch / "public-gates.txt"
        source.write_bytes(("\n".join(text for _, text in GATES) + "\n").encode())
        source_ref = {"sha256": _sha(source), "bytes": source.stat().st_size}
        source_records = []
        offset = 0
        for row in records:
            length = len(row["text"].encode())
            source_records.append(SourceSampleRecord(
                source=SourceSpan(artifact=SourceArtifact(**source_ref), source_kind="diagnostic",
                    release_id="public-gates-v1", document_id="public-gates", language="en",
                    citation="diagnostic:" + row["section"], byte_start=offset, byte_end=offset + length),
                sample=SampleRecord.from_dict(row),
            ))
            offset += length + 1
        manifest = build_corpus_manifest(source_records,
            training_record_ids=[row.record_id for row in source_records],
            validation_record_ids=[row.record_id for row in source_records], mode="diagnostic")
        manifest.validate_sources(lambda ref: source)
        manifest_path = scratch / "corpus.manifest.json"
        manifest.save(manifest_path, resolver=lambda ref: source)
        receipt["batch_manifest"] = {
            "sha256": _sha(manifest_path), "bytes": manifest_path.stat().st_size,
            "dataset_snapshot_id": manifest.dataset_snapshot_id,
            "split_snapshot_id": manifest.split_snapshot_id,
            "source": source_ref, "mode": "diagnostic", "source_kind": "diagnostic",
        }
        with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as executor:
            prepared = executor.submit(_prepare, records, str(scratch / "targets.bundle")).result()
        receipt["target_preparation"] = prepared
        if len(prepared["statuses"]) != 3 or set(prepared["statuses"].values()) != {"ready"}:
            raise RuntimeError("qualification requires three ready targets")
        database, artifacts = scratch / "control.duckdb", scratch / "artifacts"
        preparation_seconds = {}

        def job(registry, run_id, version_id, verified):
            started = time.perf_counter()
            payload = {
                "schema_version": "autoencoder-training-job-v4" if verified else "autoencoder-training-job-v3",
                "job_id": run_id, "run_id": run_id, "base_version_id": version_id,
                **registered_checkpoint_inputs(registry, version_id),
                "output_directory": str(scratch / run_id), "code_identity": "actual-source-file-hashes",
                "dataset_snapshot_id": manifest.dataset_snapshot_id if verified else "legacy-public-gates",
                "split_snapshot_id": manifest.split_snapshot_id if verified else "legacy-in-sample",
                "samples": records, "validation_samples": records,
                "variant": {"model_variant": "verified-corpus-fixture"},
                "training_config": {"profile_projection": True}, "capture_sparse_patches": True,
                "candidate_storage": "sparse", "target_snapshot_id": prepared["target_snapshot_id"],
                "target_snapshot_artifact": {**targets, "path": str(registry.artifact_path(targets))},
            }
            if verified:
                payload.update(corpus_manifest_artifact={**sealed, "path": str(registry.artifact_path(sealed))},
                    corpus_source_artifacts=[{**staged_source, "path": str(registry.artifact_path(staged_source))}])
            spec = TrainingJobSpec.from_dict(payload)
            path = scratch / (run_id + ".job.json")
            _write(path, spec.to_dict())
            registry.create_run("create-" + run_id, run_id, "english-gate", version_id,
                {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": registry.stage_artifact(path)})
            preparation_seconds[run_id] = time.perf_counter() - started
            return spec

        def execute(registry, specs, workers=1):
            started = time.perf_counter()
            result = run_training_jobs(registry, specs, max_workers=workers)
            elapsed = time.perf_counter() - started
            if result["failed"]:
                receipt["failed_owner_result"] = result
                raise RuntimeError("native job failed")
            rows = []
            for spec in specs:
                worker = json.loads((Path(spec.output_directory) / "receipt.json").read_bytes())
                completed = next(row for row in result["completed"] if row["run_id"] == spec.run_id)
                if any(worker["training_report"][stage]["legal_ir_target_count"] != 3 for stage in ("before", "after")):
                    raise RuntimeError("target coverage differs from 3/3")
                if worker["shared_target_status_counts"] != {"ready": 3} or worker["optimizer_accepted_epochs"] != 1:
                    raise RuntimeError("qualification requires three ready targets and one accepted epoch")
                verified = spec.corpus_manifest_artifact is not None
                mode = "manifest_and_source_bytes" if verified else "legacy_unverified"
                if (worker["corpus_verification"]["verification_mode"] != mode
                        or worker["dataset_and_split_identity_verified"] is not verified
                        or worker["corpus_verification"]["global_holdout_verified"] is not False):
                    raise RuntimeError("corpus input qualification differs from the requested mode")
                rows.append({"mode": "verified" if spec.corpus_manifest_artifact else "legacy",
                    "worker": worker, "completed": completed})
            prep = sum(preparation_seconds[spec.run_id] for spec in specs)
            batch = {"elapsed_seconds": elapsed, "seconds_per_training_span": elapsed / (3 * len(specs)),
                "job_preparation_seconds": prep, "prepared_job_end_to_end_seconds": elapsed + prep,
                "training_workers": workers, "jobs": rows,
                "timing_scope": "dispatch through durable completion; prepared job also includes input inventory, job staging and run creation; target preparation and initial source staging excluded"}
            print(json.dumps({"runs": [spec.run_id for spec in specs], "elapsed_seconds": elapsed, "admitted": False}), flush=True)
            return batch

        def profile_preparation(registry, version_id):
            reference = registry.get_version(version_id)["artifact"]
            timings = {"prior_full_reconstruction": [], "inventory": []}
            old_dependencies = None
            new_dependencies = None
            for index in range(3):
                for mode in (("prior_full_reconstruction", "inventory") if index % 2 == 0 else ("inventory", "prior_full_reconstruction")):
                    started = time.perf_counter()
                    if mode == "prior_full_reconstruction":
                        root = registry.verify_artifact(reference)
                        resolved = resolve_checkpoint(root, resolver=lambda ref: registry.artifact_path(registry.verify_artifact(ref)))
                        old_dependencies = sorted((dict(ref) for ref in resolved.artifacts if dict(ref) != root), key=lambda ref: ref["sha256"])
                        # Include the same path construction as the former helper.
                        for ref in (root, *old_dependencies):
                            registry.artifact_path(ref)
                        del resolved
                    else:
                        value = registered_checkpoint_inputs(registry, version_id)
                        new_dependencies = [{"sha256": ref["sha256"], "bytes": ref["bytes"]} for ref in value["base_checkpoint_dependencies"]]
                    timings[mode].append(time.perf_counter() - started)
            if old_dependencies != new_dependencies:
                raise RuntimeError("inventory closure differs from replay closure")
            return {"timings_seconds": timings, "median_seconds": {key: statistics.median(value) for key, value in timings.items()},
                "identical_dependency_closure": True, "repeats": 3,
                "inventory_scope": "hash/schema/reference verification only; worker and owner still replay before candidate registration"}

        first = {}
        with AutoencoderRegistry(database, artifacts) as registry:
            base = registry.stage_artifact(PINNED, PINNED_SHA)
            targets = registry.stage_artifact(prepared["artifact"]["path"], prepared["artifact"]["sha256"])
            sealed = registry.stage_artifact(manifest_path)
            staged_source = registry.stage_artifact(source)
            registry.register_variant("variant", "english-gate", {"source_language": "en",
                "target_formal_language": "typed_deontic_ir", "jurisdiction": "us", "model_variant": "verified-corpus-fixture"})
            version = registry.register_version("base", "english-gate", base)["version_id"]
            registry.initialize_head("head", "english-gate", "benchmark", version)
            receipt["full_base_input_preparation"] = profile_preparation(registry, version)
            modes = [mode for pair in range(args.pairs) for mode in ((False, True) if pair % 2 == 0 else (True, False))]
            for index, verified in enumerate(modes):
                spec = job(registry, f"paired-{index}-{'verified' if verified else 'legacy'}", version, verified)
                batch = execute(registry, [spec])
                receipt["paired_runs"].append(batch)
                first.setdefault(batch["jobs"][0]["mode"], batch["jobs"][0])
            reference = first["legacy"]["worker"]
            for batch in receipt["paired_runs"]:
                parity = _compare(reference, batch["jobs"][0]["worker"])
                receipt["parity"].append(parity)
                if not all(parity.values()):
                    raise RuntimeError("verified and legacy results differ")
            receipt["head_unchanged"] = registry.resolve_head("english-gate", "benchmark")["version_id"] == version

        with AutoencoderRegistry(database, artifacts) as registry:
            sparse_version = first["verified"]["completed"]["version_id"]
            receipt["sparse_base_input_preparation"] = profile_preparation(registry, sparse_version)
            specs = [job(registry, f"resumed-verified-{index}", sparse_version, True) for index in range(2)]
            receipt["parallel_resume"] = execute(registry, specs, workers=2)
            left, right = receipt["parallel_resume"]["jobs"]
            receipt["resume_parity"] = _compare(left["worker"], right["worker"])
            if not all(receipt["resume_parity"].values()):
                raise RuntimeError("parallel resumed candidates differ")
            receipt["head_unchanged_after_resume"] = registry.resolve_head("english-gate", "benchmark")["version_id"] == version
        with AutoencoderRegistry(database, artifacts) as registry:
            all_rows = [batch["jobs"][0] for batch in receipt["paired_runs"]] + receipt["parallel_resume"]["jobs"]
            receipt["runs_survive_restart"] = all(registry.get_run(row["worker"]["run_id"])["status"] == "completed" for row in all_rows)
            receipt["source_survives_restart"] = registry.verify_artifact(staged_source) == staged_source
            receipt["manifest_survives_restart"] = registry.verify_artifact(sealed) == sealed
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
    paths = list(require_workspace_logic_tree().values())
    paths += [str(Path(__file__).resolve().with_name(name)) for name in (
        Path(__file__).name, "benchmark_sparse_checkpoint_training.py", "benchmark_shared_autoencoder_training.py")]
    paths += [str(ROOT / "ipfs_datasets_py" / name) for name in (
        "duckdb_control/autoencoder_registry.py", "huggingface/autoencoder_release.py",
        *("optimizers/logic_theorem_optimizer/" + name for name in (
            "modal_autoencoder.py", "modal_autoencoder_state_version.py", "modal_autoencoder_state_transaction.py",
            "modal_autoencoder_patch_codec.py", "modal_autoencoder_sparse_checkpoint.py", "modal_autoencoder_arrow_weights.py",
            "legal_ir_target_snapshot.py", "legal_ir_target_bundle.py", "autoencoder_target_preparation.py",
            "autoencoder_corpus_manifest.py", "autoencoder_training_worker.py", "autoencoder_training_coordinator.py", "legal_samples.py")),
    )]
    if _sha(PINNED) != PINNED_SHA:
        raise RuntimeError("pinned checkpoint changed")
    started = time.perf_counter()
    receipt = {"schema": "verified-corpus-training-benchmark-v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": False, "admitted": False, "promotion_performed": False, "heldout_canary": False,
        "workload": "three_public_gate_sentences_in_sample", "sample_count_per_job": 3,
        "bridge_names": list(BRIDGE_NAMES), "legal_ir_evaluate_provers": False, "legal_ir_parallel_workers": 1,
        "paired_training_workers": 1, "resume_training_workers": 2, "metric_disk_cache": 0, "use_sample_memory": False,
        "backend": "python_sparse_batch", "temperature": 0, "epochs": 1, "max_seconds": 180,
        "projection_max_update_families": 1, "max_line_search_attempts": 1, "native_threads": 1,
        "state_sha256": PINNED_SHA, "state_bytes": PINNED.stat().st_size,
        "cache_policy": "fresh training processes; complete shared targets explicitly reused; generation caches bypassed; OS cache uncontrolled; preparation microbenchmark repeats in one owner",
        "source_hashes": {str(Path(path).relative_to(ROOT)): _sha(path) for path in paths},
        "paired_runs": [], "parity": []}
    try:
        _run(args, receipt)
        receipt["source_unchanged"] = all(_sha(ROOT / name) == digest for name, digest in receipt["source_hashes"].items())
        receipt["pinned_checkpoint_unchanged"] = _sha(PINNED) == PINNED_SHA
        receipt["passed"] = all(receipt[key] for key in ("source_unchanged", "pinned_checkpoint_unchanged",
            "head_unchanged", "head_unchanged_after_resume", "runs_survive_restart", "source_survives_restart",
            "manifest_survives_restart", "scratch_removed"))
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    receipt["elapsed_seconds"] = time.perf_counter() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "admitted": False}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
