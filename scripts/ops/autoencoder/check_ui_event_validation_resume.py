#!/usr/bin/env python3
"""Validate explicit UI EC and resume prepared targets without model inference.

This is an authored projection/resource regression, not new fidelity evidence.
The six previous resource failures remain archived. Completed durable results
are evidence only on process restart; they never restore live training gates.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
TOOLS = {
    "lake": ("/home/barberb/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lake",
             "8c987aee79f105bc2ff21772b958b219c8921a51b8ca2df8af410a2b17bd8701"),
    "java": ("/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/advisors/temurin-jdk/17.0.20+8/jdk/bin/java",
             "0cd543f9949605b5eccb1d2b98c2b8637bb0953f0b5087208393b4b7ded73c1a"),
    "tla2tools": ("/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/tlc/1.8.0/tla2tools.jar",
                  "e22f8ffb4bacdea0a871f444dd94fe5fb0d8013b3388ae39e82e26f852c735d5"),
}
FALSE = dict(admitted=False, qualified=False, formalized=False, source_semantics_verified=False,
    model_inference_executed=False, training_executed=False, weights_modified=False,
    source_prediction_repaired=False, event_authenticity_verified=False, fresh_holdout=False)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-native-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()
    output, prior = args.output.resolve(), args.previous_native_directory.resolve()
    require(output.is_dir() if args.resume else not output.exists(), "new output or explicit existing resume required")
    sys.dont_write_bytecode = True
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        HF_DATASETS_OFFLINE="1", IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0", CUDA_VISIBLE_DEVICES="",
        OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    sys.path.insert(0, str(ROOT))
    pins = {}

    def pin(path, expected=None):
        path = Path(path).resolve()
        actual = sha(path)
        require(expected is None or expected == actual, "input/tool changed: " + str(path))
        require(str(path) not in pins or pins[str(path)] == actual, "input changed during reading")
        pins[str(path)] = actual

    def read(path):
        pin(path)
        return json.loads(Path(path).read_bytes())

    for path, digest in TOOLS.values():
        pin(path, digest)
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training as core
    from ipfs_datasets_py.logic.formalization.autoencoder import intent_source_contract_384 as intent
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v4 as old_ui
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v5 as ui
    from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks_v3 as checks
    from ipfs_datasets_py.logic.formalization.autoencoder import resumable_native_validation as resume
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v7 as trainer
    tree = require_workspace_logic_tree()
    previous = read(prior / "parallel-receipt.json")
    unfinished = [row for row in previous["jobs"] if row["status"] == "failed"]
    require(len(unfinished) == 6 and all(row["error_type"] == "LeaseTimeoutError" for row in unfinished),
        "exact six previously unfinished native resource jobs required")
    jobs, attempts = [], []
    for row in unfinished:
        identity = row["job_id"]
        require(checks._identifier(identity) == identity, "unsafe prior job identifier")
        old = read(prior / identity / "candidate-and-preparation.json")
        options = {}
        for key, value in old["interpretation_options"].items():
            require(key in {"behavior_interpretation", "guard_interpretation"}, "unknown historical interpretation")
            cls = old_ui.UIBehaviorInterpretation if key == "behavior_interpretation" else old_ui.UIGuardInterpretation
            options[key] = cls.from_dict(value)
        adapter = intent if old["domain"] == "intent_ir" else old_ui
        prepared = adapter.prepare_family_targets(old["source_text"], old["candidate"], **options)
        require(prepared["report"] == old["family_report"] and core._json(prepared["source_inputs"]) == old["source_inputs"],
            "historical prepared target changed: " + identity)
        jobs.append(checks.NativeProjectionJob(identity, prepared["report"], prepared["source_inputs"]))
        attempts.append({"job_id": identity, "origin": "exact_replayed_prepared_target_without_inference",
            "old_native_failure": row, "preparation_status": "prepared", "packet": core._json(prepared), **FALSE})
    fixture = ROOT / "tests/fixtures/logic/ui_bounded_event_v1/cases.py"
    pin(fixture)
    pin(ROOT / "tests/fixtures/logic/native_dcec_ui_v1/guard_cases.py")
    spec = importlib.util.spec_from_file_location("bounded_ui_event_regression", fixture)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixtures = module.cases()
    require(len(fixtures) == 9, "complete declared nine-case EC panel required")
    for index, row in enumerate(fixtures):
        identity = "fixture-" + row["id"]
        record = {"job_id": identity, "origin": row["candidate_origin"],
            "candidate": row["candidate"], "source_text": row["source_text"],
            "interpretation_options": core._json(row["options"]), **FALSE}
        try:
            prepared = ui.prepare_family_targets(row["source_text"], row["candidate"], **row["options"])
        except ValueError as error:
            require(index >= 3, "positive EC preparation unexpectedly failed: " + str(error))
            record.update(preparation_status="blocked_before_lake", reason=str(error), error_type=type(error).__name__)
        else:
            require(index < 3, "negative EC control unexpectedly prepared")
            require(len(prepared["report"]["requested_families"]) == 40, "family request narrowed")
            record.update(preparation_status="prepared", packet=core._json(prepared))
            jobs.append(checks.NativeProjectionJob(identity, prepared["report"], prepared["source_inputs"]))
        attempts.append(record)
    require(len(jobs) == 9 and len(attempts) == 15, "complete intended regression scope required")
    preparation_seconds = time.perf_counter() - started
    prepared_wire = core._json({"attempts": attempts, "tree": tree, "tools": TOOLS,
        "script_sha256": sha(__file__), **FALSE})
    if args.resume:
        require(read(output / "prepared-inputs.json") == prepared_wire, "resume typed inputs or producers changed")
    else:
        output.mkdir(parents=True)
        save(output / "prepared-inputs.json", prepared_wire)
    run_started = time.perf_counter()
    result = resume.run_resumable_native_validation(jobs, owner=resume.NativeValidationOwner.from_module(checks),
        output_directory=output / "validation", resume=args.resume, max_attempts_per_job=3,
        max_admission_seconds=300, retry_backoff_seconds=1, max_workers=2,
        native_memory_mb=1024, native_cpu_slots=2, native_child_process_slots=2,
        lease_wait_timeout_seconds=30, native_step_timeout_seconds=60,
        lake_executable=TOOLS["lake"][0], java_executable=TOOLS["java"][0], tla2tools_jar=TOOLS["tla2tools"][0])
    checked_seconds = time.perf_counter() - run_started
    gates = {}
    for row in result["live_jobs"]:
        probe = trainer.policy.evaluate_projection_training_batch([row["observation"]],
            domain_id=row["report"]["domain_id"], target_reports=[row["report"]])
        require(probe["strict_training_allowed"] is False, "partial fixture cannot qualify a modality")
        gates[row["job_id"]] = probe
    rows = [row["receipt"] for row in result["live_jobs"] + result["archived_jobs"]]
    loaded = {name: {"path": str(Path(module.__file__).resolve()), "sha256": sha(module.__file__)}
        for name, module in tuple(sys.modules.items()) if name.startswith("ipfs_datasets_py") and getattr(module, "__file__", None)}
    require(all(Path(row["path"]).is_relative_to(ROOT) for row in loaded.values()), "loaded module escaped pinned source tree")
    for row in loaded.values():
        pin(row["path"], row["sha256"])
    require(all(sha(path) == digest for path, digest in pins.items()), "input or loaded producer changed")
    prefix = "resume" if args.resume else "initial"
    save(output / (prefix + "-loaded-modules.json"), loaded)
    save(output / (prefix + "-input-provenance.json"), {"files": pins, "all_inputs_unchanged": True})
    save(output / (prefix + "-strict-gates.json"), gates)
    summary = {"schema": "bounded-ui-event-resume-regression/v1", "resume": args.resume,
        "attempt_count": len(attempts), "native_job_count": len(jobs), "preparation_blocks": 6,
        "live_job_count": len(result["live_jobs"]), "archived_job_count": len(result["archived_jobs"]),
        "native_lake_status_counts": dict(Counter(row.get("native", {}).get("execution", {}).get("status", "not_run") for row in rows)),
        "preparation_seconds": preparation_seconds, "validation_seconds": checked_seconds,
        "elapsed_seconds": time.perf_counter() - started, "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "rss_scope": "Python_process_only_excludes_native_children", "receipt": result["receipt"],
        "all_inputs_unchanged": True, "scope": "authored_bounded_EC_and_unchanged_prepared_native_targets", **FALSE}
    save(output / (prefix + "-summary.json"), summary)
    print(json.dumps({key: summary[key] for key in ("resume", "live_job_count", "archived_job_count",
        "native_lake_status_counts", "preparation_seconds", "validation_seconds", "elapsed_seconds")}), flush=True)


if __name__ == "__main__":
    main()
