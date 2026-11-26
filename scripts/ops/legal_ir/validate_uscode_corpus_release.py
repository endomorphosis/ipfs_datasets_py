"""Export/validate a candidate graph or replay one bounded release component.

Run with the package installed/on a qualified PYTHONPATH, either as a module
or a direct script. This command never adjusts sys.path, calls models, or
publishes artifacts. Its JSON receipt establishes local integrity only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

RECEIPT_SCHEMA = "legal-corpus-graph-cli-receipt/v1"
_WHOLE_NORM_V4_PROFILE = "reviewed-source-use-whole-norm-physical-source-replay/v1"
_PHYSICAL_V3_PROFILE = "reviewed-norm-v3-physical-three-cache-replay/v1"
_RETAINED_TYPE_COMMAND = "retained-type-eligibility"
_RETAINED_INPUT_FILES = ("checked-report", "probe-input", "stdout", "stderr")
_RETAINED_SELECTION_FLAGS = ("preparation-sha256", "graph-sha256", "unit-id")
_RETAINED_REPLAY_FLAGS = tuple(flag for name in _RETAINED_INPUT_FILES
                               for flag in (name, name + "-sha256")) + _RETAINED_SELECTION_FLAGS
_RETAINED_REPLAY_USAGE = (
    "--checked-report PATH --checked-report-sha256 SHA "
    "--probe-input PATH --probe-input-sha256 SHA --stdout PATH --stdout-sha256 SHA "
    "--stderr PATH --stderr-sha256 SHA --preparation-sha256 SHA --graph-sha256 SHA --unit-id ID"
)


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
    closure = commands.add_parser("validate-closure", add_help=False)
    closure.add_argument("-h", "--help", action="store_true")
    closure.add_argument("--request", required=True)
    closure.add_argument("--request-sha256", required=True)
    closure.add_argument("--include-declared-eligibility", action="store_true")
    closure.add_argument("--profile", choices=(
        "reviewed-norm-v2-local-replay/v1",
        "reviewed-norm-v2-physical-three-cache-replay/v1",
        _PHYSICAL_V3_PROFILE,
        "reviewed-norm-v3-direct",
        _WHOLE_NORM_V4_PROFILE,
    ), default="reviewed-norm-v2-local-replay/v1")
    for flag in _RETAINED_REPLAY_FLAGS + ("saved", "saved-sha256"):
        closure.add_argument("--" + flag)
    physical_request = closure.add_mutually_exclusive_group()
    physical_request.add_argument("--retain-physical-request", metavar="DEST")
    physical_request.add_argument("--replay-retained-artifacts", action="store_true")
    closure.add_argument("--paired-cache-archive")
    closure.add_argument("--paired-cache-archive-sha256")
    closure.add_argument("--current-review", metavar="PATH")
    closure.add_argument("--current-review-sha256", metavar="SHA")
    retained = commands.add_parser(_RETAINED_TYPE_COMMAND, add_help=False)
    retained.add_argument("-h", "--help", action="store_true")
    for flag in _RETAINED_REPLAY_FLAGS:
        retained.add_argument("--" + flag, required=True)
    destination = retained.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output")
    destination.add_argument("--saved")
    retained.add_argument("--saved-sha256")
    return parser


@contextmanager
def _file_location(path):
    """Open the existing parent by descending through unsymlinked directory FDs."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise CLIError("this profile requires O_NOFOLLOW and directory-descriptor support")
    candidate = Path(path).absolute()
    if ".." in candidate.parts:
        raise CLIError("parent traversal is unsupported in snapshot paths")
    components = candidate.parts[1:]
    if not components:
        raise CLIError("snapshot must name a regular file")
    directory_fd = os.open(candidate.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in components[:-1]:
            child_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        yield directory_fd, components[-1]
    finally:
        os.close(directory_fd)


def _file_inode(info):
    return info.st_dev, info.st_ino


def _read_named_file(directory_fd, name, maximum_bytes):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
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
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        observations = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if size != before.st_size or any(
                getattr(before, field) != getattr(after, field)
                or getattr(before, field) != getattr(named, field) for field in observations):
            raise CLIError("snapshot changed during its read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_regular_file(path, *, maximum_bytes):
    """Read one bounded regular file without following any path symlink."""
    with _file_location(path) as (directory_fd, name):
        return _read_named_file(directory_fd, name, maximum_bytes)


def _remove_owned_file(directory_fd, name, inode):
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if _file_inode(info) == inode:
        os.unlink(name, dir_fd=directory_fd)


def _write_new_handoff(path, raw, *, maximum_bytes):
    """Read back an exclusive stage and publish a closed file without overwrite."""
    if not 0 < len(raw) <= maximum_bytes:
        raise CLIError("retained eligibility handoff exceeds its byte bound")
    with _file_location(path) as (directory_fd, name):
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise CLIError("retained eligibility output already exists; overwrite refused")
        stage = ".retained-type-eligibility-" + secrets.token_hex(16) + ".pending"
        descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory_fd)
        linked = False
        inode = None
        try:
            with os.fdopen(descriptor, "wb") as stream:
                inode = _file_inode(os.fstat(stream.fileno()))
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if _read_named_file(directory_fd, stage, maximum_bytes) != raw:
                raise CLIError("staged retained eligibility handoff differs from replay")
            if _file_inode(os.stat(stage, dir_fd=directory_fd, follow_symlinks=False)) != inode:
                raise CLIError("retained eligibility stage was replaced")
            try:
                os.link(stage, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                        follow_symlinks=False)
            except FileExistsError as error:
                raise CLIError("retained eligibility output already exists; overwrite refused") from error
            linked = True
            _remove_owned_file(directory_fd, stage, inode)
            os.fsync(directory_fd)
            with _file_location(path) as (current_fd, current_name):
                if (_file_inode(os.fstat(current_fd)) != _file_inode(os.fstat(directory_fd))
                        or _file_inode(os.stat(current_name, dir_fd=current_fd, follow_symlinks=False)) != inode
                        or _read_named_file(current_fd, current_name, maximum_bytes) != raw):
                    raise CLIError("published retained eligibility handoff differs from replay")
        except BaseException:
            if linked:
                _remove_owned_file(directory_fd, name, inode)
                os.fsync(directory_fd)
            raise
        finally:
            if inode is not None:
                _remove_owned_file(directory_fd, stage, inode)


def _replay_retained_type_eligibility(args):
    from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
    from ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_preservation_elaboration_native_v2 import (
        MAX_CAPTURE_BYTES,
    )
    from ipfs_datasets_py.logic.autoformal.legal_release_coordinator_v1 import (
        qualify_retained_physical_type_capture_v4,
    )
    from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest
    from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

    if (args.saved is None) != (args.saved_sha256 is None):
        raise CLIError("--saved and --saved-sha256 must be supplied together")
    for field in ("checked_report", "probe_input", "stdout", "stderr", "preparation", "graph"):
        contracts.require_sha256(getattr(args, field + "_sha256"), field + " SHA256")
    contracts.require_text(args.unit_id, "selected unit ID")
    if args.saved is not None:
        contracts.require_sha256(args.saved_sha256, "saved handoff SHA256")
    limit = contracts.MAX_RECORD_BYTES
    raw = _read_regular_file(args.probe_input, maximum_bytes=limit)
    probe = contracts.load_record_bytes(raw, expected_sha256=args.probe_input_sha256)
    contracts.require_keys(probe, ("schema", "request", "request_sha256", "original_files",
                                  "retained_receipt_sha256", "retained_packet_sha256"), "probe input")
    if probe["schema"] != "physical-type-probe-caller-input/v1" or type(probe["original_files"]) is not dict:
        raise CLIError("closed physical type probe input required")
    request = BackendRequest.from_dict(probe["request"])
    contracts.require_sha256(probe["request_sha256"], "probe request SHA256")
    if request.digest != probe["request_sha256"]:
        raise CLIError("typed request differs from the pinned probe input")
    if args.saved is not None:
        saved = _read_regular_file(args.saved, maximum_bytes=limit)
        if hashlib.sha256(saved).hexdigest() != args.saved_sha256:
            raise CLIError("saved handoff differs from expected SHA256")
    handoff = qualify_retained_physical_type_capture_v4(
        _read_regular_file(args.checked_report, maximum_bytes=limit),
        request, tuple(sorted(probe["original_files"].items())),
        _read_regular_file(args.stdout, maximum_bytes=MAX_CAPTURE_BYTES),
        _read_regular_file(args.stderr, maximum_bytes=MAX_CAPTURE_BYTES),
        expected_checked_release_report_sha256=args.checked_report_sha256,
        expected_graph_sha256=args.graph_sha256, expected_unit_id=args.unit_id,
        expected_retained_receipt_sha256=probe["retained_receipt_sha256"],
        expected_retained_packet_sha256=probe["retained_packet_sha256"],
        expected_preparation_sha256=args.preparation_sha256,
        expected_stdout_sha256=args.stdout_sha256, expected_stderr_sha256=args.stderr_sha256)
    content = canonical_dag_json_bytes(handoff)
    if args.saved is not None and saved != content:
        raise CLIError("saved handoff differs from the exact retained eligibility replay")
    return handoff, content


def _retained_type_eligibility(args):
    from ipfs_datasets_py.logic.autoformal.corpus_contracts import MAX_RECORD_BYTES

    handoff, content = _replay_retained_type_eligibility(args)
    if args.output is not None:
        _write_new_handoff(args.output, content, maximum_bytes=MAX_RECORD_BYTES)
    return _receipt(status="success", command=_RETAINED_TYPE_COMMAND,
        validation_scope="retained-v4-type-eligibility-local-replay",
        mode="save" if args.output is not None else "reload",
        artifact={"path": str(Path(args.output or args.saved).absolute()), "bytes": len(content),
                  "sha256": hashlib.sha256(content).hexdigest()},
        declared_eligibility_cid=handoff["declared_eligibility"]["record_cid"])


def _current_review_for_closure(args):
    """Load an independently pinned caller observation for physical V4 replay."""
    path, digest = args.current_review, args.current_review_sha256
    if path is None and digest is None:
        return None
    if path is None or digest is None:
        raise CLIError("--current-review and --current-review-sha256 must be supplied together")
    if args.profile != _WHOLE_NORM_V4_PROFILE:
        raise CLIError("current review observation requires the physical V4 profile")
    from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts

    contracts.require_sha256(digest, "current review SHA256")
    raw = _read_regular_file(path, maximum_bytes=contracts.MAX_RECORD_BYTES)
    return contracts.load_record_bytes(raw, expected_sha256=digest)


def _retained_type_for_closure(args):
    flags = _RETAINED_REPLAY_FLAGS + ("saved", "saved-sha256")
    supplied = [getattr(args, flag.replace("-", "_")) is not None for flag in flags]
    if not any(supplied):
        return None
    if args.profile != _WHOLE_NORM_V4_PROFILE:
        raise CLIError("saved retained type eligibility requires the physical V4 profile")
    if not all(supplied):
        raise CLIError("saved retained type eligibility requires all replay input pins and the saved handoff")
    handoff, _ = _replay_retained_type_eligibility(args)
    evidence = handoff["declared_eligibility_evidence"]
    if evidence["request_sha256"] != args.request_sha256:
        raise CLIError("saved retained type eligibility belongs to a different physical release request")
    return handoff


def _bind_retained_type_to_closure(closure, handoff, saved_sha256):
    # The retained review and conditional observation are historical. Compare
    # the exact component evidence shared with the new source-only replay.
    evidence = handoff["declared_eligibility_evidence"]
    historical_fields = {
        "schema", "record_cid", "cid_scope", "current_review_observation",
        "checked_native_observation", "retained_type_capture_provenance",
    }
    observed = {key: value for key, value in closure["declared_eligibility_evidence"].items()
                if key not in historical_fields}
    retained = {key: value for key, value in evidence.items() if key not in historical_fields}
    if observed != retained:
        raise CLIError("saved retained type eligibility differs from the replayed release components")
    provenance = evidence["retained_type_capture_provenance"]
    population = {row["unit_id"]: row for row in closure["unit_preservation_bindings"]}
    for role, kind in (("unit", "norm"), ("source_definition", "definition")):
        binding = provenance[role]
        row = population.get(binding["unit_id"], {})
        if row.get("kind") != kind or any(row.get(key) != value for key, value in binding.items()):
            raise CLIError("saved retained type eligibility differs from the replayed unit binding")
    if handoff["declared_eligibility"]["views"] != closure["declared_eligibility"]["views"]:
        raise CLIError("saved retained type eligibility differs from the replayed eligibility views")
    return {"validation_scope": "retained-v4-type-eligibility-local-replay",
            "saved_handoff_sha256": saved_sha256,
            "handoff": handoff}


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
            command = arguments[0] if arguments and arguments[0] in ("export", "validate", "validate-closure", _RETAINED_TYPE_COMMAND) else None
            result = _receipt(status="help", command=command, usage=[
                "export --snapshot PATH --snapshot-sha256 SHA --output DIRECTORY",
                "validate --bundle DIRECTORY --manifest-sha256 SHA",
            ] if command != "validate-closure" else [
                "validate-closure --request PATH --request-sha256 SHA",
            ])
            if command == _RETAINED_TYPE_COMMAND:
                result["usage"] = [
                    f"retained-type-eligibility {_RETAINED_REPLAY_USAGE} "
                    "(--output PATH | --saved PATH --saved-sha256 SHA)",
                ]
            if command == "validate-closure":
                result["supported_profiles"] = [
                    "reviewed-norm-v2-local-replay/v1",
                    "reviewed-norm-v2-physical-three-cache-replay/v1",
                    _PHYSICAL_V3_PROFILE,
                    "reviewed-norm-v3-direct",
                    _WHOLE_NORM_V4_PROFILE,
                ]
                result["default_profile"] = "reviewed-norm-v2-local-replay/v1"
                result["retained_type_eligibility_usage"] = (
                    f"validate-closure --profile {_WHOLE_NORM_V4_PROFILE} --request PATH --request-sha256 SHA "
                    f"--saved PATH --saved-sha256 SHA {_RETAINED_REPLAY_USAGE}")
                result["retained_physical_request_usage"] = (
                    f"validate-closure --profile {_WHOLE_NORM_V4_PROFILE} --request PATH --request-sha256 SHA "
                    "(--retain-physical-request DEST | --replay-retained-artifacts "
                    "[--paired-cache-archive PATH --paired-cache-archive-sha256 SHA])")
                result["current_review_usage"] = (
                    f"validate-closure --profile {_WHOLE_NORM_V4_PROFILE} --request PATH --request-sha256 SHA "
                    "--current-review PATH --current-review-sha256 SHA")
                result["declared_eligibility"] = {
                    "flag": "--include-declared-eligibility",
                    "supported_profiles": [_PHYSICAL_V3_PROFILE, _WHOLE_NORM_V4_PROFILE],
                }
        else:
            args = parser.parse_args(arguments)
            command = args.command
            if command is None:
                raise CLIError("a subcommand is required: export, validate, validate-closure or retained-type-eligibility")
            if command == _RETAINED_TYPE_COMMAND:
                result = _retained_type_eligibility(args)
                sys.stdout.write(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
                return 0
            if command == "validate-closure":
                if ((args.retain_physical_request is not None or args.replay_retained_artifacts)
                        and args.profile != _WHOLE_NORM_V4_PROFILE):
                    raise CLIError("retained physical request options require the physical V4 profile")
                paired_archive_args = args.paired_cache_archive, args.paired_cache_archive_sha256
                if any(value is not None for value in paired_archive_args) and (
                        not all(paired_archive_args) or not args.replay_retained_artifacts):
                    raise CLIError("paired cache archive and its SHA256 require physical V4 retained replay")
                current_review = _current_review_for_closure(args)
                from ipfs_datasets_py.logic.autoformal.legal_release_coordinator_v1 import (
                    MAX_CLOSURE_REQUEST_BYTES, validate_uscode_release_closure_v1,
                )
                retained_handoff = _retained_type_for_closure(args)
                eligibility_options = {}
                if current_review is not None:
                    eligibility_options["current_review"] = current_review
                if args.include_declared_eligibility or retained_handoff is not None:
                    if args.profile not in (_PHYSICAL_V3_PROFILE, _WHOLE_NORM_V4_PROFILE):
                        raise CLIError("declared eligibility requires a supported physical V3 or V4 profile")
                    eligibility_options["include_declared_eligibility"] = True
                request_limit = MAX_CLOSURE_REQUEST_BYTES
                if args.profile in ("reviewed-norm-v3-direct", _WHOLE_NORM_V4_PROFILE):
                    from ipfs_datasets_py.logic.autoformal.legal_release_coordinator_v1 import (
                        MAX_CLOSURE_REQUEST_BYTES_V3,
                    )
                    request_limit = MAX_CLOSURE_REQUEST_BYTES_V3
                raw = _read_regular_file(args.request, maximum_bytes=request_limit)
                validator = validate_uscode_release_closure_v1
                if args.profile == "reviewed-norm-v2-physical-three-cache-replay/v1":
                    from ipfs_datasets_py.logic.autoformal.legal_release_coordinator_v1 import (
                        validate_uscode_release_closure_v2,
                    )
                    validator = validate_uscode_release_closure_v2
                elif args.profile == _PHYSICAL_V3_PROFILE:
                    from ipfs_datasets_py.logic.autoformal.legal_release_coordinator_v1 import (
                        validate_uscode_release_closure_v3,
                    )
                    validator = validate_uscode_release_closure_v3
                elif args.profile == "reviewed-norm-v3-direct":
                    from ipfs_datasets_py.logic.autoformal.legal_release_coordinator_v1 import (
                        validate_uscode_release_closure_direct_v3,
                    )
                    validator = validate_uscode_release_closure_direct_v3
                elif args.profile == _WHOLE_NORM_V4_PROFILE:
                    from ipfs_datasets_py.logic.autoformal.legal_release_coordinator_v1 import (
                        validate_uscode_release_closure_v4,
                    )
                    validator = validate_uscode_release_closure_v4
                if args.replay_retained_artifacts:
                    eligibility_options["replay_retained_artifacts"] = True
                if args.paired_cache_archive is not None:
                    from ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_lake_v2 import (
                        decode_parent_replay_value_v1,
                    )
                    archive_raw = _read_regular_file(args.paired_cache_archive, maximum_bytes=request_limit)
                    archive_files = decode_parent_replay_value_v1(archive_raw,
                        expected_payload_sha256=args.paired_cache_archive_sha256, max_bytes=request_limit)
                    if type(archive_files) is not dict or len(archive_files) != 3:
                        raise CLIError("exact three retained paired-cache tables required")
                    eligibility_options["retained_paired_cache_files"] = archive_files
                closure = validator(raw, expected_request_sha256=args.request_sha256,
                    **eligibility_options)
                result = _receipt(status="success", command=command,
                    validation_scope="selected-component-local-replay-not-release-admission",
                    closure=closure)
                if retained_handoff is not None:
                    result["retained_type_eligibility"] = _bind_retained_type_to_closure(
                        closure, retained_handoff, args.saved_sha256)
                if args.retain_physical_request is not None:
                    _write_new_handoff(args.retain_physical_request, raw, maximum_bytes=request_limit)
                    result["retained_physical_request"] = {
                        "path": str(Path(args.retain_physical_request).absolute()),
                        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                    }
                if args.replay_retained_artifacts:
                    result["physical_input_replay"] = "embedded-reviewed-artifacts"
                if args.paired_cache_archive is not None:
                    result["paired_cache_replay"] = {
                        "archive_sha256": args.paired_cache_archive_sha256,
                        "table_count": len(archive_files),
                        "custody": "new-local-replay-files",
                        "original_physical_custody_reestablished": False,
                    }
                sys.stdout.write(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
                return 0
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
