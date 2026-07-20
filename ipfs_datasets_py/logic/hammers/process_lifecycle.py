"""Supervisor-owned lifecycle for theorem-prover subprocesses.

The proof runtime launches programs which routinely create children of their
own (``lake``, Lean plugins, ATP workers, and solver helpers).  A timeout on a
single :func:`subprocess.run` call is therefore not a sufficient ownership
boundary: the program receiving the timeout may exit while one of its
children continues running.  This module provides that ownership boundary.

Every managed command is placed in a new process group, recorded in a small
durable ownership manifest, heartbeated while it is alive, terminated with
TERM before KILL, and removed from the registry only after its whole group is
gone.  Recovery never searches for processes by executable name.  It acts
only on manifests whose PID birth marker and per-process environment token
still match, which prevents a stale PID from targeting an unrelated Lean or
Elan user.
"""

from __future__ import annotations

import atexit
import enum
import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Protocol, Sequence

try:  # pragma: no cover - production proof workers are POSIX.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


PROCESS_MANIFEST_SCHEMA = "legal-ir-managed-process-v1"
TEMP_DIRECTORY_MARKER = ".legal-ir-process-owner.json"
DEFAULT_STATE_ENV = "IPFS_DATASETS_PROCESS_SUPERVISOR_DIR"
_MANAGED_ID_ENV = "IPFS_DATASETS_MANAGED_PROCESS_ID"
_SUPERVISOR_ID_ENV = "IPFS_DATASETS_PROCESS_SUPERVISOR_ID"


class CancellationSignal(Protocol):
    def is_set(self) -> bool: ...


class ReleasableLease(Protocol):
    @property
    def cancelled(self) -> bool: ...

    def heartbeat(self) -> bool: ...

    def release(self) -> bool: ...


class ProcessKind(str, enum.Enum):
    """Stable labels used by lifecycle telemetry and recovery."""

    LEAN = "lean"
    LAKE = "lake"
    ATP = "atp"
    SMT = "smt"
    TRANSLATOR = "translator"
    TOOLCHAIN = "toolchain"
    OTHER = "other"


@dataclass(frozen=True)
class ProcessLimits:
    """Wall-clock and OS resource bounds for one managed process group."""

    wall_time_seconds: float = 30.0
    cpu_seconds: Optional[float] = None
    memory_mb: Optional[int] = None
    graceful_shutdown_seconds: float = 1.0
    forced_cleanup_seconds: float = 2.0

    def validate(self) -> None:
        for name, value in (
            ("wall_time_seconds", self.wall_time_seconds),
            ("graceful_shutdown_seconds", self.graceful_shutdown_seconds),
            ("forced_cleanup_seconds", self.forced_cleanup_seconds),
        ):
            if not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError(f"{name} must be non-negative and finite")
        if self.wall_time_seconds <= 0:
            raise ValueError("wall_time_seconds must be positive")
        if self.cpu_seconds is not None and (
            not math.isfinite(float(self.cpu_seconds)) or self.cpu_seconds <= 0
        ):
            raise ValueError("cpu_seconds must be positive and finite")
        if self.memory_mb is not None and (
            isinstance(self.memory_mb, bool) or int(self.memory_mb) <= 0
        ):
            raise ValueError("memory_mb must be a positive integer")


@dataclass
class ProcessExecutionResult:
    """Captured outcome of one complete managed process-group lifecycle."""

    command: List[str]
    kind: str
    managed_process_id: str = ""
    pid: Optional[int] = None
    process_group_id: Optional[int] = None
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    cancelled: bool = False
    resource_exhausted: bool = False
    graceful_termination: bool = False
    forced_cleanup: bool = False
    wall_time_seconds: float = 0.0
    error: Optional[str] = None
    termination_reason: str = ""
    lease_released: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RecoveryReport:
    """Auditable result of a conservative recovery sweep."""

    recovered_process_ids: List[str] = field(default_factory=list)
    removed_paths: List[str] = field(default_factory=list)
    skipped_active: List[str] = field(default_factory=list)
    skipped_unowned: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def recovered_count(self) -> int:
        return len(self.recovered_process_ids) + len(self.removed_paths)


