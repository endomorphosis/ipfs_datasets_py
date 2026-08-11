"""Tests for deterministic, non-executing semantic snapshot inputs."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    GitCommandTimeout,
    RepositorySnapshot,
    repository_identity,
    snapshot_repository,
)


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_filesystem_snapshot_is_sorted_bounded_and_repeatable(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("b = 1\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "ignored.py").write_text("x = 1\n", encoding="utf-8")
    first = snapshot_repository(tmp_path, max_file_bytes=10)
    second = snapshot_repository(tmp_path, max_file_bytes=10)
    assert first.mode == "filesystem"
    assert [entry.path for entry in first.entries] == ["a.py", "b.py"]
    assert first.snapshot_cid == second.snapshot_cid
    assert RepositorySnapshot.from_dict(first.to_dict()) == first


def test_opaque_inputs_are_retained(tmp_path: Path) -> None:
    (tmp_path / "large.py").write_text("x" * 20, encoding="utf-8")
    (tmp_path / "binary.py").write_bytes(b"\xff")
    snapshot = snapshot_repository(tmp_path, max_file_bytes=10)
    by_path = {entry.path: entry for entry in snapshot.entries}
    assert by_path["large.py"].opaque_reason == "oversized"
    assert by_path["binary.py"].opaque_reason == "undecodable"
    assert by_path["binary.py"].source_cid is not None


def test_git_clean_uses_tree_and_dirty_uses_working_bytes(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "module.py")
    _git(tmp_path, "commit", "-m", "initial")
    clean = snapshot_repository(tmp_path)
    assert clean.mode == "git-clean"
    source.write_text("value = 2\n", encoding="utf-8")
    dirty = snapshot_repository(tmp_path)
    assert dirty.mode == "git-working"
    assert clean.snapshot_cid != dirty.snapshot_cid
    assert snapshot_repository(tmp_path).snapshot_cid == dirty.snapshot_cid


def test_clean_git_snapshot_is_tree_anchored_and_excludes_index_storage(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".semantic-index").mkdir()
    (tmp_path / ".semantic-index" / "state.py").write_text("ignored = 1\n", encoding="utf-8")
    (tmp_path / "semantic-index-state").write_text("also ignored\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    first = snapshot_repository(tmp_path)
    second = snapshot_repository(tmp_path)
    assert first.git_tree is not None
    assert first.snapshot_cid == second.snapshot_cid
    assert [entry.path for entry in first.entries] == ["module.py"]
    assert first.entries[0].source_cid == cid_for_bytes(b"value = 1\n")


def test_unrelated_same_basename_git_repositories_have_distinct_identity(tmp_path: Path) -> None:
    roots = [tmp_path / "one" / "same", tmp_path / "two" / "same"]
    for number, root in enumerate(roots):
        root.mkdir(parents=True)
        _git(root, "init")
        _git(root, "config", "user.email", "test@example.invalid")
        _git(root, "config", "user.name", "Test")
        (root / "module.py").write_text(f"value = {number}\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", "initial")
    assert repository_identity(roots[0]) != repository_identity(roots[1])


def test_no_origin_identity_is_root_history_stable_and_unborn_is_typed(tmp_path: Path) -> None:
    unborn = tmp_path / "unborn"
    unborn.mkdir()
    _git(unborn, "init")
    snapshot = snapshot_repository(unborn, repository_id="repo:caller")
    assert snapshot.mode == "git-unborn"
    assert snapshot.repository_id == "repo:caller"
    _git(unborn, "config", "user.email", "test@example.invalid")
    _git(unborn, "config", "user.name", "Test")
    (unborn / "module.py").write_text("value = 1\n", encoding="utf-8")
    _git(unborn, "add", ".")
    _git(unborn, "commit", "-m", "initial")
    first_identity = repository_identity(unborn)
    _git(unborn, "commit", "--allow-empty", "-m", "empty")
    assert repository_identity(unborn) == first_identity
    assert snapshot_repository(unborn, repository_id="repo:caller").repository_id == "repo:caller"


def test_excluded_change_does_not_change_clean_selection_or_snapshot(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".semantic-index").mkdir()
    control = tmp_path / ".semantic-index" / "state"
    control.write_text("one", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    first = snapshot_repository(tmp_path)
    control.write_text("two", encoding="utf-8")
    second = snapshot_repository(tmp_path)
    assert second.mode == "git-clean"
    assert second.snapshot_cid == first.snapshot_cid


def test_malformed_git_name_is_retained_as_opaque_artifact(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    bad_name = b"bad-\xff.py"
    descriptor = __import__("os").open(__import__("os").fsencode(tmp_path) + b"/" + bad_name,
                                        __import__("os").O_WRONLY | __import__("os").O_CREAT, 0o600)
    try:
        __import__("os").write(descriptor, b"value = 1\n")
    finally:
        __import__("os").close(descriptor)
    subprocess.run([b"git", b"add", b"--", bad_name], cwd=tmp_path, check=True)
    _git(tmp_path, "commit", "-m", "initial")
    entry = snapshot_repository(tmp_path).entries[0]
    assert entry.is_opaque
    assert entry.opaque_reason == "malformed_path"
    assert entry.path.startswith("@malformed-path/")


def test_git_timeout_has_a_typed_snapshot_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot as snapshot

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(["git"], 1)

    monkeypatch.setattr(snapshot.subprocess, "run", timeout)
    with pytest.raises(GitCommandTimeout):
        snapshot_repository(tmp_path)
