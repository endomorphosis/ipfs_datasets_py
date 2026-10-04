"""Installed-tool qualification of default prover admission; never installs tools.

Uses the existing shared pool unchanged, with its real host-pressure sampler.
The benchmark imports the saved-pool guard used by the retained SMT benchmark.
Explicit paths select reviewed installed tools, not alternative runner objects.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import resource
import shlex
import statistics
import sys
import threading
import time
import traceback

import bench_codebase_restart_safety as saved

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024**2


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def require(value, message):
    if not value:
        raise AssertionError(message)


def pins():
    paths = [Path(__file__), Path(saved.__file__)]
    paths += [ROOT / "ipfs_datasets_py" / path for path in (
        "logic/backends/resource_admission.py", "logic/backends/process.py",
        "logic/backends/kernel/lean.py", "logic/backends/kernel/rocq.py",
        "logic/backends/kernel/isabelle.py", "logic/backends/tla/runners.py",
        "logic/backends/installers/isabelle_profile.py",
        "logic/external_provers/__init__.py",
        "optimizers/logic_theorem_optimizer/resource_scheduler.py",
        "optimizers/logic_theorem_optimizer/proof_resource_safety.py",
    )]
    return {str(path.resolve()): digest(path) for path in paths}


class LaunchAudit:
    """Observe actual Popen admission without replacing executors or samplers."""

    def __init__(self, owner):
        self.owner = owner
        self.events = []
        self.results = []
        self.lock = threading.Lock()
        self.local = threading.local()

    def install_observers(self):
        """Delegate unchanged admission/execution, recording their actual objects."""
        from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
        acquire = self.owner.acquire
        def observed_acquire(*args, **kwargs):
            lease = acquire(*args, **kwargs)
            require(getattr(self.local, "lease", None) is None, "unexpected nested benchmark root")
            self.local.lease = lease
            release = lease.release
            def observed_release():
                try:
                    return release()
                finally:
                    self.local.lease = None
            lease.release = observed_release
            return lease
        self.owner.acquire = observed_acquire
        run = ResourceAdmittedToolRunner.run
        def observed_run(runner, *args, **kwargs):
            result = run(runner, *args, **kwargs)
            state = saved.read_json(self.owner.state_path, 4 * MIB)
            with self.lock:
                require(len(self.results) < 1024, "bounded result audit exhausted")
                self.results.append({"case": getattr(self.local, "case", "setup"),
                                     "shared_backoff_after": state.get("proof_backoff"),
                                     "result": result.to_dict()})
            return result
        ResourceAdmittedToolRunner.run = observed_run

    def observe(self, name, args):
        if name != "subprocess.Popen":
            return
        state = saved.read_json(self.owner.state_path, 4 * MIB)
        leases = list(state["leases"].values())
        own = [row for row in leases if row["owner_pid"] == os.getpid()]
        lease = getattr(self.local, "lease", None)
        require(lease is not None and not lease.released and not lease.cancelled,
                "native subprocess launched without this thread's actual live lease")
        require(any(row["lease_id"] == lease.lease_id for row in own), "launch lease absent from durable pool")
        roots = [row for row in leases if not row.get("parent_lease_id")]
        allocations = {key: sum(row.get(key, 0) for row in roots)
                       for key in ("cpu_slots", "memory_mb", "child_process_slots")}
        config = state["config"]
        for key in allocations:
            require(allocations[key] <= config["total_" + key], "global capacity overspent")
        event = {"at_monotonic": time.monotonic(), "thread": threading.get_ident(),
                 "argv": list(args[1]), "owned_leases": own,
                 "launch_lease_id": lease.lease_id, "case": getattr(self.local, "case", "setup"),
                 "root_allocations": allocations, "waiting": len(state["waiters"])}
        with self.lock:
            require(len(self.events) < 1024, "bounded launch audit exhausted")
            self.events.append(event)


def request(family, source="", *, memory_mb=1024, timeout_ms=15000):
    from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
    from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
    return BackendRequest(
        request_id="request:admission:" + family,
        claim_id="claim:admission", declaration_id="declaration:admission",
        claim_digest="1" * 64, obligation_id="obligation:admission", obligation_digest="2" * 64,
        assumption_ids=(), logic_family=family,
        query_kind=QueryKind.SATISFIABILITY if family == "state_transition" else QueryKind.THEOREM_PROOF,
        bounds=ExecutionBounds(timeout_ms=timeout_ms, max_memory_bytes=memory_mb * MIB,
                               max_output_bytes=65536),
        payload=FrozenMap({"encoding": family, "source": source}) if source else FrozenMap(),
    )


def artifacts(valid):
    from ipfs_datasets_py.logic.backends.tla.compiler import GeneratedTLAArtifacts, TLACompileBounds
    return GeneratedTLAArtifacts(
        module_name="BoundedCounter",
        model_text=("---- MODULE BoundedCounter ----\nEXTENDS Integers\nVARIABLE n\n"
                    "Init == n = 0\nNext == n < 3 /\\ n' = n + 1\n"
                    "Spec == Init /\\ [][Next]_n\nSafety == n \\in 0.." +
                    ("3" if valid else "1") + "\n====\n"),
        tlc_config_text="SPECIFICATION Spec\nINVARIANT Safety\nCHECK_DEADLOCK FALSE\n",
        apalache_config_text="INIT Init\nNEXT Next\nINVARIANT Safety\n",
        source_map=(), losses=(), bounds=TLACompileBounds(max_steps=4),
        source_document_id="benchmark:bounded-counter", source_kind="state_transition",
        safety_properties=("Safety",), liveness_properties=(), fairness_limitations=(),
    )


def native_case(kind, valid, paths, audit, label):
    from ipfs_datasets_py.logic.backends.kernel.lean import LeanKernelBackend
    from ipfs_datasets_py.logic.backends.kernel.rocq import RocqKernelBackend
    from ipfs_datasets_py.logic.backends.tla.runners import TLCBackend
    started = time.monotonic()
    audit.local.case = label + ":" + kind + ":" + str(valid)
    if kind == "lean":
        source = "theorem admission_demo : (1 : Nat) + 1 = " + ("2" if valid else "3") + " := by decide\n"
        outcome = LeanKernelBackend(executable=str(paths["lean"])).run(request("lean4", source, memory_mb=512))
    elif kind == "rocq":
        source = "Theorem admission_demo : 1 + 1 = " + ("2" if valid else "3") + ".\nProof. reflexivity. Qed.\n"
        outcome = RocqKernelBackend(executable=str(paths["rocq"])).run(request("rocq", source))
    else:
        # This execution-only qualification uses a selected installed Java/JAR.
        # Legacy JVM discovery and lazy installation are separate open work.
        outcome = TLCBackend(executable=str(paths["tlc"]), jvm_probe=lambda: True,
                             lazy_install=False).check(artifacts(valid),
                             request=request("state_transition", memory_mb=256))
    value = outcome.to_dict()
    status = outcome.result.status.value
    processes = [row["result"] for row in audit.results if row["case"] == audit.local.case]
    require(processes, kind + " did not return an observed lifecycle result")
    for process in processes:
        require(process["pid"] is not None and process["returncode"] is not None,
                kind + " never launched: " + json.dumps(process))
        require(not any(process[key] for key in (
            "cancelled", "timed_out", "unavailable", "resource_exhausted", "output_truncated",
            "workspace_limit_exceeded")), kind + " interrupted: " + json.dumps(process))
        require(process["workspace_cleaned"], kind + " leaked workspace")
    expected = "satisfied" if kind == "tlc" else "proved"
    if valid:
        require(status == expected, kind + " positive failed: " + json.dumps(value))
    elif kind == "tlc":
        require(status == "violated", "TLC did not retain the negative counterexample: " + json.dumps(value))
    else:
        require(status not in ("proved", "satisfied"), kind + " false theorem accepted")
        require(not outcome.receipt.accepted, "false theorem receipt accepted")
        require(processes[0]["returncode"] != 0 and bool(processes[0]["stdout"] or processes[0]["stderr"]),
                kind + " negative lacks a real nonzero native diagnostic")
    return {"kind": kind, "valid": valid, "started": started,
            "ended": time.monotonic(), "outcome": value}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lean", type=Path, required=True)
    parser.add_argument("--rocq", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--tlc-jar", type=Path, required=True)
    parser.add_argument("--isabelle", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2, choices=range(1, 4))
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    before_pins = pins()
    write(directory / "command.json", {"argv": sys.argv, "cwd": str(Path.cwd())})
    saved.capture_config(directory / "saved-scheduler-config.json")
    owner, envelope = saved.install_saved_owner(directory / "saved-scheduler-config.json")
    result = {"schema": "generic-prover-admission-benchmark@1", "source_pins_before": before_pins,
              "runtime": saved.runtime(), "shared_before": saved.state_summary(owner.state_path),
              "runs": [], "checks": {}, "scope": "Installed default execution paths; no downloads or JVM discovery"}
    audit = LaunchAudit(owner)
    audit.install_observers()
    sys.addaudithook(audit.observe)
    try:
        from ipfs_datasets_py.logic.backends.kernel.isabelle import IsabelleKernelBackend
        paths = {name: getattr(args, name).resolve() for name in ("lean", "rocq", "java", "tlc_jar", "isabelle")}
        for name, path in paths.items():
            require(path.is_file(), "missing installed tool: " + name)
        result["installed_files"] = {name: {"path": str(path), "sha256": digest(path)} for name, path in paths.items()}
        # Bound JVM ergonomics independently of sampled tree RSS. This launcher
        # is local benchmark setup and never replaces the canonical runner.
        launcher = directory / "tlc-memory-aware"
        command = [str(paths["java"]), "-Xms16m", "-Xmx128m", "-XX:ActiveProcessorCount=1",
                   "-XX:+UseSerialGC", "-XX:ReservedCodeCacheSize=64m",
                   "-XX:CompressedClassSpaceSize=64m", "-cp", str(paths["tlc_jar"]), "tlc2.TLC"]
        launcher.write_text("#!/bin/sh\nexec " + shlex.join(command) + ' "$@"\n')
        launcher.chmod(0o700)
        paths["tlc"] = launcher
        from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
        from ipfs_datasets_py.logic.backends.process import CancellationToken, ToolRunLimits, ToolRunRequest
        runner = ResourceAdmittedToolRunner()
        for name, command in (("lean", (str(paths["lean"]), "--version")),
                              ("rocq", (str(paths["rocq"]), "-v")),
                              ("java", (str(paths["java"]), "-XX:ActiveProcessorCount=1", "-Xmx64m", "-version"))):
            version = runner.run(ToolRunRequest(argv=command, limits=ToolRunLimits(
                timeout_seconds=10, memory_bytes=4 * 1024**3, resident_memory_bytes=256 * MIB)))
            require(version.ok, name + " bounded version failed: " + str(version.to_dict()))
            result.setdefault("versions", {})[name] = version.to_dict()
        cases = [(kind, valid) for kind in ("lean", "rocq", "tlc") for valid in (True, False)]
        for workers in (1, 2, 4):
            for repeat in range(args.repeats):
                started = time.monotonic()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    rows = list(pool.map(lambda case: native_case(*case, paths, audit,
                        "workers:" + str(workers) + ":repeat:" + str(repeat)), cases))
                result["runs"].append({"workers": workers, "repeat": repeat,
                                       "elapsed_seconds": time.monotonic() - started, "cases": rows})
                write(directory / "partial.json", result)
        # An installed Isabelle is not permission to enlarge the shared pool.
        if owner.config.total_child_process_slots < 12:
            count = len(audit.events)
            audit.local.case = "isabelle-capacity"
            source = 'theory AdmissionDemo\nimports Main\nbegin\nlemma admission_demo: "True" by simp\nend\n'
            from ipfs_datasets_py.logic.backends.kernel.wasm import KernelCapabilityState
            refused = IsabelleKernelBackend(executable=str(paths["isabelle"]), native_probe=lambda:
                KernelCapabilityState.available_native(kernel_id="isabelle", executable=str(paths["isabelle"]),
                    version="Isabelle2025-2")).run(request("isabelle", source))
            result["isabelle_capacity_refusal"] = refused.to_dict()
            refusal = audit.results[-1]["result"]
            result["checks"]["isabelle_oversized_refused_without_launch"] = (
                len(audit.events) == count and not refused.receipt.accepted
                and refusal["resource_exhausted"] and refusal["pid"] is None
                and "child-process request exceeds configured process capacity" in refusal["error"])
        else:
            result["isabelle_capacity_refusal"] = "not applicable to this saved pool; native success not qualified"
        token = CancellationToken()
        audit.local.case = "native-cancellation"
        timer = threading.Timer(0.25, token.cancel)
        timer.start()
        try:
            cancelled = runner.run(ToolRunRequest(argv=(sys.executable, "-c", "import time; time.sleep(10)"),
                limits=ToolRunLimits(timeout_seconds=3, memory_bytes=128 * MIB)), cancellation=token)
        finally:
            timer.cancel()
        result["native_cancellation"] = cancelled.to_dict()
        result["checks"]["native_cancelled_and_cleaned"] = (
            cancelled.cancelled and cancelled.workspace_cleaned and cancelled.process_tree_terminated
            and cancelled.pid is not None and not Path("/proc", str(cancelled.pid)).exists())
        result["median_seconds"] = {
            str(n): statistics.median(row["elapsed_seconds"] for row in result["runs"] if row["workers"] == n)
            for n in (1, 2, 4)}
        result["checks"]["all_36_cases_checked" if args.repeats == 2 else "all_cases_checked"] = (
            sum(len(row["cases"]) for row in result["runs"]) == 18 * args.repeats)
        result["checks"]["concurrent_admitted_roots_observed"] = max(len(e["owned_leases"]) for e in audit.events) >= 2
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
        raise
    finally:
        result["source_pins_after"] = pins()
        result["child_resource_usage"] = {key: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), key)
                                          for key in ("ru_utime", "ru_stime", "ru_maxrss")}
        result["child_memory_observation_scope"] = "Linux ru_maxrss in KiB: largest reaped child, not aggregate peak RSS"
        result["shared_after"] = saved.state_summary(owner.state_path)
        result["checks"].update(
            sources_stable=before_pins == result["source_pins_after"],
            shared_config_unchanged=result["shared_after"]["config"] == envelope["config"],
            owned_leases_and_waiters_drained=not result["shared_after"]["owned_active_leases"]
                and not result["shared_after"]["owned_waiting_requests"],
        )
        write(directory / "launch-audit.json", audit.events)
        write(directory / "lifecycle-audit.json", audit.results)
        result["lifecycle_audit_sha256"] = digest(directory / "lifecycle-audit.json")
        result["launch_audit_sha256"] = digest(directory / "launch-audit.json")
        result["launches"] = len(audit.events)
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    require(result["status"] == "passed", "qualification checks failed")
    print(json.dumps({"status": result["status"], "checks": result["checks"],
                      "launches": result["launches"], "median_seconds": result["median_seconds"]}))


if __name__ == "__main__":
    main()
