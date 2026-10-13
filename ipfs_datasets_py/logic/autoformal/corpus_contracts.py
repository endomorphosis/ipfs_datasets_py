"""Bounded content-addressed envelopes for additive legal corpus records.

Seals establish data identity, not source authenticity, legal meaning or proof.
Existing caches, semantic payloads and historical identifiers are unchanged.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from ipfs_datasets_py.utils.cid_utils import (
    canonical_dag_json_bytes,
    cid_for_dag_json,
    validate_cid,
)

MAX_RECORD_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 20
MAX_JSON_NODES = 25_000
MAX_INTEGER = (1 << 63) - 1
RECORD_CID_SCOPE = "payload_without_record_cid/v1"


class CorpusContractError(ValueError):
    """A record is malformed, unbound, oversized or unsupported."""


def require_text(value, field, *, allow_empty=False, max_bytes=4096):
    if type(value) is not str or "\x00" in value:
        raise CorpusContractError(f"{field} must be ordinary text without NUL")
    if not allow_empty and not value.strip():
        raise CorpusContractError(f"{field} must be nonblank")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise CorpusContractError(f"{field} must be valid UTF8") from error
    if size > max_bytes:
        raise CorpusContractError(f"{field} exceeds its byte bound")
    return value


def require_int(value, field, *, minimum=0, maximum=MAX_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum:
        raise CorpusContractError(f"{field} must be an integer in [{minimum}, {maximum}]")
    return value


def require_keys(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise CorpusContractError(f"closed {label} fields required")
    return value


def require_sha256(value, field):
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise CorpusContractError(f"{field} must be lowercase SHA256")
    return value


def require_cid(value, field, *, codecs=("raw", "dag-json")):
    if type(value) is not str:
        raise CorpusContractError(f"{field} must be a canonical CIDv1")
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as error:
        raise CorpusContractError(f"{field} must be a canonical CIDv1") from error


def require_cid_sha256(value, digest, field, *, codecs=("raw",)):
    """Check an artifact CID against an independently supplied SHA256."""
    from multiformats import CID

    checked = require_cid(value, field, codecs=codecs)
    require_sha256(digest, field + " SHA256")
    if bytes(CID.decode(checked).raw_digest).hex() != digest:
        raise CorpusContractError(f"{field} CID digest differs from SHA256")
    return checked


def clone_json(value):
    """Validate bounded ordinary JSON before returning a detached copy."""
    remaining = MAX_JSON_NODES
    remaining_bytes = MAX_RECORD_BYTES

    def visit(node, depth):
        nonlocal remaining, remaining_bytes
        remaining -= 1
        if remaining < 0 or depth > MAX_JSON_DEPTH:
            raise CorpusContractError("record exceeds JSON node/depth bounds")
        if type(node) is dict:
            for key, item in node.items():
                require_text(key, "JSON key", max_bytes=4096)
                remaining_bytes -= len(key.encode("utf-8"))
                visit(item, depth + 1)
        elif type(node) is list:
            for item in node:
                visit(item, depth + 1)
        elif type(node) is str:
            require_text(node, "JSON string", allow_empty=True, max_bytes=MAX_RECORD_BYTES)
            remaining_bytes -= len(node.encode("utf-8"))
        elif type(node) is int:
            require_int(node, "JSON integer", minimum=-MAX_INTEGER, maximum=MAX_INTEGER)
        elif node is None or type(node) in (bool, float):
            pass  # The existing canonical owner rejects non-finite floats.
        else:
            raise CorpusContractError("record requires ordinary JSON values")
        if remaining_bytes < 0:
            raise CorpusContractError("record exceeds byte bound")

    try:
        visit(value, 0)
        raw = canonical_dag_json_bytes(value)
        if len(raw) > MAX_RECORD_BYTES:
            raise CorpusContractError("record exceeds byte bound")
        return json.loads(raw)
    except (TypeError, ValueError, RecursionError, OverflowError) as error:
        if isinstance(error, CorpusContractError):
            raise
        raise CorpusContractError("record requires bounded finite JSON") from error


def seal_record(payload):
    """Seal a new payload; the CID excludes only its own record_cid field."""
    body = clone_json(payload)
    if type(body) is not dict:
        raise CorpusContractError("record payload must be an object")
    require_text(body.get("schema"), "schema", max_bytes=256)
    if {"record_cid", "cid_scope"} & set(body):
        raise CorpusContractError("record_cid and cid_scope are reserved envelope fields")
    body["cid_scope"] = RECORD_CID_SCOPE
    body["record_cid"] = cid_for_dag_json(body)
    return clone_json(body)


def validate_record(record, *, schema, fields: Sequence[str]):
    """Verify exact envelope shape, scope and canonical content identity."""
    checked = clone_json(record)
    require_keys(checked, {*fields, "schema", "record_cid", "cid_scope"}, schema)
    if checked["schema"] != schema or checked["cid_scope"] != RECORD_CID_SCOPE:
        raise CorpusContractError("record schema or CID scope differs")
    require_cid(checked["record_cid"], "record_cid", codecs=("dag-json",))
    body = {key: item for key, item in checked.items() if key != "record_cid"}
    if cid_for_dag_json(body) != checked["record_cid"]:
        raise CorpusContractError("record CID differs from payload")
    return checked


def load_record_bytes(raw, *, expected_sha256):
    """Read exact digest-bound JSON; duplicate keys and oversized input refuse."""
    require_sha256(expected_sha256, "expected_sha256")
    if type(raw) is not bytes or len(raw) > MAX_RECORD_BYTES:
        raise CorpusContractError("bounded record bytes required")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise CorpusContractError("record bytes differ from expected SHA256")

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise CorpusContractError("duplicate JSON key")
            result[key] = item
        return result

    def constant(value):
        raise CorpusContractError(f"non-finite JSON constant {value}")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, CorpusContractError):
            raise
        raise CorpusContractError("invalid record JSON bytes") from error
    if type(result) is not dict:
        raise CorpusContractError("record JSON must be an object")
    return clone_json(result)
