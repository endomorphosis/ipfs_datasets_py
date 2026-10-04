"""Qualify native public SMT consumers under the unchanged shared resource pool.

No installs, pressure substitutions, pool reconfiguration, or legacy benchmark
execution occur. Per-solver reservations and process limits do not establish
hard aggregate containment or a whole-pipeline deadline.
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
import time
import traceback

import bench_smt_resource_admission as previous
from bench_smt_resource_admission import Audit, MIB, bounds, obligation, require, saved, sha, write

ROOT = Path(__file__).resolve().parents[1]
WORKERS = (1, 2, 4)
REPEATS = 2


def pins():
    """Bind this harness, reused observers, and both legacy and public routes."""
    captured = previous.pins()
    paths = [Path(__file__)]
    paths += [ROOT / "ipfs_datasets_py" / name for name in (
        "logic/backends/smt/__init__.py", "logic/backends/smt/admitted_differential.py",
        "logic/software_verification/__init__.py", "logic/software_verification/admitted_pipeline.py",
        "logic/software_verification/pipeline.py", "logic/software_verification/source_adapters.py",
        "logic/software_verification/vc.py", "logic/software_verification/program.py",
        "logic/software_verification/contracts.py", "logic/software_verification/receipts.py",
        "logic/verification_api.py", "logic/parsers/classical_adapters.py",
    )]
    captured.update({str(path.resolve()): sha(path) for path in paths})
    return captured


def _parent_backends(parent):
    if parent is None:
        return {}
    from ipfs_datasets_py.logic.backends.z3 import Z3SoftwareVerificationBackend
    from ipfs_datasets_py.logic.backends.cvc5 import CVC5SoftwareVerificationBackend
    return {"z3_backend": Z3SoftwareVerificationBackend(parent_lease=parent),
            "cvc5_backend": CVC5SoftwareVerificationBackend(parent_lease=parent)}


def _check_report(report, valid, *, expected_obligation=None):
    expected = "agree_proved" if valid else "agree_disproved"
    require(report.classification.value == expected and report.agreement,
            "wrong differential classification: " + json.dumps(report.to_dict()))
    require(not report.disagreement_evidence, "agreement retained contradictory evidence")
    if expected_obligation is not None:
        require(report.obligation_id == expected_obligation.obligation_id,
                "differential report lost the fixture obligation")
    compilation = report.compilation
    require(compilation.obligation_id == report.obligation_id
            and compilation.script.digest == report.script_digest,
            "report lost its canonical compilation identity")
    require(compilation.receipt.source_identity == compilation.source_identity
            and compilation.receipt.target_identity == compilation.target_identity,
            "translation receipt lost its source/target identities")
    require(compilation.script.request_model and compilation.script.request_unsat_core,
            "fixture must request both conditional artifact branches")
    for solver, outcome in (("z3", report.left), ("cvc5", report.right)):
        require(outcome.backend_id == solver and bool(outcome.solver_version),
                "differential outcome lacks the native solver/version")
        require(outcome.obligation_id == report.obligation_id
                and outcome.compilation.script.digest == report.script_digest,
                "differential participant lost the shared translation")
        require(outcome.result.status.value == ("proved" if valid else "disproved"),
                "unexpected participant result")
        require(outcome.verdict.value == ("unsat" if valid else "sat"),
                "unexpected native participant verdict")
        if valid:
            require(bool(outcome.unsat_core) and not outcome.model_text,
                    "proved fixture lacks its native core or retained an inapplicable model")
        else:
            require("define-fun" in outcome.model_text and not outcome.unsat_core,
                    "refuted fixture lacks its native model or retained an inapplicable core")
    return expected


def _check_phases(audit, label, kind, valid):
    with audit.lock:
        phases = [row for row in audit.results if row["case"] == label]
        launches = [row for row in audit.events if row["case"] == label]
    commands = (["(check-sat)", ""] if kind == "classical" else
                ["(check-sat)", "(get-unsat-core)" if valid else "(get-model)", ""] * 2)
    require([row["request"]["terminal_command"] for row in phases] == commands,
            "native phase count/order/artifact differs for " + label)
    require(len(launches) == len(phases), "not every native phase has one admitted launch")
    for row in phases:
        request, process = row["request"], row["result"]
        require(process["pid"] is not None and process["returncode"] == 0,
                "native process did not complete successfully: " + json.dumps(process))
        require(not any(process[key] for key in (
            "timed_out", "cancelled", "unavailable", "resource_exhausted", "output_truncated",
            "workspace_limit_exceeded", "process_tree_terminated", "error")),
            "native phase retained an unsafe lifecycle result")
        require(process["workspace_cleaned"], "native phase leaked its workspace")
        require(request["memory_bytes"] == request["resident_memory_bytes"] == 128 * MIB,
                "native phase lost its finite address-space/RSS bounds")
        require(0 < request["timeout_seconds"] <= 5 and 0 < request["max_output_bytes"] <= 65536,
                "native phase lost its bounded wall/output budget")
    if kind != "classical":
        require(phases[0]["request"]["stdin_sha256"] == phases[3]["request"]["stdin_sha256"]
                and phases[1]["request"]["stdin_sha256"] == phases[4]["request"]["stdin_sha256"],
                "native participants received different query/artifact bytes")
    return len(phases)


def case(kind, solver, valid, audit, label, *, parent=None):
    """One tiny semantic fixture through an ordinary public consumer default."""
    audit.local.case = label + ":" + kind + ":" + solver + ":" + str(valid)
    identifier = audit.local.case
    started = time.monotonic()
    fixture = {}
    if kind in {"public_differential", "verification_api"}:
        if kind == "public_differential":
            from ipfs_datasets_py.logic.backends.smt import run_z3_cvc5_differential
        else:
            from ipfs_datasets_py.logic.verification_api import run_z3_cvc5_differential
        expected = obligation(valid)
        outcome = run_z3_cvc5_differential(expected, bounds=bounds(), **_parent_backends(parent))
        status = _check_report(outcome, valid, expected_obligation=expected)
        fixture = {"obligation": expected.to_dict()}
    elif kind == "source_pipeline":
        from ipfs_datasets_py.logic.software_verification import SourceToVerificationPipeline
        from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
        source = "def increment(x: int) -> int:\n    return " + ("x + 1" if valid else "x") + "\n"
        contract = ContractSpec("increment", postconditions=("result == x + 1",))
        path, revision = "benchmark_increment.py", "benchmark:smt-consumer-admission"
        outcome = SourceToVerificationPipeline(bounds=bounds(), include_supervisor_evidence=False,
            **_parent_backends(parent)).run(source, path=path, language="python",
                                          contracts=[contract], revision=revision)
        require(outcome.status.value == "success" and len(outcome.obligation_results) == 1,
                "source fixture failed its bounded translation: " + json.dumps(outcome.to_dict()))
        item = outcome.obligation_results[0]
        require(item.solver_executed and item.differential is not None,
                "source pipeline did not execute its differential obligation")
        status = _check_report(item.differential, valid, expected_obligation=item.smt_obligation)
        require(outcome.proved is valid and outcome.disproved is (not valid),
                "source pipeline changed its mathematical result")
        bindings = outcome.bindings
        require(bindings is not None and bindings.source.content_sha256 == hashlib.sha256(source.encode()).hexdigest()
                and bindings.source.path == path and bindings.source.source_revision == revision,
                "source pipeline lost exact source bytes/path/revision")
        require(bindings.source.source_ref_ids and bindings.source.span_ids
                and bindings.source.program_id == outcome.program.program_id,
                "source pipeline lost source spans/program identity")
        require(item.compilation.receipt.receipt_id in bindings.translation_receipt_ids
                and item.property_id in bindings.property_ids
                and item.vc_obligation.parent_contract_id in bindings.parent_contract_ids,
                "source pipeline lost contract/property/translation bindings")
        require(set(bindings.tool_ids) >= {"z3", "cvc5"}, "source binding omitted a solver")
        fixture = {"source": source, "path": path, "revision": revision, "contract": contract.to_dict()}
    elif kind == "classical":
        require(parent is None, "classical parent injection is not part of this fixture")
        from ipfs_datasets_py.logic.parsers.classical_adapters import ClassicalBackendAdapter, content_digest
        from ipfs_datasets_py.logic.parsers.smtlib import parse_smtlib2, print_smtlib2
        source = "(set-logic QF_LIA)\n(assert " + ("true" if valid else "false") + ")\n(check-sat)\n"
        parsed = parse_smtlib2(source)
        require(parsed.document is not None, "controlled SMT-LIB fixture did not parse")
        printed = print_smtlib2(parsed.document)
        outcome = ClassicalBackendAdapter().run_smt(parsed.document, route=solver, bounds=bounds())
        status = "satisfiable" if valid else "unsatisfiable"
        require(outcome.status.value == status and outcome.is_conclusive,
                "wrong classical SMT disposition: " + json.dumps(outcome.to_dict()))
        require(outcome.authority.value == outcome.receipt.authority_ceiling.value == "satisfiability",
                "classical parser join changed its authority ceiling")
        require(outcome.receipt.exactness.value == "exact"
                and outcome.receipt.availability.value == "available",
                "classical parser join lost exact native availability")
        require(outcome.source_binding.source_digest == content_digest(printed)
                and outcome.source_binding.request_digest == outcome.backend_request.digest,
                "classical parser join lost its source/request identity")
        fixture = {"source": source, "canonical_source": printed,
                   "source_binding": outcome.source_binding.to_dict()}
    else:
        raise AssertionError("unknown bounded benchmark case")
    phase_count = _check_phases(audit, identifier, kind, valid)
    return {"case": identifier, "kind": kind, "solver": solver, "valid": valid,
            "status": status, "started": started, "ended": time.monotonic(),
            "phase_count": phase_count, "fixture": fixture, "outcome": outcome.to_dict()}


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
    saved.capture_config(directory / "saved-scheduler-config.json")
    owner, envelope = saved.install_saved_owner(directory / "saved-scheduler-config.json")
    audit = Audit(owner)
    audit.install_observers()
    sys.addaudithook(audit.observe)
    result = {"schema": "smt-consumer-admission-benchmark@1", "status": "running",
        "source_pins_before": before, "runtime": saved.runtime(),
        "shared_before": saved.state_summary(owner.state_path), "runs": [], "checks": {},
        "scope": "Installed public consumer defaults; compilation outside reservations; no aggregate pipeline deadline or hard cgroup containment"}
    started = time.monotonic()
    try:
        result["executables"] = {}
        for solver in ("z3", "cvc5"):
            path = shutil.which(solver)
            require(path is not None, "native solver is not installed: " + solver)
            result["executables"][solver] = {"path": path, "sha256": sha(path)}
        cases = [(kind, "differential", valid)
                 for kind in ("public_differential", "verification_api", "source_pipeline")
                 for valid in (True, False)]
        cases += [("classical", solver, valid) for solver in ("z3", "cvc5") for valid in (True, False)]
        for workers in WORKERS:
            for repeat in range(REPEATS):
                label = f"parallel:{workers}:{repeat}"
                batch_started = time.monotonic()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    rows = list(pool.map(lambda item: case(*item, audit, label), cases))
                require(sum(row["phase_count"] for row in rows) == 44, "batch lost native phases")
                result["runs"].append({"workers": workers, "repeat": repeat,
                    "elapsed_seconds": time.monotonic() - batch_started, "cases": rows})
                write(directory / "partial.json", result)
        audit.local.case = "parent"
        with owner.acquire("validation", cpu_slots=2, memory_mb=256,
                           child_process_slots=2, timeout=5) as parent:
            nested_cases = (("public_differential", "differential", True),
                            ("source_pipeline", "differential", False))
            with ThreadPoolExecutor(max_workers=2) as pool:
                result["nested_cases"] = list(pool.map(
                    lambda item: case(*item, audit, "nested", parent=parent), nested_cases))
            nested = [event for event in audit.events if event["case"].startswith("nested:")]
            result["checks"]["native_children_bound_to_actual_parent"] = len(nested) == 12 and all(
                any(row["lease_id"] == event["launch_lease_id"] and row.get("parent_lease_id") == parent.lease_id
                    for row in event["owned_leases"]) for event in nested)
            state = saved.read_json(owner.state_path, 4 * MIB)
            own = [row for row in state["leases"].values() if row["owner_pid"] == os.getpid()]
            result["checks"]["children_drained_before_parent_release"] = (
                len(own) == 1 and own[0]["lease_id"] == parent.lease_id)
        result["median_seconds"] = {str(workers): statistics.median(
            run["elapsed_seconds"] for run in result["runs"] if run["workers"] == workers)
            for workers in WORKERS}
        result["checks"].update(
            all_60_expected_outcomes=sum(len(run["cases"]) for run in result["runs"]) == 60,
            all_264_batch_native_phases=sum(row["phase_count"] for run in result["runs"] for row in run["cases"]) == 264,
            all_276_native_launches_have_lifecycles=len(audit.events) == len(audit.results) == 276,
            concurrent_owned_roots_observed=max(sum(not row.get("parent_lease_id") for row in event["owned_leases"])
                for event in audit.events if event["case"].startswith("parallel:")) >= 2,
            installed_executables_unchanged=all(sha(value["path"]) == value["sha256"]
                                               for value in result["executables"].values()))
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
        raise
    finally:
        result["elapsed_seconds"] = time.monotonic() - started
        result["source_pins_after"] = pins()
        result["shared_after"] = saved.state_summary(owner.state_path)
        result["checks"].update(
            sources_stable=result["source_pins_after"] == before,
            shared_config_unchanged=result["shared_after"]["config"] == envelope["config"],
            owned_work_drained=not result["shared_after"]["owned_active_leases"]
                               and not result["shared_after"]["owned_waiting_requests"])
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
    require(result["status"] == "passed", "native consumer benchmark checks failed")
    print(json.dumps({key: result[key] for key in ("status", "checks", "launches", "median_seconds")}))


if __name__ == "__main__":
    main()
