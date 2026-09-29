"""Frozen source bytes and namespace admission must fail closed."""
import hashlib
import json
import os
import fcntl
import signal
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


def test_runtime_allows_owned_output_but_not_tmp_covering_a_test_capsule(tree):
    _, data = capture(tree)
    output = tree[0].parents[1] / "runtime"
    output.mkdir()
    assert source._runtime_paths(data, [output]) == [output]
    with pytest.raises(source.SourceSnapshotError, match="overlaps frozen"):
        source._runtime_paths(data, [Path("/tmp")])


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


@pytest.mark.parametrize("fail", [False, True])
def test_preparation_reserves_before_capture_releases_success_and_retains_failure(tree, monkeypatch, fail):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as leases
    root, _ = tree
    workspace = root.parents[1]
    ledger = workspace / "ledger.json"
    ledger.write_text(json.dumps({"roots": [{"path": str(workspace)}]}))
    events = []
    class Owner:
        reservation_id = "fixture-owned-reservation"
        def __init__(self, *args, **kwargs):
            assert kwargs["storage_bytes"] == 1_000_000_000
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
            source.prepare_snapshot(attempt, resource_ledger=ledger)
        assert "released" not in events and events[-1] == "retained"
        assert (attempt / "failure.json").is_file()
    else:
        result = source.prepare_snapshot(attempt, resource_ledger=ledger)
        assert events[-1] == "released" and result["resource_reservation_id"] == Owner.reservation_id
        assert (attempt / "resources.json").is_file()
