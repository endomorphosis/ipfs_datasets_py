"""Qualify bounded TLC help and Apalache version probes on the shared pool.

This executes installed support tools only: no model checks, installation,
downloads, or shared-pool changes. Canonical TLC launcher selection expands to
the direct reviewed Java command; the managed launcher itself is not executed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shlex
import stat
import sys
import time
import traceback

import bench_java_probe_admission as previous
from bench_smt_operation_control import MIB, ROOT, require, saved, sha, write

WORKERS = (1, 2, 4)
REPEATS = 2
ROUTES = ("tlc_jar", "tlc_managed_launcher", "tlc_banner", "apalache_runtime", "apalache_banner")
JAVA_FLAGS = ("-Xms16m", "-Xmx256m", "-Xss1m", "-XX:+UseSerialGC",
              "-XX:ActiveProcessorCount=1", "-XX:MaxMetaspaceSize=128m",
              "-XX:ReservedCodeCacheSize=64m", "-XX:-UsePerfData")
TLC_HELP_MARKERS = ("TLC - provides model checking and simulation of TLA+ specifications", "SYNOPSIS", "DESCRIPTION")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__)}


def tool_sha(path):
    """Stream the large installed Apalache JAR without allocating its contents."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 256 * MIB,
                "tool identity needs a regular bounded installed file")
        digest, size = hashlib.sha256(), 0
        while True:
            block = stream.read(MIB)
            if not block:
                break
            size += len(block)
            require(size <= 256 * MIB, "installed tool grew beyond the identity bound")
            digest.update(block)
        require(size == info.st_size == os.fstat(stream.fileno()).st_size,
                "installed tool size changed during identity observation")
    return digest.hexdigest()


def selected_tools():
    from ipfs_datasets_py.logic.backends.installers import state_model
    require(tuple(state_model.STATE_MODEL_PROBE_JAVA_ARGUMENTS) == JAVA_FLAGS
            and state_model.STATE_MODEL_PROBE_RESIDENT_BYTES == 512 * MIB
            and state_model.STATE_MODEL_PROBE_ADDRESS_SPACE_BYTES == 4 * 1024**3
            and state_model.STATE_MODEL_PROBE_OUTPUT_BYTES == 65536,
            "production help/version profile differs from the independently fixed qualification profile")
    root = state_model.expand_user_local_root().resolve()
    manifests = {name: root / "manifests" / (name + ".json") for name in ("tlc", "apalache")}
    records = {}
    for name, path in manifests.items():
        require(path.is_file() and path.stat().st_size <= 65536, "bounded installed manifest is missing")
        records[name] = json.loads(path.read_text())
        require(records[name]["tool_id"] == name and records[name]["version"] == ("1.8.0" if name == "tlc" else "0.58.3"),
                "installed tool manifest does not select the reviewed version")
    paths = {"tlc_launcher": root / "bin/tlc", "tlc_jar": root / "tlc/1.8.0/tla2tools.jar",
        "apalache_launcher": root / "bin/apalache-mc",
        "apalache_payload": Path(records["apalache"]["payload_path"]),
        "tlc_java": Path(records["tlc"]["java_executable"]),
        "apalache_java": Path(records["apalache"]["java_executable"]),
        "tlc_manifest": manifests["tlc"], "apalache_manifest": manifests["apalache"]}
    paths["apalache_jar"] = paths["apalache_payload"].parent.parent / "lib/apalache.jar"
    paths = {role: path.resolve(strict=True) for role, path in paths.items()}
    hashes = {str(path): tool_sha(path) for path in paths.values()}
    require(hashes[str(paths["tlc_jar"])] == state_model.TLC_SHA256,
            "installed TLC JAR differs from the immutable reviewed artifact")
    for role in ("tlc_java", "apalache_java"):
        with paths[role].open("rb") as stream:
            require(stream.read(4) == b"\x7fELF", "native qualification requires the selected actual Java ELF")
    expected_tlc = state_model._launcher_body(paths["tlc_jar"],
        environment={"TLA2TOOLS_JAR": str(paths["tlc_jar"])}, java_jar=paths["tlc_jar"],
        java_main="tlc2.TLC", java_executable=paths["tlc_java"])
    expected_apalache = state_model._launcher_body(paths["apalache_payload"], java_executable=paths["apalache_java"])
    for role, body in (("tlc_launcher", expected_tlc), ("apalache_launcher", expected_apalache)):
        require(paths[role].stat().st_size <= 16384 and paths[role].read_text() == body,
                "managed launcher differs from the unchanged canonical renderer")
    selection = {role: str(path) for role, path in paths.items()}
    selection["canonical_tlc_launcher_bytes_verified"] = True
    selection["tlc_launcher_expands_to_direct_java"] = True
    selection["transitive_jvm_library_tree_hashed"] = False
    return selection, hashes


