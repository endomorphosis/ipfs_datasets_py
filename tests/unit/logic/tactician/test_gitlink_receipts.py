"""Nested datasets commit + parent gitlink receipt protocol tests.

These tests exercise the two-repository receipt shape required by LPR-003:
a nested datasets commit receipt and a parent gitlink advance/rollback
receipt. They operate on temporary directories so unit tests never mutate
the live superproject gitlink.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict


def _run(cmd: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], cwd=path)
    _run(["git", "config", "user.email", "lpr003@example.com"], cwd=path)
    _run(["git", "config", "user.name", "LPR-003 Tester"], cwd=path)


def _write_receipt(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def test_nested_commit_parent_gitlink_advance_and_rollback(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    nested = parent / "ipfs_datasets_py"
    _init_repo(parent)
    _init_repo(nested)

    # Seed nested repository.
    (nested / "README.md").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=nested)
    _run(["git", "commit", "-m", "base nested"], cwd=nested)
    base_nested = _run(["git", "rev-parse", "HEAD"], cwd=nested)

    # Parent tracks nested as a gitlink (git submodule-like path without
    # requiring .gitmodules for this hermetic unit test).
    _run(["git", "add", "ipfs_datasets_py"], cwd=parent)
    # git add of a nested repo creates a gitlink automatically.
    _run(["git", "commit", "-m", "track nested base"], cwd=parent)
    prior_gitlink = _run(
        ["git", "rev-parse", f"HEAD:ipfs_datasets_py"], cwd=parent
    )
    assert prior_gitlink == base_nested

    # Reviewed nested commit with tactician marker.
    marker = nested / "logic" / "tactician" / "MARKER"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("logic.tactician@1\n", encoding="utf-8")
    _run(["git", "add", "logic/tactician/MARKER"], cwd=nested)
    _run(["git", "commit", "-m", "LPR-003 Add Logic Tactician"], cwd=nested)
    new_nested = _run(["git", "rev-parse", "HEAD"], cwd=nested)
    assert new_nested != base_nested
    assert _run(["git", "status", "--porcelain"], cwd=nested) == ""
    # Non-detached: branch is checked out.
    branch = _run(["git", "symbolic-ref", "--short", "HEAD"], cwd=nested)
    assert branch

    nested_receipt = {
        "schema": "lpr-003.nested_datasets_commit_receipt@1",
        "repository": "ipfs_datasets_py",
        "prior_commit": base_nested,
        "commit": new_nested,
        "branch": branch,
        "dirty": False,
        "detached": False,
    }
    nested_receipt_path = tmp_path / "receipts" / "nested_datasets_commit.json"
    _write_receipt(nested_receipt_path, nested_receipt)

    # Advance parent gitlink to the nested commit.
    _run(["git", "add", "ipfs_datasets_py"], cwd=parent)
    _run(
        ["git", "commit", "-m", "Advance ipfs_datasets_py gitlink for LPR-003"],
        cwd=parent,
    )
    advanced_gitlink = _run(
        ["git", "rev-parse", "HEAD:ipfs_datasets_py"], cwd=parent
    )
    assert advanced_gitlink == new_nested

    parent_receipt = {
        "schema": "lpr-003.parent_gitlink_receipt@1",
        "path": "ipfs_datasets_py",
        "prior_gitlink": prior_gitlink,
        "gitlink": advanced_gitlink,
        "matches_nested_head": advanced_gitlink == new_nested,
    }
    parent_receipt_path = tmp_path / "receipts" / "parent_gitlink.json"
    _write_receipt(parent_receipt_path, parent_receipt)

    assert json.loads(nested_receipt_path.read_text(encoding="utf-8"))["commit"] == new_nested
    assert json.loads(parent_receipt_path.read_text(encoding="utf-8"))["gitlink"] == new_nested

    # Rollback restores the prior gitlink.
    _run(
        ["git", "update-index", "--cacheinfo", f"160000,{prior_gitlink},ipfs_datasets_py"],
        cwd=parent,
    )
    _run(
        ["git", "commit", "-m", "Rollback ipfs_datasets_py gitlink"],
        cwd=parent,
    )
    rolled = _run(["git", "rev-parse", "HEAD:ipfs_datasets_py"], cwd=parent)
    assert rolled == prior_gitlink

    rollback_receipt = {
        "schema": "lpr-003.parent_gitlink_rollback_receipt@1",
        "path": "ipfs_datasets_py",
        "restored_gitlink": rolled,
        "matches_prior": rolled == prior_gitlink,
    }
    _write_receipt(tmp_path / "receipts" / "parent_gitlink_rollback.json", rollback_receipt)

    # Nested remains clean and non-detached after protocol.
    assert _run(["git", "status", "--porcelain"], cwd=nested) == ""
    assert _run(["git", "symbolic-ref", "--short", "HEAD"], cwd=nested)
