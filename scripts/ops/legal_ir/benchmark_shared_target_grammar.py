#!/usr/bin/env python3
"""Compare native shared-target evaluation with frozen historical helpers.

Both modes verify a newly generated complete target bundle normally. Reference
mode explicitly substitutes three historical helpers in memory: it is a diagnostic
ablation, not an owner-qualified execution. No promotion, publication or admit.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import copy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import statistics
import sys
import time

from benchmark_produced_corpus_arrow_training import _prepare
from benchmark_sparse_checkpoint_training import _compare
from benchmark_shared_autoencoder_training import ROOT, PINNED, PINNED_SHA

PRIOR = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan/produced-arrow-training-20260925.json"
REFERENCE = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan/warm-target-reference-grammar-20260925.py"
REFERENCE_SHA = "afb0598ed8cdc89954cacfb88106cbb1769d8183f84f6d816441dc419858fd0d"
MODAL_REFERENCE = REFERENCE.with_name("warm-target-reference-modal-20260925.py")
MODAL_REFERENCE_SHA = "aff91b35c7dd7845b8ffa897a637c203d33f5f4ac8833aa9cf53c1c6ed145761"


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def execute(payload, mode):
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
    from ipfs_datasets_py.logic.modal import codec, decompiler
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, execute_training_job
    if mode == "reference":
        raw = REFERENCE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != REFERENCE_SHA:
            raise ValueError("historical helper changed")
        namespace = dict(modal.__dict__)
        exec(compile(raw, str(REFERENCE), "exec"), namespace)
        modal._legal_ir_grammar_validation_from_target = namespace["_legal_ir_grammar_validation_from_target"]
        raw = MODAL_REFERENCE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != MODAL_REFERENCE_SHA:
            raise ValueError("historical modal helpers changed")
        # Keep original global lookup, and explicitly replace codec's eager
        # alias as well as decompiler's own binding.
        exec(compile(raw, str(MODAL_REFERENCE), "exec"), decompiler.__dict__)
        codec._legal_semantic_atoms_from_text = decompiler._legal_semantic_atoms_from_text
    elif mode != "native":
        raise ValueError("unknown mode")
    helper_bindings = {
        "modal._legal_ir_grammar_validation_from_target": modal._legal_ir_grammar_validation_from_target.__code__.co_filename,
        "decompiler._legal_semantic_atoms_from_text": decompiler._legal_semantic_atoms_from_text.__code__.co_filename,
        "decompiler._bridge_cues_from_text": decompiler._bridge_cues_from_text.__code__.co_filename,
        "codec._legal_semantic_atoms_from_text": codec._legal_semantic_atoms_from_text.__code__.co_filename,
    }
    if mode == "reference" and helper_bindings != {
        key: str(REFERENCE if key.startswith("modal.") else MODAL_REFERENCE) for key in helper_bindings
    }:
        raise ValueError("incomplete historical helper substitution")
    captures = []
    capture = modal._capture_ontology

    def observe_capture(samples):
        result = capture(samples)
        captures.append(result)
        return result

    # Both modes have the same observer. No output is replaced or suppressed.
    # Serialization occurs after timing; ontology isn't in evaluate.to_dict().
    modal._capture_ontology = observe_capture
    pattern_cache_before = decompiler._compiled_decompiler_pattern.cache_info()._asdict()
    started = time.perf_counter()
    worker = execute_training_job(TrainingJobSpec.from_dict(payload))
    elapsed = time.perf_counter() - started
    pattern_cache_after = decompiler._compiled_decompiler_pattern.cache_info()._asdict()
    if len(captures) != 3 or any(len(rows) != 3 for rows in captures):
        raise ValueError("expected all three ontology captures for three samples")
    if any(row["admitted"] is not False or row["recipient"]["admitted"] is not False
           or row["procedure"]["admitted"] is not False for rows in captures for row in rows):
        raise ValueError("ontology capture cannot admit a sample")
    from ipfs_datasets_py.logic.modal.codec import modal_ir_to_flogic_triples
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
    full_triples = []
    for raw in payload["samples"] + payload["validation_samples"]:
        sample = build_us_code_sample(**asdict(SampleRecord.from_dict(raw)))
        triples = modal_ir_to_flogic_triples(sample.modal_ir)
        encoded = json.dumps(triples, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        full_triples.append({"sample_id": sample.sample_id, "count": len(triples),
                             "sha256": hashlib.sha256(encoded).hexdigest(), "json_bytes": len(encoded)})
    return {"mode": mode, "diagnostic_helper_substitution": mode == "reference",
            "ontology_observer_enabled": True, "ontology_captures": captures,
            "helper_bindings": helper_bindings,
            "compiled_pattern_cache_before": pattern_cache_before, "compiled_pattern_cache_after_worker": pattern_cache_after,
            "full_triples_after_timing": full_triples, "worker_wall_seconds": elapsed, "worker": worker}


def comparable_report(report):
    # The profiler and total elapsed time are excluded; acceptance decisions, losses, target hashes,
    # optimizer attempts, gradients and stop reasons remain exact comparisons.
    if isinstance(report, dict):
        return {key: comparable_report(value) for key, value in report.items()
                if key not in {"projection_profile", "elapsed_seconds"}}
    if isinstance(report, list):
        return [comparable_report(value) for value in report]
    return report


def run(args, receipt):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec
    prior = json.loads(PRIOR.read_bytes())
    payload = copy.deepcopy(prior["paired_runs"][0]["jobs"][0]["worker"]["job_spec"])
    receipt["ordered_training_samples"] = payload["samples"]
    receipt["ordered_validation_samples"] = payload["validation_samples"]
    receipt["effective_training_config"] = payload["training_config"]
    if (not prior["passed"] or sha(PINNED) != PINNED_SHA or sha(REFERENCE) != REFERENCE_SHA
            or sha(MODAL_REFERENCE) != MODAL_REFERENCE_SHA):
        raise ValueError("prior evidence or immutable reference binding changed")
    if args.prepared_receipt is not None:
        donor = json.loads(args.prepared_receipt.read_bytes())
        if not donor["passed"] or any(sha(ROOT / name) != digest for name, digest in donor["source_hashes"].items()):
            raise ValueError("target preparation donor is no longer qualified under current sources")
        prepared = donor["target_preparation"]
        receipt["target_preparation_reused_from"] = {"path": str(args.prepared_receipt.resolve()),
                                                    "sha256": sha(args.prepared_receipt)}
    else:
        with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as pool:
            prepared = pool.submit(_prepare, payload["samples"], payload["validation_samples"],
                                   str(args.directory / "targets.bundle")).result()
    receipt["target_preparation"] = prepared
    write(args.directory / "target-preparation.json", prepared)
    if prepared["sample_count"] != 6 or set(prepared["statuses"].values()) != {"ready"}:
        raise ValueError("require the same six ready samples; no reselection")
    payload.update(target_snapshot_id=prepared["target_snapshot_id"],
                   target_snapshot_artifact={key: prepared["artifact"][key] for key in ("path", "sha256", "bytes")})
    for pair in range(args.pairs):
        order = ("reference", "native") if pair % 2 == 0 else ("native", "reference")
        rows = []
        for mode in order:
            job = copy.deepcopy(payload)
            name = f"pair-{pair}-{mode}"
            job.update(job_id=name, run_id=name, output_directory=str(args.directory / name),
                       code_identity=f"grammar-inspection-ablation:{mode}:reference-{REFERENCE_SHA}")
            job = TrainingJobSpec.from_dict(job).to_dict()
            write(args.directory / f"{name}.job.json", job)
            started = time.perf_counter()
            with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as pool:
                row = pool.submit(execute, job, mode).result()
            row["dispatch_wall_seconds"] = time.perf_counter() - started
            worker = row["worker"]
            row["worker_wall_seconds_per_training_span"] = row["worker_wall_seconds"] / 3
            row["initial_bridge_evaluate_seconds"] = worker["training_report"]["projection_profile"]["by_stage"]["before_holdout_evaluation"]["seconds"]
            row["initial_bridge_evaluate_seconds_per_validation_span"] = row["initial_bridge_evaluate_seconds"] / 3
            for phase in ("before", "after"):
                metrics = worker["training_report"][phase]
                if metrics["legal_ir_target_count"] != 3 or not metrics["legal_ir_losses"]:
                    raise ValueError("bridge-disconnected result is not a speed qualification")
            rows.append(row)
            print(json.dumps({"job": name, "worker_seconds": row["worker_wall_seconds"],
                              "evaluate_seconds": row["initial_bridge_evaluate_seconds"]}), flush=True)
        receipt["paired_runs"].append(rows)
        left, right = (row["worker"] for row in rows)
        parity = _compare(left, right)
        parity["training_report_except_profile_and_elapsed_identical"] = comparable_report(left["training_report"]) == comparable_report(right["training_report"])
        parity["sparse_segment_count_identical"] = len(left["sparse_patch_segments"]) == len(right["sparse_patch_segments"])
        parity["all_ontology_captures_identical"] = rows[0]["ontology_captures"] == rows[1]["ontology_captures"]
        parity["all_ordered_full_triples_identical"] = rows[0]["full_triples_after_timing"] == rows[1]["full_triples_after_timing"]
        receipt["parity"].append(parity)
        if not all(parity.values()):
            raise ValueError("reference/native parity failed")
    all_workers = [row["worker"] for pair in receipt["paired_runs"] for row in pair]
    receipt["all_runs_exact_parity"] = all(all(_compare(all_workers[0], worker).values()) and
        comparable_report(all_workers[0]["training_report"]) == comparable_report(worker["training_report"])
        for worker in all_workers[1:])
    all_rows = [row for pair in receipt["paired_runs"] for row in pair]
    receipt["all_runs_capture_parity"] = all(
        row["ontology_captures"] == all_rows[0]["ontology_captures"] and
        row["full_triples_after_timing"] == all_rows[0]["full_triples_after_timing"]
        for row in all_rows[1:])
    receipt["medians"] = {mode: {key: statistics.median(row[key] for pair in receipt["paired_runs"]
        for row in pair if row["mode"] == mode) for key in (
            "worker_wall_seconds", "worker_wall_seconds_per_training_span", "dispatch_wall_seconds",
            "initial_bridge_evaluate_seconds", "initial_bridge_evaluate_seconds_per_validation_span")}
        for mode in ("reference", "native")}
    receipt["target_artifact_unchanged"] = sha(prepared["artifact"]["path"]) == prepared["artifact"]["sha256"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=2)
    parser.add_argument("--prepared-receipt", type=Path,
                        help="reuse preparation from a passing final-source native benchmark; normal worker verification still applies")
    args = parser.parse_args()
    if args.directory.exists() or args.output.exists() or not 1 <= args.pairs <= 3:
        parser.error("use new paths and 1–3 paired comparisons")
    args.directory = args.directory.resolve()
    args.directory.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    os.environ.update({"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    prior = json.loads(PRIOR.read_bytes())
    paths = [ROOT / name for name in prior["source_hashes"]]
    paths += [Path(__file__), REFERENCE, MODAL_REFERENCE, ROOT / "ipfs_datasets_py/logic/bridge/multiview.py",
              ROOT / "ipfs_datasets_py/logic/autoformal/autoencoder_router.py"]
    paths += [ROOT / "ipfs_datasets_py/logic" / name for name in (
        "modal/codec.py", "modal/decompiler.py", "autoformal/ontology_capture.py",
        "autoformal/recipient_reference.py", "autoformal/procedure_slot.py")]
    receipt = {"schema": "shared-target-grammar-ablation-v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": False, "diagnostic_reference_ablation": True, "owner_dispatch_performed": False,
        "admitted": False, "formalized": False, "promotion_performed": False, "publication_performed": False,
        "weights_downloaded": False, "prior_receipt": {"path": str(PRIOR), "sha256": sha(PRIOR)},
        "reference_helper": {"path": str(REFERENCE), "sha256": sha(REFERENCE),
            "original_module_sha256": "54b0824707bd22b49f8eaf975474aa05f1aeb791f25ae28aa4ddcf74996f1a17"},
        "reference_modal_helpers": {"path": str(MODAL_REFERENCE), "sha256": sha(MODAL_REFERENCE),
            "original_module_sha256": "2aa99133971449edbb66d1f9b4023b7a97d9d2a2df3cb4f4ca7de0c481b15213"},
        "sample_count": 3, "validation_sample_count": 3, "shared_target_union_count": 6,
        "training_report_parity_excludes": ["elapsed_seconds", "projection_profile"],
        "dispatch_timing_scope": "includes startup, worker, post-timing full-triple checks, result transfer and shutdown; not a training speed measurement",
        "cache_policy": "new process each job; same sealed shared targets; metric disk cache 0; OS cache uncontrolled; target generation excluded",
        "bridge_names": prior["bridge_names"], "legal_ir_evaluate_provers": False,
        "legal_ir_parallel_workers": 1, "use_sample_memory": False, "temperature": 0,
        "source_hashes": {str(path.relative_to(ROOT)): sha(path) for path in paths}, "paired_runs": [], "parity": []}
    started = time.perf_counter()
    try:
        run(args, receipt)
        receipt["source_unchanged"] = all(sha(ROOT / path) == digest for path, digest in receipt["source_hashes"].items())
        receipt["pinned_checkpoint_unchanged"] = sha(PINNED) == PINNED_SHA and PINNED.stat().st_size == 25895338
        receipt["passed"] = all(receipt[key] for key in (
            "source_unchanged", "pinned_checkpoint_unchanged", "target_artifact_unchanged", "all_runs_exact_parity", "all_runs_capture_parity"))
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