def _default_state_directory() -> Path:
    configured = os.environ.get(DEFAULT_STATE_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    uid = getattr(os, "getuid", lambda: 0)()
    return Path(tempfile.gettempdir()) / f"ipfs-datasets-process-supervisor-{uid}"


def _process_birth_marker(pid: int) -> str:
    """Return a value which changes if ``pid`` is recycled."""

    if pid <= 0:
        return ""
    try:
        # Linux /proc stat field 22 is the start time in clock ticks.  The
        # command field may contain spaces and parentheses, so split only
        # after its final closing parenthesis.
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        return f"linux:{fields[19]}"
    except (OSError, IndexError):
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return ""
    # Non-Linux fallback cannot distinguish recycling.  Recovery consequently
    # refuses to kill from this weak marker; live in-memory ownership still
    # works normally.
    return f"weak:{pid}"


def _pid_matches(pid: int, birth_marker: str) -> bool:
    return bool(birth_marker and not birth_marker.startswith("weak:") and _process_birth_marker(pid) == birth_marker)


def _process_has_token(pid: int, managed_id: str) -> bool:
    try:
        environ = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return False
    expected = f"{_MANAGED_ID_ENV}={managed_id}".encode("utf-8")
    return expected in environ


def _group_exists(pgid: int) -> bool:
    if os.name != "posix" or pgid <= 0:
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=True, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _resource_preexec(limits: ProcessLimits):
    if os.name != "posix" or (limits.cpu_seconds is None and limits.memory_mb is None):
        return None

    def apply_limits() -> None:
        import resource

        if limits.cpu_seconds is not None:
            value = max(1, int(math.ceil(limits.cpu_seconds)))
            resource.setrlimit(resource.RLIMIT_CPU, (value, value))
        if limits.memory_mb is not None:
            value = int(limits.memory_mb) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (value, value))

    return apply_limits


class ManagedProcess:
    """Handle for a process whose monitor and cleanup belong to a supervisor."""

    def __init__(
        self,
        supervisor: "ProcessSupervisor",
        process: "subprocess.Popen[str]",
        *,
        managed_id: str,
        pgid: int,
        command: Sequence[str],
        kind: ProcessKind,
        limits: ProcessLimits,
        started: float,
        manifest_path: Path,
        cancel_event: Optional[CancellationSignal],
        lease: Optional[ReleasableLease],
        input_text: Optional[str],
    ) -> None:
        self._supervisor = supervisor
        self._process = process
        self.managed_process_id = managed_id
        self.process_group_id = pgid
        self.command = list(command)
        self.kind = kind
        self.limits = limits
        self.started = started
        self.manifest_path = manifest_path
        self.external_cancel_event = cancel_event
        self.lease = lease
        self.input_text = input_text
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._result: Optional[ProcessExecutionResult] = None
        self._monitor = threading.Thread(
            target=supervisor._monitor_process,
            args=(self,),
            daemon=True,
            name=f"managed-process-{managed_id[:8]}",
        )

    def _start_monitor(self) -> None:
        self._monitor.start()

    @property
    def pid(self) -> int:
        return self._process.pid

    def poll(self) -> Optional[int]:
        return self._process.poll()

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self, timeout: Optional[float] = None) -> ProcessExecutionResult:
        if not self._done.wait(timeout):
            raise TimeoutError(f"managed process {self.managed_process_id} is still running")
        assert self._result is not None
        return self._result

    def __enter__(self) -> "ManagedProcess":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if not self._done.is_set():
            self.cancel()
        self.wait(self.limits.graceful_shutdown_seconds + self.limits.forced_cleanup_seconds + 2.0)


