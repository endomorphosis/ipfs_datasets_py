"""Exercise real default Tamarin admission without widening the saved pool.

The reviewed pool has four process slots; the default Tamarin profile needs
eight. Direct and standalone V2 calls must therefore refuse before workspace
creation or native launch. This qualifies admission, not native solver success.
The stock source and installed tools are retained for a later native qualification.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import resource
import sys
import time
import traceback

import bench_protocol_operation_control as retained
from bench_generic_prover_admission import LaunchAudit, request as old_request
from bench_smt_operation_control import MIB, ROOT, install_saved_owner, require, saved, sha, write

NEW_TEST = ROOT / "tests/unit/logic/backends/test_tamarin_resource_admission.py"
CASES = ("direct", "standalone_v2")
INSTALL = Path("/home/barberb/.local/share/ipfs_datasets_py/theorem-provers")
SOURCE = '''theory AdmissionSmoke
begin
rule Emit:
  [ Fr(~s) ] --[ Emitted(~s) ]-> [ Out(~s) ]
lemma emitted_has_event:
  "All x #i. Emitted(x) @ i ==> Ex #j. Emitted(x) @ j"
end
'''
PROFILE = {"cpu_slots": 2, "memory_mb": 512, "child_process_slots": 8}


def pins():
    return {**retained.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST)}


def selected_tools():
    paths = {
        "tamarin": str(INSTALL / "tamarin-prover-1.12.0/bin/tamarin-prover"),
        "maude": str(INSTALL / "bin/maude"),
        "maude_target": str(INSTALL / "maude-distro/usr/bin/maude"),
    }
    expected = {
        "tamarin": "462e21b904a33dcf2618992dc88235bd28761af0abddde3f92d45c83c9d3db03",
        "maude_target": "ae049687825fbd1c5d62b94d272d7a8e49a4bfbd57ad8f0ee4af63ec3ff964d9",
    }
    for name, path in paths.items():
        require(Path(path).is_file() and os.access(path, os.X_OK), "installed tool unavailable: " + name)
        if name in expected:
            require(sha(path) == expected[name], "reviewed installed ELF changed: " + name)
            header = Path(path).read_bytes()[:20]
            require(header[:6] == b"\x7fELF\x02\x01" and int.from_bytes(header[18:20], "little") == 183,
                    "selected binary is not ELF64 little-endian AArch64")
    library = str(INSTALL / "maude-distro/usr/lib/aarch64-linux-gnu")
    modules = str(INSTALL / "maude-distro/usr/share/maude")
    wrapper = ('#!/bin/sh\nset -eu\nlauncher_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
        'export PATH="$launcher_dir${PATH:+:$PATH}"\n'
        'export LD_LIBRARY_PATH=' + library + '"${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
        'export MAUDE_LIB=' + modules + '"${MAUDE_LIB:+:$MAUDE_LIB}"\n'
        'exec ' + paths["maude_target"] + ' "$@"\n')
    require(Path(paths["maude"]).read_text() == wrapper, "reviewed managed Maude wrapper changed")
    dependencies = [Path(library) / "libbdd.so.0.0.0", Path(library) / "libtecla.so.1.6.3",
        Path(modules) / "prelude.maude"]
    ghc = INSTALL / "stack-root/programs/aarch64-linux/ghc-tinfo6-9.6.7"
    documentation = [ghc / "share/doc/ghc-9.6.7/html/users_guide/runtime_control.html",
        ghc / "share/doc/ghc-9.6.7/html/users_guide/using-concurrent.html",
        ghc / "lib/ghc-9.6.7/lib/aarch64-linux-ghc-9.6.7/rts-1.0.2/include/ghcautoconf.h",
        INSTALL / "tamarin-prover-1.12.0-source/tamarin-prover-1.12.0/tamarin-prover.cabal"]
    files = {str(p): sha(p) for p in [*map(Path, paths.values()), *dependencies, *documentation]}
    runtime = Path(documentation[0]).read_text()
    binary = Path(paths["tamarin"]).read_bytes()
    require("-xr" not in runtime and b"-xr" not in binary and b"9.6.7" in binary,
            "reviewed GHC runtime identity or unsupported flag evidence changed")
    require("#define USE_LARGE_ADDRESS_SPACE 1" in documentation[2].read_text()
            and "-with-rtsopts=-N" in documentation[3].read_text(), "reviewed GHC build settings changed")
    evidence = {"installed_ghc": "9.6.7", "native_version_probed": False,
        "installed_elf_architecture": "ELF64 little-endian AArch64",
        "unsupported_rts_option": "-xr", "default_capabilities_override": "-N1",
        "heap_limit_is_not_hard_aggregate_memory_limit": True,
        "finite_address_space_startup_sufficiency_tested": False,
        "source_findings": {
            "initial_aarch64_virtual_reservation_bytes": 1 << 38,
            "finite_rlimit_as_reservation_fraction": 0.666,
            "reservation_is_uncommitted": True,
            "failed_reservation_shrink_fraction": 0.125,
        },
        "primary_sources": [
            "https://raw.githubusercontent.com/ghc/ghc/ghc-9.6.7-release/rts/posix/OSMem.c",
            "https://raw.githubusercontent.com/ghc/ghc/ghc-9.6.7-release/rts/sm/MBlock.c",
            "https://raw.githubusercontent.com/ghc/ghc/ghc-9.6.7-release/rts/RtsFlags.c"],
        "maude_environment_source": "unchanged installed managed wrapper; no benchmark environment override",
        "process_profile_scope": "ordinary stock source; estimate, not hard thread/descendant containment"}
    return paths, files, evidence


def request(route):
    require(route in CASES, "unknown route")
    original = old_request("cryptographic_protocol", SOURCE, memory_mb=512, timeout_ms=5000)
    if route == "direct":
        return replace(original, request_id="request:tamarin-admission:direct", requested_backend_id="tamarin",
            payload={"encoding": "spthy", "source": SOURCE})
    from ipfs_datasets_py.logic.backends.protocol.execution_v2 import ProtocolExecutionRequestV2
    return ProtocolExecutionRequestV2(request_id="request:tamarin-admission:v2", provider="tamarin",
        source=SOURCE, source_format="spthy", bounds=original.bounds)


def canonical_request(route):
    """Independent expected conversion; never injected into the V2 engine."""
    req = request(route)
    if route == "direct":
        return req
    from ipfs_datasets_py.logic.backends.protocol.execution_v2 import _digest_of
    from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
    from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, QueryKind
    digest = _digest_of(req.to_dict())
    return BackendRequest(request_id=req.request_id, claim_id="claim:protocol:" + req.request_id,
        declaration_id="declaration:protocol:" + req.request_id, claim_digest=digest,
        obligation_id="obligation:protocol:" + req.request_id, obligation_digest=digest, assumption_ids=(),
        logic_family="cryptographic_protocol", query_kind=QueryKind.THEOREM_PROOF, bounds=req.bounds,
        payload=FrozenMap({"encoding": "spthy", "source": req.source}), requested_backend_id="tamarin")


def backend(paths):
    from ipfs_datasets_py.logic.backends.protocol import tamarin
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    value = tamarin.TamarinBackend(executable=paths["tamarin"], maude_executable=paths["maude"])
    require(value._owns_runner and type(value._runner) is ResourceAdmittedToolRunner
            and type(value._compiler) is tamarin.TamarinCompiler
            and value._version_probe is value._maude_probe is value._available_probe is None,
            "default runner/compiler/probes changed")
    require(value._runner.cpu_slots == 2 and value._runner.child_process_slots == 8
            and value._runner._default_executor and value._runner._resource_scheduler is None
            and value._runner._parent_lease is None
            and "GHCRTS" not in value._runner._base_environment
            and "DEBUG_MAUDE" not in value._runner._base_environment,
            "owned default execution profile changed")
    return value


class Audit(LaunchAudit):
    """Delegate real admission and record refusals without synthetic capacity."""

    def __init__(self, owner):
        super().__init__(owner)
        self.requests, self.admissions, self.workspaces = [], [], []

    def install_observers(self):
        super().install_observers()
        from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
        from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
        acquire = self.owner.acquire

        def observed_acquire(lane, **kwargs):
            row = {"case": self.local.case, "lane": lane, "at_monotonic": time.monotonic(),
                **{key: kwargs[key] for key in (*PROFILE, "timeout", "request_id")},
                "parent_lease_absent": kwargs["parent_lease"] is None,
                "cancellation_signal_present": kwargs["cancel_event"] is not None}
            self.admissions.append(row)
            try:
                value = acquire(lane, **kwargs)
                row["lease_id"] = value.lease_id
                return value
            except Exception as error:
                row.update(error_type=type(error).__name__, error=str(error))
                raise

        self.owner.acquire = observed_acquire
        run = ResourceAdmittedToolRunner.run

        def observed_run(runner, req, **kwargs):
            operation = current_proof_operation()
            forwarded = kwargs.get("cancellation")
            self.requests.append({"case": self.local.case, "at_monotonic": time.monotonic(),
                "deadline": operation.deadline if operation else None,
                "argv": list(req.argv), "limits": asdict(req.limits),
                "input_files": dict(req.input_files), "environment": dict(req.environment),
                "explicit_cancellation_forwarded": forwarded is not None,
                "forwarded_signal_is_current_operation": operation is not None and forwarded is operation})
            return run(runner, req, **kwargs)

        ResourceAdmittedToolRunner.run = observed_run

    def observe(self, name, args):
        if name == "tempfile.mkdtemp" and "logic-tool-" in str(args[0]):
            self.workspaces.append({"case": getattr(self.local, "case", "setup"), "path": str(args[0])})
        return super().observe(name, args)


def run_case(route, paths, audit):
    from ipfs_datasets_py.logic.backends.protocol import tamarin, execution_v2 as v2
    from ipfs_datasets_py.logic.backends.process import BoundedToolRunner, SubprocessExecutor
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    from ipfs_datasets_py.logic.ir_core.protocols import stable_digest
    require(current_proof_operation() is None and sys.getprofile() is None, "unexpected ambient operation/profiler")
    audit.local.case = route
    req, selected = request(route), backend(paths)
    outcomes, canonical, observations, semantic_calls, native_calls = [], [], [], [], []
    methods = {f.__code__: name for name, f in (
        ("backend_run", tamarin.TamarinBackend.run), ("compile_request", tamarin.TamarinBackend._compile_request),
        ("toolchain", tamarin.TamarinBackend.probe_toolchain), ("availability", tamarin.TamarinBackend.is_available))}
    semantics = {f.__code__: f.__name__ for f in (tamarin.parse_tamarin_claim_outcomes,
        tamarin.classify_claim_outcomes, tamarin.parse_attack_trace)}
    execution = {BoundedToolRunner.run.__code__, SubprocessExecutor.execute.__code__}

    def observer(frame, event, value):
        if event == "call" and frame.f_code in semantics:
            semantic_calls.append(semantics[frame.f_code])
        if event == "call" and frame.f_code in execution:
            native_calls.append(frame.f_code.co_name)
        if event not in {"call", "return"} or frame.f_code not in methods:
            return
        operation = current_proof_operation()
        observations.append({"phase": methods[frame.f_code], "event": event,
            "deadline": operation.deadline if operation else None, "at_monotonic": time.monotonic()})
        if frame.f_code is tamarin.TamarinBackend.run.__code__:
            if event == "call":
                canonical.append(frame.f_locals["request"])
            elif isinstance(value, tamarin.TamarinBackendOutcome):
                outcomes.append(value)

    started = time.monotonic()
    sys.setprofile(observer)
    try:
        returned = selected.run(req) if route == "direct" else v2.ProtocolExecutionEngineV2(tamarin=selected).execute(req)
    finally:
        sys.setprofile(None)
    require(current_proof_operation() is None and len(outcomes) == len(canonical) == 1, "scope/result binding changed")
    original = outcomes[0]
    def single(rows):
        values = [r for r in rows if r["case"] == route]
        require(len(values) == 1, "expected one default admission/lifecycle record")
        return values[0]
    lifecycle, tool, admission = map(single, (audit.results, audit.requests, audit.admissions))
    raw, typed, receipt = lifecycle["result"], original.result.to_dict(), original.receipt.to_dict()
    require(audit.owner.config.total_child_process_slots < PROFILE["child_process_slots"],
            "this qualification accepts only the reviewed insufficient-capacity route")
    require({k: admission[k] for k in PROFILE} == PROFILE and admission["lane"] == "validation"
            and admission["parent_lease_absent"] and admission["cancellation_signal_present"]
            and 0 < admission["timeout"] <= 5 and admission.get("error_type") == "ResourceUnavailableError"
            and admission.get("error") == "child-process request exceeds configured process capacity"
            and "lease_id" not in admission, "actual scheduler did not reject the requested impossible profile")
    require(raw["resource_exhausted"] and raw["returncode"] is raw["pid"] is None
            and raw["workspace_cleaned"] and raw["stdout"] == raw["stderr"] == ""
            and bool(raw["error"]) and not any(raw[k] for k in ("cancelled", "timed_out", "unavailable",
                "output_truncated", "workspace_limit_exceeded", "process_tree_terminated")), "unclean admission refusal")
    require(not audit.events and not audit.workspaces and not native_calls and not semantic_calls,
            "refused request entered native execution, workspace creation or semantic parsing")
    require(typed["status"] == "error" and typed["authority"] == "protocol" and typed["translation_ceiling"] == "none"
            and receipt["accepted"] is False and receipt["claim_outcomes"] == []
            and receipt["quarantine"] is None and "attack_traces" not in typed["witness"], "refusal gained semantic evidence")
    expected_metadata = {k: raw[k] for k in ("cancelled", "command", "error", "output_truncated",
        "process_tree_terminated", "returncode", "resource_exhausted", "timed_out", "termination_reason",
        "unavailable", "workspace_cleaned", "workspace_limit_exceeded")}
    expected_metadata.update(stdout_digest=stable_digest({"content": raw["stdout"]}),
        stderr_digest=stable_digest({"content": raw["stderr"]}))
    require(typed["metadata"]["process"] == expected_metadata and raw["command"] == tool["argv"], "raw lifecycle metadata lost")
    require(original.request_digest == canonical[0].digest
            and canonical[0] == canonical_request(route)
            and original.source_binding == tamarin.TamarinSourceBinding.bind(canonical[0], SOURCE, "spthy")
            and original.compile_result.source == SOURCE
            and original.compile_result.claim_lemmas.to_dict() == {"emitted_has_event": "emitted_has_event"}, "source/request binding differs")
    require(all(row["deadline"] == tool["deadline"] for row in observations)
            and (tool["deadline"] is not None) == (route == "standalone_v2")
            and tool["explicit_cancellation_forwarded"] == (route == "standalone_v2"), "operation/cancellation ownership differs")
    wire = returned.to_dict()
    if route == "standalone_v2":
        require(tool["forwarded_signal_is_current_operation"] and wire["backend_outcome"] == original.to_dict()
                and wire["disposition"] == "error" and not wire["protocol_established"]
                and not wire["is_proved"] and not wire["is_theorem_authority"], "V2 promoted refused evidence")
    after = saved.state_summary(audit.owner.state_path)
    require(not after["owned_active_leases"] and not after["owned_waiting_requests"], "owned work did not drain")
    return {"case": route, "request": req.to_dict(), "canonical_request": canonical[0].to_dict(),
        "original_outcome": original.to_dict(), "result": wire, "tool_request": tool, "admission": admission,
        "lifecycle": lifecycle, "operation_observations": observations, "semantic_calls": semantic_calls,
        "native_execution_calls": native_calls, "elapsed_seconds": time.monotonic() - started,
        "outcome_kind": "real_default_admission_refusal", "native_solver_executed": False,
        "default_runner_compiler_and_probes": True, "ambient_absent_before_and_after": True,
        "observer_restored": sys.getprofile() is None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    directory = parser.parse_args().output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "tamarin-default-admission-benchmark@1", "status": "running",
        "source_pins_before": pins(), "runtime": saved.runtime(), "cases": [], "checks": {},
        "scope": {"real_default_admission": True, "native_solver_success": False,
            "native_tamarin_execution": False, "managed_launcher_execution": False,
            "benchmark_operation_scope_injected": False, "runner_or_probe_injected": False,
            "resource_sampler_injected": False, "pool_widened": False, "installation": False,
            "version_probe": False, "semantic_claim_binding_qualified": False, "semantic_attack_replay": False,
            "native_cancellation_tested": False, "parallel_scaling_claim": False, "hard_aggregate_containment": False}}
    owner = audit = None
    started = time.monotonic()
    try:
        paths, files, evidence = selected_tools()
        result.update(tool_selection=paths, tool_files_before=files, installed_ghc_review=evidence)
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = install_saved_owner(directory / "saved-scheduler-config.json")
        result.update(shared_before=saved.state_summary(owner.state_path), shared_pool_compatibility=owner._benchmark_pool_compatibility)
        require(owner.config.total_child_process_slots == 4,
                "qualification requires the reviewed four-process pool; changed capacity needs a new native review")
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import collect_proof_host_resources
        result["sampler_configuration"] = {
            "resource_pressure_sampler_is_default": owner.config.resource_pressure_sampler is None,
            "proof_resource_sampler_is_default": owner.config.proof_resource_sampler is collect_proof_host_resources,
            "pressure_sample_during_refused_acquisition_claimed": False}
        require(result["sampler_configuration"]["resource_pressure_sampler_is_default"]
                and result["sampler_configuration"]["proof_resource_sampler_is_default"], "host sampler substituted")
        audit = Audit(owner)
        audit.install_observers()
        sys.addaudithook(audit.observe)
        for route in CASES:
            result["cases"].append(run_case(route, paths, audit))
            write(directory / "partial.json", result)
        result["checks"].update(two_real_default_refusals=len(result["cases"]) == len(audit.requests) == len(audit.results) == len(audit.admissions) == 2,
            no_native_launches=not audit.events, no_native_workspaces=not audit.workspaces,
            no_semantic_evidence=all(not c["original_outcome"]["receipt"]["accepted"] for c in result["cases"]),
            observers_restored=all(c["observer_restored"] for c in result["cases"]))
        result["status"] = "qualified_capacity_refusal_only"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
    finally:
        if audit is not None:
            result["audit_sha256"] = {}
            for name, value in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results),
                    ("request-audit.json", audit.requests), ("admission-audit.json", audit.admissions), ("workspace-audit.json", audit.workspaces)):
                write(directory / name, value)
                result["audit_sha256"][name] = sha(directory / name)
            result["launches"] = len(audit.events)
            result["native_launches"] = len(audit.events)
            result["workspace_count"] = len(audit.workspaces)
            result["workspaces"] = len(audit.workspaces)
        if owner is not None:
            result["shared_after"] = saved.state_summary(owner.state_path)
            result["checks"].update(shared_config_unchanged=result["shared_before"]["config"] == result["shared_after"]["config"],
                foreign_work_counts_unchanged=all(result["shared_before"][key] == result["shared_after"][key]
                    for key in ("active_leases", "waiting_requests")),
                owned_work_drained=not result["shared_after"]["owned_active_leases"] and not result["shared_after"]["owned_waiting_requests"])
        if "tool_files_before" in result:
            result["tool_files_after"] = {p: sha(p) for p in result["tool_files_before"]}
            result["checks"]["selected_files_unchanged"] = result["tool_files_before"] == result["tool_files_after"]
        result["source_pins_after"] = pins()
        result["checks"]["sources_stable"] = result["source_pins_before"] == result["source_pins_after"]
        result["elapsed_seconds"] = time.monotonic() - started
        result["child_usage"] = {k: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), k) for k in ("ru_utime", "ru_stime", "ru_maxrss")}
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "checks": result["checks"], "result": str(directory / "result.json")}))
    return 0 if result["status"] == "qualified_capacity_refusal_only" else 1


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT.parent / "ipfs_accelerate"), str(ROOT)]
    raise SystemExit(main())
