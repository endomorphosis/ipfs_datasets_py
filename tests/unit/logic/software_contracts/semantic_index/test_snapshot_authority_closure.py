"""Regression probes for snapshot authority closure.

These deliberately exercise public snapshot/scanner boundaries instead of
constructing repository state records by hand.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    RepositorySnapshot,
    SnapshotEntry,
    SnapshotError,
    snapshot_repository,
)


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _init(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "Test")


def test_snapshot_mode_is_cid_bound_and_manifest_fields_are_closed(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    snapshot = snapshot_repository(tmp_path, repository_id="repo:closure")
    manifest = snapshot.to_dict()
    manifest["mode"] = "filesystem" if snapshot.mode != "filesystem" else "git-unborn"
    with pytest.raises(SnapshotError):
        RepositorySnapshot.from_dict(manifest)


def test_raw_path_binding_rejects_a_forged_safe_display_path(tmp_path: Path) -> None:
    snapshot = snapshot_repository(tmp_path, repository_id="repo:closure")
    entry = SnapshotEntry("one.py", "artifact", 1, "bafkreihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku")
    manifest = entry.to_dict()
    manifest["path"] = "two.py"
    with pytest.raises(SnapshotError):
        SnapshotEntry.from_dict(manifest)
    assert snapshot.entries == ()


def test_unborn_inventory_and_explicit_bootstrap_id_survive_first_commit(tmp_path: Path) -> None:
    _init(tmp_path)
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    unborn = snapshot_repository(tmp_path, repository_id="repo:caller")
    assert unborn.mode == "git-unborn"
    assert unborn.repository_id == "repo:caller"
    assert unborn.entries[0].disposition == "unborn"
    _git(tmp_path, "add", "module.py")
    _git(tmp_path, "commit", "-m", "born")
    assert snapshot_repository(tmp_path, repository_id="repo:caller").repository_id == "repo:caller"


def test_staged_and_unstaged_deletion_are_retained_as_evidence(tmp_path: Path) -> None:
    _init(tmp_path)
    path = tmp_path / "module.py"
    path.write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "module.py")
    _git(tmp_path, "commit", "-m", "initial")
    path.unlink()
    unstaged = snapshot_repository(tmp_path)
    item = next(entry for entry in unstaged.entries if entry.path == "module.py")
    assert item.disposition == "unstaged_deleted"
    assert item.head_blob_oid
    _git(tmp_path, "add", "-u")
    staged = snapshot_repository(tmp_path)
    item = next(entry for entry in staged.entries if entry.path == "module.py")
    assert item.disposition == "staged_deleted"
    assert item.head_blob_oid
