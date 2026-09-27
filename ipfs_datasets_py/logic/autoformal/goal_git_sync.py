"""Pull origin/main before a supervisor goal edits the compiler, then commit.

Only compiler, decompiler, and parser files are committed. A merge conflict
is reported and left in place. The push is not forced.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

COMPILER_PATHS = (
    "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py",
    "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
    "ipfs_datasets_py/logic/deontic/formula_builder.py",
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def sync_origin_main(
    repo: Path,
    *,
    paths: Sequence[str] = COMPILER_PATHS,
    message: str = "Update compiler and decompiler from supervisor goals",
    push: bool = True,
) -> dict[str, object]:
    """Fetch and merge origin/main, then commit allowlisted edits and push."""

    fetch = _git(repo, "fetch", "origin", "main")
    if fetch.returncode != 0:
        return {"conflict": False, "error": "fetch_failed", "pulled": False, "pushed": False}
    pull = _git(repo, "merge", "--no-edit", "origin/main")
    if pull.returncode != 0:
        conflicted = _git(repo, "diff", "--name-only", "--diff-filter=U")
        return {
            "conflict": True,
            "conflict_paths": [line for line in conflicted.stdout.splitlines() if line.strip()],
            "error": "merge_conflict",
            "pulled": False,
            "pushed": False,
        }
    dirty = _git(repo, "status", "--porcelain", "--", *paths)
    changed = [line[3:] for line in dirty.stdout.splitlines() if len(line) > 3]
    committed = False
    if changed:
        add = _git(repo, "add", "--", *changed)
        if add.returncode != 0:
            return {"conflict": False, "error": "add_failed", "pulled": True, "pushed": False}
        commit = _git(repo, "commit", "-m", message)
        committed = commit.returncode == 0
        if not committed and "nothing to commit" not in commit.stdout:
            return {"conflict": False, "error": "commit_failed", "pulled": True, "pushed": False}
    pushed = False
    if push and committed:
        pushed_result = _git(repo, "push", "origin", "HEAD:main")
        pushed = pushed_result.returncode == 0
        if not pushed:
            return {
                "committed": committed,
                "conflict": False,
                "error": "push_failed",
                "pulled": True,
                "pushed": False,
            }
    return {
        "committed": committed,
        "conflict": False,
        "error": "",
        "pulled": True,
        "pushed": pushed,
    }
