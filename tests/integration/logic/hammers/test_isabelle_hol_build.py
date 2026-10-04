"""Bounded persistent-heap mechanics with synthetic files, not HOL proofs."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import threading
import time

import pytest

from ipfs_datasets_py.logic.backends.installers import isabelle_hol_build as build
from ipfs_datasets_py.logic.backends.installers import isabelle as legacy
from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig


def heap(path, body):
    digest = hashlib.sha1(body).hexdigest()
    path.write_bytes(body + b"SHA1:" + digest.encode())
    return digest


def database(path, pure, hol, *, identifier="12345678-1234-5678-1234-567812345678"):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE isabelle_session_info(session_name TEXT PRIMARY KEY,sources TEXT,input_heaps TEXT,output_heap TEXT,uuid TEXT,return_code INTEGER)")
        db.execute("INSERT INTO isabelle_session_info VALUES(?,?,?,?,?,?)",
                   ("HOL", "fixed fixture sources", pure + " Pure\n", hol + " HOL\n", identifier, 0))


@pytest.fixture
def owner(tmp_path):
    healthy = ProofHostResources(16, 16384, 16384)
    telemetry = [healthy]
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "leases.json", proof_resource_sampler=lambda: telemetry[0],
        total_cpu_slots=6, total_memory_mb=8192, total_child_process_slots=16, lane_reservations={},
        proof_memory_headroom_mb=512, proof_backoff_seconds=.02, poll_interval_seconds=.01))
    yield scheduler, telemetry, healthy
    assert scheduler.snapshot()["active_lease_count"] == 0
    assert scheduler.snapshot()["waiting_request_count"] == 0


@pytest.fixture
def staged(tmp_path):
    owner = tmp_path / ".bounded-isabelle-fixture"
    owner.mkdir(mode=0o700)
    root = owner / "extracted" / legacy.ISABELLE_VERSION
    for directory in (root / "bin", root / "etc", root / "lib/scripts"):
        directory.mkdir(parents=True)
    (root / "etc/ISABELLE_IDENTIFIER").write_text(legacy.ISABELLE_VERSION)
    for name in ("etc/settings", "etc/components", "lib/scripts/getsettings"):
        (root / name).write_text("# synthetic fixture\n")
    directory = root / "heaps" / build._PLATFORMS[legacy.detect_platform_key()]
    (directory / "log").mkdir(parents=True)
    pure, hol = heap(directory / "Pure", b"fixture pure"), heap(directory / "HOL", b"old fixture hol")
    (directory / "log/Pure.db").write_bytes(b"immutable fixture Pure database")
    (directory / "log/Pure.gz").write_bytes(b"immutable fixture Pure log")
    (directory / "log/HOL.gz").write_bytes(b"old fixture HOL log")
    database(directory / "log/HOL.db", pure, hol)
    return root


def launcher(root, *, mode="success"):
    path = root / "bin/isabelle"
    path.write_text(f'''#!{Path(sys.executable).resolve()}
import hashlib, json, os, sqlite3, subprocess, sys, time
from pathlib import Path
root=Path(__file__).resolve().parent.parent
directory=root/'heaps'/{build._PLATFORMS[legacy.detect_platform_key()]!r}
assert sys.argv[1:]=={list(build.BUILD_ARGS)!r}
assert not (directory/'HOL').exists() and not (directory/'log/HOL.db').exists()
(root.parent.parent/'native.pid').write_text(str(os.getpid()))
mode={mode!r}
if mode=='guard_heap':
    os.mkfifo(directory/'unexpected-fifo')
    time.sleep(30)
elif mode=='guard_workspace':
    with (Path.cwd()/'large-temporary').open('wb') as f: f.truncate({build.MAX_WORKSPACE_BYTES+1})
    time.sleep(30)
elif mode=='sleep':
    time.sleep(30)
elif mode=='nested_session':
    grandchild_code="import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    child_code="import os,subprocess,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); subprocess.Popen([sys.executable,'-c',sys.argv[3],sys.argv[2]],start_new_session=True); time.sleep(30)"
    subprocess.Popen([sys.executable,'-c',child_code,str(root.parent.parent/'detached-child.pid'),
        str(root.parent.parent/'detached-grandchild.pid'),grandchild_code],start_new_session=True)
    time.sleep(30)
elif mode=='fail':
    sys.exit(2)
elif mode=='noop':
    sys.exit(0)
body=b'new fixture hol'
hol=hashlib.sha1(body).hexdigest()
(directory/'HOL').write_bytes(body+b'SHA1:'+hol.encode())
pure=(directory/'Pure').read_bytes()[-40:].decode()
with sqlite3.connect(directory/'log/HOL.db') as db:
    db.execute('CREATE TABLE isabelle_session_info(session_name TEXT PRIMARY KEY,sources TEXT,input_heaps TEXT,output_heap TEXT,uuid TEXT,return_code INTEGER)')
    db.execute('INSERT INTO isabelle_session_info VALUES(?,?,?,?,?,?)',('HOL','fixed fixture sources',pure+' Pure\\n',hol+' HOL\\n',
        '12345678-1234-5678-1234-567812345678' if mode=='old_uuid' else '87654321-4321-8765-4321-876543218765',0))
(directory/'log/HOL.gz').write_bytes(b'new fixture HOL log')
if mode=='pure_changed':
    (directory/'log/Pure.db').write_bytes(b'changed pure database')
print('Finished HOL synthetic process fixture')
''')
    path.chmod(0o755)


def run(owner, staged, *, mode="success", seconds=15, cancellation=None, on_progress=None):
    launcher(staged, mode=mode)
    deadline = time.monotonic() + seconds
    with owner[0].acquire("orchestration", cpu_slots=4, memory_mb=6400, child_process_slots=12) as parent:
        result = build.build_staged_hol(install_root=staged, parent_lease=parent, cancellation=cancellation,
            remaining=lambda: max(.001, deadline-time.monotonic()), on_progress=on_progress)
        assert not parent.released
        assert len(owner[0].active_leases()) == 1
    return result


def test_actual_bounded_fixture_build_then_rename_and_readonly_verification(owner, staged, tmp_path, monkeypatch):
    launches = []
    execute = process.SubprocessExecutor.execute
    def observe(self, invocation, cancellation=None):
        launches.append(invocation)
        rows = owner[0].active_leases()
        assert len(rows) == 2 and sum(not row.get("parent_lease_id") for row in rows) == 1
        return execute(self, invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", observe)
    result = run(owner, staged)
    assert result["build_succeeded"], result
    assert result["heap_after"]["session"]["uuid"] != result["heap_before"]["session"]["uuid"]
    assert result["heap_after"]["files"]["Pure"] == result["heap_before"]["files"]["Pure"]
    assert not result["persistent_heap_published"] and not result["grants_proof_authority"]
    assert launches[0].limits.resident_memory_bytes == 6144*1024**2
    assert "-Xmx2048m" in launches[0].environment["JDK_JAVA_OPTIONS"]
    assert result["limits"]["java_max_heap_mb"] == 2048
    assert result["limits"]["ml_max_heap_mb"] == 3072
    assert launches[0].limits.max_file_bytes == 4*1024**3
    assert launches[0].limits.max_workspace_bytes == 64*1024**2
    assert not Path(launches[0].cwd).exists()
    published = tmp_path / "published" / legacy.ISABELLE_VERSION
    published.parent.mkdir()
    staged.replace(published)
    before = build._heap_manifest(published, lambda: None)
    with owner[0].acquire("orchestration", cpu_slots=4, memory_mb=6400, child_process_slots=12) as parent:
        checked = build.verify_published_hol(install_root=published, expected_build=result,
            parent_lease=parent, cancellation=None, remaining=lambda: 10)
    assert checked["verified"], checked
    assert checked["heap_after"] == result["heap_after"] == before
    assert build._heap_manifest(published, lambda: None) == before
    assert launches[1].limits.resident_memory_bytes == 512*1024**2


@pytest.mark.parametrize("mode", ["fail", "noop", "old_uuid", "pure_changed"])
def test_native_exit_or_changed_dependency_cannot_claim_fresh_build(owner, staged, mode):
    result = run(owner, staged, mode=mode)
    assert not result["build_succeeded"] and result["status"] == "failed"
    assert not result["persistent_heap_published"]
    assert result["observation"]["workspace_cleaned"]


@pytest.mark.parametrize("mode", ["guard_heap", "guard_workspace"])
def test_live_disk_violation_cancels_outer_tree_retaining_observed_failure(owner, staged, mode):
    result = run(owner, staged, mode=mode)
    assert not result["build_succeeded"] and result["reason"] == "disk_guard_triggered", result
    assert result["heap_before"] and result["worker_receipt"]["command"]
    assert result["observation"]["cancelled"] and result["observation"]["process_tree_terminated"]
    assert result["observation"]["workspace_cleaned"]
    native_pid = int((staged.parent.parent / "native.pid").read_text())
    assert not Path(f"/proc/{native_pid}").exists()


@pytest.mark.parametrize("stop", ["timeout", "cancel"])
def test_live_build_timeout_and_cancellation_keep_observation_and_reap(owner, staged, stop):
    signal = threading.Event()
    timer = threading.Timer(.35, signal.set) if stop == "cancel" else None
    if timer:
        timer.start()
    try:
        result = run(owner, staged, mode="sleep", seconds=.5 if stop == "timeout" else 10, cancellation=signal)
    finally:
        if timer:
            timer.cancel()
            timer.join(1)
    assert not result["build_succeeded"]
    assert result["reason"] == ("cancelled" if stop == "cancel" else "deadline_exceeded"), result
    assert result["observation"]["workspace_cleaned"]
    if (staged.parent.parent / "native.pid").exists():
        pid = int((staged.parent.parent / "native.pid").read_text())
        assert not Path(f"/proc/{pid}").exists()


def test_pressure_before_native_child_admission_backs_off(owner, staged):
    timer = None
    started = []
    def progress(*_):
        nonlocal timer
        owner[1][0] = replace(owner[2], available_memory_mb=100)
        started.append(time.monotonic())
        timer = threading.Timer(.2, lambda: owner[1].__setitem__(0, owner[2]))
        timer.start()
    try:
        result = run(owner, staged, on_progress=progress)
    finally:
        if timer:
            timer.cancel()
            timer.join(1)
    assert result["build_succeeded"], result
    assert time.monotonic() - started[0] >= .19


def test_cancellation_reaps_native_descendants_with_separate_sessions(owner, staged):
    signal, ready, stop = threading.Event(), threading.Event(), threading.Event()
    stage = staged.parent.parent
    files = [stage / name for name in ("native.pid", "detached-child.pid", "detached-grandchild.pid")]
    births = {}
    def birth(pid):
        try:
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        except FileNotFoundError:
            return None
    def cancel_when_ready():
        deadline = time.monotonic() + 5
        while not stop.wait(.01) and time.monotonic() < deadline:
            if all(path.exists() and path.read_text().strip().isdigit() for path in files):
                for path in files:
                    pid = int(path.read_text())
                    births[pid] = birth(pid)
                ready.set()
                signal.set()
                return
    waiter = threading.Thread(target=cancel_when_ready)
    waiter.start()
    try:
        result = run(owner, staged, mode="nested_session", cancellation=signal)
        assert ready.is_set(), result
        assert result["reason"] == "cancelled", result
        assert result["observation"]["process_tree_terminated"]
        assert result["observation"]["workspace_cleaned"]
        for path in files:
            pid = int(path.read_text())
            assert not Path(f"/proc/{pid}").exists(), (path.name, pid)
    finally:
        stop.set()
        waiter.join(1)
        # Controlled fixture PIDs belong only to this test; a failed regression
        # must not itself leave known native fixture processes running.
        for path in files:
            if path.exists() and path.read_text().strip().isdigit():
                try:
                    pid = int(path.read_text())
                    if births.get(pid) is not None and birth(pid) == births[pid]:
                        os.kill(pid, 9)
                except ProcessLookupError:
                    pass


@pytest.mark.parametrize("cpu,ram,processes", [(3,6400,12),(4,6144,12),(4,6400,11)])
def test_underfunded_parent_refused_before_staged_heap_mutation(owner, staged, cpu, ram, processes):
    launcher(staged)
    before = build._heap_manifest(staged, lambda: None)
    with owner[0].acquire("orchestration", cpu_slots=cpu, memory_mb=ram, child_process_slots=processes) as parent:
        with pytest.raises(ValueError, match="underfunded"):
            build.build_staged_hol(install_root=staged, parent_lease=parent, cancellation=None, remaining=lambda: 10)
    assert build._heap_manifest(staged, lambda: None) == before


def test_build_refuses_published_runtime_layout(owner, staged, tmp_path):
    published = tmp_path / legacy.ISABELLE_VERSION
    staged.replace(published)
    with owner[0].acquire("orchestration", cpu_slots=4, memory_mb=6400, child_process_slots=12) as parent:
        with pytest.raises(ValueError, match="staging"):
            build.build_staged_hol(install_root=published, parent_lease=parent, cancellation=None, remaining=lambda: 10)


@pytest.mark.parametrize("kind", ["symlink", "fifo", "bytes", "nodes", "depth", "free"])
def test_disk_guard_bounds_and_unknown_types(tmp_path, monkeypatch, kind):
    tree = tmp_path / "tree"
    tree.mkdir()
    options = {}
    if kind == "symlink":
        (tree / "link").symlink_to(tmp_path)
    elif kind == "fifo":
        os.mkfifo(tree / "pipe")
    elif kind == "bytes":
        (tree / "large").write_bytes(b"x" * 33)
    elif kind == "nodes":
        (tree / "a").touch()
        (tree / "b").touch()
        options["max_nodes"] = 1
    elif kind == "depth":
        (tree / "a/b").mkdir(parents=True)
        options["max_depth"] = 1
    else:
        empty = type(shutil.disk_usage(tmp_path))(0, 0, 0)
        monkeypatch.setattr(shutil, "disk_usage", lambda _: empty)
    with pytest.raises(ValueError):
        build._scan(tree, 32, lambda: None, **options)


def test_heap_digest_verifies_full_body_not_only_declared_trailer(tmp_path):
    path = tmp_path / "HOL"
    heap(path, b"good")
    path.write_bytes(b"evil" + path.read_bytes()[4:])
    with pytest.raises(ValueError, match="trailer"):
        build._digest_file(path, lambda: None, heap=True)


def test_sql_metadata_size_preflight_refuses_oversized_source_before_fetch(staged):
    path = staged / "heaps" / build._PLATFORMS[legacy.detect_platform_key()] / "log/HOL.db"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE isabelle_session_info SET sources=?", ("x" * (256*1024+1),))
    with pytest.raises(ValueError, match="bounded HOL build metadata"):
        build._session_metadata(path, lambda: None)


def test_published_verifier_refuses_modified_heap_after_rename(owner, staged, tmp_path):
    result = run(owner, staged)
    assert result["build_succeeded"], result
    published = tmp_path / "published" / legacy.ISABELLE_VERSION
    published.parent.mkdir()
    staged.replace(published)
    directory = published / "heaps" / result["heap_after"]["ml_identifier"]
    heap(directory / "HOL", b"different heap with valid self digest")
    with owner[0].acquire("orchestration", cpu_slots=4, memory_mb=6400, child_process_slots=12) as parent:
        checked = build.verify_published_hol(install_root=published, expected_build=result,
            parent_lease=parent, cancellation=None, remaining=lambda: 10)
    assert not checked["verified"] and not checked["build_succeeded"]


@pytest.mark.parametrize("memory,java,ml", [(2048,682,342),(4096,1365,1707),(6144,2048,3072),(8192,2048,5120)])
def test_private_build_settings_bound_threads_and_heap(memory, java, ml):
    value = build._settings(memory)
    assert f"--maxheap {ml} --gcthreads 1" in value
    assert java + ml + 1024 == memory
    assert "ActiveProcessorCount=1" in value and f"-Xmx{java}m" in value
    assert f"-Xmx{java}m" in build._java_options(memory)
    assert "UseSerialGC" in build._java_options(memory)
    assert "threads=2" in build.BUILD_ARGS
    assert "-f" not in build.BUILD_ARGS and "-c" not in build.BUILD_ARGS
