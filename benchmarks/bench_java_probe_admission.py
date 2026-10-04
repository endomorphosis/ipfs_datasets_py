"""Qualify admitted, bounded identity probes for an installed support JVM.

These cases execute only java -version. They do not install tools, check models,
or prove claims. All shared resource policy and actual pressure sampling remain
unchanged; observers delegate native admission and process execution.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import threading
import time
import traceback

import bench_smt_operation_control as previous
import bench_smt_v2_operation_control as frozen_v2
from bench_generic_prover_admission import LaunchAudit
from bench_smt_operation_control import MIB, ROOT, require, saved, sha, write

WORKERS = (1, 2, 4)
REPEATS = 2
ROUTES = ("direct_banner", "runtime_probe", "tlc_constructor", "apalache_constructor", "registry_tlc")
JAVA_FLAGS = ("-Xms16m", "-Xmx128m", "-Xss1m", "-XX:+UseSerialGC",
              "-XX:ActiveProcessorCount=1", "-XX:MaxMetaspaceSize=128m",
              "-XX:ReservedCodeCacheSize=64m", "-XX:-UsePerfData", "-version")
JAVA_ENV = ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS")


def pins():
    paths = (Path(__file__), ROOT / "ipfs_datasets_py/logic/backends/installers/state_model.py",
             ROOT / "ipfs_datasets_py/logic/backends/tla/runners.py")
    return {**frozen_v2.pins(), **{str(path.resolve()): sha(path) for path in paths}}


class JavaAudit(LaunchAudit):
    """Use the frozen lease audit with a null-stdin JVM lifecycle observer."""

    def __init__(self, owner):
        super().__init__(owner)
        self.environments = []
        self.triggers = []

    def install_observers(self):
        from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
        from ipfs_datasets_py.logic.backends.process import SubprocessExecutor
        acquire = self.owner.acquire

        def observed_acquire(*args, **kwargs):
            lease = acquire(*args, **kwargs)
            prior = getattr(self.local, "lease", None)
            self.local.lease = lease
            release = lease.release

            def observed_release():
                try:
                    return release()
                finally:
                    self.local.lease = prior
            lease.release = observed_release
            return lease

        self.owner.acquire = observed_acquire
        run = ResourceAdmittedToolRunner.run

        def observed_run(runner, *args, **kwargs):
            request = args[0] if args else kwargs["request"]
            result = run(runner, *args, **kwargs)
            state = saved.read_json(self.owner.state_path, 4 * MIB)
            with self.lock:
                require(len(self.results) < 128, "bounded JVM lifecycle audit exhausted")
                self.results.append({"case": getattr(self.local, "case", "setup"),
                    "shared_backoff_after": state.get("proof_backoff"), "result": result.to_dict(),
                    "request": {"argv": list(request.argv), "stdin_is_empty": request.stdin in (None, "", b""),
                        "input_file_count": len(request.input_files), "output_path_count": len(request.output_paths),
                        "java_option_environment_absent": all(name not in request.environment for name in JAVA_ENV),
                        "timeout_seconds": request.limits.timeout_seconds,
                        "memory_bytes": request.limits.memory_bytes,
                        "resident_memory_bytes": request.limits.resident_memory_bytes,
                        "max_output_bytes": request.limits.max_output_bytes}})
            return result

        ResourceAdmittedToolRunner.run = observed_run
        initialize = SubprocessExecutor.__init__

        def observed_initialize(executor, *args, **kwargs):
            initialize(executor, *args, **kwargs)
            popen = executor._popen

            def observed_popen(*args, **kwargs):
                process = popen(*args, **kwargs)
                token = getattr(self.local, "cancel_live_probe", None)
                if token is not None:
                    self.local.cancel_live_probe = None
                    alive = process.pid is not None and process.poll() is None and Path("/proc", str(process.pid)).is_dir()
                    observed = time.monotonic()
                    token.cancel()
                    with self.lock:
                        self.triggers.append({"case": self.local.case, "pid": process.pid,
                            "observed_live": alive, "at_monotonic": observed,
                            "boundary": "immediately_after_actual_probe_popen"})
                return process
            executor._popen = observed_popen

        SubprocessExecutor.__init__ = observed_initialize

    def observe(self, name, args):
        super().observe(name, args)
        if name != "subprocess.Popen":
            return
        environment = args[3]
        require(isinstance(environment, dict) and all(key not in environment for key in JAVA_ENV),
                "actual JVM launch retained ambient option overrides")
        lease = self.local.lease
        with self.lock:
            self.environments.append({"case": self.local.case, "thread": threading.get_ident(),
                "launch_lease_id": lease.lease_id, "java_option_environment_absent": True})


def _rows(audit, label):
    with audit.lock:
        return ([row for row in audit.events if row["case"] == label],
                [row for row in audit.results if row["case"] == label])


def _check_phase(audit, label, java, *, interrupted=False, timeout_ceiling=10):
    launches, phases = _rows(audit, label)
    require(len(launches) == len(phases) == 1, "JVM route did not run exactly one native probe")
    phase = phases[0]
    limits, native = phase["request"], phase["result"]
    require(tuple(limits["argv"]) == (java, *JAVA_FLAGS)
            and limits["stdin_is_empty"] and not limits["input_file_count"] and not limits["output_path_count"],
            "JVM support probe ran outside the reviewed version-only command profile")
    require(limits["memory_bytes"] == 4 * 1024**3 and limits["resident_memory_bytes"] == 256 * MIB
            and limits["max_output_bytes"] == 65536 and 0 < limits["timeout_seconds"] <= timeout_ceiling,
            "JVM probe lost finite AS/RSS/output/wall bounds")
    require(limits["java_option_environment_absent"] and native["pid"] is not None and native["workspace_cleaned"],
            "JVM probe lost environment sanitization, native PID, or workspace cleanup")
    require(not any(native[key] for key in (
        "unavailable", "resource_exhausted", "output_truncated", "workspace_limit_exceeded", "timed_out")),
        "JVM identity probe failed from an unexpected resource/tool condition")
    lease = next(row for row in launches[0]["owned_leases"] if row["lease_id"] == launches[0]["launch_lease_id"])
    require(lease["cpu_slots"] == lease["child_process_slots"] == 1 and lease["memory_mb"] == 256,
            "JVM probe did not reserve one CPU/process and256MiB RSS")
    if interrupted:
        require(native["cancelled"] and native["process_tree_terminated"]
                and not Path("/proc", str(native["pid"])).exists(),
                "cancelled live JVM probe did not terminate and drain its process tree")
    else:
        require(native["returncode"] == 0 and not native["cancelled"]
                and not native["process_tree_terminated"] and not native["error"],
                "JVM identity probe did not complete successfully")
    return phase


def case(route, audit, java, label, *, parent=None):
    from ipfs_datasets_py.logic.backends.installers.state_model import (
        java_major_version, probe_java_runtime, read_java_version_banner,
    )
    identifier = label + ":" + route
    audit.local.case = identifier
    started = time.monotonic()
    ownership = {} if parent is None else {"parent_lease": parent}
    if route == "direct_banner":
        returncode, banner = read_java_version_banner(java, **ownership)
        require(returncode == 0 and java_major_version(banner) >= 17, "direct JVM banner did not identify the installed runtime")
        outcome = {"returncode": returncode, "banner": banner, "major": java_major_version(banner)}
    elif route == "runtime_probe":
        probe = probe_java_runtime(java_executable=java, minimum_major=17, **ownership)
        require(probe.usable and probe.reason_code is None and probe.major >= 17
                and probe.executable == java and probe.source == "argument", "typed JVM probe lost usable runtime identity")
        outcome = probe.to_dict()
    else:
        require(parent is None, "constructor cases retain their ordinary default ownership")
        from ipfs_datasets_py.logic.backends.tla.runners import TLCBackend, ApalacheBackend
        if route == "registry_tlc":
            from ipfs_datasets_py.logic.backends.registry import default_backend_registry
            registry = default_backend_registry()
            require(not any(_rows(audit, identifier)), "registry declaration unexpectedly probed Java")
            wrapper = registry["tla_tlc"]
            availability = wrapper.is_available()
            backend = wrapper._delegate
            require(isinstance(backend, TLCBackend) and not wrapper._delegate_error,
                    "registry did not construct its actual default TLC backend")
        else:
            backend = TLCBackend() if route == "tlc_constructor" else ApalacheBackend()
            availability = None
        require(backend._java_executable == java and backend._jvm_probe() is True,
                "default checker constructor did not retain a usable selected JVM")
        outcome = {"backend_id": backend.backend_id, "selected_java": backend._java_executable,
            "jvm_usable": backend._jvm_probe(), "checker_availability": availability,
            "model_checker_executed": False}
    phase = _check_phase(audit, identifier, java)
    native = phase["result"]
    banner = "\n".join(part for part in (native["stdout"], native["stderr"]) if part).strip()
    major = java_major_version(banner)
    require(major is not None and major >= 17, "native lifecycle lacks the actual JVM version identity")
    if route in {"direct_banner", "runtime_probe"}:
        require(outcome["banner"] == banner and outcome["major"] == major,
                "public JVM probe output differs from its actual native lifecycle")
    return {"case": identifier, "route": route, "outcome": outcome, "phase_count": 1,
        "elapsed_seconds": time.monotonic() - started, "observed_major": major,
        "banner_sha256": hashlib.sha256(banner.encode()).hexdigest(), "support_only": True}


def pre_cancel_control(audit, java, *, typed_probe):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    from ipfs_datasets_py.logic.backends.installers.state_model import probe_java_runtime, read_java_version_banner
    label = "control:pre-cancel:" + ("runtime_probe" if typed_probe else "direct_banner")
    audit.local.case = label
    token = CancellationToken()
    token.cancel()
    started = time.monotonic()
    value = (probe_java_runtime(java_executable=java, minimum_major=17, cancellation=token)
             if typed_probe else read_java_version_banner(java, cancellation=token))
    if typed_probe:
        require(not value.usable and value.reason_code == "java_probe_failed" and value.banner is None and value.major is None,
                "pre-cancelled JVM probe returned usable runtime identity")
        outcome = value.to_dict()
    else:
        require(value == (None, None), "pre-cancelled direct probe returned a version banner")
        outcome = list(value)
    launches, phases = _rows(audit, label)
    require(not launches and all(row["result"]["pid"] is None and row["result"]["cancelled"] for row in phases),
            "pre-cancelled JVM probe launched native work")
    return {"case": label, "phase_count": 0, "launch_count": 0, "lifecycle_count": len(phases),
        "outcome": outcome, "elapsed_seconds": time.monotonic() - started,
        "shared_after": previous._drained(audit)}


def live_cancel_control(audit, java, *, ambient):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    from ipfs_datasets_py.logic.backends.installers.state_model import read_java_version_banner
    from ipfs_datasets_py.logic.backends.smt.operation_budget import proof_operation_scope
    label = "control:live-cancel:" + ("ambient_operation" if ambient else "local_probe")
    audit.local.case = label
    token = CancellationToken()
    audit.local.cancel_live_probe = token

    def ambient_probe():
        with proof_operation_scope(timeout_ms=5000, cancellation=token):
            return read_java_version_banner(java)

    started = time.monotonic()
    try:
        if ambient:
            result = previous._stopped_call(ambient_probe, expected_kind="cancelled")
        else:
            value = read_java_version_banner(java, cancellation=token)
            require(value == (None, None), "cancelled live local JVM probe returned an identity")
            result = {"outcome": list(value), "elapsed_seconds": time.monotonic() - started}
    finally:
        audit.local.cancel_live_probe = None
    require(result["elapsed_seconds"] < 10, "bounded live JVM cancellation did not finish cleanup promptly")
    phase = _check_phase(audit, label, java, interrupted=True, timeout_ceiling=5 if ambient else 10)
    triggers = [row for row in audit.triggers if row["case"] == label]
    launches, _ = _rows(audit, label)
    require(len(triggers) == 1 and triggers[0]["observed_live"] and token.is_set()
            and triggers[0]["pid"] == phase["result"]["pid"]
            and launches[0]["at_monotonic"] <= triggers[0]["at_monotonic"],
            "live JVM cancellation did not follow an actual admitted live PID")
    result.update(case=label, phase_count=1, launch_count=1, ambient_operation=ambient,
        trigger=triggers[0], no_followup_launch=True, shared_after=previous._drained(audit))
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
        owner, envelope = previous.install_saved_owner(directory / "saved-scheduler-config.json")
    except BaseException:
        write(directory / "result.json", {"schema": "java-probe-admission-benchmark@1", "status": "failed",
            "failure_stage": "shared_pool_initialization", "error": traceback.format_exc(),
            "source_pins_before": before, "source_pins_after": pins(), "launches": 0, "lifecycles": 0,
            "native_execution_started": False, "shared_pool_compatibility": {"mode": "refused"}})
        raise
    audit = JavaAudit(owner)
    audit.install_observers()
    sys.addaudithook(audit.observe)
    result = {"schema": "java-probe-admission-benchmark@1", "status": "running",
        "source_pins_before": before, "runtime": saved.runtime(), "shared_before": saved.state_summary(owner.state_path),
        "runs": [], "controls": [], "checks": {}, "shared_pool_compatibility": owner._benchmark_pool_compatibility,
        "scope": "Installed JVM identity and support usability only; no model checking, proving, or installation"}
    started = time.monotonic()
    try:
        from ipfs_datasets_py.logic.backends.installers.state_model import resolve_java_executable
        java, selected_by = resolve_java_executable()
        require(java is not None, "selected installed Java executable is missing")
        result["executable"] = {"path": java, "resolved_path": str(Path(java).resolve()),
            "sha256": sha(java), "selected_by": selected_by}
        for workers in WORKERS:
            for repeat in range(REPEATS):
                label = f"parallel:{workers}:{repeat}"
                batch_started = time.monotonic()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    rows = list(pool.map(lambda route: case(route, audit, java, label), ROUTES))
                result["runs"].append({"workers": workers, "repeat": repeat,
                    "elapsed_seconds": time.monotonic() - batch_started, "cases": rows})
                write(directory / "partial.json", result)
        audit.local.case = "parent"
        with owner.acquire("validation", cpu_slots=2, memory_mb=512, child_process_slots=2, timeout=10) as parent:
            with ThreadPoolExecutor(max_workers=2) as pool:
                result["nested_cases"] = list(pool.map(lambda route: case(route, audit, java, "nested", parent=parent),
                    ("direct_banner", "runtime_probe")))
            nested = [event for event in audit.events if event["case"].startswith("nested:")]
            result["checks"]["two_native_probes_bound_to_actual_parent"] = len(nested) == 2 and all(
                any(row["lease_id"] == event["launch_lease_id"] and row.get("parent_lease_id") == parent.lease_id
                    for row in event["owned_leases"]) for event in nested)
            state = saved.read_json(owner.state_path, 4 * MIB)
            own = [row for row in state["leases"].values() if row["owner_pid"] == os.getpid()]
            result["checks"]["native_children_drained_before_parent_release"] = len(own) == 1 and own[0]["lease_id"] == parent.lease_id
        for typed_probe in (False, True):
            result["controls"].append(pre_cancel_control(audit, java, typed_probe=typed_probe))
        for ambient in (False, True):
            result["controls"].append(live_cancel_control(audit, java, ambient=ambient))
        successful = [row for run in result["runs"] for row in run["cases"]] + result["nested_cases"]
        result["checks"].update(
            all_30_default_route_cases=sum(len(run["cases"]) for run in result["runs"]) == 30,
            all_32_successful_probes_share_native_identity=len({row["banner_sha256"] for row in successful}) == 1,
            all_four_controls_passed=len(result["controls"]) == 4,
            all_34_native_launches_have_lifecycles=len(audit.events) == sum(row["result"]["pid"] is not None for row in audit.results) == 34,
            all_34_native_environments_sanitized=len(audit.environments) == 34,
            concurrent_owned_roots_observed=max(sum(not row.get("parent_lease_id") for row in event["owned_leases"])
                for event in audit.events if event["case"].startswith("parallel:")) >= 2,
            installed_executable_unchanged=sha(java) == result["executable"]["sha256"])
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
        raise
    finally:
        result["elapsed_seconds"] = time.monotonic() - started
        result["source_pins_after"] = pins()
        result["shared_after"] = saved.state_summary(owner.state_path)
        result["checks"].update(sources_stable=result["source_pins_after"] == before,
            shared_config_unchanged=previous._config_bytes(result["shared_after"]["config"]) == previous._config_bytes(envelope["config"]),
            owned_work_drained=not result["shared_after"]["owned_active_leases"] and not result["shared_after"]["owned_waiting_requests"])
        result["child_usage"] = {key: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), key)
                                 for key in ("ru_utime", "ru_stime", "ru_maxrss")}
        result["memory_observation_scope"] = "Largest reaped child in Linux KiB; not aggregate peak RSS"
        for name, value in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results),
                            ("control-audit.json", {"triggers": audit.triggers, "native_environments": audit.environments})):
            write(directory / name, value)
            result[name + "_sha256"] = sha(directory / name)
        result.update(launches=len(audit.events), lifecycles=len(audit.results),
            native_lifecycles=sum(row["result"]["pid"] is not None for row in audit.results),
            prelaunch_lifecycles=sum(row["result"]["pid"] is None for row in audit.results))
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    require(result["status"] == "passed", "native JVM probe admission qualification failed")
    print(json.dumps({key: result[key] for key in ("status", "checks", "launches", "lifecycles")}))


if __name__ == "__main__":
    main()
