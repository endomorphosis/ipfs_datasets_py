"""Frozen source bytes and namespace admission must fail closed."""
import hashlib
import io
import json
import os
import fcntl
import signal
import subprocess
import sys
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_snapshot as source


@pytest.fixture
def tree(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    root = workspace / "external/ipfs_datasets"
    package = root / "ipfs_datasets_py"
    scripts = root / "scripts/ops/legal_ir"
    jevops = workspace / "JevOps/jevops"
    for path in (package, scripts, jevops):
        path.mkdir(parents=True)
        (path / "__init__.py").write_text("VALUE = 1\n")
    (package / "data.json").write_text('{"resource": true}\n')
    (package / "__pycache__").mkdir()
    (package / "__pycache__/stale.pyc").write_bytes(b"stale")
    (package / "stray.pyc").write_bytes(b"stale")
    (jevops / "statement_lock.py").write_text("LOCK = 'unchanged'\n")
    (jevops / "autoformal_tools.py").write_text("TOOLS = []\n")
    # Real current runtime bytes; placeholder __init__ code must not certify
    # compatibility with a policy-aware launcher.
    for relative, actual in source._runtime_producers(Path(source.__file__).absolute().parents[3]).items():
        destination = source._runtime_producers(root)[relative]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(actual.read_bytes())
    monkeypatch.setattr(source, "canonical_root", lambda: root)
    monkeypatch.setattr(source, "_git", lambda root: {"head": "a" * 40, "dirty": "fixture"})
    capsule = workspace / "capsule"
    capsule.mkdir()
    return root, capsule


def capture(tree, **kwargs):
    root, capsule = tree
    receipt = source.capture_snapshot(root, capsule, **kwargs)
    return receipt, source.verify_snapshot(receipt["path"], receipt["sha256"])


def test_frozen_source_survives_live_edits_and_preserves_resources(tree):
    receipt, manifest = capture(tree)
    root, capsule = tree
    (root / "ipfs_datasets_py/__init__.py").write_text("VALUE = 2\n")
    verified = source.verify_snapshot(receipt["path"], receipt["sha256"])
    assert verified == manifest
    assert (capsule / "sources/package/__init__.py").read_text() == "VALUE = 1\n"
    assert (capsule / "sources/package/data.json").read_text() == '{"resource": true}\n'
    assert not list(capsule.rglob("*.pyc"))
    assert all(path.stat().st_nlink == 1 for path in capsule.rglob("*") if path.is_file())
    assert receipt["admitted"] is manifest["admitted"] is False


@pytest.mark.parametrize("kind", ["file_symlink", "directory_symlink", "hardlink", "weights"])
def test_unsafe_sources_are_rejected(tree, kind):
    root, capsule = tree
    package = root / "ipfs_datasets_py"
    if kind == "file_symlink":
        (package / "alias.py").symlink_to("__init__.py")
    elif kind == "directory_symlink":
        (package / "alias").symlink_to(package)
    elif kind == "hardlink":
        os.link(package / "__init__.py", package / "duplicate.py")
    else:
        (package / "model.safetensors").write_bytes(b"do not copy weights")
    with pytest.raises(source.SourceSnapshotError):
        source.capture_snapshot(root, capsule)
    assert not (capsule / "manifest.json").exists()


def font_alias(tree):
    root, _ = tree
    package = root / "ipfs_datasets_py"
    (package / "static/admin").mkdir(parents=True)
    fonts = package / "static/webfonts"
    fonts.mkdir()
    (fonts / "example.woff2").write_bytes(b"font bytes")
    (package / source.FONT_ALIAS).symlink_to("../webfonts")
    return fonts


def test_only_recorded_font_alias_is_materialized_without_aliases(tree):
    font_alias(tree)
    receipt, data = capture(tree)
    assert data["inventory"]["materialized_font_aliases"][0]["target"] == "../webfonts"
    assert (tree[1] / "sources/package/static/admin/webfonts/example.woff2").read_bytes() == b"font bytes"
    assert not any(path.is_symlink() for path in tree[1].rglob("*"))
    assert source.verify_snapshot(receipt["path"], receipt["sha256"]) == data


@pytest.mark.parametrize("bad", ["python", "executable", "nested_alias", "outside"])
def test_font_alias_cannot_smuggle_code_or_external_paths(tree, bad):
    fonts = font_alias(tree)
    if bad == "python":
        (fonts / "code.py").write_text("pass\n")
    elif bad == "executable":
        (fonts / "example.woff2").chmod(0o755)
    elif bad == "nested_alias":
        (fonts / "alias.woff2").symlink_to("example.woff2")
    else:
        alias = tree[0] / "ipfs_datasets_py" / source.FONT_ALIAS
        alias.unlink()
        alias.symlink_to(fonts.absolute())
    with pytest.raises(source.SourceSnapshotError):
        source.capture_snapshot(*tree)


def test_byte_cap_fails_before_manifest(tree):
    with pytest.raises(source.SourceSnapshotError, match="ceiling"):
        source.capture_snapshot(*tree, max_bytes=2)
    assert not (tree[1] / "manifest.json").exists()


def test_edit_during_copy_retains_partial_capsule_and_refuses_manifest(tree, monkeypatch):
    original = source._inventory
    calls = []
    def inventory(*args):
        calls.append(None)
        if len(calls) == 2:
            (tree[0] / "ipfs_datasets_py/data.json").write_text("changed\n")
        return original(*args)
    monkeypatch.setattr(source, "_inventory", inventory)
    with pytest.raises(source.SourceSnapshotError, match="changed"):
        source.capture_snapshot(*tree)
    assert (tree[1] / "sources/package/data.json").exists()
    assert not (tree[1] / "manifest.json").exists()


@pytest.mark.parametrize("change", ["bytes", "extra", "missing", "hardlink", "symlink", "manifest"])
def test_capsule_tampering_is_rejected(tree, change):
    receipt, _ = capture(tree)
    root = tree[1]
    package = root / "sources/package"
    package.chmod(0o755)
    target = package / "data.json"
    if change == "bytes":
        target.chmod(0o644)
        target.write_text("changed")
    elif change == "extra":
        (package / "unlisted.py").write_text("pass")
    elif change == "missing":
        target.unlink()
    elif change == "hardlink":
        os.link(target, package / "alias")
    elif change == "symlink":
        target.unlink()
        target.symlink_to(tree[0] / "ipfs_datasets_py/data.json")
    else:
        path = Path(receipt["path"])
        path.chmod(0o644)
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(source.SourceSnapshotError):
        source.verify_snapshot(receipt["path"], receipt["sha256"])


def test_extra_harness_is_frozen_with_exact_absolute_path(tree):
    harness = tree[0].parents[1] / "harness.py"
    harness.write_text("print('fixture')\n")
    _, data = capture(tree, extra_files=[harness])
    assert data["bindings"][-1]["source"] == str(harness)
    assert (tree[1] / "sources/extra-0").read_text() == harness.read_text()


def test_snapshot_verification_does_not_depend_on_deleted_live_harness(tree):
    harness = tree[0].parents[1] / "harness.py"
    harness.write_text("print('fixture')\n")
    receipt, _ = capture(tree, extra_files=[harness])
    harness.unlink()
    assert source.verify_snapshot(receipt["path"], receipt["sha256"])["bindings"][-1]["source"] == str(harness)


def test_writable_harness_output_parent_keeps_captured_file_binding(tree):
    parent = tree[0].parents[1] / "harness-output"
    parent.mkdir()
    harness = parent / "harness.py"
    harness.write_text("print('fixture')\n")
    _, data = capture(tree, extra_files=[harness])
    assert source._runtime_paths(data, [parent]) == [parent]
    assert data["bindings"][-1] == {"source": str(harness), "snapshot": "sources/extra-0", "kind": "file"}


def test_extra_harness_must_not_overlap_package(tree):
    with pytest.raises(source.SourceSnapshotError, match="overlap"):
        source.capture_snapshot(*tree, extra_files=[tree[0] / "ipfs_datasets_py/__init__.py"])


@pytest.mark.parametrize("value", [None, "", "0" * 63, "X" * 64])
def test_expected_manifest_hash_is_required(tree, value):
    receipt, _ = capture(tree)
    with pytest.raises(source.SourceSnapshotError, match="SHA256"):
        source.verify_snapshot(receipt["path"], value)


def test_environment_is_absent_or_fails_closed(tree, monkeypatch):
    monkeypatch.delenv(source.MANIFEST_ENV, raising=False)
    monkeypatch.delenv(source.DIGEST_ENV, raising=False)
    assert source.verify_frozen_runtime_from_environment() is None
    monkeypatch.setenv(source.MANIFEST_ENV, "unused")
    with pytest.raises(source.SourceSnapshotError, match="partial"):
        source.verify_frozen_runtime_from_environment()
    receipt, _ = capture(tree)
    monkeypatch.setenv(source.MANIFEST_ENV, receipt["path"])
    monkeypatch.setenv(source.DIGEST_ENV, receipt["sha256"])
    with pytest.raises(source.SourceSnapshotError, match="mount missing"):
        source.verify_frozen_runtime_from_environment()


@pytest.mark.parametrize("fault", ["backing_rw", "source_rw", "wrong_backing", "nested_rw", "changed_source"])
def test_frozen_environment_checks_actual_mounts_and_canonical_bytes(tree, monkeypatch, fault):
    receipt, data = capture(tree)
    monkeypatch.setenv(source.MANIFEST_ENV, receipt["path"])
    monkeypatch.setenv(source.DIGEST_ENV, receipt["sha256"])
    mounts = {data["capsule"]: {"root": data["capsule"], "options": ["ro"]}}
    for row in data["bindings"]:
        mounts[row["source"]] = {"root": str(tree[1] / row["snapshot"]), "options": ["ro"]}
    if fault == "backing_rw":
        mounts[data["capsule"]]["options"] = ["rw"]
    elif fault == "source_rw":
        mounts[data["bindings"][0]["source"]]["options"] = ["rw"]
    elif fault == "wrong_backing":
        mounts[data["capsule"]]["root"] = "/other"
    elif fault == "nested_rw":
        mounts[data["bindings"][0]["source"] + "/subdir"] = {"root": "/unrelated", "options": ["rw"]}
    else:
        (tree[0] / "ipfs_datasets_py/data.json").write_text("changed")
    monkeypatch.setattr(source, "_mounts", lambda: mounts)
    with pytest.raises(source.SourceSnapshotError):
        source.verify_frozen_runtime_from_environment()


def test_verified_frozen_environment_returns_content_identity_not_admission(tree, monkeypatch):
    receipt, data = capture(tree)
    monkeypatch.setenv(source.MANIFEST_ENV, receipt["path"])
    monkeypatch.setenv(source.DIGEST_ENV, receipt["sha256"])
    mounts = {data["capsule"]: {"root": data["capsule"], "options": ["ro"]}}
    for row in data["bindings"]:
        mounts[row["source"]] = {"root": str(tree[1] / row["snapshot"]), "options": ["ro"]}
    monkeypatch.setattr(source, "_mounts", lambda: mounts)
    result = source.verify_frozen_runtime_from_environment()
    assert result["sha256"] == receipt["sha256"] and result["admitted"] is False


@pytest.mark.parametrize("bad", ["capsule", "source", "workspace", "root", "nested"])
def test_runtime_cannot_make_source_writable(tree, bad):
    _, data = capture(tree)
    paths = {"capsule": [tree[1]], "source": [tree[0] / "ipfs_datasets_py"],
             "workspace": [tree[0].parents[1]], "root": [Path("/")],
             "nested": [tree[0].parents[1] / "runtime", tree[0].parents[1] / "runtime/child"]}[bad]
    for path in paths:
        path.mkdir(exist_ok=True, parents=True)
    with pytest.raises(source.SourceSnapshotError):
        source._runtime_paths(data, paths)


def test_runtime_allows_owned_output_but_not_parent_covering_a_test_capsule(tree):
    _, data = capture(tree)
    output = tree[0].parents[1] / "runtime"
    output.mkdir()
    assert source._runtime_paths(data, [output]) == [output]
    with pytest.raises(source.SourceSnapshotError, match="overlaps frozen"):
        source._runtime_paths(data, [tree[1].parent])


def test_host_and_container_pid_must_match():
    row = {"pid": 10, "parent_pid": 9, "group_pid": 10, "birth": "a"}
    source._check_process_pair(row, row)
    with pytest.raises(source.SourceSnapshotError, match="identities"):
        source._check_process_pair(row, {**row, "pid": 11})


def test_host_sigterm_enters_cleanup_and_restores_handler():
    previous = signal.getsignal(signal.SIGTERM)
    events = []
    with pytest.raises(KeyboardInterrupt, match="owned launcher"):
        with source._host_interruptions():
            try:
                os.kill(os.getpid(), signal.SIGTERM)
            finally:
                events.append("cleanup")
    assert events == ["cleanup"]
    assert signal.getsignal(signal.SIGTERM) == previous


def test_host_owner_presence_checks_birth_identity():
    actual = source._process(os.getpid())
    assert source._host_owner_alive(actual)
    assert not source._host_owner_alive({**actual, "birth": "wrong"})
    assert not source._host_owner_alive({**actual, "pid": 999999999})


def test_control_observation_locks_block_atomic_writers_then_release(tmp_path):
    lock = tmp_path / "state.lock"
    lock.write_bytes(b"")
    with lock.open("rb") as writer:
        with source._control_observation_locks([str(lock)]):
            with pytest.raises(BlockingIOError):
                fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(writer, fcntl.LOCK_UN)


@pytest.mark.parametrize("fault", ["missing", "readonly", "executable", "not_tmpfs", "host_mount", "oversize"])
def test_private_shared_memory_refuses_unsafe_mounts(monkeypatch, fault):
    mount = {"root": "/", "filesystem": "tmpfs", "options": ["rw", "noexec", "nosuid", "nodev"]}
    host = {"path": "/dev/shm", "device": 1, "inode": 1}
    observed = {**host, "device": 2}
    size = source.SHARED_MEMORY_BYTES
    if fault == "readonly":
        mount["options"] = ["ro", "noexec", "nosuid", "nodev"]
    elif fault == "executable":
        mount["options"].remove("noexec")
    elif fault == "not_tmpfs":
        mount["filesystem"] = "ext4"
    elif fault == "host_mount":
        observed = host
    elif fault == "oversize":
        size *= 2
    monkeypatch.setattr(source, "_mounts", lambda: {} if fault == "missing" else {"/dev/shm": mount})
    monkeypatch.setattr(source, "_identity", lambda path: observed)
    monkeypatch.setattr(source.os, "statvfs", lambda path: SimpleNamespace(f_frsize=1, f_blocks=size))
    with pytest.raises(source.SourceSnapshotError):
        source._private_shared_memory(host)


def test_private_shared_memory_has_explicit_wrapper_memory_charge(monkeypatch):
    mount = {"root": "/", "filesystem": "tmpfs", "options": ["rw", "noexec", "nosuid", "nodev"]}
    monkeypatch.setattr(source, "_mounts", lambda: {"/dev/shm": mount})
    monkeypatch.setattr(source, "_identity", lambda path: {"path": path, "device": 2, "inode": 1})
    monkeypatch.setattr(source.os, "statvfs", lambda path: SimpleNamespace(f_frsize=4096, f_blocks=16384))
    result = source._private_shared_memory({"device": 1, "inode": 1})
    assert result["bytes"] == 64 * 1024 * 1024
    assert result["charged_to"] == "wrapper_memory_mb=1024" and result["admitted"] is False


def test_real_spawn_queue_lock_roundtrip_reaps_child():
    result = source._spawn_semaphore_probe()
    assert result["start_method"] == "spawn"
    assert result["queue_roundtrip"] is result["lock_roundtrip"] is True
    assert result["child_exitcode"] == 0 and result["admitted"] is False
    assert not Path("/proc", str(result["child_pid"])).exists()


@pytest.mark.parametrize("fail", [False, True])
def test_preparation_reserves_before_capture_releases_success_and_retains_failure(tree, monkeypatch, fail):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as leases
    root, _ = tree
    workspace = root.parents[1]
    ledger = workspace / "ledger.json"
    ledger.write_text(json.dumps({"roots": [{"path": str(workspace)}]}))
    events = []
    scheduler = workspace / "existing-state.json"
    scheduler.write_text("{}")
    policy = "a" * 64
    monkeypatch.setattr(source, "_existing_scheduler_binding", lambda path, digest: (path, digest))
    class Owner:
        reservation_id = "fixture-owned-reservation"
        def __init__(self, *args, **kwargs):
            assert kwargs["storage_bytes"] == 1_000_000_000
            assert kwargs["scheduler_state_path"] == scheduler
            assert kwargs["expected_scheduler_policy_sha256"] == policy
            assert kwargs["require_existing_ledger"] is True
            self.released = False
        def __enter__(self):
            events.append("reserved")
            return self
        def check_usage(self, path):
            events.append("usage")
        def finalize(self, path, artifacts_durable=False):
            assert artifacts_durable and (path / "capture.json").is_file()
            self.released = True
            events.append("released")
            return {"status": "released"}
        def __exit__(self, *args):
            if not self.released:
                events.append("retained")
    @contextmanager
    def lease(root, **kwargs):
        assert kwargs["mode"] == "read" and events[0] == "reserved"
        events.append("lease")
        yield SimpleNamespace(to_dict=lambda: {"mode": "read"})
    monkeypatch.setattr(resources, "DaemonResourceReservation", Owner)
    monkeypatch.setattr(leases, "source_lease", lease)
    attempt = workspace / "attempt"
    if fail:
        (root / "ipfs_datasets_py/alias.py").symlink_to("__init__.py")
        with pytest.raises(source.SourceSnapshotError):
            source.prepare_snapshot(attempt, resource_ledger=ledger,
                scheduler_state_path=scheduler, expected_scheduler_policy_sha256=policy)
        assert "released" not in events and events[-1] == "retained"
        assert (attempt / "failure.json").is_file()
    else:
        result = source.prepare_snapshot(attempt, resource_ledger=ledger,
                scheduler_state_path=scheduler, expected_scheduler_policy_sha256=policy)
        assert events[-1] == "released" and result["resource_reservation_id"] == Owner.reservation_id
        assert (attempt / "resources.json").is_file()


def test_exact_scheduler_binding_uses_existing_facade_without_global_fallback(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    state = tmp_path / "native-state.json"
    state.write_text("{}")
    policy = "b" * 64
    calls = []
    def open_existing(path, digest):
        calls.append((path, digest))
        return SimpleNamespace(state_path=state)
    def forbidden(*args, **kwargs):
        pytest.fail("implicit global scheduler must not be used")
    monkeypatch.setattr(existing, "open_existing_scheduler", open_existing)
    monkeypatch.setattr(resources, "get_global_resource_scheduler", forbidden)
    assert source._existing_scheduler_binding(state, policy) == (state, policy)
    assert calls == [(state, policy)]


def test_scheduler_binding_refuses_alias_before_opening_control(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
    actual = tmp_path / "native-state.json"
    actual.write_text("{}")
    alias = tmp_path / "alias.json"
    alias.symlink_to(actual)
    monkeypatch.setattr(existing, "open_existing_scheduler", lambda *args: pytest.fail("aliased state reached facade"))
    with pytest.raises(source.SourceSnapshotError, match="aliased"):
        source._existing_scheduler_binding(alias, "b" * 64)


def test_scheduler_binding_refuses_a_facade_for_another_path(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
    state = tmp_path / "native-state.json"
    state.write_text("{}")
    monkeypatch.setattr(existing, "open_existing_scheduler", lambda *args: SimpleNamespace(state_path=tmp_path / "other.json"))
    with pytest.raises(source.SourceSnapshotError, match="path differs"):
        source._existing_scheduler_binding(state, "b" * 64)


@pytest.mark.parametrize("operation", ["prepare", "run"])
def test_wrong_existing_policy_refuses_before_reservation_or_output(tmp_path, monkeypatch, operation):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    state = tmp_path / "native-state.json"
    state.write_text("{}")
    attempt = tmp_path / "no-output"
    def reject(*args):
        raise existing.ExistingResourceSchedulerError("exact stored native policy required")
    monkeypatch.setattr(existing, "open_existing_scheduler", reject)
    monkeypatch.setattr(resources, "DaemonResourceReservation", lambda *args, **kwargs: pytest.fail("policy refusal created a reservation"))
    kwargs = dict(resource_ledger=tmp_path / "ledger.json", scheduler_state_path=state,
                  expected_scheduler_policy_sha256="c" * 64)
    with pytest.raises(existing.ExistingResourceSchedulerError, match="exact stored"):
        if operation == "prepare":
            source.prepare_snapshot(attempt, **kwargs)
        else:
            source.run_snapshot(tmp_path / "manifest.json", "d" * 64,
                run_directory=attempt, writable_directories=[tmp_path], argv=["/usr/bin/true"],
                timeout_seconds=1, tmp_directory=tmp_path, **kwargs)
    assert not attempt.exists()


def test_run_wrapper_passes_exact_existing_policy_to_owner_and_entry(tree, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    root, _ = tree
    workspace = root.parents[1]
    ledger = workspace / "ledger.json"
    ledger.write_text(json.dumps({"roots": [{"path": str(workspace)}]}))
    state = workspace / "native-state.json"
    state.write_text("{}")
    policy = "e" * 64
    receipt, _ = capture(tree)
    events = []
    monkeypatch.setattr(source, "_existing_scheduler_binding", lambda path, digest: (path, digest))
    class Owner:
        reservation_id = "fixture-run-owner"
        def __init__(self, *args, **kwargs):
            assert kwargs["scheduler_state_path"] == state
            assert kwargs["expected_scheduler_policy_sha256"] == policy
            assert kwargs["require_existing_ledger"] is True
            assert kwargs["cpu_slots"] == 1 and kwargs["memory_mb"] == 1024
            assert kwargs["child_process_slots"] == 4
        def __enter__(self):
            events.append("reserved")
            return self
        def __exit__(self, *args):
            events.append("exit")
        def finalize(self, path, artifacts_durable=False):
            assert artifacts_durable and path.is_dir()
            events.append("released")
            return {"status": "released"}
    def run(*args, **kwargs):
        assert isinstance(kwargs["owner"], Owner)
        assert kwargs["scheduler_state_path"] == state
        assert kwargs["expected_scheduler_policy_sha256"] == policy
        Path(kwargs["run_directory"]).mkdir()
        events.append("run")
        return {"admitted": False}
    monkeypatch.setattr(resources, "DaemonResourceReservation", Owner)
    monkeypatch.setattr(source, "_run_snapshot", run)
    attempt = workspace / "run"
    assert source.run_snapshot(receipt["path"], receipt["sha256"],
        run_directory=attempt, writable_directories=[workspace], resource_ledger=ledger,
        scheduler_state_path=state, expected_scheduler_policy_sha256=policy,
        argv=["/usr/bin/true"], timeout_seconds=1, tmp_directory=workspace) == {"admitted": False}
    assert events == ["reserved", "run", "released", "exit"]
    assert json.loads((attempt / "resources.json").read_text()) == {"status": "released"}


def test_container_wrong_policy_refuses_before_spawn_probe(tmp_path, monkeypatch):
    config = dict(runtime_protocol=source.RUNTIME_PROTOCOL,
                  manifest_sha256="a" * 64, python_prefix=source.sys.prefix,
                  home=str(Path.home()), scheduler_path=str(tmp_path / "native-state.json"),
                  expected_scheduler_policy_sha256="b" * 64)
    raw = source._json(config)
    path = tmp_path / "configuration.json"
    path.write_bytes(raw)
    monkeypatch.setenv(source.SCHEDULER_ENV, config["scheduler_path"])
    monkeypatch.setattr(source, "verify_frozen_runtime_from_environment", lambda: {"sha256": config["manifest_sha256"]})
    monkeypatch.setattr(source, "signal", SimpleNamespace(signal=lambda *args: None, SIGTERM=signal.SIGTERM, SIGINT=signal.SIGINT))
    def reject(*args):
        raise source.SourceSnapshotError("wrong selected policy")
    monkeypatch.setattr(source, "_existing_scheduler_binding", reject)
    monkeypatch.setattr(source, "_spawn_semaphore_probe", lambda: pytest.fail("policy refusal spawned a child"))
    monkeypatch.setattr(source, "_private_shared_memory", lambda *args: pytest.fail("policy refusal progressed to shared memory"))
    with pytest.raises(source.SourceSnapshotError, match="wrong selected policy"):
        source._container_entry(path, hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("operation", ["prepare", "run"])
@pytest.mark.parametrize("provided", ["none", "path_only", "policy_only"])
def test_cli_requires_explicit_existing_scheduler_binding(operation, provided, tmp_path):
    cli = Path(source.__file__).absolute().parents[3] / "scripts/ops/legal_ir/run_frozen_autoencoder_source.py"
    args = [sys.executable, "-B", str(cli), operation, "--resource-ledger", str(tmp_path / "ledger")]
    if operation == "prepare":
        args += ["--output-directory", str(tmp_path / "attempt")]
    else:
        args += ["--manifest", str(tmp_path / "manifest"), "--sha256", "a" * 64,
                 "--run-directory", str(tmp_path / "attempt"), "--writable-directory", str(tmp_path),
                 "--tmp-directory", str(tmp_path), "--timeout-seconds", "1"]
    if provided == "path_only":
        args += ["--scheduler-state-path", str(tmp_path / "native-state.json")]
    elif provided == "policy_only":
        args += ["--expected-scheduler-policy-sha256", "b" * 64]
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=5)
    assert result.returncode == 2
    if provided != "path_only":
        assert "--scheduler-state-path" in result.stderr
    if provided != "policy_only":
        assert "--expected-scheduler-policy-sha256" in result.stderr
    assert not (tmp_path / "attempt").exists()


def test_real_private_existing_policy_is_read_only_and_wrong_digest_refuses(tmp_path, monkeypatch):
    """Real private native metadata only; no grant or shared host state."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    state = tmp_path / "private-native-state.json"
    native.GlobalResourceScheduler(native.ResourceSchedulerConfig(
        state_path=state, total_cpu_slots=2, total_memory_mb=2048,
        total_child_process_slots=4, lane_reservations={"validation": 1},
        proof_safety_enabled=True, auto_renew_leases=False))
    before = state.read_bytes()
    digest = existing.policy_sha256(json.loads(before)["config"])
    monkeypatch.setattr(resources, "get_global_resource_scheduler",
        lambda *args, **kwargs: pytest.fail("private binding tried shared global facade"))
    assert source._existing_scheduler_binding(state, digest) == (state, digest)
    wrong = ("0" if digest[0] != "0" else "1") + digest[1:]
    with pytest.raises(existing.ExistingResourceSchedulerError, match="exact stored"):
        source._existing_scheduler_binding(state, wrong)
    assert state.read_bytes() == before
    observed = json.loads(before)
    assert observed["leases"] == {} and observed["waiters"] == {}


def rewritten_manifest(receipt, data):
    """Produce a separately hashed legacy/tampered test artifact, never retag a run."""
    path = Path(receipt["path"])
    path.chmod(0o644)
    raw = source._json(data) + b"\n"
    path.write_bytes(raw)
    return str(path), hashlib.sha256(raw).hexdigest()


def test_new_capture_binds_actual_runtime_producers(tree):
    receipt, data = capture(tree)
    assert data["runtime_contract"] == source._current_runtime_contract()
    assert source._require_runtime_contract(data) == data["runtime_contract"]
    assert len(data["runtime_contract"]["producers"]) == 2
    assert source.verify_snapshot(receipt["path"], receipt["sha256"])["admitted"] is False


@pytest.mark.parametrize("legacy", ["missing", "old_protocol"])
def test_legacy_capsule_remains_verifiable_but_refuses_before_run_claim(tree, monkeypatch, legacy):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    receipt, data = capture(tree)
    if legacy == "missing":
        del data["runtime_contract"]
    else:
        data["runtime_contract"]["protocol"] = "autoencoder-frozen-source-run/v1"
    manifest, digest = rewritten_manifest(receipt, data)
    assert source.verify_snapshot(manifest, digest) == data
    monkeypatch.setattr(source, "_existing_scheduler_binding", lambda *args: (Path("/fixture-state"), "a" * 64))
    monkeypatch.setattr(resources, "DaemonResourceReservation",
                        lambda *a, **kw: pytest.fail("legacy capsule created a native run claim"))
    monkeypatch.setattr(source.subprocess, "Popen", lambda *a, **kw: pytest.fail("legacy capsule spawned Docker"))
    attempt = tree[0].parents[1] / "no-run"
    with pytest.raises(source.SourceSnapshotError, match="incompatible frozen runtime"):
        source.run_snapshot(manifest, digest, run_directory=attempt,
            writable_directories=[attempt.parent], resource_ledger=attempt.parent / "unused-ledger",
            scheduler_state_path="/fixture-state", expected_scheduler_policy_sha256="a" * 64,
            argv=["/usr/bin/true"], timeout_seconds=1, tmp_directory=attempt.parent)
    assert not attempt.exists()


@pytest.mark.parametrize("relative", [
    "sources/package/optimizers/logic_theorem_optimizer/autoencoder_source_snapshot.py",
    "sources/scripts/run_frozen_autoencoder_source.py",
])
def test_new_protocol_label_cannot_certify_older_runtime_bytes(tree, monkeypatch, relative):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    receipt, data = capture(tree)
    target = tree[1] / relative
    target.chmod(0o644)
    old_size = target.stat().st_size
    raw = b"# older runtime without explicit policy handshake\n"
    target.write_bytes(raw)
    row = next(row for row in data["inventory"]["entries"] if row["snapshot"] == relative)
    row.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    data["inventory"]["bytes"] += len(raw) - old_size
    # Even a fresh-looking declaration with internally consistent old bytes
    # must not be accepted by the current host runtime.
    data["runtime_contract"]["producers"][relative].update(bytes=len(raw), sha256=row["sha256"])
    manifest, digest = rewritten_manifest(receipt, data)
    assert source.verify_snapshot(manifest, digest) == data
    monkeypatch.setattr(source, "_existing_scheduler_binding", lambda *args: (Path("/fixture-state"), "a" * 64))
    monkeypatch.setattr(resources, "DaemonResourceReservation",
                        lambda *a, **kw: pytest.fail("old runtime acquired a native claim"))
    attempt = tree[0].parents[1] / "no-run"
    with pytest.raises(source.SourceSnapshotError, match="incompatible frozen runtime"):
        source.run_snapshot(manifest, digest, run_directory=attempt, writable_directories=[attempt.parent],
            resource_ledger=attempt.parent / "unused-ledger", scheduler_state_path="/fixture-state",
            expected_scheduler_policy_sha256="a" * 64, argv=["/usr/bin/true"],
            timeout_seconds=1, tmp_directory=attempt.parent)
    assert not attempt.exists()


@pytest.mark.parametrize("fault", ["missing", "duplicate", "source", "snapshot", "bytes"])
def test_runtime_inventory_refuses_wrong_mapping_or_bytes(tree, fault):
    _, data = capture(tree)
    relative = next(iter(data["runtime_contract"]["producers"]))
    row = next(row for row in data["inventory"]["entries"] if row["snapshot"] == relative)
    if fault == "missing":
        data["inventory"]["entries"].remove(row)
    elif fault == "duplicate":
        data["inventory"]["entries"].append(dict(row))
    elif fault == "source":
        row["source"] = "/outside/capsule.py"
    elif fault == "snapshot":
        row["snapshot"] = "../../outside.py"
    else:
        target = tree[1] / relative
        target.chmod(0o644)
        target.write_bytes(b"changed")
    with pytest.raises(source.SourceSnapshotError, match="runtime producer"):
        source._require_runtime_contract(data)


@pytest.mark.parametrize("fault", ["old_preflight", "protocol", "path", "policy", "configuration"])
def test_host_requires_exact_runtime_policy_and_configuration_before_acknowledgment(fault):
    config = dict(runtime_protocol=source.RUNTIME_PROTOCOL, scheduler_path="/fixture/state.json",
                  expected_scheduler_policy_sha256="a" * 64)
    digest = "b" * 64
    preflight = dict(runtime_acknowledgment=source._runtime_acknowledgment(config),
                     configuration_sha256=digest)
    if fault == "old_preflight":
        del preflight["runtime_acknowledgment"]
    elif fault == "configuration":
        preflight["configuration_sha256"] = "c" * 64
    else:
        key = {"protocol": "protocol", "path": "scheduler_path", "policy": "expected_scheduler_policy_sha256"}[fault]
        preflight["runtime_acknowledgment"][key] = "different"
    with pytest.raises(source.SourceSnapshotError, match="acknowledgment"):
        source._require_preflight_acknowledgment(preflight, config, digest)


def test_exact_preflight_acknowledgment_is_accepted_without_admission():
    config = dict(runtime_protocol=source.RUNTIME_PROTOCOL, scheduler_path="/fixture/state.json",
                  expected_scheduler_policy_sha256="a" * 64)
    preflight = dict(runtime_acknowledgment=source._runtime_acknowledgment(config),
                     configuration_sha256="b" * 64)
    source._require_preflight_acknowledgment(preflight, config, "b" * 64)


def test_old_container_configuration_refuses_before_any_probe(tmp_path, monkeypatch):
    raw = source._json(dict(manifest_sha256="a" * 64, scheduler_path="/fixture/state.json",
                            expected_scheduler_policy_sha256="b" * 64))
    path = tmp_path / "configuration.json"
    path.write_bytes(raw)
    monkeypatch.setattr(source, "verify_frozen_runtime_from_environment",
                        lambda: pytest.fail("old configuration progressed to runtime mounts"))
    monkeypatch.setattr(source, "_spawn_semaphore_probe", lambda: pytest.fail("old configuration spawned a child"))
    with pytest.raises(source.SourceSnapshotError, match="unsupported runtime protocol"):
        source._container_entry(path, hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("fault", ["old_preflight", "policy", "configuration"])
def test_actual_host_run_refuses_bad_preflight_without_acknowledging_command(tree, monkeypatch, fault):
    """Controlled Docker transport only; real capsule/config/host refusal path."""
    receipt, _ = capture(tree)
    runtime = tree[0].parents[1] / "runtime"
    runtime.mkdir()
    state, ledger, temporary = runtime / "state.json", runtime / "ledger.json", runtime / "tmp"
    for path in (state, ledger, state.with_suffix(".json.lock"), ledger.with_suffix(".json.lock")):
        path.write_text("{}")
    temporary.mkdir()
    run = runtime / "attempt"
    stopped = []
    process = SimpleNamespace(pid=999999999, stdout=io.BytesIO(), stderr=io.BytesIO(),
                              returncode=None, poll=lambda: None)
    def docker_run(argv, **kwargs):
        assert argv[:2] == ["docker", "run"]
        config_raw = (run / "configuration.json").read_bytes()
        config = json.loads(config_raw)
        preflight = dict(configuration_sha256=hashlib.sha256(config_raw).hexdigest())
        if fault != "old_preflight":
            preflight["runtime_acknowledgment"] = source._runtime_acknowledgment(config)
        if fault == "policy":
            preflight["runtime_acknowledgment"]["expected_scheduler_policy_sha256"] = "b" * 64
        elif fault == "configuration":
            preflight["configuration_sha256"] = "c" * 64
        source._write(run / "preflight.json", preflight)
        return process
    monkeypatch.setattr(source.subprocess, "Popen", docker_run)
    monkeypatch.setattr(source.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=""))
    monkeypatch.setattr(source, "_stop_owned_container", lambda name, process: stopped.append(name))
    owner = SimpleNamespace(reservation_id="controlled-owner", check_usage=lambda *a, **kw: None)
    with pytest.raises(source.SourceSnapshotError, match="acknowledgment"):
        source._run_snapshot(receipt["path"], receipt["sha256"], run_directory=run,
            writable_directories=[runtime], resource_ledger=ledger, argv=[sys.executable, "-B", "-c", "pass"],
            timeout_seconds=1, tmp_directory=temporary, image=source.IMAGE, owner=owner,
            scheduler_state_path=state, expected_scheduler_policy_sha256="a" * 64)
    assert stopped and not (run / "host-verified.json").exists()
    assert not (run / "command-result.json").exists()
    assert json.loads((run / "cleanup.json").read_text())["absent"] is True


@pytest.mark.parametrize("index", [0, 1])
def test_capture_cannot_label_an_older_runtime_as_current(tree, index):
    target = list(source._runtime_producers(tree[0]).values())[index]
    target.write_bytes(b"# old runtime\n")
    with pytest.raises(source.SourceSnapshotError, match="runtime producer inventory differs"):
        source.capture_snapshot(*tree)
    assert not (tree[1] / "manifest.json").exists()
    assert (tree[1] / list(source._runtime_producers(tree[0]))[index]).read_bytes() == b"# old runtime\n"


def test_host_ack_hashes_exact_validated_preflight_bytes_when_file_changes(tree, monkeypatch):
    """Controlled transport tests the host read/validate/hash boundary."""
    receipt, _ = capture(tree)
    runtime = tree[0].parents[1] / "runtime"
    runtime.mkdir()
    state, ledger, temporary = runtime / "state.json", runtime / "ledger.json", runtime / "tmp"
    for path in (state, ledger, state.with_suffix(".json.lock"), ledger.with_suffix(".json.lock")):
        path.write_text("{}")
    temporary.mkdir()
    run = runtime / "attempt"
    identities = {999999991: dict(pid=999999991, parent_pid=1, group_pid=999999991, birth="fixture-parent"),
                  999999992: dict(pid=999999992, parent_pid=999999991, group_pid=999999992, birth="fixture-child")}
    real_process = source._process
    monkeypatch.setattr(source, "_process", lambda pid: identities[pid] if pid in identities else real_process(pid))
    process = SimpleNamespace(pid=999999999, stdout=io.BytesIO(), stderr=io.BytesIO(),
                              returncode=None, poll=lambda: None)
    observed = {}
    def docker_run(argv, **kwargs):
        config_raw = (run / "configuration.json").read_bytes()
        config = json.loads(config_raw)
        preflight = dict(configuration_sha256=hashlib.sha256(config_raw).hexdigest(),
            runtime_acknowledgment=source._runtime_acknowledgment(config),
            process=identities[999999991], child=identities[999999992],
            identities=config["identities"],
            state_identities=[source._identity(path) for path in config["control_state_paths"]])
        source._write(run / "preflight.json", preflight)
        observed["validated_raw"] = (run / "preflight.json").read_bytes()
        return process
    monkeypatch.setattr(source.subprocess, "Popen", docker_run)
    monkeypatch.setattr(source.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=""))
    monkeypatch.setattr(source.subprocess, "check_output", lambda *a, **kw: b'{"Pid":999999991}')
    monkeypatch.setattr(source, "_stop_owned_container", lambda *args: None)
    actual_check = source._require_preflight_acknowledgment
    def change_after_check(preflight, config, digest):
        actual_check(preflight, config, digest)
        changed = dict(preflight, configuration_sha256="changed-after-validation")
        (run / "preflight.json").write_bytes(source._json(changed))
    monkeypatch.setattr(source, "_require_preflight_acknowledgment", change_after_check)
    actual_write = source._write
    class AcknowledgmentObserved(RuntimeError):
        pass
    def write(path, value):
        if path.name == "host-verified.json":
            observed["acknowledgment"] = value
            raise AcknowledgmentObserved()
        actual_write(path, value)
    monkeypatch.setattr(source, "_write", write)
    owner = SimpleNamespace(reservation_id="controlled-owner", check_usage=lambda *a, **kw: None)
    with pytest.raises(AcknowledgmentObserved):
        source._run_snapshot(receipt["path"], receipt["sha256"], run_directory=run,
            writable_directories=[runtime], resource_ledger=ledger, argv=[sys.executable, "-B", "-c", "pass"],
            timeout_seconds=1, tmp_directory=temporary, image=source.IMAGE, owner=owner,
            scheduler_state_path=state, expected_scheduler_policy_sha256="a" * 64)
    digest = observed["acknowledgment"]["preflight_sha256"]
    assert digest == hashlib.sha256(observed["validated_raw"]).hexdigest()
    assert digest != hashlib.sha256((run / "preflight.json").read_bytes()).hexdigest()
