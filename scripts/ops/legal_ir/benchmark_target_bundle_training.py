#!/usr/bin/env python3
"""Qualify complete compressed target shards against identical legacy targets.

Uses the three public gates in-sample and the read-only restart12 checkpoint.
No downloads, corpus campaign, model promotion, publication or Lean admission.
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

from benchmark_shared_autoencoder_training import GATES, PINNED, PINNED_SHA, ROOT, _numbers, _sha, _write


def _prepare_pair(records, directory):
    """Exercise streaming preparation; derive JSON from those exact targets."""
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import prepare_training_targets
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import load_target_bundle
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import build_target_snapshot
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample

    root = Path(directory)
    prepared = prepare_training_targets(
        [SampleRecord.from_dict(row) for row in records], root / "targets.bundle", artifact_format="bundle",
    )
    started = time.perf_counter()
    samples = [build_us_code_sample(**row) for row in records]
    with load_target_bundle(prepared["artifact"]["path"], expected_sha256=prepared["artifact"]["sha256"]) as bundle:
        targets = bundle.targets_for(samples, config=bundle.config)
        legacy = build_target_snapshot(samples, targets, config=bundle.config, statuses=bundle.statuses)
        saved = legacy.save(root / "targets.json")
        stats = dict(bundle.statistics)
    return {
        "bundle_preparation": prepared,
        "json_materialization": {
            "artifact": {key: saved[key] for key in ("path", "sha256", "bytes")},
            "target_snapshot_id": saved["snapshot_id"],
            "elapsed_seconds": time.perf_counter() - started,
            "scope": "load bundle, hydrate complete targets, build and durably save v1 JSON; no new targets generated",
        },
        "bundle_statistics_after_transcode": stats,
    }


def _audit_pair(records, prepared):
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import load_target_bundle
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import load_target_snapshot, _encode, _json
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample

    require_workspace_logic_tree()
    samples = [build_us_code_sample(**row) for row in records]
    json_artifact = prepared["json_materialization"]["artifact"]
    legacy = load_target_snapshot(json_artifact["path"], expected_sha256=json_artifact["sha256"])
    legacy_targets = legacy.targets_for(samples, config=legacy.config)
    bundle_artifact = prepared["bundle_preparation"]["artifact"]
    with load_target_bundle(bundle_artifact["path"], expected_sha256=bundle_artifact["sha256"]) as bundle:
        bundle_targets = bundle.targets_for(samples, config=bundle.config)
        rows = []
        for sample in samples:
            left, right = legacy_targets[sample.sample_id], bundle_targets[sample.sample_id]
            left_sha = hashlib.sha256(_json(_encode(left))).hexdigest()
            right_sha = hashlib.sha256(_json(_encode(right))).hexdigest()
            rows.append({
                "sample_id": sample.sample_id, "json_payload_sha256": left_sha,
                "bundle_payload_sha256": right_sha, "complete_payload_identical": left_sha == right_sha,
                "document_hash_identical": left.document.canonical_hash() == right.document.canonical_hash(),
            })
        return {
            "config_identical": bundle.config.to_dict() == legacy.config.to_dict(),
            "statuses_identical": bundle.statuses == legacy.statuses,
            "sample_count": bundle.sample_count, "payloads": rows,
        }


def _audit_subset(records, prepared):
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import load_target_bundle
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import _encode, _json
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample

    require_workspace_logic_tree()
    sample = build_us_code_sample(**records[0])
    artifact = prepared["bundle_preparation"]["artifact"]
    with load_target_bundle(artifact["path"], expected_sha256=artifact["sha256"]) as bundle:
        before = dict(bundle.statistics)
        targets = bundle.targets_for([sample], config=bundle.config)
        return {
            "manifest_sample_count": bundle.sample_count, "requested_sample_count": 1,
            "returned_sample_count": len(targets), "sample_id": sample.sample_id,
            "payload_sha256": hashlib.sha256(_json(_encode(targets[sample.sample_id]))).hexdigest(),
            "statistics_before": before, "statistics_after": dict(bundle.statistics),
        }


def _one_process(callback, *args):
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as executor:
        return executor.submit(callback, *args).result()


def _run(args, receipt):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import run_training_jobs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec

    records = [{"title": "gate", "section": section, "text": text} for section, text in GATES]
    with tempfile.TemporaryDirectory(prefix="target-bundle-benchmark-") as directory:
        scratch = Path(directory)
        prepared = _one_process(_prepare_pair, records, directory)
        receipt["target_artifacts"] = prepared
        statuses = prepared["bundle_preparation"]["statuses"]
        if len(statuses) != len(records) or set(statuses.values()) != {"ready"}:
            raise RuntimeError("qualification requires three complete ready targets, with no timeout fallback")
        receipt["complete_target_parity"] = _one_process(_audit_pair, records, prepared)
        receipt["subset_loading"] = _one_process(_audit_subset, records, prepared)
        audit = receipt["complete_target_parity"]
        if not (audit["sample_count"] == len(records) and audit["config_identical"] and audit["statuses_identical"] and
                all(row["complete_payload_identical"] and row["document_hash_identical"] for row in audit["payloads"])):
            raise RuntimeError("complete target payload equivalence failed")
        subset = receipt["subset_loading"]
        expected = next(row["bundle_payload_sha256"] for row in audit["payloads"] if row["sample_id"] == subset["sample_id"])
        if subset["manifest_sample_count"] != len(records) or subset["returned_sample_count"] != 1 or subset["payload_sha256"] != expected:
            raise RuntimeError("subset target differs from complete target")
        if (subset["statistics_before"]["decompressed_shards"] != 0 or
                subset["statistics_after"]["decompressed_shards"] != 1 or
                subset["statistics_after"]["unique_decompressed_shards"] != 1):
            raise RuntimeError("subset load did not hydrate exactly one target shard")

        with AutoencoderRegistry(scratch / "control.duckdb", scratch / "artifacts") as registry:
            base = registry.stage_artifact(PINNED, PINNED_SHA)
            staged = {}
            for mode, key in (("shared_json", "json_materialization"), ("shared_bundle", "bundle_preparation")):
                item = prepared[key]
                artifact = registry.stage_artifact(item["artifact"]["path"], item["artifact"]["sha256"])
                staged[mode] = (item["target_snapshot_id"], {**artifact, "path": str(registry.artifact_path(artifact))})
            registry.register_variant("variant", "english-gate", {
                "source_language": "en", "target_formal_language": "typed_deontic_ir",
                "jurisdiction": "us", "model_variant": "target-bundle-fixture"})
            version = registry.register_version("base", "english-gate", base)["version_id"]
            registry.initialize_head("head", "english-gate", "benchmark", version)
            modes = [mode for pair in range(args.pairs) for mode in (
                ("fresh", "shared_json", "shared_bundle") if pair % 2 == 0 else
                ("shared_bundle", "shared_json", "fresh"))]
            modes.append("shared_bundle_sparse")
            for index, mode in enumerate(modes):
                run_id = f"{index}-{mode}"
                payload = {
                    "job_id": run_id, "run_id": run_id, "base_version_id": version,
                    "base_checkpoint": {**base, "path": str(registry.artifact_path(base))},
                    "output_directory": str(scratch / run_id),
                    "code_identity": "actual-file-hashes-in-worker-receipt",
                    "dataset_snapshot_id": hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest(),
                    "split_snapshot_id": "public-three-gates-in-sample", "samples": records, "validation_samples": records,
                    "variant": {"model_variant": "target-bundle-fixture"},
                    "training_config": {"profile_projection": True}, "capture_sparse_patches": mode.endswith("_sparse"),
                }
                if mode != "fresh":
                    snapshot_id, artifact = staged["shared_bundle" if mode.endswith("_sparse") else mode]
                    payload.update(target_snapshot_id=snapshot_id, target_snapshot_artifact=artifact)
                spec = TrainingJobSpec.from_dict(payload)
                job_path = scratch / (run_id + ".job.json")
                _write(job_path, spec.to_dict())
                job_artifact = registry.stage_artifact(job_path)
                registry.create_run("create-" + run_id, run_id, "english-gate", version,
                    {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": job_artifact})
                started = time.perf_counter()
                result = run_training_jobs(registry, [spec], max_workers=1)
                elapsed = time.perf_counter() - started
                if result["failed"]:
                    receipt["failed_owner_result"] = result
                    raise RuntimeError("native worker failed; see failed_owner_result")
                worker = json.loads((Path(spec.output_directory) / "receipt.json").read_bytes())
                if any(worker["training_report"][stage]["legal_ir_target_count"] != len(records) for stage in ("before", "after")):
                    raise RuntimeError("target coverage differs from 3/3")
                if worker["optimizer_accepted_epochs"] != 1:
                    raise RuntimeError("qualification requires one accepted epoch")
                if mode != "fresh" and worker["shared_target_status_counts"] != {"ready": len(records)}:
                    raise RuntimeError("shared target status coverage differs from three ready targets")
                row = {"mode": mode, "elapsed_seconds": elapsed,
                    "seconds_per_training_span": elapsed / len(records), "worker": worker, "owner_result": result}
                receipt["modes"].append(row)
                print(json.dumps({"mode": mode, "elapsed_seconds": elapsed, "admitted": False}), flush=True)
            receipt["head_unchanged"] = registry.resolve_head("english-gate", "benchmark")["version_id"] == version
        with AutoencoderRegistry(scratch / "control.duckdb", scratch / "artifacts") as reopened:
            receipt["runs_survive_restart"] = all(reopened.get_run(row["worker"]["run_id"])["status"] == "completed" for row in receipt["modes"])

        fresh = receipt["modes"][0]["worker"]
        shared = next(row["worker"] for row in receipt["modes"] if row["mode"] == "shared_json")
        for row in receipt["modes"]:
            other = row["worker"]
            parity = {
                "mode": row["mode"], "run_id": other["run_id"],
                "candidate_bytes_identical": fresh["candidate"]["sha256"] == other["candidate"]["sha256"],
                "accepted_epochs_identical": fresh["optimizer_accepted_epochs"] == other["optimizer_accepted_epochs"],
                "before_numeric_metrics_identical": _numbers(fresh["training_report"]["before"]) == _numbers(other["training_report"]["before"]),
                "after_numeric_metrics_identical": _numbers(fresh["training_report"]["after"]) == _numbers(other["training_report"]["after"]),
            }
            if row["mode"] != "fresh":
                parity.update({
                    "complete_before_evaluation_identical": shared["training_report"]["before"] == other["training_report"]["before"],
                    "complete_after_evaluation_identical": shared["training_report"]["after"] == other["training_report"]["after"],
                })
            receipt["parity"].append(parity)
        receipt["sparse_replay_verified"] = receipt["modes"][-1]["owner_result"]["completed"][0]["result"]["sparse_replay_verified"]
        receipt["scratch_removed_on_exit"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=2)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.pairs <= 5:
        parser.error("use a new receipt path and 1–5 comparisons per mode")
    sys.path.insert(0, str(ROOT))
    os.environ.update({"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import BRIDGE_NAMES

    source_paths = list(require_workspace_logic_tree().values()) + [
        str(Path(__file__).resolve()), str(Path(__file__).resolve().with_name("benchmark_shared_autoencoder_training.py")),
    ]
    source_paths += [str(ROOT / "ipfs_datasets_py" / name) for name in (
        "logic/legal_document.py", "duckdb_control/autoencoder_registry.py",
        *("optimizers/logic_theorem_optimizer/" + name for name in (
            "modal_autoencoder.py", "modal_autoencoder_state_version.py", "modal_autoencoder_state_transaction.py",
            "modal_autoencoder_patch_codec.py", "legal_ir_target_snapshot.py", "legal_ir_target_bundle.py",
            "autoencoder_target_preparation.py", "autoencoder_training_worker.py", "autoencoder_training_coordinator.py",
            "legal_samples.py")),
    )]
    if _sha(PINNED) != PINNED_SHA:
        raise RuntimeError("pinned checkpoint changed")
    started = time.perf_counter()
    receipt = {"schema": "target-bundle-training-benchmark-v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "admitted": False, "promotion_performed": False, "heldout_canary": False,
        "workload": "three_public_gate_sentences_in_sample", "sample_count": 3,
        "bridge_names": list(BRIDGE_NAMES), "legal_ir_evaluate_provers": False,
        "legal_ir_parallel_workers": 1, "training_workers": 1, "metric_disk_cache": 0,
        "use_sample_memory": False, "backend": "python_sparse_batch", "temperature": 0,
        "max_seconds": 180, "max_line_search_attempts": 1, "projection_max_update_families": 1,
        "epochs": 1, "native_threads": 1, "state_sha256": PINNED_SHA, "state_bytes": PINNED.stat().st_size,
        "source_hashes": {str(Path(path).relative_to(ROOT)): _sha(path) for path in source_paths},
        "cache_policy": "fresh process per job; generation bypasses metric/multiview caches; shared modes reuse exact sealed targets; OS cache uncontrolled",
        "modes": [], "parity": [], "passed": False}
    try:
        _run(args, receipt)
        receipt["source_unchanged"] = all(_sha(ROOT / name) == digest for name, digest in receipt["source_hashes"].items())
        receipt["pinned_checkpoint_unchanged"] = _sha(PINNED) == PINNED_SHA
        receipt["passed"] = all(receipt[key] for key in (
            "head_unchanged", "runs_survive_restart", "sparse_replay_verified", "source_unchanged", "pinned_checkpoint_unchanged")) and all(
            all(value is True for key, value in row.items() if key not in {"mode", "run_id"}) for row in receipt["parity"])
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    receipt["elapsed_seconds"] = time.perf_counter() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "admitted": False}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
