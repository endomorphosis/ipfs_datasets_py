"""Qualify TLC outcome integrity with actual bounded, admitted native work.

Constructor Java identity, model execution and descriptive help use their real
default admission paths. Constructor ownership is separate from check ownership.
No installs, Apalache model execution, pool changes or manufactured pressure.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import resource
import shlex
import sys
import time
import traceback

import bench_java_probe_admission as java_baseline
import bench_state_model_probe_admission as previous
from bench_generic_prover_admission import artifacts, request as baseline_request
from bench_smt_operation_control import MIB, ROOT, require, saved, sha, write

WORKERS = (1, 2, 4)
REPEATS = 2
MODEL_TIMEOUT_MS = 15000
OUTPUT_BYTES = 65536
TRUNCATED_OUTPUT_BYTES = 4096
JAVA_FLAGS = ("-Xms16m", "-Xmx128m", "-XX:ActiveProcessorCount=1",
              "-XX:+UseSerialGC", "-XX:ReservedCodeCacheSize=64m",
              "-XX:CompressedClassSpaceSize=64m")


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__)}


def selected_tools():
    from ipfs_datasets_py.logic.backends.installers import state_model
    root = state_model.expand_user_local_root().resolve()
    manifest = root / "manifests/tlc.json"
    require(manifest.is_file() and manifest.stat().st_size <= 65536, "bounded installed TLC manifest missing")
    record = json.loads(manifest.read_text())
    require(record["tool_id"] == "tlc" and record["version"] == "1.8.0", "unreviewed TLC installation selected")
    paths = {"java": Path(record["java_executable"]).resolve(strict=True),
             "jar": (root / "tlc/1.8.0/tla2tools.jar").resolve(strict=True),
             "manifest": manifest.resolve(strict=True)}
    hashes = {str(path): previous.tool_sha(path) for path in paths.values()}
    require(hashes[str(paths["jar"])] == state_model.TLC_SHA256, "installed TLC JAR identity differs")
    with paths["java"].open("rb") as stream:
        require(stream.read(4) == b"\x7fELF", "selected Java must be the actual installed ELF")
    return {name: str(path) for name, path in paths.items()}, hashes


def launcher_body(selection):
    # Only this new benchmark-local launcher is written. TMPDIR is the actual
    # bounded runner workspace; Java otherwise ignores that environment hint.
    # set/unset are shell builtins and exec replaces the shell with Java: this
    # reviewed launcher does not fork helper processes beyond its one slot.
    command = shlex.join((selection["java"], *JAVA_FLAGS))
    suffix = shlex.join(("-cp", selection["jar"], "tlc2.TLC"))
    return ('#!/bin/sh\nset -eu\nunset JAVA_TOOL_OPTIONS _JAVA_OPTIONS JDK_JAVA_OPTIONS\n'
            + 'exec ' + command + ' -Djava.io.tmpdir="${TMPDIR:?}" ' + suffix + ' "$@"\n')


def bounded_request(*, output_bytes=OUTPUT_BYTES):
    value = baseline_request("state_transition", memory_mb=256, timeout_ms=MODEL_TIMEOUT_MS)
    return replace(value, bounds=replace(value.bounds, max_output_bytes=output_bytes))


def padded_counterexample():
    """Three explored violating states with a large real, unchanged trace value."""
    value = artifacts(False)
    text = ("---- MODULE BoundedCounter ----\nEXTENDS Integers\nVARIABLES n, padding\n"
            "Init == n = 0 /\\ padding = [i \\in 1..1024 |-> i]\n"
            "Next == n < 3 /\\ n' = n + 1 /\\ UNCHANGED padding\n"
            "Spec == Init /\\ [][Next]_<<n, padding>>\nSafety == n \\in 0..1\n====\n")
    return replace(value, model_text=text, source_document_id="benchmark:bounded-padded-counter")


class OutcomeAudit(java_baseline.JavaAudit):
    """Delegate every real native call and retain exact bounded fixture inputs."""

    def __init__(self, owner):
        super().__init__(owner)
        self.requests = []
        self.completed_model_triggers = []
        self.workspace_environments = []

    def observe(self, name, args):
        super().observe(name, args)
        if name == "subprocess.Popen":
            require(args[3].get("TMPDIR") == str(args[2]), "Java temporary path is outside its private workspace")
            with self.lock:
                self.workspace_environments.append({"case": self.local.case, "tmpdir_is_workspace": True})

    def install_observers(self):
        super().install_observers()
        from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
        run = ResourceAdmittedToolRunner.run

        def observed_run(runner, *args, **kwargs):
            request = args[0] if args else kwargs["request"]
            inputs = {name: value.encode() if isinstance(value, str) else value
                      for name, value in request.input_files.items()}
            detail = {"case": self.local.case, "argv": list(request.argv), "limits": asdict(request.limits),
                "input_sha256": {name: hashlib.sha256(value).hexdigest() for name, value in inputs.items()},
                "input_bytes": {name: len(value) for name, value in inputs.items()},
                "output_paths": list(request.output_paths)}
            with self.lock:
                require(len(self.requests) < 128, "bounded request audit exhausted")
                self.requests.append(detail)
            result = run(runner, *args, **kwargs)
            token = getattr(self.local, "cancel_after_model", None)
            if token is not None and request.input_files:
                self.local.cancel_after_model = None
                # The completed object is unchanged; only the caller-owned
                # token is set after actual native execution and lease cleanup.
                token.cancel()
                with self.lock:
                    self.completed_model_triggers.append({"case": self.local.case,
                        "boundary": "after_actual_completed_model", "pid": result.pid,
                        "returncode": result.returncode, "workspace_cleaned": result.workspace_cleaned,
                        "at_monotonic": time.monotonic()})
            return result

        ResourceAdmittedToolRunner.run = observed_run


def construct(audit, selection, label):
    from ipfs_datasets_py.logic.backends.tla.runners import TLCBackend
    audit.local.case = label + ":constructor"
    backend = TLCBackend(executable=selection["wrapper"], java_executable=selection["java"], lazy_install=False)
    java_baseline._check_phase(audit, audit.local.case, selection["java"])
    audit.local.case = label
    return backend


def phase_rows(audit, label, selection, *, count, fixture, output_bytes=OUTPUT_BYTES):
    launches, rows = java_baseline._rows(audit, label)
    require(len(launches) == len(rows) == count, "unexpected model/help launch count")
    require(len({row["result"]["pid"] for row in rows}) == count, "native phase PIDs are missing or reused")
    for index, (launch, row) in enumerate(zip(launches, rows)):
        observed, native = row["request"], row["result"]
        model = index == 0
        expected = ([selection["wrapper"], "-workers", "1", "-config", "BoundedCounter.cfg", "BoundedCounter.tla"]
                    if model else [selection["wrapper"], "-help"])
        require(observed["argv"] == native["command"] == expected, "actual model/help command receipt differs")
        require(launch["argv"][-len(expected):] == expected, "Popen argv differs from its lifecycle")
        require(observed["memory_bytes"] == 4 * 1024**3 and observed["resident_memory_bytes"] == 256 * MIB
                and observed["max_output_bytes"] == output_bytes
                and 0 < observed["timeout_seconds"] <= (MODEL_TIMEOUT_MS / 1000 if model else 3),
                "model/help phase lost finite bounds")
        require(observed["stdin_is_empty"] and observed["java_option_environment_absent"]
                and observed["input_file_count"] == (2 if model else 0)
                and observed["output_path_count"] == (3 if model else 0), "model/help inputs differ")
        require(native["pid"] is not None and native["workspace_cleaned"]
                and not any(native[key] for key in ("timed_out", "unavailable", "resource_exhausted", "workspace_limit_exceeded", "error")),
                "unexpected native tool/resource/cleanup failure")
        lease = next(row for row in launch["owned_leases"] if row["lease_id"] == launch["launch_lease_id"])
        require((lease["cpu_slots"], lease["memory_mb"], lease["child_process_slots"]) == (1, 256, 1)
                and lease["parent_lease_id"] is None, "default TLC phase did not own one bounded root lease")
        details = [row for row in audit.requests if row["case"] == label and row["argv"] == expected]
        require(len(details) == 1 and details[0]["limits"]["cpu_seconds"] == observed["timeout_seconds"],
                "native CPU or request accounting differs")
        detail_limits = details[0]["limits"]
        require(detail_limits["max_input_bytes"] == (max(4096, len(fixture.model_text.encode())
                    + len(fixture.tlc_config_text.encode())) if model else 4096)
                and detail_limits["max_workspace_bytes"] == 16 * MIB
                and detail_limits["enforce_file_size_limit"] is True and detail_limits["max_file_bytes"] is None,
                "native input/workspace or inherited finite per-file limit differs")
        require(details[0]["output_paths"] == (["counterexample.tla", "violation.tla", "example.tla"] if model else []),
                "native declared output paths differ")
        if model:
            inputs = {"BoundedCounter.tla": fixture.model_text, "BoundedCounter.cfg": fixture.tlc_config_text}
            require(details[0]["input_sha256"] == {name: hashlib.sha256(value.encode()).hexdigest() for name, value in inputs.items()},
                    "model/configuration native bytes differ from the bound artifacts")
    return rows


def verify_binding(outcome, fixture, request, *, status):
    from ipfs_datasets_py.logic.backends.results import ResultAuthority
    receipt, result = outcome.receipt, outcome.result
    require(result.status.value == status and result.authority is ResultAuthority.MODEL_CHECK,
            "model outcome status/authority differs")
    require(outcome.request_digest == request.digest and receipt.artifact_digest == fixture.artifact_digest
            and receipt.model_digest == fixture.model_digest and receipt.configuration_digest == fixture.tlc_config_digest
            and receipt.configuration_text == fixture.tlc_config_text and receipt.bounded and not receipt.unbounded_proof,
            "outcome lost exact request/artifact/configuration binding")
    witness = result.witness.to_dict()
    require(witness["receipt_id"] == receipt.receipt_id and witness["bounded"] and not witness["unbounded_proof"],
            "result witness differs from its bounded receipt")
    if status not in {"satisfied", "violated"}:
        require(receipt.counterexample is None and "counterexample" not in witness,
                "incomplete native outcome published counterexample evidence")


def case(valid, audit, selection, label):
    label += ":" + ("valid" if valid else "invalid")
    started = time.monotonic()
    backend = construct(audit, selection, label)
    fixture, request = artifacts(valid), bounded_request()
    outcome = backend.check(fixture, request=request)
    rows = phase_rows(audit, label, selection, count=2, fixture=fixture)
    model, help_result = (row["result"] for row in rows)
    for native in (model, help_result):
        require(not native["cancelled"] and not native["output_truncated"] and not native["process_tree_terminated"],
                "clean baseline native phase was interrupted")
    require(model["returncode"] == (0 if valid else 12) and help_result["returncode"] == 1,
            "native TLC exit conventions changed")
    verify_binding(outcome, fixture, request, status="satisfied" if valid else "violated")
    require("TLC" in outcome.receipt.tool_version and "Version" in outcome.receipt.tool_version,
            "clean descriptive TLC help is absent")
    if valid:
        require("4 distinct states found" in model["stdout"] and outcome.receipt.counterexample is None,
                "four-state positive exploration did not complete")
    else:
        trace = outcome.receipt.counterexample
        require("Invariant Safety is violated" in model["stdout"] and trace is not None
                and [state.assignments.get("n") for state in trace.states] == ["0", "1", "2"],
                "real complete counterexample trace differs")
    return {"case": label, "valid": valid, "phase_count": 3, "constructor_phases": 1,
        "model_and_help_phases": 2, "elapsed_seconds": time.monotonic() - started, "outcome": outcome.to_dict()}


def control(kind, audit, selection):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    label = "control:" + kind
    started = time.monotonic()
    backend = construct(audit, selection, label)
    token = CancellationToken()
    fixture = padded_counterexample() if kind == "truncated_counterexample" else artifacts(False)
    request = bounded_request(output_bytes=TRUNCATED_OUTPUT_BYTES if kind == "truncated_counterexample" else OUTPUT_BYTES)
    if kind == "pre_cancel":
        token.cancel()
    elif kind == "live_cancel":
        audit.local.cancel_live_probe = token
    elif kind == "after_model_cancel":
        audit.local.cancel_after_model = token
    elif kind != "truncated_counterexample":
        raise AssertionError("unknown outcome control")
    try:
        outcome = backend.check(fixture, request=request, cancellation=token)
    finally:
        audit.local.cancel_live_probe = audit.local.cancel_after_model = None
    count = 0 if kind == "pre_cancel" else 1
    rows = phase_rows(audit, label, selection, count=count, fixture=fixture, output_bytes=request.bounds.max_output_bytes)
    verify_binding(outcome, fixture, request, status="unknown" if kind == "truncated_counterexample" else "error")
    require(outcome.receipt.tool_version in {"", "unavailable"}, "unsafe model launched or published follow-up help")
    detail = {"case": label, "kind": kind, "phase_count": count + 1, "constructor_phases": 1,
        "model_phases": count, "help_phases": 0, "outcome": outcome.to_dict()}
    if rows:
        native = rows[0]["result"]
        if kind == "live_cancel":
            triggers = [row for row in audit.triggers if row["case"] == label]
            require(native["cancelled"] and native["process_tree_terminated"] and not Path("/proc", str(native["pid"])).exists()
                    and len(triggers) == 1 and triggers[0]["pid"] == native["pid"] and triggers[0]["observed_live"],
                    "real live model cancellation did not cleanly drain")
            detail["trigger"] = triggers[0]
        elif kind == "after_model_cancel":
            triggers = [row for row in audit.completed_model_triggers if row["case"] == label]
            require(native["returncode"] == 12 and not any(native[key] for key in ("cancelled", "output_truncated", "process_tree_terminated"))
                    and "Invariant Safety is violated" in native["stdout"] and len(triggers) == 1
                    and triggers[0]["pid"] == native["pid"] and token.is_set(),
                    "completed-model cancellation did not follow the genuine counterexample")
            detail["trigger"] = triggers[0]
        else:
            require(native["output_truncated"] and not native["cancelled"]
                    and "Invariant Safety is violated" in native["stdout"]
                    and outcome.receipt.output_truncated, "actual truncation did not retain a genuine violation marker")
            detail["genuine_violation_marker_preserved"] = True
    detail.update(elapsed_seconds=time.monotonic() - started,
                  shared_after=java_baseline.previous._drained(audit))
    require(detail["elapsed_seconds"] < 25, "bounded native outcome control took unexpectedly long")
    return detail


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    before = pins()
    write(directory / "command.json", {"argv": sys.argv, "cwd": str(Path.cwd()),
        "environment": {name: os.environ.get(name) for name in (
            "PYTHONPATH", "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS", "IPFS_TEST_PROOF_REUSE_MODE")}})
    try:
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = java_baseline.previous.install_saved_owner(directory / "saved-scheduler-config.json")
    except BaseException:
        write(directory / "result.json", {"schema": "tla-outcome-integrity-benchmark@1", "status": "failed",
            "failure_stage": "shared_pool_initialization", "error": traceback.format_exc(),
            "source_pins_before": before, "source_pins_after": pins(), "launches": 0, "lifecycles": 0,
            "native_execution_started": False})
        raise
    audit = OutcomeAudit(owner)
    audit.install_observers()
    sys.addaudithook(audit.observe)
    result = {"schema": "tla-outcome-integrity-benchmark@1", "status": "running", "source_pins_before": before,
        "runtime": saved.runtime(), "shared_before": saved.state_summary(owner.state_path),
        "shared_pool_compatibility": owner._benchmark_pool_compatibility, "runs": [], "controls": [], "checks": {},
        "scope": "Bounded actual TLC model outcomes; constructor Java identity owns a separate root; no installation or Apalache model execution"}
    started = time.monotonic()
    try:
        selection, tool_before = selected_tools()
        launcher = directory / "tlc-memory-aware"
        launcher.write_text(launcher_body(selection))
        launcher.chmod(0o700)
        selection["wrapper"] = str(launcher)
        tool_before[str(launcher)] = previous.tool_sha(launcher)
        result.update(tool_selection=selection, tool_files_before=tool_before,
            wrapper_profile={"java_flags": list(JAVA_FLAGS), "heap_bytes": 128 * MIB,
                "direct_exec_no_helper_forks": True, "java_tmpdir_from_private_workspace": True})
        write(directory / "fixtures.json", {"valid": artifacts(True).to_dict(), "invalid": artifacts(False).to_dict(),
                                             "padded_invalid": padded_counterexample().to_dict()})
        for workers in WORKERS:
            for repeat in range(REPEATS):
                label = f"parallel:{workers}:{repeat}"
                batch_started = time.monotonic()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    rows = list(pool.map(lambda job: case(job[1], audit, selection,
                        label + f":instance:{job[0]}"), ((0, True), (0, False), (1, True), (1, False))))
                result["runs"].append({"workers": workers, "repeat": repeat,
                    "elapsed_seconds": time.monotonic() - batch_started, "cases": rows})
                write(directory / "partial.json", result)
        for kind in ("pre_cancel", "live_cancel", "after_model_cancel", "truncated_counterexample"):
            result["controls"].append(control(kind, audit, selection))
        result["checks"].update(
            all_24_clean_model_cases=sum(len(run["cases"]) for run in result["runs"]) == 24,
            all_four_outcome_controls=len(result["controls"]) == 4,
            all_79_native_phases_accounted=len(audit.events) == len(audit.results) == len(audit.requests) == 79,
            all_28_real_constructor_probes=sum(row["case"].endswith(":constructor") for row in audit.events) == 28,
            all_27_model_phases=sum(bool(row["request"]["input_file_count"]) for row in audit.results) == 27,
            all_24_help_phases=sum(row["request"]["argv"][-1] == "-help" for row in audit.results) == 24,
            all_79_native_environments_sanitized=len(audit.environments) == len(audit.workspace_environments) == 79,
            concurrent_owned_roots_observed=max(sum(not row["parent_lease_id"] for row in event["owned_leases"])
                for event in audit.events if event["case"].startswith("parallel:")) >= 2)
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
        raise
    finally:
        result["elapsed_seconds"] = time.monotonic() - started
        result["source_pins_after"] = pins()
        result["shared_after"] = saved.state_summary(owner.state_path)
        if "tool_files_before" in result:
            try:
                result["tool_files_after"] = {path: previous.tool_sha(path) for path in result["tool_files_before"]}
            except (OSError, AssertionError):
                result["tool_files_after"] = {}
                result["tool_identity_error"] = traceback.format_exc()
            result["checks"]["selected_tool_files_unchanged"] = result["tool_files_before"] == result["tool_files_after"]
        result["checks"].update(sources_stable=result["source_pins_after"] == before,
            shared_config_unchanged=java_baseline.previous._config_bytes(result["shared_after"]["config"]) ==
                java_baseline.previous._config_bytes(envelope["config"]),
            owned_work_drained=not result["shared_after"]["owned_active_leases"] and not result["shared_after"]["owned_waiting_requests"])
        result["child_usage"] = {key: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), key)
                                for key in ("ru_utime", "ru_stime", "ru_maxrss")}
        result["memory_observation_scope"] = "Largest reaped child in Linux KiB; not aggregate peak RSS"
        for name, value in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results),
                            ("request-audit.json", audit.requests),
                            ("control-audit.json", {"live_triggers": audit.triggers,
                                "completed_model_triggers": audit.completed_model_triggers, "native_environments": audit.environments,
                                "workspace_environments": audit.workspace_environments})):
            write(directory / name, value)
            result[name + "_sha256"] = sha(directory / name)
        result.update(launches=len(audit.events), lifecycles=len(audit.results),
            native_lifecycles=sum(row["result"]["pid"] is not None for row in audit.results),
            prelaunch_lifecycles=sum(row["result"]["pid"] is None for row in audit.results))
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    require(result["status"] == "passed", "native TLC outcome qualification failed")
    print(json.dumps({key: result[key] for key in ("status", "checks", "launches", "lifecycles")}))


if __name__ == "__main__":
    main()
