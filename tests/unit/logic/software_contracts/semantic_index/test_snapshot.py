"""Tests for deterministic, non-executing semantic snapshot inputs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    RepositorySnapshot,
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