class ProbeAudit(previous.JavaAudit):
    """Reuse actual lease/lifecycle/PID observers; also check launcher ergonomics."""

    def __init__(self, owner):
        super().__init__(owner)
        self.profile_environments = []

    def observe(self, name, args):
        super().observe(name, args)
        if name != "subprocess.Popen":
            return
        environment, cwd = args[3], args[2]
        tool = self.local.tool
        require(environment.get("TMPDIR") == str(cwd), "support-tool temporary files escaped the private workspace")
        record = {"case": self.local.case, "tool": tool, "tmpdir_is_workspace": True}
        if tool == "apalache":
            jvm_args = tuple(shlex.split(environment.get("JVM_ARGS", "")))
            gc_args = tuple(shlex.split(environment.get("JVM_GC_ARGS", "")))
            require(jvm_args == tuple(arg for arg in JAVA_FLAGS if arg != "-XX:+UseSerialGC")
                    and gc_args == ("-XX:+UseSerialGC",),
                    "Apalache launcher did not receive the owned finite JVM/GC profile")
            record.update(jvm_args=list(jvm_args), jvm_gc_args=list(gc_args))
        with self.lock:
            self.profile_environments.append(record)


def _actual_command(selection, tool):
    if tool == "tlc":
        return (selection["tlc_java"], *JAVA_FLAGS, "-cp", selection["tlc_jar"], "tlc2.TLC", "-help")
    return (selection["apalache_launcher"], "version")


def _check_phase(audit, label, selection, tool, *, interrupted=False, timeout_ceiling=20):
    launches, phases = previous._rows(audit, label)
    require(len(launches) == len(phases) == 1, "support route did not execute exactly one native phase")
    phase = phases[0]
    request, native = phase["request"], phase["result"]
    expected = _actual_command(selection, tool)
    require(tuple(request["argv"]) == tuple(native["command"]) == expected,
            "support receipt/lifecycle did not bind the actual expanded command")
    require(tuple(launches[0]["argv"][-len(expected):]) == expected,
            "observed Popen arguments differ from the actual support command")
    require(request["memory_bytes"] == 4 * 1024**3 and request["resident_memory_bytes"] == 512 * MIB
            and request["max_output_bytes"] == 65536 and 0 < request["timeout_seconds"] <= timeout_ceiling,
            "support probe lost finite AS/RSS/output/wall bounds")
    require(request["stdin_is_empty"] and not request["input_file_count"] and not request["output_path_count"]
            and request["java_option_environment_absent"], "support command retained unreviewed inputs/environment")
    lease = next(row for row in launches[0]["owned_leases"] if row["lease_id"] == launches[0]["launch_lease_id"])
    require(lease["cpu_slots"] == 1 and lease["memory_mb"] == 512
            and lease["child_process_slots"] == (1 if tool == "tlc" else 3),
            "support probe lost its tool-specific reservation")
    require(native["pid"] is not None and native["workspace_cleaned"]
            and not any(native[key] for key in ("unavailable", "resource_exhausted", "output_truncated",
                "workspace_limit_exceeded", "timed_out")), "support probe has an unsafe native lifecycle")
    if interrupted:
        require(native["cancelled"] and native["process_tree_terminated"]
                and not Path("/proc", str(native["pid"])).exists(), "cancelled support process/tree did not drain")
    else:
        require(native["returncode"] == (1 if tool == "tlc" else 0) and not native["cancelled"]
                and not native["process_tree_terminated"] and not native["error"],
                "support probe did not complete with the tool's reviewed exit convention")
    require(len(native["stdout"].encode()) + len(native["stderr"].encode()) <= 65536,
            "support probe exceeded its combined accepted output budget")
    return phase


