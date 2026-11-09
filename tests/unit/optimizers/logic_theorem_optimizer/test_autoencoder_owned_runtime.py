"""Filesystem contracts only; no Docker, native grant, charge or qualification.

Socket/FIFO and unsafe-alias metadata use explicit simulation over regular
fixtures, preserving the existing unit owner's strict live-filesystem policy.
A separately charged real filesystem probe must establish actual socket use.
"""
import os
from pathlib import Path
import stat

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_owned_runtime as runtime


@pytest.fixture
def bound(tmp_path):
    path = tmp_path / "runtime"
    path.mkdir(mode=0o700)
    observer = runtime.OwnedRuntimeDirectory(path, expected_parent=tmp_path,
        expected_owner_uid=os.geteuid(), byte_limit=4096)
    try:
        yield path, observer
    finally:
        observer.close()


@pytest.fixture
def simulated_bound(tmp_path):
    path = tmp_path / "runtime"
    path.mkdir(mode=0o700)
    backend = SimulatedMetadata()
    observer = runtime.OwnedRuntimeDirectory(path, expected_parent=tmp_path,
        expected_owner_uid=os.geteuid(), byte_limit=4096, _backend=backend)
    try:
        yield path, observer, backend
    finally:
        observer.close()


def test_empty_then_regular_files_are_counted_without_authority(bound):
    path, observer = bound
    assert observer.observe()["apparent_bytes"] == 0
    (path / "state").write_bytes(b"abc")
    report = observer.observe()
    assert report["apparent_bytes"] == 3 and report["entry_count"] == 2
    assert report["entries"]["state"]["kind"] == "file"
    assert report["observation_only"] is report["stable_double_snapshot"] is True
    for key in ("native_ownership_authenticated", "external_charge_authenticated", "resource_admission",
                "ledger_changed", "files_deleted", "admitted", "Lean_admitted",
                "ordinary_strict_filesystem_profile_passed", "hostile_same_uid_confinement"):
        assert report[key] is False
    assert not hasattr(observer, "release") and not hasattr(observer, "cleanup")


def test_hardlinks_are_counted_once_per_path_and_all_copies_must_be_internal(bound, tmp_path):
    path, observer = bound
    (path / "a").write_bytes(b"abcd")
    (path / "b").hardlink_to(path / "a")
    assert observer.observe()["apparent_bytes"] == 8
    outside = tmp_path / "outside"
    outside.hardlink_to(path / "a")
    with pytest.raises(runtime.RuntimeDirectoryError, match="outside copies"):
        observer.observe()


def test_relative_internal_aliases_are_recorded_without_following(simulated_bound):
    path, observer, backend = simulated_bound
    (path / "dir").mkdir()
    link, indirect = path / "dir" / "link", path / "indirect"
    link.touch()
    indirect.touch()
    backend.symlink("link", "../missing")
    backend.symlink("indirect", "dir/link")
    try:
        report = observer.observe()
        assert report["simulation"] is True
        assert report["entries"]["dir/link"]["lexical_target"] == "missing"
        assert report["entries"]["dir/link"]["resolved_target"] == "missing"
        assert report["entries"]["indirect"]["resolved_target"] == "missing"
        assert report["apparent_bytes"] == len("../missing") + len("dir/link")
    finally:
        link.unlink(missing_ok=True)
        indirect.unlink(missing_ok=True)


def test_composed_relative_alias_cannot_escape_after_prefix_expansion(simulated_bound):
    path, observer, backend = simulated_bound
    (path / "d").mkdir()
    (path / "d" / "back").touch()
    (path / "out").touch()
    backend.symlink("back", "..")
    backend.symlink("out", "d/back/../outside")
    with pytest.raises(runtime.RuntimeDirectoryError, match="expanded symlink escapes"):
        observer.observe()


@pytest.mark.parametrize("target,reason", [("cycle", "cycle or expansion"),
    ("missing/child", "missing traversed prefix"), ("file/../outside", "non-directory prefix")])
def test_alias_cycles_and_unsupported_traversed_prefixes_fail_closed(simulated_bound, target, reason):
    path, observer, backend = simulated_bound
    (path / "cycle").touch()
    (path / "file").write_text("regular")
    backend.symlink("cycle", target)
    with pytest.raises(runtime.RuntimeDirectoryError, match=reason):
        observer.observe()


@pytest.mark.parametrize("target", ["../outside", "/etc/passwd", "a/../../outside"])
def test_outside_or_absolute_aliases_fail_closed(simulated_bound, target):
    path, observer, backend = simulated_bound
    alias = path / "alias"
    alias.touch()
    backend.symlink("alias", target)
    try:
        with pytest.raises(runtime.RuntimeDirectoryError, match="symlink"):
            observer.observe()
    finally:
        alias.unlink(missing_ok=True)


