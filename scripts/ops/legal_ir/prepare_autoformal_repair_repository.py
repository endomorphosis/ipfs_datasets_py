#!/usr/bin/env python3
"""Snapshot current source into an owned local repair repository, never main.

Keep the original checkout, index, branch, caches and evidence untouched.
This is an explicit local snapshot, not publication or a production promotion.
Source changes during copying fail closed. Partial output is retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


SOURCE = Path(__file__).resolve().parents[3]
PREFIXES = ("ipfs_datasets_py/", "scripts/ops/legal_ir/", "tests/unit/logic/",
            "tests/unit/duckdb_control/", "tests/unit/optimizers/logic_theorem_optimizer/",
            "tests/unit/huggingface/", "tests/unit_tests/logic/")
DOCUMENTS = {"docs/implementation/plans/US_CODE_AUTOFORMALIZATION_PLAN.md",
             "docs/implementation/runbooks/uscode_autoformal_supervisor.md"}
SUFFIXES = {".py", ".md", ".json", ".toml", ".yaml", ".yml"}


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=root)


def selected_changes(root: Path) -> list[str]:
    modified = git(root, "diff", "--name-only", "-z", "HEAD").split(b"\0")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    return sorted({os.fsdecode(path) for path in modified + untracked if path
                   and (os.fsdecode(path).startswith(PREFIXES) or os.fsdecode(path) in DOCUMENTS)
                   and Path(os.fsdecode(path)).suffix in SUFFIXES})


def file_identity(root: Path, relative: str) -> str:
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("snapshot requires existing regular source files: " + relative)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--storage-limit-bytes", type=int, default=50_000_000_000)
    args = parser.parse_args(argv)
    if not 1_000_000_000 <= args.storage_limit_bytes <= 50_000_000_000:
        parser.error("storage limit must be between 1 and 50 billion bytes")
    runtime = args.runtime_root.resolve(strict=True)
    destination = args.destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("snapshot destination must be new; existing caches are retained")
    if not destination.resolve().is_relative_to(runtime) or destination.resolve() == runtime:
        raise ValueError("snapshot must be a new child of the owned runtime")
    paths = selected_changes(SOURCE)
    identities = {path: file_identity(SOURCE, path) for path in paths}
    head = git(SOURCE, "rev-parse", "HEAD").decode().strip()
    used = sum(path.stat().st_size for path in runtime.rglob("*") if path.is_file())
    # This repository's tracked tree and object store currently total ~1.3 GB.
    # Reserve room for the snapshot, a task worktree and retained evidence.
    reserve = 4_000_000_000
    if used + reserve > args.storage_limit_bytes or shutil.disk_usage(runtime).free < reserve:
        raise RuntimeError("snapshot reservation exceeds retained-artifact budget")
    git(SOURCE, "clone", "--local", "--no-hardlinks", "--no-checkout", "--", str(SOURCE), str(destination))
    git(destination, "remote", "remove", "origin")
    git(destination, "checkout", "-b", "autoformal-candidate", head)
    for relative in paths:
        target = destination / relative
        if target.is_symlink() or not target.parent.resolve().is_relative_to(destination):
            raise ValueError("unsafe snapshot target: " + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / relative, target)
        if file_identity(destination, relative) != identities[relative]:
            raise RuntimeError("source changed during snapshot: " + relative)
    if selected_changes(SOURCE) != paths or any(file_identity(SOURCE, p) != identities[p] for p in paths):
        raise RuntimeError("source changed during snapshot; partial output retained, do not launch")
    if git(SOURCE, "rev-parse", "HEAD").decode().strip() != head:
        raise RuntimeError("source HEAD changed during snapshot")
    if paths:
        git(destination, "add", "--", *paths)
        git(destination, "-c", "user.name=Autoformal Snapshot", "-c", "user.email=autoformal@localhost",
            "-c", "commit.gpgsign=false", "commit", "-m", "Local autoformal source snapshot (not a repair)")
    if git(destination, "status", "--porcelain"):
        raise RuntimeError("prepared repair repository is not clean")
    receipt = {"schema": "autoformal-isolated-source-snapshot/v1", "source": str(SOURCE),
               "source_head": head, "repository": str(destination),
               "snapshot_head": git(destination, "rev-parse", "HEAD").decode().strip(),
               "overlaid_files": identities, "source_index_modified": False,
               "primary_branch_modified": False, "published": False}
    receipt_path = runtime / (destination.name + "-source-snapshot.json")
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"repository": str(destination), "receipt": str(receipt_path),
                      "overlaid_file_count": len(paths), "snapshot_head": receipt["snapshot_head"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
