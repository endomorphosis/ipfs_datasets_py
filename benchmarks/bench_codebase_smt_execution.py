"""Bounded conditional SMT execution and solver-free evidence consumption.

This is a new protocol generation. It does not alter the previous query
qualification, and its execution counts must be derived from native phase
receipts. Resource fault fixtures are synthetic local executables, never proof
evidence. Native Z3/CVC5 runs still establish conditional mathematical claims.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import os
import platform
import subprocess
import time
import traceback

import bench_codebase_evidence_queries as base

SCHEMA = "codebase-bounded-smt-execution-benchmark@1"

SMT_FIXTURE = """(set-logic QF_LIA)
(set-option :produce-models true)
(set-option :produce-unsat-cores true)
(declare-fun n () Int)
(assert (! false :named premise))
(check-sat)
(get-model)
(get-unsat-core)
"""


def write_solver_fixture(directory: Path, mode: str, *, verdict: str = "unsat") -> Path:
    """Create an inert, finite test tool; callers own its admission and limits."""
    directory.mkdir(parents=True, exist_ok=True)
    source = r'''
import json, os, pathlib, signal, subprocess, sys, time
root = pathlib.Path(ROOT)
version = any(arg in ('-version', '--version') for arg in sys.argv[1:])
def identity(path):
    fields = pathlib.Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()
    path.write_text(json.dumps({'pid': os.getpid(), 'birth': int(fields[19]), 'ready_at': time.monotonic()}))
def journal(kind):
    with (root / 'phases.jsonl').open('a') as stream:
        stream.write(json.dumps({'kind': kind, 'pid': os.getpid(), 'argv': sys.argv}) + '\n')
if version:
    journal('version')
    if MODE == 'version_sleep':
        identity(root / 'ready.json')
        time.sleep(30)
    print('Z3 version bounded-fixture')
    sys.exit(0)
if MODE == 'blocked_stdin':
    journal('blocked_stdin')
    identity(root / 'ready.json')
    time.sleep(30)
    sys.exit(0)
source = sys.stdin.read()
artifact = '(get-model)' in source or '(get-unsat-core)' in source
kind = 'artifact' if artifact else 'verdict'
journal(kind)
identity(root / 'leader.json')
if MODE == 'descendant_cancel':
    leaf = "import pathlib,os,sys,json,time,signal; signal.signal(signal.SIGTERM,signal.SIG_IGN); fields=pathlib.Path('/proc/self/stat').read_text().rsplit(')',1)[1].split(); pathlib.Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),'birth':int(fields[19]),'ready_at':time.monotonic()})); time.sleep(30)"
    subprocess.Popen([sys.executable, '-c', leaf, str(root / 'child.json')], start_new_session=True)
    while not (root / 'child.json').exists(): time.sleep(.005)
    identity(root / 'ready.json')
    time.sleep(30)
if MODE == 'as_exhaustion':
    allocation = bytearray(1024 * 1024 * 1024)
if MODE == 'rss_exhaustion':
    leaf = "import pathlib,os,sys,json,time; fields=pathlib.Path('/proc/self/stat').read_text().rsplit(')',1)[1].split(); pathlib.Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),'birth':int(fields[19]),'ready_at':time.monotonic()})); allocation=bytearray(72*1024*1024); time.sleep(30)"
    subprocess.Popen([sys.executable, '-c', leaf, str(root / 'child.json')], start_new_session=True)
    allocation = bytearray(72 * 1024 * 1024)
    time.sleep(30)
if MODE == 'nonzero':
    print(VERDICT, flush=True)
    sys.exit(7)
if MODE in ('stdout_flood', 'stderr_flood'):
    print(VERDICT, flush=True)
    stream = sys.stdout if MODE == 'stdout_flood' else sys.stderr
    stream.write('x' * (2 * 1024 * 1024))
    stream.flush()
    sys.exit(0)
if MODE == 'mismatch' and artifact:
    print('sat' if VERDICT == 'unsat' else 'unsat')
    print('()')
    sys.exit(0)
if MODE == 'artifact_flood' and artifact:
    print(VERDICT)
    print('x' * (2 * 1024 * 1024))
    sys.exit(0)
print(VERDICT)
if artifact:
    print('((define-fun n () Int 0))' if VERDICT == 'sat' else '(premise)')
'''
    path = directory / "solver-fixture"
    path.write_text(f"#!{sys.executable}\nROOT={str(directory.resolve())!r}\nMODE={mode!r}\nVERDICT={verdict!r}\n" + source)
    path.chmod(0o700)
    return path


def recorded_phases(directory: Path) -> list[dict]:
    path = directory / "phases.jsonl"
    return [] if not path.exists() else [json.loads(line) for line in path.read_text().splitlines()]


def process_identity(pid: int):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[19]), fields[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def retained_processes(directory: Path) -> list[dict]:
    return [json.loads(path.read_text()) for path in sorted(directory.glob("*.json"))
            if path.name in {"leader.json", "child.json", "ready.json"}]


def live_retained_processes(directory: Path) -> list[dict]:
    live = []
    for record in retained_processes(directory):
        current = process_identity(record["pid"])
        if current is not None and current[0] == record["birth"] and current[1] != "Z":
            live.append(record)
    return live


class ReadyCancellation:
    """Wait for an actual phase to run long enough for ancestry sampling."""

    def __init__(self, directory: Path, delay_seconds: float = .25):
        self.directory, self.delay_seconds = directory, delay_seconds

    def is_set(self):
        import time
        path = self.directory / "ready.json"
        if not path.exists():
            return False
        try:
            return time.monotonic() - json.loads(path.read_text())["ready_at"] >= self.delay_seconds
        except json.JSONDecodeError:
            return False


def source_pins():
    pins = base.source_pins()
    for path in (Path(__file__).resolve(),
        base.ROOT / "ipfs_datasets_py/logic/software_contracts/codebase_smt_execution.py",
        base.ROOT / "ipfs_datasets_py/logic/software_contracts/codebase_smt_protocol.py",
        base.ROOT / "ipfs_datasets_py/logic/software_contracts/codebase_smt_compat.py",
        base.ROOT / "ipfs_datasets_py/logic/parsers/smtlib.py",
        base.ROOT / "ipfs_datasets_py/logic/syntax_core/contracts.py",
        base.ROOT / "ipfs_datasets_py/logic/backends/process.py"):
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return pins


class ProcessAudit(base.ProcessAudit):
    """Retain native helper argv while counting the tool that prlimit execs."""

    def observe(self, event, arguments):
        if event != "subprocess.Popen":
            return
        executable, argv, cwd, _environment = arguments
        values = [os.fsdecode(item) for item in argv] if isinstance(argv, (list, tuple)) else [str(argv)]
        actual_name = Path(os.fsdecode(executable)).name
        logical = values[values.index("--") + 1:] if actual_name == "prlimit" and "--" in values else values
        name = Path(logical[0]).name if logical else actual_name
        kind = ("version" if name in {"z3", "cvc5"} and any(item in {"--version", "-version"} for item in logical)
                else "solver_query" if name in {"z3", "cvc5"} else "git" if name == "git" else
                "synthetic_stress" if name == "solver-fixture" else "other")
        key = self.stage + ":" + kind
        self.counts[key] = self.counts.get(key, 0) + 1
        base.require(len(self.events) < 16384, "bounded process audit retention exceeded")
        self.events.append({"stage": self.stage, "kind": kind, "executable": os.fsdecode(executable),
                            "argv": values, "logical_argv": logical, "cwd": None if cwd is None else os.fsdecode(cwd)})
        if self.only_git and actual_name != "git":
            raise AssertionError("historical lookup attempted a non-Git process: " + actual_name)


def stress(directory, deadline, audit):
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
    from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources
    from ipfs_datasets_py.logic.software_contracts.codebase_smt_execution import (
        make_codebase_smt_runner, CodebaseSmtExecutionError,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError
    rows = []
    for mode in ("stdout_flood", "stderr_flood", "blocked_stdin", "as_exhaustion", "rss_exhaustion",
                 "version_sleep", "descendant_cancel", "nonzero", "mismatch"):
        tool = write_solver_fixture(directory / mode, mode)
        signal = ReadyCancellation(tool.parent) if mode in {"blocked_stdin", "version_sleep", "descendant_cancel"} else None
        source = ";" + "x" * (200 * 1024) + "\n" + SMT_FIXTURE if mode == "blocked_stdin" else SMT_FIXTURE
        started = time.perf_counter()
        with audit.scope("synthetic_stress"):
            # Same default pool as production. Extra process slots account for
            # the deliberately spawned local descendant fixture, not a hard cap.
            with acquire_codebase_resources(memory_mb=512, child_process_slots=3,
                    timeout_seconds=min(30, deadline.options()["timeout_seconds"]),
                    cancel_event=deadline.cancelled) as parent:
                runner = make_codebase_smt_runner("z3", str(tool), parent_lease=parent,
                    cancel_event=signal, deadline=min(deadline.end, time.monotonic() + 4))
                try:
                    runner(source, ExecutionBounds(timeout_ms=3000,
                        max_memory_bytes=(128 if mode == "rss_exhaustion" else 256) * 1024**2,
                        max_output_bytes=1024))
                except (CodebaseSmtExecutionError, LeaseCancelledError) as error:
                    execution = error.execution.to_dict()
                    outcome = {"mode": mode, "error_type": type(error).__name__, "error": str(error),
                        "execution": execution, "wall_seconds": time.perf_counter() - started,
                        "phase_journal": recorded_phases(tool.parent), "retained_processes": retained_processes(tool.parent),
                        "live_at_return": live_retained_processes(tool.parent), "parent_lease_id": parent.lease_id,
                        "executable_sha256": hashlib.sha256(tool.read_bytes()).hexdigest(),
                        "synthetic_execution_only": True, "proof_authority": False, "checks_passed": False}
                    # Preserve the actual receipt even if a later qualification
                    # assertion fails; never turn recovery into original success.
                    (tool.parent / "outcome.json").write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")
                    base.require(execution.get("status") == "failed" and execution.get("phases"),
                                 "stress did not retain actual bounded process observations")
                    if signal is not None:
                        base.require(isinstance(error, LeaseCancelledError)
                            and any(phase["cancelled"] for phase in execution["phases"]), "in-flight stress cancellation not observed")
                    if mode in {"stdout_flood", "stderr_flood"}:
                        base.require(any(phase["output_truncated"] for phase in execution["phases"]), "flood was not observed")
                    if mode == "rss_exhaustion":
                        base.require(any(phase["resource_exhausted"] for phase in execution["phases"]), "RSS limit was not observed")
                    base.require(all(phase["workspace_cleaned"] for phase in execution["phases"]), "stress workspace survived")
                    base.require(not live_retained_processes(tool.parent), "stress descendant survived return")
                    outcome["checks_passed"] = True
                    (tool.parent / "outcome.json").write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")
                    rows.append(outcome)
                else:
                    raise AssertionError("synthetic failed execution became successful: " + mode)
    return rows


def benchmark(directory, report, *, rounds, seconds, operation_seconds):
    import duckdb
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
    from ipfs_datasets_py.logic.software_contracts.codebase_verification import verify_current_codebase_unit
    from ipfs_datasets_py.logic.software_contracts.codebase_applicability import verify_current_codebase_applicability
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
    audit = ProcessAudit()
    sys.addaudithook(audit.observe)
    owner = get_global_resource_scheduler()
    base.require(owner.config.proof_safety_enabled and not base.own_leases(owner), "default shared owner must be enabled and unowned")
    report["source_pins_before"] = source_pins()
    report["scheduler_before"] = owner.snapshot()
    report["runtime"] = {"python": sys.version, "duckdb": duckdb.__version__, "platform": platform.platform(),
                         "machine": platform.machine(), "logical_cpu_count": os.cpu_count()}
    deadline = base.Deadline(seconds, operation_seconds)
    telemetry = base.Telemetry(owner)
    telemetry.thread.start()
    connection = None
    try:
        base.progress(directory, report, "fixture")
        repository = directory / "source"
        repository.mkdir()
        for unit in base.fixture_units():
            (repository / unit.path).write_bytes(unit.source)
        with audit.scope("fixture"):
            for args in (("init", "-q"), ("config", "user.name", "Bounded SMT Fixture"),
                         ("config", "user.email", "fixture@example.invalid"), ("add", "."), ("commit", "-qm", "fixture")):
                subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True, timeout=10)
        index, catalog, connection = base.open_index(directory)
        started = time.perf_counter()
        with audit.scope("prepare"):
            head = index.prepare_current(repository, repository_id=base.VIEW, operation_id="initial", expected_head=None,
                                         **deadline.options()).head
        report.update(head=head.to_dict(), prepare_seconds=time.perf_counter() - started, producers=[], identities=[])
        for number, unit in enumerate(base.fixture_units()):
            contract, domain = unit.native()
            base.progress(directory, report, "verification:" + unit.path)
            started = time.perf_counter()
            with audit.scope("verification"):
                verification = verify_current_codebase_unit(index, repository, expected_head=head, path=unit.path,
                                                            contracts=[contract], **deadline.options())
            verification_seconds = time.perf_counter() - started
            report["last_verification"] = verification.artifact_cid
            base.progress(directory, report, "applicability:" + unit.path)
            started = time.perf_counter()
            with audit.scope("applicability"):
                applicability = verify_current_codebase_applicability(index, repository, expected_head=head,
                    verification_cid=verification.artifact_cid, domains=[domain], **deadline.options())
            applicability_seconds = time.perf_counter() - started
            report["last_applicability"] = applicability.artifact_cid
            base.progress(directory, report, "publication:" + unit.path)
            started = time.perf_counter()
            with audit.scope("publish", only_git=True):
                projection = catalog.publish(repository, expected_head=head, verification_cid=verification.artifact_cid,
                    applicability_cid=applicability.artifact_cid, operation_id=f"publish:{number}", **deadline.options())
            publication_seconds = time.perf_counter() - started
            value, app = projection.to_dict(), applicability.to_dict()
            selected = value["contracts"][0]
            observations = verification.to_dict()["process_observations"] + app["process_observations"]
            base.require(len(observations) == 10, "logical native observation inventory changed")
            phases = [phase for observation in observations for phase in observation["execution"]["phases"]]
            base.require(len(phases) == 30 and all(observation["execution"]["status"] == "completed" for observation in observations),
                         "closed native fixture did not complete all actual protocol phases")
            base.require(all(phase["returncode"] == 0 and phase["workspace_cleaned"] and not phase["error"]
                and not any(phase[name] for name in ("timed_out", "cancelled", "resource_exhausted", "output_truncated", "unavailable"))
                and phase["limits"]["memory_bytes"] == phase["limits"]["resident_memory_bytes"] == 128 * 1024**2
                for phase in phases), "native production escaped declared clean 128MiB profile")
            base.require(applicability.conditional_proved is (number < 6) and applicability.conditional_refuted is (number == 6),
                         "native conditional controls changed")
            base.require(app["contract_results"][0]["status"] == ("empty_domain" if number == 7 else "established"),
                         "native requested-domain gate changed")
            report["producers"].append({"path": unit.path, "verification_seconds": verification_seconds,
                "applicability_seconds": applicability_seconds, "publication_seconds": publication_seconds,
                "verification_cid": verification.artifact_cid, "applicability_cid": applicability.artifact_cid,
                "projection_cid": projection.projection_cid, "canonical_keys": selected["canonical_keys"] + selected["applicability_keys"],
                "observations": observations, "environment": verification.to_dict()["environment"],
                "applicability_status": app["contract_results"][0]})
            report["identities"].append({"path": unit.path, "contract_id": contract.contract_id,
                "contract_cid": cid_for_structured(contract.to_dict()), "domain_id": domain.domain_id,
                "domain_cid": cid_for_structured(domain.to_dict()), "verification_cid": verification.artifact_cid,
                "source_cid": value["source_binding"]["entry"]["source_cid"], "projection_cid": projection.projection_cid,
                "key_id": selected["canonical_keys"][0]["key_id"]})
            base.require(not base.own_leases(owner), "producer leaked an owned lease")
            base.progress(directory, report, "published:" + unit.path)
        base.progress(directory, report, "queries")
        report["queries"] = base.query_suite(catalog, index, directory, head, report["identities"], audit, deadline, rounds)
        connection.close()
        connection = None
        request = {"directory": str(directory), "head": head.to_dict(), "identities": report["identities"],
            "entry_ids": report["queries"]["entry_ids"], "source_pins": base.source_pins(),
            "execution_source_pins": report["source_pins_before"],
            "resume_cursor": report["queries"]["measurements"][0]["pages"][0]["next_cursor"],
            "timeout_seconds": deadline.options()["timeout_seconds"], "operation_timeout_seconds": operation_seconds}
        request_path = directory / "restart-request.json"
        request_path.write_text(json.dumps(request))
        base.progress(directory, report, "restart")
        started = time.perf_counter()
        with audit.scope("restart_launcher"):
            child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--replay", str(request_path)],
                capture_output=True, text=True, timeout=min(deadline.end - time.monotonic(), operation_seconds + 10))
        (directory / "restart.stdout").write_text(child.stdout)
        (directory / "restart.stderr").write_text(child.stderr)
        base.require(child.returncode == 0, "fresh-process replay failed: " + child.stderr[-4000:])
        report["restart"] = json.loads(child.stdout.splitlines()[-1])
        report["restart"]["wall_seconds_including_startup"] = time.perf_counter() - started
        index, catalog, connection = base.open_index(directory)
        base.progress(directory, report, "query_controls")
        started = time.perf_counter()
        report["query_controls"] = base.controls(catalog, index, connection, directory, head,
                                                report["identities"], audit, deadline)
        report["query_controls_seconds"] = time.perf_counter() - started
        base.progress(directory, report, "synthetic_runtime_stress")
        report["synthetic_stress"] = stress(directory / "stress", deadline, audit)
        report["completed"] = True
    finally:
        deadline.close()
        if connection is not None:
            connection.close()
        report["telemetry"] = telemetry.finish()
        report["source_pins_after"] = source_pins()
        report["process_audit"] = {"counts": audit.counts, "events": audit.events}
        report["scheduler_after"] = owner.snapshot()
        report["owned_leases_at_return"] = base.own_leases(owner)
        phases = [phase for producer in report.get("producers", []) for observation in producer["observations"]
                  for phase in observation["execution"]["phases"]]
        counts = dict(Counter(phase["kind"] for phase in phases))
        report["native_phase_counts"] = counts
        expected_queries = sum(value for key, value in counts.items() if key != "version")
        report["checks"] = {
            "completed": report.get("completed") is True,
            "selected_sources_unchanged": report["source_pins_before"] == report["source_pins_after"],
            "eight_native_units": len(report.get("producers", [])) == 8,
            "actual_version_launches_match_receipts": counts.get("version", 0) == 80 ==
                sum(value for key, value in audit.counts.items() if key.endswith(":version")),
            "actual_query_launches_match_receipts": expected_queries == 160 ==
                sum(value for key, value in audit.counts.items() if key.endswith(":solver_query")),
            "lookup_without_solver_launches": all(event["kind"] == "git" for event in audit.events
                if event["stage"] in {"lookup", "publish", "controls"}),
            "fresh_process_replay": report.get("restart", {}).get("completed") is True,
            "nine_runtime_stress_controls": len(report.get("synthetic_stress", [])) == 9,
            "owned_leases_drained": report["owned_leases_at_return"] == [],
            "sampler_stopped": report["telemetry"]["sampler_stopped"],
            "telemetry_without_errors": report["telemetry"]["errors"] == [],
            "finished_within_overall_deadline": time.monotonic() < deadline.end,
        }
        base.progress(directory, report, "completed" if report.get("completed") else "failed")
    base.require(all(report["checks"].values()), "benchmark final checks failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--rounds", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--overall-timeout", type=float, default=600)
    parser.add_argument("--operation-timeout", type=float, default=120)
    args = parser.parse_args()
    sys.path.insert(0, str(base.ROOT))
    sys.path.insert(0, str(base.ACCELERATE))
    if args.replay:
        raw = args.replay.read_bytes()
        base.require(len(raw) <= 128 * 1024, "replay request exceeds finite input bound")
        request = json.loads(raw)
        base.require(source_pins() == request["execution_source_pins"], "execution generation changed before fresh replay")
        result = base.replay(request)
        base.require(source_pins() == request["execution_source_pins"], "execution generation changed during fresh replay")
        result["execution_source_pins"] = source_pins()
        print(json.dumps(result))
        return 0
    if args.output is None:
        parser.error("--output is required")
    base.require(0 < args.operation_timeout <= args.overall_timeout <= 900, "invalid finite benchmark deadlines")
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    base.require(not (directory / "result.json").exists() and not (directory / "source").exists(), "attempt directory already used")
    report = {"schema": SCHEMA, "started_at_utc": datetime.now(timezone.utc).isoformat(), "completed": False,
        "configuration": {"units": 8, "rounds": args.rounds, "page_size": 3, "duckdb": base.DB_CONFIG,
            "scheduler": "shared_default", "native_per_process_as_bytes": 128 * 1024**2,
            "native_sampled_tree_rss_bytes": 128 * 1024**2, "overall_timeout_seconds": args.overall_timeout,
            "operation_timeout_seconds": args.operation_timeout},
        "scope": {"conditional_model_evidence_only": True, "kernel_checked": False, "runtime_behavior_verified": False,
            "scaling_qualification": False, "network_requested": False, "hard_aggregate_cgroup_memory": False,
            "hard_parent_memory_limit": False, "rss_guard_is_sampled": True,
            "synthetic_runtime_stress_is_proof_evidence": False, "resource_slots_are_accounting_not_hard_pid_limits": True},
        "errors": []}
    started = time.perf_counter()
    try:
        benchmark(directory, report, rounds=args.rounds, seconds=args.overall_timeout, operation_seconds=args.operation_timeout)
    except BaseException as error:
        report["completed"] = False
        report["errors"].append({"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()})
    finally:
        report["wall_seconds"] = time.perf_counter() - started
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        (directory / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"result": str(directory / "result.json"), "completed": report["completed"],
                      "wall_seconds": report["wall_seconds"], "checks": report.get("checks", {})}))
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
