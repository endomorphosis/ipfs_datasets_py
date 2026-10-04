"""Qualify default Apalache admission with installed JNI and bounded real models.

Run --smoke first (two cases/six phases), then the separate full qualification
(sixteen cases/four controls/fifty-four phases). Previous benchmark mains are
never executed. The invalid Apalache case retains a genuine raw violation file;
the existing TLC-only trace parser is not represented as an Apalache replay.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import sys
import time
import traceback
import zipfile

import bench_tla_operation_control as previous
from bench_smt_operation_control import MIB, ROOT, require, saved, sha, write

WORKERS = (1, 2, 4)
CONTROLS = ("pre_setup_cancel", "live_model_cancel", "after_model_cancel", "live_model_deadline")
RUNTIME_CONFIG = "apalache-runtime.json"
OUTPUT_PATHS = tuple("apalache-run/" + name for name in ("counterexample.tla", "violation.tla", "example.tla"))
JVM_ARGS = ("-Xms16m", "-Xmx256m", "-Xss1m", "-XX:ActiveProcessorCount=1",
            "-XX:MaxMetaspaceSize=128m", "-XX:ReservedCodeCacheSize=64m", "-XX:-UsePerfData", "-Duser.home=.")
NATIVE_ENTRIES = {
    "com/microsoft/z3/linux/aarch64/libz3.so": (31683329, "bfa95832286d352df731c5c137a098508c44e5ed7cc6d947845e2d05d8e9c452"),
    "com/microsoft/z3/linux/aarch64/libz3java.so": (581161, "a5e34485123280b60ae34e08bc27f3f10401b612c829cc00f7077cb526f28cd2"),
}


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__)}


def artifacts(valid):
    value = previous.baseline.artifacts(valid)
    model = ("---- MODULE BoundedCounter ----\nEXTENDS Integers\nVARIABLE\n"
             "    \\* @type: Int;\n    n\n"
             "Init == n = 0\nNext == n' = IF n < 3 THEN n + 1 ELSE n\n"
             "Spec == Init /\\ [][Next]_n\n"
             + ("Safety == n \\in 0..3\n" if valid else "Safety == n \\in 0..1\n") + "====\n")
    return replace(value, model_text=model, bounds=replace(value.bounds, max_steps=3),
                   source_document_id="benchmark:typed-apalache-counter:" + str(valid).lower())


def bounds(provider):
    value = previous.baseline.bounded_request().bounds
    return replace(value, timeout_ms=30000 if provider == "apalache" else 15000,
                   max_memory_bytes=(512 if provider == "apalache" else 256) * MIB)


def dispatch_capacity(snapshot, requested):
    """Advisory whole-operation width; real admission still owns each phase."""
    require(type(requested) is int and requested in WORKERS, "unsupported requested caller width")
    available = {key: snapshot["available"][key] for key in ("cpu_slots", "memory_mb", "child_process_slots")}
    require(all(type(value) is int and value >= 0 for value in available.values()), "invalid available capacity snapshot")
    protected = {"cpu_slots": 0, "memory_mb": 0}
    for lane, row in snapshot["lanes"].items():
        if lane != "validation":
            for key in protected:
                reserved, allocated = row["reservation"][key], row["allocated"][key]
                require(type(reserved) is int and type(allocated) is int and reserved >= 0 and allocated >= 0,
                        "invalid lane reservation snapshot")
                protected[key] += max(0, reserved - allocated)
    for key, value in protected.items():
        available[key] = max(0, available[key] - value)
    effective = min(requested, available["cpu_slots"], available["memory_mb"] // 512,
                    available["child_process_slots"] // 3)
    return {"requested_workers": requested, "effective_workers": effective,
            "capacity_snapshot": snapshot, "protected_other_lanes": protected,
            "available_to_validation": available,
            "whole_operation_envelope": {"cpu_slots": 1, "memory_mb": 512, "child_process_slots": 3},
            "scope": "Advisory dispatch before API entry; native admission rechecks changing capacity and real pressure"}


def prepare_dispatch(audit, requested, label, result):
    previous.baseline.java_baseline.previous._drained(audit)
    dispatch = {"batch": label, "at_monotonic": time.monotonic(),
                **dispatch_capacity(audit.owner.snapshot(), requested)}
    result["dispatches"].append(dispatch)
    require(dispatch["effective_workers"] > 0, "no shared capacity for one conservative Apalache operation")
    return dispatch


def finish_dispatch(audit, dispatch, prefix):
    previous.baseline.java_baseline.previous._drained(audit)
    launches = [row for row in audit.events if row["case"].startswith(prefix)]
    dispatch["observed_max_owned_roots"] = max(sum(not lease["parent_lease_id"] for lease in row["owned_leases"])
                                                for row in launches)
    require(dispatch["observed_max_owned_roots"] <= dispatch["effective_workers"],
            "whole-operation dispatch exceeded its advisory width")


def selected_tools(directory):
    selection, files = previous.baseline.previous.selected_tools()
    require(selection["apalache_java"] == selection["tlc_java"], "reviewed mixed run requires one pinned Java selection")
    require(files[selection["apalache_jar"]] == "4ed614a62797fc74b5a7878e4a10c3597cc5bf8810e81eb18e667b731d4596d5",
            "installed Apalache JAR is not the statically reviewed 0.58.3 build")
    require(os.uname().machine == "aarch64", "reviewed JNI qualification targets Linux aarch64")
    native = {}
    with zipfile.ZipFile(selection["apalache_jar"]) as archive:
        for name, (size, expected) in NATIVE_ENTRIES.items():
            info = archive.getinfo(name)
            require(info.file_size == size and size < 64 * MIB, "unexpected packaged JNI size")
            digest = hashlib.sha256()
            with archive.open(name) as stream:
                head = stream.read(64)
                require(head[:4] == b"\x7fELF" and int.from_bytes(head[18:20], "little") == 183,
                        "packaged solver library is not the reviewed aarch64 ELF")
                digest.update(head)
                while block := stream.read(MIB):
                    digest.update(block)
            require(digest.hexdigest() == expected, "packaged solver library identity differs")
            native[name] = {"bytes": size, "sha256": expected, "elf_machine": 183}
    launcher = directory / "tlc-memory-aware"
    launcher.write_text(previous.baseline.launcher_body({"java": selection["tlc_java"], "jar": selection["tlc_jar"]}))
    launcher.chmod(0o700)
    selection["tlc_wrapper"] = str(launcher)
    files[str(launcher)] = previous.baseline.previous.tool_sha(launcher)
    return selection, files, native


class Audit(previous.OperationAudit):
    def __init__(self, owner):
        super().__init__(owner)
        self.apalache_environments = []

    def observe(self, name, args):
        super().observe(name, args)
        if name != "subprocess.Popen" or getattr(self.local, "provider", None) != "apalache" or self.local.phase == "setup":
            return
        env = args[3]
        require(env.get("JVM_ARGS") == " ".join(JVM_ARGS) and env.get("JVM_GC_ARGS") == "-XX:+UseSerialGC",
                "actual Apalache launch lost the owned JVM profile")
        require(all(key not in env for key in ("APALACHE_JAR", "SMT_SOLVER", "SMT_ENCODING", "CONFIG_FILE", "RUN_DIR", "OUT_DIR")),
                "default Apalache launch inherited a foreign payload/configuration override")
        require(env["HOME"] == env["TMPDIR"] == str(args[2]), "Apalache shell temporary files escaped private cwd")
        with self.lock:
            self.apalache_environments.append({"case": self.local.case, "phase": self.local.phase,
                "jvm_args": env["JVM_ARGS"], "jvm_gc_args": env["JVM_GC_ARGS"],
                "private_home_and_tmpdir": True, "foreign_configuration_environment_absent": True})


def execute(provider, route, valid, audit, selection, label, *, control=None, token=None, timeout=None):
    from ipfs_datasets_py.logic.backends.tla.execution_v2 import StateExecutionEngineV2, StateExecutionRequestV2, execute_apalache, execute_tlc
    audit.local.operation_label = audit.local.case = label
    audit.local.provider, audit.local.control, audit.local.token = provider, control, token

    def finder(name):
        expected = "apalache-mc" if provider == "apalache" else "tlc"
        require(name == expected, "execution attempted setup of an unselected provider")
        return selection["apalache_launcher"] if provider == "apalache" else selection["tlc_wrapper"]

    before = len([row for row in audit.events if row["case"].startswith(label)])
    engine = StateExecutionEngineV2(which=finder, lazy_install=False)
    require(len([row for row in audit.events if row["case"].startswith(label)]) == before,
            "default V2 construction eagerly launched Java")
    fixture = artifacts(valid) if provider == "apalache" else previous.baseline.artifacts(valid)
    request = dict(request_id="req:" + label, module_name="BoundedCounter", bounds=bounds(provider), artifacts=fixture)
    controls = {"cancellation": token} if token is not None else {}
    if timeout is not None:
        controls["operation_timeout_ms"] = timeout
    try:
        if route == "engine":
            return engine.execute(StateExecutionRequestV2(provider=provider, **request), **controls)
        return (execute_apalache if provider == "apalache" else execute_tlc)(engine=engine, **request, **controls)
    finally:
        audit.local.control = audit.local.token = audit.local.cancel_live_probe = None


def phases(audit, label, provider, valid, selection, expected, *, stopped=None):
    if provider == "tlc":
        return previous.validate_phases(audit, label, {"java": selection["tlc_java"], "wrapper": selection["tlc_wrapper"]},
            previous.baseline.artifacts(valid), expected, stopped=stopped)
    launches, rows = previous.rows_for(audit, label)
    details = [row for row in audit.requests if row["case"] in {label, label + ":constructor"}]
    require(len(launches) == len(rows) == len(details) == len(expected), "unexpected Apalache phases/lifecycles")
    fixture = artifacts(valid)
    for kind, launch, row, detail in zip(expected, launches, rows, details):
        native, request, limits = row["result"], row["request"], detail["limits"]
        if kind == "setup":
            argv = [selection["apalache_java"], *previous.baseline.java_baseline.JAVA_FLAGS]
        elif kind == "model":
            argv = [selection["apalache_launcher"], "check", "--config-file=" + RUNTIME_CONFIG,
                    "--run-dir=apalache-run", "--out-dir=apalache-out", "--smt-solver=z3",
                    "--config=apalache.cfg", "--length=3", "--inv=Safety", "--no-deadlock", "BoundedCounter.tla"]
        else:
            argv = [selection["apalache_launcher"], "version"]
        require(request["argv"] == native["command"] == detail["argv"] == argv and launch["argv"][-len(argv):] == argv,
                "Apalache logical/actual command differs from reviewed argv")
        rss = (256 if kind == "setup" else 512) * MIB
        slots = 1 if kind == "setup" else 3
        require(request["memory_bytes"] == 4 * 1024**3 and request["resident_memory_bytes"] == rss
                and request["max_output_bytes"] == 65536 and 0 < request["timeout_seconds"] <= (10 if kind == "setup" else 3 if kind == "help" else 30),
                "native phase lost finite AS/RSS/output/wall bounds")
        require(0 < limits["cpu_seconds"] <= request["timeout_seconds"] and limits["enforce_file_size_limit"]
                and limits["max_file_bytes"] == (MIB if kind == "setup" else 64 * MIB)
                and limits["max_workspace_bytes"] == (MIB if kind == "setup" else 128 * MIB),
                "native phase lost finite CPU/file/workspace bounds")
        require(request["stdin_is_empty"] and request["java_option_environment_absent"], "native environment/stdin differs")
        lease = next(item for item in launch["owned_leases"] if item["lease_id"] == launch["launch_lease_id"])
        require((lease["cpu_slots"], lease["memory_mb"], lease["child_process_slots"]) == (1, rss // MIB, slots)
                and lease["parent_lease_id"] is None, "native phase lacks its actual admitted root profile")
        require(native["pid"] is not None and native["workspace_cleaned"] and not Path("/proc", str(native["pid"])).exists()
                and not any(native[k] for k in ("error", "unavailable", "resource_exhausted", "output_truncated", "workspace_limit_exceeded")),
                "native phase failed clean resource/workspace containment")
        if kind == "model":
            inputs = {"BoundedCounter.tla": fixture.model_text, "apalache.cfg": fixture.apalache_config_text,
                      RUNTIME_CONFIG: "{}\n"}
            require(detail["input_sha256"] == {name: hashlib.sha256(value.encode()).hexdigest() for name, value in inputs.items()}
                    and detail["input_bytes"] == {name: len(value.encode()) for name, value in inputs.items()}
                    and request["input_file_count"] == 3 and request["output_path_count"] == 3
                    and detail["output_paths"] == list(OUTPUT_PATHS)
                    and limits["max_input_bytes"] == max(4096, sum(len(value.encode()) for value in inputs.values())),
                    "model/source/private-runtime-config receipt differs")
        else:
            require(request["input_file_count"] == request["output_path_count"] == 0
                    and limits["max_input_bytes"] == (1024 if kind == "setup" else 4096), "identity phase has unexpected files")
        if stopped == kind:
            require((native["cancelled"] or native["timed_out"]) and native["process_tree_terminated"],
                    "live stop did not terminate its actual process")
        else:
            require(not native["cancelled"] and not native["timed_out"] and not native["process_tree_terminated"]
                    and native["returncode"] == ((0 if valid else 12) if kind == "model" else 0),
                    "native Apalache phase did not finish with its expected clean exit")
    budgets = [row for row in audit.phase_budgets if row["case"] == label]
    require(len(budgets) == len(expected) and len({row["deadline"] for row in budgets}) <= 1,
            "native phases did not share their aggregate operation deadline")
    require(all(row["request_timeout_seconds"] <= row["remaining_seconds"] + .05 for row in budgets),
            "native request widened remaining operation budget")
    return rows


def case(provider, route, valid, audit, selection, label):
    from ipfs_datasets_py.logic.backends.tla.execution_v2 import BackendRequest, FrozenMap, QueryKind, StateExecutionRequestV2, _digest_of
    fixture = artifacts(valid) if provider == "apalache" else previous.baseline.artifacts(valid)
    started = time.monotonic()
    result = execute(provider, route, valid, audit, selection, label)
    rows = phases(audit, label, provider, valid, selection, ("setup", "model", "help"))
    require(result.provider.value == provider and result.outcome is not None
            and result.disposition.value == ("satisfied" if valid else "counterexample")
            and result.result.status.value == ("satisfied" if valid else "violated")
            and result.evidence.model_check_established and not result.evidence.theorem_established,
            "public V2 bounded-model status/authority differs")
    request = StateExecutionRequestV2(request_id="req:" + label, provider=provider, module_name="BoundedCounter",
        bounds=bounds(provider), artifacts=fixture)
    digest = _digest_of(request.to_dict())
    backend_request = BackendRequest(request_id=request.request_id, claim_id=f"claim:state:{request.request_id}",
        declaration_id=f"declaration:state:{request.request_id}", claim_digest=digest,
        obligation_id=f"obligation:state:{request.request_id}", obligation_digest=digest,
        assumption_ids=("assumption:bounded-model-check",), logic_family="state_transition", query_kind=QueryKind.SATISFIABILITY,
        bounds=request.bounds, payload=FrozenMap({"module_name": fixture.module_name, "provider": provider}), requested_backend_id=provider)
    require(result.request_digest == result.evidence.request_digest == digest, "V2 request digest binding changed")
    if provider == "tlc":
        previous.baseline.verify_binding(result.outcome, fixture, backend_request, status="satisfied" if valid else "violated")
    receipt = result.outcome.receipt
    require(result.outcome.request_digest == backend_request.digest and receipt.model_digest == fixture.model_digest
            and receipt.artifact_digest == fixture.artifact_digest
            and receipt.configuration_digest == (fixture.apalache_config_digest if provider == "apalache" else fixture.tlc_config_digest)
            and receipt.bounded and not receipt.unbounded_proof, "exact model/config/backend request binding changed")
    witness = None
    if provider == "apalache":
        require(rows[2]["result"]["stdout"].strip() == "0.58.3", "actual Apalache version differs")
        if valid:
            require(receipt.counterexample is None and not rows[1]["result"]["output_files"], "valid check returned a witness")
        else:
            raw = rows[1]["result"]["output_files"].get("apalache-run/violation.tla", "")
            require(raw and receipt.counterexample is not None and receipt.counterexample.raw == raw
                    and receipt.counterexample.source == "checker_counterexample_file", "genuine violation file was not retained")
            assignments = re.findall(r"(?ms)^State\d+\s*==\s*(?:/\\\s*)?n\s*=\s*(\d+)\s*(?=\n|$)", raw)
            require(assignments == ["0", "1", "2"], "raw finite counterexample differs from the submitted source")
            require(not receipt.counterexample.states
                    and any("no parseable State blocks" in note for note in receipt.counterexample.replay_notes),
                    "benchmark silently claimed an unsupported Apalache structural replay")
            witness = {"path": "apalache-run/violation.tla", "sha256": hashlib.sha256(raw.encode()).hexdigest(),
                       "raw_state_values": assignments, "parsed_state_count": 0,
                       "scope": "Native raw witness only; existing structural parser accepts TLC State blocks"}
    elif not valid:
        require([s.assignments.get("n") for s in receipt.counterexample.states] == ["0", "1", "2"], "mixed TLC counterexample differs")
    return {"case": label, "provider": provider, "route": route, "valid": valid, "phase_count": 3,
            "elapsed_seconds": time.monotonic() - started, "raw_witness": witness, "result": result.to_dict()}


def control(kind, audit, selection):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    from ipfs_datasets_py.logic.backends.smt.operation_budget import ProofOperationCancelled, ProofOperationTimeout
    label = "control:" + kind
    token = CancellationToken()
    if kind == "pre_setup_cancel":
        token.cancel()
    timeout = 300 if kind == "live_model_deadline" else 15000
    started = time.monotonic()
    expected_error = ProofOperationTimeout if kind == "live_model_deadline" else ProofOperationCancelled
    try:
        returned = execute("apalache", "helper", False, audit, selection, label, control=kind, token=token, timeout=timeout)
    except expected_error as error:
        failure = {"type": type(error).__name__, **error.to_dict()}
    else:
        details = {"kind": kind, "status": returned.result.status.value,
                   "disposition": returned.disposition.value,
                   "model_check_established": returned.evidence.model_check_established,
                   "theorem_established": returned.evidence.theorem_established,
                   "reason": returned.outcome.receipt.reason if returned.outcome is not None else None}
        raise AssertionError("expected typed interruption not observed: " + json.dumps(details, sort_keys=True))
    expected = () if kind == "pre_setup_cancel" else ("setup", "model")
    rows = phases(audit, label, "apalache", False, selection, expected,
        stopped="model" if kind in {"live_model_cancel", "live_model_deadline"} else None)
    boundaries = [row for row in audit.boundaries if row["case"] == label]
    triggers = [row for row in audit.triggers if row["case"] == label]
    if kind == "live_model_cancel":
        require(len(triggers) == 1 and triggers[0]["observed_live"]
                and triggers[0]["pid"] == rows[-1]["result"]["pid"], "live cancellation lacked actual process observation")
    elif kind == "live_model_deadline":
        require(len(boundaries) == 1 and boundaries[0]["observed_live"]
                and boundaries[0]["at_monotonic"] < boundaries[0]["deadline"]
                and boundaries[0]["pid"] == rows[-1]["result"]["pid"], "deadline lacked live native startup")
    elif kind == "after_model_cancel":
        require(len(boundaries) == 1 and boundaries[0]["returncode"] == 12 and boundaries[0]["workspace_cleaned"],
                "boundary cancellation did not follow a complete native violation")
        require(rows[-1]["result"]["output_files"].get("apalache-run/violation.tla"), "completed violation file missing before cancellation")
    elapsed = time.monotonic() - started
    require(elapsed < 20, "bounded interruption exceeded cleanup envelope")
    previous.baseline.java_baseline.previous._drained(audit)
    return {"case": label, "kind": kind, "phase_count": len(expected), "phases": list(expected),
            "operation_timeout_ms": timeout, "elapsed_seconds": elapsed, "interruption": failure,
            "boundaries": boundaries, "live_triggers": triggers, "result_published": False,
            "deadline_scope": "Actual launched model process/JVM startup; no assertion that SMT checking began",
            "native_stop_flags": "Ambient deadline polling can report cancelled; typed outer timeout is authoritative"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(previous.runtime_baseline.base.ACCELERATE))
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output", str(directory)]
        + (["--smoke"] if args.smoke else []), "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "apalache-resource-admission-benchmark@1", "status": "running", "smoke": args.smoke,
        "source_pins_before": pins(), "runtime": saved.runtime(), "runs": [], "mixed_cases": [], "controls": [], "checks": {},
        "dispatches": [],
        "scope": {"installed_apalache_launcher": True, "installation": False, "new_smt_backend_processes": False,
                  "raw_apalache_counterexample_only": True, "parser_extension": False, "throughput_scaling_claim": False,
                  "resource_limits": "Reservations, per-process CPU/AS and sampled tree RSS; no aggregate cgroup/PID guarantee"}}
    started = time.monotonic()
    old_java = os.environ.get(previous.JAVA_ENV)
    owner = audit = envelope = None
    try:
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = previous.baseline.java_baseline.previous.install_saved_owner(directory / "saved-scheduler-config.json")
        result["shared_before"] = saved.state_summary(owner.state_path)
        result["shared_pool_compatibility"] = owner._benchmark_pool_compatibility
        selection, files, native = selected_tools(directory)
        result.update(tool_selection=selection, tool_files_before=files, packaged_native_entries=native)
        os.environ[previous.JAVA_ENV] = selection["apalache_java"]
        audit = Audit(owner)
        audit.install_observers()
        sys.addaudithook(audit.observe)
        write(directory / "fixtures.json", {"valid": artifacts(True).to_dict(), "invalid": artifacts(False).to_dict()})
        for workers in ((1,) if args.smoke else WORKERS):
            jobs = (("engine", True), ("engine", False)) if args.smoke else (("engine", True), ("engine", False), ("helper", True), ("helper", False))
            dispatch = prepare_dispatch(audit, workers, f"parallel:{workers}", result)
            batch_started = time.monotonic()
            with ThreadPoolExecutor(max_workers=dispatch["effective_workers"]) as pool:
                rows = list(pool.map(lambda job: case("apalache", job[0], job[1], audit, selection,
                    f"parallel:{workers}:{job[0]}:{job[1]}"), jobs))
            finish_dispatch(audit, dispatch, f"parallel:{workers}:")
            result["runs"].append({"workers": workers, "requested_workers": workers,
                "effective_workers": dispatch["effective_workers"], "dispatch": dispatch,
                "elapsed_seconds": time.monotonic() - batch_started, "cases": rows})
            write(directory / "partial.json", result)
        if not args.smoke:
            dispatch = prepare_dispatch(audit, 4, "mixed", result)
            batch_started = time.monotonic()
            with ThreadPoolExecutor(max_workers=dispatch["effective_workers"]) as pool:
                jobs = (("apalache", True), ("tlc", True), ("apalache", False), ("tlc", False))
                result["mixed_cases"] = list(pool.map(lambda job: case(job[0], "helper", job[1], audit, selection,
                    f"mixed:{job[0]}:{job[1]}"), jobs))
            finish_dispatch(audit, dispatch, "mixed:")
            result["mixed_dispatch"] = dispatch
            result["mixed_elapsed_seconds"] = time.monotonic() - batch_started
            for kind in CONTROLS:
                result["controls"].append(control(kind, audit, selection))
        count = 6 if args.smoke else 54
        result["checks"].update(expected_success_cases=sum(len(run["cases"]) for run in result["runs"]) == (2 if args.smoke else 12),
            mixed_provider_cases=len(result["mixed_cases"]) == (0 if args.smoke else 4),
            operation_stop_controls=len(result["controls"]) == (0 if args.smoke else 4),
            expected_real_phases=len(audit.events) == len(audit.results) == len(audit.requests) == count,
            native_environments_sanitized=len(audit.environments) == len(audit.workspace_environments) == count,
            owned_apalache_jvm_environments=len(audit.apalache_environments) == (4 if args.smoke else 31))
        if not args.smoke:
            result["mixed_overlap_required"] = result["mixed_dispatch"]["effective_workers"] >= 2
            result["checks"]["mixed_admitted_roots_overlap_when_capacity_permits"] = (
                not result["mixed_overlap_required"] or result["mixed_dispatch"]["observed_max_owned_roots"] >= 2)
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
    finally:
        if old_java is None:
            os.environ.pop(previous.JAVA_ENV, None)
        else:
            os.environ[previous.JAVA_ENV] = old_java
        result["elapsed_seconds"] = time.monotonic() - started
        result["source_pins_after"] = pins()
        result["checks"].update(sources_stable=result["source_pins_before"] == result["source_pins_after"],
            java_selection_environment_restored=os.environ.get(previous.JAVA_ENV) == old_java)
        if "tool_files_before" in result:
            result["tool_files_after"] = {path: previous.baseline.previous.tool_sha(path) for path in result["tool_files_before"]}
            result["checks"]["selected_tool_files_unchanged"] = result["tool_files_before"] == result["tool_files_after"]
        if owner is not None:
            result["shared_after"] = saved.state_summary(owner.state_path)
            result["checks"].update(shared_config_unchanged=previous.baseline.java_baseline.previous._config_bytes(
                result["shared_after"]["config"]) == previous.baseline.java_baseline.previous._config_bytes(envelope["config"]),
                owned_work_drained=not result["shared_after"]["owned_active_leases"] and not result["shared_after"]["owned_waiting_requests"])
        if audit is not None:
            result.update(launches=len(audit.events), lifecycles=len(audit.results),
                native_lifecycles=sum(row["result"]["pid"] is not None for row in audit.results),
                prelaunch_lifecycles=sum(row["result"]["pid"] is None for row in audit.results),
                phase_counts=dict(Counter(row["phase"] for row in audit.phase_budgets)))
            result["audit_sha256"] = {}
            for name, value in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results),
                ("request-audit.json", audit.requests), ("control-audit.json", {"boundaries": audit.boundaries,
                    "triggers": audit.triggers, "phase_budgets": audit.phase_budgets}),
                ("apalache-environment-audit.json", audit.apalache_environments)):
                write(directory / name, value)
                result["audit_sha256"][name] = sha(directory / name)
        result["child_usage"] = {key: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), key) for key in ("ru_utime", "ru_stime", "ru_maxrss")}
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "checks": result["checks"], "result": str(directory / "result.json")}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
