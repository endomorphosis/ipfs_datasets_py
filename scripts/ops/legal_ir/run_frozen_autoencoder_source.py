#!/usr/bin/env python3
"""Prepare and run explicit frozen canonical source; all qualification gates remain."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).absolute().parents[3]
sys.path.insert(0, str(ROOT))


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    prepare = commands.add_parser("prepare", help="Capture current canonical source with a bounded reservation")
    prepare.add_argument("--output-directory", type=Path, required=True)
    prepare.add_argument("--resource-ledger", type=Path, required=True)
    prepare.add_argument("--extra-python-file", type=Path, action="append", default=[])
    prepare.add_argument("--max-source-bytes", type=int, default=512 * 1024 * 1024)
    prepare.add_argument("--storage-bytes", type=int, default=1_000_000_000)
    prepare.add_argument("--source-timeout-seconds", type=float, default=300)
    run = commands.add_parser("run", help="Run from a verified capsule with explicit writable runtime directories")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--sha256", required=True)
    run.add_argument("--run-directory", type=Path, required=True)
    run.add_argument("--writable-directory", type=Path, action="append", required=True)
    run.add_argument("--resource-ledger", type=Path, required=True)
    run.add_argument("--tmp-directory", type=Path, required=True)
    run.add_argument("--timeout-seconds", type=float, required=True)
    run.add_argument("--image-sha256", default=None, help="Existing local Docker image ID; never pulled")
    run.add_argument("command", nargs=argparse.REMAINDER)
    private = commands.add_parser("_container-entry", help=argparse.SUPPRESS)
    private.add_argument("configuration", type=Path)
    private.add_argument("sha256")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_snapshot as snapshot
    if snapshot.canonical_root() != ROOT:
        raise snapshot.SourceSnapshotError("snapshot module resolved outside the CLI's canonical source tree")
    if args.operation == "prepare":
        result = snapshot.prepare_snapshot(args.output_directory, resource_ledger=args.resource_ledger,
                                           extra_files=args.extra_python_file, max_bytes=args.max_source_bytes,
                                           storage_bytes=args.storage_bytes, source_timeout_seconds=args.source_timeout_seconds)
    elif args.operation == "run":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        result = snapshot.run_snapshot(args.manifest, args.sha256, run_directory=args.run_directory,
                                       writable_directories=args.writable_directory, resource_ledger=args.resource_ledger,
                                       argv=command, timeout_seconds=args.timeout_seconds, tmp_directory=args.tmp_directory,
                                       image=args.image_sha256 or snapshot.IMAGE)
    else:
        return snapshot._container_entry(args.configuration, args.sha256)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
