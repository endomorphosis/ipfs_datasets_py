"""Lossless decoder for the current manifest-selected wrapped graph records.

The release encoder transports ``entry_cid,legal_id,family,record_sha256,
record_json``. Current graph bodies use entry_cid and, for edges, explicit
source_entry_cid/target_entry_cid. This is distinct from retained flat shards
and GraphNodeRecord/GraphEdgeRecord's alternative node_cid/edge_cid schema.
Nothing here selects shards, verifies files, resolves endpoints, reviews legal
meaning, or turns legacy admission flags into authority. Caller-owned immutable
custody and raw-row pins are mandatory; the iterator owns their file checks.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import math
from pathlib import PurePosixPath
import re

from ...processors.legal_data.uscode_release_schema import (
    require_immutable_revision, validate_entry_cid, validate_legal_id,
)

SCHEMA = "legal-primary-wrapped-graph-record-observation/v1"
TRANSPORT_PROFILE = "uscode-hf-release/v1:versionless-entry-cid-graph-wrapper"
MAX_ROW_BYTES = 1024 * 1024
MAX_ENVELOPE_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FILE_ROWS = 4096
MAX_TEXT = 4096
FAMILIES = ("graph_nodes", "graph_edges")
WRAPPER_FIELDS = ("entry_cid", "legal_id", "family", "record_sha256", "record_json")
CUSTODY_FIELDS = ("repository", "revision", "manifest_sha256", "selection_sha256",
    "release_root_cid", "source_revision", "family", "shard_path", "file_sha256",
    "file_bytes", "file_row_count", "row_ordinal", "row_group", "row_group_ordinal")
FALSE_AUTHORITY = dict.fromkeys(("admitted", "formalized", "source_semantics_verified",
    "legal_review_verified", "global_consistency_verified", "context_closure_verified",
    "proof_authority", "training_qualified", "source_occurrences_bound",
    "file_custody_verified_by_decoder", "endpoint_existence_verified",
    "legacy_admission_flags_used", "published"), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class PrimaryGraphRecordError(ValueError):
    """An independent pin or finite decoder transport bound differs."""


def _need(ok, message):
    if not ok:
        raise PrimaryGraphRecordError(message)


def _wire(value, maximum=MAX_ENVELOPE_BYTES):
    count = 0

    def visit(item, depth):
        nonlocal count
        count += 1
        _need(depth <= 40 and count <= 262144, "primary record JSON depth/node bound exceeded")
        if type(item) is dict:
            _need(all(type(key) is str for key in item), "plain JSON string keys required")
            for child in item.values():
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        else:
            _need(item is None or type(item) in (str, bool, int, float), "plain JSON values required without coercion")
            if type(item) is float:
                _need(math.isfinite(item), "finite primary record JSON required")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise PrimaryGraphRecordError("finite UTF-8 primary record JSON required") from exc
    _need(len(raw) <= maximum, "primary record byte bound exceeded; no truncation performed")
    return raw


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value), "exact lowercase SHA256 required")


def _text(value, label):
    _need(type(value) is str and value.strip() and len(value.encode("utf-8")) <= MAX_TEXT
          and "\x00" not in value, "bounded explicit " + label + " required")


def raw_row_sha256(raw_row):
    """Hash all raw wrapper fields; original record_json whitespace is data."""
    _need(type(raw_row) is dict, "raw graph wrapper must be an object")
    return hashlib.sha256(_wire(raw_row, MAX_ROW_BYTES)).hexdigest()


def _custody(custody):
    _need(type(custody) is dict and set(custody) == set(CUSTODY_FIELDS), "closed physical graph record custody required")
    for key in ("repository", "revision", "release_root_cid", "source_revision", "shard_path"):
        _text(custody[key], key)
    for key in ("manifest_sha256", "selection_sha256", "file_sha256"):
        _sha(custody[key])
    for key in ("revision", "source_revision"):
        _need(require_immutable_revision(custody[key], name=key) == custody[key], "immutable exact revision required")
    _need(validate_entry_cid(custody["release_root_cid"]) == custody["release_root_cid"], "exact release root identity required")
    _need(custody["family"] in FAMILIES, "explicit supported graph family required")
    path = PurePosixPath(custody["shard_path"])
    _need(path.parts and path.suffix == ".parquet" and not path.is_absolute() and ".." not in path.parts and path.as_posix() == custody["shard_path"]
          and "\\" not in custody["shard_path"], "safe exact relative graph shard path required")
    _need(type(custody["file_bytes"]) is int and 0 < custody["file_bytes"] <= MAX_FILE_BYTES,
          "bounded physical graph file bytes required")
    _need(type(custody["file_row_count"]) is int and 0 < custody["file_row_count"] <= MAX_FILE_ROWS,
          "bounded physical graph file population required")
    for key in ("row_ordinal", "row_group", "row_group_ordinal"):
        _need(type(custody[key]) is int and 0 <= custody[key] < custody["file_row_count"],
              "bounded exact physical " + key + " required")
    _need(custody["row_group_ordinal"] <= custody["row_ordinal"], "row group/local ordinal differs from physical row")
    return json.loads(_wire(custody))


def custody_sha256(custody):
    """Hash the explicit manifest/file/shard/physical occurrence declaration."""
    return hashlib.sha256(_wire(_custody(custody))).hexdigest()


def _parse_record(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate record_json field: " + key)
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite record_json value: " + value)))
    _wire(value, MAX_ROW_BYTES)  # Reject exponent overflow, surrogates, and deep bodies too.
    return value


def _identity(value, label, issues):
    if value in (None, ""):
        issues.append({"code": "missing_" + label})
        return None
    try:
        _need(type(value) is str, "identity must be a string")
        _need(validate_entry_cid(value, name=label) == value, "identity would require normalization")
    except (ValueError, TypeError, UnicodeError) as exc:
        issues.append({"code": "invalid_" + label, "message": str(exc)[:512]})
        return None
    return value


def _aliases(body, raw_row, canonical, alternatives, value, issues):
    for origin, mapping in (("body", body), ("wrapper", raw_row)):
        for key in alternatives:
            if key not in mapping or mapping[key] in (None, ""):
                continue
            if value is None:
                issues.append({"code": "unsupported_identity_alias", "origin": origin,
                               "alias": key, "required_field": canonical})
            elif mapping[key] != value:
                issues.append({"code": "conflicting_identity_alias", "origin": origin,
                               "alias": key, "required_field": canonical})


def decode_primary_graph_record(raw_row, *, custody, expected_raw_row_sha256, expected_custody_sha256):
    """Decode one raw record without choosing aliases or projecting its body.

    Wrong independent pins or finite bounds fail the call. Row-specific syntax,
    parity and identity problems produce a lossless unresolved envelope. Only
    the explicit current identity fields can populate declared_identity, and
    any unresolved problem leaves all three identity values null. A blank
    wrapper legal_id is the producer's explicit transport of absent/null body
    legal_id; it does not manufacture a legal citation for structural nodes.
    """
    _sha(expected_raw_row_sha256); _sha(expected_custody_sha256)
    bound = _custody(custody)
    row_digest = raw_row_sha256(raw_row)
    custody_digest = custody_sha256(bound)
    _need(row_digest == expected_raw_row_sha256, "independently pinned raw graph row differs")
    _need(custody_digest == expected_custody_sha256, "independently pinned physical graph custody differs")
    raw_row = json.loads(_wire(raw_row, MAX_ROW_BYTES))
    issues = []
    for key in WRAPPER_FIELDS:
        if key not in raw_row:
            issues.append({"code": "missing_wrapper_field", "field": key})
        elif type(raw_row[key]) is not str:
            issues.append({"code": "invalid_wrapper_field_type", "field": key})
    raw_json = raw_row.get("record_json")
    raw_bytes = raw_json.encode("utf-8") if type(raw_json) is str else None
    record_digest = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else None
    hash_verified = record_digest is not None and raw_row.get("record_sha256") == record_digest
    if not hash_verified:
        issues.append({"code": "record_sha256_mismatch"})
    original_body = None
    if raw_bytes is not None:
        try:
            original_body = _parse_record(raw_json)
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            issues.append({"code": "malformed_record_json", "message": str(exc)[:512]})
    body = original_body if type(original_body) is dict else None
    entry = source = target = legal_id = None
    if body is None:
        issues.append({"code": "unsupported_non_object_graph_body"})
    else:
        for origin, mapping in (("body", body), ("wrapper", raw_row)):
            if mapping.get("family") != bound["family"]:
                issues.append({"code": "family_parity_mismatch", "origin": origin})
            if "schema_version" in mapping:
                issues.append({"code": "unsupported_graph_schema_version", "origin": origin,
                               "declared_version": deepcopy(mapping["schema_version"])})
        entry = _identity(body.get("entry_cid"), "entry_cid", issues)
        if raw_row.get("entry_cid") != (body.get("entry_cid") or ""):
            issues.append({"code": "entry_cid_parity_mismatch"})
        declared_legal = body.get("legal_id")
        if declared_legal not in (None, ""):
            try:
                _need(type(declared_legal) is str and validate_legal_id(declared_legal) == declared_legal,
                      "legal identity would require normalization")
                legal_id = declared_legal
            except (ValueError, TypeError, UnicodeError) as exc:
                issues.append({"code": "invalid_legal_id", "message": str(exc)[:512]})
        if raw_row.get("legal_id") != (declared_legal or ""):
            issues.append({"code": "legal_id_parity_mismatch"})
        _aliases(body, raw_row, "legal_id", ("legalID", "legalId"), legal_id, issues)
        if bound["family"] == "graph_nodes":
            _aliases(body, raw_row, "entry_cid", ("node_cid", "node_id", "id", "record_id"), entry, issues)
            kind = body.get("node_type")
        else:
            _aliases(body, raw_row, "entry_cid", ("edge_cid", "edge_id", "id", "record_id"), entry, issues)
            source = _identity(body.get("source_entry_cid"), "source_entry_cid", issues)
            target = _identity(body.get("target_entry_cid"), "target_entry_cid", issues)
            _aliases(body, raw_row, "source_entry_cid", ("source_node_cid", "source_id", "src", "source"), source, issues)
            _aliases(body, raw_row, "target_entry_cid", ("target_node_cid", "target_id", "dst", "target"), target, issues)
            for key in ("source_entry_cid", "target_entry_cid"):
                if key in raw_row and raw_row[key] != body.get(key):
                    issues.append({"code": "endpoint_parity_mismatch", "field": key})
            kind = body.get("edge_type")
        if type(kind) is not str or not kind.strip() or len(kind.encode("utf-8")) > MAX_TEXT:
            issues.append({"code": "missing_or_invalid_declared_graph_kind"})
    identity = {"entry_cid": entry, "source_entry_cid": source, "target_entry_cid": target}
    if issues:
        identity = dict.fromkeys(identity, None)
    report = {"schema": SCHEMA, "transport_profile": TRANSPORT_PROFILE, "custody": bound,
        "custody_sha256": custody_digest, "raw_row": raw_row, "raw_row_sha256": row_digest,
        "record_json": raw_json, "record_json_utf8_base64": base64.b64encode(raw_bytes).decode("ascii") if raw_bytes is not None else None,
        "record_sha256": record_digest, "record_sha256_verified": hash_verified,
        "original_body": original_body, "declared_identity": identity, "family": bound["family"],
        "legal_id": legal_id, "disposition": "unresolved" if issues else
            "decoded_unreviewed_node" if bound["family"] == "graph_nodes" else "decoded_unreviewed_edge",
        "issues": issues, "coverage_scope": "exact_independently_pinned_physical_record_only",
        "authority": dict(FALSE_AUTHORITY)}
    report["envelope_sha256"] = hashlib.sha256(_wire(report)).hexdigest()
    return json.loads(_wire(report))


def validate_primary_graph_record(envelope, raw_row, **trusted_inputs):
    """Regenerate from independently pinned raw transport and custody inputs."""
    expected = decode_primary_graph_record(raw_row, **trusted_inputs)
    _need(_wire(envelope) == _wire(expected), "primary graph record differs from exact pinned regeneration")
    return expected


__all__ = ["PrimaryGraphRecordError", "raw_row_sha256", "custody_sha256",
           "decode_primary_graph_record", "validate_primary_graph_record"]
