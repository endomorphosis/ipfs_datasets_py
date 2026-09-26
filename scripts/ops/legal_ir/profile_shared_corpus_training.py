#!/usr/bin/env python3
"""Diagnostic cProfile of the previously qualified shared-target corpus job.

Profiling overhead makes these unsuitable as wall-speed measurements. This
does not dispatch to the owner, promote, publish, fetch weights, or admit Lean.
"""
from __future__ import annotations

import argparse
import cProfile
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import pstats
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
PRIOR = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan/produced-arrow-training-20260925.json"


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prior-receipt", type=Path, default=PRIOR)
    parser.add_argument("--prepare-targets", action="store_true",
                        help="regenerate the same frozen samples under current producer provenance")
    args = parser.parse_args()
    if args.directory.exists() or args.output.exists():
        parser.error("use new diagnostic directory and receipt paths")
    args.directory = args.directory.resolve()
    args.directory.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    os.environ.update({"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, execute_training_job
    from benchmark_sparse_checkpoint_training import _compare

    prior = json.loads(args.prior_receipt.read_bytes())
    if not prior["passed"] or any(sha(ROOT / path) != digest for path, digest in prior["source_hashes"].items()):
        raise ValueError("qualified baseline source changed before diagnostic")
    reference = prior["paired_runs"][0]["jobs"][0]["worker"]
    payload = reference["job_spec"]
    payload.update(job_id="profile-shared-corpus", run_id="profile-shared-corpus",
                   output_directory=str(args.directory / "worker-output"))
    spec = TrainingJobSpec.from_dict(payload)
    result = {"schema": "shared-corpus-training-profile-v1", "diagnostic_only": True,
        "wall_speed_claim": False, "admitted": False, "formalized": False,
        "owner_dispatch_performed": False, "promotion_performed": False, "publication_performed": False,
        "prior_receipt": {"path": str(args.prior_receipt), "sha256": sha(args.prior_receipt)}, "source_hashes": prior["source_hashes"],
        "profile_script_sha256": sha(__file__), "passed": False}
    profiler = cProfile.Profile()
    started = time.perf_counter()
    try:
        if args.prepare_targets:
            from benchmark_produced_corpus_arrow_training import _prepare
            with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as executor:
                prepared = executor.submit(_prepare, payload["samples"], payload["validation_samples"],
                                           str(args.directory / "targets.bundle")).result()
            result["target_preparation"] = prepared
            if set(prepared["statuses"].values()) != {"ready"} or prepared["sample_count"] != 6:
                raise ValueError("the same six ready targets are required; no reselection")
            payload.update(target_snapshot_id=prepared["target_snapshot_id"],
                           target_snapshot_artifact={key: prepared["artifact"][key] for key in ("path", "sha256", "bytes")})
            spec = TrainingJobSpec.from_dict(payload)
        worker = profiler.runcall(execute_training_job, spec)
        result["worker_receipt"] = {"path": str(Path(spec.output_directory) / "receipt.json"),
                                    "sha256": sha(Path(spec.output_directory) / "receipt.json")}
        result["parity"] = _compare(reference, worker)
        if args.prepare_targets:
            # Fresh graph identities contain timestamps. Retain and disclose
            # the full comparison, and compare every other metric separately.
            result["regenerated_target_parity"] = {
                phase: {key: value for key, value in reference["training_report"][phase].items()
                        if key != "legal_ir_target_hashes"} ==
                       {key: value for key, value in worker["training_report"][phase].items()
                        if key != "legal_ir_target_hashes"}
                for phase in ("before", "after")}
        result["profiled_training_seconds"] = worker["training_seconds"]
        result["source_unchanged"] = all(sha(ROOT / path) == digest for path, digest in prior["source_hashes"].items())
        result["passed"] = result["source_unchanged"] and (
            all(result["regenerated_target_parity"].values()) and
            all(value for key, value in result["parity"].items() if not key.startswith("complete_"))
            if args.prepare_targets else all(result["parity"].values()))
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    result["diagnostic_elapsed_seconds"] = time.perf_counter() - started
    profile_path = args.directory / "worker.pstats"
    profiler.dump_stats(str(profile_path))
    result["profile_artifact"] = {"path": str(profile_path), "sha256": sha(profile_path), "bytes": profile_path.stat().st_size}
    stats = pstats.Stats(profiler)
    result["top_cumulative"] = [
        {"file": key[0], "line": key[1], "function": key[2], "primitive_calls": value[0],
         "calls": value[1], "self_seconds": value[2], "cumulative_seconds": value[3]}
        for key, value in sorted(stats.stats.items(), key=lambda pair: pair[1][3], reverse=True)[:70]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"receipt": str(args.output), "passed": result["passed"], "error": result.get("error")}), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
