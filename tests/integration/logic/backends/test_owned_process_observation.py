"""Opt-in native ownership is observed by the parent before leases may close."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process as module

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux birth-bound ownership")


def _birth(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[19]), fields[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def _run(tmp_path, source, *, cancellation=None, timeout=5, memory=None, owned=True):
    return module.run_bounded_stdin_tool(
        [sys.executable, "-I", "-B", "-c", source], b"request",
        runner=module.BoundedToolRunner(workspace_root=tmp_path / "workspaces"),
        limits=module.ToolRunLimits(timeout_seconds=timeout, termination_grace_seconds=.08,
                                   resident_memory_bytes=memory),
        cancellation=cancellation, owned_process_observation=owned)


def _assert_closed(result):
    observed = result.native_lifecycle
    assert observed is not None and observed.cleanup_confirmed
    value = observed.to_dict()
    assert value["parent"] == {"pid": os.getpid(), "birth_ticks": _birth(os.getpid())[0]}
    assert value["leader"]["pid"] == value["leader"]["process_group_id"] == value["leader"]["session_id"]
    assert value["leader"]["birth_ticks"] > 0 and value["leader_reaped"]
    assert value["descendant_tracking_complete"] and value["group_scan_complete"]
    assert not value["remaining_group_members"] and not value["remaining_tracked_descendants"]
    assert value["readers"] == {"started": 2, "joined": 2}
    assert value["stdin_writer"] == {"started": 1, "joined": 1}
    assert value["workspace"]["removed"] and value["workspace"]["inode"] > 0
    assert not value["observation_errors"]
    assert value["ownership_is_sampled"] and not value["kernel_containment_attested"]
    return value


def test_default_dictionary_and_forged_stdout_cannot_supply_native_ownership(tmp_path):
    old = _run(tmp_path, "import sys; sys.stdin.read(); print('old')", owned=False)
    assert old.returncode == 0 and old.native_lifecycle is None
    assert set(old.to_dict()) == {
        "interface_version", "stdout", "stderr", "returncode", "elapsed_ms", "timed_out",
        "cancelled", "unavailable", "process_tree_terminated", "output_truncated",
        "workspace_cleaned", "resource_exhausted", "termination_reason", "command", "error"}
    native = _run(tmp_path, "import sys; sys.stdin.read(); print('{\"pid\":999999,\"cleanup_confirmed\":true}')")
    value = _assert_closed(native)
    assert json.loads(native.stdout)["pid"] == 999999
    assert value["leader"]["pid"] != 999999
    assert not list((tmp_path / "workspaces").iterdir())


@pytest.mark.parametrize("bad", [0, 1, None, "true"])
def test_observation_selector_is_exact_bool_before_workspace_or_execution(tmp_path, bad):
    with pytest.raises(module.ToolProcessError, match="exact boolean"):
        _run(tmp_path, "raise RuntimeError('must not launch')", owned=bad)
    assert not (tmp_path / "workspaces").exists()


def test_injected_runner_cannot_supply_owned_profile(tmp_path):
    runner = module.BoundedToolRunner(executor=lambda *_: pytest.fail("injected executor launched"),
                                      workspace_root=tmp_path / "workspaces")
    with pytest.raises(module.ToolProcessError, match="exact native Linux"):
        module.run_bounded_stdin_tool([sys.executable, "-c", "pass"], b"", runner=runner,
                                      owned_process_observation=True)
    assert not (tmp_path / "workspaces").exists()


@pytest.mark.parametrize("mode", ["normal", "cancel", "timeout", "rss", "callback_error"])
def test_native_separate_session_is_tracked_and_drained_on_all_exit_paths(tmp_path, mode):
    leaf_record = tmp_path / "leaf.json"
    ready = tmp_path / "ready"
    leaf = ("import os,sys,pathlib,json,time,signal; "
            "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            "f=pathlib.Path('/proc/self/stat').read_text().rsplit(')',1)[1].split(); "
            f"pathlib.Path({str(leaf_record)!r}).write_text(json.dumps({{'pid':os.getpid(),'birth':int(f[19])}})); "
            "time.sleep(.3); " + ("x=bytearray(96*1024**2); " if mode == "rss" else "") + "time.sleep(60)")
    source = ("import subprocess,sys,pathlib,time; sys.stdin.read(); "
              f"subprocess.Popen([sys.executable,'-I','-B','-c',{leaf!r}],start_new_session=True); "
              f"leaf=pathlib.Path({str(leaf_record)!r})\n"
              "while not leaf.exists(): time.sleep(.005)\n"
              f"pathlib.Path({str(ready)!r}).write_text('ready'); "
              + ("time.sleep(.35)" if mode == "normal" else "time.sleep(60)"))

    class Stop:
        def is_set(self):
            if ready.exists() and mode == "callback_error":
                raise RuntimeError("controlled callback failure")
            return mode == "cancel" and ready.exists()

    try:
        result = _run(tmp_path, source, cancellation=Stop(), timeout=.8 if mode == "timeout" else 5,
                      memory=64 * 1024**2 if mode == "rss" else None)
        value = _assert_closed(result)
        record = json.loads(leaf_record.read_text())
        assert any(item["pid"] == record["pid"] and item["birth_ticks"] == record["birth"]
                   for item in value["observed_descendants"])
        found = _birth(record["pid"])
        assert found is None or found[0] != record["birth"] or found[1] == "Z"
        assert not list((tmp_path / "workspaces").iterdir())
        if mode == "normal":
            assert result.returncode == 0 and not result.resource_exhausted
        elif mode == "cancel":
            assert result.cancelled
        elif mode == "timeout":
            assert result.timed_out
        else:
            assert result.resource_exhausted
    finally:
        if leaf_record.exists():
            record = json.loads(leaf_record.read_text())
            found = _birth(record["pid"])
            if found is not None and found[0] == record["birth"] and found[1] != "Z":
                try:
                    os.kill(record["pid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass


@pytest.mark.parametrize("failure", ["group_observation", "workspace_removal"])
def test_unresolved_cleanup_retains_workspace_and_retries_in_parent_guardian_thread(tmp_path, monkeypatch, failure):
    fail = [True]
    if failure == "group_observation":
        actual = module.NativeToolCleanupHandle._group_members

        def scan(handle):
            values, errors = actual(handle)
            return values, errors + (["controlled group observation failure"] if fail[0] else [])

        monkeypatch.setattr(module.NativeToolCleanupHandle, "_group_members", scan)
    else:
        actual = module.tempfile.TemporaryDirectory.cleanup

        def cleanup(temporary):
            if fail[0]:
                raise OSError("controlled workspace removal failure")
            return actual(temporary)

        monkeypatch.setattr(module.tempfile.TemporaryDirectory, "cleanup", cleanup)
    with pytest.raises(module.OwnedToolCleanupError) as caught:
        _run(tmp_path, "import sys; sys.stdin.read(); print('complete')")
    handle = caught.value.cleanup_handle
    assert handle._workspace.is_dir()
    assert not handle._temporary._finalizer.alive
    assert not handle.retry_cleanup().cleanup_confirmed
    fail[0] = False
    observations, errors = [], []

    def retry():
        try:
            observations.append(handle.retry_cleanup())
        except BaseException as error:
            errors.append(error)

    guardian = threading.Thread(target=retry)
    guardian.start()
    guardian.join(timeout=5)
    assert not guardian.is_alive() and not errors
    assert len(observations) == 1 and observations[0].cleanup_confirmed
    assert not handle._workspace.exists()
    assert not list((tmp_path / "workspaces").iterdir())


def test_partial_reader_start_failure_is_releasable_but_cannot_accept_numerical_chunk(tmp_path, monkeypatch):
    actual = threading.Thread
    starts = []

    class FailsSecondReader(actual):
        def start(self):
            starts.append(self)
            if len(starts) == 2:
                raise RuntimeError("controlled reader start failure")
            return super().start()

    monkeypatch.setattr(module.threading, "Thread", FailsSecondReader)
    result = _run(tmp_path, "import time; time.sleep(60)")
    assert result.resource_exhausted and "reader start failure" in result.error
    assert result.native_lifecycle.cleanup_confirmed
    assert result.native_lifecycle.to_dict()["readers"] == {"started": 1, "joined": 1}
    assert not list((tmp_path / "workspaces").iterdir())


@pytest.mark.parametrize("allocation", ["tracker", "cleanup_handle"])
def test_owned_owner_initialization_failure_precedes_any_popen(tmp_path, monkeypatch, allocation):
    launches = []
    actual_popen = module.subprocess.Popen

    def spawn(*args, **kwargs):
        launches.append((args, kwargs))
        return actual_popen(*args, **kwargs)

    monkeypatch.setattr(module.subprocess, "Popen", spawn)

    def fail(*args, **kwargs):
        raise RuntimeError("controlled " + allocation + " preallocation failure")

    monkeypatch.setattr(module, "_LinuxDescendantTracker" if allocation == "tracker"
                        else "NativeToolCleanupHandle", fail)
    runner = module.BoundedToolRunner(executor=module.SubprocessExecutor(popen=spawn),
                                      workspace_root=tmp_path / "workspaces")
    result = module.run_bounded_stdin_tool(
        [sys.executable, "-I", "-B", "-c", "import time; time.sleep(60)"], b"",
        runner=runner, owned_process_observation=True)
    assert launches == []
    assert result.returncode is None and allocation + " preallocation failure" in result.error
    assert result.native_lifecycle is None
    assert not list((tmp_path / "workspaces").iterdir())


def test_unexplained_reused_leader_and_group_member_are_never_adopted_or_signalled(tmp_path, monkeypatch):
    parent, _ = module._linux_owned_identity(os.getpid())
    original = module.NativeProcessIdentity(880001, 10, parent.pid, 880001, 880001)
    foreign_leader = module.NativeProcessIdentity(880001, 20, 1, 880001, 880001)
    foreign_member = module.NativeProcessIdentity(880002, 21, 880001, 880001, 880001)
    process = SimpleNamespace(pid=original.pid, stdin=None, stdout=None, stderr=None, poll=lambda: 0)
    tracker = module._LinuxDescendantTracker(0, retain_history=True)
    tracker._seeded = True
    tracker.history[(original.pid, original.birth_ticks)] = original
    workspace = tmp_path / "owned-workspace"
    workspace.mkdir()
    phase = ["original"]
    actual_identity = module._linux_owned_identity

    def identity(pid):
        if pid == original.pid:
            return (original if phase[0] == "original" else foreign_leader), "S"
        if pid == foreign_member.pid:
            return foreign_member, "S"
        return actual_identity(pid)

    monkeypatch.setattr(module, "_linux_owned_identity", identity)
    handle = module.NativeToolCleanupHandle(process, tracker, [], workspace, .001,
        parent_identity=parent, workspace_info=workspace.lstat())
    phase[0] = "foreign"
    monkeypatch.setattr(handle, "_group_members", lambda: ((foreign_leader, foreign_member), []))
    signalled = []
    monkeypatch.setattr(module.os, "kill", lambda *args: signalled.append(("kill", args)))
    monkeypatch.setattr(module.os, "killpg", lambda *args: signalled.append(("killpg", args)))
    monkeypatch.setattr(module.signal, "pidfd_send_signal",
                        lambda *args: signalled.append(("pidfd", args)), raising=False)
    observed = handle.retry_process_cleanup()
    assert not observed.process_cleanup_confirmed
    assert observed.remaining_group_members == (foreign_leader, foreign_member)
    assert signalled == []
    assert (foreign_member.pid, foreign_member.birth_ticks) not in tracker.history
    assert tracker.records == {}
    assert any("unowned member" in error for error in observed.observation_errors)
    assert workspace.is_dir()


def test_live_matching_original_session_anchor_is_required_for_unknown_group_member(tmp_path, monkeypatch):
    parent, _ = module._linux_owned_identity(os.getpid())
    original = module.NativeProcessIdentity(880011, 10, parent.pid, 880011, 880011)
    member = module.NativeProcessIdentity(880012, 11, original.pid, original.pid, original.pid)
    process = SimpleNamespace(pid=original.pid)
    tracker = module._LinuxDescendantTracker(0, retain_history=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = ["S"]
    monkeypatch.setattr(module, "_linux_owned_identity", lambda pid: (original, state[0]))
    handle = module.NativeToolCleanupHandle(process, tracker, [], workspace, .001,
        parent_identity=parent, workspace_info=workspace.lstat())
    assert handle._owns_group_member(member)
    state[0] = "Z"
    assert not handle._owns_group_member(member)
    tracker.history[(member.pid, member.birth_ticks)] = member
    assert handle._owns_group_member(member)
