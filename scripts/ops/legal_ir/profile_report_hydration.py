#!/usr/bin/env python3
"""Forensic hydration profile of one historical sealed report, never training.

The recorded producer configuration is accepted only by the low-level artifact
decoder for this inspection. The unchanged native daemon session must reject
that stale configuration. No bridges, evaluator, model or checkpoint are run.
"""
from __future__ import annotations

import argparse
import cProfile
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
HARNESS_PATH = Path(__file__).with_name("benchmark_daemon_shared_reports.py")
HARNESS_SHA = "9a6643f10da541173c465ed502a724ffa58804d9a85aa15642d75735ce288c53"
if hashlib.sha256(HARNESS_PATH.read_bytes()).hexdigest() != HARNESS_SHA:
    raise RuntimeError("frozen report benchmark changed")
import benchmark_daemon_shared_reports as frozen

base = frozen.base
R3 = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan/daemon-shared-report-native-20260925-r3.json"
R3_SHA = "3114a63d34a9b949659ff7e70af19e93f92ece76d551a539c8e498770dcaf02b"
SAMPLE_ID = "us-code-22-4021a-fce42ca5c6a35f9d"
ARTIFACT_SHA = "ade32159e43d4c9c7ba0af54f22920e3c1981f97fe47851911755a7e4da2c52c"
ARTIFACT_BYTES = 16237649
MAX_CHILD_SECONDS = 180
CRITICAL_SOURCES = (
    "optimizers/logic_theorem_optimizer/legal_ir_report_bundle.py",
    "optimizers/logic_theorem_optimizer/legal_ir_target_bundle.py",
    "optimizers/logic_theorem_optimizer/legal_ir_target_snapshot.py",
    "logic/bridge/multiview.py", "logic/bridge/types.py",
)


def source_manifest():
    root = ROOT / "ipfs_datasets_py"
    return {p.relative_to(root).as_posix(): base.sha(p) for p in sorted(root.rglob("*.py")) if p.is_file()}


def differences(before, after):
    return [{"path": key, "historical_sha256": before.get(key), "current_sha256": after.get(key)}
            for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)]


def profile_call(name, function, directory, result):
    profile = cProfile.Profile()
    started = time.perf_counter()
    error = None
    try:
        profile.enable()
        return function()
    except BaseException as exc:
        error = {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)[:4096]}
        raise
    finally:
        profile.disable()
        elapsed = time.perf_counter() - started
        path = directory / (name + ".pstats")
        if path.exists():
            raise FileExistsError(path)
        profile.dump_stats(str(path))
        rows = [{"file": key[0], "line": key[1], "function": key[2], "primitive_calls": value[0],
                 "calls": value[1], "self_seconds": value[2], "cumulative_seconds": value[3]}
                for key, value in profile.stats.items()]
        selected = {"_json", "_parse", "_node_limits", "_validated_target", "report_from_bytes",
                    "report_to_bytes", "_expand_positional", "_native_fields", "_encode", "_decode"}
        result["profiles"][name] = {"wall_seconds_with_cprofile": elapsed, "error": error,
            "pstats": base.descriptor(path), "function_entry_count": len(rows),
            "total_calls": sum(row["calls"] for row in rows),
            "top_cumulative": sorted(rows, key=lambda row: row["cumulative_seconds"], reverse=True)[:50],
            "top_self": sorted(rows, key=lambda row: row["self_seconds"], reverse=True)[:40],
            "selected_functions": [row for row in rows if row["function"] in selected]}


