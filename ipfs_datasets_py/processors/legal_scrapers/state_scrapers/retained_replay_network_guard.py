"""Process-wide network denial for retained state-law replay.

Retained replay is a byte-reprocessing mode, not an acquisition transport.
The ordinary scraper adapters already fail closed at their shared fetch seams,
but a state-owned helper, raw ``urllib`` call, manually-created thread, or
network-capable subprocess must not be able to escape those seams.  This
module installs one inert Python audit hook and activates it only while one or
more retained state workers hold a deny lease.

The active decision is deliberately process-global.  ``ContextVar`` state is
used only as a diagnostic hint because newly-created ``threading.Thread``
workers do not inherit context variables.  Any attempted network syscall while
the global lease is active permanently poisons every active evidence root and
causes each affected guard to fail on exit even when scraper code swallowed
the audit-hook exception.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import shutil
import socket
import sys
import threading
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from ...legal_data.state_laws_multifetch_acquisition import (
    StateLawRetainedReplayOnlyError,
)
from ...legal_data.state_laws_run_seal import (
    IN_PROGRESS_EVIDENCE_MARKER,
    NONQUIESCENT_EVIDENCE_MARKER,
)


_NETWORK_AUDIT_EVENTS: Final = frozenset(
    {
        "socket.connect",
        "socket.bind",
        "socket.getaddrinfo",
        "socket.gethostbyaddr",
        "socket.gethostbyname",
        "socket.gethostbyname_ex",
        "socket.getnameinfo",
        "socket.__new__",
        "socket.sendmsg",
        "socket.sendto",
    }
)
_PROCESS_LAUNCH_AUDIT_EVENTS: Final = frozenset(
    {
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.spawn",
        "os.startfile",
        "os.system",
    }
)
_AUDIT_LIVENESS_EVENT: Final = (
    "ipfs_datasets_py.state_laws.retained_replay_guard_liveness"
)
_AF_UNIX_FAMILY: Final = int(getattr(socket, "AF_UNIX", -1))
_ACTIVE_GUARDS_LOCK = threading.RLock()
_ACTIVE_GUARDS: dict[str, dict[str, Any]] = {}
_CONTEXT_GUARD_TOKEN: contextvars.ContextVar[str] = contextvars.ContextVar(
    "state_laws_retained_replay_guard_token",
    default="",
)


_OVERFLOW_UIDS: Final = frozenset({65534})
_SYSTEM_PDFTOTEXT_PATHS: Final = frozenset(
    {"/bin/pdftotext", "/usr/bin/pdftotext"}
)


def _posix_converter_is_trusted(candidate: Path, stat_result: os.stat_result) -> bool:
    """Accept the host root-owned converter, or its rootless bind-mount image.

    Rootless Docker maps container uid 0 to the invoking user and shows
    host-root files as overflow uid 65534.  The isolated worker still mounts
    ``/usr`` read-only, so a non-writable ``/usr/bin/pdftotext`` there is the
    same host converter, not a look-alike.
    """

    if stat_result.st_mode & 0o022:
        return False
    if candidate.is_symlink() or not candidate.is_file():
        return False
    if stat_result.st_uid == 0:
        for parent in (candidate.parent, *candidate.parents):
            parent_stat = parent.stat()
            if parent_stat.st_uid != 0 or parent_stat.st_mode & 0o022:
                return False
            if parent == parent.parent:
                break
        return True
    if stat_result.st_uid not in _OVERFLOW_UIDS:
        return False
    if str(candidate) not in _SYSTEM_PDFTOTEXT_PATHS:
        return False
    return not os.access(candidate, os.W_OK)


def _resolve_trusted_pdftotext() -> tuple[str, str]:
    """Bind a privileged, non-writable system converter and its exact bytes."""

    raw_candidate = shutil.which("pdftotext", path=os.defpath)
    if not raw_candidate:
        return "", ""
    try:
        candidate = Path(raw_candidate).resolve(strict=True)
        stat_result = candidate.stat()
        if os.name == "posix" and not _posix_converter_is_trusted(
            candidate, stat_result
        ):
            return "", ""
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    except OSError:
        return "", ""
    return str(candidate), digest


_TRUSTED_PDFTOTEXT_PATH, _TRUSTED_PDFTOTEXT_SHA256 = (
    _resolve_trusted_pdftotext()
)


def trusted_pdftotext_executable() -> str:
    """Return the exact root-owned converter bound at import time.

    Callers must pass this absolute path to ``subprocess``.  Basename
    ``pdftotext`` lookups remain forbidden because they can exec a look-alike
    from ``PATH`` after the audit hook observes only the requested name.
    """

    if not _TRUSTED_PDFTOTEXT_PATH or not _TRUSTED_PDFTOTEXT_SHA256:
        raise FileNotFoundError("no trusted root-owned pdftotext is bound")
    return _TRUSTED_PDFTOTEXT_PATH


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _read_run_binding(root: Path) -> tuple[str, str]:
    """Return the durable run id and lease digest without trusting a symlink."""

    marker = root / IN_PROGRESS_EVIDENCE_MARKER
    if marker.is_symlink() or not marker.is_file():
        return "unbound-retained-worker", ""
    try:
        raw = marker.read_bytes()
        payload = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "invalid-in-progress-marker", ""
    if not isinstance(payload, dict):
        return "invalid-in-progress-marker", hashlib.sha256(raw).hexdigest()
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        run_id = "invalid-in-progress-marker"
    return run_id, hashlib.sha256(raw).hexdigest()


def _write_permanent_network_violation_poison(
    *,
    root: Path,
    states: tuple[str, ...],
    event: str,
    target: str,
) -> None:
    """Install the existing permanent nonauthorization fence with O_EXCL."""

    if root.is_symlink() or not root.is_dir():
        return
    run_id, lease_sha256 = _read_run_binding(root)
    payload = {
        "affected_states": list(states),
        "attempted_event": str(event),
        "attempted_target": str(target),
        "authorizing_for_publication": False,
        "evidence_root": str(root),
        "in_progress_marker_sha256": lease_sha256 or None,
        "permanently_nonauthorizing": True,
        "reason": "retained replay attempted a forbidden network operation",
        "run_id": run_id,
        "schema": (
            "ipfs_datasets_py.state_laws_refresh."
            "retained_network_violation.v1"
        ),
    }
    raw = _canonical_json_bytes(payload)
    target_path = root / NONQUIESCENT_EVIDENCE_MARKER
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target_path, flags, 0o600)
    except FileExistsError:
        # Any existing permanent-nonauthorization marker is already stronger
        # than another diagnostic write.  Never replace its first evidence.
        return
    except OSError:
        return
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                return
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    try:
        directory_descriptor = os.open(root, directory_flags)
    except OSError:
        return
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _decode_subprocess_executable(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    if isinstance(value, os.PathLike):
        return os.fsdecode(value).strip()
    return str(value or "").strip()


def _is_trusted_pdftotext_executable(executable: Any) -> bool:
    """Allow only the exact root-owned converter bound at import time.

    Basename and ``PATH`` lookup are never sufficient.  A look-alike
    ``pdftotext`` on a caller-controlled path must not inherit the local
    converter exception, and the file bytes are re-hashed on every use so a
    swapped inode cannot reuse the import-time path string.
    """

    if not _TRUSTED_PDFTOTEXT_PATH or not _TRUSTED_PDFTOTEXT_SHA256:
        return False
    raw = _decode_subprocess_executable(executable)
    if not raw or not os.path.isabs(raw):
        return False
    candidate = Path(raw)
    try:
        if candidate.is_symlink() or not candidate.is_file():
            return False
        resolved = candidate.resolve(strict=True)
        if str(resolved) != _TRUSTED_PDFTOTEXT_PATH:
            return False
        if resolved.is_symlink() or not resolved.is_file():
            return False
        stat_result = resolved.stat()
        if os.name == "posix" and not _posix_converter_is_trusted(
            resolved, stat_result
        ):
            return False
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError:
        return False
    return digest == _TRUSTED_PDFTOTEXT_SHA256


def _subprocess_executable(args: tuple[Any, ...]) -> str:
    return _decode_subprocess_executable(args[0] if args else "")


def _subprocess_target(args: tuple[Any, ...]) -> str:
    executable = _subprocess_executable(args)
    if not executable:
        return "unknown-subprocess"
    return executable


def _network_target(event: str, args: tuple[Any, ...]) -> str:
    if event == "subprocess.Popen":
        return _subprocess_target(args) or "unknown-subprocess"
    if event in _PROCESS_LAUNCH_AUDIT_EVENTS:
        if event == "os.system":
            return "shell-command-redacted"
        if not args:
            return "unknown-process-launch"
        candidate = args[0]
        if isinstance(candidate, bytes):
            return candidate.decode("utf-8", errors="replace")[:500]
        return str(candidate)[:500]
    if event == "socket.connect" and len(args) > 1:
        return str(args[1])[:500]
    if event == "socket.bind" and len(args) > 1:
        return str(args[1])[:500]
    if event == "socket.sendto" and len(args) > 2:
        return str(args[2])[:500]
    if event.startswith("socket.get") and args:
        return str(args[-1])[:500]
    return "network-target-redacted"


def _is_forbidden_audit_event(event: str, args: tuple[Any, ...]) -> bool:
    if event in _NETWORK_AUDIT_EVENTS:
        if event == "socket.__new__":
            family = args[1] if len(args) > 1 else None
            return family != getattr(socket, "AF_UNIX", object())
        if event in {
            "socket.bind",
            "socket.connect",
            "socket.sendmsg",
            "socket.sendto",
        } and args:
            candidate = args[0]
            family = getattr(candidate, "family", None)
            if family == getattr(socket, "AF_UNIX", object()):
                return False
        return True
    if event == "subprocess.Popen":
        return not _is_trusted_pdftotext_executable(_subprocess_executable(args))
    if event in _PROCESS_LAUNCH_AUDIT_EVENTS:
        return True
    return False


def _record_named_violation(event: str, target: str) -> None:
    with _ACTIVE_GUARDS_LOCK:
        active = tuple(_ACTIVE_GUARDS.values())
        if not active:
            return
        violation = {"event": event, "target": target}
        for state in active:
            state["violation"] = state.get("violation") or violation
        roots: dict[Path, set[str]] = {}
        for state in active:
            roots.setdefault(Path(state["root"]), set()).add(
                str(state["state_code"])
            )
    for root, states in roots.items():
        _write_permanent_network_violation_poison(
            root=root,
            states=tuple(sorted(states)),
            event=event,
            target=target,
        )


def _record_violation(event: str, args: tuple[Any, ...]) -> str:
    target = _network_target(event, args)
    _record_named_violation(event, target)
    return target


def _retained_replay_audit_hook(event: str, args: tuple[Any, ...]) -> None:
    if event == _AUDIT_LIVENESS_EVENT:
        token = str(args[0] if args else "")
        with _ACTIVE_GUARDS_LOCK:
            state = _ACTIVE_GUARDS.get(token)
            if state is not None:
                state["liveness_proved"] = True
        return
    with _ACTIVE_GUARDS_LOCK:
        active = bool(_ACTIVE_GUARDS)
    if not active or not _is_forbidden_audit_event(event, args):
        return
    target = _record_violation(event, args)
    raise StateLawRetainedReplayOnlyError(
        "retained-replay-only process guard blocked forbidden operation "
        f"{event}: {target}"
    )


# Install the inert hook as part of the module's immutable executable
# lifecycle.  It performs no work unless a retained worker holds a lease.
# Keeping installation out of guard entry removes mutable "already installed"
# state that scraper code could tamper with to suppress first-use enforcement.
sys.addaudithook(_retained_replay_audit_hook)


def _active_worker_thread_idents_locked() -> set[int]:
    """Return idents of threads that currently hold a deny lease.

    Historical nested-worker idents are never retained.  Thread IDs are reused
    by the OS; a finished worker's ident must not exclude a later child from
    the survivor set.
    """

    return {
        int(state["worker_ident"])
        for state in _ACTIVE_GUARDS.values()
        if state.get("worker_ident") is not None
    }


def _surviving_child_threads_locked(
    *,
    token: str,
    current_ident: int,
) -> tuple[threading.Thread, ...]:
    state = _ACTIVE_GUARDS.get(token)
    if state is None:
        return ()
    entry_thread_ids = set(state.get("entry_thread_ids") or ())
    active_workers = _active_worker_thread_idents_locked()
    return tuple(
        thread
        for thread in threading.enumerate()
        if thread.is_alive()
        and thread.ident is not None
        and thread.ident != current_ident
        and thread.ident not in entry_thread_ids
        and thread.ident not in active_workers
    )


def _finish_quarantined_guard(
    token: str,
    surviving_threads: tuple[threading.Thread, ...],
) -> None:
    """Keep denial active until every child surviving a worker has stopped."""

    pending = surviving_threads
    while pending:
        for thread in pending:
            try:
                thread.join()
            except (RuntimeError, TimeoutError):
                # A thread that cannot be joined keeps the deny lease active.
                # A permanent process-wide network fence is safer than
                # releasing a poisoned root while unknown work is still live.
                return
        with _ACTIVE_GUARDS_LOCK:
            if token not in _ACTIVE_GUARDS:
                return
            pending = _surviving_child_threads_locked(
                token=token,
                current_ident=threading.get_ident(),
            )
    with _ACTIVE_GUARDS_LOCK:
        _ACTIVE_GUARDS.pop(token, None)


def _release_guard_or_quarantine_children(
    token: str,
) -> tuple[threading.Thread, ...]:
    """Release one lease or retain it until newly surviving threads quiesce."""

    with _ACTIVE_GUARDS_LOCK:
        if token not in _ACTIVE_GUARDS:
            return ()
        current_ident = threading.get_ident()
        survivors = _surviving_child_threads_locked(
            token=token,
            current_ident=current_ident,
        )
        if not survivors:
            _ACTIVE_GUARDS.pop(token, None)
            return ()
        target = ",".join(
            sorted(
                f"{thread.name}:{thread.ident}"
                for thread in survivors
            )
        )[:500]
    _record_named_violation("thread.survived_retained_worker", target)
    monitor = threading.Thread(
        target=_finish_quarantined_guard,
        args=(token, survivors),
        name="state-laws-retained-replay-quiescence-monitor",
        daemon=True,
    )
    monitor.start()
    return survivors


@contextmanager
def retained_replay_network_guard(
    *,
    ledger: Any,
    state_code: str,
) -> Iterator[None]:
    """Deny network operations process-wide for one retained worker lease."""

    if getattr(ledger, "retained_replay_only", False) is not True:
        yield
        return
    root = Path(getattr(ledger, "root", "")).expanduser().resolve()
    normalized_state = str(state_code or "").strip().upper()
    if not normalized_state:
        raise StateLawRetainedReplayOnlyError(
            "retained-replay-only network guard requires a state code"
        )
    token = uuid.uuid4().hex
    state: dict[str, Any] = {
        "entry_thread_ids": {
            int(thread.ident)
            for thread in threading.enumerate()
            if thread.ident is not None
        },
        "liveness_proved": False,
        "root": root,
        "state_code": normalized_state,
        "violation": None,
        "worker_ident": threading.get_ident(),
    }
    with _ACTIVE_GUARDS_LOCK:
        _ACTIVE_GUARDS[token] = state
    context_token = _CONTEXT_GUARD_TOKEN.set(token)
    pending_error: BaseException | None = None
    try:
        # Prove the import-time hook is actually live in this process.  A
        # suppressed or replaced hook would otherwise let a worker proceed
        # with source correspondence while denial is inert.
        sys.audit(_AUDIT_LIVENESS_EVENT, token)
        if state.get("liveness_proved") is not True:
            _record_named_violation("audit.hook_not_live", token)
            raise StateLawRetainedReplayOnlyError(
                "retained-replay-only network guard failed its fresh-process "
                f"liveness proof: {_AUDIT_LIVENESS_EVENT}"
            )
        yield
    except BaseException as exc:
        pending_error = exc
    finally:
        _CONTEXT_GUARD_TOKEN.reset(context_token)
        _release_guard_or_quarantine_children(token)
    violation = state.get("violation")
    if isinstance(violation, dict):
        raise StateLawRetainedReplayOnlyError(
            "retained-replay-only worker is permanently non-authorizing after "
            f"forbidden operation {violation.get('event')}: "
            f"{violation.get('target')}"
        ) from pending_error
    if pending_error is not None:
        raise pending_error


__all__ = ["retained_replay_network_guard", "trusted_pdftotext_executable"]
