"""Seal a local LegalIR coordinator receipt after its referenced artifacts.

Artifact bytes are written first. The coordinator receipt is a separate file
and its commit hash is computed over a body that does not contain that hash.
Candidate, reviewed, replay-qualified, and promoted statuses stay separate
selector values. This module does not upload, read a Hub, mutate a
ModelManager catalog, or accept law.
"""
from __future__ import annotations

import hashlib
import json
import sys as _sys
import types as _types
from pathlib import Path


SCHEMA = "legal-release-coordinator/v1"
RECEIPT_NAME = "coordinator-receipt.json"
STATUSES = ("candidate", "reviewed", "replay-qualified", "promoted")
_COMMIT_KEYS = frozenset({"sha256", "digest", "commit", "commit_sha256", "commit_hash"})
_MAX_ARTIFACT_BYTES = 1_000_000


class ReleaseCoordinatorError(ValueError):
    """A release root, artifact, receipt, or selector was not admissible."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseCoordinatorError(message)


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ReleaseCoordinatorError("finite JSON release record required") from error
    _need(len(encoded) <= 1_000_000, "release record byte bound exceeded")
    return encoded


def _root(root: Path) -> Path:
    _need(isinstance(root, Path) and root.is_dir() and not root.is_symlink(), "real release directory required")
    return root


def _artifact_path(root: Path, relative_path: object) -> Path:
    _need(
        type(relative_path) is str and bool(relative_path) and not relative_path.startswith("/")
        and "\\" not in relative_path,
        "relative artifact path required",
    )
    parts = relative_path.split("/")
    _need(all(part not in ("", ".", "..") for part in parts), "artifact path escapes the release root")
    return root.joinpath(*parts)


def publish_referenced_artifact(
    root: Path, relative_path: str, payload: bytes, status: str
) -> dict[str, object]:
    """Write one referenced artifact before any coordinator receipt exists."""

    directory = _root(root)
    _need(not (directory / RECEIPT_NAME).exists(), "artifact published after the coordinator receipt")
    _need(type(payload) is bytes and 0 < len(payload) <= _MAX_ARTIFACT_BYTES, "bounded artifact bytes required")
    _need(status in STATUSES, "artifact status is not a separate release selector")
    path = _artifact_path(directory, relative_path)
    _need(path.name != RECEIPT_NAME, "coordinator receipt cannot be published as a referenced artifact")
    _need(not path.exists(), "referenced artifact path already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "relative_path": relative_path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "byte_length": len(payload),
        "status": status,
        "published": True,
    }


def seal_coordinator_receipt(root: Path, artifacts: list[dict[str, object]]) -> dict[str, object]:
    """Write the coordinator receipt only after every referenced artifact matches."""

    directory = _root(root)
    receipt_path = directory / RECEIPT_NAME
    _need(not receipt_path.exists(), "coordinator receipt already sealed")
    _need(type(artifacts) is list and 1 <= len(artifacts) <= 64, "bounded referenced artifact list required")
    seen: set[str] = set()
    sealed: list[dict[str, object]] = []
    for artifact in artifacts:
        _need(type(artifact) is dict, "closed artifact record required")
        _need(set(artifact) == {"relative_path", "sha256", "byte_length", "status", "published"},
              "closed artifact record required")
        _need(artifact["published"] is True, "referenced artifact is not published")
        relative = artifact["relative_path"]
        _need(type(relative) is str and relative not in seen, "duplicate referenced artifact")
        seen.add(relative)
        _need(relative != RECEIPT_NAME, "coordinator receipt cannot list itself")
        _need(artifact["status"] in STATUSES, "artifact status is not a separate release selector")
        digest = artifact["sha256"]
        _need(type(digest) is str and len(digest) == 64 and all(character in "0123456789abcdef" for character in digest),
              "artifact sha256 required")
        length = artifact["byte_length"]
        _need(type(length) is int and 0 < length <= _MAX_ARTIFACT_BYTES, "artifact byte length required")
        path = _artifact_path(directory, relative)
        _need(path.is_file() and not path.is_symlink(), "referenced artifact is not published")
        payload = path.read_bytes()
        _need(len(payload) == length and hashlib.sha256(payload).hexdigest() == digest,
              "published artifact bytes differ")
        sealed.append({
            "relative_path": relative,
            "sha256": digest,
            "byte_length": length,
            "status": artifact["status"],
        })
    receipt = {
        "schema": SCHEMA,
        "artifacts": sorted(sealed, key=lambda item: str(item["relative_path"])),
        "remote_upload_executed": False,
        "hub_readback_executed": False,
        "model_manager_catalog_mutated": False,
        "legal_acceptance_claimed": False,
        "federal_corpus_acceptance_claimed": False,
    }
    _need(_COMMIT_KEYS.isdisjoint(receipt), "coordinator receipt includes its own commit hash")
    receipt_path.write_bytes(_canonical(receipt) + b"\n")
    return receipt


def coordinator_commit_sha256(receipt: dict[str, object]) -> str:
    """Hash the receipt body. A body that already carries its commit hash is refused."""

    _need(type(receipt) is dict and receipt.get("schema") == SCHEMA, "closed coordinator receipt required")
    _need(_COMMIT_KEYS.isdisjoint(receipt), "self-referential commit hash refused")
    return hashlib.sha256(_canonical(receipt)).hexdigest()


def select_model_manager_status(
    records: list[dict[str, object]], status: str
) -> list[dict[str, object]]:
    """Return records of one exact status. Selectors do not collapse into each other."""

    _need(status in STATUSES, "unknown ModelManager status selector")
    chosen: list[dict[str, object]] = []
    for record in records:
        _need(type(record) is dict and type(record.get("status")) is str, "closed status record required")
        _need(record["status"] in STATUSES, "record status is not a separate release selector")
        _need("statuses" not in record and "selector_alias" not in record, "collapsed status selector refused")
        if record["status"] == status:
            chosen.append(record)
    return chosen


# This profile checks a selected finite component. It never selects a release.
CLOSURE_REQUEST_SCHEMA = "legal-uscode-release-closure-request/v1"
CLOSURE_SCHEMA = "legal-uscode-release-closure-report/v1"
CLOSURE_PROFILE = "reviewed-norm-v2-local-replay/v1"
MAX_CLOSURE_REQUEST_BYTES = 8 * 1024 * 1024
_CLOSURE_ROLES = ("law", "span", "entity")
_CLOSURE_REPOSITORIES = (
    "justicedao/ipfs_uscode", "justicedao/uscode-autoformal-span-cache",
    "justicedao/uscode-autoformal-entity-cache",
)


# Explicit direct-packet domain; the established chunk-index V3 domain is unchanged.
CLOSURE_PROFILE_V3_DIRECT = "reviewed-norm-v3-physical-three-cache-direct-packet-replay/v1"
_BYTE_PROFILE_V3_DIRECT = "reviewed-norm-v3-local-direct-byte-replay/v1"
MAX_CLOSURE_REQUEST_BYTES_V3 = 64 * 1024**2
MAX_CLOSURE_NATIVE_PACKET_BYTES_V3 = 48 * 1024**2
MAX_CLOSURE_ARTIFACT_TOTAL_BYTES_V3 = 48 * 1024**2


def _require_hf_reviewed_graph_v4(release, descriptors, reviewed_graph):
    """Join exact packaged graph rows to the independently replayed graph."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    error = "HF package graph differs from the independently reviewed graph"
    remaining = {
        "graph_nodes": {row["record_cid"]: row for row in reviewed_graph["nodes"]},
        "graph_edges": {row["record_cid"]: row for row in reviewed_graph["edges"]},
    }
    companions = {"graph_nodes": "semantic_graph_node", "graph_edges": "semantic_graph_edge"}
    for descriptor in descriptors:
        family = descriptor["family"]
        companion = companions[family]
        fields = {"entry_cid", "family", companion}
        allowed = fields | {"legal_id"}
        artifact = release.artifact(descriptor["relative_path"])
        _need(artifact.row_count <= len(remaining[family]), error)
        with pq.ParquetFile(pa.BufferReader(artifact.content)) as reader:
            _need(reader.metadata.num_rows == artifact.row_count, error)
            for batch in reader.iter_batches(batch_size=128, use_threads=False):
                for row in batch.to_pylist():
                    entry_cid = row["entry_cid"]
                    expected = remaining[family].pop(entry_cid, None)
                    record_json = row["record_json"]
                    _need(expected is not None and type(record_json) is str and row["family"] == family,
                          error)
                    raw = record_json.encode("utf-8")
                    _need(hashlib.sha256(raw).hexdigest() == row["record_sha256"], error)
                    body = _reviewed_json_artifact_v3(raw)
                    # A V4 row has one graph representation. A parallel flat
                    # projection could present different endpoints or kinds.
                    _need(type(body) is dict and fields <= body.keys() <= allowed, error)
                    legal_id = body.get("legal_id")
                    _need((legal_id is None or type(legal_id) is str)
                          and (legal_id or "") == row["legal_id"]
                          and body["entry_cid"] == entry_cid and body["family"] == family
                          and _canonical(body[companion]) == _canonical(expected), error)
    _need(not any(remaining.values()), error)


def _validate_retained_paired_join_v4(report, inputs, kwargs, *,
        expected_report_sha256, retained_paired_file_bytes):
    """Replay original V3 join bytes through fresh files, without historical custody.

    Internal V4 retained-artifact lane only. The caller selects this path;
    v1/v2/default replay and all Native authority stay with their original owners.
    Return the exact pinned historical report after independently decoding all
    retained table bytes. Historic inode/timestamps remain recorded observations,
    rather than being asserted as the newly materialized file generation.
    """
    import os
    import stat
    from pathlib import Path, PurePosixPath
    from tempfile import TemporaryDirectory
    from . import legal_source_span_entity_join_v1 as joins
    from . import legal_paired_manifest_inventory_v1 as inventory
    from . import legal_paired_payload_intake_v1 as payload

    joins._digest(expected_report_sha256)
    if type(report) is bytes:
        report = joins._read_json(report, joins.MAX_REPORT_BYTES, "retained join report")
    original = joins._wire(report, joins.MAX_REPORT_BYTES)
    _need(hashlib.sha256(original).hexdigest() == expected_report_sha256,
          "retained join report differs from independent pin")
    historical = joins._read_json(original, joins.MAX_REPORT_BYTES, "retained join snapshot")
    _need(type(inputs) in (list, tuple) and len(inputs) == 6,
          "six exact original coordinate join inputs required")
    _need(type(kwargs) is dict and set(kwargs) in (
        {"expected_request_sha256"}, {"expected_request_sha256", "legacy_join_inputs"}),
          "closed original coordinate join arguments required")
    _need(kwargs.get("legacy_join_inputs") is None or type(kwargs.get("legacy_join_inputs")) is dict
          and not kwargs["legacy_join_inputs"], "retained coordinate legacy inputs must be absent")
    initial_kwargs = {key: ({} if key == "legacy_join_inputs" and value is not None else value)
                      for key,value in kwargs.items()}
    captured_inputs = tuple(inputs)
    request_raw, source_raw, source_metadata, paired_raw, manifest_bytes, entity_raw = captured_inputs
    _need(all(type(raw) is bytes for raw in (request_raw, source_raw, paired_raw, entity_raw)),
          "immutable original coordinate request bytes required")
    source_snapshot, manifest_snapshot = joins._coordinate_metadata_snapshot(
        source_metadata, manifest_bytes, (request_raw, source_raw, paired_raw, entity_raw))
    request, _, _ = joins._preflight(request_raw, source_raw, paired_raw, entity_raw,
        kwargs["expected_request_sha256"], kwargs.get("legacy_join_inputs"),
        coordinate=True, wire_source=True)
    span_report = inventory.prepare_paired_manifest_inventory_v2(paired_raw,
        dict(manifest_snapshot), expected_request_sha256=request["paired_inventory_request_sha256"])
    _need(len(span_report["manifests"]) == 1, "one complete retained coordinate bundle required")
    selected = span_report["manifests"][0]
    location = request["paired_bundles"][0]
    manifest_path = selected["path_in_repo"]
    _need(manifest_path == location["manifest_path_in_repo"], "retained manifest selection differs")
    tables = selected["manifest"]["tables"]
    _need(type(tables) is dict and set(tables) == set(inventory.TABLES),
          "exact three retained paired table descriptors required")
    maximum = payload.DEFAULT_LIMITS["max_bytes"]
    _need(type(maximum) is int and maximum == 64 * 1024**2,
          "original paired payload byte bound changed")
    _need(type(retained_paired_file_bytes) is dict and len(retained_paired_file_bytes) == 3
          and all(type(key) is str for key in retained_paired_file_bytes),
          "exact three repository-relative retained paired table bodies required")
    declared = {manifest_path: (selected["bytes"], selected["sha256"])}
    for descriptor in tables.values():
        relative = descriptor["path_in_repo"]
        _need(relative not in declared, "retained bundle paths must be distinct")
        declared[relative] = (descriptor["bytes"], descriptor["sha256"])
    _need(set(retained_paired_file_bytes) == set(declared) - {manifest_path},
          "retained paired-cache table byte population differs from manifest")
    bodies = {manifest_path: manifest_snapshot[manifest_path]}
    total = 0
    for relative, (length, digest) in declared.items():
        path = PurePosixPath(relative)
        _need(type(relative) is str and 0 < len(relative) <= 512
              and not path.is_absolute() and str(path) == relative
              and all(part not in ("", ".", "..") for part in relative.split("/"))
              and "\\" not in relative, "canonical relative retained bundle path required")
        body = bodies.get(relative) if relative == manifest_path else retained_paired_file_bytes[relative]
        _need(type(length) is int and 0 < length <= maximum and type(body) is bytes
              and len(body) == length, "retained paired-cache table byte length differs")
        joins._digest(digest)
        _need(hashlib.sha256(body).hexdigest() == digest, "retained paired-cache table byte digest differs")
        _need(length <= maximum - total, "retained paired bundle aggregate byte bound exceeded")
        total += length
        bodies[relative] = body
    retained_snapshot = {key:value for key,value in bodies.items() if key != manifest_path}
    logical_root = location["repository_root"]
    historic_files = historical.get("retained_file_witnesses")
    original_paths = {str(PurePosixPath(logical_root)/relative): length
                      for relative,(length,_) in declared.items()}
    _need(type(historic_files) is dict and set(historic_files) == set(original_paths),
          "historical coordinate witness population differs from declared paths")
    for path, size in original_paths.items():
        row = historic_files[path]
        _need(type(row) is list and len(row) == 6
              and all(type(value) is int and -(2**63) <= value < 2**63 for value in row)
              and row[0] >= 0 and row[1] >= 0 and stat.S_ISREG(row[2]) and row[3] == size,
              "historical coordinate witness shape or declared size differs")
    owner_pins = joins._coordinate_owner_pins(joins._owners())

    def originals_unchanged():
        _need(type(inputs) in (list, tuple) and len(inputs) == 6,
              "original coordinate inputs changed during retained replay")
        _need(all(type(inputs[index]) is bytes and inputs[index] == captured_inputs[index]
                  for index in (0, 1, 3, 5)), "original coordinate request bytes changed")
        _need(type(kwargs) is dict and kwargs == initial_kwargs,
              "original coordinate arguments changed during retained replay")
        for index, snapshot in ((2, source_snapshot), (4, manifest_snapshot)):
            offered = inputs[index]
            _need(type(offered) is dict and set(offered) == set(snapshot)
                  and all(type(offered[key]) is bytes and offered[key] == body
                          for key,body in snapshot.items()), "original coordinate metadata changed")
        _need(type(retained_paired_file_bytes) is dict
              and set(retained_paired_file_bytes) == set(retained_snapshot)
              and all(type(retained_paired_file_bytes[key]) is bytes
                      and retained_paired_file_bytes[key] == body
                      for key,body in retained_snapshot.items()), "retained paired body mapping changed")
        _need(joins._wire(report, joins.MAX_REPORT_BYTES) == original
              and joins._wire(historical, joins.MAX_REPORT_BYTES) == original,
              "historical pinned join report changed")

    def owners_unchanged():
        _need(joins._coordinate_owner_pins(joins._owners()) == owner_pins,
              "retained coordinate replay owner sources changed")

    primary = None
    try:
        originals_unchanged()
        with TemporaryDirectory(prefix="legal-v4-retained-paired-") as spelling:
            root = Path(spelling).resolve(strict=True)
            _need(root.is_dir() and stat.S_IMODE(root.stat().st_mode) == 0o700,
                  "private retained bundle directory required")
            for relative, body in bodies.items():
                path = root
                for part in PurePosixPath(relative).parts[:-1]:
                    path = path/part
                    if not path.exists():
                        path.mkdir(mode=0o700)
                    _need(path.resolve(strict=True) == path and path.is_dir()
                          and stat.S_IMODE(path.stat().st_mode) == 0o700,
                          "unaliased private retained bundle directory required")
                path = root/relative
                fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    _need(stream.write(body) == len(body), "incomplete retained bundle stage")
                    stream.flush()
                    os.fsync(stream.fileno())
            runtime_request = joins._read_json(request_raw, joins.MAX_REQUEST_BYTES,
                                               "detached coordinate join request")
            runtime_request["paired_bundles"][0]["repository_root"] = str(root)
            runtime_raw = joins._wire(runtime_request, joins.MAX_REQUEST_BYTES)
            runtime_kwargs = dict(initial_kwargs, expected_request_sha256=hashlib.sha256(runtime_raw).hexdigest())
            runtime_inputs = (runtime_raw, source_raw, dict(source_snapshot), paired_raw,
                              dict(manifest_snapshot), entity_raw)
            runtime_location = runtime_request["paired_bundles"][0]
            current_files = joins._coordinate_file_witnesses(runtime_location, selected)
            current_primary = None
            try:
                regenerated = joins.prepare_source_span_entity_join_manifest_v3(*runtime_inputs, **runtime_kwargs)
                _need(regenerated["request"] == runtime_request
                      and regenerated["request_raw_utf8"] == runtime_raw.decode("utf-8")
                      and regenerated["request_sha256"] == runtime_kwargs["expected_request_sha256"]
                      and regenerated["retained_file_witnesses"] == current_files,
                      "fresh retained replay request or custody observation differs")
                _need(type(regenerated["paired_bundles"]) is list and len(regenerated["paired_bundles"]) == 1
                      and regenerated["paired_bundles"][0]["payload_intake"]["repository_root"] == str(root),
                      "fresh retained payload I/O root differs")
                normalized = joins._read_json(joins._wire(regenerated, joins.MAX_REPORT_BYTES),
                                              joins.MAX_REPORT_BYTES, "detached retained replay result")
                normalized["request"] = request
                normalized["request_raw_utf8"] = request_raw.decode("utf-8")
                normalized["request_sha256"] = initial_kwargs["expected_request_sha256"]
                normalized["retained_file_witnesses"] = historic_files
                normalized["paired_bundles"][0]["payload_intake"]["repository_root"] = logical_root
                _need(joins._wire(normalized, joins.MAX_REPORT_BYTES) == original,
                      "retained join report differs outside historical location and custody observations")
            except BaseException as error:
                current_primary = error
                raise
            finally:
                def current_files_unchanged():
                    _need(joins._coordinate_file_witnesses(runtime_location, selected) == current_files,
                          "fresh retained coordinate files changed during replay")
                joins._finish_coordinate_custody((("fresh retained files", current_files_unchanged),), current_primary)
    except BaseException as error:
        primary = error
        raise
    finally:
        joins._finish_coordinate_custody((("original retained inputs and report", originals_unchanged),
                                         ("retained replay owner sources", owners_unchanged)), primary)
    # No producer callbacks follow this final held-report commitment check.
    _need(joins._wire(historical, joins.MAX_REPORT_BYTES) == original,
          "historical retained join return changed after closing custody")
    return historical