class ProcessSupervisor:
    """Own process groups, deadlines, leases, heartbeats, and recovery."""

    def __init__(
        self,
        *,
        state_directory: Optional[str | Path] = None,
        heartbeat_interval_seconds: float = 0.25,
        stale_after_seconds: float = 30.0,
        recover: bool = True,
    ) -> None:
        if heartbeat_interval_seconds <= 0 or stale_after_seconds <= 0:
            raise ValueError("heartbeat and stale intervals must be positive")
        self.state_directory = Path(state_directory or _default_state_directory()).expanduser().resolve()
        self.manifest_directory = self.state_directory / "processes"
        self.temp_directory = self.state_directory / "temporary"
        self.manifest_directory.mkdir(parents=True, exist_ok=True)
        self.temp_directory.mkdir(parents=True, exist_ok=True)
        self.supervisor_id = uuid.uuid4().hex
        self.owner_pid = os.getpid()
        self.owner_birth_marker = _process_birth_marker(self.owner_pid)
        self.heartbeat_interval_seconds = float(heartbeat_interval_seconds)
        self.stale_after_seconds = float(stale_after_seconds)
        self._active: Dict[str, ManagedProcess] = {}
        self._lock = threading.RLock()
        self._closed = False
        if recover:
            self.recover_orphaned_processes()
            recover_stale_temporary_directories(
                self.temp_directory, stale_after_seconds=self.stale_after_seconds
            )
        atexit.register(self.close)

    @property
    def active_process_count(self) -> int:
        with self._lock:
            return len(self._active)

    @property
    def managed_pids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(sorted(item.pid for item in self._active.values()))

    def launch(
        self,
        command: Sequence[str],
        *,
        kind: ProcessKind | str = ProcessKind.OTHER,
        limits: Optional[ProcessLimits] = None,
        cancel_event: Optional[CancellationSignal] = None,
        lease: Optional[ReleasableLease] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[Mapping[str, str]] = None,
        input_text: Optional[str] = None,
    ) -> ManagedProcess:
        if self._closed:
            raise RuntimeError("process supervisor is closed")
        if isinstance(command, (str, bytes)) or not command or not all(isinstance(value, str) and value for value in command):
            raise ValueError("command must be a non-empty sequence of non-empty argv strings")
        resolved_kind = kind if isinstance(kind, ProcessKind) else ProcessKind(str(kind))
        resolved_limits = limits or ProcessLimits()
        resolved_limits.validate()
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("process launch was cancelled before start")

        managed_id = uuid.uuid4().hex
        child_env = dict(os.environ if env is None else env)
        child_env[_MANAGED_ID_ENV] = managed_id
        child_env[_SUPERVISOR_ID_ENV] = self.supervisor_id
        started = time.monotonic()
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            env=child_env,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=(os.name == "posix"),
            preexec_fn=_resource_preexec(resolved_limits),
            shell=False,
        )
        pgid = os.getpgid(process.pid) if os.name == "posix" else process.pid
        manifest_path = self.manifest_directory / f"{managed_id}.json"
        manifest = {
            "schema": PROCESS_MANIFEST_SCHEMA,
            "managed_process_id": managed_id,
            "supervisor_id": self.supervisor_id,
            "supervisor_pid": self.owner_pid,
            "supervisor_birth_marker": self.owner_birth_marker,
            "pid": process.pid,
            "pid_birth_marker": _process_birth_marker(process.pid),
            "process_group_id": pgid,
            "kind": resolved_kind.value,
            "command_digest": hashlib.sha256(b"\0".join(part.encode() for part in command)).hexdigest(),
            "created_at": time.time(),
            "heartbeat_at": time.time(),
            "lease_id": str(getattr(lease, "lease_id", "")),
        }
        try:
            _atomic_json(manifest_path, manifest)
            handle = ManagedProcess(
                self,
                process,
                managed_id=managed_id,
                pgid=pgid,
                command=command,
                kind=resolved_kind,
                limits=resolved_limits,
                started=started,
                manifest_path=manifest_path,
                cancel_event=cancel_event,
                lease=lease,
                input_text=input_text,
            )
            with self._lock:
                self._active[managed_id] = handle
            handle._start_monitor()
            return handle
        except BaseException:
            self._signal_process(process, pgid, signal.SIGKILL)
            try:
                process.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
            if lease is not None:
                lease.release()
            raise

    def run(self, command: Sequence[str], **kwargs: Any) -> ProcessExecutionResult:
        """Launch and wait, guaranteeing cleanup even on caller interruption."""

        try:
            handle = self.launch(command, **kwargs)
        except OSError as exc:
            kind = kwargs.get("kind", ProcessKind.OTHER)
            kind_value = kind.value if isinstance(kind, ProcessKind) else str(kind)
            lease = kwargs.get("lease")
            released = False
            if lease is not None:
                try:
                    released = bool(lease.release()) or bool(getattr(lease, "released", False))
                except Exception:
                    released = False
            return ProcessExecutionResult(
                command=list(command),
                kind=kind_value,
                error=f"{exc.__class__.__name__}: {exc}",
                termination_reason="spawn_error",
                lease_released=released,
            )
        except RuntimeError as exc:
            if "cancelled before start" not in str(exc):
                raise
            kind = kwargs.get("kind", ProcessKind.OTHER)
            kind_value = kind.value if isinstance(kind, ProcessKind) else str(kind)
            lease = kwargs.get("lease")
            released = False
            if lease is not None:
                released = bool(lease.release()) or bool(getattr(lease, "released", False))
            return ProcessExecutionResult(command=list(command), kind=kind_value, cancelled=True, termination_reason="cancelled_before_start", lease_released=released)
        try:
            return handle.wait()
        except BaseException:
            handle.cancel()
            try:
                handle.wait(handle.limits.graceful_shutdown_seconds + handle.limits.forced_cleanup_seconds + 2.0)
            except TimeoutError:
                self._signal_process(handle._process, handle.process_group_id, signal.SIGKILL)
            raise

    def _monitor_process(self, handle: ManagedProcess) -> None:
        process = handle._process
        deadline = handle.started + handle.limits.wall_time_seconds
        stdout = ""
        stderr = ""
        timed_out = cancelled = resource_exhausted = False
        graceful = forced = False
        reason = "completed"
        input_value = handle.input_text
        manifest: Dict[str, Any] = {}
        try:
            try:
                manifest = json.loads(handle.manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = {}
            while True:
                external_cancelled = bool(handle.external_cancel_event is not None and handle.external_cancel_event.is_set())
                lease_cancelled = bool(handle.lease is not None and getattr(handle.lease, "cancelled", False))
                now = time.monotonic()
                if handle._cancel.is_set() or external_cancelled or lease_cancelled:
                    cancelled = True
                    reason = "resource_deadline" if lease_cancelled else "cancelled"
                    graceful, forced, stdout, stderr = self._terminate(handle)
                    break
                if now >= deadline:
                    timed_out = True
                    reason = "wall_clock_deadline"
                    graceful, forced, stdout, stderr = self._terminate(handle)
                    break
                try:
                    stdout, stderr = process.communicate(
                        input=input_value,
                        timeout=min(self.heartbeat_interval_seconds, max(0.001, deadline - now)),
                    )
                    input_value = None
                    break
                except subprocess.TimeoutExpired:
                    input_value = None
                    manifest["heartbeat_at"] = time.time()
                    try:
                        _atomic_json(handle.manifest_path, manifest)
                    except OSError:
                        pass
                    if handle.lease is not None:
                        try:
                            if not handle.lease.heartbeat():
                                cancelled = True
                                reason = "resource_deadline"
                                graceful, forced, stdout, stderr = self._terminate(handle)
                                break
                        except Exception:
                            # The lease's cancellation state is checked on the
                            # next poll; transient state-file I/O is recoverable.
                            pass

            # A command may daemonise a child and then exit.  The group is
            # still ours, so complete the lifecycle before reporting success.
            if _group_exists(handle.process_group_id):
                cleaned_gracefully, cleaned_forced, _, _ = self._terminate(handle, root_already_exited=True)
                graceful = graceful or cleaned_gracefully
                forced = forced or cleaned_forced
                if reason == "completed":
                    reason = "completed_with_descendant_cleanup"
            returncode = process.poll()
            if returncode is not None and returncode < 0 and not (timed_out or cancelled):
                if -returncode in {getattr(signal, "SIGXCPU", 24), signal.SIGKILL}:
                    resource_exhausted = True
                    reason = "resource_deadline"
        except BaseException as exc:
            reason = "monitor_error"
            try:
                graceful, forced, extra_out, extra_err = self._terminate(handle)
                stdout = stdout or extra_out
                stderr = stderr or extra_err
            except BaseException:
                pass
            error = f"{exc.__class__.__name__}: {exc}"
        else:
            error = None
        finally:
            released = False
            if handle.lease is not None:
                try:
                    released = bool(handle.lease.release()) or bool(getattr(handle.lease, "released", False))
                except Exception:
                    released = False
            result = ProcessExecutionResult(
                command=handle.command,
                kind=handle.kind.value,
                managed_process_id=handle.managed_process_id,
                pid=handle.pid,
                process_group_id=handle.process_group_id,
                returncode=process.poll(),
                stdout=stdout or "",
                stderr=stderr or "",
                timed_out=timed_out,
                cancelled=cancelled,
                resource_exhausted=resource_exhausted,
                graceful_termination=graceful,
                forced_cleanup=forced,
                wall_time_seconds=max(0.0, time.monotonic() - handle.started),
                error=error,
                termination_reason=reason,
                lease_released=released,
            )
            handle._result = result
            try:
                handle.manifest_path.unlink()
            except FileNotFoundError:
                pass
            with self._lock:
                self._active.pop(handle.managed_process_id, None)
            handle._done.set()

    @staticmethod
    def _signal_process(process: "subprocess.Popen[str]", pgid: int, sig: signal.Signals) -> None:
        try:
            if os.name == "posix":
                os.killpg(pgid, sig)
            else:  # pragma: no cover
                process.terminate() if sig == signal.SIGTERM else process.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def _terminate(self, handle: ManagedProcess, *, root_already_exited: bool = False) -> tuple[bool, bool, str, str]:
        process = handle._process
        self._signal_process(process, handle.process_group_id, signal.SIGTERM)
        end = time.monotonic() + handle.limits.graceful_shutdown_seconds
        stdout = stderr = ""
        while time.monotonic() < end:
            try:
                if not root_already_exited:
                    stdout, stderr = process.communicate(timeout=min(0.05, max(0.001, end - time.monotonic())))
                    root_already_exited = True
                if not _group_exists(handle.process_group_id):
                    return True, False, stdout or "", stderr or ""
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.01)
        self._signal_process(process, handle.process_group_id, signal.SIGKILL)
        forced_end = time.monotonic() + handle.limits.forced_cleanup_seconds
        try:
            if not root_already_exited:
                stdout, stderr = process.communicate(timeout=max(0.001, handle.limits.forced_cleanup_seconds))
                root_already_exited = True
        except subprocess.TimeoutExpired:
            pass
        while _group_exists(handle.process_group_id) and time.monotonic() < forced_end:
            time.sleep(0.01)
        return False, True, stdout or "", stderr or ""

    def recover_orphaned_processes(self) -> RecoveryReport:
        """Recover only cryptographically-labelled process groups we own."""

        report = RecoveryReport()
        for path in self.manifest_directory.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("schema") != PROCESS_MANIFEST_SCHEMA:
                    report.skipped_unowned.append(str(path))
                    continue
                managed_id = str(record["managed_process_id"])
                pid = int(record["pid"])
                pgid = int(record["process_group_id"])
                supervisor_pid = int(record.get("supervisor_pid", 0))
                supervisor_birth = str(record.get("supervisor_birth_marker", ""))
                heartbeat = float(record.get("heartbeat_at", 0.0))
                if _pid_matches(supervisor_pid, supervisor_birth) and time.time() - heartbeat <= self.stale_after_seconds:
                    report.skipped_active.append(managed_id)
                    continue
                if not _pid_matches(pid, str(record.get("pid_birth_marker", ""))) or not _process_has_token(pid, managed_id):
                    # A dead leader needs no signal.  Remove the stale record;
                    # a live PID without both proofs of ownership is untouchable.
                    if not _process_birth_marker(pid):
                        path.unlink(missing_ok=True)
                    else:
                        report.skipped_unowned.append(managed_id)
                    continue
                if os.name == "posix" and os.getpgid(pid) != pgid:
                    report.skipped_unowned.append(managed_id)
                    continue
                try:
                    os.killpg(pgid, signal.SIGTERM)
                    deadline = time.monotonic() + 0.5
                    while _group_exists(pgid) and time.monotonic() < deadline:
                        time.sleep(0.01)
                    if _group_exists(pgid):
                        os.killpg(pgid, signal.SIGKILL)
                    report.recovered_process_ids.append(managed_id)
                    path.unlink(missing_ok=True)
                except (OSError, ValueError) as exc:
                    report.errors.append(f"{path}: {exc}")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                report.errors.append(f"{path}: {exc}")
        return report

    @contextmanager
    def temporary_directory(self, *, prefix: str = "proof-process-") -> Iterator[str]:
        path = Path(tempfile.mkdtemp(prefix=prefix, dir=str(self.temp_directory)))
        marker = {
            "schema": PROCESS_MANIFEST_SCHEMA,
            "supervisor_id": self.supervisor_id,
            "owner_pid": self.owner_pid,
            "owner_birth_marker": self.owner_birth_marker,
            "created_at": time.time(),
        }
        _atomic_json(path / TEMP_DIRECTORY_MARKER, marker)
        try:
            yield str(path)
        finally:
            shutil.rmtree(path, ignore_errors=True)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            active = list(self._active.values())
        for handle in active:
            handle.cancel()
        for handle in active:
            try:
                handle.wait(handle.limits.graceful_shutdown_seconds + handle.limits.forced_cleanup_seconds + 2.0)
            except TimeoutError:
                self._signal_process(handle._process, handle.process_group_id, signal.SIGKILL)

    def __enter__(self) -> "ProcessSupervisor":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def recover_stale_temporary_directories(
    root: str | Path,
    *,
    stale_after_seconds: float = 3600.0,
) -> RecoveryReport:
    """Remove stale marked directories, never unmarked or live-owner paths."""

    root_path = Path(root).expanduser().resolve()
    report = RecoveryReport()
    if not root_path.is_dir():
        return report
    now = time.time()
    for child in root_path.iterdir():
        marker_path = child / TEMP_DIRECTORY_MARKER
        if not child.is_dir() or not marker_path.is_file():
            report.skipped_unowned.append(str(child))
            continue
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            if marker.get("schema") != PROCESS_MANIFEST_SCHEMA:
                report.skipped_unowned.append(str(child))
                continue
            created = float(marker.get("created_at", marker_path.stat().st_mtime))
            pid = int(marker.get("owner_pid", 0))
            birth = str(marker.get("owner_birth_marker", ""))
            if _pid_matches(pid, birth):
                report.skipped_active.append(str(child))
                continue
            if now - created < stale_after_seconds:
                report.skipped_active.append(str(child))
                continue
            shutil.rmtree(child)
            report.removed_paths.append(str(child))
        except (OSError, ValueError, TypeError) as exc:
            report.errors.append(f"{child}: {exc}")
    return report


