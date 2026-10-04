"""Exact-version decoding of every declared UI/UX IR wire field.

All nested records are constructed from the local schema's closed dataclasses.
No field is silently dropped, no scalar is stringified/coerced, and ordered
collections retain order. Schema validation remains the cross-reference owner.
This wire codec does not claim neural decoding or source semantic fidelity.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import MISSING, fields, is_dataclass
from enum import Enum
from functools import lru_cache
import json
import math
from types import UnionType
from typing import Any, get_args, get_origin, get_type_hints

from . import schema
from .schema import UIIRDocument, UIIRValidationError

MAX_WIRE_BYTES = 16 * 1024 * 1024
MAX_WIRE_NODES = 200000
MAX_WIRE_DEPTH = 64
_WIRE_CLASSES = frozenset(value for value in vars(schema).values()
    if isinstance(value, type) and is_dataclass(value) and value.__module__ == schema.__name__)


class UIIRDecodeError(UIIRValidationError):
    """An untrusted payload cannot be decoded without loss or coercion."""


def _require(condition, message):
    if not condition:
        raise UIIRDecodeError(message)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate UI/UX IR JSON field: " + key)
        result[key] = value
    return result


def _snapshot(value, budget, depth=0):
    budget[0] -= 1
    _require(budget[0] >= 0 and depth <= MAX_WIRE_DEPTH, "UI/UX IR wire resource bound exceeded")
    if isinstance(value, Mapping):
        _require(all(type(key) is str for key in value), "UI/UX IR object keys must be strings")
        return {key: _snapshot(item, budget, depth + 1) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [_snapshot(item, budget, depth + 1) for item in value]
    _require(value is None or type(value) in (str, bool, int, float), "UI/UX IR requires JSON values")
    _require(type(value) is not float or math.isfinite(value), "UI/UX IR contains nonfinite number")
    return value


@lru_cache(maxsize=len(_WIRE_CLASSES))
def _field_types(record_type):
    _require(record_type in _WIRE_CLASSES, "unsupported UI/UX IR record type")
    return get_type_hints(record_type)


def _decode_value(value, expected, path):
    origin, arguments = get_origin(expected), get_args(expected)
    if origin is UnionType:
        nonnull = tuple(item for item in arguments if item is not type(None))
        _require(len(nonnull) == 1 and type(None) in arguments, "unsupported UI/UX IR union type")
        return None if value is None else _decode_value(value, nonnull[0], path)
    if origin is tuple:
        _require(len(arguments) == 2 and arguments[1] is Ellipsis and type(value) is list,
                 path + " must be an array")
        return tuple(_decode_value(item, arguments[0], path + "[" + str(index) + "]")
                     for index, item in enumerate(value))
    if origin is Mapping:
        _require(arguments == (str, Any) and type(value) is dict, path + " must be a JSON object")
        # The complete JSON snapshot was bounded above. The existing schema
        # owner freezes these extension/settings payloads and rejects code.
        return value
    if expected in _WIRE_CLASSES:
        return _decode_record(value, expected, path)
    if isinstance(expected, type) and issubclass(expected, Enum):
        _require(expected.__module__ == schema.__name__ and type(value) is str,
                 path + " must be a declared enum string")
        try:
            return expected(value)
        except ValueError as exc:
            raise UIIRDecodeError(path + " has an unknown enum value") from exc
    _require(expected in (str, bool, int) and type(value) is expected,
             path + " has the wrong scalar type")
    return value


def _decode_record(payload, record_type, path):
    _require(type(payload) is dict, path + " must be an object")
    declared = {field.name: field for field in fields(record_type)}
    unknown = sorted(set(payload) - set(declared))
    _require(not unknown, path + " has unknown fields: " + ", ".join(unknown))
    missing = [name for name, field in declared.items() if name not in payload
               and field.default is MISSING and field.default_factory is MISSING]
    _require(not missing, path + " is missing required fields: " + ", ".join(missing))
    hints = _field_types(record_type)
    return record_type(**{key: _decode_value(value, hints[key], path + "." + key)
                          for key, value in payload.items()})


# Retain the original private helper names for local consumers, with exact
# nested schemas and types instead of lossy str()/int() conversions.
def _decode_source(payload):
    return _decode_record(_snapshot(payload, [MAX_WIRE_NODES]), schema.UISourceRef, "UISourceRef")


def _decode_component(payload):
    return _decode_record(_snapshot(payload, [MAX_WIRE_NODES]), schema.UIComponent, "UIComponent")


def _decode_terminal(payload):
    return _decode_record(_snapshot(payload, [MAX_WIRE_NODES]), schema.UITerminalOutcome, "UITerminalOutcome")


def _decode_locale(payload):
    return _decode_record(_snapshot(payload, [MAX_WIRE_NODES]), schema.UILocaleDefaults, "UILocaleDefaults")


def decode_ui_ir(payload: Mapping[str, Any] | str | bytes) -> UIIRDocument:
    """Decode every schema field and validate the complete reference closure.

    Omitted optional fields receive only schema-declared defaults. Present null,
    false, zero or empty values never substitute for a missing field. Legacy
    versions still require the explicit migration owner.
    """
    try:
        if isinstance(payload, (str, bytes, bytearray)):
            raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
            _require(len(raw) <= MAX_WIRE_BYTES, "UI/UX IR wire exceeds byte bound")
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        payload = _snapshot(payload, [MAX_WIRE_NODES])
        _require(type(payload) is dict, "UI/UX IR payload must decode to an object")
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        _require(len(raw) <= MAX_WIRE_BYTES, "UI/UX IR wire exceeds byte bound")
        version = payload.get("schema_version")
        _require(type(version) is str and bool(version), "UI/UX IR payload missing schema_version")
        if version == schema.LEGACY_UI_UX_IR_SCHEMA_VERSION:
            raise UIIRDecodeError(f"Legacy schema_version {version!r} requires explicit migration before decode")
        _require(version == schema.UI_UX_IR_SCHEMA_VERSION,
                 f"Unsupported schema_version {version!r}; expected {schema.UI_UX_IR_SCHEMA_VERSION!r}")
        schema.reject_unknown_document_fields(payload)
        document = _decode_record(payload, UIIRDocument, "UIIRDocument")
        return schema.validate_ui_ir(document)
    except UIIRDecodeError:
        raise
    except (UIIRValidationError, UnicodeError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise UIIRDecodeError(f"Failed to decode UI/UX IR document: {exc}") from exc


__all__ = ["UIIRDecodeError", "decode_ui_ir"]
