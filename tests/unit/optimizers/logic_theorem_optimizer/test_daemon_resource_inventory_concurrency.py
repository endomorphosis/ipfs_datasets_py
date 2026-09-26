"""Deterministic census races without weakening strict attempt accounting."""
from contextlib import contextmanager
import errno
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources


def _after_scan(monkeypatch, target, callback):
    original = os.scandir

    @contextmanager
    def scan(path):
        with original(path) as entries:
            yield entries
        if path == target:
            callback()

    monkeypatch.setattr(resources.os, "scandir", scan)


class _Entry:
    def __init__(self, entry, callback):
        self.path = entry.path
        self._entry = entry
        self._callback = callback

    def stat(self, *, follow_symlinks):
        assert follow_symlinks is False
        self._callback()
        return self._entry.stat(follow_symlinks=False)


def _before_stat(monkeypatch, target, callback):
    original = os.scandir

    @contextmanager
    def scan(path):
        with original(path) as entries:
            yield (_Entry(entry, callback) if Path(entry.path) == target else entry for entry in entries)

    monkeypatch.setattr(resources.os, "scandir", scan)


@pytest.mark.parametrize("strict", [False, True])
def test_discovered_directory_deleted_before_visit_is_only_allowed_in_shared_census(tmp_path, monkeypatch, strict):
    root = tmp_path / "root"
    root.mkdir()
    subtree = root / "other-process-temporary"
    subtree.mkdir()
    (root / "kept").write_bytes(b"kept")
    _after_scan(monkeypatch, root, subtree.rmdir)
    if strict:
        with pytest.raises(resources.DaemonResourceError, match="missing resource path"):
            resources._inventory([root], strict=True)
    else:
        assert resources._inventory([root]) == {
            "apparent_bytes": 4, "entry_count": 2, "symlink_count": 0, "special_file_count": 0}


@pytest.mark.parametrize("strict", [False, True])
def test_missing_ancestor_of_queued_descendant_is_only_allowed_in_shared_census(tmp_path, monkeypatch, strict):
    root = tmp_path / "root"
    branch = root / "branch"
    child = branch / "child"
    child.mkdir(parents=True)
    def remove_branch():
        child.rmdir()
        branch.rmdir()
    _after_scan(monkeypatch, branch, remove_branch)
    if strict:
        with pytest.raises(resources.DaemonResourceError, match="missing resource path"):
            resources._inventory([root], strict=True)
    else:
        assert resources._inventory([root])["entry_count"] == 2