def recover_stale_elan_locks(
    elan_home: Optional[str | Path] = None,
    *,
    stale_after_seconds: float = 3600.0,
) -> RecoveryReport:
    """Remove old, unlocked Elan lock files without signalling tool users.

    Age alone is insufficient: an active toolchain installation may hold an
    old lock inode.  On POSIX we acquire the same advisory exclusive lock
    non-blockingly and keep it until after unlink.  Platforms without
    advisory locking conservatively skip recovery.
    """

    root = Path(elan_home or os.environ.get("ELAN_HOME", "~/.elan")).expanduser().resolve()
    report = RecoveryReport()
    if fcntl is None or not root.is_dir():
        return report
    now = time.time()
    for path in root.rglob("*.lock"):
        try:
            if not path.is_file() or now - path.stat().st_mtime < stale_after_seconds:
                report.skipped_active.append(str(path))
                continue
            with path.open("a+b") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    report.skipped_active.append(str(path))
                    continue
                # Resolve again immediately before unlink to guard against a
                # swapped symlink or a path escaping ELAN_HOME.
                if path.is_symlink() or root not in path.resolve().parents:
                    report.skipped_unowned.append(str(path))
                    continue
                path.unlink()
                report.removed_paths.append(str(path))
        except (OSError, ValueError) as exc:
            report.errors.append(f"{path}: {exc}")
    return report


