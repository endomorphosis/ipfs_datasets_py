#!/usr/bin/env python3
"""Diagnostic coarse phase/GC profile of six frozen target-preparation inputs.

Run in a new Python process. This instruments the actual preparation entry
point, without loading model weights or running training. No GC policy, target
timeout, return value, or exception disposition is changed. Instrumentation
can still affect a wall-time timeout, so this is not native qualification or a
speed comparison. SIGALRM belongs exclusively to the existing target guard;
there is no signal sampler, background sampling thread, or cProfile hook.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import functools
import gc
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[3]
PRIOR = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan/target-hydration-gc-native-20260925.json"
PRIOR_SHA = "9af775375c4a297b7f2ce75db77c86ab2f989c32113e27ede6766464b8fae2f5"
BRIDGES = ("modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router")
PHASES = ("unattributed", "other_thread", "preparation", "source_binding", "sample_build",
          "bundle_writer", "target_generate", "timeout_guard", "multiview_evaluate",
          "adapter_evaluate", "merge_reports", "training_target", "loss_vector",
          "canonical_loss_vector", "bundle_validate", "bundle_encode", "bundle_json",
          "bundle_compress", "bundle_hash")


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def package_hashes():
    package = ROOT / "ipfs_datasets_py"
    result = {}
    for path in sorted(package.rglob("*.py")):
        if path.is_symlink() or package not in path.resolve().parents:
            raise ValueError("package source aliases another tree: " + str(path))
        if path.is_file():
            result[str(path.relative_to(ROOT))] = sha(path)
    return result


class PhaseObserver:
    """Bounded primitive telemetry; no sample, target, frame, or exception retention."""

    def __init__(self, max_calls=2048):
        self.owner_thread = threading.get_ident()
        self.max_calls = max_calls
        self.calls = []
        self.dropped_calls = 0
        self.stack = []
        self.sample_id = None
        self.phase_totals = {name: {"calls": 0, "inclusive_seconds": 0.0,
                                   "exclusive_seconds": 0.0, "raised_calls": 0} for name in PHASES}
        # Each generation row: collections, elapsed, collected, uncollectable.
        self.gc_by_phase = {name: [[0, 0.0, 0, 0] for _ in range(3)] for name in PHASES}
        self.gc_starts = [None, None, None]
        self.unmatched_gc_stops = 0
        self.cross_thread_phase_calls = 0
        self.gc_collection_counts = [0, 0, 0]
        self.gc_total_seconds = 0.0
        self.callbacks_restored = False
        self.generation_outcomes = []
        self.unsupported_generation_results = 0
        self.dropped_generation_outcomes = 0
        self.outcome_capture_seconds = 0.0

    def gc_callback(self, event, info):
        generation = info["generation"]
        if event == "start":
            name = (self.stack[-1][0] if self.stack else "unattributed")
            if threading.get_ident() != self.owner_thread:
                name = "other_thread"
            self.gc_starts[generation] = (time.perf_counter(), name)
        elif event == "stop":
            finished = time.perf_counter()
            started = self.gc_starts[generation]
            self.gc_starts[generation] = None
            if started is None:
                self.unmatched_gc_stops += 1
                return
            row = self.gc_by_phase[started[1]][generation]
            row[0] += 1
            row[1] += finished - started[0]
            row[2] += info.get("collected", 0)
            row[3] += info.get("uncollectable", 0)
            self.gc_collection_counts[generation] += 1
            self.gc_total_seconds += finished - started[0]

    @contextmanager
    def phase(self, name, detail=None):
        if threading.get_ident() != self.owner_thread:
            self.cross_thread_phase_calls += 1
            yield
            return
        frame = [name, time.perf_counter(), 0.0, self.gc_collection_counts.copy(), self.gc_total_seconds]
        self.stack.append(frame)
        error_type = None
        try:
            yield
        except BaseException as exc:
            error_type = type(exc).__module__ + "." + type(exc).__qualname__
            raise
        finally:
            elapsed = time.perf_counter() - frame[1]
            self.stack.pop()
            if self.stack:
                self.stack[-1][2] += elapsed
            exclusive = max(0.0, elapsed - frame[2])
            totals = self.phase_totals[name]
            totals["calls"] += 1
            totals["inclusive_seconds"] += elapsed
            totals["exclusive_seconds"] += exclusive
            totals["raised_calls"] += error_type is not None
            if len(self.calls) < self.max_calls:
                self.calls.append({"phase": name, "sample_id": self.sample_id, "detail": detail,
                                   "inclusive_seconds": elapsed, "exclusive_seconds": exclusive,
                                   "inclusive_gc_collections_by_generation": [
                                       after - before for before, after in zip(frame[3], self.gc_collection_counts)],
                                   "inclusive_gc_seconds": self.gc_total_seconds - frame[4],
                                   "raised_exception_type": error_type})
            else:
                self.dropped_calls += 1

    def to_dict(self):
        gc_rows = {
            name: [{"generation": i, "collections": row[0], "seconds": row[1],
                    "collected": row[2], "uncollectable": row[3]} for i, row in enumerate(rows)]
            for name, rows in self.gc_by_phase.items()
        }
        return {"phase_totals": self.phase_totals, "calls": self.calls,
                "max_retained_calls": self.max_calls, "dropped_calls": self.dropped_calls,
                "gc_by_deepest_phase": gc_rows,
                "gc_totals_by_generation": [
                    {"generation": i, **{key: sum(rows[i][key] for rows in gc_rows.values())
                                           for key in ("collections", "seconds", "collected", "uncollectable")}}
                    for i in range(3)],
                "unmatched_gc_stops": self.unmatched_gc_stops,
                "unclosed_gc_starts": sum(item is not None for item in self.gc_starts),
                "cross_thread_phase_calls": self.cross_thread_phase_calls,
                "generation_outcomes": self.generation_outcomes,
                "unsupported_generation_results": self.unsupported_generation_results,
                "dropped_generation_outcomes": self.dropped_generation_outcomes,
                "outcome_capture_seconds": self.outcome_capture_seconds,
                "outcome_capture_scope": "at most six detached status/bridge-telemetry results; capture occurs after target_generate timing; no target retained",
                "timing_scope": "inclusive phases overlap; exclusive subtracts direct instrumented children only",
                "gc_scope": "callback start-to-stop wall duration attributed once to the deepest active phase",
                "gc_callback_overhead_calibrated": False}


@contextmanager
def instrument(observer):
    from ipfs_datasets_py.logic import bridge
    from ipfs_datasets_py.logic.bridge import multiview
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        autoencoder_target_preparation as preparation, legal_ir_target_bundle as bundle,
        legal_samples, modal_autoencoder,
    )

    replacements = []

    def replace(owner, name, replacement):
        replacements.append((owner, name, getattr(owner, name)))
        setattr(owner, name, replacement)

    def wrap(owner, name, phase, detail=None):
        original = getattr(owner, name)

        @functools.wraps(original)
        def wrapped(*args, **kwargs):
            label = detail(args, kwargs) if detail else None
            with observer.phase(phase, label):
                return original(*args, **kwargs)

        replace(owner, name, wrapped)
        return wrapped

    original_bounded = preparation._bounded_target_results

    def bounded(generate, samples, workers):
        def measured_generate(sample):
            previous = observer.sample_id
            observer.sample_id = sample.sample_id
            try:
                with observer.phase("target_generate"):
                    result = generate(sample)
                started = time.perf_counter()
                if (type(result) is not tuple or len(result) != 4 or type(result[0]) is not str
                        or type(result[2]) is not str or type(result[3]) is not dict):
                    # Preserve the result unchanged; mark this observation
                    # unsupported instead of inspecting arbitrary objects.
                    observer.unsupported_generation_results += 1
                elif len(observer.generation_outcomes) >= 6:
                    observer.dropped_generation_outcomes += 1
                else:
                    observer.generation_outcomes.append({"sample_id": result[0], "status": result[2],
                        "bridge_report_telemetry": copy.deepcopy(result[3])})
                observer.outcome_capture_seconds += time.perf_counter() - started
                return result
            finally:
                observer.sample_id = previous
        return original_bounded(measured_generate, samples, workers)

    callbacks_before = list(gc.callbacks)
    callback = observer.gc_callback
    try:
        replace(preparation, "_bounded_target_results", bounded)
        wrap(preparation, "target_snapshot_config", "source_binding")
        wrap(legal_samples, "build_us_code_sample", "sample_build")
        wrap(modal_autoencoder, "_evaluate_legal_ir_multiview_with_timeout", "timeout_guard")
        evaluate = wrap(multiview, "evaluate_legal_ir_multiview", "multiview_evaluate")
        replace(bridge, "evaluate_legal_ir_multiview", evaluate)
        wrap(multiview, "_evaluate_adapter", "adapter_evaluate",
             lambda args, kwargs: type(args[0]).__module__ + "." + type(args[0]).__qualname__)
        wrap(multiview, "_merge_reports_to_document", "merge_reports")
        for name in ("training_target", "loss_vector", "canonical_loss_vector"):
            wrap(multiview.MultiViewLegalIRReport, name, name)
        wrap(bundle, "write_target_bundle", "bundle_writer")
        for name, phase in (("_validate_target", "bundle_validate"), ("_encode", "bundle_encode"),
                            ("_json", "bundle_json"), ("_sha", "bundle_hash")):
            # Bundle aliases enter once per object; recursive snapshot internals
            # retain their original globals and are deliberately not wrapped.
            wrap(bundle, name, phase)
        original_zlib = bundle.zlib

        class ZlibView:
            def __getattr__(self, name):
                return getattr(original_zlib, name)

            def compress(self, *args, **kwargs):
                with observer.phase("bundle_compress"):
                    return original_zlib.compress(*args, **kwargs)

        replace(bundle, "zlib", ZlibView())
        gc.callbacks.append(callback)
        yield
    finally:
        gc.callbacks[:] = [item for item in gc.callbacks if item is not callback]
        for owner, name, original in reversed(replacements):
            setattr(owner, name, original)
        observer.callbacks_restored = gc.callbacks == callbacks_before


def run(args, result):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import prepare_training_targets
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
        SampleRecord, TrainingConfig, TrainingJobSpec, verify_corpus_job_inputs,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal

    if sha(args.parent_receipt) != args.parent_sha256:
        raise ValueError("frozen parent receipt changed")
    parent = json.loads(args.parent_receipt.read_bytes())
    if parent["passed"] is not True:
        raise ValueError("parent native receipt did not pass")
    worker = parent["runs"][0]["worker"]
    payload = worker["job_spec"]
    spec = TrainingJobSpec.from_dict(payload)
    if spec.canonical_sha256 != worker["job_spec_canonical_sha256"]:
        raise ValueError("parent job specification identity differs")
    train, validation = parent["ordered_training_samples"], parent["ordered_validation_samples"]
    if train != payload["samples"] or validation != payload["validation_samples"] or len(train) != 3 or len(validation) != 3:
        raise ValueError("exact frozen three training plus three validation samples required")
    config = TrainingConfig.from_dict(parent["effective_training_config"])
    if (tuple(config.legal_ir_bridge_names) != BRIDGES or config.legal_ir_evaluate_provers is not False
            or config.legal_ir_parallel_workers != 1 or config.metric_disk_cache != 0
            or config.use_sample_memory is not False):
        raise ValueError("parent preparation configuration differs from diagnostic scope")
    tree = require_workspace_logic_tree()
    if any(ROOT not in Path(path).resolve().parents for path in tree.values()):
        raise ValueError("logic tree is not the canonical workspace")
    result.update(canonical_tree=tree, parent_job_spec_canonical_sha256=spec.canonical_sha256,
                  input_verification=verify_corpus_job_inputs(spec), selection=parent["selection"],
                  ordered_training_samples=train, ordered_validation_samples=validation,
                  effective_training_config=parent["effective_training_config"],
                  base_checkpoint_loaded=False,
                  timeout_seconds=modal._legal_ir_target_timeout_seconds(),
                  timeout_guard_enabled=modal._legal_ir_target_timeout_enabled(modal._legal_ir_target_timeout_seconds()))
    if not result["timeout_guard_enabled"] or threading.active_count() != 1:
        raise ValueError("diagnostic requires the unchanged main-thread timeout and one Python thread")
    rows = [SampleRecord.from_dict(row) for row in train]
    validation_rows = [SampleRecord.from_dict(row) for row in validation]
    observer = PhaseObserver()
    before = {"enabled": gc.isenabled(), "threshold": list(gc.get_threshold()),
              "debug": gc.get_debug(), "callback_count": len(gc.callbacks), "stats": gc.get_stats()}
    handler, timer = signal.getsignal(signal.SIGALRM), signal.getitimer(signal.ITIMER_REAL)
    if timer != (0.0, 0.0):
        raise ValueError("diagnostic must not compete with a pre-existing real-time timer")
    result["gc_before"] = before
    try:
        with instrument(observer), observer.phase("preparation"):
            prepared = prepare_training_targets(rows, args.directory / "targets.bundle",
                validation_records=validation_rows, training_config=config, artifact_format="bundle")
        result["target_preparation"] = prepared
        write(args.directory / "target-preparation.json", prepared)
        expected = set(prepared["statuses"])
        result["six_targets_observed"] = (prepared["sample_count"] == 6
            and prepared["legal_ir_target_count"] == 6 and len(expected) == 6
            and set(prepared["bridge_report_telemetry"]) == expected)
        result["failure_disposition_policy"] = "retain every ready/timeout/partial outcome; no reselection or retry"
    finally:
        result["observations"] = observer.to_dict()
        result["gc_after"] = {"enabled": gc.isenabled(), "threshold": list(gc.get_threshold()),
                              "debug": gc.get_debug(), "callback_count": len(gc.callbacks), "stats": gc.get_stats()}
        result["gc_policy_restored"] = (all(result["gc_after"][key] == before[key]
            for key in ("enabled", "threshold", "debug", "callback_count")) and observer.callbacks_restored)
        result["timeout_state_restored"] = (signal.getsignal(signal.SIGALRM) is handler
                                             and signal.getitimer(signal.ITIMER_REAL) == timer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent-receipt", type=Path, default=PRIOR)
    parser.add_argument("--parent-sha256", default=PRIOR_SHA)
    args = parser.parse_args()
    if args.directory.exists() or args.output.exists():
        parser.error("use new diagnostic directory and output paths")
    args.directory = args.directory.resolve()
    args.directory.mkdir(parents=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    environment = {"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA": "0", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
        "IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    os.environ.update(environment)
    result = {"schema": "cold-target-preparation-phase-profile-v1", "diagnostic_only": True,
        "native_qualification": False, "wall_speed_claim": False, "admitted": False, "formalized": False,
        "owner_dispatch_performed": False, "training_performed": False, "weights_loaded": False,
        "weights_downloaded": False, "promotion_performed": False, "publication_performed": False,
        "gc_policy_changed": False, "signal_profiler_used": False, "cprofile_used": False,
        "environment_settings": environment,
        "adapter_workers_note": "explicitly 1 here; an unset native adapter-worker setting also resolves to 1; environment identities differ",
        "cold_scope": "fresh process with no prior target generation; imports/input verification precede phase observation; OS caches uncontrolled",
        "timeout_observer_effect": "coarse wrappers and GC callbacks add overhead; timeout and partial bridge outcomes may change",
        "parent_receipt": {"path": str(args.parent_receipt.resolve()), "sha256": args.parent_sha256},
        "profile_script_sha256": sha(__file__), "passed": False,
        "recorded_at": datetime.now(timezone.utc).isoformat()}
    result["package_source_hashes_before"] = package_hashes()
    try:
        run(args, result)
    except BaseException as exc:
        result["error"] = {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)}
    finally:
        result["package_source_hashes_after"] = package_hashes()
        before, after = result["package_source_hashes_before"], result["package_source_hashes_after"]
        result["package_source_changes"] = {name: {"before": before.get(name), "after": after.get(name)}
            for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)}
        result["source_unchanged"] = not result["package_source_changes"]
        result["script_unchanged"] = result["profile_script_sha256"] == sha(__file__)
        result["passed"] = ("error" not in result and result["source_unchanged"] and result["script_unchanged"]
            and result.get("six_targets_observed", False) and result.get("gc_policy_restored", False)
            and result.get("timeout_state_restored", False)
            and not result.get("observations", {}).get("unsupported_generation_results", 0)
            and not result.get("observations", {}).get("dropped_generation_outcomes", 0))
        result["pass_scope"] = "diagnostic execution/provenance integrity only; bridge success and native qualification not implied"
        write(args.output, result)
    print(json.dumps({"receipt": str(args.output), "passed": result["passed"], "error": result.get("error")}), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
