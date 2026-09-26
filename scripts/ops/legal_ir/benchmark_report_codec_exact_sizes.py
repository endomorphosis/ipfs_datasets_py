#!/usr/bin/env python3
"""Unprofiled forensic comparison of original and optimized report codecs.

Four fresh processes use one historical sealed report in original/optimized/
optimized/original order. Only the low-level decoder receives the recorded
historical configuration. The unchanged current native session must reject it.
No bridge generation, evaluation, model, checkpoint load or training occurs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import importlib.util
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
PROFILE_PATH = Path(__file__).with_name("profile_report_hydration.py")
PROFILE_SHA = "180ba84c1bf509e098281bd5ff867dd3240a0f871dc2819b584dbc99b6b4b719"
if hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest() != PROFILE_SHA:
    raise RuntimeError("frozen forensic profile changed")
import profile_report_hydration as forensic

base, frozen = forensic.base, forensic.frozen
ORIGINAL_SHA = "0e86cccef95373ed19329fd27b77a7fda106bcb6e5561f17c63e66f429c17059"
CODEC_PATH = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_report_bundle.py"
ARM_ORDER = ("original", "optimized", "optimized", "original")
MAX_CHILD_SECONDS = 180


def error_record(exc):
    return {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)[:4096]}


def observed_runtime():
    return {"memory": base.memory_observation(), "gc_enabled": gc.isenabled(),
            "gc_threshold": list(gc.get_threshold()), "gc_count": list(gc.get_count()),
            "gc_stats": gc.get_stats(), "gc_debug": gc.get_debug(), "gc_callbacks": len(gc.callbacks)}


def timed(name, function, result):
    started = time.perf_counter()
    try:
        return function()
    finally:
        result["timings"][name] = time.perf_counter() - started


def original_module(archive):
    """Separate module identity; never replace any canonical production binding."""
    if base.sha(archive) != ORIGINAL_SHA:
        raise ValueError("original codec archive differs")
    name = "ipfs_datasets_py.optimizers.logic_theorem_optimizer._diagnostic_original_report_codec"
    if name in sys.modules:
        raise ValueError("original codec diagnostic module already loaded")
    spec = importlib.util.spec_from_file_location(name, archive)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def save_manifest(directory, name):
    manifest = forensic.source_manifest()
    path = directory / (name + ".json")
    base.write(path, manifest)
    return manifest, base.descriptor(path)


def child_run(common, arm, directory, result):
    from audit_native_uscode_embedding_production import _deny_network
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_report_session import DaemonReportDescriptor, VerifiedDaemonReportSession
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, verify_corpus_job_inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig, TargetSnapshotError
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_report_bundle as canonical_codec
    result["network_guard"] = _deny_network()
    result["tree_pin"] = require_workspace_logic_tree()
    helper = base.dependencies()
    helper.verify_descriptor(common["source_manifest_before"])
    expected_sources = base.read(common["source_manifest_before"]["path"])
    before, result["source_manifest_before"] = save_manifest(directory, "source-before")
    if before != expected_sources or base.sha(CODEC_PATH) != common["candidate_sha256"]:
        raise ValueError("current package changed before arm")
    result["current_native_codec_file"] = str(Path(canonical_codec.__file__).resolve())
    if Path(canonical_codec.__file__).resolve() != CODEC_PATH:
        raise ValueError("canonical decoder resolves outside checkout")
    try:
        for ref in common["code_archives"].values():
            helper.verify_descriptor(ref)
        if base.sha(forensic.R3) != forensic.R3_SHA:
            raise ValueError("historical failed receipt changed")
        prior = base.read(forensic.R3)
        historical = prior["config_before"]
        result["historical_source_differences"] = forensic.differences(historical["code_sha256"], before)
        result["historical_producer_stale"] = bool(result["historical_source_differences"])
        unchanged_dependencies = [name for name in forensic.CRITICAL_SOURCES if name != "optimizers/logic_theorem_optimizer/legal_ir_report_bundle.py"]
        if not result["historical_producer_stale"] or any(before.get(name) != historical["code_sha256"].get(name) for name in unchanged_dependencies):
            raise ValueError("historical native class/decoder dependencies changed")
        result["native_class_dependency_hashes"] = {name: before[name] for name in unchanged_dependencies}
        prepared = prior["preparation"]["result"]["prepared"]
        artifact = prepared["artifact"]
        if artifact["sha256"] != forensic.ARTIFACT_SHA or artifact["bytes"] != forensic.ARTIFACT_BYTES:
            raise ValueError("unexpected historical report artifact")
        helper.verify_descriptor(artifact)
        helper.verify_descriptor(prior["preparation"]["spec_artifact"])
        payload = base.read(prior["preparation"]["spec_artifact"]["path"])["payload"]
        result["input_verification"] = verify_corpus_job_inputs(TrainingJobSpec.from_dict(payload))
        _, _, samples = base.fixture(payload)
        sample = next(row for row in samples if row.sample_id == forensic.SAMPLE_ID)
        expected = prior["preparation"]["result"]["native_report_evidence"][forensic.SAMPLE_ID]
        result["artifact"], result["expected_identities"] = artifact, expected
        descriptor = DaemonReportDescriptor(artifact["path"], artifact["sha256"], artifact["bytes"], prepared["report_snapshot_id"])
        try:
            session = VerifiedDaemonReportSession(descriptor, bridge_names=base.BRIDGES, evaluate_provers=False, parallel_workers=1)
        except TargetSnapshotError as exc:
            result["current_native_session_rejection"] = error_record(exc)
            if str(exc) != "report configuration/provenance mismatch":
                raise
        else:
            session.close()
            raise ValueError("normal session unexpectedly accepted stale artifact")
        if arm == "original":
            codec = original_module(common["code_archives"]["original"]["path"])
        elif arm == "optimized":
            codec = canonical_codec
        else:
            raise ValueError("unknown diagnostic arm")
        result["executed_codec"] = {"module": codec.__name__, "path": str(Path(codec.__file__).resolve()),
            "sha256": base.sha(codec.__file__), "canonical_production_module_replaced": False}
        config = TargetSnapshotConfig.from_dict(historical)
        result["before_load"] = observed_runtime()
        bundle = timed("load_seconds", lambda: codec.load_report_bundle(artifact["path"], expected_sha256=forensic.ARTIFACT_SHA,
            expected_size_bytes=forensic.ARTIFACT_BYTES, config=config), result)
        try:
            result["before_selection"] = observed_runtime()
            selection = timed("selection_seconds", lambda: bundle.selection_for([sample], config=config), result)
            result["after_selection"] = observed_runtime()
            report, target = selection.reports[sample.sample_id], selection.targets[sample.sample_id]
            raw = timed("encode_seconds", lambda: codec.report_to_bytes(report), result)
            result["after_encode_before_audit"] = observed_runtime()
            started = time.perf_counter()
            try:
                result["actual_wire"] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                del raw
                result["actual_target"] = frozen.target_fingerprint(target)
                result["actual_native_fields"] = frozen.native_fingerprint(report)
                result["checks"] = {
                    "wire_exact": result["actual_wire"] == {"sha256": expected["report_dag_sha256"], "bytes": expected["report_dag_bytes"]},
                    "target_exact": result["actual_target"] == expected["derived_target"],
                    "all_native_fields_types_order_aliases_exact": result["actual_native_fields"] == expected["independent_native_fingerprint"],
                    "one_shard_only": bundle.statistics["decompressed_shards"] == 1,
                    "document_shared": target.document is report.document,
                    "canonical_module_unchanged": sys.modules[canonical_codec.__name__] is canonical_codec,
                }
                result["artifact_verification_after"] = bundle.verify_unchanged()
                result["bundle_statistics"] = bundle.statistics
            finally:
                result["audit_seconds_outside_operation_timers"] = time.perf_counter() - started
            result["passed"] = all(result["checks"].values())
        finally:
            bundle.close()
    finally:
        after, result["source_manifest_after"] = save_manifest(directory, "source-after")
        result["source_changes_during_arm"] = forensic.differences(before, after)
        result["source_unchanged_during_arm"] = before == after == expected_sources
        result["checkpoint_source_unchanged"] = base.sha(helper.PINNED) == helper.PINNED_SHA
        result["archives_unchanged"] = all(base.sha(ref["path"]) == ref["sha256"] for ref in common["code_archives"].values())
        result["passed"] = result["passed"] and result["source_unchanged_during_arm"] and result["checkpoint_source_unchanged"] and result["archives_unchanged"]


def run_child(directory, arm, common_path):
    directory.mkdir()
    output, log_path = directory / "receipt.json", directory / "process.log"
    started, timed_out = time.perf_counter(), False
    with log_path.open("xb") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", "--arm", arm,
            "--common", str(common_path), "--directory", str(directory), "--output", str(output)],
            cwd=ROOT, env=dict(os.environ), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            exit_code = process.wait(timeout=MAX_CHILD_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                exit_code = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                exit_code = process.wait()
    result = base.read(output) if output.exists() else {"passed": False, "error": {"type": "MissingChildReceipt"}}
    return {"arm": arm, "exit_code": exit_code, "outer_timeout": timed_out,
            "process_seconds_including_audit_guards_shutdown": time.perf_counter() - started,
            "receipt": base.descriptor(output) if output.exists() else None,
            "process_log": base.descriptor(log_path), "result": result}


def parent_run(args, directory, result):
    if directory.exists():
        raise ValueError("fresh diagnostic directory required")
    if args.original_code is None or args.candidate_sha256 is None:
        raise ValueError("original archive and exact candidate SHA required")
    if base.sha(args.original_code) != ORIGINAL_SHA or base.sha(CODEC_PATH) != args.candidate_sha256:
        raise ValueError("original/candidate source identity differs")
    directory.mkdir(parents=True)
    with (directory / "benchmark_report_codec_exact_sizes.py").open("xb") as handle:
        handle.write(Path(__file__).read_bytes())
    before, result["source_manifest_before"] = save_manifest(directory, "source-before")
    result["runs"] = []
    try:
        archives = {}
        for arm, source in (("original", args.original_code), ("optimized", CODEC_PATH)):
            destination = directory / (arm + "-legal_ir_report_bundle.py")
            with destination.open("xb") as handle:
                handle.write(Path(source).read_bytes())
            archives[arm] = base.descriptor(destination)
        result["code_archives"] = archives
        common = {"source_manifest_before": result["source_manifest_before"], "code_archives": archives,
                  "candidate_sha256": args.candidate_sha256}
        common_path = directory / "common.json"
        base.write(common_path, common)
        result["common_artifact"] = base.descriptor(common_path)
        for index, arm in enumerate(ARM_ORDER):
            row = run_child(directory / (str(index) + "-" + arm), arm, common_path)
            result["runs"].append(row)
            if row["exit_code"] or row["outer_timeout"] or row["result"].get("passed") is not True:
                raise ValueError("diagnostic arm failed; no retry")
        result["paired_comparison"] = []
        for baseline, optimized in ((0, 1), (3, 2)):
            a, b = result["runs"][baseline]["result"], result["runs"][optimized]["result"]
            result["paired_comparison"].append({"original_ordinal": baseline, "optimized_ordinal": optimized,
                "timings": {key: {"original": a["timings"][key], "optimized": b["timings"][key],
                    "original_minus_optimized_seconds": a["timings"][key] - b["timings"][key]}
                    for key in ("load_seconds", "selection_seconds", "encode_seconds")}})
        result["median_operation_seconds"] = {arm: {key: statistics.median(row["result"]["timings"][key]
            for row in result["runs"] if row["arm"] == arm) for key in ("load_seconds", "selection_seconds", "encode_seconds")}
            for arm in ("original", "optimized")}
        result["passed"] = True
    finally:
        after, result["source_manifest_after"] = save_manifest(directory, "source-after")
        result["source_changes_during_comparison"] = forensic.differences(before, after)
        result["source_unchanged_during_comparison"] = before == after
        helper = base.dependencies()
        result["checkpoint_source_unchanged"] = base.sha(helper.PINNED) == helper.PINNED_SHA
        ref = result.get("common_artifact")
        result["common_artifact_unchanged"] = bool(ref) and Path(ref["path"]).stat().st_size == ref["bytes"] and base.sha(ref["path"]) == ref["sha256"]
        archives = result.get("code_archives", {})
        result["code_archives_unchanged"] = set(archives) == {"original", "optimized"} and all(
            Path(ref["path"]).stat().st_size == ref["bytes"] and base.sha(ref["path"]) == ref["sha256"]
            for ref in archives.values())
        result["passed"] = (result["passed"] and result["source_unchanged_during_comparison"]
            and result["checkpoint_source_unchanged"] and result["common_artifact_unchanged"] and result["code_archives_unchanged"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--original-code", type=Path)
    parser.add_argument("--candidate-sha256")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--arm", choices=("original", "optimized"))
    parser.add_argument("--common", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    os.environ.update(base.ENVIRONMENT)
    directory, output = args.directory.resolve(), args.output.resolve()
    if output.exists() or ROOT not in directory.parents:
        parser.error("new output under canonical workspace required")
    result = {"schema": "same-artifact-report-codec-comparison-v1", "passed": False, "timings": {},
        "recorded_at": datetime.now(timezone.utc).isoformat(), "harness_sha256": base.sha(__file__),
        "frozen_dependency": {"path": str(PROFILE_PATH), "sha256": PROFILE_SHA}, "environment": base.ENVIRONMENT,
        "sample_id": forensic.SAMPLE_ID, "arm": args.arm, "arm_order": list(ARM_ORDER),
        "historical_artifact": {"sha256": forensic.ARTIFACT_SHA, "bytes": forensic.ARTIFACT_BYTES},
        "historical_bridge_names": base.BRIDGES, "historical_evaluate_provers": False,
        "historical_parallel_workers": 1, "historical_metric_disk_cache": 0,
        "bridge_on_evaluation_ran": False, "generation_or_training_performed": False,
        "model_or_checkpoint_loaded": False, "admitted": False, "production_guard_bypassed_or_modified": False,
        "native_daemon_qualified": False, "automatic_retry": False, "gc_policy_changed": False,
        "cache_scope": "fresh process per arm; no memo carryover across operations; OS caches uncontrolled and artifact read by guards before timing",
        "original_alias_scope": "original arm imports an additional archived codec module; its allocations are reflected in GC and memory observations",
        "timing_scope": "unprofiled native low-level load/selection/encoding only; imports, guards, memory observations and integrity audit excluded",
        "qualification_scope": "forensic same-artifact codec comparison; stale current session must reject; no end-to-end daemon speed inference",
        "outer_child_timeout_seconds": MAX_CHILD_SECONDS}
    started = time.perf_counter()
    try:
        if args.child:
            if args.arm is None or args.common is None:
                raise ValueError("child arm/common descriptor required")
            child_run(base.read(args.common), args.arm, directory, result)
        else:
            parent_run(args, directory, result)
    except BaseException as exc:
        result["error"] = error_record(exc)
    finally:
        result["elapsed_seconds"] = time.perf_counter() - started
        result["harness_unchanged"] = base.sha(__file__) == result["harness_sha256"] and base.sha(PROFILE_PATH) == PROFILE_SHA
        result["passed"] = result["passed"] and result["harness_unchanged"] and "error" not in result
        base.write(output, result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
