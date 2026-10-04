"""Shared-owner Isabelle installation with bounded staging and native checks.

Only the controller publishes paths, under the legacy install lock. Ordinary
exceptions roll back both paths; this is not crash-atomic publication. Large
cleanup runs in a bounded child and unfinished staging is explicitly retained.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from urllib.parse import urlparse

from . import isabelle as legacy, isabelle_profile as profile
from .isabelle_preparation import prepare_isabelle_runtime
from ..process import BoundedToolRunner, ToolRunLimits, ToolRunRequest
from ....optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceLease, LeaseCancelledError, LeaseTimeoutError,
    get_global_resource_scheduler,
)

SCHEMA = "isabelle-bounded-installation@1"
WORKER_MODULE = "ipfs_datasets_py.logic.backends.installers.isabelle_install_worker"
WORKER_MEMORY_MB = 512
MAX_RECEIPT_BYTES = 32 * 1024


@dataclass(slots=True)
class IsabelleInstallationReceipt:
    status: str = "failed"
    reason_codes: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    installed: bool = False
    already_present: bool = False
    launcher_repaired: bool = False
    build_hol_requested: bool = False
    hol_build: dict = field(default_factory=dict)
    download_attempted: bool = False
    checksum_verified: bool = False
    executable: str | None = None
    install_root: str = ""
    resource_lease_id: str = ""
    elapsed_seconds: float = 0
    preparation: dict = field(default_factory=dict)
    staged_preparation: dict = field(default_factory=dict)
    worker: dict = field(default_factory=dict)
    cleanup: dict = field(default_factory=dict)
    cleanup_pending: list[str] = field(default_factory=list)
    recovery: dict = field(default_factory=dict)
    pin: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)

    @property
    def usable(self):
        return self.status in {"installed", "already_present"} and self.preparation.get("usable") is True

    def to_dict(self):
        return {**asdict(self), "schema_version": SCHEMA, "tool_id": "isabelle",
            "usable": self.usable, "executable_path": self.executable,
            "grants_proof_authority": False, "grants_repository_authority": False,
            "scope": {
                "publication": "Controller rename/launcher transaction with ordinary-exception rollback; not crash-atomic.",
                "deadline": "Includes admission, lock, download, extraction, native checks. Rollback is completed despite cancellation; cleanup is best effort after commit.",
                "memory": "Sampled process-tree RSS and per-process address space; not an aggregate cgroup ceiling.",
                "storage": "Archive/extraction caps govern external cache/staging; workspace limit is also a per-file OS ceiling, not an aggregate external staging ceiling.",
                "runtime": "Selected-file identities and a fixed True smoke; trusted installed heaps/components/libraries, no repository proof.",
                "heap_build": ("Fixed HOL rebuild in unpublished official staging; fresh verification before and after publication."
                               if self.build_hol_requested else "No explicit persistent HOL heap build."),
            }}


class IsabelleInstallationError(legacy.IsabelleInstallerError):
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__("; ".join(receipt.reason_codes + receipt.messages))


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _launcher_bytes(destination):
    return ("#!/usr/bin/env bash\nset -euo pipefail\n"
        f"export ISABELLE_HOME={legacy._shell_quote(str(destination))}\n"
        f'exec {legacy._shell_quote(str(destination / "bin/isabelle"))} "$@"\n').encode()


def _validate_worker_result(observed, request, argv):
    if (observed.command != argv or not observed.ok or observed.error or observed.output_truncated
            or observed.workspace_limit_exceeded or not observed.workspace_cleaned):
        raise ValueError("bounded_archive_worker_incomplete")
    raw = observed.output_files.get("result.json", b"")
    if not raw or len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError("archive_worker_receipt_size")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate archive receipt key")
            result[key] = value
        return result
    result = json.loads(raw, object_pairs_hook=unique)
    expected = {"schema": "isabelle-archive-staging-result@2",
        "request_sha256": hashlib.sha256(_canonical(request)).hexdigest(),
        "version": request["version"], "platform_key": request["platform_key"],
        "sha256": request["sha256"], "candidate_relative_path": request["version"]}
    if (not isinstance(result, dict) or set(result) != {*expected, "archive_size_bytes"}
            or any(result.get(key) != value for key, value in expected.items())
            or type(result["archive_size_bytes"]) is not int
            or not 0 < result["archive_size_bytes"] <= legacy.MAX_DOWNLOAD_BYTES):
        raise ValueError("archive_worker_receipt_binding")
    candidate = Path(request["staging_dir"]) / request["version"]
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError("archive_worker_candidate_layout")
    return result


def ensure_isabelle_installation(*, yes=False, strict=True, force=False, on_progress=None,
        install_root=None, timeout_seconds=None, parent_lease=None, scheduler=None,
        cancellation=None, memory_mb=2048, build_hol=False, allow_download=True,
        build_memory_mb=6144):
    """Reuse or install the pinned runtime through the actual shared scheduler.

    Installation is explicit (yes=True); safety cannot be disabled on this API.
    Strict controls raising vs a failure receipt, never pin verification. A
    successful cold or warm result includes a fresh fixed kernel smoke. Explicit
    build_hol recreates HOL in an independent verified archive, then publishes
    persistent system heaps. allow_download=False requires the local pinned cache
    and cannot fall back to the network or modify the current runtime in place.
    """
    for name, value in (("yes", yes), ("strict", strict), ("force", force),
                        ("build_hol", build_hol), ("allow_download", allow_download)):
        if type(value) is not bool:
            raise TypeError(f"{name} must be bool")
    if timeout_seconds is None:
        timeout_seconds = 3600 if build_hol else 600
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 3600):
        raise ValueError("timeout_seconds must be finite in (0, 3600]")
    if type(memory_mb) is not int or not 1024 <= memory_mb <= 4096:
        raise ValueError("memory_mb must be an exact integer in [1024, 4096]")
    if type(build_memory_mb) is not int or not 2048 <= build_memory_mb <= 8192:
        raise ValueError("build_memory_mb must be an exact integer in [2048, 8192]")
    if parent_lease is not None and not isinstance(parent_lease, ResourceLease):
        raise TypeError("parent_lease must be an actual datasets ResourceLease")
    if scheduler is not None and not isinstance(scheduler, GlobalResourceScheduler):
        raise TypeError("scheduler must be an actual datasets GlobalResourceScheduler")
    if parent_lease is not None and scheduler is not None:
        raise ValueError("supply only parent_lease or scheduler")
    if cancellation is not None and not callable(getattr(cancellation, "is_set", None)):
        raise TypeError("cancellation must supply is_set()")
    if on_progress is not None and not callable(on_progress):
        raise TypeError("on_progress must be callable")
    started = time.monotonic()
    deadline = started + timeout_seconds
    signal, envelope, stage = cancellation, None, None
    reservation_memory_mb = max(memory_mb, build_memory_mb if build_hol else 0) + profile.OVERHEAD_MB
    cpu_slots = max(profile.CPU_SLOTS, 4 if build_hol else 0)
    receipt = IsabelleInstallationReceipt(build_hol_requested=build_hol, limits={"timeout_seconds": timeout_seconds,
        "cpu_slots": cpu_slots, "process_slots": profile.PROCESS_SLOTS,
        "reservation_memory_mb": reservation_memory_mb,
        "worker_memory_mb": WORKER_MEMORY_MB, "worker_address_space_bytes": 2 * 1024**3,
        "native_memory_mb": memory_mb, "native_address_space_bytes": profile.ADDRESS_SPACE_BYTES,
        "build_memory_mb": build_memory_mb if build_hol else None,
        "allow_download": allow_download,
        "archive_bytes": legacy.MAX_DOWNLOAD_BYTES, "expanded_bytes": legacy.MAX_EXTRACTED_BYTES,
        "extracted_file_bytes": legacy.MAX_EXTRACTED_FILE_BYTES, "archive_members": legacy.MAX_ARCHIVE_MEMBERS})

    def remaining():
        if signal is not None and signal.is_set():
            raise LeaseCancelledError("Isabelle installation cancelled")
        duration = deadline - time.monotonic()
        if duration <= 0:
            raise LeaseTimeoutError("Isabelle installation deadline exceeded")
        return duration

    def announce(phase, message):
        if on_progress:
            on_progress(phase, message)
        remaining()

    # Imports resolve from the selected source tree, not from an inherited
    # PYTHONPATH that may contain an older nested checkout.
    source_root = str(Path(__file__).resolve().parents[4])
    runner = BoundedToolRunner(base_environment={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C",
        "PYTHONPATH": source_root, "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0"})

    def python_child(argv, *, inputs=None, outputs=(), phase, max_seconds=None):
        with envelope.acquire_child(lane="validation", cpu_slots=1, memory_mb=WORKER_MEMORY_MB,
                child_process_slots=1, timeout=remaining(), cancel_event=signal,
                request_id="isabelle:" + phase) as child:
            budget = remaining()
            if max_seconds is not None:
                budget = min(max_seconds, budget)
            request = ToolRunRequest(argv=argv, input_files=inputs or {}, output_paths=outputs,
                limits=ToolRunLimits(timeout_seconds=budget, cpu_seconds=budget,
                    memory_bytes=2 * 1024**3, resident_memory_bytes=WORKER_MEMORY_MB * 1024**2,
                    max_input_bytes=MAX_RECEIPT_BYTES, max_output_bytes=MAX_RECEIPT_BYTES,
                    max_workspace_bytes=legacy.MAX_DOWNLOAD_BYTES))
            observed = runner.run(request, cancellation=child.combined_cancellation_signal(signal))
            return observed, {"child_lease_id": child.lease_id, "timeout_seconds": budget,
                              "observation": observed.to_dict()}

    def prepare(path, phase):
        announce(phase, "Checking pinned Isabelle with a bounded fixed kernel smoke")
        result = prepare_isabelle_runtime(mode="smoke", install_root=path,
            parent_lease=envelope, cancellation=signal, memory_mb=memory_mb,
            timeout_seconds=min(300, remaining()))
        remaining()
        return result.to_dict()

    def cleanup_stage():
        if stage is None or not stage.exists():
            return
        receipt.cleanup_pending = [str(stage)]
        try:
            # This path was created here, beneath the locked install root. No
            # caller-supplied deletion requests are accepted by a public API.
            observed, record = python_child((sys.executable, "-I", "-c",
                "import shutil,sys; shutil.rmtree(sys.argv[1])", str(stage)),
                phase="cleanup", max_seconds=30)
            receipt.cleanup = record
            if observed.ok and not observed.error and observed.workspace_cleaned and not stage.exists():
                receipt.cleanup_pending = []
        except Exception as exc:
            receipt.cleanup = {"reason": type(exc).__name__, "message": str(exc)}

    def repair_warm_launcher(root, runtime):
        nonlocal stage
        target = Path(runtime["runtime_root"])
        # When the caller selected the distribution itself, bin/isabelle is the
        # native launcher and must never be replaced by a self-referencing stub.
        if target == root:
            return True
        launcher = root / "bin/isabelle"
        if launcher.parent.is_symlink():
            raise ValueError("managed_bin_must_not_be_symlink")
        try:
            correct = (profile.regular_bytes(launcher, profile.MAX_INPUT_BYTES, remaining)
                       == _launcher_bytes(target) and os.access(launcher, os.X_OK))
        except (OSError, ValueError):
            correct = False
        if correct:
            return True
        if not yes:
            receipt.status, receipt.reason_codes = "blocked", ["managed_launcher_repair_requires_yes"]
            return False
        announce("launcher_repair", "Repairing managed launcher for the validated runtime")
        stage = Path(tempfile.mkdtemp(prefix=".bounded-isabelle-", dir=root))
        receipt.cleanup_pending = [str(stage)]
        backup = root / "bin/.isabelle.previous"
        had_launcher = os.path.lexists(launcher)
        moved = attempted = False
        try:
            if had_launcher:
                launcher.replace(backup)
                moved = True
            attempted = True
            legacy.write_launcher("isabelle", target / "bin/isabelle", install_root=root,
                                  environment={"ISABELLE_HOME": str(target)})
            if (profile.regular_bytes(launcher, profile.MAX_INPUT_BYTES, remaining) != _launcher_bytes(target)
                    or not os.access(launcher, os.X_OK)):
                raise ValueError("managed_launcher_binding_mismatch")
            announce("warm_validated", "Managed launcher matches the validated runtime")
        except BaseException:
            errors = []
            for source, dest in ((launcher, stage / "failed-launcher"), (backup, launcher)):
                if (source == launcher and not attempted) or (source == backup and not moved):
                    continue
                if os.path.lexists(source):
                    try:
                        source.replace(dest)
                    except OSError as exc:
                        errors.append({"source": str(source), "target": str(dest), "error": str(exc)})
            if errors:
                receipt.cleanup_pending = [str(path) for path in (stage, backup) if os.path.lexists(path)]
                receipt.recovery = {"required": True, "reason": "rollback_failed",
                    "errors": errors, "paths": receipt.cleanup_pending.copy()}
            raise
        receipt.launcher_repaired = True
        # Retirement follows the same commit boundary as a full installation.
        if moved:
            try:
                backup.replace(stage / "previous-launcher")
            except OSError as exc:
                receipt.cleanup_pending = [str(stage), str(backup)]
                receipt.cleanup = {"reason": "committed_backup_retirement_failed", "message": str(exc)}
                return True
        cleanup_stage()
        return True

    try:
        remaining()
        if build_hol and not yes:
            receipt.status, receipt.reason_codes = "blocked", ["explicit_install_authorization_required"]
            return receipt
        if not sys.platform.startswith("linux") or not Path("/proc/self/stat").is_file():
            raise ValueError("linux_resource_guards_required")
        owner = parent_lease._scheduler if parent_lease is not None else scheduler or get_global_resource_scheduler()
        if not owner.config.proof_safety_enabled:
            raise ValueError("pressure_aware_scheduler_required")
        if parent_lease is not None and (parent_lease.owner_pid != os.getpid() or parent_lease.released
                or parent_lease.cancelled or parent_lease.cpu_slots < cpu_slots
                or parent_lease.child_process_slots < profile.PROCESS_SLOTS
                or parent_lease.memory_mb < reservation_memory_mb):
            raise ValueError("inactive_or_underfunded_parent_lease")
        announce("admission", "Waiting for shared Isabelle installation resources")
        envelope = owner.acquire("orchestration", cpu_slots=cpu_slots,
            memory_mb=reservation_memory_mb, child_process_slots=profile.PROCESS_SLOTS,
            parent_lease=parent_lease, timeout=remaining(), cancel_event=cancellation,
            request_id="isabelle:installation")
        receipt.resource_lease_id = envelope.lease_id
        signal = envelope.combined_cancellation_signal(cancellation)
        announce("admitted", "Shared Isabelle installation resources acquired")
        root = legacy.expand_user_local_root(install_root)
        receipt.install_root = str(root)
        pin = legacy.select_strict_pin("isabelle", platform_key=legacy.detect_platform_key())
        receipt.pin = pin.to_dict()
        if not yes and (force or not root.exists()):
            receipt.status, receipt.reason_codes = "blocked", ["explicit_install_authorization_required"]
            return receipt
        with legacy.installation_lock(root, checkpoint=remaining):
            announce("locked", "Installer lock acquired")
            destination, launcher = root / pin.version, root / "bin/isabelle"
            backup, launcher_backup = root / (".previous-" + pin.version), root / "bin/.isabelle.previous"
            if os.path.lexists(backup) or os.path.lexists(launcher_backup):
                receipt.cleanup_pending = [str(path) for path in (backup, launcher_backup) if os.path.lexists(path)]
                receipt.recovery = {"required": True, "reason": "unresolved_previous_installation",
                                    "paths": receipt.cleanup_pending.copy()}
                raise ValueError("unresolved_previous_installation_requires_recovery")
            if not force and not build_hol:
                # Static selection failure is missing/unusable, never PATH
                # fallback. Only the admitted preparation executes native tools.
                try:
                    _, runtime = profile.resolve_runtime(checkpoint=remaining, install_root=root)
                except (FileNotFoundError, ValueError, OSError):
                    runtime = None
                if runtime is not None:
                    receipt.preparation = prepare(root, "warm_validation")
                    if receipt.preparation.get("usable"):
                        if not repair_warm_launcher(root, receipt.preparation["native_runtime"]):
                            return receipt
                        receipt.executable = receipt.preparation["executable"]
                        receipt.status, receipt.already_present = "already_present", True
                        receipt.reason_codes = ["bounded_installed_runtime_observed"]
                        return receipt
            if not yes:
                receipt.status, receipt.reason_codes = "blocked", ["explicit_install_authorization_required"]
                return receipt
            legacy.authorize_plugin_install(yes=True, strict=True, checksum_verified=True,
                                            platform_key=pin.platform)
            storage = legacy.check_storage_budget(root)
            if not storage["ok"]:
                raise ValueError("insufficient_installation_storage")
            if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
                raise ValueError("managed_destination_must_be_directory")
            if launcher.parent.is_symlink():
                raise ValueError("managed_bin_must_not_be_symlink")
            cache = root / "downloads" / Path(urlparse(pin.artifact_url).path).name
            if not allow_download and not os.path.lexists(cache):
                receipt.status, receipt.reason_codes = "blocked", ["verified_archive_required"]
                receipt.messages.append(f"No cached pinned archive at {cache}; explicitly allow installation/download to populate it.")
                return receipt
            stage = Path(tempfile.mkdtemp(prefix=".bounded-isabelle-", dir=root))
            receipt.cleanup_pending = [str(stage)]
            staging = stage / "extracted"
            staging.mkdir(mode=0o700)
            announce("archive", "Staging pinned archive in bounded worker" + (" (cache only)" if not allow_download else ""))
            request = {"schema": "isabelle-archive-staging-request@2", "version": pin.version,
                "platform_key": pin.platform, "artifact_url": pin.artifact_url, "sha256": pin.sha256,
                "cache_path": str(cache), "staging_dir": str(staging), "timeout_seconds": remaining(),
                "allow_download": allow_download}
            argv = (sys.executable, "-P", "-m", WORKER_MODULE, "{workspace}/request.json", "{workspace}/result.json")
            receipt.download_attempted = allow_download
            observed, receipt.worker = python_child(argv, inputs={"request.json": _canonical(request)},
                outputs=("result.json",), phase="archive")
            remaining()
            receipt.worker["receipt"] = _validate_worker_result(observed, request, argv)
            receipt.checksum_verified = True
            candidate = staging / pin.version
            if build_hol:
                from .isabelle_hol_build import build_staged_hol
                announce("hol_build", "Rebuilding persistent HOL in unpublished staging under shared limits")
                receipt.hol_build = build_staged_hol(install_root=candidate,
                    parent_lease=envelope, cancellation=signal, remaining=remaining,
                    memory_mb=build_memory_mb, on_progress=on_progress)
                remaining()
                if receipt.hol_build.get("build_succeeded") is not True:
                    raise ValueError("staged_hol_build_failed")
                if receipt.hol_build.get("persistent_heap_published") is not False:
                    raise ValueError("staged_hol_build_cannot_claim_publication")
            receipt.staged_preparation = prepare(candidate, "staged_validation")
            if not receipt.staged_preparation.get("usable"):
                raise ValueError("staged_runtime_not_usable:" + receipt.staged_preparation.get("reason_code", "unknown"))
            announce("publication", "Publishing validated runtime while retaining previous installation")
            had_tree = had_launcher = published = wrote_launcher = False
            try:
                if destination.exists():
                    destination.replace(backup)
                    had_tree = True
                candidate.replace(destination)
                published = True
                if os.path.lexists(launcher):
                    launcher.replace(launcher_backup)
                    had_launcher = True
                wrote_launcher = True
                legacy.write_launcher("isabelle", destination / "bin/isabelle", install_root=root,
                                      environment={"ISABELLE_HOME": str(destination)})
                if (profile.regular_bytes(launcher, profile.MAX_INPUT_BYTES, remaining) != _launcher_bytes(destination)
                        or not os.access(launcher, os.X_OK)):
                    raise ValueError("published_launcher_binding_mismatch")
                receipt.preparation = prepare(destination, "published_validation")
                if not receipt.preparation.get("usable"):
                    raise ValueError("published_runtime_not_usable:" + receipt.preparation.get("reason_code", "unknown"))
                before = receipt.staged_preparation["native_runtime"]
                after = receipt.preparation["native_runtime"]
                if any(before[key] != after[key] for key in ("version", "selected_file_sha256")):
                    raise ValueError("published_runtime_identity_changed")
                if build_hol:
                    from .isabelle_hol_build import verify_published_hol
                    announce("published_heap_verification", "Checking that the rebuilt HOL heap survived publication")
                    checked = verify_published_hol(install_root=destination,
                        expected_build=receipt.hol_build, parent_lease=envelope,
                        cancellation=signal, remaining=remaining)
                    receipt.hol_build["publication_verification"] = checked
                    remaining()
                    if checked.get("verified") is not True:
                        raise ValueError("published_hol_heap_identity_changed")
                announce("validated", "Published runtime passed bounded validation")
            except BaseException:
                # No deadline/cancellation checkpoint may interrupt rollback.
                # Move large trees aside instead of unbounded controller rmtree.
                rollback_errors = []
                def restore(source, target):
                    try:
                        source.replace(target)
                    except OSError as exc:
                        rollback_errors.append({"source": str(source), "target": str(target), "error": str(exc)})
                if wrote_launcher and os.path.lexists(launcher):
                    restore(launcher, stage / "failed-launcher")
                if had_launcher:
                    restore(launcher_backup, launcher)
                if published:
                    restore(destination, stage / "failed-runtime")
                if had_tree:
                    restore(backup, destination)
                if rollback_errors:
                    receipt.cleanup_pending = [str(path) for path in (stage, backup, launcher_backup)
                                               if os.path.lexists(path)]
                    receipt.recovery = {"required": True, "reason": "rollback_failed",
                        "errors": rollback_errors, "paths": receipt.cleanup_pending.copy()}
                raise
            # Commit after final checks. Cleanup cannot revoke an already
            # completed publication; retained paths are explicit in the receipt.
            receipt.status, receipt.installed = "installed", True
            if build_hol:
                receipt.hol_build["persistent_heap_published"] = True
            receipt.reason_codes = ["bounded_archive_installation_validated"]
            receipt.executable = receipt.preparation["executable"]
            try:
                if had_tree:
                    backup.replace(stage / "previous-runtime")
                if had_launcher:
                    launcher_backup.replace(stage / "previous-launcher")
            except OSError as exc:
                receipt.cleanup_pending = [str(path) for path in (stage, backup, launcher_backup)
                                           if os.path.lexists(path)]
                receipt.cleanup = {"reason": "committed_backup_retirement_failed", "message": str(exc)}
                return receipt
            cleanup_stage()
    except Exception as exc:
        receipt.status = "failed"
        receipt.reason_codes = ["cancelled" if isinstance(exc, LeaseCancelledError) else
            "deadline_exceeded" if isinstance(exc, LeaseTimeoutError) else "installation_failed"]
        receipt.messages.append(f"{type(exc).__name__}: {exc}")
        if receipt.recovery.get("required"):
            receipt.reason_codes.append(receipt.recovery["reason"])
        elif envelope is not None:
            cleanup_stage()
        receipt.elapsed_seconds = time.monotonic() - started
        if strict:
            raise IsabelleInstallationError(receipt) from exc
    finally:
        if envelope is not None:
            envelope.release()
        receipt.elapsed_seconds = time.monotonic() - started
    return receipt


def plugin_manifest():
    result = legacy.plugin_manifest()
    result.update(module_path=__name__, ensure_entrypoints={"isabelle": "ensure_isabelle_installation"})
    result["policy"].update(shared_resource_admission=True, bounded_archive_worker=True,
                            bounded_native_validation=True)
    return result