def _validate_uscode_release_byte_closure(request_raw: bytes, *, expected_request_sha256: str, reviewed_version: int, _captured_native_context=None,
        _native_transport="chunk-index/v1", original_parent_handle=None, _original_parent_context=None,
        _retained_paired_cache_files=None) -> dict:
    """Replay exact local package, source/IR/graph/dependency/Lean-text custody.

    The request uses the existing bounded plain-value replay codec, including
    exact bytes. No capabilities, imports, executable names or verified flags
    are accepted. Immutable revisions are declarations until independent Hub
    readback exists. The current join/native owners retain their missing
    correspondence and original-parent prerequisites; readiness stays false.
    """
    parent_context = None
    parent_callback_states = None
    if original_parent_handle is not None or _original_parent_context is not None:
        _release_v3_policy()
        if original_parent_handle is not None:
            entry_guard = _release_original_parent_entry_guard_v3
            if (entry_guard is not _RELEASE_ORIGINAL_PARENT_ENTRY_GUARD_V3
                    or entry_guard.__code__ is not _RELEASE_ORIGINAL_PARENT_ENTRY_CODE_V3):
                raise ReleaseCoordinatorError("original-parent coordinator entry generation changed: entry guard")
            entry_guard()
        _need(original_parent_handle is None or reviewed_version == 3, "original parent requires the explicit V3 domain")
        _need(original_parent_handle is not None or _original_parent_context is None,
              "original-parent context cannot replace its opaque handle")
        parent_context = (_original_parent_context if _original_parent_context is not None
            else _release_original_parent_context_v3(original_parent_handle)) if original_parent_handle is not None else None
        if parent_context is not None:
            _release_original_parent_fence_v3(parent_context)
            _need(parent_context[1] is original_parent_handle, "same original opaque parent handle required")
        parent_callback_states = (_release_callback_states_v3((_release_original_parent_context_v3,
            _release_original_parent_fence_v3, _release_original_parent_authentication_v3))
            if parent_context is not None else None)
    from . import corpus_contracts as contracts
    from . import corpus_norm_definition_adapter as graphs
    from . import legal_corpus_definition_use_lake_v2 as wire
    from . import legal_corpus_definition_use_native_v2 as native
    from . import legal_corpus_shared_lake as shared
    from . import legal_graph_dependencies as dependencies
    _need(type(reviewed_version) is int and reviewed_version in (1, 3, 4), "closed reviewed byte version required")
    _need(type(_native_transport) is str and _native_transport in ("chunk-index/v1", "direct-packet/v1"),
          "explicit supported native transport required")
    direct = _native_transport == "direct-packet/v1"
    _need(not direct or reviewed_version in (3, 4), "direct packet requires its explicit V3 domain")
    if direct:
        _release_direct_v3_policy()
    if reviewed_version in (3, 4):
        _release_v3_policy()
        from . import legal_reviewed_norm_admission_v3 as admissions
        request_schema, report_schema = _BYTE_REQUEST_SCHEMA_V3, _BYTE_SCHEMA_V3
        profile = _BYTE_PROFILE_V3_DIRECT if direct else _BYTE_PROFILE_V3
        if reviewed_version == 4:
            _release_v4_policy()
            _need(direct, "source-use physical V4 requires explicit direct transport")
            request_schema, report_schema, profile = (_BYTE_REQUEST_SCHEMA_V4, _BYTE_SCHEMA_V4, _BYTE_PROFILE_V4)
        admission_validator = admissions.validate_reviewed_norm_admission_v3
        graph_validator = graphs.validate_reviewed_norm_graph_v3
        preparation_validator = native.validate_reviewed_norm_preservation_native_v3
        receipt_validator = native.validate_reviewed_norm_preservation_native_receipt_v3
    else:
        from . import legal_norm_content_adjudication_v1 as admissions
        request_schema, report_schema, profile = CLOSURE_REQUEST_SCHEMA, CLOSURE_SCHEMA, CLOSURE_PROFILE
        admission_validator = admissions.validate_reviewed_norm_admission_v2
        graph_validator = graphs.validate_reviewed_norm_graph_v2
        preparation_validator = native.validate_reviewed_norm_preservation_native_v2
        receipt_validator = native.validate_reviewed_norm_preservation_native_receipt_v2
    callbacks = (admission_validator, graph_validator, preparation_validator, receipt_validator)
    callback_states = _release_callback_states_v3(callbacks) if reviewed_version in (3, 4) else None
    def version_fence():
        if reviewed_version in (3, 4):
            _release_v3_policy()
            if reviewed_version == 4:
                _release_v4_policy()
            if direct:
                _release_direct_v3_policy()
            current = (admissions.validate_reviewed_norm_admission_v3, graphs.validate_reviewed_norm_graph_v3,
                native.validate_reviewed_norm_preservation_native_v3, native.validate_reviewed_norm_preservation_native_receipt_v3)
            _release_callback_fence_v3(current, callback_states)
        if parent_context is not None:
            _release_callback_fence_v3((_release_original_parent_context_v3,
                _release_original_parent_fence_v3, _release_original_parent_authentication_v3), parent_callback_states)
            _release_original_parent_fence_v3(parent_context)
    from . import legal_source_span_entity_join_v1 as joins
    from ...processors.legal_data import uscode_hf_release as hf
    from ...processors.legal_data.uscode_release_schema import require_immutable_revision

    contracts.require_sha256(expected_request_sha256, "closure request SHA256")
    request_limit = MAX_CLOSURE_REQUEST_BYTES_V3 if direct else MAX_CLOSURE_REQUEST_BYTES
    artifact_total_limit = MAX_CLOSURE_ARTIFACT_TOTAL_BYTES_V3 if direct else MAX_CLOSURE_REQUEST_BYTES
    request = wire.decode_parent_replay_value_v1(request_raw,
        expected_payload_sha256=expected_request_sha256, max_bytes=request_limit)
    keys = {"schema", "profile", "datasets", "expected_artifact_ids", "artifacts",
            "expected_unit_ids", "component", "pins", "native"}
    _need(type(request) is dict and set(request) == keys, "closed closure request required")
    _need(request["schema"] == request_schema and request["profile"] == profile,
          "unsupported closure schema/profile; explicit compatible consumer required")
    datasets = request["datasets"]
    _need(type(datasets) is list and len(datasets) == 3, "exact law/span/entity revision population required")
    for row, role, repository in zip(datasets, _CLOSURE_ROLES, _CLOSURE_REPOSITORIES):
        _need(type(row) is dict and set(row) == {"role", "repository_id", "revision"}
              and row["role"] == role and row["repository_id"] == repository,
              "exact ordered law/span/entity repository identities required")
        require_immutable_revision(row["revision"], name=role + " revision")
    rows, expected = request["artifacts"], request["expected_artifact_ids"]
    _need(type(rows) is list and 1 <= len(rows) <= 64 and type(expected) is list
          and len(expected) == len(rows), "bounded exact artifact population required")
    materials, descriptors, total = {}, [], 0
    for row in rows:
        _need(type(row) is dict and set(row) == {"artifact_id", "family", "sha256", "bytes", "payload"},
              "closed artifact byte descriptor required")
        name, raw = row["artifact_id"], row["payload"]
        _need(type(name) is str and 0 < len(name.encode("utf-8")) <= 512 and name not in materials,
              "unique bounded artifact identity required")
        artifact_limit = (MAX_CLOSURE_NATIVE_PACKET_BYTES_V3
            if direct and row["family"] == "native_packet" else _MAX_ARTIFACT_BYTES)
        _need(type(row["family"]) is str and type(raw) is bytes
              and 0 < len(raw) <= artifact_limit and type(row["bytes"]) is int
              and row["bytes"] == len(raw), "bounded exact artifact bytes required")
        contracts.require_sha256(row["sha256"], "artifact SHA256")
        _need(hashlib.sha256(raw).hexdigest() == row["sha256"], "artifact byte identity differs")
        total += len(raw)
        _need(total <= artifact_total_limit, "complete artifact population exceeds byte bound")
        materials[name] = row
        descriptors.append({key: row[key] for key in ("artifact_id", "family", "sha256", "bytes")})
    _need(list(materials) == expected, "artifact population order or membership differs")
    component, pins = request["component"], request["pins"]
    roles = {"admission", "graph", "dependency", "preservation", "replay", "hf_package", "source_span_entity_join"}
    _need(type(component) is dict and set(component) == roles
          and len(set(component.values())) == len(roles), "distinct exact component artifact roles required")
    _need(type(pins) is dict and set(pins) == {"admission", "graph", "preservation"},
          "independent complete component pins required")
    for pin in pins.values():
        contracts.require_sha256(pin, "component pin")
    def payload(name, family):
        _need(name in materials and materials[name]["family"] == family,
              "required component artifact omitted or family changed: " + str(name))
        return materials[name]["payload"]
    def ordinary(name, family):
        raw = payload(name, family)
        if reviewed_version in (3, 4) and family in ("admission", "graph"):
            value = _reviewed_json_artifact_v3(raw)
        else:
            value = contracts.load_json_bytes(raw, expected_sha256=hashlib.sha256(raw).hexdigest())
        _need(raw == _canonical(value), "exact canonical artifact bytes required")
        return value
    replay_raw = payload(component["replay"], "replay")
    replay = wire.decode_parent_replay_value_v1(replay_raw,
        expected_payload_sha256=hashlib.sha256(replay_raw).hexdigest(), max_bytes=MAX_CLOSURE_REQUEST_BYTES)
    replay_fields = {"admission_args", "admission_kwargs", "join_args", "join_kwargs", "toolchain"}
    if reviewed_version == 4:
        replay_fields |= {"instance_identity_profile", "definition_application_profile"}
    _need(type(replay) is dict and set(replay) == replay_fields,
          "complete closed replay arguments required")
    selected_profiles = {}
    if reviewed_version == 4:
        _need(replay["instance_identity_profile"] == "reviewed-source-use/v1"
              and replay["definition_application_profile"] == "whole-norm-definition-expansion/v1",
              "explicit joint source-use whole-norm physical profile required")
        selected_profiles = {key: replay[key] for key in ("instance_identity_profile", "definition_application_profile")}
    _need(type(replay["admission_args"]) is list and type(replay["admission_kwargs"]) is dict,
          "complete reviewed admission replay required")
    args, kwargs = replay["admission_args"], replay["admission_kwargs"]
    admission = ordinary(component["admission"], "admission")
    if reviewed_version in (3, 4):
        version_fence()
    admission = admission_validator(admission, *args,
        expected_report_sha256=pins["admission"], **kwargs)
    _need(admission["semantic_use_eligible"] is True, "current reviewed admission has unresolved blockers")
    declaration = kwargs["preparation_inputs"]["declaration"]
    units = declaration["units"]
    _need(type(request["expected_unit_ids"]) is list
          and [unit["unit_id"] for unit in units] == request["expected_unit_ids"]
          and len(set(request["expected_unit_ids"])) == len(units), "exact complete reviewed unit population required")
    required = set(component.values())
    for unit in units:
        source_id, ir_id = unit["source_artifact_id"], unit["ir_artifact_id"]
        _need(source_id != ir_id and source_id not in required and ir_id not in required,
              "source/IR artifact identities overlap")
        required.update((source_id, ir_id))
        version = ordinary(source_id, "source_version")
        _need(version == unit["source_version"], "source version/edition/occurrence component link differs")
        _need(payload(ir_id, "ir") == kwargs["preparation_inputs"]["relational_inputs"][unit["unit_id"]]["request_raw"],
              "complete typed IR artifact link differs")
    dependency = ordinary(component["dependency"], "dependency")
    _need(dependency == kwargs["preparation_inputs"]["dependency_manifest"], "dependency artifact differs from complete admission replay")
    dependencies.validate_dependency_manifest(dependency,
        expected_manifest_sha256=kwargs["preparation_inputs"]["expected_manifest_sha256"])
    invalidation = dependencies.invalidate_dependencies(dependency,
        expected_manifest_sha256=dependency["manifest_sha256"],
        observed_artifact_sha256s=kwargs["observed_artifact_sha256s"], observed_pins=kwargs["observed_pins"])
    _need(not dependency["missing_dependencies"] and not dependency["cycles"]
          and not invalidation["stale_artifact_ids"], "complete current acyclic dependencies required")
    graph = ordinary(component["graph"], "graph")
    if reviewed_version in (3, 4):
        version_fence()
    graph_validator(graph, admission, *args,
        expected_graph_sha256=pins["graph"], expected_admission_sha256=pins["admission"], **kwargs)
    preparation_raw = payload(component["preservation"], "preservation")
    saved = wire.decode_parent_replay_value_v1(preparation_raw,
        expected_payload_sha256=hashlib.sha256(preparation_raw).hexdigest(), max_bytes=MAX_CLOSURE_REQUEST_BYTES)
    _need(type(saved) is dict and set(saved) == {"manifest_json", "files"}
          and type(saved["files"]) is list and all(type(row) is list and len(row) == 2 for row in saved["files"]),
          "exact complete Lean preservation project required")
    preparation = shared.ReviewedPreservationCorpusPreparation(saved["manifest_json"],
        tuple(tuple(row) for row in saved["files"]))
    if reviewed_version in (3, 4):
        version_fence()
    preparation_validator(preparation, graph, admission, *args,
        expected_preservation_sha256=pins["preservation"], expected_graph_sha256=pins["graph"],
        expected_admission_sha256=pins["admission"], toolchain=replay["toolchain"], **kwargs,
        **({"instance_identity_profile": selected_profiles["instance_identity_profile"]} if selected_profiles else {}))
    join = ordinary(component["source_span_entity_join"], "source_span_entity_join")
    _need(type(replay["join_args"]) is list and len(replay["join_args"]) == 6
          and type(replay["join_kwargs"]) is dict and set(replay["join_kwargs"]) == {"expected_request_sha256"},
          "complete explicit wire-coordinate join-v3 replay required")
    if _retained_paired_cache_files is None:
        joins.validate_source_span_entity_join_manifest_v3(join, *replay["join_args"],
            expected_report_sha256=joins.source_span_entity_join_manifest_sha256(join), **replay["join_kwargs"])
    else:
        _need(reviewed_version == 4 and original_parent_handle is None and request["native"] is None,
              "detached paired-cache replay requires the source-only physical V4 domain")
        _validate_retained_paired_join_v4(join, replay["join_args"], replay["join_kwargs"],
            expected_report_sha256=joins.source_span_entity_join_manifest_sha256(join),
            retained_paired_file_bytes=_retained_paired_cache_files)
    observed_datasets = [join["source_repository"],
        {key: join["span_inventory"][key] for key in ("repository_id", "revision")},
        {key: join["entity_metadata"][key] for key in ("repository_id", "revision")}]
    _need(observed_datasets == [{key: row[key] for key in ("repository_id", "revision")} for row in datasets],
          "law/span/entity immutable revision links differ")
    hf_raw = payload(component["hf_package"], "hf_package")
    package = wire.decode_parent_replay_value_v1(hf_raw,
        expected_payload_sha256=hashlib.sha256(hf_raw).hexdigest(), max_bytes=MAX_CLOSURE_REQUEST_BYTES)
    _need(type(package) is dict and set(package) == {"metadata", "configs", "artifacts"}, "closed existing HF package required")
    metadata = package["metadata"]
    _need(type(metadata) is dict and set(metadata) == set(hf.UscodeHuggingFaceRelease.__dataclass_fields__) - {"configs", "artifacts"},
          "closed existing HF release metadata required")
    _need(type(package["configs"]) is list and 1 <= len(package["configs"]) <= 3
          and type(package["artifacts"]) is list and 1 <= len(package["artifacts"]) <= 64,
          "bounded existing HF package population required")
    release = hf.UscodeHuggingFaceRelease(**metadata,
        configs=tuple(hf.ViewerConfig(**row) for row in package["configs"]),
        artifacts=tuple(hf.ReleaseArtifact(**row) for row in package["artifacts"]))
    package_report = hf.validate_uscode_hf_release(release)
    intake = join["source_metadata_intake"]
    identity = intake["request"]["expected_release_identity"]
    package_manifest = contracts.load_json_bytes(release.artifact(hf.MANIFEST_FILENAME).content,
        expected_sha256=hashlib.sha256(release.artifact(hf.MANIFEST_FILENAME).content).hexdigest())
    _need(release.dataset_id == datasets[0]["repository_id"]
          and release.source_revision == identity["source_revision"]
          and release.release_root_cid == identity["release_root_cid"]
          and release.manifest_digest == identity["manifest_digest"]
          and all(package_manifest.get(key) == value for key, value in identity.items()),
          "HF package/selected source metadata identity link differs")
    package_files = {artifact.relative_path: artifact.content for artifact in release.artifacts}
    _need(all(package_files.get(row["path_in_repo"]) == row["raw_utf8"].encode("utf-8")
              for row in intake["files"]), "HF package/selected source metadata bytes differ")
    if reviewed_version == 4:
        _require_hf_reviewed_graph_v4(
            release, intake["primary_manifest_selection"]["descriptors"], graph["graph"])
    native_report = None
    transport_report = None
    parent_authentication = None
    selection = request["native"]
    if parent_context is not None:
        _need(type(selection) is dict and selection.get("observation_profile") == "retained-native-observation/v1",
              "original parent requires the complete retained-native V3 packet selection")
    _need(reviewed_version != 4 or selection is None,
          "physical V4 source replay cannot acquire Native authority from packet bytes")
    if selection is not None and (reviewed_version == 1 or direct):
        _need(type(selection) is dict and set(selection) == {"receipt", "packet", "expected_packet_sha256", "expected_binary_sha256"},
              "closed exact retained native evidence required")
        _need(selection["receipt"] not in required and selection["packet"] not in required
              and selection["receipt"] != selection["packet"], "native artifact identities overlap")
        required.update((selection["receipt"], selection["packet"]))
        receipt_raw = payload(selection["receipt"], "native_receipt")
        packet_raw = payload(selection["packet"], "native_packet")
        packet = wire.decode_parent_replay_value_v1(packet_raw,
            expected_payload_sha256=hashlib.sha256(packet_raw).hexdigest(), max_bytes=request_limit)
        if direct:
            version_fence()
        selected_receipt_validator = receipt_validator if direct else native.validate_reviewed_norm_preservation_native_receipt_v2
        native_report = selected_receipt_validator(receipt_raw,
            preparation, graph, admission, *args, packet_files=packet,
            expected_receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
            expected_packet_sha256=selection["expected_packet_sha256"],
            expected_binary_sha256=selection["expected_binary_sha256"],
            expected_preservation_sha256=pins["preservation"], expected_graph_sha256=pins["graph"],
            expected_admission_sha256=pins["admission"], toolchain=replay["toolchain"], **kwargs)
    elif selection is not None:
        receipt_raw, packet, transport_report = _release_native_packet_v3(selection, materials, required, contracts, wire)
        if selection["observation_profile"] == "fictional-authored-observation/v1":
            _need(admission["fixture_only"] is True and admission["provenance_kind"] == "fictional_fixture",
                  "fictional observation requires genuinely admitted fictional fixture")
        version_fence()
        native_report = receipt_validator(receipt_raw,
            preparation, graph, admission, *args, packet_files=packet,
            expected_receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
            expected_packet_sha256=selection["expected_packet_sha256"],
            expected_binary_sha256=selection["expected_binary_sha256"],
            expected_preservation_sha256=pins["preservation"], expected_graph_sha256=pins["graph"],
            expected_admission_sha256=pins["admission"], toolchain=replay["toolchain"],
            observation_profile=selection["observation_profile"], **kwargs)
        if parent_context is not None:
            version_fence()
            parent_authentication = _release_original_parent_authentication_v3(parent_context,
                packet, preparation, graph, admission, args, kwargs, native_report=native_report,
                receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
                packet_sha256=selection["expected_packet_sha256"], binary_sha256=selection["expected_binary_sha256"],
                preservation_sha256=pins["preservation"], graph_sha256=pins["graph"],
                admission_sha256=pins["admission"], toolchain=replay["toolchain"], contracts=contracts)
    _need(set(materials) == required, "unreferenced or omitted artifact population")
    if _captured_native_context is not None:
        _need(reviewed_version in (3, 4) and type(_captured_native_context) is list
              and not _captured_native_context, "one internal complete V3 replay context required")
        _captured_native_context.append({
            "reviewed_version": reviewed_version, "core_request_sha256": expected_request_sha256,
            **selected_profiles,
            "preparation": preparation, "graph": graph, "admission": admission,
            "args": tuple(args), "kwargs": kwargs, "pins": dict(pins), "toolchain": replay["toolchain"],
            "native": None if selection is None else {
                "packet_files": packet, "receipt_raw": receipt_raw,
                "expected_packet_sha256": selection["expected_packet_sha256"],
                "expected_binary_sha256": dict(selection["expected_binary_sha256"])}})
    blockers = ["independent_law_span_entity_to_reviewed_source_crosswalk_missing",
                "original_admitted_native_parent_custody_not_established",
                "immutable_remote_Hub_readback_not_established"]
    if not (package_report.get("metadata_profile") == hf.WIRE_METADATA_PROFILE
            and intake.get("metadata_profile") == hf.WIRE_METADATA_PROFILE):
        blockers.insert(0, "production_packaging_to_wire_profile_adapter_not_established")
    if selection is None:
        blockers.append("retained_native_receipt_and_packet_not_provided")
    report = {"schema": report_schema, "profile": profile, **selected_profiles,
        "request_sha256": expected_request_sha256, "datasets": datasets,
        "artifacts": descriptors, "unit_ids": list(request["expected_unit_ids"]),
        "fixture_only": admission["fixture_only"], "provenance_kind": admission["provenance_kind"],
        "local_replay_complete": True, "release_ready": False, "closure_complete": False,
        "blockers": blockers, "hf_package": package_report,
        "source_span_entity_join_sha256": joins.source_span_entity_join_manifest_sha256(join),
        "admission_sha256": pins["admission"], "graph_sha256": pins["graph"],
        "preservation_sha256": pins["preservation"], "native_receipt_replayed": native_report is not None,
        "declared_dependency_invalidation": invalidation,
        "admitted": False, "formalized": False, "proof_verified": False,
        "source_semantics_verified": False, "source_authenticity_verified": False,
        "source_metadata_arrow_bytes_verified": False, "original_native_parent_custody_verified": False,
        "remote_readback_verified": False,
        "model_or_compiler_execution_performed": False}
    if reviewed_version in (3, 4):
        blockers.append("statutory_meaning_and_full_corpus_qualification_not_established")
        manifest = json.loads(preparation.manifest_json)
        report.update(reviewed_version=reviewed_version, native_packet_transport=transport_report,
            signature_headers_by_unit=manifest["signature_headers_by_unit"],
            predicate_compatibility_ledger=manifest["predicate_compatibility_ledger"],
            definition_use_record_cids=manifest["definition_use_record_cids"],
            unit_preservation_bindings=manifest["units"],
            original_parent_handle_consumed=False, native_receipt_authenticated=False,
            release_eligible=False, statutory_meaning_proved=False, gold_verified=False,
            original_success_authenticated=False, source_kernel_receipt_authenticated=False,
            admission_mask=0, release_mask=0, gold_mask=0, training_mask=0, evaluation_gold_mask=0)
        if parent_authentication is not None:
            report.update(profile=_BYTE_PARENT_PROFILE_V3, original_parent_handle_consumed=True,
                native_receipt_authenticated=True, original_native_parent_custody_verified=True,
                original_success_authenticated=True, original_parent_evidence=parent_authentication,
                blockers=[item for item in report["blockers"]
                    if item != "original_admitted_native_parent_custody_not_established"])
    version_fence()
    return report


