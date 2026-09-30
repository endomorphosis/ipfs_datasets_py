"""Lossless, bounded packing for large source-derived bridge documents.

Small formal views remain directly readable. Large view payloads/metadata and
frame triples use checksummed JSON blocks; packing confers no validation or
admission authority. No files, model weights, or network services are touched.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import zlib
from typing import Any


DOCUMENT_ENCODING = "recursive-zlib-json/v1"
PACK_THRESHOLD_BYTES = 64 * 1024
DEFAULT_MAX_DECODED_BYTES = 16 * 1024 * 1024
_MARKER = "__legacy_span_logic_artifact__"
_BLOCK_KEYS = {_MARKER, "compression", "base64", "decoded_bytes", "decoded_sha256"}


class LogicArtifactError(ValueError):
    """An artifact is malformed, corrupt, ambiguous, or exceeds its limit."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError) as error:
        raise LogicArtifactError("artifact must contain finite JSON values") from error


def _validate_json(value: Any, *, reject_markers: bool, active: set[int] | None = None) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise LogicArtifactError("artifact must contain finite JSON values")
        return
    if type(value) not in (dict, list):
        raise LogicArtifactError("artifact must contain JSON objects, arrays and scalar values")
    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        raise LogicArtifactError("artifact contains a cyclic value")
    active.add(identity)
    try:
        if isinstance(value, dict):
            if any(type(key) is not str for key in value):
                raise LogicArtifactError("artifact object keys must be strings")
            if reject_markers and _MARKER in value:
                raise LogicArtifactError("unpacked document contains a reserved encoding marker")
            values = value.values()
        else:
            values = value
        for item in values:
            _validate_json(item, reject_markers=reject_markers, active=active)
    finally:
        active.remove(identity)


def _pack_value(value: Any) -> Any:
    raw = _canonical_bytes(value)
    if len(raw) <= PACK_THRESHOLD_BYTES:
        return value
    return {
        _MARKER: DOCUMENT_ENCODING,
        "compression": "zlib",
        "base64": base64.b64encode(zlib.compress(raw, level=9)).decode("ascii"),
        "decoded_bytes": len(raw),
        "decoded_sha256": hashlib.sha256(raw).hexdigest(),
    }


def pack_document(document: dict[str, Any]) -> dict[str, Any]:
    """Pack selected large blocks without changing or truncating their content.

    The caller records ``DOCUMENT_ENCODING`` alongside the packed document.
    This function does not mutate its input or add document-level metadata.
    Already packed input must be unpacked first; reserved marker collisions are
    rejected rather than silently interpreting source data as encoded content.
    """
    if type(document) is not dict:
        raise LogicArtifactError("document must be a JSON object")
    try:
        _validate_json(document, reject_markers=True)
    except RecursionError as error:
        raise LogicArtifactError("artifact JSON nesting exceeds runtime limits") from error
    packed = dict(document)
    if "frame_logic_triples" in packed:
        packed["frame_logic_triples"] = _pack_value(packed["frame_logic_triples"])
    if "views" in packed:
        if type(packed["views"]) is not dict:
            raise LogicArtifactError("document views must be a JSON object")
        views = {}
        for name, view in packed["views"].items():
            if type(view) is not dict:
                raise LogicArtifactError("document view must be a JSON object")
            changed = dict(view)
            for key in ("payload", "metadata"):
                if key in changed:
                    changed[key] = _pack_value(changed[key])
            views[name] = changed
        packed["views"] = views
    return packed


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise LogicArtifactError("encoded JSON has duplicate object keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise LogicArtifactError("encoded JSON contains a non-finite value: " + value)


def _unpack_block(block: dict[str, Any], remaining: int) -> tuple[Any, int]:
    if set(block) != _BLOCK_KEYS or block.get(_MARKER) != DOCUMENT_ENCODING or block.get("compression") != "zlib":
        raise LogicArtifactError("unknown or malformed artifact encoding")
    size = block.get("decoded_bytes")
    if type(size) is not int or size < 0:
        raise LogicArtifactError("decoded byte count must be a nonnegative integer")
    if size > remaining:
        raise LogicArtifactError("artifact exceeds decoded byte limit")
    expected = block.get("decoded_sha256")
    if type(expected) is not str or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise LogicArtifactError("invalid decoded SHA256")
    encoded = block.get("base64")
    # zlib's default compression bound, then base64 expansion. This prevents
    # allocating an arbitrarily large compressed input for a small claimed output.
    compressed_bound = size + (size >> 12) + (size >> 14) + (size >> 25) + 13
    if type(encoded) is not str or len(encoded) > 4 * ((compressed_bound + 2) // 3):
        raise LogicArtifactError("encoded block exceeds compressed byte limit")
    try:
        compressed = base64.b64decode(encoded, validate=True)
        inflater = zlib.decompressobj()
        raw = inflater.decompress(compressed, size + 1)
    except (ValueError, binascii.Error, zlib.error) as error:
        raise LogicArtifactError("invalid compressed artifact") from error
    if len(raw) > size or inflater.unconsumed_tail:
        raise LogicArtifactError("artifact exceeds declared decoded byte limit")
    if not inflater.eof or inflater.unused_data:
        raise LogicArtifactError("compressed artifact is truncated or has trailing data")
    if len(raw) != size:
        raise LogicArtifactError("decoded byte count mismatch")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise LogicArtifactError("decoded SHA256 mismatch")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs_without_duplicates, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise LogicArtifactError("invalid encoded JSON") from error
    _validate_json(value, reject_markers=True)
    if _canonical_bytes(value) != raw:
        raise LogicArtifactError("encoded JSON is not canonical")
    return value, size


def unpack_document(packed: dict[str, Any], *, max_decoded_bytes: int = DEFAULT_MAX_DECODED_BYTES) -> dict[str, Any]:
    """Verify and restore a document within a whole-document JSON byte limit.

    Every compressed block is bounded before decompression. The sum of decoded
    blocks and final canonical document size are checked independently; multiple
    individually small blocks cannot bypass the document budget.
    """
    if type(packed) is not dict:
        raise LogicArtifactError("document must be a JSON object")
    if type(max_decoded_bytes) is not int or max_decoded_bytes <= 0:
        raise LogicArtifactError("max_decoded_bytes must be a positive integer")
    remaining = max_decoded_bytes

    def visit(value: Any) -> Any:
        nonlocal remaining
        if isinstance(value, dict):
            if _MARKER in value:
                decoded, size = _unpack_block(value, remaining)
                remaining -= size
                return decoded
            return {key: visit(item) for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    try:
        _validate_json(packed, reject_markers=False)
        document = visit(packed)
        if type(document) is not dict:
            raise LogicArtifactError("decoded document must be a JSON object")
        # iterencode bounds the total without building a second full JSON buffer.
        size = 0
        encoder = json.JSONEncoder(ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
        for chunk in encoder.iterencode(document):
            size += len(chunk)
            if size > max_decoded_bytes:
                raise LogicArtifactError("document exceeds decoded byte limit")
        return document
    except RecursionError as error:
        raise LogicArtifactError("artifact JSON nesting exceeds runtime limits") from error
