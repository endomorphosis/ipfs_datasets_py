"""Versioned, deterministic canonical JSON for shared IR contracts.

The ``ir-canonical-json-v1`` profile deliberately has no optional
dependencies.  It accepts JSON values plus tuples and :class:`~decimal.Decimal`
numbers and defines the following representation:

* text (including map keys) is Unicode NFC;
* map keys are strings, unique after NFC normalization, and sorted by Unicode
  code point;
* numbers are finite decimal numbers, with no exponent, insignificant zeroes,
  leading zeroes, or negative zero;
* JSON is compact, uses lowercase literals, and is encoded as UTF-8;
* sequences are ordered unless a JSON-Pointer rule declares them ``set-like``
  or ``multiset``.

Set-like sequences are sorted by canonical element bytes and canonical
duplicates are removed.  Multisets use the same sorting but retain duplicate
elements.  Rules may use ``*`` as one JSON-Pointer segment to describe
collections nested below sequence elements.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import json
import math
import unicodedata
from typing import Any


CANONICAL_JSON_PROFILE = "ir-canonical-json-v1"
"""Name of the canonical JSON profile implemented by this module."""

_MAX_DECIMAL_DIGITS = 1_000_000


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented by the canonical profile."""


class CollectionSemantics(str, Enum):
    """The identity semantics of a JSON sequence."""

    ORDERED = "ordered"
    SET_LIKE = "set-like"
    SET = "set-like"
    MULTISET = "multiset"