_DEFAULT_SUPERVISOR: Optional[ProcessSupervisor] = None
_DEFAULT_LOCK = threading.Lock()


def get_process_supervisor() -> ProcessSupervisor:
    global _DEFAULT_SUPERVISOR
    with _DEFAULT_LOCK:
        if _DEFAULT_SUPERVISOR is None or _DEFAULT_SUPERVISOR._closed:
            _DEFAULT_SUPERVISOR = ProcessSupervisor()
        return _DEFAULT_SUPERVISOR


def run_managed_process(
    command: Sequence[str], **kwargs: Any
) -> ProcessExecutionResult:
    """Run ``command`` through the host-default proof process supervisor."""

    return get_process_supervisor().run(command, **kwargs)


@contextmanager
def supervised_temporary_directory(*, prefix: str = "proof-process-") -> Iterator[str]:
    with get_process_supervisor().temporary_directory(prefix=prefix) as path:
        yield path


__all__ = [
    "PROCESS_MANIFEST_SCHEMA",
    "TEMP_DIRECTORY_MARKER",
    "ManagedProcess",
    "ProcessExecutionResult",
    "ProcessKind",
    "ProcessLimits",
    "ProcessSupervisor",
    "RecoveryReport",
    "get_process_supervisor",
    "recover_stale_elan_locks",
    "recover_stale_temporary_directories",
    "run_managed_process",
    "supervised_temporary_directory",
]
