"""Export or validate the bounded, candidate-only Legal corpus graph v1.

Run with the package installed/on a qualified PYTHONPATH, either as a module
or a direct script. This command never adjusts sys.path, calls models, or
publishes artifacts. Its JSON receipt establishes local integrity only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

RECEIPT_SCHEMA = "legal-corpus-graph-cli-receipt/v1"


class CLIError(ValueError):
    """Closed command-line usage or local input failure."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CLIError(message)


def _parser():
    parser = _Parser(description=__doc__, add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    commands = parser.add_subparsers(dest="command", parser_class=_Parser)
    export = commands.add_parser("export", add_help=False)
    export.add_argument("-h", "--help", action="store_true")
    export.add_argument("--snapshot", required=True)
    export.add_argument("--snapshot-sha256", required=True)
    export.add_argument("--output", required=True)
    validate = commands.add_parser("validate", add_help=False)
    validate.add_argument("-h", "--help", action="store_true")
    validate.add_argument("--bundle", required=True)
    validate.add_argument("--manifest-sha256", required=True)
    return parser


def _read_regular_file(path, *, maximum_bytes):
    """Read one bounded regular file without following any path symlink.

    Directory descriptors prevent a parent-component symlink from being hidden
    by path resolution. The expected digest is checked separately by the common
    JSON loader. Exact source intake/authenticity remains the caller's concern.
    """
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise CLIError("this profile requires O_NOFOLLOW and directory-descriptor support")
    candidate = Path(path).absolute()
    if ".." in candidate.parts:
        raise CLIError("parent traversal is unsupported in snapshot paths")
    components = candidate.parts[1:]
    if not components:
        raise CLIError("snapshot must name a regular file")
    directory_fd = os.open(candidate.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = None
    try:
        for component in components[:-1]:
            child_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        descriptor = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory_fd)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            raise CLIError("snapshot must be a bounded regular file")
        chunks, size = [], 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum_bytes + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > maximum_bytes:
                raise CLIError("snapshot exceeds its byte bound")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        observations = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in observations):
            raise CLIError("snapshot changed during its read")
        return b"".join(chunks)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_fd)


def _receipt(*, status, command, **values):
    return dict(schema=RECEIPT_SCHEMA, status=status, command=command,
                view="candidate", admitted=False, formalized=False,
                source_semantics_verified=False, source_authenticity_verified=False,
                proof_verified=False, **values)


def _validated_result(command, bundle, manifest_sha256, loaded):
    snapshot, manifest = loaded["snapshot"], loaded["manifest"]
    return _receipt(status="success", command=command,
        validation_scope="candidate-graph-v1-local-integrity",
        bundle_directory=str(Path(bundle).absolute()), manifest_sha256=manifest_sha256,
        manifest_cid=manifest["record_cid"], snapshot_cid=snapshot["record_cid"],
        node_count=len(snapshot["nodes"]), edge_count=len(snapshot["edges"]),
        external_references_verified=False)


def main(argv=None):
    """Write exactly one JSON receipt and return zero only on success/help."""
    command = None
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        parser = _parser()
        # Help is a receipt too; subcommand help does not require file options.
        if "--help" in arguments or "-h" in arguments:
            command = arguments[0] if arguments and arguments[0] in ("export", "validate") else None
            result = _receipt(status="help", command=command, usage=[
                "export --snapshot PATH --snapshot-sha256 SHA --output DIRECTORY",
                "validate --bundle DIRECTORY --manifest-sha256 SHA",
            ])
        else:
            args = parser.parse_args(arguments)
            command = args.command
            if command is None:
                raise CLIError("a subcommand is required: export or validate")
            from ipfs_datasets_py.logic.autoformal.corpus_contracts import (
                MAX_RECORD_BYTES,
                load_record_bytes,
                require_sha256,
            )
            from ipfs_datasets_py.logic.autoformal.corpus_graph import validate_graph_snapshot
            from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import (
                load_graph_bundle,
                write_graph_bundle,
            )
            if command == "export":
                require_sha256(args.snapshot_sha256, "snapshot-sha256")
                raw = _read_regular_file(args.snapshot, maximum_bytes=MAX_RECORD_BYTES)
                snapshot = validate_graph_snapshot(load_record_bytes(raw,
                    expected_sha256=args.snapshot_sha256))
                manifest = write_graph_bundle(snapshot, args.output)
                from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes
                manifest_sha256 = hashlib.sha256(canonical_dag_json_bytes(manifest)).hexdigest()
                loaded = load_graph_bundle(args.output, expected_manifest_sha256=manifest_sha256)
                if (loaded["manifest"]["record_cid"] != manifest["record_cid"]
                        or loaded["snapshot"]["record_cid"] != snapshot["record_cid"]):
                    raise CLIError("bundle readback differs from exported graph")
                result = _validated_result(command, args.output, manifest_sha256, loaded)
            else:
                require_sha256(args.manifest_sha256, "manifest-sha256")
                loaded = load_graph_bundle(args.bundle,
                    expected_manifest_sha256=args.manifest_sha256)
                result = _validated_result(command, args.bundle, args.manifest_sha256, loaded)
        exit_code = 0
    except Exception as error:
        result = _receipt(status="error", command=command,
            error_type=type(error).__name__, error=str(error))
        exit_code = 1
    sys.stdout.write(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