@pytest.mark.parametrize("strict", [False, True])
def test_discovered_file_deleted_before_stat_keeps_entry_count_but_only_shared_census_continues(tmp_path, monkeypatch, strict):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "temporary"
    target.write_bytes(b"gone")
    _before_stat(monkeypatch, target, target.unlink)
    if strict:
        with pytest.raises(FileNotFoundError):
            resources._inventory([root], strict=True)
    else:
        assert resources._inventory([root]) == {
            "apparent_bytes": 0, "entry_count": 1, "symlink_count": 0, "special_file_count": 0}


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("change", ["delete", "replace", "symlink"])
def test_named_root_disappearance_or_identity_change_always_fails(tmp_path, monkeypatch, strict, change):
    root = tmp_path / "root"
    root.mkdir()
    original_root = tmp_path / "original-root"
    def mutate():
        if change == "delete":
            root.rmdir()
        else:
            root.rename(original_root)
            if change == "replace":
                root.mkdir()
            else:
                root.symlink_to(original_root, target_is_directory=True)
    _after_scan(monkeypatch, root, mutate)
    with pytest.raises(resources.DaemonResourceError, match="missing resource|identity changed|symlink"):
        resources._inventory([root], strict=strict)


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("change", ["symlink", "dangling_symlink", "file", "fifo"])
def test_queued_directory_type_replacement_is_never_treated_as_deletion(tmp_path, monkeypatch, strict, change):
    root = tmp_path / "root"
    root.mkdir()
    child = root / "queued"
    child.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    def mutate():
        child.rmdir()
        if change in {"symlink", "dangling_symlink"}:
            child.symlink_to(outside if change == "symlink" else tmp_path / "missing", target_is_directory=True)
        elif change == "file":
            child.write_bytes(b"not a directory")
        else:
            os.mkfifo(child)
    _after_scan(monkeypatch, root, mutate)
    with pytest.raises(resources.DaemonResourceError, match="symlink|directory"):
        resources._inventory([root], strict=strict)


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("error", [PermissionError, NotADirectoryError])
def test_scandir_permission_and_type_errors_are_not_swallowed(tmp_path, monkeypatch, strict, error):
    root = tmp_path / "root"
    child = root / "queued"
    child.mkdir(parents=True)
    original = os.scandir
    failure = error("injected specific filesystem error")
    def scan(path):
        if path == child:
            raise failure
        return original(path)
    monkeypatch.setattr(resources.os, "scandir", scan)
    with pytest.raises(error) as caught:
        resources._inventory([root], strict=strict)
    assert caught.value is failure


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("change", ["delete", "dangling_symlink"])
def test_scandir_disappearance_recheck_never_accepts_dangling_link(tmp_path, monkeypatch, strict, change):
    root = tmp_path / "root"
    child = root / "queued"
    child.mkdir(parents=True)
    original = os.scandir
    def scan(path):
        if path == child:
            child.rmdir()
            if change == "dangling_symlink":
                child.symlink_to(tmp_path / "missing", target_is_directory=True)
            raise FileNotFoundError(errno.ENOENT, "injected disappearance", str(path))
        return original(path)
    monkeypatch.setattr(resources.os, "scandir", scan)
    if strict:
        with pytest.raises(FileNotFoundError):
            resources._inventory([root], strict=True)
    elif change == "dangling_symlink":
        with pytest.raises(resources.DaemonResourceError, match="symlink"):
            resources._inventory([root])
    else:
        assert resources._inventory([root])["entry_count"] == 1


def test_false_missing_error_for_existing_file_does_not_hide_its_bytes(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "retained"
    target.write_bytes(b"must be counted")
    failure = FileNotFoundError(errno.ENOENT, "injected stale observation", str(target))
    def reject():
        raise failure
    _before_stat(monkeypatch, target, reject)
    with pytest.raises(FileNotFoundError) as caught:
        resources._inventory([root])
    assert caught.value is failure


@pytest.mark.parametrize("strict", [False, True])
def test_descendant_path_permission_errors_remain_errors(tmp_path, monkeypatch, strict):
    root = tmp_path / "root"
    child = root / "queued"
    child.mkdir(parents=True)
    original = Path.lstat
    failure = PermissionError("injected lstat permission error")
    def lstat(path):
        if path == child:
            raise failure
        return original(path)
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(PermissionError) as caught:
        resources._inventory([root], strict=strict)
    assert caught.value is failure


def test_named_root_replacement_before_queued_descendant_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "root"
    child = root / "queued"
    child.mkdir(parents=True)
    def replace_root():
        root.rename(tmp_path / "original")
        root.mkdir()
    _after_scan(monkeypatch, root, replace_root)
    with pytest.raises(resources.DaemonResourceError, match="identity changed"):
        resources._inventory([root])


def test_vanished_entries_do_not_relax_inventory_entry_limit(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    first, second = root / "first", root / "second"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    _before_stat(monkeypatch, first, first.unlink)
    monkeypatch.setattr(resources, "MAX_INVENTORY_ENTRIES", 1)
    with pytest.raises(resources.DaemonResourceError, match="entry bound"):
        resources._inventory([root])


@pytest.mark.parametrize("strict", [False, True])
def test_unchanged_symlink_and_special_entry_accounting(tmp_path, strict):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside bytes must not be followed")
    regular = root / "regular"
    regular.write_bytes(b"abc")
    link = root / "link"
    link.symlink_to(outside)
    fifo = root / "fifo"
    os.mkfifo(fifo)
    if strict:
        with pytest.raises(resources.DaemonResourceError, match="symlink|nonregular"):
            resources._inventory([root], strict=True)
    else:
        assert resources._inventory([root]) == {
            "apparent_bytes": 3 + link.lstat().st_size + fifo.lstat().st_size,
            "entry_count": 3, "symlink_count": 1, "special_file_count": 1}
