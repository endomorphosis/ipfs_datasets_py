"""Canonical JSON for shared intermediate-representation identities.

``IRCanonicalJSON@1`` is a deliberately small, dependency-free profile:

* strings and object keys are normalized to Unicode NFC;
* object keys are unique strings ordered by their UTF-8 encoding;
* nulls and booleans use their JSON literals;
* integers and finite decimal numbers use minimal, exponent-free spelling;
* arrays are ordered unless a schema declares them set-like or multiset;
* output is compact UTF-8 JSON with no byte-order mark or trailing newline.

Collection paths are relative to the value passed to :func:`canonical_bytes`.
They may be JSON pointers or component sequences.  ``"*"`` represents every
item of an array, so ``("nodes", "*", "tags")`` declares the tag collection
on every node.
"""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, TypeAlias


CANONICAL_JSON_PROFILE = "IRCanonicalJSON@1"

CanonicalPath: TypeAlias = tuple[str, ...]
PathInput: TypeAlias = str | Sequence[str]


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented by the canonical profile."""


class CollectionKind(str, Enum):
    """Collection semantics supported by the shared canonical profile."""

    ORDERED = "ordered"
    SET = "set-like"
    SET_LIKE = "set-like"
    MULTISET = "multiset"

    @classmethod
    def coerce(cls, value: "CollectionKind | str") -> "CollectionKind":
        """Normalize a collection-kind enum or its documented string aliases."""

        if isinstance(value, cls):
            return value
        aliases = {
            "ordered": cls.ORDERED,
            "set": cls.SET,
            "set-like": cls.SET,
            "set_like": cls.SET,
            "multiset": cls.MULTISET,
            "bag": cls.MULTISET,
        }
        try:
            return aliases[str(value).strip().lower()]
        except KeyError as exc:
            choices = ", ".join(kind.value for kind in cls)
            raise CanonicalizationError(
                f"unknown collection kind {value!r}; expected one of: {choices}"
            ) from exc


def _normalize_text(value: object, *, what: str) -> str:
    if not isinstance(value, str):
        raise CanonicalizationError(
            f"{what} must be a string, got {type(value).__name__}"
        )
    normalized = unicodedata.normalize("NFC", value)
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError(
            f"{what} contains an unpaired Unicode surrogate"
        ) from exc
    return normalized


def _decode_pointer_component(component: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(component):
        character = component[index]
        if character != "~":
            decoded.append(character)
            index += 1
            continue
        if index + 1 >= len(component) or component[index + 1] not in {"0", "1"}:
            raise CanonicalizationError(
                f"invalid JSON pointer escape in collection path component {component!r}"
            )
        decoded.append("~" if component[index + 1] == "0" else "/")
        index += 2
    return "".join(decoded)


def _parse_path(path: PathInput) -> CanonicalPath:
    if isinstance(path, str):
        if path == "":
            return ()
        if not path.startswith("/"):
            raise CanonicalizationError(
                f"collection path {path!r} must be a JSON pointer "
                "or a component sequence"
            )
        return tuple(
            _normalize_text(
                _decode_pointer_component(component),
                what="collection path component",
            )
            for component in path[1:].split("/")
        )

    if isinstance(path, (bytes, bytearray)) or not isinstance(path, Sequence):
        raise CanonicalizationError(
            "collection path must be a JSON pointer or component sequence"
        )
    return tuple(
        _normalize_text(component, what="collection path component")
        for component in path
    )


@dataclass(frozen=True, init=False)
class CollectionRule:
    """Declare the semantics of the array at ``path``."""

    path: CanonicalPath
    kind: CollectionKind

    def __init__(self, path: PathInput, kind: CollectionKind | str) -> None:
        object.__setattr__(self, "path", _parse_path(path))
        object.__setattr__(self, "kind", CollectionKind.coerce(kind))


@dataclass(frozen=True, init=False)
class CollectionSchema:
    """Immutable collection rules for one versioned IR schema.

    Arrays without a matching rule use ``default`` (ordered by default).
    Setting ``require_explicit=True`` makes every undeclared array an error.
    When wildcard rules overlap, the rule with the most literal path
    components wins; equally specific rules with different kinds are
    rejected as ambiguous when encountered.
    """

    rules: tuple[CollectionRule, ...]
    require_explicit: bool
    default: CollectionKind

    def __init__(
        self,
        rules: Mapping[PathInput, CollectionKind | str]
        | Iterable[CollectionRule] = (),
        *,
        require_explicit: bool = False,
        default: CollectionKind | str = CollectionKind.ORDERED,
    ) -> None:
        if not isinstance(require_explicit, bool):
            raise TypeError("require_explicit must be a bool")
        if isinstance(rules, Mapping):
            normalized = tuple(
                CollectionRule(path, kind) for path, kind in rules.items()
            )
        else:
            normalized = tuple(
                rule if isinstance(rule, CollectionRule) else _invalid_rule(rule)
                for rule in rules
            )

        by_path: dict[CanonicalPath, CollectionRule] = {}
        for rule in normalized:
            if rule.path in by_path:
                raise CanonicalizationError(
                    f"duplicate collection declaration for "
                    f"{_display_path(rule.path)}"
                )
            by_path[rule.path] = rule

        ordered_rules = tuple(
            sorted(
                by_path.values(),
                key=lambda rule: tuple(
                    component.encode("utf-8") for component in rule.path
                ),
            )
        )
        object.__setattr__(self, "rules", ordered_rules)
        object.__setattr__(self, "require_explicit", require_explicit)
        object.__setattr__(self, "default", CollectionKind.coerce(default))

    @classmethod
    def from_mapping(
        cls,
        rules: Mapping[PathInput, CollectionKind | str],
        *,
        require_explicit: bool = False,
        default: CollectionKind | str = CollectionKind.ORDERED,
    ) -> "CollectionSchema":
        """Build a schema from JSON-pointer or component-sequence paths."""

        return cls(
            rules,
            require_explicit=require_explicit,
            default=default,
        )

    def kind_for(self, path: CanonicalPath) -> CollectionKind:
        """Resolve the most-specific collection rule for ``path``."""

        matches = [
            rule
            for rule in self.rules
            if len(rule.path) == len(path)
            and all(
                expected == "*" or expected == actual
                for expected, actual in zip(rule.path, path)
            )
        ]
        if matches:
            specificity = max(
                sum(component != "*" for component in rule.path)
                for rule in matches
            )
            most_specific = [
                rule
                for rule in matches
                if sum(component != "*" for component in rule.path)
                == specificity
            ]
            kinds = {rule.kind for rule in most_specific}
            if len(kinds) != 1:
                raise CanonicalizationError(
                    f"ambiguous collection declarations for {_display_path(path)}"
                )
            return most_specific[0].kind

        if self.require_explicit:
            raise CanonicalizationError(
                f"array at {_display_path(path)} has no declared "
                "collection semantics"
            )
        return self.default


DEFAULT_COLLECTION_SCHEMA = CollectionSchema()

# Domain adapters use both terms; keep one implementation and explicit aliases.
CanonicalizationSchema = CollectionSchema
CollectionSemantics = CollectionKind


def _invalid_rule(rule: object) -> CollectionRule:
    raise CanonicalizationError(
        f"expected CollectionRule, got {type(rule).__name__}"
    )


def _display_path(path: CanonicalPath) -> str:
    if not path:
        return "<root>"
    escaped = (
        component.replace("~", "~0").replace("/", "~1")
        for component in path
    )
    return "/" + "/".join(escaped)


def _number_text(value: int | float | Decimal) -> str:
    if isinstance(value, bool):  # bool is an int subclass.
        raise AssertionError("booleans must be handled before numbers")

    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError(
                "NaN and infinite numbers are not valid canonical JSON"
            )
        decimal = Decimal(repr(value))
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalizationError(
                "NaN and infinite numbers are not valid canonical JSON"
            )
        decimal = value
    else:
        return str(value)

    if decimal.is_zero():
        return "0"

    sign, digits_tuple, exponent = decimal.as_tuple()
    digits = "".join(str(digit) for digit in digits_tuple)
    if exponent >= 0:
        rendered = digits + ("0" * exponent)
    else:
        point = len(digits) + exponent
        if point <= 0:
            rendered = "0." + ("0" * -point) + digits
        else:
            rendered = digits[:point] + "." + digits[point:]
        rendered = rendered.rstrip("0").rstrip(".")
    return ("-" if sign else "") + rendered


def _mapping_from_dataclass(value: object) -> dict[str, Any]:
    return {field.name: getattr(value, field.name) for field in fields(value)}


class _CanonicalNumber(str):
    """Internal marker distinguishing a number token from a JSON string."""


def _normalize(
    value: Any,
    *,
    schema: CollectionSchema,
    path: CanonicalPath,
    active_ids: set[int],
) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        container_id = id(value)
        if container_id in active_ids:
            raise CanonicalizationError(
                f"cyclic value at {_display_path(path)}"
            )
        active_ids.add(container_id)
        try:
            return _normalize(
                _mapping_from_dataclass(value),
                schema=schema,
                path=path,
                active_ids=active_ids,
            )
        finally:
            active_ids.remove(container_id)
    if isinstance(value, Enum):
        value = value.value

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _normalize_text(
            value,
            what=f"string at {_display_path(path)}",
        )
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return _CanonicalNumber(_number_text(value))
    if isinstance(value, Mapping):
        container_id = id(value)
        if container_id in active_ids:
            raise CanonicalizationError(
                f"cyclic value at {_display_path(path)}"
            )
        active_ids.add(container_id)
        normalized: dict[str, Any] = {}
        original_keys: dict[str, str] = {}
        try:
            for key, item in value.items():
                normalized_key = _normalize_text(
                    key,
                    what=f"object key at {_display_path(path)}",
                )
                if normalized_key in normalized:
                    first = original_keys[normalized_key]
                    raise CanonicalizationError(
                        f"object keys {first!r} and {key!r} collide after "
                        f"Unicode normalization at {_display_path(path)}"
                    )
                normalized[normalized_key] = _normalize(
                    item,
                    schema=schema,
                    path=path + (normalized_key,),
                    active_ids=active_ids,
                )
                original_keys[normalized_key] = key
            return normalized
        finally:
            active_ids.remove(container_id)
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray, memoryview),
    ):
        container_id = id(value)
        if container_id in active_ids:
            raise CanonicalizationError(
                f"cyclic value at {_display_path(path)}"
            )
        active_ids.add(container_id)
        try:
            kind = schema.kind_for(path)
            items = [
                _normalize(
                    item,
                    schema=schema,
                    path=path + ("*",),
                    active_ids=active_ids,
                )
                for item in value
            ]
            if kind is CollectionKind.ORDERED:
                return items

            keyed = [(_encode(item), item) for item in items]
            keyed.sort(key=lambda pair: pair[0])
            if kind is CollectionKind.MULTISET:
                return [item for _, item in keyed]

            unique: list[Any] = []
            previous: bytes | None = None
            for encoded, item in keyed:
                if encoded != previous:
                    unique.append(item)
                    previous = encoded
            return unique
        finally:
            active_ids.remove(container_id)

    raise CanonicalizationError(
        f"value at {_display_path(path)} has unsupported type "
        f"{type(value).__name__}"
    )


def _encode(value: Any) -> bytes:
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, _CanonicalNumber):
        return value.encode("ascii")
    if isinstance(value, str):
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(_encode(item) for item in value) + b"]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda key: key.encode("utf-8"))
        pairs = (
            _encode(key) + b":" + _encode(value[key])
            for key in keys
        )
        return b"{" + b",".join(pairs) + b"}"
    raise AssertionError(
        f"unexpected normalized value: {type(value).__name__}"
    )


def _coerce_schema(
    schema: CollectionSchema
    | Mapping[PathInput, CollectionKind | str]
    | None,
) -> CollectionSchema:
    if schema is None:
        return DEFAULT_COLLECTION_SCHEMA
    if isinstance(schema, CollectionSchema):
        return schema
    if isinstance(schema, Mapping):
        return CollectionSchema(schema)
    raise TypeError(
        "collection_schema must be a CollectionSchema, mapping, or None"
    )


def canonical_bytes(
    value: Any,
    *,
    collection_schema: CollectionSchema
    | Mapping[PathInput, CollectionKind | str]
    | None = None,
) -> bytes:
    """Return canonical UTF-8 JSON bytes with no trailing newline."""

    schema = _coerce_schema(collection_schema)
    return _encode(
        _normalize(
            value,
            schema=schema,
            path=(),
            active_ids=set(),
        )
    )


def canonical_json(
    value: Any,
    *,
    collection_schema: CollectionSchema
    | Mapping[PathInput, CollectionKind | str]
    | None = None,
) -> str:
    """Return compact canonical JSON text."""

    return canonical_bytes(
        value,
        collection_schema=collection_schema,
    ).decode("utf-8")


def canonicalize(
    value: Any,
    *,
    collection_schema: CollectionSchema
    | Mapping[PathInput, CollectionKind | str]
    | None = None,
) -> Any:
    """Return an inspectable normalized value under the shared profile.

    Fractional numbers are materialized as :class:`~decimal.Decimal` so an
    inspection round trip cannot silently lose precision.
    """

    encoded = canonical_bytes(value, collection_schema=collection_schema)
    return json.loads(encoded, parse_float=Decimal)


# Familiar serialization aliases for domain adapters.
canonical_dumps = canonical_json
canonical_json_bytes = canonical_bytes


__all__ = [
    "CANONICAL_JSON_PROFILE",
    "CanonicalPath",
    "CanonicalizationError",
    "CanonicalizationSchema",
    "CollectionKind",
    "CollectionRule",
    "CollectionSchema",
    "CollectionSemantics",
    "DEFAULT_COLLECTION_SCHEMA",
    "PathInput",
    "canonical_bytes",
    "canonical_dumps",
    "canonical_json",
    "canonical_json_bytes",
    "canonicalize",
]
