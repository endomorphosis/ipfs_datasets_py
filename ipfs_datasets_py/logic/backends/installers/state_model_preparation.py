"""Admitted, bounded observation of an already installed TLC runtime.

This additive preparation surface does not download, install, publish launchers,
or run a model check. Legacy installer probes remain separate. Executables and
their transitive libraries are owner-controlled installed tools; their observed
digests are identity evidence, not an authenticity or proof certificate.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import sys
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass

from ...ir_core.claims import FrozenMap, stable_digest
from ..process import BoundedToolRunner, ToolRunLimits, ToolRunRequest, ToolRuntime
from . import state_model as legacy
from ....optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, LeaseCancelledError, LeaseTimeoutError,
    ResourceLease, ResourceUnavailableError, get_global_resource_scheduler,
)

PREPARATION_SCHEMA = "state-model-runtime-preparation/v1"
MAX_JAR_BYTES = 8 * 1024**2
MAX_JAVA_BYTES = 16 * 1024**2
MAX_MANIFEST_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
PREPARATION_OVERHEAD_MB = 128


@dataclass(frozen=True, slots=True)
class StateModelRuntimePreparation:
    """Historical runtime observations; never installation/proof authority."""

    status: str
    reason_code: str
    elapsed_seconds: float
    resource_lease_id: str
    bindings: FrozenMap
    probes: tuple[FrozenMap, ...]
    limits: FrozenMap

    @property
    def usable(self) -> bool:
        return self.status == "usable"

    def to_dict(self) -> dict:
        return {
            "schema_version": PREPARATION_SCHEMA,
            "tool_id": "tlc", "status": self.status, "reason_code": self.reason_code,
            "usable": self.usable, "elapsed_seconds": self.elapsed_seconds,
            "resource_lease_id": self.resource_lease_id,
            "bindings": self.bindings.to_dict(),
            "probes": [probe.to_dict() for probe in self.probes],
            "limits": self.limits.to_dict(),
            "installation_performed": False, "model_check_executed": False,
            "grants_proof_authority": False, "grants_repository_authority": False,
            "requires_fresh_model_check": True,
        }

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())


class _PreparationFailure(Exception):
    def __init__(self, reason: str, status: str = "error"):
        self.reason, self.status = reason, status


def _regular_bytes(path: Path, limit: int, checkpoint: Callable[[], float]) -> bytes:
    """Never block opening a FIFO; cap actual bytes even if a file grows."""
    checkpoint()
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise _PreparationFailure("invalid_or_oversized_artifact")
        result = bytearray()
        while True:
            checkpoint()
            block = stream.read(min(64 * 1024, limit - len(result) + 1))
            checkpoint()
            if not block:
                return bytes(result)
            result.extend(block)
            if len(result) > limit:
                raise _PreparationFailure("invalid_or_oversized_artifact")


def _jar_identity(payload: bytes) -> dict:
    # Validate only after the immutable digest matches; arbitrary ZIP payloads
    # never reach ZIP directory/manifest decompression.
    if hashlib.sha256(payload).hexdigest() != legacy.TLC_SHA256:
        raise _PreparationFailure("tlc_artifact_checksum_mismatch")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        info = archive.getinfo("META-INF/MANIFEST.MF")
        if info.file_size > MAX_MANIFEST_BYTES:
            raise _PreparationFailure("tlc_manifest_oversized")
        with archive.open(info) as stream:
            manifest = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise _PreparationFailure("tlc_manifest_oversized")
    attributes = legacy._jar_manifest_attributes(manifest)
    if attributes is None:
        raise _PreparationFailure("tlc_manifest_invalid")
    tags = [part.strip() for part in attributes.get("x-git-tag", "").split(";")
            if legacy._TLC_RELEASE_TAG_RE.fullmatch(part.strip())]
    short = attributes.get("x-git-shortrevision", "")
    revision = attributes.get("x-git-revision", "")
    if (tags != [legacy.TLC_RELEASE_TAG] or short != legacy.TLC_REVISION
            or not legacy._TLC_FULL_REVISION_RE.fullmatch(revision) or not revision.startswith(short)):
        raise _PreparationFailure("tlc_manifest_release_mismatch")
    return {"sha256": legacy.TLC_SHA256, "version": legacy.TLC_VERSION,
            "release_tag": tags[0], "revision": revision,
            "manifest_sha256": hashlib.sha256(manifest).hexdigest()}


def prepare_tlc_runtime(
    *, java_executable: str | Path | None = None,
    jar_path: str | Path | None = None, install_root: str | Path | None = None,
    parent_lease: ResourceLease | None = None,
    scheduler: GlobalResourceScheduler | None = None,
    timeout_seconds: float = 15.0, memory_mb: int = 256,
    cancellation=None, on_progress: Callable[[str, str], None] | None = None,
) -> StateModelRuntimePreparation:
    """Observe pinned installed TLC using default-on shared admission.

    One deadline includes root/child admission and both native probes. Each
    probe obtains a fresh child lease, so external pressure can defer the second
    JVM even after Java identity has been observed. ``memory_mb`` is the sampled
    child RSS guard; the envelope adds 128 MiB for bounded preparation buffers.
    RSS sampling may overshoot; the independent finite virtual-address limit
    accommodates JVM reservations. CPU limits apply per process. No cgroup or
    transitive Java library attestation is claimed.

    Defaults read the managed TLC path and Java selection manifest only after
    admission. Explicit paths select already installed owner-controlled tools;
    a bad explicit path never falls back. Cancellation supplies ``is_set()``.
    Progress callbacks run before checkpoints and may set that signal.
    """
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60):
        raise ValueError("timeout_seconds must be finite and in (0, 60]")
    if type(memory_mb) is not int or not 128 <= memory_mb <= 1024:
        raise ValueError("memory_mb must be an integer in [128, 1024]")
    if cancellation is not None and not callable(getattr(cancellation, "is_set", None)):
        raise TypeError("cancellation must supply is_set()")
    if parent_lease is not None and type(parent_lease) is not ResourceLease:
        raise TypeError("parent_lease must be an actual ResourceLease")
    if scheduler is not None and not isinstance(scheduler, GlobalResourceScheduler):
        raise TypeError("scheduler must be a GlobalResourceScheduler")
    if parent_lease is not None and scheduler is not None:
        raise ValueError("supply only parent_lease or scheduler; one owner is required")

    started, envelope = time.monotonic(), None
    deadline = started + timeout_seconds
    signal = cancellation
    bindings, probes = {}, []
    policy = {"timeout_seconds": timeout_seconds, "cpu_slots": 1, "child_process_slots": 1,
              "reservation_memory_mb": memory_mb + PREPARATION_OVERHEAD_MB,
              "resident_memory_bytes": memory_mb * 1024**2,
              "address_space_bytes": max(4 * 1024**3, memory_mb * 4 * 1024**2),
              "max_output_bytes": MAX_OUTPUT_BYTES, "max_input_bytes": MAX_JAR_BYTES,
              "max_workspace_bytes": 16 * 1024**2, "rss_sampling_ms": 100}

    def remaining():
        if signal is not None and signal.is_set():
            raise LeaseCancelledError("TLC preparation cancelled")
        duration = deadline - time.monotonic()
        if duration <= 0:
            raise LeaseTimeoutError("TLC preparation deadline expired")
        return duration

    def announce(phase):
        if on_progress is not None:
            on_progress(phase, "Observing installed TLC runtime; no installation or model check")
        remaining()

    status, reason = "error", "preparation_failed"
    lease_id = ""
    try:
        remaining()
        if not sys.platform.startswith("linux") or not Path("/proc/self/stat").is_file():
            raise _PreparationFailure("linux_resource_guards_required", "unsupported")
        owner = parent_lease._scheduler if parent_lease is not None else scheduler or get_global_resource_scheduler()
        if not owner.config.proof_safety_enabled:
            raise _PreparationFailure("pressure_aware_scheduler_required", "admission_denied")
        if parent_lease is not None:
            if parent_lease.owner_pid != os.getpid() or parent_lease.released or parent_lease.cancelled:
                raise _PreparationFailure("inactive_parent_lease", "admission_denied")
            if (parent_lease.cpu_slots < 1 or parent_lease.child_process_slots < 1
                    or parent_lease.memory_mb < policy["reservation_memory_mb"]):
                raise _PreparationFailure("underfunded_parent_lease", "admission_denied")
        announce("admission")
        envelope = owner.acquire(
            "validation", cpu_slots=1, memory_mb=policy["reservation_memory_mb"],
            child_process_slots=1, parent_lease=parent_lease,
            timeout=remaining(), cancel_event=cancellation, request_id="tlc:runtime-preparation",
        )
        lease_id = envelope.lease_id
        signal = envelope.combined_cancellation_signal(cancellation)
        announce("admitted")
        root = legacy.expand_user_local_root(install_root)
        selected_jar = Path(jar_path) if jar_path is not None else root / "tlc" / legacy.TLC_VERSION / legacy.TLC_JAR_NAME
        jar = selected_jar.expanduser().absolute()
        payload = _regular_bytes(jar, MAX_JAR_BYTES, remaining)
        bindings["jar"] = {"path": str(jar), "size_bytes": len(payload), **_jar_identity(payload)}
        if java_executable is None:
            raw_manifest = _regular_bytes(root / "manifests/tlc.json", MAX_MANIFEST_BYTES, remaining)
            manifest = json.loads(raw_manifest)
            if (not isinstance(manifest, dict) or manifest.get("schema_version") != legacy._MANIFEST_SCHEMA
                    or manifest.get("tool_id") != "tlc" or manifest.get("version") != legacy.TLC_VERSION
                    or manifest.get("artifact_sha256") != legacy.TLC_SHA256
                    or manifest.get("payload_sha256") != legacy.TLC_SHA256
                    or not isinstance(manifest.get("java_executable"), str)
                    or not Path(manifest["java_executable"]).is_absolute()):
                raise _PreparationFailure("managed_java_selection_invalid")
            java_executable = manifest["java_executable"]
            bindings["selection_manifest_sha256"] = hashlib.sha256(raw_manifest).hexdigest()
        java = Path(java_executable).expanduser().resolve(strict=True)
        java_bytes = _regular_bytes(java, MAX_JAVA_BYTES, remaining)
        if not os.access(java, os.X_OK):
            raise _PreparationFailure("java_not_executable", "unavailable")
        java_digest = hashlib.sha256(java_bytes).hexdigest()
        bindings["java"] = {"path": str(java), "sha256": java_digest, "size_bytes": len(java_bytes)}
        del java_bytes
        flags = ("-Xms16m", f"-Xmx{memory_mb // 2}m", "-XX:ActiveProcessorCount=1",
                 "-XX:+UseSerialGC", "-XX:ReservedCodeCacheSize=64m", "-XX:CompressedClassSpaceSize=64m")
        policy["jvm_options"] = list(flags)
        runner = BoundedToolRunner(base_environment={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"})

        def native(phase, args, inputs=None):
            announce(phase)
            with envelope.acquire_child(
                lane="validation", cpu_slots=1, memory_mb=memory_mb, child_process_slots=1,
                timeout=remaining(), cancel_event=signal, request_id="tlc:prepare:" + phase,
            ) as child:
                duration = remaining()
                limits = ToolRunLimits(
                    timeout_seconds=duration, cpu_seconds=duration,
                    memory_bytes=policy["address_space_bytes"], resident_memory_bytes=policy["resident_memory_bytes"],
                    max_output_bytes=MAX_OUTPUT_BYTES, max_input_bytes=MAX_JAR_BYTES,
                    max_workspace_bytes=policy["max_workspace_bytes"], max_output_files=4,
                )
                observed = runner.run(ToolRunRequest(
                    argv=(str(java), *flags, *args), runtime=ToolRuntime.JVM,
                    limits=limits, input_files=inputs or {},
                ), cancellation=child.combined_cancellation_signal(signal))
                probes.append({"phase": phase, "child_lease_id": child.lease_id,
                               "timeout_seconds": duration, "cpu_seconds": duration,
                               "observation": observed.to_dict()})
                remaining()
                if observed.cancelled:
                    raise LeaseCancelledError("TLC preparation process cancelled")
                if observed.timed_out:
                    raise LeaseTimeoutError("TLC preparation process timed out")
                if (observed.unavailable or observed.resource_exhausted or observed.output_truncated
                        or observed.workspace_limit_exceeded or not observed.workspace_cleaned or observed.error):
                    raise _PreparationFailure("bounded_probe_incomplete")
            return observed

        java_result = native("java_probe", ("-version",))
        banner = "\n".join(part for part in (java_result.stdout, java_result.stderr) if part).strip()
        major = legacy.java_major_version(banner)
        if java_result.returncode != 0 or major is None or major < legacy.TLC_MIN_JAVA_MAJOR:
            raise _PreparationFailure("java_version_unsupported", "unavailable")
        bindings["java"].update(major=major, banner=banner)
        tool_result = native("tlc_probe", ("-cp", "tla2tools.jar", "tlc2.TLC", "-help"), {"tla2tools.jar": payload})
        output = "\n".join(part for part in (tool_result.stdout, tool_result.stderr) if part).strip()
        semantic = legacy._tlc_help_probe(legacy.RuntimeCommandProbe(
            command=tool_result.command, returncode=tool_result.returncode, output=output,
            usable=False,
        ))
        if not semantic.usable:
            raise _PreparationFailure(semantic.reason_code or "tlc_help_semantics_missing", "unavailable")
        bindings["tlc_help_sha256"] = hashlib.sha256(semantic.output.encode()).hexdigest()
        # Re-observe selected executable bytes before delivering historical
        # usability. The JVM installation and shared libraries remain trusted.
        if hashlib.sha256(_regular_bytes(java, MAX_JAVA_BYTES, remaining)).hexdigest() != java_digest:
            raise _PreparationFailure("java_identity_changed")
        announce("complete")
        status, reason = "usable", "bounded_installed_runtime_observed"
    except LeaseCancelledError:
        status, reason = "cancelled", "preparation_cancelled"
    except LeaseTimeoutError:
        status, reason = "timed_out", "preparation_deadline_exceeded"
    except ResourceUnavailableError:
        status, reason = "admission_denied", "resource_admission_unavailable"
    except _PreparationFailure as exc:
        status, reason = exc.status, exc.reason
    except FileNotFoundError:
        status, reason = "unavailable", "installed_artifact_missing"
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        status, reason = "error", "preparation_artifact_or_io_invalid"
    finally:
        if envelope is not None:
            envelope.release()
    return StateModelRuntimePreparation(
        status=status, reason_code=reason, elapsed_seconds=max(0.0, time.monotonic() - started),
        resource_lease_id=lease_id, bindings=FrozenMap(bindings),
        probes=tuple(FrozenMap(probe) for probe in probes), limits=FrozenMap(policy),
    )


__all__ = ["prepare_tlc_runtime", "StateModelRuntimePreparation", "PREPARATION_SCHEMA"]
