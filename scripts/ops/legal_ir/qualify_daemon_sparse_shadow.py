#!/usr/bin/env python3
"""Bounded offline reconstruction of two historical full checkpoint pairs.

The unchanged owner candidate and the archived in-sample accepted update are
distinct evidence cases. No training, bridge evaluation, owner operation or
checkpoint promotion occurs. Failed attempts are retained and never retried.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
OWNER_HELPER = Path(__file__).with_name("qualify_owned_daemon_invocation.py")
OWNER_HELPER_SHA = "c54b99391e7dfdf9515ebd9ced4fa917f6a49efc1f86dbe254a632ef30c0e350"
EVIDENCE = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan"
NATIVE_RECEIPT = EVIDENCE / "owned-daemon-invocation-native-20260925-r2.json"
NATIVE_SHA = "0c7b84a8cd11dc9f181c68d2124786b020edaff990a5565dfa3e54c8fdc7863f"
NATIVE_BYTES = 4_371_004
ACCEPTED_STATE = ROOT / "workspace/todo-queues/restart12-bridge-on-one-step.state.json"
ACCEPTED_SHA = "23fa2a50725fa5afe3f96da9ae84ea686df5fb49262aa1b6614321023a91799c"
ACCEPTED_BYTES = 25_895_897
ACCEPTED_RECEIPT = ROOT / "workspace/todo-queues/restart12-bridge-on-one-step.json"
ACCEPTED_RECEIPT_SHA = "f799be3ff83d48513bd6a23669d334b24c73f08564c7cfdc86841bc21b696535"
MAX_RECEIPT_BYTES = 32 * 1024 * 1024
TIMEOUT_SECONDS = 180
CASE_NAMES = ("owner_zero_update", "archived_accepted_six_scalar")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def helpers():
    require(sha(OWNER_HELPER) == OWNER_HELPER_SHA, "owner qualification helper changed")
    spec = importlib.util.spec_from_file_location("_sparse_shadow_owner_helper", OWNER_HELPER)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    return owner, owner.load_helper()


def write_new(path, payload):
    raw = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    require(len(raw) <= MAX_RECEIPT_BYTES, "diagnostic receipt exceeds bound")
    with Path(path).open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    fd = os.open(Path(path).parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def progress(stage, **values):
    print(json.dumps({"stage": stage, **values}, sort_keys=True), flush=True)


def install_network_guard(helper):
    require(sha(helper.SECCOMP_SCRIPT) == helper.SECCOMP_SHA, "network helper changed")
    sys.path.insert(0, str(OWNER_HELPER.parent))
    from audit_native_uscode_embedding_production import _deny_network
    return _deny_network()


def fixed_cases(helper):
    native_ref = {"path": str(NATIVE_RECEIPT), "sha256": NATIVE_SHA, "bytes": NATIVE_BYTES}
    accepted_receipt = {"path": str(ACCEPTED_RECEIPT), "sha256": ACCEPTED_RECEIPT_SHA, "bytes": 1148}
    base = {"path": str(helper.PINNED), "sha256": helper.PINNED_SHA, "bytes": helper.PINNED_BYTES}
    accepted = {"path": str(ACCEPTED_STATE), "sha256": ACCEPTED_SHA, "bytes": ACCEPTED_BYTES}
    for ref in (native_ref, accepted_receipt, base, accepted):
        helper.verify(ref)
    native, prior = helper.read(NATIVE_RECEIPT), helper.read(ACCEPTED_RECEIPT)
    require(native.get("passed") is True and native.get("candidate_parent_is_registered_base") is True,
            "historical owner qualification failed")
    require(native["native_result"]["accepted_projection_epochs"] == 0,
            "owner historical case must be zero-update")
    require(prior.get("accepted_epochs") == 1 and prior.get("optimizer_step") is True
            and prior.get("source_state") == base["path"] and prior.get("saved_state") == accepted["path"]
            and prior.get("admitted") is False, "archived accepted receipt differs")
    final = native["candidate"]
    helper.verify(final)
    base_version = native["candidate_version"]["parent_version_id"]
    require(base_version == native["historical_owner"]["base_version_id"], "historical base identity differs")
    return [
        {"name": CASE_NAMES[0], "base": base, "final": final, "base_version_id": base_version,
         "scope": "historical actual owner candidate with zero accepted updates; unchanged-state control",
         "historical_owner_transition": True},
        {"name": CASE_NAMES[1], "base": base, "final": accepted, "base_version_id": base_version,
         "scope": "archived three-gate in-sample accepted update; no owner-observed changed transition",
         "historical_owner_transition": False},
    ], [native_ref, accepted_receipt, base, final, accepted]


def result_checks(value, case):
    capture = value.get("capture_report", {})
    expected_changed = case["name"] == CASE_NAMES[1]
    expected_counts = {"changed_component_count": int(expected_changed),
        "touched_row_count": 6 if expected_changed else 0, "touched_component_count": 0,
        "inserted_rows": 6 if expected_changed else 0, "deleted_rows": 0, "revision_witness_count": 0}
    return {
        "passed": value.get("passed") is True,
        "diagnostic_only": value.get("mode") == "diagnostic_only",
        "full_authoritative": value.get("full_checkpoint_authoritative") is True,
        "base_exact": value.get("base_artifact") == case["base"],
        "final_exact": value.get("final_artifact") == case["final"],
        "all_comparisons": bool(value.get("checks")) and all(x is True for x in value["checks"].values()),
        "expected_change_counts": capture.get("counts") == expected_counts,
        "expected_changed_components": capture.get("changed_components") ==
            (["legal_ir_view_logits"] if expected_changed else []),
        "legacy_reload_revisions_zero": capture.get("base_snapshot", {}).get("state_revision") == 0
            and capture.get("result_snapshot", {}).get("state_revision") == 0,
        "not_revision_only": capture.get("revision_only") is False,
        "all_38_components_scanned": len(capture.get("base_snapshot", {}).get("component_fields", [])) == 38
            and len(capture.get("result_snapshot", {}).get("component_fields", [])) == 38,
        "no_admission": value.get("admitted") is False,
        "no_promotion": value.get("promoted") is False,
        "no_publication": value.get("publication_performed") is False,
        "no_current_base_authority": value.get("registered_base_authority_verified") is False,
        "no_optimizer_acceptance_inferred": value.get("optimizer_acceptance_asserted") is False,
    }


def child(query_path, query_sha, output):
    started = time.perf_counter()
    owner, helper = helpers()
    result = {"schema": "daemon-sparse-shadow-child-v1", "passed": False,
              "cases": [], "training_performed": False, "bridge_evaluation_performed": False}
    query = None
    try:
        require(sha(query_path) == query_sha, "child query changed")
        query = helper.read(query_path, MAX_RECEIPT_BYTES)
        require(query["case_names"] == list(CASE_NAMES), "unexpected diagnostic cases")
        require(dict(os.environ) == query["environment"], "child environment differs")
        result["network_guard"] = install_network_guard(helper)
        sys.path.insert(0, str(ROOT))
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_sparse_shadow import write_checkpoint_shadow
        result["tree_pin"] = require_workspace_logic_tree()
        result["source_manifest_before"] = helper.source_manifest()
        require(result["source_manifest_before"] == query["source_manifest"], "source changed before replay")
        cases, guards = fixed_cases(helper)
        require(cases == query["cases"] and guards == query["guards"], "fixed input identities differ")
        for case in cases:
            case_dir = Path(query["directory"]) / case["name"]
            case_dir.mkdir()
            row = {"name": case["name"], "scope": case["scope"]}
            row["memory_before"] = helper.memory_observation()
            result["cases"].append(row)
            progress("replay_started", case=case["name"])
            clock = time.perf_counter()
            try:
                row["result"] = write_checkpoint_shadow(case["base"], case["final"],
                    base_version_id=case["base_version_id"], output_directory=case_dir,
                    provenance={"qualification_case": case["name"],
                        "historical_owner_transition": case["historical_owner_transition"],
                        "current_owner_authority_verified": False})
            finally:
                row["wall_seconds"] = time.perf_counter() - clock
                row["memory_after"] = helper.memory_observation()
            row["checks"] = result_checks(row["result"], case)
            require(all(row["checks"].values()), "case comparison failed")
            for name in ("patch_ref", "receipt_ref"):
                helper.verify(row["result"][name])
                ref = row["result"][name]
                expected_name = "patch.json" if name == "patch_ref" else "receipt.json"
                require(Path(ref["path"]) == case_dir / expected_name, "shadow output escaped case directory")
            capture = row["result"]["capture_report"]
            require(row["result"]["patch_ref"]["sha256"] == capture["patch_sha256"]
                    and row["result"]["patch_ref"]["bytes"] == capture["patch_bytes"], "patch capture descriptor differs")
            persisted = helper.read(row["result"]["receipt_ref"]["path"], MAX_RECEIPT_BYTES)
            require(helper.canonical(persisted) == helper.canonical({key: value for key, value in
                    row["result"].items() if key != "receipt_ref"}), "returned and persisted shadow receipts differ")
            row["output_closure_verified"] = True
            progress("replay_completed", case=case["name"], wall_seconds=row["wall_seconds"])
        result["passed"] = True
    except BaseException as exc:
        result["error"] = {"type": f"{type(exc).__module__}.{type(exc).__qualname__}", "message": str(exc)[:4096]}
    finally:
        try:
            require(query is not None, "query unavailable for final verification")
            for ref in query["guards"]:
                helper.verify(ref)
            result["source_manifest_after"] = helper.source_manifest()
            result["source_unchanged"] = result["source_manifest_after"] == query["source_manifest"]
            result["inputs_unchanged"] = True
            result["environment_unchanged"] = dict(os.environ) == query["environment"]
            result["query_unchanged"] = sha(query_path) == query_sha
            result["harness_unchanged"] = sha(__file__) == query["harness_sha256"]
            result["passed"] = result["passed"] and all(result[k] for k in
                ("source_unchanged", "inputs_unchanged", "environment_unchanged", "query_unchanged", "harness_unchanged"))
        except BaseException as exc:
            result["passed"] = False
            result["guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:4096]}
        result["elapsed_seconds_including_guards"] = time.perf_counter() - started
        write_new(output, result)
    return 0 if result["passed"] else 1


def supervise(query, output, directory, environment, reservation, helper):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import _process, _group_usage
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_invocation import _terminate
    process = identity = primary = None
    started = time.monotonic()
    with (directory / "child.log").open("xb") as log:
        try:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", str(query),
                "--query-sha256", sha(query), "--output", str(output)], cwd=directory,
                env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            observed = _process(process.pid)
            if observed is not None:
                identity = {key: observed[key] for key in ("pid", "birth")}
            reservation.check_usage(directory, child_pid=process.pid)
            progress("child_started", pid=process.pid, log=str(directory / "child.log"), timeout_seconds=TIMEOUT_SECONDS)
            next_check = time.monotonic() + 5
            while process.poll() is None:
                now = time.monotonic()
                require(now - started <= TIMEOUT_SECONDS, "offline replay exceeded 180 seconds")
                if now >= next_check:
                    reservation.check_usage(directory)
                    next_check = now + 5
                time.sleep(0.2)
            require(process.returncode == 0, f"offline child exited {process.returncode}; retained child receipt/log")
            require(identity is not None and not _group_usage(identity)["live_processes"], "child left live group members")
            reservation.check_usage(directory)
            value = helper.read(output, MAX_RECEIPT_BYTES)
            require(value.get("passed") is True, "offline child verification failed")
            return value
        except BaseException as exc:
            primary = exc
            raise
        finally:
            try:
                if process is not None:
                    _terminate(process, identity)
                log.flush(); os.fsync(log.fileno())
            except BaseException as exc:
                if primary is None:
                    raise
                primary.add_note(f"cleanup also failed: {type(exc).__name__}")


def parent(directory, output):
    owner, helper = helpers()
    started = time.perf_counter()
    result = {"schema": "daemon-sparse-shadow-qualification-v1", "passed": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "automatic_retry": False,
        "training_performed": False, "bridge_evaluation_performed": False,
        "owner_operations_performed": False, "admitted": False, "promoted": False,
        "publication_performed": False, "speed_claim": False,
        "scope": "offline exact checkpoint reconstruction; full endpoints remain authoritative",
        "harness": helper.descriptor(__file__), "resource_policy": owner.resource_policy(),
        "cold_scope": "fresh replay child; filesystem cache uncontrolled; no bridge-on timings"}
    reservation = None
    try:
        environment = owner.parent_environment(helper, dict(os.environ))
        os.environ.clear(); os.environ.update(environment)
        result["parent_network_guard"] = install_network_guard(helper)
        sys.path.insert(0, str(ROOT))
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation
        scheduler = get_global_resource_scheduler()
        os.environ["IPFS_DATASETS_RESOURCE_SCHEDULER_PATH"] = str(scheduler.state_path)
        environment = dict(os.environ)
        result["environment_before"] = environment
        result["scheduler"] = {"state_path": str(scheduler.state_path), "configuration": scheduler.config.persisted_dict(),
            "private_configuration_override": False}
        result["source_manifest_before"] = helper.source_manifest()
        cases, guards = fixed_cases(helper)
        result["cases"], result["input_guards"] = cases, guards
        policy = owner.resource_policy()
        reservation = DaemonResourceReservation(policy["ledger_path"], roots=policy["roots"],
            storage_bytes=policy["storage_bytes"], memory_mb=policy["memory_mb"], cpu_slots=1, timeout_seconds=0)
        with reservation:
            reservation.check_usage(directory)
            reservation.account_external_bytes("qualification-receipt", MAX_RECEIPT_BYTES)
            query = directory / "query.json"
            write_new(query, {"case_names": list(CASE_NAMES), "cases": cases, "guards": guards,
                "directory": str(directory), "environment": environment,
                "source_manifest": result["source_manifest_before"], "harness_sha256": result["harness"]["sha256"]})
            result["query"] = helper.descriptor(query)
            result["child"] = supervise(query, directory / "child-result.json", directory, environment, reservation, helper)
            result["child_result"] = helper.descriptor(directory / "child-result.json")
            result["reservation"] = reservation.release(artifacts_durable=True)
        result["passed"] = True
    except BaseException as exc:
        result["error"] = {"type": f"{type(exc).__module__}.{type(exc).__qualname__}", "message": str(exc)[:4096],
            "notes": getattr(exc, "__notes__", [])}
        if reservation is not None:
            result["reservation"] = reservation.to_dict()
    finally:
        try:
            for ref in result.get("input_guards", []):
                helper.verify(ref)
            result["inputs_unchanged"] = bool(result.get("input_guards"))
            result["source_manifest_after"] = helper.source_manifest()
            result["source_unchanged"] = result["source_manifest_after"] == result.get("source_manifest_before")
            result["environment_unchanged"] = dict(os.environ) == result.get("environment_before")
            result["harness_unchanged"] = sha(__file__) == result["harness"]["sha256"]
            result["helpers_unchanged"] = sha(OWNER_HELPER) == OWNER_HELPER_SHA and sha(owner.HELPER_PATH) == owner.HELPER_SHA
            result["artifact_inventory"] = owner.collect_failure_artifacts(helper, directory)
            result["passed"] = result["passed"] and all(result[k] for k in
                ("inputs_unchanged", "source_unchanged", "environment_unchanged", "harness_unchanged", "helpers_unchanged"))
        except BaseException as exc:
            result["passed"] = False
            result["guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:4096]}
        result["total_seconds_including_guards"] = time.perf_counter() - started
        write_new(output, result)
        progress("receipt_written", path=str(output), passed=result["passed"], sha256=sha(output))
    return 0 if result["passed"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline-replay", action="store_true")
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--query-sha256", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child is not None:
        require(args.query_sha256 is not None and not args.offline_replay and args.directory is None,
                "invalid child arguments")
        return child(args.child, args.query_sha256, args.output)
    if not args.offline_replay or args.directory is None:
        parser.error("--offline-replay and a fresh --directory are required")
    owner, _ = helpers()
    directory, output = args.directory.absolute(), args.output.absolute()
    if directory != directory.resolve() or output != output.resolve() or directory.exists() or output.exists():
        parser.error("fresh unaliased directory and receipt required; no retries")
    if not directory.is_relative_to(owner.STORAGE_ROOTS[0]) or not output.is_relative_to(owner.STORAGE_ROOTS[2]):
        parser.error("directory and receipt must lie within their fixed storage roots")
    directory.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    return parent(directory, output)


if __name__ == "__main__":
    raise SystemExit(main())
