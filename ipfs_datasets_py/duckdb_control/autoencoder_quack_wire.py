"""Bounded JSON framing for the experimental scoped Quack control transport.

Binding a reply to a request establishes correlation, not proof of execution
or current authority. In particular an error reply can follow a committed
operation; the caller must resolve its original operation ID and payload.
This module imports only the standard library and opens no transport.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any


SCHEMA = "ipfs_datasets_py/autoencoder-quack-prototype@1"
MAX_COMMAND_BYTES = 65_536
MAX_REPLY_BYTES = 131_072
MAX_DEPTH = 32
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {"schema", "request_id", "operation_id", "command", "payload"}
_REPLY_FIELDS = {"schema", "ok", "admitted", "runtime_qualified", "request_id", "request_digest"}


class QuackWireError(ValueError):
    """Invalid wire data or a bound owner error; neither proves no commit."""


def _validate_json(value: Any, *, maximum_bytes: int) -> None:
    # Visit aliases per occurrence, as JSON does. A byte-bounded valid JSON
    # value cannot contain more visited values/keys than encoded bytes. This
    # also bounds work for direct Python callers before JSON serialization.
    stack = [(value, 0)]
    visits = 0
    scalar_bytes = 0
    while stack:
        item, depth = stack.pop()
        visits += 1
        if visits > maximum_bytes:
            raise QuackWireError("JSON value count exceeds wire bound")
        if depth > MAX_DEPTH:
            raise QuackWireError("JSON depth exceeds 32")
        kind = type(item)
        if kind is dict:
            if visits + len(stack) + 2 * len(item) > maximum_bytes:
                raise QuackWireError("JSON object exceeds wire bound")
            for key, child in item.items():
                if type(key) is not str:
                    raise QuackWireError("JSON object keys must be strings")
                stack.append((key, depth + 1))
                stack.append((child, depth + 1))
        elif kind is list:
            if visits + len(stack) + len(item) > maximum_bytes:
                raise QuackWireError("JSON array exceeds wire bound")
            stack.extend((child, depth + 1) for child in item)
        elif kind is str:
            if len(item) > maximum_bytes:
                raise QuackWireError("JSON string exceeds wire bound")
            try:
                scalar_bytes += len(item.encode("utf-8")) + 2
                if scalar_bytes > maximum_bytes:
                    raise QuackWireError("JSON string exceeds wire bound")
            except UnicodeError as exc:
                raise QuackWireError("JSON string is not valid UTF-8") from exc
        elif kind is float:
            if not math.isfinite(item):
                raise QuackWireError("non-finite JSON number")
        elif kind not in {type(None), bool, int}:
            raise QuackWireError("wire values must be native JSON types")


def _canonical(value: Any, *, maximum_bytes: int) -> bytes:
    _validate_json(value, maximum_bytes=maximum_bytes)
    try:
        # Matches the registry's canonical JSON for the native JSON types
        # admitted here; integers, float values and signed zero stay distinct.
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise QuackWireError("value cannot be encoded as bounded JSON") from exc
    if len(raw) > maximum_bytes:
        raise QuackWireError("JSON exceeds wire byte bound")
    return raw


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise QuackWireError("duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise QuackWireError("non-finite JSON number")


def _parse(raw: str | bytes, *, maximum_bytes: int) -> dict[str, Any]:
    if type(raw) not in {str, bytes}:
        raise QuackWireError("wire JSON must be text or bytes")
    if not 0 < len(raw) <= maximum_bytes:
        raise QuackWireError("JSON exceeds wire byte bound")
    try:
        encoded = raw.encode("utf-8") if type(raw) is str else raw
        if len(encoded) > maximum_bytes:
            raise QuackWireError("JSON exceeds wire byte bound")
        text = encoded.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    except QuackWireError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        # Do not include the input, parameter contents or parser excerpt.
        raise QuackWireError("invalid bounded JSON") from exc
    if type(value) is not dict:
        raise QuackWireError("wire JSON must be an object")
    _validate_json(value, maximum_bytes=maximum_bytes)
    return value


def _request(envelope: Any) -> bytes:
    if (type(envelope) is not dict or len(envelope) != len(_REQUEST_FIELDS)
            or any(type(key) is not str for key in envelope)
            or set(envelope) != _REQUEST_FIELDS
            or type(envelope["schema"]) is not str or envelope["schema"] != SCHEMA):
        raise QuackWireError("invalid request envelope")
    for name in ("request_id", "operation_id", "command"):
        value = envelope[name]
        if type(value) is not str or not _IDENTIFIER.fullmatch(value):
            raise QuackWireError("invalid request identifier")
    if type(envelope["payload"]) is not dict:
        raise QuackWireError("request payload must be an object")
    return _canonical(envelope, maximum_bytes=MAX_COMMAND_BYTES)


def parse_request(raw: str | bytes) -> dict[str, Any]:
    """Parse a closed envelope; command vocabulary and scope remain owner-side."""
    envelope = _parse(raw, maximum_bytes=MAX_COMMAND_BYTES)
    _request(envelope)
    return envelope


def _error_text(error: Any) -> str:
    if type(error) is not str or not error.strip():
        raise QuackWireError("reply error must be a nonempty string")
    return error


def make_reply(envelope: dict[str, Any], *, result: dict[str, Any] | None = None,
               error: str | None = None) -> dict[str, Any]:
    """Create a detached request-bound reply; errors do not assert no commit."""
    encoded_request = _request(envelope)
    if (result is None) == (error is None):
        raise QuackWireError("reply requires exactly one result or error")
    reply = {"schema": SCHEMA, "ok": error is None, "admitted": False, "runtime_qualified": False,
             "request_id": envelope["request_id"], "request_digest": hashlib.sha256(encoded_request).hexdigest()}
    if error is not None:
        reply["error"] = _error_text(error)
    else:
        if type(result) is not dict:
            raise QuackWireError("reply result must be an object")
        reply["result"] = result
    return _parse(_canonical(reply, maximum_bytes=MAX_REPLY_BYTES), maximum_bytes=MAX_REPLY_BYTES)


def make_unbound_error(error: str) -> dict[str, Any]:
    """Diagnostic for an invalid request; decode_reply always refuses it."""
    reply = {"schema": SCHEMA, "ok": False, "admitted": False, "runtime_qualified": False,
             "request_id": "invalid-request", "request_digest": None, "error": _error_text(error)}
    return _parse(_canonical(reply, maximum_bytes=MAX_REPLY_BYTES), maximum_bytes=MAX_REPLY_BYTES)


def decode_reply(raw: str | bytes, expected_envelope: dict[str, Any]) -> dict[str, Any]:
    """Return a bound result or raise; this is not command-semantic validation."""
    request_bytes = _request(expected_envelope)
    reply = _parse(raw, maximum_bytes=MAX_REPLY_BYTES)
    if (type(reply.get("ok")) is not bool or reply.get("schema") != SCHEMA
            or reply.get("admitted") is not False or reply.get("runtime_qualified") is not False):
        raise QuackWireError("invalid reply schema or flags")
    expected_fields = _REPLY_FIELDS | ({"result"} if reply["ok"] else {"error"})
    if set(reply) != expected_fields:
        raise QuackWireError("reply does not match closed schema")
    if (type(reply["request_id"]) is not str or reply["request_id"] != expected_envelope["request_id"]
            or type(reply["request_digest"]) is not str or not _DIGEST.fullmatch(reply["request_digest"])
            or reply["request_digest"] != hashlib.sha256(request_bytes).hexdigest()):
        raise QuackWireError("reply request binding differs")
    if not reply["ok"]:
        raise QuackWireError(_error_text(reply["error"]))
    if type(reply["result"]) is not dict:
        raise QuackWireError("reply result must be an object")
    return reply["result"]