def test_owned_unix_socket_type_is_metadata_only_with_explicit_simulation(simulated_bound):
    path, observer, backend = simulated_bound
    endpoint = path / "s"
    endpoint.touch()
    backend.entry_overrides["s"] = dict(mode=stat.S_IFSOCK | 0o600, bytes=0)
    try:
        report = observer.observe()
        assert report["simulation"] is True
        assert report["entries"]["s"]["kind"] == "unix_socket"
        assert endpoint.exists() and report["files_deleted"] is False
    finally:
        endpoint.unlink(missing_ok=True)


def test_fifo_type_is_rejected_without_opening_it_with_explicit_simulation(simulated_bound):
    path, observer, backend = simulated_bound
    fifo = path / "pipe"
    fifo.touch()
    backend.entry_overrides["pipe"] = dict(mode=stat.S_IFIFO | 0o600, bytes=0)
    try:
        with pytest.raises(runtime.RuntimeDirectoryError, match="FIFO, device"):
            observer.observe()
        assert fifo.exists()
    finally:
        fifo.unlink(missing_ok=True)


def test_initially_nonempty_root_cannot_be_adopted(tmp_path):
    path = tmp_path / "runtime"
    path.mkdir(mode=0o700)
    (path / "old").write_text("existing")
    before = len(os.listdir("/proc/self/fd"))
    with pytest.raises(runtime.RuntimeDirectoryError, match="initially be empty"):
        runtime.OwnedRuntimeDirectory(path, expected_parent=tmp_path,
            expected_owner_uid=os.geteuid(), byte_limit=4096)
    assert len(os.listdir("/proc/self/fd")) == before
    assert (path / "old").read_text() == "existing"


def test_closing_observer_preserves_files_and_never_releases_a_lease(bound):
    path, observer = bound
    (path / "evidence").write_text("preserve")
    observer.close()
    observer.close()
    assert (path / "evidence").read_text() == "preserve"
    with pytest.raises(runtime.RuntimeDirectoryError, match="closed"):
        observer.observe()


def test_root_replacement_is_not_adopted(bound):
    path, observer = bound
    path.rename(path.with_name("original"))
    path.mkdir(mode=0o700)
    with pytest.raises(runtime.RuntimeDirectoryError, match="path identity changed"):
        observer.observe()