def forensic_child(directory, result):
    from audit_native_uscode_embedding_production import _deny_network
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_report_session import DaemonReportDescriptor, VerifiedDaemonReportSession
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, verify_corpus_job_inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig, TargetSnapshotError
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_report_bundle as codec
    result["network_guard"] = _deny_network()
    result["tree_pin"] = require_workspace_logic_tree()
    if base.sha(R3) != R3_SHA:
        raise ValueError("historical failed receipt changed")
    prior = base.read(R3)
    result["historical_receipt"] = {"path": str(R3), "sha256": R3_SHA, "native_run_passed": prior["passed"]}
    historical = prior["config_before"]
    current = source_manifest()
    result["current_code_sha256_before"] = current
    result["historical_source_differences"] = differences(historical["code_sha256"], current)
    result["historical_producer_is_stale"] = bool(result["historical_source_differences"])
    if not result["historical_producer_is_stale"]:
        raise ValueError("expected stale historical producer configuration")
    result["critical_decoder_sources_match_historical"] = all(current.get(name) == historical["code_sha256"].get(name) for name in CRITICAL_SOURCES)
    if not result["critical_decoder_sources_match_historical"]:
        raise ValueError("codec/native class source changed since the historical artifact")
    prep = prior["preparation"]["result"]
    prepared, artifact = prep["prepared"], prep["prepared"]["artifact"]
    if artifact["sha256"] != ARTIFACT_SHA or artifact["bytes"] != ARTIFACT_BYTES:
        raise ValueError("unexpected historical report artifact")
    helper = base.dependencies()
    helper.verify_descriptor(artifact)
    spec_ref = prior["preparation"]["spec_artifact"]
    helper.verify_descriptor(spec_ref)
    payload = base.read(spec_ref["path"])["payload"]
    job = TrainingJobSpec.from_dict(payload)
    result["input_verification"] = verify_corpus_job_inputs(job)
    _, _, samples = base.fixture(payload)
    sample = next(row for row in samples if row.sample_id == SAMPLE_ID)
    expected = prep["native_report_evidence"][SAMPLE_ID]
    result["expected_exact_identities"] = expected
    result["artifact"] = artifact
    descriptor = DaemonReportDescriptor(artifact["path"], artifact["sha256"], artifact["bytes"], prepared["report_snapshot_id"])
    # Exercise the ordinary guard. Historical decoding below never changes it.
    try:
        session = VerifiedDaemonReportSession(descriptor, bridge_names=base.BRIDGES, evaluate_provers=False, parallel_workers=1)
    except TargetSnapshotError as exc:
        result["current_native_session_rejection"] = {"type": type(exc).__name__, "message": str(exc)}
        if str(exc) != "report configuration/provenance mismatch":
            raise
    else:
        session.close()
        raise ValueError("current native session unexpectedly accepted stale producer")
    config = TargetSnapshotConfig.from_dict(historical)
    bundle = codec.load_report_bundle(artifact["path"], expected_sha256=ARTIFACT_SHA,
        expected_size_bytes=ARTIFACT_BYTES, config=config)
    try:
        result["selection_metadata"] = bundle.selection_metadata([sample], config=config)
        selection = profile_call("selection_for", lambda: bundle.selection_for([sample], config=config), directory, result)
        report, target = selection.reports[SAMPLE_ID], selection.targets[SAMPLE_ID]
        result["target_shares_report_document"] = target.document is report.document
        def wire_identity():
            raw = codec.report_to_bytes(report)
            return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        result["rehydrated_wire"] = profile_call("report_reencoding", wire_identity, directory, result)
        result["rehydrated_target"] = profile_call("derived_target_identity", lambda: frozen.target_fingerprint(target), directory, result)
        result["independent_native_fingerprint"] = profile_call("native_field_fingerprint", lambda: frozen.native_fingerprint(report), directory, result)
        result["checks"] = {
            "wire_exact": result["rehydrated_wire"] == {"sha256": expected["report_dag_sha256"], "bytes": expected["report_dag_bytes"]},
            "target_exact": result["rehydrated_target"] == expected["derived_target"],
            "native_fields_types_order_aliases_exact": result["independent_native_fingerprint"] == expected["independent_native_fingerprint"],
            "one_report_only": bundle.statistics["decompressed_shards"] == 1,
            "shared_document": result["target_shares_report_document"],
        }
        result["artifact_verification_after"] = bundle.verify_unchanged()
        result["bundle_statistics"] = bundle.statistics
        result["passed"] = all(result["checks"].values())
    finally:
        bundle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    os.environ.update(base.ENVIRONMENT)
    directory, output = args.directory.resolve(), args.output.resolve()
    if output.exists() or ROOT not in directory.parents:
        parser.error("new output under canonical diagnostic workspace required")
    result = {"schema": "historical-single-report-hydration-profile-v1", "passed": False, "profiles": {},
        "recorded_at": datetime.now(timezone.utc).isoformat(), "harness_sha256": base.sha(__file__),
        "historical_producer_config_usage": "forensic low-level artifact decoding only; current native session rejects",
        "production_guard_bypassed_or_modified": False, "generation_performed": False, "score_or_training_performed": False,
        "model_or_checkpoint_loaded": False, "artifact_rewritten": False, "admitted": False,
        "native_daemon_qualified": False, "speed_claim": False, "sample_id": SAMPLE_ID,
        "outer_child_timeout_seconds": MAX_CHILD_SECONDS,
        "profile_scope": "cProfile attribution; wall times include instrumentation and are not native performance measurements"}
    started = time.perf_counter()
    try:
        if args.child:
            forensic_child(directory, result)
        else:
            if directory.exists():
                raise ValueError("fresh forensic output directory required")
            directory.mkdir(parents=True)
            with (directory / "profile_report_hydration.py").open("xb") as handle:
                handle.write(Path(__file__).read_bytes())
            child_output, log_path = directory / "child.json", directory / "process.log"
            with log_path.open("xb") as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", "--directory", str(directory), "--output", str(child_output)],
                    cwd=ROOT, env=dict(os.environ), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    result["child_exit"] = process.wait(timeout=MAX_CHILD_SECONDS)
                    result["outer_timeout"] = False
                except subprocess.TimeoutExpired:
                    result["outer_timeout"] = True
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        result["child_exit"] = process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        result["child_exit"] = process.wait()
            result["child"] = base.read(child_output) if child_output.exists() else {"passed": False, "error": {"type": "MissingChildReceipt"}}
            result["process_log"] = base.descriptor(log_path)
            result["child_receipt"] = base.descriptor(child_output) if child_output.exists() else None
            result["passed"] = result["child"].get("passed") is True and result["child_exit"] == 0 and not result["outer_timeout"]
    except BaseException as exc:
        result["error"] = {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)[:4096]}
    finally:
        if args.child and "current_code_sha256_before" in result:
            try:
                after = source_manifest()
                result["source_changes_during_profile"] = differences(result["current_code_sha256_before"], after)
                result["source_unchanged_during_profile"] = not result["source_changes_during_profile"]
                result["passed"] = result["passed"] and result["source_unchanged_during_profile"]
            except BaseException as exc:
                result["final_source_guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:4096]}
                result["passed"] = False
        result["elapsed_seconds"] = time.perf_counter() - started
        result["harness_unchanged"] = base.sha(__file__) == result["harness_sha256"] and base.sha(HARNESS_PATH) == HARNESS_SHA
        result["passed"] = result["passed"] and result["harness_unchanged"] and "error" not in result
        base.write(output, result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
