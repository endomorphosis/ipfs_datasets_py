#!/usr/bin/env python3
"""Compare capture observations with saved original helpers on frozen samples.

This is capture-only diagnostic parity and overhead analysis, not training,
bridge evaluation, or a legal-admission measurement. No weights are loaded.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan"
PRIOR = EVIDENCE / "shared-target-native-20260925.json"
REFERENCES = {
    "capture": ("ontology-observation-reference-capture-20260925.py", "31f923a5fc7e5f9cab9486a26838857d2a412364026eba801f8142a8ffd0b689"),
    "wrapper": ("ontology-observation-reference-wrapper-20260925.py", "518105a77a9cc88261ee513e4b3e553304fea8489a3f611245e0371296bc15b2"),
    "conversion": ("ontology-conversion-reference-20260925.py", "a1ec4f7432e726d155d40e5eba12dc867af289aa67c24b22d2d3f0f835e35226"),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def execute(payload, mode, references):
    sys.path.insert(0, str(ROOT))
    ontology_capture = importlib.import_module("ipfs_datasets_py.logic.autoformal.ontology_capture")
    recipient_reference = importlib.import_module("ipfs_datasets_py.logic.autoformal.recipient_reference")
    procedure_slot = importlib.import_module("ipfs_datasets_py.logic.autoformal.procedure_slot")
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord, TrainingConfig
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import target_snapshot_config
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_ontology_observation import observe_ontology_captures
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample

    config = target_snapshot_config(TrainingConfig.from_dict(payload["training_config"]))
    if mode == "reference":
        for key, module, names in (
            ("capture", ontology_capture, ("triples_from_sample", "capture_samples")),
            ("conversion", recipient_reference, ("recipient_surface_from_sentence",)),
            ("conversion", procedure_slot, ("procedure_from_sentence",)),
            ("wrapper", modal, ("_capture_ontology",)),
        ):
            ref = references[key]
            raw = Path(ref["path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                raise ValueError("historical capture reference changed")
            namespace = dict(module.__dict__)
            exec(compile(raw, ref["path"], "exec"), namespace)
            for name in names:
                setattr(module, name, namespace[name])
    elif mode != "observed":
        raise ValueError("unknown capture mode")
    training = [build_us_code_sample(**asdict(SampleRecord.from_dict(row))) for row in payload["samples"]]
    validation = [build_us_code_sample(**asdict(SampleRecord.from_dict(row))) for row in payload["validation_samples"]]
    schedule = (validation, training, validation)
    if [len(rows) for rows in schedule] != [3, 3, 3]:
        raise ValueError("frozen capture schedule changed")
    started = time.perf_counter()
    if mode == "observed":
        with observe_ontology_captures(producer_identity={"source_config_sha256": digest(config.to_dict())}) as observation:
            captures = [modal._capture_ontology(rows) for rows in schedule]
        elapsed = time.perf_counter() - started
        telemetry = observation.to_dict()
    else:
        captures = [modal._capture_ontology(rows) for rows in schedule]
        elapsed = time.perf_counter() - started
        telemetry = None
    if target_snapshot_config(TrainingConfig.from_dict(payload["training_config"])) != config:
        raise ValueError("capture producer changed")
    if [len(rows) for rows in captures] != [3, 3, 3]:
        raise ValueError("capture batch lost a source row")
    for rows in captures:
        for row in rows:
            if any(row[key]["admitted"] is not False for key in ("recipient", "procedure")) or row["admitted"] is not False:
                raise ValueError("capture cannot admit a source row")
    return {"mode": mode, "diagnostic_helper_substitution": mode == "reference",
            "capture_wall_seconds": elapsed, "seconds_per_capture": elapsed / 9,
            "ordered_sample_ids": [[sample.sample_id for sample in rows] for rows in schedule],
            "captures": captures, "captures_sha256": digest(captures), "telemetry": telemetry,
            "source_configuration_sha256": digest(config.to_dict()),
            "source_unchanged_within_process": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a new receipt path")
    sys.path.insert(0, str(ROOT))
    os.environ.update({"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    prior = json.loads(PRIOR.read_bytes())
    payload = prior["combined_arrow_inputs_and_feature_weights"]["jobs"][0]["worker"]["job_spec"]
    references = {}
    for key, (name, expected) in REFERENCES.items():
        path = EVIDENCE / name
        actual = sha(path)
        if expected is not None and expected != actual:
            raise ValueError("reference digest mismatch")
        references[key] = {"path": str(path), "sha256": actual}
    receipt = {"schema": "ontology-observation-capture-diagnostic-v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "passed": False,
        "scope": "one paired nine-capture diagnostic; no bridge evaluation, model loading or training",
        "source_selection": {"path": str(PRIOR), "sha256": sha(PRIOR)}, "references": references,
        "script_sha256": sha(__file__), "capture_count": 9, "distinct_sample_count": 6,
        "cache_policy": "fresh process each mode; no capture result reuse; OS cache uncontrolled",
        "sample_memory_used": False, "provers_called": False, "metric_disk_cache": 0,
        "bridge_evaluate_performed": False, "weights_loaded": False, "weights_downloaded": False,
        "owner_dispatch_performed": False, "admitted": False, "formalized": False, "runs": []}
    started = time.perf_counter()
    try:
        if prior["passed"] is not True:
            raise ValueError("parent input qualification failed")
        for mode in ("reference", "observed"):
            with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as pool:
                receipt["runs"].append(pool.submit(execute, payload, mode, references).result())
        left, right = receipt["runs"]
        receipt["exact_capture_parity"] = left["captures"] == right["captures"]
        receipt["same_source_configuration"] = left["source_configuration_sha256"] == right["source_configuration_sha256"]
        receipt["same_schedule"] = left["ordered_sample_ids"] == right["ordered_sample_ids"]
        receipt["passed"] = all(receipt[key] for key in ("exact_capture_parity", "same_source_configuration", "same_schedule"))
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    receipt["elapsed_seconds"] = time.perf_counter() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "error": receipt.get("error")}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
