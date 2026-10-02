"""Native helper sessions remain owned through cancellation and leader exit."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import time

import pytest

from ipfs_datasets_py.logic.backends import process as module

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux ancestry and pidfd cleanup")


def _identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[19]), fields[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def _fixture_source(directory, mode, separate_session):
    write_identity = "fields=pathlib.Path('/proc/self/stat').read_text().rsplit(')',1)[1].split(); "
    write_identity += "pathlib.Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),'birth':int(fields[19])}))"
    leaf = ("import os,signal,time,pathlib,sys,json; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            + write_identity + "; time.sleep(.2); "
            + ("allocation=bytearray(96*1024**2); " if mode == "rss" else "") + "time.sleep(60)")
    launch_options = "start_new_session=True" if separate_session else "process_group=0"
    middle = ("import os,signal,time,pathlib,sys,json,subprocess,threading; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); " + write_identity + "; "
        # Fork from a non-leader thread to exercise JVM-style ancestry lookup.
        f"thread=threading.Thread(target=lambda:subprocess.Popen([sys.executable,'-c',{leaf!r},{str(directory / 'leaf.json')!r}],{launch_options})); "
        "thread.start(); thread.join(); time.sleep(60)")
    source = ("import os,time,pathlib,sys,json,subprocess; "
        f"subprocess.Popen([sys.executable,'-c',{middle!r},{str(directory / 'middle.json')!r}],{launch_options}); "
        f"ready=pathlib.Path({str(directory / 'ready')!r}); leaf=pathlib.Path({str(directory / 'leaf.json')!r})\n"
        "while not leaf.exists(): time.sleep(.005)\n"
        "ready.write_text('ready')\n" + ("time.sleep(.3)" if mode == "normal" else "time.sleep(60)"))
    return source


@pytest.mark.parametrize("mode", ["cancel", "timeout", "rss", "normal"])
@pytest.mark.parametrize("separate_session", [True, False], ids=["new-session", "new-group"])
def test_independent_descendants_stop_before_receipt_on_every_exit(tmp_path, mode, separate_session):
    source = _fixture_source(tmp_path, mode, separate_session)
    class ReadyCancellation:
        def is_set(self):
            return mode == "cancel" and (tmp_path / "ready").exists()
    result = None
    try:
        result = module.BoundedToolRunner(workspace_root=tmp_path / "workspaces").run(
            module.ToolRunRequest(argv=(sys.executable, "-c", source), limits=module.ToolRunLimits(
                timeout_seconds=.8 if mode == "timeout" else 5,
                termination_grace_seconds=.08, resident_memory_bytes=64 * 1024**2 if mode == "rss" else None)),
            cancellation=ReadyCancellation())
        assert (tmp_path / "ready").exists(), result
        assert result.workspace_cleaned and result.process_tree_terminated, result
        assert not result.error, result
        assert result.elapsed_seconds < 3, result
        if mode == "cancel":
            assert result.cancelled and not result.ok
        elif mode == "timeout":
            assert result.timed_out and not result.ok
        elif mode == "rss":
            assert result.resource_exhausted and not result.ok
        else:
            assert result.returncode == 0 and result.ok
        for name in ("middle.json", "leaf.json"):
            record = json.loads((tmp_path / name).read_text())
            found = _identity(record["pid"])
            assert found is None or found[0] != record["birth"] or found[1] == "Z", (name, record, result)
        assert not list((tmp_path / "workspaces").iterdir())
    finally:
        # A failed regression must not itself leave native work behind. Match
        # the recorded birth identity; never terminate a reused PID or a name.
        for name in ("middle.json", "leaf.json"):
            path = tmp_path / name
            if path.exists():
                record = json.loads(path.read_text())
                found = _identity(record["pid"])
                if found is not None and found[0] == record["birth"] and found[1] != "Z":
                    try:
                        os.kill(record["pid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass


def test_reused_pid_is_not_signalled_or_adopted(monkeypatch):
    tracker = module._LinuxDescendantTracker(111)
    tracker._seeded = True
    tracker.records[222] = (10, None)
    monkeypatch.setattr(module, "_linux_process_identity", lambda pid: (20, "S", 1, 0))
    signalled = []
    monkeypatch.setattr(module.os, "kill", lambda *args: signalled.append(args))
    assert not tracker.signal_descendants(signal.SIGKILL)
    assert tracker.records == {} and signalled == []


def test_pidfd_signal_uses_the_retained_handle(monkeypatch):
    tracker = module._LinuxDescendantTracker(111)
    tracker.records[222] = (10, 12345)
    monkeypatch.setattr(module, "_linux_process_identity", lambda pid: (10, "S", 1, 0))
    observed = []
    monkeypatch.setattr(module.signal, "pidfd_send_signal", lambda fd, number: observed.append((fd, number)), raising=False)
    monkeypatch.setattr(module.os, "kill", lambda *args: pytest.fail("pidfd was replaced with unchecked PID signalling"))
    assert tracker.signal_descendants(signal.SIGTERM)
    assert observed == [(12345, signal.SIGTERM)]


def test_surviving_tracked_descendant_refuses_successful_leader_result(tmp_path, monkeypatch):
    # Inject the OS boundary's inability to stop a known child without creating
    # an actual unkillable process. The real native leader completes normally.
    monkeypatch.setattr(module._LinuxDescendantTracker, "drain", lambda self, grace: (True, [999999]))
    result = module.BoundedToolRunner(workspace_root=tmp_path / "workspaces").run(
        module.ToolRunRequest(argv=(sys.executable, "-c", "print('leader finished')")))
    assert result.returncode == 0
    assert not result.ok and result.resource_exhausted
    assert "tracked descendants survived bounded cleanup" in result.error
    assert not result.process_tree_terminated


def test_tracker_closes_pidfds_after_success(tmp_path):
    before = {path.name for path in Path('/proc/self/fd').iterdir()}
    for _ in range(3):
        result = module.BoundedToolRunner(workspace_root=tmp_path / "workspaces").run(
            module.ToolRunRequest(argv=(sys.executable, "-c", "print('bounded')")))
        assert result.ok
    after = {path.name for path in Path('/proc/self/fd').iterdir()}
    assert after == before