def validate_uscode_release_closure_v1(request_raw: bytes, *, expected_request_sha256: str) -> dict:
    """Replay the unchanged closed V1 byte-custody profile."""
    return _validate_uscode_release_byte_closure(request_raw,
        expected_request_sha256=expected_request_sha256, reviewed_version=1)


# Explicit successor: the preceding v1 request and implementation stay closed.
CLOSURE_REQUEST_SCHEMA_V2 = "legal-uscode-release-closure-request/v2"
CLOSURE_SCHEMA_V2 = "legal-uscode-release-closure-report/v2"
CLOSURE_PROFILE_V2 = "reviewed-norm-v2-physical-three-cache-replay/v1"
REVIEWED_PHYSICAL_CROSSWALK_SCHEMA = "legal-reviewed-physical-source-crosswalk/v1"
REVIEWED_PHYSICAL_CROSSWALK_PROFILE = "identity-text-complete-reviewed-graph/v1"


def _validate_uscode_release_physical_closure(request_raw: bytes, *, expected_request_sha256: str,
        reviewed_version: int, _observe_checked_context=None, _native_transport="chunk-index/v1",
        original_parent_handle=None, replay_retained_artifacts=False, _retained_paired_cache_files=None) -> dict:
    """Replay a reviewed, exact physical law/span/entity-to-IR component.

    Crosswalk bytes are versioned cross-reference dependencies of every reviewed
    unit, covered by the existing independent meaning/context review. Selectors
    contain stable addresses, never admission-dependent graph CIDs. Resolution
    happens only after genuine admission and complete graph replay. Local files
    are read through their existing owners while independent open descriptors
    retain byte/stat custody. This is no remote, native or corpus admission.
    """
    parent_context = None
    parent_callback_states = None
    if original_parent_handle is not None:
        _release_v3_policy()
        if original_parent_handle is not None:
            entry_guard = _release_original_parent_entry_guard_v3
            if (entry_guard is not _RELEASE_ORIGINAL_PARENT_ENTRY_GUARD_V3
                    or entry_guard.__code__ is not _RELEASE_ORIGINAL_PARENT_ENTRY_CODE_V3):
                raise ReleaseCoordinatorError("original-parent coordinator entry generation changed: entry guard")
            entry_guard()
        _need(original_parent_handle is None or reviewed_version == 3, "original parent requires the explicit V3 domain")
        parent_context = (_release_original_parent_context_v3(original_parent_handle)
            if original_parent_handle is not None else None)
        parent_callback_states = (_release_callback_states_v3((_release_original_parent_context_v3,
            _release_original_parent_fence_v3, _release_original_parent_authentication_v3))
            if parent_context is not None else None)
    from contextlib import ExitStack, contextmanager
    import os
    import stat
    from . import corpus_contracts as contracts
    from . import legal_corpus_definition_use_lake_v2 as wire
    from . import legal_entity_index_intake as entity_owner
    from . import uscode_ingest as coordinates
    from ...optimizers.logic_theorem_optimizer import uscode_dataset as law_owner
    from ...processors.legal_data import uscode_hf_release as hf

    _need(type(reviewed_version) is int and reviewed_version in (2, 3, 4),
          "explicit supported physical reviewed closure version required")
    _need(type(replay_retained_artifacts) is bool and (not replay_retained_artifacts or reviewed_version == 4),
          "retained physical artifact replay requires the explicit V4 domain")
    _need(type(_native_transport) is str and _native_transport in ("chunk-index/v1", "direct-packet/v1"),
          "explicit supported physical native transport required")
    direct = _native_transport == "direct-packet/v1"
    _need(not direct or reviewed_version in (3, 4), "direct packet requires its explicit V3 domain")
    if reviewed_version in (3, 4):
        _release_v3_policy()
        if direct:
            _release_direct_v3_policy()
    if _observe_checked_context is not None:
        _need(reviewed_version in (3, 4) and type(_observe_checked_context) is _types.FunctionType,
              "one finite internal V3 context observer required")
        _joined_release_guard()
    joined_guard = _joined_release_guard
    joined_guard_code = joined_guard.__code__
    joined_guard_defaults = joined_guard.__defaults__
    joined_guard_kwdefaults = joined_guard.__kwdefaults__

    def observer_owner_fence():
        _need(_joined_release_guard is joined_guard
              and joined_guard.__code__ is joined_guard_code
              and joined_guard.__defaults__ is joined_guard_defaults
              and joined_guard.__kwdefaults__ is joined_guard_kwdefaults,
              "joined guard changed during physical observation")
        joined_guard()

    if reviewed_version == 4:
        _release_v4_policy()
        _need(direct, "source-use physical V4 requires explicit direct transport")
        request_schema, report_schema, profile = (CLOSURE_REQUEST_SCHEMA_V4, CLOSURE_SCHEMA_V4, CLOSURE_PROFILE_V4)
        core_request_schema, core_profile = _BYTE_REQUEST_SCHEMA_V4, _BYTE_PROFILE_V4
    elif reviewed_version == 2:
        request_schema, report_schema, profile = (
            CLOSURE_REQUEST_SCHEMA_V2, CLOSURE_SCHEMA_V2, CLOSURE_PROFILE_V2)
        core_request_schema, core_profile = CLOSURE_REQUEST_SCHEMA, CLOSURE_PROFILE
    else:
        request_schema, report_schema, profile = (
            CLOSURE_REQUEST_SCHEMA_V3, CLOSURE_SCHEMA_V3,
            CLOSURE_PROFILE_V3_DIRECT if direct else CLOSURE_PROFILE_V3)
        core_request_schema, core_profile = _BYTE_REQUEST_SCHEMA_V3, (_BYTE_PROFILE_V3_DIRECT if direct else _BYTE_PROFILE_V3)

    def selected_core():
        if reviewed_version == 4:
            return _validate_uscode_release_byte_closure_v4
        return (validate_uscode_release_closure_v1 if reviewed_version == 2
                else _validate_uscode_release_byte_closure_v3)

    core_validator = selected_core()

    # These are the added physical delegates, not a complete execution/library
    # attestation. Selected reviewed owners retain their own opening/closing pins.
    def physical_owner_snapshot():
        result = {}
        for source_path in (Path(__file__), Path(law_owner.__file__),
                            Path(coordinates.__file__), Path(entity_owner.__file__)):
            source_path = source_path.resolve(strict=True)
            info = source_path.lstat()
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                  and 0 < info.st_size <= 2 * 1024 * 1024,
                  "bounded unaliased physical delegate source required")
            raw = source_path.read_bytes()
            identity = [getattr(info, key) for key in ("st_dev", "st_ino", "st_mode",
                "st_nlink", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns")]
            after = source_path.lstat()
            _need(identity == [getattr(after, key) for key in ("st_dev", "st_ino", "st_mode",
                "st_nlink", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns")]
                and len(raw) == info.st_size, "physical delegate source changed during snapshot")
            result[str(source_path)] = {"sha256": hashlib.sha256(raw).hexdigest(), "identity": identity}
        return result
    physical_generation = physical_owner_snapshot()
    physical_callbacks = (law_owner.capture_uscode_source_documents_from_parquet,
        coordinates.validate_uscode_source_coordinates, entity_owner.iter_observed_rows,
        core_validator, _validate_uscode_release_byte_closure)
    physical_callback_states = (_release_callback_states_v3(physical_callbacks) if reviewed_version in (3, 4) else None)
    def physical_owner_fence():
        _need(physical_owner_snapshot() == physical_generation,
              "physical delegate source generation changed during complete replay")
        current = (law_owner.capture_uscode_source_documents_from_parquet,
            coordinates.validate_uscode_source_coordinates, entity_owner.iter_observed_rows,
            selected_core(), _validate_uscode_release_byte_closure)
        if reviewed_version in (3, 4):
            _release_v3_policy()
        _need(all(left is right for left, right in zip(current, physical_callbacks, strict=True)),
              "physical delegate callback changed during complete replay")
        if reviewed_version in (3, 4):
            _release_callback_fence_v3(current, physical_callback_states)
        if parent_context is not None:
            _release_callback_fence_v3((_release_original_parent_context_v3,
                _release_original_parent_fence_v3, _release_original_parent_authentication_v3), parent_callback_states)
            _release_original_parent_fence_v3(parent_context)

    def same(left, right):
        return _canonical(left) == _canonical(right)

    def keys(value, fields, label):
        _need(type(value) is dict and set(value) == set(fields), "closed " + label + " required")

    def integer(value, minimum, maximum, label):
        _need(type(value) is int and minimum <= value <= maximum,
              "bounded nonboolean integer required: " + label)
        return value

    def text(value, label):
        _need(type(value) is str and 0 < len(value.encode("utf-8")) <= 4096,
              "bounded exact text required: " + label)
        return value

    request_limit = (MAX_CLOSURE_REQUEST_BYTES_V3 if direct
                     else MAX_CLOSURE_REQUEST_BYTES)
    artifact_total_limit = (MAX_CLOSURE_ARTIFACT_TOTAL_BYTES_V3 if direct
                            else MAX_CLOSURE_REQUEST_BYTES)
    request = wire.decode_parent_replay_value_v1(request_raw,
        expected_payload_sha256=expected_request_sha256, max_bytes=request_limit)
    keys(request, {"schema", "profile", "datasets", "expected_artifact_ids", "artifacts",
        "expected_unit_ids", "component", "pins", "native", "physical_inputs"}, "physical closure request")
    _need(request["schema"] == request_schema and request["profile"] == profile,
          "unsupported physical closure schema/profile")
    physical_inputs = request["physical_inputs"]
    keys(physical_inputs, {"law_path", "entity_path"}, "retained physical inputs")
    if replay_retained_artifacts:
        _need(request["native"] is None, "retained physical artifact replay cannot acquire Native authority")
        for spelling in physical_inputs.values():
            path = Path(text(spelling, "original physical path"))
            _need(path.anchor == os.sep and ".." not in path.parts,
                  "literal absolute original physical path required")
    component, pins = request["component"], request["pins"]
    extra_roles = {"reviewed_crosswalk", "entity_parquet"}
    base_roles = {"admission", "graph", "dependency", "preservation", "replay", "hf_package", "source_span_entity_join"}
    keys(component, base_roles | extra_roles, "physical component roles")
    _need(all(type(value) is str for value in component.values())
          and len(set(component.values())) == len(component), "distinct physical artifact roles required")
    keys(pins, {"admission", "graph", "preservation", "reviewed_crosswalk"}, "physical component pins")
    for pin in pins.values():
        contracts.require_sha256(pin, "independent physical component SHA256")
    rows = request["artifacts"]
    _need(type(rows) is list and 1 <= len(rows) <= 64, "bounded complete physical artifact population required")
    materials = {}
    total = 0
    for row in rows:
        keys(row, {"artifact_id", "family", "sha256", "bytes", "payload"}, "physical artifact descriptor")
        identity = text(row["artifact_id"], "artifact identity")
        _need(len(identity.encode("utf-8")) <= 512, "existing bounded artifact identity required")
        raw = row["payload"]
        artifact_limit = (MAX_CLOSURE_NATIVE_PACKET_BYTES_V3
                          if direct and row["family"] == "native_packet"
                          else _MAX_ARTIFACT_BYTES)
        _need(identity not in materials and type(row["family"]) is str and type(raw) is bytes
              and 0 < len(raw) <= artifact_limit, "unique bounded physical artifact required")
        integer(row["bytes"], 1, artifact_limit, "artifact bytes")
        contracts.require_sha256(row["sha256"], "physical artifact SHA256")
        _need(row["bytes"] == len(raw) and hashlib.sha256(raw).hexdigest() == row["sha256"],
              "physical artifact bytes differ")
        total += len(raw)
        _need(total <= artifact_total_limit, "physical artifact population exceeds existing byte ceiling")
        materials[identity] = row
    _need(type(request["expected_artifact_ids"]) is list
          and same(list(materials), request["expected_artifact_ids"]), "physical artifact order or membership differs")
    def artifact(role, family):
        row = materials.get(component[role])
        _need(row is not None and row["family"] == family, "physical component artifact omitted or family changed: " + role)
        return row["payload"]

    crosswalk_raw = artifact("reviewed_crosswalk", "reviewed_crosswalk")
    _need(hashlib.sha256(crosswalk_raw).hexdigest() == pins["reviewed_crosswalk"],
          "independent reviewed crosswalk pin differs")
    crosswalk = contracts.load_json_bytes(crosswalk_raw, expected_sha256=pins["reviewed_crosswalk"])
    _need(_canonical(crosswalk) == crosswalk_raw, "exact canonical reviewed crosswalk bytes required")
    keys(crosswalk, {"schema", "profile", "datasets", "law", "entity", "units", "span_rows", "entity_rows"},
         "reviewed physical crosswalk")
    _need(crosswalk["schema"] == REVIEWED_PHYSICAL_CROSSWALK_SCHEMA
          and crosswalk["profile"] == REVIEWED_PHYSICAL_CROSSWALK_PROFILE,
          "unsupported reviewed physical crosswalk profile")
    _need(same(crosswalk["datasets"], request["datasets"]), "crosswalk law/span/entity revision namespace differs")
    law_selection, entity_selection = crosswalk["law"], crosswalk["entity"]
    keys(law_selection, {"artifact_path", "file_sha256", "file_bytes", "row_offset", "rows",
        "release_id", "coordinate_report_sha256"}, "physical law selection")
    keys(entity_selection, {"file_sha256", "file_bytes", "rows", "projection"}, "physical entity selection")
    for selection in (law_selection, entity_selection):
        contracts.require_sha256(selection["file_sha256"], "selected physical file SHA256")
        integer(selection["file_bytes"], 1, _MAX_ARTIFACT_BYTES, "selected physical file bytes")
    integer(law_selection["row_offset"], 0, 10_000_000, "law row offset")
    integer(law_selection["rows"], 1, law_owner.RAW_USCODE_MAX_ROWS, "complete selected law rows")
    integer(entity_selection["rows"], 1, 12_288, "complete selected entity rows")
    contracts.require_sha256(law_selection["coordinate_report_sha256"], "complete coordinate report SHA256")
    text(law_selection["release_id"], "source-coordinate release")
    _need(entity_selection["projection"] == "complete_reviewed_norm_graph_nodes_and_edges/v1",
          "complete reviewed graph projection profile required")
    entity_raw = artifact("entity_parquet", "entity_parquet")
    _need(len(entity_raw) == entity_selection["file_bytes"]
          and hashlib.sha256(entity_raw).hexdigest() == entity_selection["file_sha256"],
          "reviewed entity artifact identity differs")

    # Delegate all established source/IR/review/graph/dependency/Lean-text logic.
    # Removing only the two new roles retains the core's exact complete artifact check.
    excluded = {component[role] for role in extra_roles}
    core = {key: value for key, value in request.items() if key != "physical_inputs"}
    core.update(schema=core_request_schema, profile=core_profile,
        component={key: component[key] for key in base_roles},
        pins={key: pins[key] for key in ("admission", "graph", "preservation")},
        artifacts=[row for row in rows if row["artifact_id"] not in excluded],
        expected_artifact_ids=[identity for identity in request["expected_artifact_ids"] if identity not in excluded])
    core_raw = wire.encode_parent_replay_value_v1(core, max_bytes=request_limit)
    core_sha = hashlib.sha256(core_raw).hexdigest()

    def core_replay(capture=None):
        if parent_context is not None:
            return core_validator(core_raw, expected_request_sha256=core_sha,
                _captured_native_context=capture, _native_transport=_native_transport,
                original_parent_handle=original_parent_handle, _original_parent_context=parent_context)
        if _retained_paired_cache_files is not None:
            _need(reviewed_version == 4 and replay_retained_artifacts,
                  "detached paired-cache files require physical V4 retained replay")
            return core_validator(core_raw, expected_request_sha256=core_sha,
                _captured_native_context=capture, _native_transport=_native_transport,
                _retained_paired_cache_files=_retained_paired_cache_files)
        if reviewed_version in (3, 4):
            return core_validator(core_raw, expected_request_sha256=core_sha,
                _captured_native_context=capture, _native_transport=_native_transport)
        return core_validator(core_raw, expected_request_sha256=core_sha)

    def decoded(role, family):
        raw = artifact(role, family)
        return wire.decode_parent_replay_value_v1(raw, expected_payload_sha256=hashlib.sha256(raw).hexdigest(),
            max_bytes=MAX_CLOSURE_REQUEST_BYTES)

    def ordinary(role, family):
        raw = artifact(role, family)
        return contracts.load_json_bytes(raw, expected_sha256=hashlib.sha256(raw).hexdigest())

    replay = decoded("replay", "replay")
    _need(type(replay) is dict and type(replay.get("admission_kwargs")) is dict,
          "complete reviewed physical replay required")
    kwargs = replay["admission_kwargs"]
    declaration = kwargs["preparation_inputs"]["declaration"]
    unit_ids = [unit["unit_id"] for unit in declaration["units"]]
    crosswalk_id = component["reviewed_crosswalk"]
    references = [ref for ref in declaration["cross_references"] if ref["dependency_artifact_id"] == crosswalk_id]
    _need([ref["from_unit_id"] for ref in references] == unit_ids
          and all(ref["dependency_sha256"] == pins["reviewed_crosswalk"]
              and ref["version"] == REVIEWED_PHYSICAL_CROSSWALK_PROFILE for ref in references),
          "each complete reviewed unit must bind the exact versioned crosswalk dependency once")
    _need(kwargs["evidence_artifacts"].get(crosswalk_id) == crosswalk_raw
          and kwargs["observed_artifact_sha256s"].get(crosswalk_id) == pins["reviewed_crosswalk"],
          "reviewed crosswalk body/current dependency observation absent or changed")
    package = decoded("hf_package", "hf_package")
    release = hf.UscodeHuggingFaceRelease(**package["metadata"],
        configs=tuple(hf.ViewerConfig(**row) for row in package["configs"]),
        artifacts=tuple(hf.ReleaseArtifact(**row) for row in package["artifacts"]))
    law_artifact = release.artifact(text(law_selection["artifact_path"], "law package artifact path"))
    _need(law_artifact.relative_path == law_owner.USCODE_LAWS_PARQUET
          and law_artifact.family == "receipt" and law_artifact.config_name == hf.LEGACY_CONFIG_NAME
          and law_artifact.schema_id == "uscode-legacy-parquet/v1"
          and law_artifact.media_type == hf.PARQUET_MEDIA_TYPE
          and law_artifact.sha256 == law_selection["file_sha256"]
          and len(law_artifact.content) == law_selection["file_bytes"],
          "selected physical law must be the existing descriptor-bound legacy laws artifact")

    @contextmanager
    def held_file(spelling, expected):
        text(spelling, "retained local physical path")
        path = Path(spelling)
        _need(path.is_absolute() and path.resolve(strict=True) == path, "literal unaliased retained physical path required")
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        post_open_error = None
        try:
            # Every operation after acquisition, including the initial fstat,
            # is inside the unconditional descriptor-close scope.
            primary = None
            identity_keys = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns")
            def identity(value):
                return tuple(getattr(value, key) for key in identity_keys)
            before = os.fstat(fd)
            def check():
                _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == len(expected),
                      "exact bounded single-link retained physical file required")
                _need(identity(before) == identity(os.fstat(fd)) == identity(path.lstat())
                      and path.resolve(strict=True) == path, "retained physical file generation changed")
                os.lseek(fd, 0, os.SEEK_SET)
                raw = bytearray()
                while len(raw) <= len(expected):
                    chunk = os.read(fd, min(1024 * 1024, len(expected) + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                _need(bytes(raw) == expected, "retained physical file differs from exact reviewed artifact bytes")
                _need(identity(before) == identity(os.fstat(fd)) == identity(path.lstat()),
                      "retained physical file changed during byte verification")
            try:
                check()
                yield path, check
            except BaseException as error:
                primary = error
                if error is not observer_error and not closing_failures:
                    closing_failures.append(error)
                raise
            finally:
                _physical_complete_checks_v1(
                    (("retained physical final descriptor fence", check),),
                    primary=primary, _closing_failures=closing_failures)
        except BaseException as error:
            post_open_error = error
            if error is not observer_error and not closing_failures:
                closing_failures.append(error)
            raise
        finally:
            _physical_complete_checks_v1(
                (("retained physical descriptor close", lambda: os.close(fd)),),
                primary=post_open_error, _closing_failures=closing_failures)

    pending_error = None
    observer_error = None
    closing_failures = []
    try:
        with ExitStack() as stack:
            paths = physical_inputs
            if replay_retained_artifacts:
                from tempfile import TemporaryDirectory

                # The exact request already carries both descriptor-bound
                # Parquet bodies. Its original locators stay in the hashed wire.
                directory = Path(stack.enter_context(
                    TemporaryDirectory(prefix="legal-v4-retained-physical-"))).resolve(strict=True)
                paths = {}
                for role, filename, content in (("law_path", "laws.parquet", law_artifact.content),
                                                 ("entity_path", "entity.parquet", entity_raw)):
                    path = directory / filename
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(content)
                    paths[role] = str(path)
            law_path, law_fence = stack.enter_context(held_file(paths["law_path"], law_artifact.content))
            entity_path, entity_fence = stack.enter_context(held_file(paths["entity_path"], entity_raw))
            captured_context = []
            if _observe_checked_context is None:
                opened = core_replay()
            else:
                opened = core_replay(captured_context)
                _need(len(captured_context) == 1, "one complete checked physical replay context required")
            join = ordinary("source_span_entity_join", "source_span_entity_join")
            graph = ordinary("graph", "graph")
            _need(join["source_repository"] == {key: request["datasets"][0][key] for key in ("repository_id", "revision")}
                  and same(join["entity_metadata"]["declared_rows"], entity_selection["rows"]),
                  "actual law/entity selection differs from selected namespace metadata")
            bundles = join["paired_bundles"]
            _need(type(bundles) is list and len(bundles) == 1, "one complete existing coordinate bundle required")
            carrier = bundles[0]["payload_intake"]["source_coordinates"]
            coordinate_report = contracts.load_json_bytes(carrier["report_raw_utf8"].encode("utf-8"),
                expected_sha256=carrier["report_artifact_sha256"])
            _need(carrier["report_sha256"] == law_selection["coordinate_report_sha256"],
                  "joined complete coordinate report differs from reviewed crosswalk")
            capture_args = dict(source_revision=request["datasets"][0]["revision"],
                source_path_in_repo=law_artifact.relative_path, expected_sha256=law_artifact.sha256,
                expected_bytes=len(law_artifact.content), offset=law_selection["row_offset"],
                limit=law_selection["rows"], release_id=law_selection["release_id"])
            captured = law_owner.capture_uscode_source_documents_from_parquet(law_path, **capture_args)
            def coordinate_replay():
                coordinates.validate_uscode_source_coordinates(coordinate_report, captured["documents"],
                    expected_report_sha256=law_selection["coordinate_report_sha256"],
                    query=coordinate_report["query"], release_id=law_selection["release_id"],
                    limits=coordinate_report["limits"])
            coordinate_replay()
            unit_maps = crosswalk["units"]
            _need(type(unit_maps) is list and len(unit_maps) == len(unit_ids), "complete ordered reviewed unit crosswalk required")
            unit_inputs = kwargs["preparation_inputs"]["source_inputs"]
            document_use = set()
            unit_lookup, unit_bindings = {}, []
            for unit, selected in zip(declaration["units"], unit_maps, strict=True):
                keys(selected, {"unit_id", "source_version_cid", "source_occurrence_cid", "document_revision",
                    "input_document_ordinal", "law_row_ordinal"}, "reviewed physical unit binding")
                ordinal = integer(selected["input_document_ordinal"], 0, len(captured["documents"]) - 1, "law document ordinal")
                document = captured["documents"][ordinal]
                integer(selected["law_row_ordinal"], 0, 10_000_000, "physical law row ordinal")
                _need(same({key: selected[key] for key in ("unit_id", "document_revision")},
                          {key: unit[key] for key in ("unit_id", "document_revision")})
                      and selected["source_version_cid"] == unit["source_version"]["record_cid"]
                      and selected["source_occurrence_cid"] == unit["occurrence"]["record_cid"]
                      and selected["law_row_ordinal"] == document["source_witness"]["physical_row_ordinal"],
                      "reviewed unit source/version/occurrence/revision or physical row differs")
                source_input = unit_inputs[unit["unit_id"]]
                view = unit["source_version"]["extracted_view"]
                _need(view["extraction_profile"] == view["normalization_profile"] == "identity/v1"
                      and source_input["raw_bytes"] == document["text"].encode("utf-8")
                      and source_input["extracted_text"] == document["text"],
                      "supported identity raw/view source must exactly match the complete captured law text")
                # Existing reviewed admission already validated both UTF8 and character
                # selectors. Keep the full occurrence, including delimiter whitespace.
                occurrence = unit["occurrence"]
                unit_lookup[unit["unit_id"]] = (ordinal, occurrence)
                document_use.add(ordinal)
                unit_bindings.append({**selected, "legal_id": document["legal_id"],
                    "source_witness": document["source_witness"], "start_char": occurrence["start_char"],
                    "end_char": occurrence["end_char"], "start_utf8": occurrence["start_utf8"],
                    "end_utf8": occurrence["end_utf8"]})
            _need(document_use == set(range(len(captured["documents"]))),
                  "selected physical law row omitted from complete reviewed unit population")
            selected_spans, span_bindings = set(), []
            span_maps = crosswalk["span_rows"]
            physical_rows = join["physical_rows"]
            _need(type(span_maps) is list and len(span_maps) == len(physical_rows), "complete ordered paired-cache physical crosswalk required")
            by_identity = {}
            for ref in join["row_references"]:
                identity = ref["physical_identity_sha256"]
                if identity in by_identity:
                    _need(same(by_identity[identity], ref), "conflicting duplicate physical cache reference")
                by_identity[identity] = ref
            for physical, selected in zip(physical_rows, span_maps, strict=True):
                keys(selected, {"physical_identity_sha256", "row_sha256", "source_coordinate_span_index", "unit_ids"},
                     "reviewed cache-span binding")
                identity = physical["physical_identity_sha256"]
                _need(selected["physical_identity_sha256"] == identity and selected["row_sha256"] == physical["row_sha256"],
                      "reviewed paired-cache physical identity or row bytes differ")
                ref = by_identity[identity]
                index = integer(selected["source_coordinate_span_index"], 0, len(coordinate_report["spans"]) - 1,
                    "original source-coordinate span index")
                _need(index == ref["source_coordinate_span_index"], "paired-cache original coordinate occurrence differs")
                span = coordinate_report["spans"][index]
                expected_units = [unit_id for unit_id in unit_ids
                    if unit_lookup[unit_id][0] == span["input_document_ordinal"]
                    and max(unit_lookup[unit_id][1]["start_char"], span["source_char_start"])
                        < min(unit_lookup[unit_id][1]["end_char"], span["source_char_end"])]
                _need(expected_units and same(selected["unit_ids"], expected_units),
                      "paired-cache row must bind every exact overlapping reviewed occurrence")
                selected_spans.add(index)
                span_bindings.append({**selected, "source_span_id": span["source_span_id"],
                    "physical_identity": physical["physical_identity"]})
            for binding in unit_bindings:
                ordinal, occurrence = unit_lookup[binding["unit_id"]]
                expected = [index for index, span in enumerate(coordinate_report["spans"])
                    if span["input_document_ordinal"] == ordinal
                    and max(occurrence["start_char"], span["source_char_start"])
                        < min(occurrence["end_char"], span["source_char_end"])]
                _need(expected and set(expected) <= selected_spans, "reviewed source occurrence has an uncached span or omitted clause")
                text_body = captured["documents"][ordinal]["text"]
                frontier = occurrence["start_char"]
                gaps = []
                for index in expected:
                    span = coordinate_report["spans"][index]
                    start, end = max(occurrence["start_char"], span["source_char_start"]), min(occurrence["end_char"], span["source_char_end"])
                    if start > frontier:
                        gap = text_body[frontier:start]
                        _need(gap.isspace(), "nonwhitespace reviewed source clause is not covered by cache spans")
                        gaps.append({"start_char": frontier, "end_char": start, "utf8_bytes": len(gap.encode("utf-8"))})
                    frontier = max(frontier, end)
                if frontier < occurrence["end_char"]:
                    gap = text_body[frontier:occurrence["end_char"]]
                    _need(gap.isspace(), "nonwhitespace reviewed source suffix is not covered by cache spans")
                    gaps.append({"start_char": frontier, "end_char": occurrence["end_char"], "utf8_bytes": len(gap.encode("utf-8"))})
                binding.update(source_coordinate_span_indices=expected, exact_unspanned_whitespace=gaps)

            entity_maps = crosswalk["entity_rows"]
            _need(type(entity_maps) is list and len(entity_maps) == entity_selection["rows"],
                  "complete materialized entity-row mapping required")
            # Retain only canonical raw rows, not the repeated full per-file footer
            # metadata carried by every original observation.
            observed = [{"ordinal": observation["ordinal"], "raw_row_sha256": observation["raw_row_sha256"],
                         "raw_row": observation["raw_row"]}
                for observation in entity_owner.iter_observed_rows(entity_path,
                    expected_file_sha256=entity_selection["file_sha256"], expected_rows=entity_selection["rows"],
                    max_rows=12_288, batch_size=128, revision=request["datasets"][2]["revision"],
                    max_file_bytes=_MAX_ARTIFACT_BYTES, max_decoded_bytes=MAX_CLOSURE_REQUEST_BYTES,
                    max_row_group_bytes=MAX_CLOSURE_REQUEST_BYTES, max_batch_bytes=_MAX_ARTIFACT_BYTES)]
            _need(len(observed) == len(entity_maps), "complete entity traversal differs")
            graph_nodes, graph_edges = graph["graph"]["nodes"], graph["graph"]["edges"]
            by_node_id, node_cids, edge_cids, entity_bindings = {}, set(), set(), []
            def node_selection(selector):
                keys(selector, {"kind", "node_type", "stable_id"}, "stable reviewed graph node selector")
                _need(selector["kind"] == "node", "node selector kind differs")
                kind, stable = text(selector["node_type"], "graph node type"), selector["stable_id"]
                if stable is None:
                    _need(kind == "scope", "only the explicit scope singleton may omit its admission-dependent stable ID")
                    matches = [node for node in graph_nodes if node["node_type"] == kind]
                else:
                    text(stable, "stable graph address")
                    matches = [node for node in graph_nodes if node["node_type"] == kind and node["stable_id"] == stable]
                _need(len(matches) == 1, "stable reviewed graph selector is absent or ambiguous")
                return matches[0]
            # Resolve nodes first; physical row order need not place every node before edges.
            for observation, selected in zip(observed, entity_maps, strict=True):
                keys(selected, {"row_ordinal", "row_sha256", "selector"}, "reviewed entity physical row")
                integer(selected["row_ordinal"], 0, len(observed) - 1, "entity physical row ordinal")
                _need(selected["row_ordinal"] == observation["ordinal"]
                      and selected["row_sha256"] == observation["raw_row_sha256"], "reviewed entity row identity differs")
                selector, row = selected["selector"], observation["raw_row"]
                _need(type(selector) is dict and selector.get("kind") in ("node", "edge"), "supported explicit entity graph selector required")
                if selector["kind"] == "node":
                    node = node_selection(selector)
                    identity = text(row["node_id"], "physical entity node ID")
                    _need(row["record_kind"] == "node" and row["graph_kind"] == node["node_type"]
                          and row["src"] == row["dst"] == "" and identity not in by_node_id
                          and node["record_cid"] not in node_cids, "entity node projection is duplicated or structurally inconsistent")
                    by_node_id[identity] = node
                    node_cids.add(node["record_cid"])
            for observation, selected in zip(observed, entity_maps, strict=True):
                selector, row = selected["selector"], observation["raw_row"]
                if selector["kind"] == "node":
                    node = by_node_id[row["node_id"]]
                    entity_bindings.append({**selected, "physical_node_id": row["node_id"],
                        "graph_record_cid": node["record_cid"], "semantic_companion_record_cid": node["content_cid"]})
                    continue
                keys(selector, {"kind", "src_node_id", "dst_node_id", "relation", "ordinal"}, "stable reviewed graph edge selector")
                left, right = selector["src_node_id"], selector["dst_node_id"]
                _need(type(left) is str and type(right) is str and left in by_node_id and right in by_node_id,
                      "reviewed entity edge endpoint omitted from physical node population")
                text(selector["relation"], "reviewed graph relation")
                ordinal = selector["ordinal"]
                _need(ordinal is None or type(ordinal) is int and 0 <= ordinal <= 8192,
                      "nonboolean reviewed graph edge ordinal required")
                _need(row["record_kind"] == "edge" and row["node_id"] == ""
                      and row["src"] == left and row["dst"] == right and row["graph_kind"] == selector["relation"],
                      "entity edge projection fields differ from exact reviewed selectors")
                matches = [edge for edge in graph_edges if edge["src_cid"] == by_node_id[left]["record_cid"]
                    and edge["dst_cid"] == by_node_id[right]["record_cid"] and edge["relation"] == selector["relation"]
                    and same(edge["ordinal"], ordinal)]
                _need(len(matches) == 1 and matches[0]["record_cid"] not in edge_cids,
                      "reviewed graph edge is missing ambiguous or duplicated")
                edge = matches[0]
                edge_cids.add(edge["record_cid"])
                entity_bindings.append({**selected, "graph_record_cid": edge["record_cid"],
                    "semantic_companion_record_cids": edge["evidence_cids"]})
            _need(node_cids == {node["record_cid"] for node in graph_nodes}
                  and edge_cids == {edge["record_cid"] for edge in graph_edges},
                  "materialized entity mapping must exhaust the complete reviewed graph node and edge populations")
            if _observe_checked_context is None:
                # Close the original generation, not a freshly repinned replacement.
                if reviewed_version in (3, 4):
                    physical_owner_fence()
                _need(same(captured, law_owner.capture_uscode_source_documents_from_parquet(law_path, **capture_args)),
                      "physical law capture changed during complete crosswalk traversal")
                coordinate_replay()
                law_fence()
                entity_fence()
                if reviewed_version in (3, 4):
                    physical_owner_fence()
                closed = core_replay()
                _need(same(opened, closed), "complete source/IR/cache/graph/review generation changed during physical replay")
            else:
                context = captured_context[0]
                context["physical_request_sha256"] = expected_request_sha256
                identity_keys = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid",
                                 "st_size", "st_mtime_ns", "st_ctime_ns")
                law_fence()
                entity_fence()
                context["physical_files"] = (
                    (str(law_path), tuple(getattr(law_path.lstat(), key) for key in identity_keys),
                     law_artifact.content),
                    (str(entity_path), tuple(getattr(entity_path.lstat(), key) for key in identity_keys),
                     entity_raw))
                context_snapshot = _physical_replay_context_snapshot(context)
                closed_state = {}

                def close_law():
                    observer_owner_fence()
                    _need(same(captured, law_owner.capture_uscode_source_documents_from_parquet(law_path, **capture_args)),
                          "physical law capture changed during complete crosswalk traversal")

                def close_coordinates():
                    observer_owner_fence()
                    coordinate_replay()

                def close_core():
                    observer_owner_fence()
                    current = core_replay()
                    _need(same(opened, current),
                          "complete source/IR/cache/graph/review generation changed during physical replay")
                    closed_state["report"] = current

                def close_context():
                    observer_owner_fence()
                    _need(_physical_replay_context_snapshot(context) == context_snapshot,
                          "complete current replay inputs changed during physical observation")

                observer_error = None
                try:
                    # The return is deliberately ignored; observation grants no authority.
                    _observe_checked_context(context)
                except BaseException as error:
                    observer_error = error
                finally:
                    # A failed check does not skip independent closing custody checks.
                    _physical_complete_checks_v1((
                        ("law recapture", close_law),
                        ("source coordinates", close_coordinates),
                        ("law descriptor", law_fence),
                        ("entity descriptor", entity_fence),
                        ("complete core replay", close_core),
                        ("physical Source generation", physical_owner_fence),
                        ("complete observer inputs", close_context),
                        ("loaded owners", observer_owner_fence)),
                        primary=observer_error, _closing_failures=closing_failures)
                if observer_error is not None:
                    raise observer_error
                closed = closed_state["report"]
            report = dict(closed)
            report.update(schema=report_schema,
                profile=CLOSURE_PARENT_PROFILE_V3 if parent_context is not None else profile,
                request_sha256=expected_request_sha256,
                artifacts=[{key: row[key] for key in ("artifact_id", "family", "sha256", "bytes")} for row in rows],
                blockers=[blocker for blocker in closed["blockers"]
                    if blocker != "independent_law_span_entity_to_reviewed_source_crosswalk_missing"],
                local_source_cache_entity_bindings_verified=True,
                independent_reviewed_crosswalk_verified=True,
                physical_owner_pins={path: row["sha256"] for path, row in physical_generation.items()},
                physical_owner_pin_scope="four_named_physical_delegate_sources_only_not_complete_execution_attestation",
                reviewed_crosswalk_sha256=pins["reviewed_crosswalk"],
                physical_crosswalk={"profile": REVIEWED_PHYSICAL_CROSSWALK_PROFILE,
                    "scope": "complete_declared_reviewed_component_and_selected_physical_cache_population",
                    "law": law_selection, "entity": entity_selection, "unit_bindings": unit_bindings,
                    "span_bindings": span_bindings, "entity_bindings": entity_bindings,
                    "counts": {"law_rows": len(captured["documents"]), "reviewed_units": len(unit_bindings),
                        "paired_cache_rows": len(span_bindings), "entity_rows": len(observed),
                        "graph_nodes": len(node_cids), "graph_edges": len(edge_cids)},
                    "candidate_formal_outputs_semantically_reviewed": False,
                    "surface_labels_used_as_semantic_identity": False,
                    "legacy_boolean_flags_used_as_admission": False,
                    "remote_revision_authenticated": False},
                release_ready=False, closure_complete=False, admitted=False, formalized=False, proof_verified=False)
            wire.encode_parent_replay_value_v1(report, max_bytes=MAX_CLOSURE_REQUEST_BYTES)
            physical_owner_fence()
    except BaseException as error:
        pending_error = error
        if error is not observer_error and not closing_failures:
            closing_failures.append(error)
        raise
    finally:
        if _observe_checked_context is not None:
            _physical_complete_checks_v1((
                ("post-close physical Source generation", physical_owner_fence),
                ("post-close loaded owners", observer_owner_fence)),
                primary=pending_error, _closing_failures=closing_failures)
    # Both original physical file scopes have completed their final byte/stat
    # checks and closed. Do the final source-generation check after that custody.
    if _observe_checked_context is None:
        physical_owner_fence()
    return report


def validate_uscode_release_closure_v2(request_raw: bytes, *, expected_request_sha256: str) -> dict:
    """Replay the unchanged closed V2 physical-three-cache profile."""
    return _validate_uscode_release_physical_closure(request_raw,
        expected_request_sha256=expected_request_sha256, reviewed_version=2)


# Explicit V3 domains. Byte closure never issues a parent/release capability.
CLOSURE_REQUEST_SCHEMA_V3 = "legal-uscode-release-closure-request/v3"
CLOSURE_SCHEMA_V3 = "legal-uscode-release-closure-report/v3"
CLOSURE_PROFILE_V3 = "reviewed-norm-v3-physical-three-cache-replay/v1"
_BYTE_REQUEST_SCHEMA_V3 = "legal-uscode-release-byte-closure-request/v3"
_BYTE_SCHEMA_V3 = "legal-uscode-release-byte-closure-report/v3"
_BYTE_PROFILE_V3 = "reviewed-norm-v3-local-byte-replay/v1"
NATIVE_PACKET_INDEX_SCHEMA_V3 = "legal-reviewed-native-packet-index/v3"
NATIVE_PACKET_INDEX_PROFILE_V3 = "complete-existing-typed-wire-chunks/v1"
NATIVE_PACKET_CODEC_V3 = "legal_corpus_definition_use_lake_v2.encode_parent_replay_value_v1"


def _reviewed_json_artifact_v3(raw):
    """Decode complete legal reports under their existing norm JSON profile.

    Generic graph envelopes retain corpus_contracts' smaller depth limit.
    V3 admission/graph reports embed typed expressions and already use the
    norm correspondence wire's bounded depth/node rules. Byte ceilings and
    subsequent independent semantic validators remain unchanged.
    """
    from . import legal_paired_manifest_inventory_v1 as reader
    from . import legal_norm_scope_correspondence_v1 as correspondence
    _need(type(raw) is bytes and 0 < len(raw) <= _MAX_ARTIFACT_BYTES,
          "bounded exact reviewed artifact bytes required")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reader._pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("finite reviewed JSON required")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ReleaseCoordinatorError("duplicate-free finite UTF8 reviewed JSON required") from error
    _need(correspondence._wire(value, _MAX_ARTIFACT_BYTES) == raw,
          "exact canonical reviewed artifact bytes required")
    return value


def _release_callback_states_v3(callbacks):
    """Capture only these named delegates' cooperative callable generation."""
    from types import FunctionType
    states = []
    for callback in callbacks:
        _need(type(callback) is FunctionType, "V3 ordinary Python delegate required")
        defaults = callback.__kwdefaults__ or {}
        _need(type(defaults) is dict and all(type(key) is str for key in defaults),
              "V3 ordinary keyword defaults required")
        states.append((callback, callback.__code__, callback.__defaults__, callback.__kwdefaults__, tuple(defaults.items())))
    return tuple(states)


def _release_callback_fence_v3(callbacks, states):
    """Refuse identity, code or default drift; no complete memory attestation."""
    from types import FunctionType
    _need(len(callbacks) == len(states), "V3 callback population changed")
    for callback, (original, code, defaults, keyword_mapping, keyword_defaults) in zip(callbacks, states, strict=True):
        current_keywords = callback.__kwdefaults__ if type(callback) is FunctionType else None
        _need(type(callback) is FunctionType and callback is original
              and callback.__code__ is code and callback.__defaults__ is defaults
              and current_keywords is keyword_mapping
              and (current_keywords is None or type(current_keywords) is dict)
              and set(current_keywords or {}) == {key for key, _ in keyword_defaults}
              and all((current_keywords or {})[key] is value for key, value in keyword_defaults),
              "V3 callback function/code/default/keyword-default generation changed")


def _release_v3_policy():
    _need(type(_MAX_ARTIFACT_BYTES) is int and _MAX_ARTIFACT_BYTES == 1_000_000
          and type(MAX_CLOSURE_REQUEST_BYTES) is int and MAX_CLOSURE_REQUEST_BYTES == 8 * 1024 * 1024,
          "V3 retains the original artifact/request ceilings")
    _need((CLOSURE_REQUEST_SCHEMA_V3, CLOSURE_SCHEMA_V3, CLOSURE_PROFILE_V3,
        _BYTE_REQUEST_SCHEMA_V3, _BYTE_SCHEMA_V3, _BYTE_PROFILE_V3,
        NATIVE_PACKET_INDEX_SCHEMA_V3, NATIVE_PACKET_INDEX_PROFILE_V3, NATIVE_PACKET_CODEC_V3) == (
        "legal-uscode-release-closure-request/v3", "legal-uscode-release-closure-report/v3",
        "reviewed-norm-v3-physical-three-cache-replay/v1", "legal-uscode-release-byte-closure-request/v3",
        "legal-uscode-release-byte-closure-report/v3", "reviewed-norm-v3-local-byte-replay/v1",
        "legal-reviewed-native-packet-index/v3", "complete-existing-typed-wire-chunks/v1",
        "legal_corpus_definition_use_lake_v2.encode_parent_replay_value_v1"),
        "closed explicit V3 release and transport domains required")


def prepare_reviewed_native_packet_transport_v3(packet_raw: bytes, *, artifact_id_prefix: str) -> dict:
    """Split one complete exact existing typed packet wire, without authority.

    Use publish_referenced_artifact for every returned descriptor and the
    existing seal_coordinator_receipt only after complete readback. This is
    transport preparation, not Native/source/parent qualification.
    """
    from . import legal_corpus_definition_use_lake_v2 as wire
    _release_v3_policy()
    _need(type(packet_raw) is bytes and 0 < len(packet_raw) <= MAX_CLOSURE_REQUEST_BYTES,
          "complete bounded native packet wire required")
    _need(type(artifact_id_prefix) is str and 0 < len(artifact_id_prefix.encode("utf-8")) <= 480,
          "bounded explicit native artifact ID prefix required")
    value = wire.decode_parent_replay_value_v1(packet_raw,
        expected_payload_sha256=hashlib.sha256(packet_raw).hexdigest(), max_bytes=MAX_CLOSURE_REQUEST_BYTES)
    _need(type(value) in (list, tuple) and len(value) > 0
          and all(type(row) in (list, tuple) and len(row) == 2 and type(row[0]) is str
                  and type(row[1]) is bytes for row in value)
          and wire.encode_parent_replay_value_v1(value, max_bytes=MAX_CLOSURE_REQUEST_BYTES) == packet_raw,
          "exact canonical existing typed packet wire required")
    def artifact(identity, family, raw):
        return dict(artifact_id=identity, family=family, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), payload=raw)
    chunks, rows = [], []
    for ordinal, offset in enumerate(range(0, len(packet_raw), _MAX_ARTIFACT_BYTES)):
        raw = packet_raw[offset:offset + _MAX_ARTIFACT_BYTES]
        identity = artifact_id_prefix + ":chunk:" + format(ordinal, "04d")
        chunks.append(artifact(identity, "native_packet_chunk", raw))
        rows.append(dict(ordinal=ordinal, artifact_id=identity, offset=offset,
                         bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    index = dict(schema=NATIVE_PACKET_INDEX_SCHEMA_V3, profile=NATIVE_PACKET_INDEX_PROFILE_V3,
        codec=NATIVE_PACKET_CODEC_V3, wire_bytes=len(packet_raw), wire_sha256=hashlib.sha256(packet_raw).hexdigest(), chunks=rows)
    _release_v3_policy()
    return dict(index=artifact(artifact_id_prefix + ":index", "native_packet_index", _canonical(index)),
                chunks=chunks, preparation_only=True, original_parent_or_release_authority=False)


def _release_native_packet_v3(selection, materials, required, contracts, wire):
    """Precharge every piece before bounded reconstruction of the whole wire."""
    _release_v3_policy()
    _need(type(selection) is dict and set(selection) == {"receipt", "packet_index", "expected_packet_sha256",
        "expected_binary_sha256", "observation_profile"}, "closed explicit V3 retained packet selection required")
    contracts.require_sha256(selection["expected_packet_sha256"], "logical native inventory SHA256")
    _need(type(selection["observation_profile"]) is str and selection["observation_profile"] in ("retained-native-observation/v1", "fictional-authored-observation/v1"),
          "explicit supported retained observation profile required")
    ids = [selection["receipt"], selection["packet_index"]]
    _need(all(type(identity) is str and 0 < len(identity.encode("utf-8")) <= 512 for identity in ids)
          and len(set(ids)) == 2 and not set(ids) & required, "native receipt/index roles overlap original roles")
    def payload(identity, family):
        row = materials.get(identity)
        _need(row is not None and row["family"] == family, "native transport role missing or changed")
        return row["payload"]
    receipt_raw, index_raw = payload(ids[0], "native_receipt"), payload(ids[1], "native_packet_index")
    index = contracts.load_json_bytes(index_raw, expected_sha256=hashlib.sha256(index_raw).hexdigest())
    _need(type(index) is dict and set(index) == {"schema", "profile", "codec", "wire_bytes", "wire_sha256", "chunks"}
          and _canonical(index) == index_raw, "closed canonical native packet index required")
    _need((index["schema"], index["profile"], index["codec"]) == ("legal-reviewed-native-packet-index/v3",
        "complete-existing-typed-wire-chunks/v1", "legal_corpus_definition_use_lake_v2.encode_parent_replay_value_v1"),
        "exact existing typed-wire V3 index required")
    length = index["wire_bytes"]
    _need(type(length) is int and 0 < length <= MAX_CLOSURE_REQUEST_BYTES, "nonboolean bounded whole wire length required")
    contracts.require_sha256(index["wire_sha256"], "whole native wire SHA256")
    chunks = index["chunks"]
    _need(type(chunks) is list and 1 <= len(chunks) <= 9
          and len(chunks) == (length + _MAX_ARTIFACT_BYTES - 1) // _MAX_ARTIFACT_BYTES,
          "complete bounded fixed-width chunk population required")
    _need(1 <= len(materials) <= 64 and sum(row["bytes"] for row in materials.values()) <= MAX_CLOSURE_REQUEST_BYTES,
          "all original artifact/count budgets must be precharged")
    pieces, seen, offset = [], set(ids), 0
    for ordinal, row in enumerate(chunks):
        _need(type(row) is dict and set(row) == {"ordinal", "artifact_id", "offset", "bytes", "sha256"},
              "closed ordered native chunk descriptor required")
        identity = row["artifact_id"]
        _need(type(identity) is str and 0 < len(identity.encode("utf-8")) <= 512
              and identity not in seen and identity not in required, "unique role-disjoint chunk IDs required")
        expected_bytes = min(_MAX_ARTIFACT_BYTES, length - offset)
        _need(type(row["ordinal"]) is int and row["ordinal"] == ordinal
              and type(row["offset"]) is int and row["offset"] == offset
              and type(row["bytes"]) is int and row["bytes"] == expected_bytes and expected_bytes > 0,
              "exact gapfree nonoverlapping full-width ordered chunks required")
        contracts.require_sha256(row["sha256"], "native chunk SHA256")
        raw = payload(identity, "native_packet_chunk")
        _need(len(raw) == expected_bytes and hashlib.sha256(raw).hexdigest() == row["sha256"], "native chunk bytes differ")
        pieces.append(raw);seen.add(identity);offset += len(raw)
    _need(offset == length and [row["artifact_id"] for row in chunks] == [
        identity for identity, row in materials.items() if row["family"] == "native_packet_chunk"],
        "exact chunk membership and artifact order required")
    packet_raw = b"".join(pieces)
    _need(len(packet_raw) == length and hashlib.sha256(packet_raw).hexdigest() == index["wire_sha256"], "whole native wire differs")
    packet = wire.decode_parent_replay_value_v1(packet_raw,
        expected_payload_sha256=index["wire_sha256"], max_bytes=MAX_CLOSURE_REQUEST_BYTES)
    _need(type(packet) in (list, tuple) and len(packet) > 0
          and all(type(row) in (list, tuple) and len(row) == 2 and type(row[0]) is str
                  and type(row[1]) is bytes for row in packet)
          and wire.encode_parent_replay_value_v1(packet, max_bytes=MAX_CLOSURE_REQUEST_BYTES) == packet_raw,
          "whole original canonical typed packet wire required")
    required.update(seen)
    _release_v3_policy()
    return receipt_raw, packet, dict(index_artifact_id=ids[1], codec=index["codec"],
        complete_wire_bytes=length, complete_wire_sha256=index["wire_sha256"], chunks=chunks,
        logical_packet_inventory_sha256=selection["expected_packet_sha256"],
        complete_packet_file_count=len(packet) if type(packet) in (list, tuple) else None, parent_or_release_authority=False)


def _validate_uscode_release_byte_closure_v3(request_raw: bytes, *, expected_request_sha256: str,
        _captured_native_context=None, _native_transport="chunk-index/v1",
        original_parent_handle=None, _original_parent_context=None) -> dict:
    if original_parent_handle is None and _original_parent_context is None:
        return _validate_uscode_release_byte_closure(request_raw, expected_request_sha256=expected_request_sha256, reviewed_version=3,
                _captured_native_context=_captured_native_context, _native_transport=_native_transport)
    if original_parent_handle is not None:
        entry_guard = _release_original_parent_entry_guard_v3
        if (entry_guard is not _RELEASE_ORIGINAL_PARENT_ENTRY_GUARD_V3
                or entry_guard.__code__ is not _RELEASE_ORIGINAL_PARENT_ENTRY_CODE_V3):
            raise ReleaseCoordinatorError("original-parent coordinator entry generation changed: entry guard")
        entry_guard()
    return _validate_uscode_release_byte_closure(request_raw, expected_request_sha256=expected_request_sha256, reviewed_version=3,
        _captured_native_context=_captured_native_context, _native_transport=_native_transport,
        original_parent_handle=original_parent_handle, _original_parent_context=_original_parent_context)


def _declared_physical_release_eligibility(request_raw, report):
    """Project evidence from the completed physical V3 or V4 replay."""
    from ipfs_datasets_py.utils.cid_utils import cid_for_bytes
    from . import corpus_contracts as contracts, corpus_qualification as qualification
    from . import legal_corpus_definition_use_lake_v2 as wire

    version = report["reviewed_version"]
    request_limit = MAX_CLOSURE_REQUEST_BYTES_V3 if version == 4 else MAX_CLOSURE_REQUEST_BYTES
    request = wire.decode_parent_replay_value_v1(
        request_raw, expected_payload_sha256=report["request_sha256"],
        max_bytes=request_limit,
    )
    artifacts = {row["artifact_id"]: row for row in request["artifacts"]}
    component = request["component"]
    admission = _reviewed_json_artifact_v3(artifacts[component["admission"]]["payload"])
    preserved = artifacts[component["preservation"]]
    preservation = wire.decode_parent_replay_value_v1(
        preserved["payload"], expected_payload_sha256=preserved["sha256"],
        max_bytes=MAX_CLOSURE_REQUEST_BYTES,
    )
    expected_obligations = json.loads(preservation["manifest_json"])["preservation_obligations"]
    cids = {role: cid_for_bytes(artifacts[component[role]]["payload"]) for role in (
        "graph", "reviewed_crosswalk", "admission", "preservation", "dependency",
    )}
    artifact_cid = cids["graph"]
    native = request["native"]
    retained_native = None
    if report["native_receipt_replayed"]:
        retained_native = {
            "receipt_cid": cid_for_bytes(artifacts[native["receipt"]]["payload"]),
            "packet_index_cid": cid_for_bytes(artifacts[native["packet_index"]]["payload"]),
            "packet_sha256": report["native_packet_transport"]["logical_packet_inventory_sha256"],
            "observation_profile": native["observation_profile"],
        }
    current_review = report.get("current_review_observation")
    checked_native = report.get("checked_native_observation")
    evidence = contracts.seal_record({
        "schema": f"legal-corpus-physical-v{version}-qualification-evidence/v1",
        "reviewed_version": version,
        **({key: report[key] for key in (
            "instance_identity_profile", "definition_application_profile",
        )} if version == 4 else {}),
        "artifact_cid": artifact_cid,
        "profile": report["profile"],
        "request_sha256": report["request_sha256"],
        "component_cids": cids,
        "graph_sha256": report["graph_sha256"],
        "admission_sha256": report["admission_sha256"],
        "preservation_sha256": report["preservation_sha256"],
        "reviewed_crosswalk_sha256": report["reviewed_crosswalk_sha256"],
        "ordered_unit_ids": report["unit_ids"],
        "fixture_only": report["fixture_only"],
        "permitted_uses": admission["permitted_uses"],
        "formal_assumptions": admission["formal_assumptions"],
        "preservation_obligations": expected_obligations,
        "retained_native": retained_native,
        **({"current_review_observation": current_review} if current_review is not None else {}),
        **({"checked_native_observation": checked_native} if checked_native is not None else {}),
    })
    # These declarations refer to the verified local component. In particular,
    # source integrity is the exact physical byte crosswalk. Retained Native
    # observations carry no new compilation or theorem-discharge status.
    dimensions = {
        "processing": ("complete", evidence["record_cid"]),
        "source_integrity": ("verified", cids["reviewed_crosswalk"]),
        "interpretation": ("reviewed", cids["admission"]),
        "representation": ("supported_complete", cids["preservation"]),
        "dependency": ("resolved", cids["dependency"]),
    }
    declarations = {name: {"status": state, "evidence_cids": [cid]}
                    for name, (state, cid) in dimensions.items()}
    if current_review is not None:
        declarations["interpretation"]["evidence_cids"].append(current_review["record_cid"])
    record = qualification.prepare_qualification(
        artifact_cid=artifact_cid, profile=report["profile"],
        theorem_requested=bool(expected_obligations), dimensions=declarations,
    )
    return {
        "declared_eligibility_evidence": evidence,
        "declared_qualification": record,
        "declared_eligibility": qualification.derive_eligibility(
            record, artifact_cid=artifact_cid, profile=report["profile"]),
    }


def validate_uscode_release_closure_v3(request_raw: bytes, *, expected_request_sha256: str,
        original_parent_handle=None, include_declared_eligibility=False) -> dict:
    """Replay V3 bytes and optionally project the checked local graph evidence.

    None retains the existing retained-only path. The request wire cannot supply
    the opaque original parent handle. The opt-in eligibility is declarative,
    with conditional obligations and retained observations kept as evidence.
    """
    _release_v3_policy()
    _need(type(include_declared_eligibility) is bool, "explicit boolean eligibility selection required")
    if original_parent_handle is not None:
        entry_guard = _release_original_parent_entry_guard_v3
        if (entry_guard is not _RELEASE_ORIGINAL_PARENT_ENTRY_GUARD_V3
                or entry_guard.__code__ is not _RELEASE_ORIGINAL_PARENT_ENTRY_CODE_V3):
            raise ReleaseCoordinatorError("original-parent coordinator entry generation changed: entry guard")
        entry_guard()
    report = _validate_uscode_release_physical_closure(
        request_raw, expected_request_sha256=expected_request_sha256,
        reviewed_version=3, original_parent_handle=original_parent_handle,
    )
    if include_declared_eligibility:
        report.update(_declared_physical_release_eligibility(request_raw, report))
    return report

def validate_reviewed_physical_realization_context_v1(request_raw: bytes, *,
        expected_request_sha256: str) -> dict:
    """Replay the physical evidence dependency before a future compiler profile.

    This report is a provenance contract, not a capability or a realization
    preparation. A consumer must replay the original request and bind its own
    complete inputs; accepting a serialized report alone is insufficient.
    Existing realization V1 still refuses all declared cross references.
    """
    from . import corpus_contracts as contracts
    from . import legal_corpus_definition_use_lake_v2 as wire
    callbacks = (validate_uscode_release_closure_v3, _reviewed_json_artifact_v3,
        wire.decode_parent_replay_value_v1, wire.encode_parent_replay_value_v1,
        contracts.seal_record, contracts.load_json_bytes, _canonical)
    states = _release_callback_states_v3(callbacks)

    def fence():
        _release_v3_policy()
        _release_callback_fence_v3((validate_uscode_release_closure_v3,
            _reviewed_json_artifact_v3, wire.decode_parent_replay_value_v1,
            wire.encode_parent_replay_value_v1, contracts.seal_record,
            contracts.load_json_bytes, _canonical), states)

    fence()
    request = wire.decode_parent_replay_value_v1(request_raw,
        expected_payload_sha256=expected_request_sha256, max_bytes=MAX_CLOSURE_REQUEST_BYTES)
    _need(type(request) is dict and request.get("schema") == CLOSURE_REQUEST_SCHEMA_V3
        and request.get("profile") == CLOSURE_PROFILE_V3 and request.get("native") is None,
        "explicit physical V3 request without native authority required")
    # The existing owner checks the complete population, signed reviews,
    # dependency manifest and every physical source/cache/graph selector.
    physical = validate_uscode_release_closure_v3(request_raw,
        expected_request_sha256=expected_request_sha256)
    fence()
    opening_physical_raw = _canonical(physical)
    physical = contracts.load_json_bytes(opening_physical_raw,
        expected_sha256=hashlib.sha256(opening_physical_raw).hexdigest())
    _need(_canonical(physical) == opening_physical_raw, "opening physical replay snapshot changed")
    fence()
    _need(physical.get("request_sha256") == expected_request_sha256
        and physical.get("local_source_cache_entity_bindings_verified") is True
        and physical.get("independent_reviewed_crosswalk_verified") is True,
        "complete current physical replay required for evidence dependency")
    rows = {row["artifact_id"]: row for row in request["artifacts"]}
    component, pins = request["component"], request["pins"]
    replay_row = rows[component["replay"]]
    replay = wire.decode_parent_replay_value_v1(replay_row["payload"],
        expected_payload_sha256=replay_row["sha256"], max_bytes=MAX_CLOSURE_REQUEST_BYTES)
    declaration = replay["admission_kwargs"]["preparation_inputs"]["declaration"]
    references = declaration["cross_references"]
    unit_ids = [unit["unit_id"] for unit in declaration["units"]]
    crosswalk_id = component["reviewed_crosswalk"]
    # Do not infer an evidence role from a version label or caller-supplied ID.
    # The complete physical replay above ties this exact body to the selected
    # law/span/entity population. No other declared dependency is classified.
    _need(len(references) == len(unit_ids)
        and [ref["from_unit_id"] for ref in references] == unit_ids
        and all(ref["dependency_artifact_id"] == crosswalk_id
            and ref["dependency_sha256"] == pins["reviewed_crosswalk"]
            and ref["version"] == REVIEWED_PHYSICAL_CROSSWALK_PROFILE for ref in references),
        "only the complete ordered physical evidence dependencies are supported")
    admission = _reviewed_json_artifact_v3(rows[component["admission"]]["payload"])
    context = contracts.seal_record(dict(
        schema="legal-reviewed-physical-realization-context/v1",
        profile="complete-reviewed-physical-crosswalk-evidence-only/v1",
        physical_request_sha256=expected_request_sha256,
        declaration_sha256=admission["declaration_sha256"],
        admission_sha256=pins["admission"], graph_sha256=pins["graph"],
        preservation_sha256=pins["preservation"], crosswalk_artifact_id=crosswalk_id,
        crosswalk_sha256=pins["reviewed_crosswalk"],
        ordered_unit_ids=unit_ids, cross_references=references,
        physical_source_bindings=physical["physical_crosswalk"],
        physical_owner_pins=physical["physical_owner_pins"],
        dependency_role="physical-source-cache-crosswalk-evidence-only/v1",
        external_legal_dependencies_supported=False,
        dependency_meaning_proved=False, realization_prepared=False,
        native_execution_performed=False, original_success_authenticated=False,
        source_kernel_receipt_authenticated=False, proof_verified=False,
        release_ready=False, admitted=False, formalized=False,
        training_mask=0, evaluation_gold_mask=0))
    # Re-run the original physical owner at closure; a saved context is no authority.
    closing = validate_uscode_release_closure_v3(request_raw,
        expected_request_sha256=expected_request_sha256)
    fence()
    _need(_canonical(closing) == opening_physical_raw,
        "physical replay changed during realization context validation")
    # Return detached JSON containers and fence the final serialization too.
    raw = _canonical(context)
    detached = contracts.load_json_bytes(raw, expected_sha256=hashlib.sha256(raw).hexdigest())
    _need(_canonical(detached) == raw, "detached physical context bytes changed")
    fence()
    return detached

def _release_direct_v3_policy():
    """Check only the explicit direct domain; preserve the chunk/default policy."""
    _release_v3_policy()
    _need(CLOSURE_PROFILE_V3_DIRECT == "reviewed-norm-v3-physical-three-cache-direct-packet-replay/v1"
          and _BYTE_PROFILE_V3_DIRECT == "reviewed-norm-v3-local-direct-byte-replay/v1"
          and type(MAX_CLOSURE_REQUEST_BYTES_V3) is int and MAX_CLOSURE_REQUEST_BYTES_V3 == 64 * 1024**2
          and type(MAX_CLOSURE_NATIVE_PACKET_BYTES_V3) is int and MAX_CLOSURE_NATIVE_PACKET_BYTES_V3 == 48 * 1024**2
          and type(MAX_CLOSURE_ARTIFACT_TOTAL_BYTES_V3) is int and MAX_CLOSURE_ARTIFACT_TOTAL_BYTES_V3 == 48 * 1024**2,
          "closed explicit direct-packet V3 bounds/profile required")


def validate_uscode_release_closure_direct_v3(request_raw: bytes, *, expected_request_sha256: str) -> dict:
    """Replay only the explicit direct-packet V3 domain, without parent grants."""
    _release_direct_v3_policy()
    return _validate_uscode_release_physical_closure(request_raw,
        expected_request_sha256=expected_request_sha256, reviewed_version=3,
        _native_transport="direct-packet/v1")


def _physical_closing_note_v1(error, message):
    # Native exception dictionary access avoids arbitrary __str__/attribute hooks.
    try:
        namespace = BaseException.__dict__["__dict__"].__get__(error, BaseException)
        previous = dict.get(namespace, "__notes__")
        notes = (list(previous) if type(previous) is list
                 and len(previous) <= 32 and all(type(note) is str for note in previous) else [])
        notes.append(message)
        dict.__setitem__(namespace, "__notes__", notes)
    except BaseException:
        # Diagnostic decoration must never interrupt remaining closing checks.
        pass


def _joined_release_guard():
    """Check the fixed selected loaded owners; no caller checker is accepted."""
    contracts = _JOIN_RELEASE_OWNER_MODULES_V1[1]
    _need(_JOIN_RELEASE_BINDING_HELPER_V1 is vars(contracts).get("_loaded_owner_guard_binding_v1")
          and _JOIN_RELEASE_REGISTRY_HELPER_V1 is vars(contracts).get("_loaded_owner_registry_binding_v1"),
          "original joined binding helpers changed")
    own = _JOIN_RELEASE_BINDING_HELPER_V1(globals(), _JOIN_LOADED_OWNER_GUARD_V1)
    _need(type(own) is tuple and len(own) == 2, "original coordinator registration required")
    _JOIN_LOADED_OWNER_GUARD_V1()
    registry = _JOIN_RELEASE_REGISTRY_HELPER_V1()
    _need(registry[0] == _JOIN_RELEASE_REGISTRY_ANCHOR_V1[0],
          "original private registration anchor changed")
    for module, verifier, expected in _JOIN_RELEASE_EXTERNAL_BINDINGS_V1:
        namespace = vars(module)
        _need(_sys.modules.get(namespace["__name__"]) is module,
              "joined external module identity changed")
        current = _JOIN_RELEASE_BINDING_HELPER_V1(namespace, verifier)
        _need(current[0] == expected[0], "original joined external registration changed")
        verifier()


def _physical_complete_checks_v1(checks, *, primary=None, _closing_failures=None):
    """Run every finite closing check; a security failure prevents a result.

    When all checks pass, a pending observer exception keeps its identity.
    Otherwise the first closing refusal takes precedence; earlier observer and
    later closing errors remain attached as context or notes.
    """
    failures = [] if _closing_failures is None else _closing_failures
    _need(type(failures) is list and len(failures) <= 32,
          "bounded private closing failure state required")
    for label, check in checks:
        try:
            check()
        except BaseException as error:
            if failures:
                _physical_closing_note_v1(failures[0], "additional closing failure in " + label)
            if len(failures) < 32:
                failures.append(error)
    if failures:
        failure = failures[0]
        if primary is not None and primary is not failure:
            _physical_closing_note_v1(failure, "prior observer/replay failure retained as cause")
            raise failure from primary
        raise failure


def _physical_replay_context_snapshot(context):
    """Fingerprint a complete internal observation; confer no live authority."""
    from . import legal_corpus_definition_use_native_v2 as native
    _joined_release_guard()
    native._live_success_guard(native._owners(), reviewed_version=3)
    fields = {"reviewed_version", "core_request_sha256", "physical_request_sha256",
        "preparation", "graph", "admission", "args", "kwargs", "pins", "toolchain", "native", "physical_files"}
    _need(type(context) is dict, "closed physical context required")
    selected_version = context.get("reviewed_version")
    _need(type(selected_version) is int and selected_version in (3, 4), "closed physical context version required")
    selected_profiles = ()
    if selected_version == 4:
        _release_v4_policy()
        fields |= {"instance_identity_profile", "definition_application_profile"}
        _need(context.get("instance_identity_profile") == "reviewed-source-use/v1"
              and context.get("definition_application_profile") == "whole-norm-definition-expansion/v1"
              and context.get("native") is None, "source-only joint physical V4 context required")
        selected_profiles = (context["instance_identity_profile"], context["definition_application_profile"])
    _need(set(context) == fields,
          "closed complete physical V3 runtime context required")
    current = native._live_original_inputs(context["preparation"], context["graph"],
        context["admission"], context["args"], context["kwargs"])
    selected = context["native"]
    native_binding = None
    if selected is not None:
        _need(type(selected) is dict and set(selected) == {
            "packet_files", "receipt_raw", "expected_packet_sha256", "expected_binary_sha256"},
            "closed retained runtime Native selection required")
        contents, inventory = native._reviewed_retained_packet(selected["packet_files"])
        _need(type(selected["receipt_raw"]) is bytes
              and contents["build-receipt.json"] == selected["receipt_raw"],
              "runtime receipt and complete packet bytes differ")
        native_binding = (native._wire(inventory, native.MAX_RECORD_BYTES),
            hashlib.sha256(selected["receipt_raw"]).hexdigest(),
            _canonical(selected["expected_binary_sha256"]), selected["expected_packet_sha256"])
    physical = context["physical_files"]
    _need(type(physical) is tuple and len(physical) == 2, "same two physical input bindings required")
    physical_binding = []
    for row in physical:
        _need(type(row) is tuple and len(row) == 3 and type(row[0]) is str
              and type(row[1]) is tuple and len(row[1]) == 9
              and all(type(value) is int for value in row[1])
              and type(row[2]) is bytes and 0 < len(row[2]) <= _MAX_ARTIFACT_BYTES,
              "closed bounded physical input binding required")
        physical_binding.append((row[0], row[1], hashlib.sha256(row[2]).hexdigest()))
    result = (current, _canonical(context["pins"]), context["toolchain"],
        context["core_request_sha256"], context["physical_request_sha256"], native_binding,
        tuple(physical_binding))
    return result if selected_version == 3 else (*result, selected_profiles)


def _physical_postclose_fence_v1(context):
    """Check the exact generation from this traversal; establish no authority.

    This is byte/full9 custody only. It neither rebuilds the graph nor replays
    the physical corpus a second time, and no caller baseline is admitted.
    """
    import os
    import stat
    _physical_replay_context_snapshot(context)
    keys = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid",
            "st_size", "st_mtime_ns", "st_ctime_ns")
    for spelling, expected_identity, expected in context["physical_files"]:
        path = Path(spelling)
        _need(path.is_absolute() and path.resolve(strict=True) == path,
              "same unaliased physical input path required")
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            before = os.fstat(fd)
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                  and tuple(getattr(before, key) for key in keys) == expected_identity
                  and tuple(getattr(path.lstat(), key) for key in keys) == expected_identity,
                  "same closed physical file generation required")
            raw = bytearray()
            while len(raw) <= len(expected):
                chunk = os.read(fd, min(1024 * 1024, len(expected) + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            _need(bytes(raw) == expected
                  and tuple(getattr(os.fstat(fd), key) for key in keys) == expected_identity
                  and tuple(getattr(path.lstat(), key) for key in keys) == expected_identity,
                  "closed physical bytes or generation changed")
        finally:
            os.close(fd)
    _joined_release_guard()





CLOSURE_REQUEST_SCHEMA_V4 = "legal-uscode-release-closure-request/v4"
CLOSURE_SCHEMA_V4 = "legal-uscode-release-closure-report/v4"
CLOSURE_PROFILE_V4 = "reviewed-source-use-whole-norm-physical-source-replay/v1"
_BYTE_REQUEST_SCHEMA_V4 = "legal-uscode-release-byte-closure-request/v4"
_BYTE_SCHEMA_V4 = "legal-uscode-release-byte-closure-report/v4"
_BYTE_PROFILE_V4 = "reviewed-source-use-whole-norm-source-byte-replay/v1"


def _release_v4_policy():
    _joined_release_guard()
    _release_v3_policy()
    _release_direct_v3_policy()
    _need((CLOSURE_REQUEST_SCHEMA_V4, CLOSURE_SCHEMA_V4, CLOSURE_PROFILE_V4,
           _BYTE_REQUEST_SCHEMA_V4, _BYTE_SCHEMA_V4, _BYTE_PROFILE_V4) == (
        "legal-uscode-release-closure-request/v4", "legal-uscode-release-closure-report/v4",
        "reviewed-source-use-whole-norm-physical-source-replay/v1",
        "legal-uscode-release-byte-closure-request/v4", "legal-uscode-release-byte-closure-report/v4",
        "reviewed-source-use-whole-norm-source-byte-replay/v1"),
        "closed source-only whole-norm physical bridge required")


def _validate_uscode_release_byte_closure_v4(request_raw, *, expected_request_sha256,
        _captured_native_context=None, _native_transport="direct-packet/v1", _retained_paired_cache_files=None):
    _release_v4_policy()
    _need(_native_transport == "direct-packet/v1", "physical V4 direct transport required")
    return _validate_uscode_release_byte_closure(request_raw,
        expected_request_sha256=expected_request_sha256, reviewed_version=4,
        _captured_native_context=_captured_native_context, _native_transport=_native_transport,
        _retained_paired_cache_files=_retained_paired_cache_files)


def _physical_v4_current_review_selection(current_review):
    from . import corpus_contracts as contracts, legal_graph_review as review

    required = {"registry_sha256", "policy_sha256", "at_time_utc", "observed_artifact_sha256s", "observed_pins"}
    _need(type(current_review) is dict and set(current_review) - {"current_trust"} == required,
          "closed current review observation required")
    _need("current_trust" not in current_review or type(current_review["current_trust"]) is dict,
          "current endpoint trust must be a mapping")
    selection = contracts.clone_json(current_review)
    for field in ("registry_sha256", "policy_sha256"):
        contracts.require_sha256(selection[field], "current review " + field)
    review._time(selection["at_time_utc"])
    _need(type(selection["observed_artifact_sha256s"]) is dict
          and type(selection["observed_pins"]) is dict,
          "current review dependency observations must be mappings")
    return selection


def _observe_physical_v4_current_review(context, selection):
    from . import corpus_contracts as contracts, legal_graph_dependencies as dependencies
    from . import legal_graph_review as review, legal_reviewed_norm_admission_v3 as admissions

    prior = context["kwargs"]
    _need(selection["registry_sha256"] == prior["expected_registry_sha256"]
          and selection["policy_sha256"] == prior["expected_policy_sha256"],
          "current review trust pins differ from the signed replay trust")
    _need(review._time(selection["at_time_utc"]) >= review._time(prior["at_time_utc"]),
          "current review evaluation time rollback")
    assessment_inputs = {**prior, "at_time_utc": selection["at_time_utc"],
                         "observed_artifact_sha256s": selection["observed_artifact_sha256s"],
                         "observed_pins": selection["observed_pins"]}
    if "current_trust" in selection:
        _, assessment = admissions._assess_reviewed_norm_admission_v3_with_current_trust(
            *context["args"], current_trust=selection["current_trust"], **assessment_inputs)
    else:
        assessment = admissions.assess_reviewed_norm_admission_v3(*context["args"], **assessment_inputs)
    historical = context["admission"]
    _need(assessment["semantic_use_eligible"] is True,
          "current review has unresolved admission blockers")
    fields = ("declaration_sha256", "preparation_sha256", "provenance_kind", "units", "permitted_uses",
              "fixture_only", "formal_assumptions", "training_mask", "evaluation_gold_mask")
    _need(all(assessment[field] == historical[field] for field in fields)
          and assessment["review_authority"]["reviews"] == historical["review_authority"]["reviews"],
          "current review differs from the selected admission")
    # The physical release requires the full dependency closure, including any
    # artifact outside the admission subject's required review dependencies.
    inputs = prior["preparation_inputs"]
    invalidation = dependencies.invalidate_dependencies(inputs["dependency_manifest"],
        expected_manifest_sha256=inputs["expected_manifest_sha256"],
        observed_artifact_sha256s=selection["observed_artifact_sha256s"],
        observed_pins=selection["observed_pins"])
    _need(not invalidation["stale_artifact_ids"], "current review dependency closure is stale")
    trust_pins = assessment.get("current_trust", selection)
    return contracts.seal_record({
        "schema": "legal-corpus-physical-v4-current-review-observation/v1",
        "request_sha256": context["physical_request_sha256"],
        "graph_sha256": context["pins"]["graph"],
        "admission_sha256": context["pins"]["admission"],
        "registry_sha256": trust_pins["registry_sha256"],
        "policy_sha256": trust_pins["policy_sha256"],
        "reviews_sha256": prior["expected_reviews_sha256"],
        "at_time_utc": selection["at_time_utc"],
        "caller_observation_sha256": hashlib.sha256(_canonical(selection)).hexdigest(),
        "current_assessment_sha256": admissions.norm_content_adjudication_sha256(assessment),
        "dependency_invalidation_sha256": invalidation["invalidation_sha256"],
        "evaluation_clock_authenticated": False,
        "registry_freshness_authenticated": False,
    })


def _physical_v4_checked_native_selection(checked_native):
    from . import corpus_contracts as contracts, legal_corpus_definition_use_native_v2 as native

    pins = {"expected_receipt_sha256", "expected_packet_sha256",
            "expected_realization_sha256", "expected_planned_request_sha256"}
    _need(type(checked_native) is dict and set(checked_native) == pins | {
        "handle", "packet_files", "realization", "expected_binary_sha256", "planned_request",
    }, "closed checked Native selection required")
    selection = dict(checked_native)
    for field in pins - {"expected_planned_request_sha256"}:
        contracts.require_sha256(selection[field], field)
    _need(selection["planned_request"] is not None and selection["expected_planned_request_sha256"] is not None,
          "exact independently pinned planned whole-norm request required")
    contracts.require_sha256(selection["expected_planned_request_sha256"], "planned whole-norm request")
    native._live_entry_guard(5)
    native._live_handle_entry(selection["handle"], reviewed_version=5,
        instance_identity_profile="reviewed-source-use/v1",
        definition_application_profile="whole-norm-definition-expansion/v1")
    selection["expected_binary_sha256"] = contracts.clone_json(selection["expected_binary_sha256"])
    return selection


def _observe_physical_v4_checked_native(context, request_raw, selection, review):
    from . import corpus_contracts as contracts, legal_corpus_definition_use_native_v2 as native

    pins = context["pins"]
    opened = native.load_verified_reviewed_physical_definition_realization_native_v2(
        selection["handle"], selection["packet_files"], selection["realization"],
        context["preparation"], context["graph"], context["admission"], *context["args"],
        expected_receipt_sha256=selection["expected_receipt_sha256"],
        expected_packet_sha256=selection["expected_packet_sha256"],
        expected_binary_sha256=selection["expected_binary_sha256"],
        expected_realization_sha256=selection["expected_realization_sha256"],
        expected_preservation_sha256=pins["preservation"],
        expected_graph_sha256=pins["graph"], expected_admission_sha256=pins["admission"],
        toolchain=context["toolchain"], physical_request_raw=request_raw,
        expected_physical_request_sha256=context["physical_request_sha256"],
        instance_identity_profile=context["instance_identity_profile"],
        definition_application_profile=context["definition_application_profile"],
        planned_request=selection["planned_request"],
        expected_planned_request_sha256=selection["expected_planned_request_sha256"], **context["kwargs"])
    plan = json.loads(native._physical_whole_norm_request_wire(
        selection["planned_request"], selection["expected_planned_request_sha256"])[1])
    planned = plan["payload"]["context"]
    observation = opened["planned_whole_norm_observation"]
    commitments = {
        "physical_request_sha256": context["physical_request_sha256"],
        "graph_sha256": pins["graph"], "admission_sha256": pins["admission"],
        "preservation_sha256": pins["preservation"],
        "realization_sha256": selection["expected_realization_sha256"],
    }
    _need(all(planned[key] == value for key, value in commitments.items())
          and opened["physical_context"]["physical_request_sha256"] == commitments["physical_request_sha256"]
          and (opened["graph_sha256"], opened["admission_sha256"], opened["preparation_sha256"])
          == (pins["graph"], pins["admission"], commitments["realization_sha256"]),
          "checked Native result differs from the exact physical review and realization")
    unit = planned["unit"]
    matching = [row for row in opened["units"] if row["unit_id"] == unit["unit_id"]]
    _need(len(matching) == 1 and matching[0]["kind"] == "norm"
          and all(matching[0][key] == value for key, value in unit.items())
          and any(row["unit_id"] == unit["unit_id"] for row in context["admission"]["units"]),
          "checked Native result differs from the selected reviewed unit")
    _need(opened["schema"] == native.REVIEWED_PHYSICAL_DEFINITION_REALIZATION_LIVE_SUCCESS_SCHEMA
          and opened["native_execution_authenticated"] is True
          and opened["live_native_success_authenticated"] is True
          and observation["checked_under_explicit_hypotheses"] is True
          and observation["premise_remains_quantified"] is True
          and observation["axiom_dependencies"] == []
          and observation["declaration"] == planned["theorem"] == plan["declaration_id"]
          and observation["request_sha256"] == selection["expected_planned_request_sha256"]
          and observation["claim_digest"] == plan["claim_digest"]
          and observation["obligation_digest"] == plan["obligation_digest"]
          and observation["retained_receipt_sha256"] == selection["expected_receipt_sha256"]
          and observation["retained_packet_sha256"] == selection["expected_packet_sha256"],
          "exact live planned conditional Native observation required")
    _need(all(observation[key] is False for key in ("qualified_request_execution", "proof_receipt_issued"))
          and all(opened[key] is False for key in ("original_admitted_parent_custody_authenticated",
              "native_execution_performed", "release_ready", "Lean_admitted"))
          and all(opened["authority"][key] is False for key in native.AUTHORITY)
          and all(type(opened[key]) is int and opened[key] == 0 for key in ("training_mask", "evaluation_gold_mask")),
          "checked Native observation cannot widen proof or admission scope")
    return contracts.seal_record({
        "schema": "legal-corpus-physical-v4-checked-native-observation/v1",
        **commitments,
        "unit": unit,
        "source_definition": planned["source_definition"],
        "planned_request_sha256": observation["request_sha256"],
        "current_review_observation_cid": review["record_cid"],
        "live_result_cid": opened["record_cid"],
        "declaration": observation["declaration"],
        "proposition_utf8_sha256": observation["proposition_utf8_sha256"],
        "claim_digest": observation["claim_digest"],
        "obligation_digest": observation["obligation_digest"],
        "retained_receipt_sha256": observation["retained_receipt_sha256"],
        "retained_packet_sha256": observation["retained_packet_sha256"],
        "native_execution_authenticated": True,
        "checked_under_explicit_hypotheses": True,
        "premise_remains_quantified": True,
        "axiom_dependencies": [],
        "qualified_request_execution": False,
        "proof_receipt_issued": False,
    })


def validate_uscode_release_closure_v4(request_raw, *, expected_request_sha256,
        include_declared_eligibility=False, current_review=None, checked_native=None,
        replay_retained_artifacts=False, retained_paired_cache_files=None):
    """Replay source-only V4 bytes, optionally joining two live observations.

    A caller may independently select current trust digests, evaluation time
    and dependency observations. The review selection binds the original signed
    registry and policy. Its optional current_trust registry and policy can veto
    reuse under their independently supplied pins. The caller's clock and
    registry freshness remain outside this validator's authentication scope.

    With current review, checked_native may supply an original V5 handle and
    its exact planned whole-norm request, realization, packet and independent
    pins. The loader joins a single checked conditional theorem to the replay.
    Graph-wide proof status and admission still require their own evidence.

    With replay_retained_artifacts, use the exact reviewed Parquet bodies in
    the pinned request after the original local files are unavailable. The
    historical locations and the physical request digest remain unchanged.
    When the original paired-cache repository is also unavailable, supply its
    exact three manifest-bound table byte bodies as retained_paired_cache_files.
    The already-embedded manifest is replayed with them under fresh custody.
    This local replay cannot consume an original Native handle.
    """
    _release_v4_policy()
    _need(type(include_declared_eligibility) is bool, "explicit boolean eligibility selection required")
    _need(type(replay_retained_artifacts) is bool, "explicit boolean retained physical artifact replay required")
    _need(not replay_retained_artifacts or checked_native is None,
          "retained physical artifact replay cannot acquire Native authority")
    if retained_paired_cache_files is not None:
        _need(replay_retained_artifacts and type(retained_paired_cache_files) is dict,
              "exact paired-cache material requires physical V4 retained replay")
        _need(len(retained_paired_cache_files) == 3,
              "exact three retained paired-cache tables required")
        retained_paired_cache_files = dict(retained_paired_cache_files)
    _need(checked_native is None or current_review is not None,
          "checked Native requires independently selected current review")
    observer = None
    observations = []
    if current_review is not None:
        selection = _physical_v4_current_review_selection(current_review)
        native_selection = None if checked_native is None else _physical_v4_checked_native_selection(checked_native)

        def observer(context):
            review = _observe_physical_v4_current_review(context, selection)
            checked = None if native_selection is None else _observe_physical_v4_checked_native(
                context, request_raw, native_selection, review)
            observations.append((review, checked))

    report = _validate_uscode_release_physical_closure(request_raw,
        expected_request_sha256=expected_request_sha256, reviewed_version=4,
        _native_transport="direct-packet/v1", _observe_checked_context=observer,
        replay_retained_artifacts=replay_retained_artifacts,
        _retained_paired_cache_files=retained_paired_cache_files)
    if observer is not None:
        _need(len(observations) == 1, "exactly one closed current review observation required")
        review, checked = observations[0]
        report["current_review_observation"] = review
        if checked is not None:
            report["checked_native_observation"] = checked
    if include_declared_eligibility:
        report.update(_declared_physical_release_eligibility(request_raw, report))
    return report


def qualify_retained_physical_type_capture_v4(
        checked_release_report_raw, planned_request, original_files, stdout_raw, stderr_raw, *,
        expected_checked_release_report_sha256, expected_graph_sha256, expected_unit_id,
        expected_retained_receipt_sha256, expected_retained_packet_sha256,
        expected_preparation_sha256, expected_stdout_sha256, expected_stderr_sha256):
    """Extend a checked V4 eligibility handoff with pinned retained type evidence.

    Select the graph and unit independently of the saved report. Replay the
    original type capture before sealing the new evidence. The original report
    remains the input anchor, and the declaration keeps its existing statuses.
    """
    from . import corpus_contracts as contracts, corpus_qualification as qualification
    from . import legal_corpus_definition_use_preservation_elaboration_native_v2 as elaboration

    _release_v4_policy()
    contracts.require_sha256(expected_graph_sha256, "selected graph")
    contracts.require_text(expected_unit_id, "selected unit ID")
    report = contracts.load_record_bytes(
        checked_release_report_raw, expected_sha256=expected_checked_release_report_sha256)
    _need(report.get("graph_sha256") == expected_graph_sha256,
          "retained type capture belongs to a different reviewed graph")
    capture = elaboration.read_checked_release_physical_whole_norm_type_capture_v2(
        planned_request, original_files, stdout_raw, stderr_raw,
        checked_release_report_raw=checked_release_report_raw,
        expected_checked_release_report_sha256=expected_checked_release_report_sha256,
        expected_retained_receipt_sha256=expected_retained_receipt_sha256,
        expected_retained_packet_sha256=expected_retained_packet_sha256,
        expected_preparation_sha256=expected_preparation_sha256,
        expected_stdout_sha256=expected_stdout_sha256, expected_stderr_sha256=expected_stderr_sha256)
    provenance = capture["provenance"]
    _need(provenance["unit"]["unit_id"] == expected_unit_id,
          "retained type capture belongs to a different reviewed unit")

    evidence = contracts.seal_record({
        **{key: value for key, value in report["declared_eligibility_evidence"].items()
           if key not in {"schema", "record_cid", "cid_scope"}},
        "schema": "legal-corpus-physical-v4-qualification-evidence/v2",
        "retained_type_capture_provenance": provenance,
    })
    previous = report["declared_qualification"]
    dimensions = previous["dimensions"]
    dimensions["processing"]["evidence_cids"] = [evidence["record_cid"]]
    record = qualification.prepare_qualification(
        artifact_cid=previous["artifact_cid"], profile=previous["profile"],
        theorem_requested=previous["theorem_requested"], dimensions=dimensions)
    eligibility = qualification.derive_eligibility(
        record, artifact_cid=previous["artifact_cid"], profile=previous["profile"])
    _need(eligibility["views"] == report["declared_eligibility"]["views"],
          "retained type evidence cannot change release eligibility")
    return {"declared_eligibility_evidence": evidence, "declared_qualification": record,
            "declared_eligibility": eligibility}


def validate_reviewed_physical_realization_context_v2(request_raw: bytes, *,
        expected_request_sha256: str) -> dict:
    """Replay the physical evidence dependency before a future compiler profile.

    This report is a provenance contract, not a capability or a realization
    preparation. A consumer must replay the original request and bind its own
    complete inputs; accepting a serialized report alone is insufficient.
    Existing realization V1 still refuses all declared cross references.
    """
    from . import corpus_contracts as contracts
    from . import legal_corpus_definition_use_lake_v2 as wire
    callbacks = (validate_uscode_release_closure_v4, _reviewed_json_artifact_v3,
        wire.decode_parent_replay_value_v1, wire.encode_parent_replay_value_v1,
        contracts.seal_record, contracts.load_json_bytes, _canonical)
    states = _release_callback_states_v3(callbacks)

    def fence():
        _release_v4_policy()
        _release_callback_fence_v3((validate_uscode_release_closure_v4,
            _reviewed_json_artifact_v3, wire.decode_parent_replay_value_v1,
            wire.encode_parent_replay_value_v1, contracts.seal_record,
            contracts.load_json_bytes, _canonical), states)

    fence()
    request = wire.decode_parent_replay_value_v1(request_raw,
        expected_payload_sha256=expected_request_sha256, max_bytes=MAX_CLOSURE_REQUEST_BYTES_V3)
    _need(type(request) is dict and request.get("schema") == CLOSURE_REQUEST_SCHEMA_V4
        and request.get("profile") == CLOSURE_PROFILE_V4 and request.get("native") is None,
        "explicit physical V3 request without native authority required")
    # The existing owner checks the complete population, signed reviews,
    # dependency manifest and every physical source/cache/graph selector.
    physical = validate_uscode_release_closure_v4(request_raw,
        expected_request_sha256=expected_request_sha256)
    fence()
    opening_physical_raw = _canonical(physical)
    physical = contracts.load_json_bytes(opening_physical_raw,
        expected_sha256=hashlib.sha256(opening_physical_raw).hexdigest())
    _need(_canonical(physical) == opening_physical_raw, "opening physical replay snapshot changed")
    fence()
    _need(physical.get("request_sha256") == expected_request_sha256
        and physical.get("local_source_cache_entity_bindings_verified") is True
        and physical.get("independent_reviewed_crosswalk_verified") is True,
        "complete current physical replay required for evidence dependency")
    rows = {row["artifact_id"]: row for row in request["artifacts"]}
    component, pins = request["component"], request["pins"]
    replay_row = rows[component["replay"]]
    replay = wire.decode_parent_replay_value_v1(replay_row["payload"],
        expected_payload_sha256=replay_row["sha256"], max_bytes=MAX_CLOSURE_REQUEST_BYTES_V3)
    declaration = replay["admission_kwargs"]["preparation_inputs"]["declaration"]
    references = declaration["cross_references"]
    unit_ids = [unit["unit_id"] for unit in declaration["units"]]
    crosswalk_id = component["reviewed_crosswalk"]
    # Do not infer an evidence role from a version label or caller-supplied ID.
    # The complete physical replay above ties this exact body to the selected
    # law/span/entity population. No other declared dependency is classified.
    _need(len(references) == len(unit_ids)
        and [ref["from_unit_id"] for ref in references] == unit_ids
        and all(ref["dependency_artifact_id"] == crosswalk_id
            and ref["dependency_sha256"] == pins["reviewed_crosswalk"]
            and ref["version"] == REVIEWED_PHYSICAL_CROSSWALK_PROFILE for ref in references),
        "only the complete ordered physical evidence dependencies are supported")
    admission = _reviewed_json_artifact_v3(rows[component["admission"]]["payload"])
    context = contracts.seal_record(dict(
        schema="legal-reviewed-physical-realization-context/v2",
        profile="source-use-whole-norm-physical-crosswalk-evidence-only/v1",
        physical_request_sha256=expected_request_sha256,
        declaration_sha256=admission["declaration_sha256"],
        admission_sha256=pins["admission"], graph_sha256=pins["graph"],
        preservation_sha256=pins["preservation"], crosswalk_artifact_id=crosswalk_id,
        instance_identity_profile=replay["instance_identity_profile"],
        definition_application_profile=replay["definition_application_profile"],
        crosswalk_sha256=pins["reviewed_crosswalk"],
        ordered_unit_ids=unit_ids, cross_references=references,
        physical_source_bindings=physical["physical_crosswalk"],
        physical_owner_pins=physical["physical_owner_pins"],
        dependency_role="physical-source-cache-crosswalk-evidence-only/v1",
        external_legal_dependencies_supported=False,
        dependency_meaning_proved=False, realization_prepared=False,
        native_execution_performed=False, original_success_authenticated=False,
        source_kernel_receipt_authenticated=False, proof_verified=False,
        release_ready=False, admitted=False, formalized=False,
        training_mask=0, evaluation_gold_mask=0))
    # Re-run the original physical owner at closure; a saved context is no authority.
    closing = validate_uscode_release_closure_v4(request_raw,
        expected_request_sha256=expected_request_sha256)
    fence()
    _need(_canonical(closing) == opening_physical_raw,
        "physical replay changed during realization context validation")
    # Return detached JSON containers and fence the final serialization too.
    raw = _canonical(context)
    detached = contracts.load_json_bytes(raw, expected_sha256=hashlib.sha256(raw).hexdigest())
    _need(_canonical(detached) == raw, "detached physical context bytes changed")
    fence()
    return detached



_BYTE_PARENT_PROFILE_V3 = "reviewed-norm-v3-original-parent-byte-replay/v1"


CLOSURE_PARENT_PROFILE_V3 = "reviewed-norm-v3-physical-three-cache-original-parent-replay/v1"


def _release_original_parent_fence_v3(context):
    """Recheck the original A owner and the same issued process/thread entry.

    This uses the existing owner, not a task-selected callable or importer.
    Callable snapshots cover cooperative drift, not hostile Python isolation.
    """
    entry_guard = _release_original_parent_entry_guard_v3
    if (entry_guard is not _RELEASE_ORIGINAL_PARENT_ENTRY_GUARD_V3
            or entry_guard.__code__ is not _RELEASE_ORIGINAL_PARENT_ENTRY_CODE_V3):
        raise ReleaseCoordinatorError("original-parent coordinator entry generation changed: entry guard")
    entry_guard()
    import sys
    from types import ModuleType
    _need(type(context) is tuple and len(context) == 4, "closed original-parent context required")
    owner, handle, entry, states = context
    name = "ipfs_accelerate_py.agent_supervisor.rescue.repair_candidate_owners"
    _need(type(owner) is ModuleType and owner.__name__ == name and sys.modules.get(name) is owner
          and owner.__spec__ is not None and owner.__spec__.origin == owner.__file__,
          "normal original-parent owner module required")
    callbacks = (getattr(owner, "_reviewed_parent_guard", None),
        getattr(owner, "_reviewed_parent_capability_entry", None),
        getattr(owner, "load_parent_verified_reviewed_preservation_v3", None))
    _release_callback_fence_v3(callbacks, states)
    _need(callbacks[0] is owner._REVIEWED_PARENT_GUARD_OBJECT
          and callbacks[0].__code__ is owner._REVIEWED_PARENT_GUARD_CODE,
          "original-parent owner guard changed")
    callbacks[0]()
    _need(callbacks[1](handle) is entry, "same original issued parent handle required")
    _need((_BYTE_PARENT_PROFILE_V3, CLOSURE_PARENT_PROFILE_V3) == (
        "reviewed-norm-v3-original-parent-byte-replay/v1",
        "reviewed-norm-v3-physical-three-cache-original-parent-replay/v1"),
        "closed original-parent coordinator profiles required")


def _release_original_parent_context_v3(handle):
    """Authenticate the opaque A handle before parsing physical/native DATA."""
    entry_guard = _release_original_parent_entry_guard_v3
    if (entry_guard is not _RELEASE_ORIGINAL_PARENT_ENTRY_GUARD_V3
            or entry_guard.__code__ is not _RELEASE_ORIGINAL_PARENT_ENTRY_CODE_V3):
        raise ReleaseCoordinatorError("original-parent coordinator entry generation changed: entry guard")
    entry_guard()
    from types import FunctionType
    from ipfs_accelerate_py.agent_supervisor.rescue import repair_candidate_owners as owner
    guard, capability = owner._reviewed_parent_guard, owner._reviewed_parent_capability_entry
    _need(guard is owner._REVIEWED_PARENT_GUARD_OBJECT
          and guard.__code__ is owner._REVIEWED_PARENT_GUARD_CODE,
          "original-parent owner guard changed")
    guard()
    # Constructor/copy/JSON values cannot manufacture this private issued entry.
    entry = capability(handle)
    # Read only the immutable evidence held by the original issued entry.
    # A genuine legacy V1 handle is authentic but belongs to another domain.
    evidence = owner.json_object(entry[4])
    _need(type(evidence) is dict and type(evidence.get("binding")) is dict
          and evidence["binding"].get("schema") == "reviewed-preservation-native-binding/v3",
          "original parent capability belongs to another reviewed native domain")
    loader = getattr(owner, "load_parent_verified_reviewed_preservation_v3", None)
    _need(type(loader) is FunctionType, "explicit original-parent V3 loader unavailable")
    states = _release_callback_states_v3((guard, capability, loader))
    context = (owner, handle, entry, states)
    _release_original_parent_fence_v3(context)
    return context


def _release_original_parent_authentication_v3(context, packet, preparation, graph, admission, args, kwargs,
        *, native_report, receipt_sha256, packet_sha256, binary_sha256, preservation_sha256,
        graph_sha256, admission_sha256, toolchain, contracts):
    """Consume the existing opaque parent through A's exact V3 native loader."""
    entry_guard = _release_original_parent_entry_guard_v3
    if (entry_guard is not _RELEASE_ORIGINAL_PARENT_ENTRY_GUARD_V3
            or entry_guard.__code__ is not _RELEASE_ORIGINAL_PARENT_ENTRY_CODE_V3):
        raise ReleaseCoordinatorError("original-parent coordinator entry generation changed: entry guard")
    entry_guard()
    _release_original_parent_fence_v3(context)
    loader = context[3][2][0]
    authenticated = loader(context[1], packet, preparation, graph, admission, *args,
        expected_receipt_sha256=receipt_sha256, expected_packet_sha256=packet_sha256,
        expected_binary_sha256=binary_sha256, expected_preservation_sha256=preservation_sha256,
        expected_graph_sha256=graph_sha256, expected_admission_sha256=admission_sha256,
        toolchain=toolchain, **kwargs)
    _release_original_parent_fence_v3(context)
    _need(type(authenticated) is dict and authenticated.get("schema") == "reviewed-preservation-admitted-parent-success/v3"
          and authenticated.get("profile") == "original-admitted-parent-exact-reviewed-native-custody/v3",
          "exact original-parent V3 result required")
    for field in ("original_success_authenticated", "native_execution_authenticated",
                  "original_admitted_parent_custody_authenticated", "retained_observations_consistent"):
        _need(authenticated.get(field) is True, "original-parent native authentication missing: " + field)
    commitments = {"retained_receipt_sha256": receipt_sha256, "retained_packet_sha256": packet_sha256,
        "preparation_sha256": preservation_sha256, "graph_sha256": graph_sha256,
        "admission_sha256": admission_sha256}
    _need(all(authenticated.get(key) == value for key, value in commitments.items())
          and authenticated.get("packet_inventory") == native_report["packet_inventory"]
          and authenticated.get("producer_pins") == native_report["producer_pins"],
          "original-parent packet or current reviewed component differs")
    for field in ("native_execution_performed", "olean_kernel_rechecked", "release_ready", "Lean_admitted"):
        _need(authenticated.get(field) is False, "original-parent replay cannot add execution or admission")
    for field in ("training_mask", "evaluation_gold_mask"):
        _need(type(authenticated.get(field)) is int and authenticated[field] == 0,
              "original-parent replay cannot grant training or gold")
    for field in ("parent_request_sha256", "parent_closeout_sha256", "parent_durability_sha256"):
        contracts.require_sha256(authenticated.get(field), field)
    _need(type(authenticated.get("record_cid")) is str and bool(authenticated["record_cid"]),
          "sealed original-parent replay result required")
    return {"schema": authenticated["schema"], "profile": authenticated["profile"],
        "record_cid": authenticated["record_cid"], **commitments,
        "parent_request_sha256": authenticated["parent_request_sha256"],
        "parent_closeout_sha256": authenticated["parent_closeout_sha256"],
        "parent_durability_sha256": authenticated["parent_durability_sha256"],
        "packet_file_count": len(authenticated["packet_inventory"])}


def _release_original_parent_entry_guard_v3():
    """Check the import-completion generation before any opt-in delegation.

    The original source/profile owner still pins this normal module. These
    finite function/code/default bindings detect cooperative substitution;
    they do not claim isolation against hostile arbitrary Python memory.
    Retained-only calls never enter this guard or resolve the A owner.
    """
    from types import FunctionType
    for name, original, code, defaults, keywords, keyword_items in _RELEASE_ORIGINAL_PARENT_ENTRY_STATES_V3:
        current = globals().get(name)
        current_keywords = current.__kwdefaults__ if type(current) is FunctionType else None
        if not (type(current) is FunctionType and current is original
                and current.__code__ is code and current.__defaults__ is defaults
                and current_keywords is keywords
                and (current_keywords is None or type(current_keywords) is dict)
                and set(current_keywords or {}) == {key for key, _ in keyword_items}
                and all((current_keywords or {})[key] is value for key, value in keyword_items)):
            raise ReleaseCoordinatorError("original-parent coordinator entry generation changed: " + name)


_RELEASE_ORIGINAL_PARENT_ENTRY_NAMES_V3 = (
    "_need", "_release_v3_policy", "_release_callback_states_v3", "_release_callback_fence_v3",
    "_release_original_parent_context_v3", "_release_original_parent_fence_v3",
    "_release_original_parent_authentication_v3", "_validate_uscode_release_byte_closure",
    "_validate_uscode_release_physical_closure", "_validate_uscode_release_byte_closure_v3",
    "validate_uscode_release_closure_v3")


_RELEASE_ORIGINAL_PARENT_ENTRY_STATES_V3 = tuple((name, globals()[name], globals()[name].__code__,
    globals()[name].__defaults__, globals()[name].__kwdefaults__, tuple((globals()[name].__kwdefaults__ or {}).items()))
    for name in _RELEASE_ORIGINAL_PARENT_ENTRY_NAMES_V3)


_RELEASE_ORIGINAL_PARENT_ENTRY_GUARD_V3 = _release_original_parent_entry_guard_v3


_RELEASE_ORIGINAL_PARENT_ENTRY_CODE_V3 = _release_original_parent_entry_guard_v3.__code__


# Cold, fixed same-repository implementation bindings for the private join.
# The public wire entry points remain retained-only and confer no parent custody.
from . import corpus_contracts as _joined_owner_contracts_v1
from ...optimizers.logic_theorem_optimizer import uscode_dataset as _joined_law_owner_v1
from . import uscode_ingest as _joined_coordinate_owner_v1
from . import legal_entity_index_intake as _joined_entity_owner_v1
from . import constitution_inventory as _joined_sentence_owner_v1
from . import legal_parent_text_views as _joined_byte_owner_v1
from . import meta_ontology as _joined_meta_owner_v1

_JOIN_RELEASE_OWNER_MODULES_V1 = (
    _sys.modules[__name__], _joined_owner_contracts_v1, _joined_law_owner_v1,
    _joined_coordinate_owner_v1, _joined_entity_owner_v1, _joined_sentence_owner_v1,
    _joined_byte_owner_v1, _joined_meta_owner_v1)
_JOIN_RELEASE_BINDING_HELPER_V1 = _joined_owner_contracts_v1._loaded_owner_guard_binding_v1
_JOIN_RELEASE_REGISTRY_HELPER_V1 = _joined_owner_contracts_v1._loaded_owner_registry_binding_v1
_JOIN_RELEASE_REGISTRY_ANCHOR_V1 = _JOIN_RELEASE_REGISTRY_HELPER_V1()
_JOIN_RELEASE_EXTERNAL_BINDINGS_V1 = tuple(
    (module, vars(module)["_JOIN_LOADED_OWNER_GUARD_V1"],
     _JOIN_RELEASE_BINDING_HELPER_V1(vars(module), vars(module)["_JOIN_LOADED_OWNER_GUARD_V1"]))
    for module in _JOIN_RELEASE_OWNER_MODULES_V1[1:])

_JOIN_LOADED_OWNER_GUARD_V1 = _joined_owner_contracts_v1._capture_loaded_owner_guard_v1(
    globals(),
    class_names=("ReleaseCoordinatorError",),
    value_names=("SCHEMA", "RECEIPT_NAME", "STATUSES", "_COMMIT_KEYS", "_MAX_ARTIFACT_BYTES",
        "CLOSURE_REQUEST_SCHEMA", "CLOSURE_SCHEMA", "CLOSURE_PROFILE", "MAX_CLOSURE_REQUEST_BYTES",
        "MAX_CLOSURE_REQUEST_BYTES_V3", "MAX_CLOSURE_NATIVE_PACKET_BYTES_V3",
        "MAX_CLOSURE_ARTIFACT_TOTAL_BYTES_V3", "_CLOSURE_ROLES", "_CLOSURE_REPOSITORIES",
        "CLOSURE_REQUEST_SCHEMA_V2", "CLOSURE_SCHEMA_V2", "CLOSURE_PROFILE_V2",
        "CLOSURE_REQUEST_SCHEMA_V3", "CLOSURE_SCHEMA_V3", "CLOSURE_PROFILE_V3",
        "CLOSURE_REQUEST_SCHEMA_V4", "CLOSURE_SCHEMA_V4", "CLOSURE_PROFILE_V4",
        "_BYTE_REQUEST_SCHEMA_V4", "_BYTE_SCHEMA_V4", "_BYTE_PROFILE_V4",
        "REVIEWED_PHYSICAL_CROSSWALK_SCHEMA",
        "REVIEWED_PHYSICAL_CROSSWALK_PROFILE", "CLOSURE_PROFILE_V3_DIRECT", "_BYTE_PROFILE_V3_DIRECT", "_BYTE_REQUEST_SCHEMA_V3", "_BYTE_SCHEMA_V3", "_BYTE_PROFILE_V3", "NATIVE_PACKET_INDEX_SCHEMA_V3", "NATIVE_PACKET_INDEX_PROFILE_V3", "NATIVE_PACKET_CODEC_V3", 'CLOSURE_PARENT_PROFILE_V3', '_BYTE_PARENT_PROFILE_V3'),
    alias_names=("hashlib", "json", "Path", "_sys", "_types", "__builtins__", "__loader__", "__spec__",
        "_joined_owner_contracts_v1", "_joined_law_owner_v1", "_joined_coordinate_owner_v1",
        "_joined_entity_owner_v1", "_joined_sentence_owner_v1", "_joined_byte_owner_v1",
        "_joined_meta_owner_v1", "_JOIN_RELEASE_OWNER_MODULES_V1",
        "_JOIN_RELEASE_BINDING_HELPER_V1", "_JOIN_RELEASE_REGISTRY_HELPER_V1",
        "_JOIN_RELEASE_REGISTRY_ANCHOR_V1", "_JOIN_RELEASE_EXTERNAL_BINDINGS_V1", '_RELEASE_ORIGINAL_PARENT_ENTRY_CODE_V3', '_RELEASE_ORIGINAL_PARENT_ENTRY_GUARD_V3', '_RELEASE_ORIGINAL_PARENT_ENTRY_NAMES_V3', '_RELEASE_ORIGINAL_PARENT_ENTRY_STATES_V3'))
