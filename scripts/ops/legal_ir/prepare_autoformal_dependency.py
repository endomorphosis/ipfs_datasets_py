#!/usr/bin/env python3
"""Freeze an existing accelerate commit inside an owned runtime, without edits.

Exports committed bytes only; no checkout/branch/index mutation in the source,
no fetch, no submodule update, and no runtime-library monkey patches. Qualify
the resulting snapshot before using it as an explicit --accelerate-root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=root)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--path", action="append", default=[], help="Optional exact committed packaging paths.")
    parser.add_argument("--storage-limit-bytes", type=int, default=50_000_000_000)
    parser.add_argument("--omit-external-data-links", action="store_true",
                        help="Record and omit unportable data/ links; never follow them or omit source links.")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("revision must be a full immutable commit SHA-1")
    if not 1_000_000_000 <= args.storage_limit_bytes <= 50_000_000_000:
        parser.error("storage limit must be between 1 and 50 billion bytes")
    source, runtime = args.source.resolve(strict=True), args.runtime_root.resolve(strict=True)
    destination = args.destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("dependency destination must be new; old snapshots are retained")
    if not destination.resolve().is_relative_to(runtime) or destination.resolve() == runtime:
        raise ValueError("dependency snapshot must be a child of the owned runtime")
    if git(source, "cat-file", "-t", args.revision).strip() != b"commit":
        raise ValueError("revision is not a commit")
    git(source, "cat-file", "-e", args.revision + ":ipfs_accelerate_py/__init__.py")
    for path in args.path:
        if Path(path).is_absolute() or ".." in Path(path).parts or path.startswith("-"):
            raise ValueError("invalid repository-relative packaging path")
        git(source, "cat-file", "-e", args.revision + ":" + path)
    path_args = ["--", *args.path] if args.path else []
    sizes = git(source, "ls-tree", "-r", "--format=%(objectsize)", args.revision, *path_args).splitlines()
    committed_bytes = sum(int(value) for value in sizes if value.isdigit())
    used = sum(p.stat().st_size for p in runtime.rglob("*") if p.is_file())
    reserve = 3 * committed_bytes + 512 * 1024 * 1024
    if used + reserve > args.storage_limit_bytes or shutil.disk_usage(runtime).free < reserve:
        raise RuntimeError("dependency snapshot reservation exceeds retained storage budget")
    destination.mkdir()
    print(json.dumps({"stage": "exporting_committed_dependency", "revision": args.revision,
                      "committed_bytes": committed_bytes, "destination": str(destination)}), flush=True)
    archive = subprocess.Popen(["git", "archive", "--format=tar", args.revision, *path_args], cwd=source, stdout=subprocess.PIPE)
    omitted_links = []
    def archive_filter(member, destination_path):
        try:
            return tarfile.data_filter(member, destination_path)
        except (tarfile.AbsoluteLinkError, tarfile.LinkOutsideDestinationError):
            if not args.omit_external_data_links or not member.name.startswith("data/"):
                raise
            omitted_links.append({"path": member.name, "target": member.linkname})
            return None
    try:
        with tarfile.open(fileobj=archive.stdout, mode="r|") as stream:
            stream.extractall(destination, filter=archive_filter)
        archive.stdout.close()
        if archive.wait() != 0:
            raise RuntimeError("dependency export failed; partial snapshot retained")
    except BaseException:
        if archive.poll() is None:
            archive.terminate()
        archive.wait()
        raise
    git(destination, "-c", "init.templateDir=", "init", "-b", "autoformal-dependency")
    # Every exported file was tracked by the pinned source commit, including
    # files subsequently covered by its .gitignore. Only this new repo is staged.
    git(destination, "add", "--force", "--all")
    git(destination, "-c", "user.name=Autoformal Snapshot", "-c", "user.email=autoformal@localhost",
        "-c", "commit.gpgsign=false", "commit", "-m", "Pinned unmodified accelerate source " + args.revision)
    core = ["task_sources/database_task_source.py", "task_sources/intent_repository.py",
            "todo_daemon/database_portal_bridge.py", "todo_daemon/implementation_daemon.py",
            "todo_daemon/implementation_daemon_runner.py"]
    hashes = {relative: hashlib.sha256((destination / "ipfs_accelerate_py/agent_supervisor" / relative).read_bytes()).hexdigest()
              for relative in core}
    receipt = {"schema": "autoformal-dependency-snapshot/v1", "source": str(source),
               "source_commit": args.revision, "snapshot": str(destination),
               "snapshot_commit": git(destination, "rev-parse", "HEAD").decode().strip(),
               "committed_bytes": committed_bytes, "core_sha256": hashes,
               "packaging_paths": args.path,
               "omitted_external_data_links": omitted_links,
               "source_modified": False, "monkey_patched": False, "qualified": False}
    path = runtime / (destination.name + "-snapshot.json")
    with path.open("x", encoding="utf-8") as out:
        json.dump(receipt, out, sort_keys=True, indent=2)
        out.write("\n")
    print(json.dumps({"stage": "snapshot_created_not_yet_qualified", "receipt": str(path)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
