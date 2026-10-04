"""Small real Hyper checks using audited vendor identities and default admission.

This driver never installs or substitutes an engine, fixture runner, resource
sampler, or scheduler. Fixture constructors supply only documents and models.
Results establish bounded native smoke compatibility, not semantic witness
reconstruction, full certification, or many-core scaling.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict, fields
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ACCELERATE = ROOT.parent / "ipfs_accelerate"
sys.path[:0] = [str(ROOT), str(ACCELERATE)]

from ipfs_datasets_py.logic.backends.hyperproperties import adapters
from ipfs_datasets_py.logic.backends import process, resource_admission
from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
from ipfs_datasets_py.logic.backends.installers.install_control import installation_scope
from ipfs_datasets_py.logic.backends.smt.operation_budget import proof_operation_scope
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler
from tools.logic.certification import hyperproperty as fixtures

# The fixture module supports script execution by adjusting sys.path. Restore
# this driver's explicit checkout precedence before any lazy imports occur.
sys.path[:0] = [str(ROOT), str(ACCELERATE)]
MIB = 1024**2
LOCK_PATH = hp.resolve_lock_path(ACCELERATE).resolve()
ENGINES = ("hyperltl", "autohyper", "mchyper")
BACKENDS = {"hyperltl": adapters.HyperLTLBackend, "autohyper": adapters.AutoHyperBackend,
            "mchyper": adapters.MCHyperBackend}
UNSAFE = ("timed_out", "cancelled", "unavailable", "output_truncated",
          "workspace_limit_exceeded", "process_tree_terminated", "resource_exhausted", "error")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(MIB), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def source_inventory():
    require(Path(adapters.__file__).resolve() == ROOT / "ipfs_datasets_py/logic/backends/hyperproperties/adapters.py",
            "datasets runtime came from an unexpected checkout")
    require(Path(fixtures.__file__).resolve() == ACCELERATE / "tools/logic/certification/hyperproperty.py",
            "fixture constructors came from an unexpected checkout")
    require(LOCK_PATH.is_file(), "reviewed deployment lock is unavailable")
    paths = {Path(__file__).resolve(), LOCK_PATH}
    for module in tuple(sys.modules.values()):
        name = getattr(module, "__name__", "")
        filename = getattr(module, "__file__", None)
        if filename and (name.startswith("ipfs_datasets_py.logic")
                or name.startswith("ipfs_datasets_py.optimizers.logic_theorem_optimizer")
                or name.startswith("tools.logic.certification")):
            path = Path(filename).resolve()
            if path.is_file() and path.suffix == ".py":
                require(ROOT in path.parents or ACCELERATE in path.parents,
                        "fixture/runtime source outside selected checkouts")
                paths.add(path)
    return tuple(sorted(paths))


def pin(paths):
    return {str(path): sha(path) for path in paths}


def text_stream(value):
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


class NativeAudit:
    """Delegate every operation; associate each launch with its actual lease."""
    def __init__(self, directory):
        self.directory, self.stack, self.local = directory, ExitStack(), threading.local()
        self.admissions, self.invocations, self.launches, self.lifecycles = [], [], [], []
        self.children, self.leases = [], []

    def __enter__(self):
        try:
            return self._enter()
        except BaseException:
            self.stack.close()
            raise

    def _enter(self):
        self.owner = resource_scheduler.get_global_resource_scheduler()
        self.before = self.owner.snapshot()
        actual_getter = resource_admission.get_global_resource_scheduler
        def observed_getter():
            owner = actual_getter()
            require(owner is self.owner, "default runner selected a different shared owner")
            return owner
        self.stack.enter_context(patch.object(resource_admission, "get_global_resource_scheduler", observed_getter))
        actual_acquire = self.owner.acquire
        def observed_acquire(lane, **kwargs):
            row = {"case": self.local.case, "requested_at": time.monotonic(), "lane": str(lane),
                   **{key: kwargs[key] for key in ("cpu_slots", "memory_mb", "child_process_slots", "timeout")}}
            self.admissions.append(row)
            require((row["cpu_slots"], row["memory_mb"], row["child_process_slots"]) == (2, 512, 4),
                    "managed Hyper reservation differs from the reviewed profile")
            lease = actual_acquire(lane, **kwargs)
            self.leases.append(lease)
            self.local.lease = lease
            actual_release = lease.release
            try:
                row.update(lease=lease.to_dict(), granted_at=time.monotonic())
                def observed_release():
                    result = actual_release()
                    row.update(released=lease.released, released_at=time.monotonic())
                    return result
                self.stack.enter_context(patch.object(lease, "release", observed_release))
            except BaseException:
                # Until this observer returns, the runner does not own the
                # acquired lease and cannot release it on an observation error.
                actual_release()
                row.update(released=lease.released, observer_setup_failed=True)
                raise
            return lease
        self.stack.enter_context(patch.object(self.owner, "acquire", observed_acquire))
        actual_execute = process.SubprocessExecutor.execute
        def observed_execute(executor, invocation, cancellation=None):
            lease = self.local.lease
            require(not lease.released and not lease.cancelled, "executor entry lacks a live owned reservation")
            require(Path(invocation.argv[0]).resolve() == self.local.executable,
                    "unexpected native executable or follow-up phase")
            limits = asdict(invocation.limits)
            require(0 < limits["timeout_seconds"] <= 30 and 0 < limits["cpu_seconds"] <= 30,
                    "native wall/CPU limits are not finite")
            require(limits["resident_memory_bytes"] == 512*MIB and limits["max_output_bytes"] <= MIB
                    and 0 < limits["max_workspace_bytes"] <= 16*MIB, "native resource profile changed")
            expected_as = (4 if self.local.engine == "autohyper" else 2) * 1024*MIB
            require(limits["memory_bytes"] == expected_as and limits["enforce_file_size_limit"]
                    is (self.local.engine != "autohyper"), "managed-runtime address/file limits changed")
            row = {"case": self.local.case, "argv": list(invocation.argv), "cwd": str(invocation.cwd),
                   "limits": limits, "lease_id": lease.lease_id, "entered_at": time.monotonic(),
                   "environment": {key: invocation.environment[key] for key in
                       ("DOTNET_ROOT", "DOTNET_PROCESSOR_COUNT", "DOTNET_gcServer", "DOTNET_GCHeapHardLimit",
                        "EAHYPER_SOLVER_DIR") if key in invocation.environment}}
            self.invocations.append(row)
            self.local.invocation = row
            try:
                raw = actual_execute(executor, invocation, cancellation)
                row["raw_process"] = {field.name: text_stream(getattr(raw, field.name)) for field in fields(raw)}
                return raw
            finally:
                row["completed_at"] = time.monotonic()
                self.local.invocation = None
        self.stack.enter_context(patch.object(process.SubprocessExecutor, "execute", observed_execute))
        actual_popen = process.SubprocessExecutor.__init__.__kwdefaults__["popen"]
        def observed_popen(*args, **kwargs):
            invocation = getattr(self.local, "invocation", None)
            lease = getattr(self.local, "lease", None)
            require(invocation is not None and lease is not None and not lease.released and not lease.cancelled,
                    "native launch without the exact active invocation lease")
            require(kwargs.get("shell") is False and kwargs.get("start_new_session") is True,
                    "native process lacks bounded tree ownership")
            child = actual_popen(*args, **kwargs)
            # Ownership is recorded immediately; no post-spawn assertions may
            # throw before the real executor can finish its cleanup lifecycle.
            self.children.append(child)
            self.launches.append({"case": self.local.case, "pid": child.pid, "lease_id": lease.lease_id,
                                  "argv": list(args[0]), "cwd": str(kwargs["cwd"]), "at": time.monotonic()})
            return child
        self.stack.enter_context(patch.object(subprocess, "Popen", observed_popen))
        self.stack.enter_context(patch.dict(process.SubprocessExecutor.__init__.__kwdefaults__, {"popen": observed_popen}))
        actual_run = resource_admission.ResourceAdmittedToolRunner.run
        def observed_run(runner, request, **kwargs):
            value = actual_run(runner, request, **kwargs)
            row = {field.name: getattr(value, field.name) for field in fields(value) if field.name != "output_files"}
            row.update(case=self.local.case, runtime=value.runtime.value, command=list(value.command), output_files={})
            for index, (name, content) in enumerate(value.output_files.items()):
                target = self.directory / f"{self.local.case}-output-{index}.bin"
                target.write_bytes(content)
                row["output_files"][name] = {"artifact": target.name, "bytes": len(content), "sha256": sha(target)}
            self.lifecycles.append(row)
            return value
        self.stack.enter_context(patch.object(resource_admission.ResourceAdmittedToolRunner, "run", observed_run))
        return self

    def __exit__(self, *args):
        try:
            self.after = self.owner.snapshot()
            self.cleanup = {"owned_processes_reaped": all(child.poll() is not None for child in self.children),
                "owned_leases_released": all(lease.released for lease in self.leases),
                "owned_workspaces_removed": all(not Path(row["cwd"]).exists() for row in self.invocations),
                "shared_capacity_unchanged": self.before["capacity"] == self.after["capacity"]}
        finally:
            self.stack.close()


def run(directory, install_root, tools):
    sources = source_inventory()
    result = {"status": "running", "source_pins_before": pin(sources), "cases": [], "identities": {},
        "install_root": str(install_root), "tools": list(tools), "deployment_lock": str(LOCK_PATH),
        "scope": {"real_vendor_engines": True, "default_resource_admission": True, "actual_shared_scheduler": True,
            "synthetic_execution": False, "installation_attempted": False, "fallback_permitted": False,
            "semantic_witness_reconstruction_qualified": False, "upstream_certification": False,
            "scaling_claim": False, "hard_aggregate_containment": False}}
    started = time.monotonic()
    audit = None
    try:
        specs = {spec.case_id: spec for spec in fixtures.default_case_specs()}
        with ExitStack() as guards:
            def forbidden(*args, **kwargs):
                raise AssertionError("native smoke driver must not install, publish, or download")
            for name in ("_ensure_tool", "_download_verified_archive", "_publish_managed_vendor_launcher", "_replace_install_tree"):
                guards.enter_context(patch.object(hp, name, forbidden))
            guards.enter_context(patch.object(fixtures, "backend_for", forbidden))
            guards.enter_context(patch.object(fixtures, "run_engine_case", forbidden))
            identities = {}
            for engine in tools:
                with installation_scope(operation_timeout_ms=60_000):
                    identity = hp._identity_from_disk(engine, install_root,
                        hp.pin_for_tool(engine, repo_root=ACCELERATE, lock_path=LOCK_PATH), vendor=True)
                require(identity is not None and identity.is_vendor_build and identity.is_upstream_build
                        and not identity.is_hermetic_engine and not identity.authorizes_universal_proof,
                        "missing or invalid audited upstream identity: " + engine)
                identities[engine] = identity
                result["identities"][engine] = identity.to_dict()
            with NativeAudit(directory) as audit:
                for engine in tools:
                    for violated in ((False,) if engine == "hyperltl" else (False, True)):
                        case_id = engine + ("-violated" if violated else "-holds")
                        audit.local.case = case_id
                        audit.local.engine = engine
                        audit.local.executable = Path(identities[engine].executable).resolve()
                        backend = BACKENDS[engine](engine_identity=identities[engine])
                        require(type(backend._runner) is resource_admission.ResourceAdmittedToolRunner and backend._managed_runner,
                                "backend did not retain its default admitted runner")
                        document = fixtures.materialize_document(specs["case:ni_violated" if violated else "case:ni_holds"])
                        system = fixtures.vendor_system_model(engine, violated=violated)
                        bounds = ExecutionBounds(timeout_ms=30_000, max_steps=64, max_memory_bytes=512*MIB, max_output_bytes=MIB)
                        row = {"case": case_id, "engine": engine, "expected": "violated" if violated else "satisfied",
                            "document": document.to_dict(), "system_model": system, "bounds": bounds.to_dict()}
                        result["cases"].append(row)
                        case_start = time.monotonic()
                        with proof_operation_scope(timeout_ms=30_000):
                            outcome = backend.check(document, bounds=bounds, system_model=system, allow_fallback=False)
                        row.update(elapsed_seconds=time.monotonic()-case_start, outcome=outcome.to_dict())
                        require(outcome.receipt.status.value == row["expected"], "unexpected native verdict: " + case_id)
                        require(outcome.receipt.evidence_path is adapters.HyperEvidencePath.ENGINE
                                and outcome.receipt.fallback_bounds is None and not outcome.receipt.authorizes_universal_proof,
                                "native result changed evidence path or authority")
                        require(outcome.result.bounds == bounds and outcome.result.authority.value == "hyperproperty",
                                "native result changed declared bounds or authority")
                        lifecycle = [value for value in audit.lifecycles if value["case"] == case_id]
                        require(len(lifecycle) == 1 and lifecycle[0]["returncode"] == 0
                                and lifecycle[0]["workspace_cleaned"] and not any(lifecycle[0][key] for key in UNSAFE),
                                "native verdict lacked a clean complete lifecycle")
                        row["passed"] = True
            require(all(audit.cleanup.values()), "owned native lifecycle did not drain")
            result["identities_after"] = {}
            for engine in tools:
                with installation_scope(operation_timeout_ms=60_000):
                    identity = hp._identity_from_disk(engine, install_root,
                        hp.pin_for_tool(engine, repo_root=ACCELERATE, lock_path=LOCK_PATH), vendor=True)
                require(identity is not None, "vendor identity failed its final read-only audit: " + engine)
                result["identities_after"][engine] = identity.to_dict()
            require(result["identities"] == result["identities_after"], "vendor identity changed during native checks")
        result["source_pins_after"] = pin(sources)
        require(result["source_pins_before"] == result["source_pins_after"], "source changed during native smoke checks")
        result["checks"] = {"all_requested_cases_passed": all(row.get("passed") for row in result["cases"]),
            "exact_case_count": len(result["cases"]) == sum(1 if tool == "hyperltl" else 2 for tool in tools),
            "one_admitted_native_launch_per_case": len(audit.launches) == len(audit.invocations) == len(audit.admissions)
                == len(audit.lifecycles) == len(result["cases"]), **audit.cleanup,
            "vendor_identities_unchanged": True, "source_pins_stable": True}
        require(all(result["checks"].values()), "native smoke checks incomplete")
        result["status"] = "passed_bounded_native_smoke"
    except BaseException as error:
        result.update(status="failed", exception_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
        result["source_pins_after"] = pin(sources)
    finally:
        result["elapsed_seconds"] = time.monotonic()-started
        if audit is not None:
            result.update(admissions=audit.admissions, invocations=audit.invocations, native_launches=audit.launches,
                lifecycles=audit.lifecycles, shared_pool_before=audit.before,
                shared_pool_after=getattr(audit, "after", None), cleanup=getattr(audit, "cleanup", None))
        write(directory / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--tools", nargs="+", choices=ENGINES, default=list(ENGINES))
    args = parser.parse_args()
    require(len(set(args.tools)) == len(args.tools), "duplicate tools requested")
    root, directory = args.install_root.expanduser().resolve(), args.output_dir.expanduser().resolve()
    require(root.is_dir(), "install root does not exist")
    directory.mkdir(parents=True, exist_ok=False)
    result = run(directory, root, args.tools)
    print(json.dumps({key: result[key] for key in ("status", "elapsed_seconds", "tools")}))
    return 0 if result["status"] == "passed_bounded_native_smoke" else 1


if __name__ == "__main__":
    raise SystemExit(main())