def _decode_pointer_segment(segment: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(segment):
        character = segment[index]
        if character != "~":
            result.append(character)
            index += 1
            continue
        if index + 1 >= len(segment) or segment[index + 1] not in {"0", "1"}:
            raise CanonicalizationError(
                f"invalid JSON Pointer escape in collection path segment {segment!r}"
            )
        result.append("~" if segment[index + 1] == "0" else "/")
        index += 2
    return "".join(result)


def _parse_pointer(pointer: str) -> tuple[str, ...]:
    if not isinstance(pointer, str):
        raise TypeError("collection paths must be strings")
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise CanonicalizationError(
            f"collection path {pointer!r} must be an RFC 6901 JSON Pointer"
        )
    return tuple(_decode_pointer_segment(part) for part in pointer[1:].split("/"))


def _encode_pointer_segment(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _format_pointer(path: tuple[str, ...]) -> str:
    if not path:
        return ""
    return "/" + "/".join(_encode_pointer_segment(part) for part in path)


def _coerce_semantics(value: CollectionSemantics | str) -> CollectionSemantics:
    if isinstance(value, CollectionSemantics):
        return value
    try:
        return CollectionSemantics(value)
    except (TypeError, ValueError) as exc:
        choices = ", ".join(item.value for item in CollectionSemantics)
        raise CanonicalizationError(
            f"unknown collection semantics {value!r}; expected one of: {choices}"
        ) from exc


@dataclass(frozen=True, slots=True)
class CollectionRule:
    """A JSON-Pointer declaration for one sequence or family of sequences."""

    pointer: str
    semantics: CollectionSemantics

    def __post_init__(self) -> None:
        _parse_pointer(self.pointer)
        object.__setattr__(self, "semantics", _coerce_semantics(self.semantics))


@dataclass(frozen=True, slots=True, init=False)
class CollectionSchema:
    """Immutable collection-semantics declarations for a canonical payload.

    Args:
        rules: A mapping from JSON Pointer to semantics, or an iterable of
            :class:`CollectionRule` objects.
        require_declared: Reject every sequence that has no matching rule.
            When false, undeclared sequences have ordered semantics.
    """

    rules: tuple[CollectionRule, ...]
    require_declared: bool

    def __init__(
        self,
        rules: (
            Mapping[str, CollectionSemantics | str]
            | Sequence[CollectionRule]
            | None
        ) = None,
        *,
        require_declared: bool = False,
    ) -> None:
        if rules is None:
            prepared: list[CollectionRule] = []
        elif isinstance(rules, Mapping):
            prepared = [
                CollectionRule(pointer, semantics)
                for pointer, semantics in rules.items()
            ]
        else:
            prepared = []
            for rule in rules:
                if not isinstance(rule, CollectionRule):
                    raise TypeError(
                        "collection rules must be CollectionRule instances"
                    )
                prepared.append(rule)

        by_pointer: dict[str, CollectionRule] = {}
        for rule in prepared:
            if rule.pointer in by_pointer:
                raise CanonicalizationError(
                    f"duplicate collection rule for {rule.pointer!r}"
                )
            by_pointer[rule.pointer] = rule

        ordered = tuple(by_pointer[key] for key in sorted(by_pointer))
        object.__setattr__(self, "rules", ordered)
        object.__setattr__(self, "require_declared", bool(require_declared))

    def semantics_for(
        self, path: tuple[str, ...]
    ) -> CollectionSemantics | None:
        """Return the most-specific matching declaration for *path*."""

        best: CollectionSemantics | None = None
        best_specificity = -1
        for rule in self.rules:
            parts = _parse_pointer(rule.pointer)
            if len(parts) != len(path):
                continue
            if not all(
                declared == "*" or declared == actual
                for declared, actual in zip(parts, path)
            ):
                continue
            specificity = sum(part != "*" for part in parts)
            if specificity > best_specificity:
                best = rule.semantics
                best_specificity = specificity
            elif specificity == best_specificity and best != rule.semantics:
                raise CanonicalizationError(
                    f"ambiguous collection rules match {_format_pointer(path)!r}"
                )
        return best

    def to_dict(self) -> dict[str, str]:
        """Return a stable JSON-ready representation of the declarations."""

        return {rule.pointer: rule.semantics.value for rule in self.rules}


# A descriptive alias for callers that think of the declaration as part of a
# canonicalization schema rather than a collection-only schema.
CanonicalizationSchema = CollectionSchema


def coerce_collection_schema(
    schema: (
        CollectionSchema
        | Mapping[str, CollectionSemantics | str]
        | Sequence[CollectionRule]
        | None
    ),
) -> CollectionSchema:
    """Return *schema* as an immutable :class:`CollectionSchema`."""

    if isinstance(schema, CollectionSchema):
        return schema
    return CollectionSchema(schema)


def _normalize_text(value: str, *, label: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError(
            f"{label} contains an unpaired Unicode surrogate"
        ) from exc
    return normalized


def _canonical_number(value: int | float | Decimal) -> str:
    if isinstance(value, bool):
        raise TypeError("booleans are not numbers in the canonical profile")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("canonical JSON numbers must be finite")
        decimal = Decimal(repr(value))
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalizationError("canonical JSON numbers must be finite")
        decimal = value
    else:  # pragma: no cover - guarded by the caller
        raise TypeError(f"unsupported number type: {type(value).__name__}")

    if decimal.is_zero():
        return "0"

    sign, digits_tuple, exponent = decimal.as_tuple()
    digits = "".join(str(digit) for digit in digits_tuple)

    # Remove insignificant trailing fractional zeroes without changing value.
    while digits.endswith("0") and exponent < 0:
        digits = digits[:-1]
        exponent += 1

    point = len(digits) + exponent
    output_size = (
        point
        if point >= len(digits)
        else len(digits) + (1 - point if point <= 0 else 1)
    )
    if output_size > _MAX_DECIMAL_DIGITS:
        raise CanonicalizationError(
            "canonical decimal expansion exceeds the profile size limit"
        )

    if point <= 0:
        body = "0." + ("0" * -point) + digits
    elif point >= len(digits):
        body = digits + ("0" * (point - len(digits)))
    else:
        body = digits[:point] + "." + digits[point:]
    return ("-" if sign else "") + body


def _encode(
    value: Any,
    *,
    path: tuple[str, ...],
    schema: CollectionSchema,
) -> bytes:
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, str):
        normalized = _normalize_text(value, label="string")
        return json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return _canonical_number(value).encode("ascii")
    if isinstance(value, Mapping):
        normalized_items: dict[str, Any] = {}
        original_keys: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(
                    f"map key at {_format_pointer(path)!r} is not a string: {key!r}"
                )
            normalized_key = _normalize_text(key, label="map key")
            if normalized_key in normalized_items:
                other = original_keys[normalized_key]
                raise CanonicalizationError(
                    "map keys collide after NFC normalization at "
                    f"{_format_pointer(path)!r}: {other!r} and {key!r}"
                )
            normalized_items[normalized_key] = item
            original_keys[normalized_key] = key

        encoded_items: list[bytes] = []
        for key in sorted(normalized_items):
            encoded_key = json.dumps(
                key,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            encoded_value = _encode(
                normalized_items[key],
                path=path + (key,),
                schema=schema,
            )
            encoded_items.append(encoded_key + b":" + encoded_value)
        return b"{" + b",".join(encoded_items) + b"}"
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        semantics = schema.semantics_for(path)
        if semantics is None:
            if schema.require_declared:
                raise CanonicalizationError(
                    f"collection semantics are not declared for {_format_pointer(path)!r}"
                )
            semantics = CollectionSemantics.ORDERED

        child_paths = (
            (path + (str(index),) for index in range(len(value)))
            if semantics is CollectionSemantics.ORDERED
            else (path + ("*",) for _ in value)
        )
        encoded_values = [
            _encode(item, path=child_path, schema=schema)
            for item, child_path in zip(value, child_paths)
        ]
        if semantics is not CollectionSemantics.ORDERED:
            encoded_values.sort()
        if semantics is CollectionSemantics.SET_LIKE:
            encoded_values = list(dict.fromkeys(encoded_values))
        return b"[" + b",".join(encoded_values) + b"]"

    raise CanonicalizationError(
        f"unsupported value at {_format_pointer(path)!r}: {type(value).__name__}"
    )


def canonical_json_bytes(
    value: Any,
    *,
    collection_schema: (
        CollectionSchema
        | Mapping[str, CollectionSemantics | str]
        | Sequence[CollectionRule]
        | None
    ) = None,
    collection_semantics: (
        CollectionSchema
        | Mapping[str, CollectionSemantics | str]
        | Sequence[CollectionRule]
        | None
    ) = None,
) -> bytes:
    """Return the canonical UTF-8 JSON representation of *value*.

    ``collection_semantics`` is a descriptive alias for
    ``collection_schema``.  Supplying both is an error.
    """

    if collection_schema is not None and collection_semantics is not None:
        raise TypeError(
            "use either collection_schema or collection_semantics, not both"
        )
    schema = coerce_collection_schema(
        collection_schema
        if collection_schema is not None
        else collection_semantics
    )
    return _encode(value, path=(), schema=schema)


def canonical_json(
    value: Any,
    *,
    collection_schema: (
        CollectionSchema
        | Mapping[str, CollectionSemantics | str]
        | Sequence[CollectionRule]
        | None
    ) = None,
    collection_semantics: (
        CollectionSchema
        | Mapping[str, CollectionSemantics | str]
        | Sequence[CollectionRule]
        | None
    ) = None,
) -> str:
    """Return the canonical JSON text representation of *value*."""

    return canonical_json_bytes(
        value,
        collection_schema=collection_schema,
        collection_semantics=collection_semantics,
    ).decode("utf-8")


# Compact aliases for domain adapters.
canonicalize = canonical_json_bytes
canonicalize_json = canonical_json
canonical_bytes = canonical_json_bytes
canonical_dumps = canonical_json


__all__ = [
    "CANONICAL_JSON_PROFILE",
    "CanonicalizationError",
    "CanonicalizationSchema",
    "CollectionRule",
    "CollectionSchema",
    "CollectionSemantics",
    "canonical_json",
    "canonical_json_bytes",
    "canonical_bytes",
    "canonical_dumps",
    "canonicalize",
    "canonicalize_json",
    "coerce_collection_schema",
]
