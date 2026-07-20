"""Production lifecycle tests for Lean, Lake, ATP, SMT, and translators."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from ipfs_datasets_py.logic.hammers.process_lifecycle import (
    PROCESS_MANIFEST_SCHEMA,
    TEMP_DIRECTORY_MARKER,
    ProcessKind,
    ProcessLimits,
    ProcessSupervisor,
    recover_stale_elan_locks,
    recover_stale_temporary_directories,
)
from ipfs_datasets_py.logic.modal.lean_runtime import run_lean_process


PYTHON = sys.executable


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists() and stat.read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0] == "Z":
            return False
        return True
    except (OSError, IndexError):
        return False


def _wait_dead(pid: int, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _alive(pid), f"managed pid {pid} survived cleanup"


def _limits(timeout: float = 2.0) -> ProcessLimits:
    return ProcessLimits(
        wall_time_seconds=timeout,
        graceful_shutdown_seconds=0.15,
        forced_cleanup_seconds=0.5,
    )


def test_short_process_is_group_owned_heartbeated_and_unregistered(tmp_path: Path) -> None:
    supervisor = ProcessSupervisor(
        state_directory=tmp_path, heartbeat_interval_seconds=0.03, recover=False
    )
    handle = supervisor.launch(
        [PYTHON, "-c", "import time; print('ready', flush=True); time.sleep(.18)"],
        kind=ProcessKind.TRANSLATOR,
        limits=_limits(),
    )
    if os.name == "posix":
        assert handle.process_group_id == handle.pid
    manifest = handle.manifest_path
    first = json.loads(manifest.read_text(encoding="utf-8"))["heartbeat_at"]
    time.sleep(0.08)
    second = json.loads(manifest.read_text(encoding="utf-8"))["heartbeat_at"]
    assert second > first
    result = handle.wait()
    assert result.returncode == 0
    assert result.stdout.strip() == "ready"
    assert result.kind == "translator"
    assert supervisor.active_process_count == 0
    assert not manifest.exists()
    supervisor.close()


def test_wall_deadline_gracefully_terminates_cooperative_process(tmp_path: Path) -> None:
    code = "import signal,time; signal.signal(signal.SIGTERM, lambda *_: exit(0)); time.sleep(60)"
    with ProcessSupervisor(state_directory=tmp_path, recover=False) as supervisor:
        result = supervisor.run([PYTHON, "-c", code], kind=ProcessKind.LEAN, limits=_limits(0.12))
    assert result.timed_out
    assert result.graceful_termination
    assert not result.forced_cleanup
    assert result.termination_reason == "wall_clock_deadline"
    _wait_dead(result.pid or -1)


def test_wall_deadline_forces_cleanup_of_term_ignoring_process_tree(tmp_path: Path) -> None:
    code = (
        "import signal,subprocess,sys,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "p=subprocess.Popen([sys.executable,'-c',"
        "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)']); "
        "print(p.pid, flush=True); time.sleep(60)"
    )
    with ProcessSupervisor(state_directory=tmp_path, recover=False) as supervisor:
        result = supervisor.run([PYTHON, "-c", code], kind=ProcessKind.ATP, limits=_limits(0.15))
    assert result.timed_out and result.forced_cleanup
    child_pid = int(result.stdout.strip())
    _wait_dead(result.pid or -1)
    _wait_dead(child_pid)


def test_external_cancellation_cleans_group(tmp_path: Path) -> None:
    cancelled = threading.Event()
    with ProcessSupervisor(state_directory=tmp_path, recover=False) as supervisor:
        handle = supervisor.launch(
            [PYTHON, "-c", "import time; time.sleep(60)"],
            kind=ProcessKind.SMT,
            limits=_limits(10),
            cancel_event=cancelled,
        )
        cancelled.set()
        result = handle.wait(3)
        assert result.cancelled
        assert supervisor.active_process_count == 0
    _wait_dead(result.pid or -1)


class _FakeLease:
    def __init__(self) -> None:
        self.cancelled = False
        self.heartbeats = 0
        self.releases = 0
        self.released = False

    def heartbeat(self) -> bool:
        self.heartbeats += 1
        return True

    def release(self) -> bool:
        if self.released:
            return False
        self.released = True
        self.releases += 1
        return True


def test_lease_is_heartbeated_and_released_exactly_once(tmp_path: Path) -> None:
    lease = _FakeLease()
    with ProcessSupervisor(
        state_directory=tmp_path, heartbeat_interval_seconds=0.02, recover=False
    ) as supervisor:
        result = supervisor.run(
            [PYTHON, "-c", "import time; time.sleep(.09)"],
            kind=ProcessKind.LAKE,
            limits=_limits(),
            lease=lease,
        )
    assert result.returncode == 0
    assert lease.heartbeats >= 2
    assert lease.releases == 1
    assert result.lease_released


def test_resource_lease_cancellation_is_a_resource_deadline(tmp_path: Path) -> None:
    lease = _FakeLease()
    with ProcessSupervisor(state_directory=tmp_path, recover=False) as supervisor:
        handle = supervisor.launch(
            [PYTHON, "-c", "import time; time.sleep(60)"],
            limits=_limits(10),
            lease=lease,
        )
        lease.cancelled = True
        result = handle.wait(3)
    assert result.cancelled
    assert result.termination_reason == "resource_deadline"
    assert lease.releases == 1


def test_close_models_test_interruption_and_leaves_no_managed_children(tmp_path: Path) -> None:
    supervisor = ProcessSupervisor(state_directory=tmp_path, recover=False)
    handles = [
        supervisor.launch(
            [PYTHON, "-c", "import time; time.sleep(60)"],
            kind=kind,
            limits=_limits(30),
        )
        for kind in (ProcessKind.LEAN, ProcessKind.SMT, ProcessKind.TRANSLATOR)
    ]
    pids = [handle.pid for handle in handles]
    supervisor.close()
    assert supervisor.active_process_count == 0
    for pid in pids:
        _wait_dead(pid)


def test_stale_temporary_directory_recovery_requires_marker_and_dead_owner(tmp_path: Path) -> None:
    stale = tmp_path / "partial"
    stale.mkdir()
    (stale / "partial-output").write_text("x", encoding="utf-8")
    (stale / TEMP_DIRECTORY_MARKER).write_text(
        json.dumps(
            {
                "schema": PROCESS_MANIFEST_SCHEMA,
                "owner_pid": 999_999_999,
                "owner_birth_marker": "linux:missing",
                "created_at": 0,
            }
        ),
        encoding="utf-8",
    )
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    report = recover_stale_temporary_directories(tmp_path, stale_after_seconds=0)
    assert str(stale) in report.removed_paths
    assert not stale.exists()
    assert unrelated.exists()
    assert str(unrelated) in report.skipped_unowned


@pytest.mark.skipif(os.name != "posix", reason="Elan uses POSIX advisory locks here")
def test_elan_recovery_removes_stale_unlocked_but_preserves_active_lock(tmp_path: Path) -> None:
    import fcntl

    unlocked = tmp_path / "downloads" / "stale.lock"
    active = tmp_path / "toolchains" / "active.lock"
    unlocked.parent.mkdir()
    active.parent.mkdir()
    unlocked.touch()
    active.touch()
    old = time.time() - 100
    os.utime(unlocked, (old, old))
    os.utime(active, (old, old))
    with active.open("a+b") as active_handle:
        fcntl.flock(active_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = recover_stale_elan_locks(tmp_path, stale_after_seconds=1)
        assert not unlocked.exists()
        assert active.exists()
        assert str(active) in report.skipped_active


def test_recovery_does_not_kill_unrelated_process_from_forged_manifest(tmp_path: Path) -> None:
    process = subprocess.Popen([PYTHON, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        processes = tmp_path / "processes"
        processes.mkdir(parents=True)
        marker = {
            "schema": PROCESS_MANIFEST_SCHEMA,
            "managed_process_id": "forged",
            "supervisor_pid": 999_999_999,
            "supervisor_birth_marker": "linux:missing",
            "pid": process.pid,
            "pid_birth_marker": f"linux:{Path(f'/proc/{process.pid}/stat').read_text().rsplit(')', 1)[1].split()[19]}",
            "process_group_id": os.getpgid(process.pid),
            "heartbeat_at": 0,
        }
        (processes / "forged.json").write_text(json.dumps(marker), encoding="utf-8")
        supervisor = ProcessSupervisor(state_directory=tmp_path, recover=True)
        assert _alive(process.pid)
        assert "forged" in supervisor.recover_orphaned_processes().skipped_unowned
        supervisor.close()
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


@pytest.mark.skipif(os.name != "posix", reason="durable recovery uses Linux process identity")
def test_supervisor_restart_recovers_exact_token_owned_orphan(tmp_path: Path) -> None:
    managed_id = "restart-owned-process"
    env = dict(os.environ)
    env["IPFS_DATASETS_MANAGED_PROCESS_ID"] = managed_id
    process = subprocess.Popen(
        [PYTHON, "-c", "import time; time.sleep(60)"],
        env=env,
        start_new_session=True,
    )
    processes = tmp_path / "processes"
    processes.mkdir(parents=True)
    birth = Path(f"/proc/{process.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    (processes / f"{managed_id}.json").write_text(
        json.dumps(
            {
                "schema": PROCESS_MANIFEST_SCHEMA,
                "managed_process_id": managed_id,
                "supervisor_pid": 999_999_999,
                "supervisor_birth_marker": "linux:missing",
                "pid": process.pid,
                "pid_birth_marker": f"linux:{birth}",
                "process_group_id": os.getpgid(process.pid),
                "heartbeat_at": 0,
            }
        ),
        encoding="utf-8",
    )
    try:
        supervisor = ProcessSupervisor(state_directory=tmp_path, recover=False)
        report = supervisor.recover_orphaned_processes()
        assert report.recovered_process_ids == [managed_id]
        process.wait(timeout=3)
        assert not _alive(process.pid)
        assert not (processes / f"{managed_id}.json").exists()
        supervisor.close()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def test_lean_runtime_uses_supervisor_owned_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class FakeSupervisor:
        def run(self, command, **kwargs):
            calls.append((command, kwargs))
            from ipfs_datasets_py.logic.hammers.process_lifecycle import ProcessExecutionResult
            return ProcessExecutionResult(command=list(command), kind=kwargs["kind"].value, returncode=0)

    monkeypatch.setattr("ipfs_datasets_py.logic.modal.lean_runtime.get_process_supervisor", lambda: FakeSupervisor())
    result = run_lean_process(["/tools/lake", "env", "lean", "Task.lean"], timeout=3)
    assert result.returncode == 0
    assert calls[0][1]["kind"] is ProcessKind.LAKE
    assert calls[0][1]["limits"].wall_time_seconds == 3