def test_parent_replacement_is_not_adopted(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    path = parent / "runtime"
    path.mkdir(mode=0o700)
    observer = runtime.OwnedRuntimeDirectory(path, expected_parent=parent,
        expected_owner_uid=os.geteuid(), byte_limit=4096)
    try:
        parent.rename(tmp_path / "old-parent")
        parent.mkdir(mode=0o700)
        with pytest.raises(runtime.RuntimeDirectoryError, match="path identity changed"):
            observer.observe()
    finally:
        observer.close()


def test_root_mode_change_is_not_ignored(bound):
    path, observer = bound
    path.chmod(0o755)
    with pytest.raises(runtime.RuntimeDirectoryError, match="identity changed"):
        observer.observe()


@pytest.mark.parametrize("limit,value", [("byte_limit", 0), ("entry_limit", 0), ("depth_limit", 0),
    ("byte_limit", True), ("entry_limit", 20001), ("depth_limit", 129)])
def test_invalid_bounds_are_not_capabilities(tmp_path, limit, value):
    path = tmp_path / "runtime"
    path.mkdir(mode=0o700)
    args = dict(expected_parent=tmp_path, expected_owner_uid=os.geteuid(), byte_limit=4096)
    args[limit] = value
    with pytest.raises(runtime.RuntimeDirectoryError, match="constraints required"):
        runtime.OwnedRuntimeDirectory(path, **args)


def test_byte_limit_fails_closed(bound):
    path, observer = bound
    (path / "too-large").write_bytes(b"a" * 4097)
    with pytest.raises(runtime.RuntimeDirectoryError, match="byte limit"):
        observer.observe()


def test_entry_limit_counts_root_and_all_paths(tmp_path):
    path = tmp_path / "runtime"
    path.mkdir(mode=0o700)
    observer = runtime.OwnedRuntimeDirectory(path, expected_parent=tmp_path,
        expected_owner_uid=os.geteuid(), byte_limit=4096, entry_limit=1)
    try:
        (path / "one").touch()
        with pytest.raises(runtime.RuntimeDirectoryError, match="entry bound"):
            observer.observe()
    finally:
        observer.close()


def test_depth_limit_is_enforced(tmp_path):
    path = tmp_path / "runtime"
    path.mkdir(mode=0o700)
    observer = runtime.OwnedRuntimeDirectory(path, expected_parent=tmp_path,
        expected_owner_uid=os.geteuid(), byte_limit=4096, depth_limit=1)
    try:
        (path / "a" / "b").mkdir(parents=True)
        with pytest.raises(runtime.RuntimeDirectoryError, match="depth bound"):
            observer.observe()
    finally:
        observer.close()


def test_change_between_snapshots_is_refused(bound, monkeypatch):
    path, observer = bound
    target = path / "state"
    target.write_text("old")
    scan = observer._scan
    calls = []
    def changed():
        result = scan()
        calls.append(True)
        if len(calls) == 1:
            target.write_text("new content")
        return result
    monkeypatch.setattr(observer, "_scan", changed)
    with pytest.raises(runtime.RuntimeDirectoryError, match="between bounded observations"):
        observer.observe()


class SimulatedMetadata(runtime._LinuxBackend):
    simulation = True

    def __init__(self):
        self.fault = None
        self.duplicate_path = None
        self.entry_overrides, self.link_targets = {}, {}

    def symlink(self, name, target):
        self.link_targets[name] = target
        self.entry_overrides[name] = dict(mode=stat.S_IFLNK | 0o777, bytes=len(os.fsencode(target)))

    def link(self, parent, name):
        return self.link_targets[name] if name in self.link_targets else super().link(parent, name)

    def identity(self, descriptor):
        value = super().identity(descriptor)
        actual = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        if self.duplicate_path is not None and actual == self.duplicate_path:
            value["inode"] = actual.with_name("a").stat().st_ino
        return value

    def entry(self, parent, name):
        value = super().entry(parent, name)
        if name == "fault" and self.fault == "uid":
            value["uid"] += 1
        if name == "fault" and self.fault == "mount":
            value["mount_id"] += 1
        value.update(self.entry_overrides.get(name, {}))
        return value


@pytest.mark.parametrize("fault", ["uid", "mount"])
@pytest.mark.parametrize("kind", ["file", "directory"])
def test_foreign_uid_and_submount_are_rejected_with_explicit_simulation(tmp_path, fault, kind):
    path = tmp_path / "runtime"
    path.mkdir(mode=0o700)
    backend = SimulatedMetadata()
    observer = runtime.OwnedRuntimeDirectory(path, expected_parent=tmp_path,
        expected_owner_uid=os.geteuid(), byte_limit=4096, _backend=backend)
    try:
        assert observer.observe()["simulation"] is True
        if kind == "file":
            (path / "fault").write_text("data")
        else:
            (path / "fault").mkdir()
        backend.fault = fault
        with pytest.raises(runtime.RuntimeDirectoryError, match="UID|submount"):
            observer.observe()
    finally:
        observer.close()


def test_duplicate_directory_identity_is_refused_with_explicit_simulation(tmp_path):
    path = tmp_path / "runtime"
    path.mkdir(mode=0o700)
    backend = SimulatedMetadata()
    observer = runtime.OwnedRuntimeDirectory(path, expected_parent=tmp_path,
        expected_owner_uid=os.geteuid(), byte_limit=4096, _backend=backend)
    try:
        (path / "a").mkdir()
        (path / "b").mkdir()
        backend.duplicate_path = path / "b"
        with pytest.raises(runtime.RuntimeDirectoryError, match="duplicate runtime directory"):
            observer.observe()
    finally:
        observer.close()


def test_symlink_root_cannot_be_followed_or_adopted(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises((OSError, runtime.RuntimeDirectoryError)):
        runtime.OwnedRuntimeDirectory(alias, expected_parent=tmp_path,
            expected_owner_uid=os.geteuid(), byte_limit=4096)


def test_directory_path_outside_exact_parent_is_refused(tmp_path):
    path = tmp_path / "sub" / "runtime"
    path.mkdir(mode=0o700, parents=True)
    with pytest.raises(runtime.RuntimeDirectoryError, match="exact expected parent"):
        runtime.OwnedRuntimeDirectory(path, expected_parent=tmp_path,
            expected_owner_uid=os.geteuid(), byte_limit=4096)


def test_unmarked_backend_and_json_receipts_cannot_supply_a_held_directory(tmp_path):
    path = tmp_path / "runtime"
    path.mkdir(mode=0o700)
    with pytest.raises(runtime.RuntimeDirectoryError, match="explicitly identify simulation"):
        runtime.OwnedRuntimeDirectory(path, expected_parent=tmp_path,
            expected_owner_uid=os.geteuid(), byte_limit=4096, _backend=object())
    with pytest.raises((TypeError, runtime.RuntimeDirectoryError)):
        runtime.OwnedRuntimeDirectory({"path": str(path)}, expected_parent=tmp_path,
            expected_owner_uid=os.geteuid(), byte_limit=4096)
