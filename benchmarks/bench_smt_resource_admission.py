"""Qualify installed SMT default entry points against the unchanged shared pool.

No tools are installed and no pressure samples or pool limits are substituted.
Direct legacy compiler/differential APIs remain outside this qualification.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import statistics
import sys
import threading
import time
import traceback

import bench_codebase_restart_safety as saved
from bench_generic_prover_admission import LaunchAudit, require, write

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024**2


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pins():
    files = [Path(__file__), ROOT / "benchmarks/bench_generic_prover_admission.py", Path(saved.__file__)]
    files += [ROOT / "ipfs_datasets_py" / name for name in (
        "logic/backends/smt/admitted.py", "logic/backends/z3/__init__.py", "logic/backends/cvc5/__init__.py",
        "logic/backends/registry.py", "logic/backends/smt/execution_v2.py",
        "logic/backends/smt/compiler.py", "logic/backends/smt/differential.py",
        "logic/backends/z3/compiler.py", "logic/backends/cvc5/compiler.py",
        "logic/backends/process.py", "logic/backends/resource_admission.py",
        "logic/software_contracts/codebase_smt_protocol.py", "logic/parsers/smtlib.py",
        "logic/syntax_core/contracts.py",
        "optimizers/logic_theorem_optimizer/resource_scheduler.py",
        "optimizers/logic_theorem_optimizer/proof_resource_safety.py",
    )]
    return {str(path): sha(path) for path in files}


class Audit(LaunchAudit):
    """Observe actual nested leases; preserve real admission and execution."""

    def install_observers(self):
        from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
        acquire = self.owner.acquire

        def observed_acquire(*args, **kwargs):
            lease = acquire(*args, **kwargs)
            previous = getattr(self.local, "lease", None)
            self.local.lease = lease
            release = lease.release

            def observed_release():
                try:
                    return release()
                finally:
                    self.local.lease = previous
            lease.release = observed_release
            return lease

        self.owner.acquire = observed_acquire
        run = ResourceAdmittedToolRunner.run

        def observed_run(runner, *args, **kwargs):
            request = args[0] if args else kwargs["request"]
            result = run(runner, *args, **kwargs)
            state = saved.read_json(self.owner.state_path, 4 * MIB)
            with self.lock:
                require(len(self.results) < 1024, "bounded lifecycle audit exhausted")
                self.results.append({"case": getattr(self.local, "case", "setup"),
                    "shared_backoff_after": state.get("proof_backoff"), "result": result.to_dict(),
                    "request": {"argv": list(request.argv),
                        "stdin_sha256": hashlib.sha256(request.stdin.encode("utf-8")).hexdigest(),
                        "terminal_command": request.stdin.strip().splitlines()[-1] if request.stdin.strip() else "",
                        "timeout_seconds": request.limits.timeout_seconds,
                        "memory_bytes": request.limits.memory_bytes,
                        "resident_memory_bytes": request.limits.resident_memory_bytes,
                        "max_output_bytes": request.limits.max_output_bytes}})
            return result

        ResourceAdmittedToolRunner.run = observed_run

    def observe(self, name, args):
        super().observe(name, args)
        if name == "subprocess.Popen":
            token = getattr(self.local, "cancel_on_query_launch", None)
            if token is not None and "-in" in args[1]:
                self.local.cancel_on_query_launch = None
                timer = threading.Timer(0.05, token.cancel)
                timer.daemon = True
                timer.start()
                self.local.cancel_timer = timer


def bounds(**kwargs):
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
    return ExecutionBounds(**{"timeout_ms": 5000, "max_steps": 100000,
        "max_memory_bytes": 128 * MIB, "max_output_bytes": 65536, **kwargs})


def obligation(valid):
    from ipfs_datasets_py.logic.backends.smt.compiler import (
        INT_SORT, SmtFunDecl, SmtNamedAssertion, SmtObligation, SmtQueryMode,
        SmtTerm, SmtTermKind, term_symbol, term_int,
    )
    x = term_symbol("x")
    return SmtObligation(
        obligation_id="obl:admission:" + str(valid).lower(),
        query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
        features=("arithmetic", "equality", "verification_conditions"),
        goal=SmtTerm(SmtTermKind.GT, arguments=(x, term_int(0))),
        assumptions=(SmtNamedAssertion(formula=SmtTerm(SmtTermKind.GE,
            arguments=(x, term_int(1))), name="assume_ge_one"),) if valid else (),
        functions=(SmtFunDecl(name="x", range=INT_SORT, is_const=True),),
        request_unsat_core=True, request_model=True,
        property_ids=("property:admission",),
    )


def registry_request(solver, valid, *, source=None, selected_bounds=None):
    from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
    from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, QueryKind
    return BackendRequest(
        request_id="request:admission:" + solver, claim_id="claim:admission",
        declaration_id="declaration:admission", claim_digest="1" * 64,
        obligation_id="obligation:admission", obligation_digest="2" * 64,
        assumption_ids=(), logic_family="first_order", query_kind=QueryKind.THEOREM_PROOF,
        requested_backend_id=solver, bounds=selected_bounds or bounds(),
        payload=FrozenMap({"encoding": "smtlib2", "source": source} if source else
                          {"encoding": "smt-expression/v1", "goal": "true" if valid else "false"}),
    )


def case(kind, solver, valid, audit, label, *, parent=None):
    from ipfs_datasets_py.logic.backends.z3 import Z3SoftwareVerificationBackend
    from ipfs_datasets_py.logic.backends.cvc5 import CVC5SoftwareVerificationBackend
    from ipfs_datasets_py.logic.backends.registry import default_backend_registry
    from ipfs_datasets_py.logic.backends.smt.execution_v2 import SmtExecutionEngineV2, SmtExecutionRequestV2
    audit.local.case = label + ":" + kind + ":" + solver + ":" + str(valid)
    started = time.monotonic()
    if kind == "registry":
        attempt, result = default_backend_registry().run(registry_request(solver, valid))
        value = {"attempt": attempt.to_dict(), "result": result.to_dict()}
        status = result.status.value
    elif kind == "public":
        backend_type = Z3SoftwareVerificationBackend if solver == "z3" else CVC5SoftwareVerificationBackend
        outcome = backend_type(parent_lease=parent).run(obligation(valid), bounds=bounds())
        value = outcome.to_dict()
        status = outcome.result.status.value
        require(bool(outcome.solver_version), "native public outcome lacks a version")
        if valid:
            require("assume_ge_one" in outcome.unsat_core, "native core missing expected assumption")
        else:
            require("define-fun" in outcome.model_text, "native countermodel missing")
    else:
        outcome = SmtExecutionEngineV2().execute(SmtExecutionRequestV2(
            request_id="request:v2:admission", obligation=obligation(valid),
            provider=solver, mode="pinned_solver", bounds=bounds(),
        ))
        value = outcome.to_dict()
        status = outcome.disposition.value
    require(status == ("proved" if valid else "disproved"), "wrong native disposition: " + json.dumps(value))
    phases = [row for row in audit.results if row["case"] == audit.local.case]
    commands = ["(check-sat)", ""] if kind == "registry" else [
        "(check-sat)", "(get-unsat-core)" if valid else "(get-model)", ""]
    if solver == "differential":
        commands *= 2
    require([row["request"]["terminal_command"] for row in phases] == commands,
            "native phase count/order/artifact differs")
    processes = [row["result"] for row in phases]
    for process in processes:
        require(process["pid"] is not None and process["returncode"] == 0, "native process failed: " + json.dumps(process))
        require(not any(process[k] for k in ("timed_out", "cancelled", "unavailable",
            "resource_exhausted", "output_truncated", "workspace_limit_exceeded",
            "process_tree_terminated", "error")), "incomplete native lifecycle")
        require(process["workspace_cleaned"], "workspace cleanup incomplete")
    return {"kind": kind, "solver": solver, "valid": valid, "status": status,
            "started": started, "ended": time.monotonic(), "outcome": value}


def pigeonholes(pigeons=18):
    holes = pigeons - 1
    lines = ["(set-logic QF_UF)"]
    lines += [f"(declare-fun p{i}_{j} () Bool)" for i in range(pigeons) for j in range(holes)]
    lines += ["(assert (or " + " ".join(f"p{i}_{j}" for j in range(holes)) + "))" for i in range(pigeons)]
    lines += [f"(assert (or (not p{i}_{j}) (not p{k}_{j})))"
              for j in range(holes) for i in range(pigeons) for k in range(i + 1, pigeons)]
    return "\n".join(lines) + "\n(check-sat)\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    before = pins()
    write(directory / "command.json", {"argv": sys.argv, "cwd": str(Path.cwd())})
    saved.capture_config(directory / "saved-scheduler-config.json")
    owner, envelope = saved.install_saved_owner(directory / "saved-scheduler-config.json")
    audit = Audit(owner)
    audit.install_observers()
    sys.addaudithook(audit.observe)
    result = {"schema": "smt-resource-admission-benchmark@1", "source_pins_before": before,
        "runtime": saved.runtime(), "shared_before": saved.state_summary(owner.state_path),
        "runs": [], "checks": {}, "status": "running"}
    try:
        result["executables"] = {}
        for name in ("z3", "cvc5"):
            path = shutil.which(name)
            require(path is not None, "required native tool is not installed: " + name)
            result["executables"][name] = {"path": path, "sha256": sha(path)}
        cases = [(kind, solver, valid) for kind in ("registry", "public", "v2")
                 for solver in ("z3", "cvc5") for valid in (True, False)]
        cases += [("v2", "differential", valid) for valid in (True, False)]
        for workers in (1, 2, 4):
            for repeat in range(2):
                label = f"parallel:{workers}:{repeat}"
                started = time.monotonic()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    rows = list(pool.map(lambda item: case(*item, audit, label), cases))
                result["runs"].append({"workers": workers, "repeat": repeat,
                    "elapsed_seconds": time.monotonic() - started, "cases": rows})
                write(directory / "partial.json", result)
        audit.local.case = "parent"
        with owner.acquire("validation", cpu_slots=2, memory_mb=256, child_process_slots=2, timeout=5) as parent:
            with ThreadPoolExecutor(max_workers=2) as pool:
                result["nested_cases"] = list(pool.map(lambda solver:
                    case("public", solver, True, audit, "nested", parent=parent), ("z3", "cvc5")))
            nested = [e for e in audit.events if e["case"].startswith("nested:")]
            result["checks"]["native_children_bound_to_actual_parent"] = len(nested) == 6 and all(
                any(row["lease_id"] == event["launch_lease_id"] and row.get("parent_lease_id") == parent.lease_id
                    for row in event["owned_leases"]) for event in nested)
            state = saved.read_json(owner.state_path, 4 * MIB)
            own = [r for r in state["leases"].values() if r["owner_pid"] == os.getpid()]
            result["checks"]["native_children_drained_before_parent_release"] = len(own) == 1 and own[0]["lease_id"] == parent.lease_id
        from ipfs_datasets_py.logic.backends.process import CancellationToken
        from ipfs_datasets_py.logic.backends.z3 import Z3Backend
        token = CancellationToken()
        audit.local.case = "cancelled-native-z3"
        audit.local.cancel_on_query_launch = token
        count = len(audit.events)
        try:
            attempt, outcome = Z3Backend().run(registry_request("z3", True, source=pigeonholes(),
                selected_bounds=bounds(timeout_ms=3000, max_steps=1_000_000_000,
                                       max_memory_bytes=256 * MIB, max_output_bytes=MIB)), cancellation=token)
        finally:
            timer = getattr(audit.local, "cancel_timer", None)
            if timer is not None:
                timer.cancel()
        result["native_cancellation"] = {"attempt": attempt.to_dict(), "result": outcome.to_dict()}
        interrupted = audit.results[-1]["result"]
        result["checks"]["native_cancellation_no_success_or_followup_launch"] = (
            len(audit.events) == count + 1 and audit.results[-1]["case"] == "cancelled-native-z3"
            and interrupted["cancelled"] and interrupted["workspace_cleaned"]
            and not any(interrupted[key] for key in ("resource_exhausted", "output_truncated", "workspace_limit_exceeded"))
            and interrupted["pid"] is not None and interrupted["process_tree_terminated"]
            and not Path("/proc", str(interrupted["pid"])).exists()
            and outcome.status.value not in ("proved", "disproved", "satisfiable", "unsatisfiable"))
        result["median_seconds"] = {str(n): statistics.median(r["elapsed_seconds"] for r in result["runs"] if r["workers"] == n)
                                    for n in (1, 2, 4)}
        result["checks"]["all_84_expected_outcomes"] = sum(len(r["cases"]) for r in result["runs"]) == 84
        result["checks"]["concurrent_owned_roots_observed"] = max(
            sum(not r.get("parent_lease_id") for r in event["owned_leases"])
            for event in audit.events if event["case"].startswith("parallel:")) >= 2
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
        raise
    finally:
        result["source_pins_after"] = pins()
        result["shared_after"] = saved.state_summary(owner.state_path)
        result["checks"].update(sources_stable=result["source_pins_after"] == before,
            shared_config_unchanged=result["shared_after"]["config"] == envelope["config"],
            owned_work_drained=not result["shared_after"]["owned_active_leases"] and not result["shared_after"]["owned_waiting_requests"])
        result["child_usage"] = {key: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), key)
                                 for key in ("ru_utime", "ru_stime", "ru_maxrss")}
        result["memory_observation_scope"] = "Largest reaped child in Linux KiB; not aggregate peak RSS"
        for name, value in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results)):
            write(directory / name, value)
            result[name + "_sha256"] = sha(directory / name)
        result.update(launches=len(audit.events), lifecycles=len(audit.results))
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    require(result["status"] == "passed", "benchmark checks failed")
    print(json.dumps({key: result[key] for key in ("status", "checks", "launches", "median_seconds")}))


if __name__ == "__main__":
    main()