def case(route, audit, selection, label, *, parent=None):
    from ipfs_datasets_py.logic.backends.installers import state_model
    identifier = label + ":" + route
    tool = "apalache" if route.startswith("apalache") else "tlc"
    audit.local.case, audit.local.tool = identifier, tool
    ownership = {} if parent is None else {"parent_lease": parent}
    started = time.monotonic()
    if route == "tlc_jar":
        value = state_model.probe_tlc_runtime(jar_path=selection["tlc_jar"], java_executable=selection["tlc_java"], **ownership)
    elif route == "tlc_managed_launcher":
        value = state_model.probe_tlc_runtime(executable=selection["tlc_launcher"], java_executable=selection["tlc_java"], **ownership)
    elif route == "tlc_banner":
        value = state_model.read_tlc_version_banner(selection["tlc_launcher"], jar_path=selection["tlc_jar"],
            java_executable=selection["tlc_java"], **ownership)
    elif route == "apalache_runtime":
        value = state_model.probe_apalache_runtime(selection["apalache_launcher"], java_executable=selection["apalache_java"], **ownership)
    elif route == "apalache_banner":
        value = state_model.read_apalache_version_banner(selection["apalache_launcher"], java_executable=selection["apalache_java"], **ownership)
    else:
        raise AssertionError("unknown support route")
    phase = _check_phase(audit, identifier, selection, tool)
    native = phase["result"]
    output = ANSI_ESCAPE.sub("", "\n".join(part for part in (native["stdout"], native["stderr"]) if part).strip())
    if tool == "apalache":
        output = output.strip()
    if isinstance(value, state_model.RuntimeCommandProbe):
        require(value.usable and value.reason_code is None and value.returncode == native["returncode"]
                and tuple(value.command) == _actual_command(selection, tool) and value.output == output,
                "runtime support receipt differs from its complete actual native result")
        outcome = value.to_dict()
    else:
        require(type(value) is str and value == output, "banner helper differs from its actual native result")
        outcome = {"banner": value}
    if tool == "tlc":
        require(all(marker in output for marker in TLC_HELP_MARKERS), "complete real TLC help semantics are absent")
    else:
        require(output == "0.58.3", "Apalache did not report its exact canonical installed version")
    return {"case": identifier, "route": route, "tool": tool, "phase_count": 1,
        "elapsed_seconds": time.monotonic() - started, "outcome": outcome,
        "actual_command": list(_actual_command(selection, tool)), "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "canonical_tlc_expansion": route in {"tlc_managed_launcher", "tlc_banner"}, "support_only": True}


def pre_cancel_control(audit, selection, tool):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    from ipfs_datasets_py.logic.backends.installers import state_model
    label = "control:pre-cancel:" + tool
    audit.local.case, audit.local.tool = label, tool
    token = CancellationToken()
    token.cancel()
    started = time.monotonic()
    value = (state_model.probe_tlc_runtime(executable=selection["tlc_launcher"],
                 java_executable=selection["tlc_java"], cancellation=token) if tool == "tlc"
             else state_model.probe_apalache_runtime(selection["apalache_launcher"],
                 java_executable=selection["apalache_java"], cancellation=token))
    require(not value.usable and value.returncode is None and not value.output,
            "pre-cancelled tool probe returned usable identity/help")
    launches, phases = previous._rows(audit, label)
    require(not launches and all(row["result"]["pid"] is None and row["result"]["cancelled"] for row in phases),
            "pre-cancelled tool probe launched native work")
    return {"case": label, "tool": tool, "phase_count": 0, "launch_count": 0,
        "lifecycle_count": len(phases), "outcome": value.to_dict(), "elapsed_seconds": time.monotonic() - started,
        "shared_after": previous.previous._drained(audit)}


def live_cancel_control(audit, selection, *, ambient):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    from ipfs_datasets_py.logic.backends.installers import state_model
    from ipfs_datasets_py.logic.backends.smt.operation_budget import proof_operation_scope
    tool = "apalache" if ambient else "tlc"
    label = "control:live-cancel:" + ("ambient_apalache" if ambient else "local_tlc")
    audit.local.case, audit.local.tool = label, tool
    token = CancellationToken()
    audit.local.cancel_live_probe = token

    def ambient_probe():
        with proof_operation_scope(timeout_ms=5000, cancellation=token):
            return state_model.probe_apalache_runtime(selection["apalache_launcher"],
                java_executable=selection["apalache_java"])

    started = time.monotonic()
    try:
        if ambient:
            result = previous.previous._stopped_call(ambient_probe, expected_kind="cancelled")
        else:
            value = state_model.probe_tlc_runtime(executable=selection["tlc_launcher"],
                java_executable=selection["tlc_java"], cancellation=token)
            require(not value.usable and value.returncode is None and not value.output,
                    "cancelled TLC help was promoted back to usability")
            result = {"outcome": value.to_dict(), "elapsed_seconds": time.monotonic() - started}
    finally:
        audit.local.cancel_live_probe = None
    require(result["elapsed_seconds"] < 10, "live support cancellation did not finish cleanup promptly")
    phase = _check_phase(audit, label, selection, tool, interrupted=True, timeout_ceiling=5 if ambient else 15)
    triggers = [row for row in audit.triggers if row["case"] == label]
    launches, _ = previous._rows(audit, label)
    require(len(triggers) == 1 and triggers[0]["observed_live"] and token.is_set()
            and triggers[0]["pid"] == phase["result"]["pid"]
            and launches[0]["at_monotonic"] <= triggers[0]["at_monotonic"],
            "support cancellation was not triggered after an actual admitted live probe PID")
    result.update(case=label, tool=tool, phase_count=1, launch_count=1, ambient_operation=ambient,
        trigger=triggers[0], no_followup_launch=True, shared_after=previous.previous._drained(audit))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    before = pins()
    write(directory / "command.json", {"argv": sys.argv, "cwd": str(Path.cwd()),
        "environment": {key: os.environ.get(key) for key in (
            "PYTHONPATH", "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS", "IPFS_TEST_PROOF_REUSE_MODE")}})
    try:
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = previous.previous.install_saved_owner(directory / "saved-scheduler-config.json")
    except BaseException:
        write(directory / "result.json", {"schema": "state-model-probe-admission-benchmark@1", "status": "failed",
            "failure_stage": "shared_pool_initialization", "error": traceback.format_exc(),
            "source_pins_before": before, "source_pins_after": pins(), "launches": 0, "lifecycles": 0,
            "native_execution_started": False, "shared_pool_compatibility": {"mode": "refused"}})
        raise
    audit = ProbeAudit(owner)
    audit.install_observers()
    sys.addaudithook(audit.observe)
    result = {"schema": "state-model-probe-admission-benchmark@1", "status": "running",
        "source_pins_before": before, "runtime": saved.runtime(), "shared_before": saved.state_summary(owner.state_path),
        "runs": [], "controls": [], "checks": {}, "shared_pool_compatibility": owner._benchmark_pool_compatibility,
        "scope": "Installed TLC help and Apalache version only; no model checking, proving, installation, or complete JVM tree attestation"}
    started = time.monotonic()
    try:
        selection, tool_before = selected_tools()
        result.update(tool_selection=selection, tool_files_before=tool_before)
        for workers in WORKERS:
            for repeat in range(REPEATS):
                label = f"parallel:{workers}:{repeat}"
                batch_started = time.monotonic()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    rows = list(pool.map(lambda route: case(route, audit, selection, label), ROUTES))
                result["runs"].append({"workers": workers, "repeat": repeat,
                    "elapsed_seconds": time.monotonic() - batch_started, "cases": rows})
                write(directory / "partial.json", result)
        audit.local.case = "parent"
        with owner.acquire("validation", cpu_slots=1, memory_mb=512, child_process_slots=3, timeout=20) as parent:
            result["nested_cases"] = [case(route, audit, selection, "nested", parent=parent)
                                      for route in ("tlc_jar", "apalache_runtime")]
            nested = [event for event in audit.events if event["case"].startswith("nested:")]
            result["checks"]["two_native_probes_bound_to_actual_parent"] = len(nested) == 2 and all(
                any(row["lease_id"] == event["launch_lease_id"] and row.get("parent_lease_id") == parent.lease_id
                    for row in event["owned_leases"]) for event in nested)
            state = saved.read_json(owner.state_path, 4 * MIB)
            own = [row for row in state["leases"].values() if row["owner_pid"] == os.getpid()]
            result["checks"]["native_children_drained_before_parent_release"] = len(own) == 1 and own[0]["lease_id"] == parent.lease_id
        for tool in ("tlc", "apalache"):
            result["controls"].append(pre_cancel_control(audit, selection, tool))
        for ambient in (False, True):
            result["controls"].append(live_cancel_control(audit, selection, ambient=ambient))
        successful = [row for run in result["runs"] for row in run["cases"]] + result["nested_cases"]
        result["checks"].update(
            all_30_default_probe_cases=sum(len(run["cases"]) for run in result["runs"]) == 30,
            all_32_successful_support_observations=len(successful) == 32 and all(row["support_only"] for row in successful),
            stable_native_output_by_tool=all(len({row["output_sha256"] for row in successful if row["tool"] == tool}) == 1
                                            for tool in ("tlc", "apalache")),
            all_four_controls_passed=len(result["controls"]) == 4,
            all_34_native_launches_have_lifecycles=len(audit.events) == sum(row["result"]["pid"] is not None for row in audit.results) == 34,
            all_34_native_environments_sanitized=len(audit.environments) == len(audit.profile_environments) == 34,
            concurrent_owned_roots_observed=max(sum(not row.get("parent_lease_id") for row in event["owned_leases"])
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
                result["tool_files_after"] = {path: tool_sha(path) for path in result["tool_files_before"]}
            except (OSError, AssertionError):
                # Preserve actual launch/cleanup evidence even if another
                # owner removes or replaces an installed file during this run.
                result["tool_files_after"] = {}
                result["tool_identity_error"] = traceback.format_exc()
            result["checks"]["selected_tool_files_unchanged"] = result["tool_files_before"] == result["tool_files_after"]
        result["checks"].update(sources_stable=result["source_pins_after"] == before,
            shared_config_unchanged=previous.previous._config_bytes(result["shared_after"]["config"]) == previous.previous._config_bytes(envelope["config"]),
            owned_work_drained=not result["shared_after"]["owned_active_leases"] and not result["shared_after"]["owned_waiting_requests"])
        result["child_usage"] = {key: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), key)
                                 for key in ("ru_utime", "ru_stime", "ru_maxrss")}
        result["memory_observation_scope"] = "Largest reaped child in Linux KiB; not aggregate peak RSS"
        for name, value in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results),
                            ("control-audit.json", {"triggers": audit.triggers, "native_environments": audit.environments,
                                                   "profile_environments": audit.profile_environments})):
            write(directory / name, value)
            result[name + "_sha256"] = sha(directory / name)
        result.update(launches=len(audit.events), lifecycles=len(audit.results),
            native_lifecycles=sum(row["result"]["pid"] is not None for row in audit.results),
            prelaunch_lifecycles=sum(row["result"]["pid"] is None for row in audit.results))
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    require(result["status"] == "passed", "native state-model support-probe qualification failed")
    print(json.dumps({key: result[key] for key in ("status", "checks", "launches", "lifecycles")}))


if __name__ == "__main__":
    main()
