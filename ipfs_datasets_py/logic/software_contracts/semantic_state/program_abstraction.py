"""Versioned state-abstraction profiles and abstract-state identity.

This module owns datasets ``StateAbstractionProfile@1`` together with the
abstractor, soundness result, canonical abstract-state identity, and
``StateAbstractionReceipt@1`` work product.

Authority rules (normative):

* Datasets alone defines abstraction meaning.  Accelerate may request a
  profile but cannot redefine it or certify soundness.  Kit only stores
  results.
* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
  Collection-semantics declarations reuse ``ir_core.canonical``.
* Raw and abstract execution states always have distinct CIDs.  The
  versioned abstraction profile participates in abstract-state identity.
* Only declared irrelevant addresses, timestamps, IDs, paths, collection
  order, values, and heap regions are normalized.  Unknown relevance
  widens (marks unavailable) rather than normalizing, and reuse is
  refused.
* Unproved heap or value omission cannot admit reuse.  Uncertainty,
  unsupported languages, and unsound profiles fail closed.
* Existing software-contract ``@1`` identity and execution payloads are
  not modified.  Operational profiles project into the landed
  ``StateAbstractionProfileIdentity@1`` envelope, and produced abstract
  states project into ``AbstractProgramState@1``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import json
import re
import unicodedata

from ipfs_datasets_py.logic.ir_core.canonical import (
    CanonicalizationError,
    CollectionSchema,
    CollectionSemantics,
    canonical_json_bytes as ir_canonical_json_bytes,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    StructuredIdentityError,
    canonical_dag_json_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    AbstractProgramState,
    AbstractionSoundnessClaim,
    CompletenessClaim,
    ExecutionTrace,
    HeapBound,
    ObservationStatus,
    ProgramEvent,
    ProgramExecutionState,
    StackFrameState,
    StateAbstractionReceipt as ExecutionStateAbstractionReceipt,
    bind_abstraction_receipt,
)


# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

STATE_ABSTRACTION_PROFILE_INTERFACE: Final[str] = "StateAbstractionProfile@1"
STATE_ABSTRACTION_RECEIPT_INTERFACE: Final[str] = "StateAbstractionReceipt@1"
PROGRAM_STATE_ABSTRACTOR_INTERFACE: Final[str] = "ProgramStateAbstractor@1"
ABSTRACTION_SOUNDNESS_RESULT_INTERFACE: Final[str] = "AbstractionSoundnessResult@1"
CANONICAL_ABSTRACT_STATE_INTERFACE: Final[str] = "CanonicalAbstractState@1"

STATE_ABSTRACTION_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.state-abstraction-profile@1"
)
STATE_ABSTRACTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-abstraction-receipt@1"
)
ABSTRACTION_SOUNDNESS_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.abstraction-soundness-result@1"
)
CANONICAL_ABSTRACT_STATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.canonical-abstract-state@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_COLLECTION_ITEMS: Final[int] = 100_000
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
MAX_METADATA_BYTES: Final[int] = 16_384

ADMITTED_LANGUAGES: Final[tuple[str, ...]] = ("python",)
UNAVAILABLE_LANGUAGES: Final[tuple[str, ...]] = (
    "javascript",
    "typescript",
    "rust",
    "c",
    "cpp",
    "java",
    "shell",
)

IRRELEVANT_CATEGORIES: Final[tuple[str, ...]] = (
    "addresses",
    "timestamps",
    "ids",
    "paths",
    "order",
    "values",
    "heap_regions",
)

QUERY_FAMILIES: Final[tuple[str, ...]] = (
    "next_call",
    "next_event",
    "inverse_trace",
    "repair",
)

PLACEHOLDER_ADDR: Final[str] = "<addr>"
PLACEHOLDER_TS: Final[str] = "<ts>"
PLACEHOLDER_ID: Final[str] = "<id>"
PLACEHOLDER_PATH: Final[str] = "<path>"

COLLECTION_SEMANTICS_DECLARATION: Final[dict[str, str]] = {
    "/irrelevant_normalizations": CollectionSemantics.SET_LIKE.value,
    "/omitted_heap_regions": CollectionSemantics.SET_LIKE.value,
    "/omitted_value_paths": CollectionSemantics.SET_LIKE.value,
    "/relevant_dimensions": CollectionSemantics.SET_LIKE.value,
    "/unavailable_dimensions": CollectionSemantics.SET_LIKE.value,
    "/unknown_relevance_dimensions": CollectionSemantics.SET_LIKE.value,
    "/normalized_categories": CollectionSemantics.SET_LIKE.value,
}

FORBIDDEN_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "embedding",
        "embedding_score",
        "embeddings",
        "hnsw",
        "password",
        "private_key",
        "raw_memory",
        "refresh_token",
        "secret",
        "session_token",
        "similarity",
        "timestamp",
        "timestamps",
        "vector",
        "vector_cid",
        "vectors",
        "wall_clock",
    }
)

SECRET_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
    }
)

ADDRESS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "addr",
        "address",
        "heap_addr",
        "object_addr",
        "object_pointer",
        "pointer",
        "ptr",
    }
)
TIMESTAMP_KEYS: Final[frozenset[str]] = frozenset(
    {
        "clock",
        "epoch_ns",
        "monotonic_ns",
        "observed_at",
        "time_ns",
        "timestamp",
        "timestamps",
        "ts",
        "wall_clock",
    }
)
ID_KEYS: Final[frozenset[str]] = frozenset(
    {
        "alloc_id",
        "correlation_id",
        "handle",
        "nonce",
        "object_id",
        "oid",
        "request_id",
        "rid",
        "span_id",
        "trace_id",
        "uuid",
    }
)
PATH_KEYS: Final[frozenset[str]] = frozenset(
    {
        "checkout_path",
        "file_path",
        "filename",
        "filepath",
        "local_path",
        "path",
        "store_path",
    }
)

ORDERED_RELEVANT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "assignments",
        "event_kinds",
        "event_order",
        "predecessor_event_cids",
        "stack_logical_names",
        "stack_order",
    }
)

FAMILY_DEFAULT_RELEVANT: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "next_call": (
            "branch_predicate",
            "callee",
            "code_cid",
            "exception_active",
            "handler_active",
            "locals",
            "stack_logical_names",
        ),
        "next_event": (
            "code_cid",
            "event_kind",
            "exception_active",
            "handler_active",
            "line",
            "locals",
            "stack_logical_names",
        ),
        "inverse_trace": (
            "assignments",
            "code_cid",
            "event_order",
            "exception_type",
            "handler_kind",
            "locals",
            "stack_logical_names",
        ),
        "repair": (
            "code_cid",
            "contract_state",
            "exception_type",
            "failing_locals",
            "handler_kind",
            "heap_summary",
            "locals",
        ),
    }
)

FAMILY_REQUIRED_RELEVANT: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "next_call": frozenset({"callee", "code_cid", "stack_logical_names"}),
        "next_event": frozenset({"code_cid", "event_kind"}),
        "inverse_trace": frozenset({"event_order"}),
        "repair": frozenset({"code_cid"}),
    }
)

FAMILY_FORBIDDEN_NORMALIZATIONS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "next_call": frozenset(),
        "next_event": frozenset(),
        "inverse_trace": frozenset({"order"}),
        "repair": frozenset(),
    }
)

DEFAULT_IRRELEVANT_NORMALIZATIONS: Final[tuple[str, ...]] = (
    "addresses",
    "ids",
    "order",
    "paths",
    "timestamps",
)

FAMILY_PROFILE_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "next_call": "next-call-abstraction-v1",
        "next_event": "next-event-abstraction-v1",
        "inverse_trace": "inverse-trace-abstraction-v1",
        "repair": "repair-abstraction-v1",
    }
)

KNOWN_SLICE_KEYS: Final[frozenset[str]] = frozenset().union(
    *FAMILY_DEFAULT_RELEVANT.values()
) | frozenset(
    {
        "dispatch",
        "logical_callee",
        "normalized",
        "query_family",
    }
)

_ADDR_RE: Final[re.Pattern[str]] = re.compile(r"^0x[0-9A-Fa-f]{4,16}$")
_UUID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class ProgramAbstractionError(ValueError):
    """Raised when a program-abstraction payload or profile is malformed."""


class ProgramLanguage(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    SHELL = "shell"


class QueryFamily(str, Enum):
    NEXT_CALL = "next_call"
    NEXT_EVENT = "next_event"
    INVERSE_TRACE = "inverse_trace"
    REPAIR = "repair"


class IrrelevantCategory(str, Enum):
    ADDRESSES = "addresses"
    TIMESTAMPS = "timestamps"
    IDS = "ids"
    PATHS = "paths"
    ORDER = "order"
    VALUES = "values"
    HEAP_REGIONS = "heap_regions"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise ProgramAbstractionError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ProgramAbstractionError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise ProgramAbstractionError(f"{name} contains invalid text")
    return value


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise ProgramAbstractionError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ProgramAbstractionError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ProgramAbstractionError(f"{name} must be a boolean")
    return value


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _reject_forbidden_value(value: Any, name: str) -> None:
    if isinstance(value, Mapping):
        forbidden = set(value) & FORBIDDEN_FIELD_MARKERS
        if forbidden:
            secrets = forbidden & SECRET_FIELD_MARKERS
            if secrets:
                raise ProgramAbstractionError(
                    f"{name} rejects secret fields {sorted(secrets)}"
                )
            raise ProgramAbstractionError(
                f"{name} rejects non-semantic fields {sorted(forbidden)}"
            )
        for key, item in value.items():
            _reject_forbidden_value(item, f"{name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_forbidden_value(item, f"{name}[{index}]")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProgramAbstractionError(f"{name} must be a mapping")
    result = _thaw_structured(dict(value))
    _reject_forbidden_value(result, name)
    try:
        validate_structured_value(result)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramAbstractionError(f"{name} must be strict DAG-JSON") from exc
    encoded = canonical_dag_json_bytes(result)
    if len(encoded) > MAX_METADATA_BYTES:
        raise ProgramAbstractionError(f"{name} exceeds its byte bound")
    return _freeze_structured(result)


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ProgramAbstractionError(f"{name} must be a mapping")
    extra = set(data) - fields
    missing = fields - set(data)
    if extra:
        if extra & SECRET_FIELD_MARKERS:
            raise ProgramAbstractionError(
                f"{name} rejects secret fields {sorted(extra)}"
            )
        if extra & FORBIDDEN_FIELD_MARKERS:
            raise ProgramAbstractionError(
                f"{name} rejects non-semantic fields {sorted(extra)}"
            )
        raise ProgramAbstractionError(f"{name} rejects unknown fields {sorted(extra)}")
    if missing:
        raise ProgramAbstractionError(f"{name} missing fields {sorted(missing)}")
    _reject_forbidden_value(data, name)
    return dict(data)


def _unique_sorted_texts(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = [_text(value, name) for value in values]
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramAbstractionError(f"{name} exceeds its item bound")
    ordered = tuple(sorted(items))
    if len(ordered) != len(set(ordered)):
        raise ProgramAbstractionError(f"{name} must not contain duplicates")
    return ordered


def _language(value: Any, name: str = "language") -> str:
    language = _enum(value, ProgramLanguage, name)
    if language not in ADMITTED_LANGUAGES:
        raise ProgramAbstractionError(
            f"{name} {language!r} is typed unavailable in this profile"
        )
    return language


def _query_family(value: Any, name: str = "query_family") -> str:
    if type(value) is str:
        marker = value.strip().lower().replace("-", "_").replace(" ", "_")
        if marker in {"similar", "similarity", "knn", "nearest"}:
            raise ProgramAbstractionError(
                "similarity/nearest-neighbor is not a state-abstraction query family"
            )
    return _enum(value, QueryFamily, name)


def _irrelevant_category(value: Any, name: str = "irrelevant_normalization") -> str:
    return _enum(value, IrrelevantCategory, name)


def _apply_collection_semantics(
    value: Any, *, path: tuple[str, ...], schema: CollectionSchema
) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _apply_collection_semantics(item, path=path + (key,), schema=schema)
            for key, item in value.items()
        }
    if isinstance(value, list):
        semantics = schema.semantics_for(path) or CollectionSemantics.ORDERED
        child_suffix = "*" if semantics is not CollectionSemantics.ORDERED else None
        prepared = [
            _apply_collection_semantics(
                item,
                path=path + ((child_suffix,) if child_suffix is not None else (str(index),)),
                schema=schema,
            )
            for index, item in enumerate(value)
        ]
        if semantics is CollectionSemantics.ORDERED:
            return prepared
        encoded = [(canonical_dag_json_bytes(item), item) for item in prepared]
        encoded.sort(key=lambda pair: pair[0])
        if semantics is CollectionSemantics.SET_LIKE:
            unique: list[Any] = []
            seen: set[bytes] = set()
            for blob, item in encoded:
                if blob in seen:
                    continue
                seen.add(blob)
                unique.append(item)
            return unique
        return [item for _, item in encoded]
    return value


def canonicalize_program_abstraction_value(value: Any) -> Any:
    """NFC-normalize, apply declared collection semantics, and reject floats."""

    try:
        validate_structured_value(value)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramAbstractionError(
            "program-abstraction value must be strict DAG-JSON"
        ) from exc

    def normalize(item: Any) -> Any:
        if type(item) is str:
            return unicodedata.normalize("NFC", item)
        if isinstance(item, Mapping):
            return {normalize(key): normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item

    prepared = normalize(_thaw_structured(value))
    schema = CollectionSchema(COLLECTION_SEMANTICS_DECLARATION, require_declared=False)
    canonical = _apply_collection_semantics(prepared, path=(), schema=schema)
    try:
        validate_structured_value(canonical)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramAbstractionError(
            "canonical program-abstraction value must be strict DAG-JSON"
        ) from exc
    content_bytes = canonical_dag_json_bytes(canonical)
    try:
        ir_bytes = ir_canonical_json_bytes(
            canonical,
            collection_schema=CollectionSchema(None, require_declared=False),
        )
    except CanonicalizationError as exc:
        raise ProgramAbstractionError(
            "ir_core rejected the canonical program-abstraction value"
        ) from exc
    if ir_bytes != content_bytes:
        raise ProgramAbstractionError(
            "ir_core canonical JSON diverged from software-contract DAG-JSON"
        )
    return canonical


def program_abstraction_cid_for(payload: Mapping[str, Any]) -> str:
    """Return the structured CID of one canonical program-abstraction payload."""

    return cid_for_structured(canonicalize_program_abstraction_value(payload))


def canonical_program_abstraction_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return canonical DAG-JSON bytes of one program-abstraction payload."""

    return canonical_dag_json_bytes(canonicalize_program_abstraction_value(payload))


def _verify_claimed(name: str, claimed: Any, payload: Mapping[str, Any]) -> str:
    canonical = canonicalize_program_abstraction_value(payload)
    try:
        return decode_and_recompute_structured(claimed, canonical)
    except Exception as exc:
        raise ProgramAbstractionError(f"{name} cid does not verify") from exc


def _reject_nonfinite_constant(token: str) -> None:
    raise ProgramAbstractionError(f"nonfinite JSON number {token!r} is rejected")


def _parse_int(token: str) -> int:
    try:
        value = int(token, 10)
    except ValueError as exc:
        raise ProgramAbstractionError(f"JSON number {token!r} is not an integer") from exc
    if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
        raise ProgramAbstractionError("integer is outside the safe JSON range")
    return value


def _parse_float(token: str) -> None:
    raise ProgramAbstractionError(
        f"JSON number {token!r} is not a finite integer; floats are rejected"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProgramAbstractionError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def loads_program_abstraction_json(text: str | bytes) -> Any:
    """Decode JSON text, rejecting duplicate keys, NaN, and floats."""

    if type(text) is bytes:
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProgramAbstractionError("program-abstraction JSON must be UTF-8") from exc
    if type(text) is not str:
        raise ProgramAbstractionError("program-abstraction JSON must be text or UTF-8 bytes")
    try:
        return json.loads(
            text,
            parse_int=_parse_int,
            parse_float=_parse_float,
            parse_constant=_reject_nonfinite_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ProgramAbstractionError:
        raise
    except json.JSONDecodeError as exc:
        raise ProgramAbstractionError("program-abstraction JSON is not well-formed") from exc


def _from_closed(cls: type[Any], data: Mapping[str, Any]) -> Any:
    payload = _closed(data, cls._FIELDS, cls.__name__)
    claimed = payload.pop(cls.CID_FIELD)
    if payload.pop("schema") != cls.SCHEMA:
        raise ProgramAbstractionError(f"unsupported {cls.__name__} schema version")
    result = cls(**payload)
    _verify_claimed(cls.__name__, claimed, result.identity_payload())
    return result


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _looks_like_path(value: str) -> bool:
    if "/" not in value and "\\" not in value:
        return False
    if value.startswith(("pkg.", "mod.")):
        return False
    if value.startswith(("/", "./", "../", "~/", "C:\\", "c:\\")):
        return True
    markers = ("/home/", "/tmp/", "/var/", "/usr/", "\\Users\\", "\\Temp\\")
    return any(marker in value for marker in markers)


def _value_sort(value: Any) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is str:
        return "str"
    if isinstance(value, Mapping):
        return "map"
    if isinstance(value, (list, tuple)):
        return "list"
    return "unknown"


def _sort_list(items: list[Any]) -> list[Any]:
    encoded = [(canonical_dag_json_bytes(item), item) for item in items]
    encoded.sort(key=lambda pair: pair[0])
    return [item for _, item in encoded]


def _key_category(key: str) -> str | None:
    if key in ADDRESS_KEYS:
        return "addresses"
    if key in TIMESTAMP_KEYS:
        return "timestamps"
    if key in ID_KEYS:
        return "ids"
    if key in PATH_KEYS:
        return "paths"
    return None


def _normalize_string(
    value: str,
    *,
    key: str,
    declared: frozenset[str],
    preserve: bool,
) -> str:
    if preserve:
        return value
    if "addresses" in declared and (_ADDR_RE.match(value) or key in ADDRESS_KEYS):
        return PLACEHOLDER_ADDR
    if "timestamps" in declared and key in TIMESTAMP_KEYS:
        return PLACEHOLDER_TS
    if "ids" in declared and (key in ID_KEYS or _UUID_RE.match(value)):
        return PLACEHOLDER_ID
    if "paths" in declared and (key in PATH_KEYS or _looks_like_path(value)):
        return PLACEHOLDER_PATH
    return value


def _normalize_tree(
    value: Any,
    *,
    declared: frozenset[str],
    omitted_value_paths: frozenset[str],
    omitted_heap_regions: frozenset[str],
    value_omission_proved: bool,
    heap_omission_proved: bool,
    path: tuple[str, ...],
    ordered_relevant: bool,
) -> Any:
    current_key = path[-1] if path else ""
    dotted = ".".join(path)
    if dotted in omitted_value_paths:
        if not value_omission_proved:
            raise ProgramAbstractionError(
                "unproved value omission cannot be applied"
            )
        return {"abstracted": "value", "sort": _value_sort(value)}
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        in_heap = bool(path) and path[0] == "heap_summary"
        for key, item in value.items():
            if in_heap and (
                key in omitted_heap_regions
                or "heap" in omitted_heap_regions
                or "*" in omitted_heap_regions
            ):
                if not heap_omission_proved:
                    raise ProgramAbstractionError(
                        "unproved heap omission cannot be applied"
                    )
                continue
            category = _key_category(str(key))
            child_path = path + (str(key),)
            child_ordered = ordered_relevant or str(key) in ORDERED_RELEVANT_KEYS
            if category is not None and category in declared and type(item) is str:
                result[str(key)] = _normalize_string(
                    item, key=str(key), declared=declared, preserve=False
                )
                continue
            if category is not None and category in declared and category == "timestamps":
                result[str(key)] = PLACEHOLDER_TS
                continue
            result[str(key)] = _normalize_tree(
                item,
                declared=declared,
                omitted_value_paths=omitted_value_paths,
                omitted_heap_regions=omitted_heap_regions,
                value_omission_proved=value_omission_proved,
                heap_omission_proved=heap_omission_proved,
                path=child_path,
                ordered_relevant=child_ordered,
            )
        if (
            "heap_regions" in declared
            and in_heap
            and ("heap" in omitted_heap_regions or "*" in omitted_heap_regions)
        ):
            if not heap_omission_proved:
                raise ProgramAbstractionError(
                    "unproved heap omission cannot be applied"
                )
            return {"omitted": True}
        return result
    if isinstance(value, (list, tuple)):
        items = [
            _normalize_tree(
                item,
                declared=declared,
                omitted_value_paths=omitted_value_paths,
                omitted_heap_regions=omitted_heap_regions,
                value_omission_proved=value_omission_proved,
                heap_omission_proved=heap_omission_proved,
                path=path + (str(index),),
                ordered_relevant=ordered_relevant,
            )
            for index, item in enumerate(value)
        ]
        if "order" in declared and not ordered_relevant:
            return _sort_list(items)
        return items
    if type(value) is str:
        return _normalize_string(
            value, key=current_key, declared=declared, preserve=ordered_relevant
        )
    return value


def _drop_heap_regions(
    heap: Mapping[str, Any],
    omitted: frozenset[str],
    *,
    proved: bool,
) -> dict[str, Any]:
    thawed = _thaw_structured(heap)
    if not omitted:
        return thawed if isinstance(thawed, dict) else dict(thawed)
    if not proved:
        raise ProgramAbstractionError("unproved heap omission cannot be applied")
    if "heap" in omitted or "*" in omitted:
        return {"omitted": True}
    return {key: value for key, value in thawed.items() if key not in omitted}


# ---------------------------------------------------------------------------
# Profile soundness
# ---------------------------------------------------------------------------


def _derived_reuse_admitted(
    *,
    soundness_claim: str,
    omitted_heap_regions: Sequence[str],
    omitted_value_paths: Sequence[str],
    heap_omission_proved: bool,
    value_omission_proved: bool,
    unavailable_dimensions: Sequence[str],
    relevant_dimensions: Sequence[str],
) -> bool:
    if soundness_claim not in {
        AbstractionSoundnessClaim.EXACT.value,
        AbstractionSoundnessClaim.OVER_APPROXIMATION.value,
    }:
        return False
    if omitted_heap_regions and not heap_omission_proved:
        return False
    if omitted_value_paths and not value_omission_proved:
        return False
    if set(unavailable_dimensions) & set(relevant_dimensions):
        return False
    return True


def _validate_profile_soundness(
    *,
    query_family: str,
    relevant_dimensions: Sequence[str],
    irrelevant_normalizations: Sequence[str],
    omitted_heap_regions: Sequence[str],
    omitted_value_paths: Sequence[str],
    heap_omission_proved: bool,
    value_omission_proved: bool,
    soundness_claim: str,
    unavailable_dimensions: Sequence[str],
) -> None:
    required = FAMILY_REQUIRED_RELEVANT[query_family]
    missing_required = required - set(relevant_dimensions)
    if missing_required:
        raise ProgramAbstractionError(
            "unsound profile: missing required relevant dimension "
            f"{sorted(missing_required)}"
        )
    forbidden = FAMILY_FORBIDDEN_NORMALIZATIONS[query_family]
    illegal = set(irrelevant_normalizations) & forbidden
    if illegal:
        raise ProgramAbstractionError(
            "order cannot be normalized for inverse_trace"
            if "order" in illegal
            else f"unsound profile: forbidden normalization {sorted(illegal)}"
        )
    if omitted_heap_regions:
        if "heap_regions" not in irrelevant_normalizations:
            raise ProgramAbstractionError(
                "unsound profile: heap omission requires heap_regions normalization"
            )
        if not heap_omission_proved:
            raise ProgramAbstractionError(
                "unproved heap omission cannot admit reuse"
            )
    if omitted_value_paths:
        if "values" not in irrelevant_normalizations:
            raise ProgramAbstractionError(
                "unsound profile: value omission requires values normalization"
            )
        if not value_omission_proved:
            raise ProgramAbstractionError(
                "unproved value omission cannot admit reuse"
            )
    if heap_omission_proved and "heap_regions" not in irrelevant_normalizations:
        raise ProgramAbstractionError(
            "unsound profile: heap_omission_proved requires heap_regions"
        )
    if value_omission_proved and "values" not in irrelevant_normalizations:
        raise ProgramAbstractionError(
            "unsound profile: value_omission_proved requires values"
        )
    approximating = set(irrelevant_normalizations) - {"order"}
    if soundness_claim == AbstractionSoundnessClaim.EXACT.value and (
        approximating or omitted_heap_regions or omitted_value_paths
    ):
        raise ProgramAbstractionError(
            "cannot claim exact soundness while omitting heap, values, or "
            "approximating irrelevant categories"
        )
    if soundness_claim == AbstractionSoundnessClaim.UNDER_APPROXIMATION.value:
        if omitted_heap_regions or omitted_value_paths:
            raise ProgramAbstractionError(
                "unsound profile: under-approximation with omissions cannot admit reuse"
            )
    overlap = set(relevant_dimensions) & set(unavailable_dimensions)
    if overlap:
        raise ProgramAbstractionError(
            "abstraction dimensions cannot also be unavailable"
        )
    relevant_omitted = set(omitted_value_paths) & set(relevant_dimensions)
    if relevant_omitted:
        raise ProgramAbstractionError(
            "unsound profile: cannot omit a relevant dimension "
            f"{sorted(relevant_omitted)}"
        )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateAbstractionProfile:
    """Versioned query-family abstraction that participates in abstract identity."""

    language: ProgramLanguage | str
    profile_name: str
    query_family: QueryFamily | str
    relevant_dimensions: Sequence[str]
    irrelevant_normalizations: Sequence[str] = ()
    omitted_heap_regions: Sequence[str] = ()
    omitted_value_paths: Sequence[str] = ()
    heap_omission_proved: bool = False
    value_omission_proved: bool = False
    soundness_claim: AbstractionSoundnessClaim | str = AbstractionSoundnessClaim.UNKNOWN
    unavailable_dimensions: Sequence[str] = ()
    environment_binding_cid: str | None = None
    transition_slice_cid: str | None = None
    profile_version: str = "1.0.0"
    reuse_admitted: bool | None = None

    SCHEMA: ClassVar[str] = STATE_ABSTRACTION_PROFILE_SCHEMA
    INTERFACE: ClassVar[str] = STATE_ABSTRACTION_PROFILE_INTERFACE
    CID_FIELD: ClassVar[str] = "abstraction_profile_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "profile_name",
            "query_family",
            "relevant_dimensions",
            "irrelevant_normalizations",
            "omitted_heap_regions",
            "omitted_value_paths",
            "heap_omission_proved",
            "value_omission_proved",
            "soundness_claim",
            "unavailable_dimensions",
            "environment_binding_cid",
            "transition_slice_cid",
            "profile_version",
            "reuse_admitted",
            "abstraction_profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "profile_name", _text(self.profile_name, "profile_name"))
        object.__setattr__(self, "query_family", _query_family(self.query_family))
        object.__setattr__(
            self,
            "relevant_dimensions",
            _unique_sorted_texts(self.relevant_dimensions, "relevant_dimension"),
        )
        object.__setattr__(
            self,
            "irrelevant_normalizations",
            _unique_sorted_texts(
                (
                    _irrelevant_category(item, "irrelevant_normalization")
                    for item in self.irrelevant_normalizations
                ),
                "irrelevant_normalization",
            ),
        )
        object.__setattr__(
            self,
            "omitted_heap_regions",
            _unique_sorted_texts(self.omitted_heap_regions, "omitted_heap_region"),
        )
        object.__setattr__(
            self,
            "omitted_value_paths",
            _unique_sorted_texts(self.omitted_value_paths, "omitted_value_path"),
        )
        object.__setattr__(
            self,
            "heap_omission_proved",
            _bool(self.heap_omission_proved, "heap_omission_proved"),
        )
        object.__setattr__(
            self,
            "value_omission_proved",
            _bool(self.value_omission_proved, "value_omission_proved"),
        )
        object.__setattr__(
            self,
            "soundness_claim",
            _enum(self.soundness_claim, AbstractionSoundnessClaim, "soundness_claim"),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        object.__setattr__(
            self,
            "environment_binding_cid",
            _optional_cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self,
            "transition_slice_cid",
            _optional_cid(self.transition_slice_cid, "transition_slice_cid"),
        )
        object.__setattr__(
            self, "profile_version", _text(self.profile_version, "profile_version")
        )
        if not self.relevant_dimensions:
            raise ProgramAbstractionError("abstraction profile requires relevant_dimensions")
        _validate_profile_soundness(
            query_family=str(self.query_family),
            relevant_dimensions=self.relevant_dimensions,
            irrelevant_normalizations=self.irrelevant_normalizations,
            omitted_heap_regions=self.omitted_heap_regions,
            omitted_value_paths=self.omitted_value_paths,
            heap_omission_proved=self.heap_omission_proved,
            value_omission_proved=self.value_omission_proved,
            soundness_claim=str(self.soundness_claim),
            unavailable_dimensions=self.unavailable_dimensions,
        )
        derived = _derived_reuse_admitted(
            soundness_claim=str(self.soundness_claim),
            omitted_heap_regions=self.omitted_heap_regions,
            omitted_value_paths=self.omitted_value_paths,
            heap_omission_proved=self.heap_omission_proved,
            value_omission_proved=self.value_omission_proved,
            unavailable_dimensions=self.unavailable_dimensions,
            relevant_dimensions=self.relevant_dimensions,
        )
        claimed = self.reuse_admitted
        if claimed is None:
            object.__setattr__(self, "reuse_admitted", derived)
        else:
            flag = _bool(claimed, "reuse_admitted")
            if flag and not derived:
                raise ProgramAbstractionError(
                    "reuse is not admitted for an unproved or unknown profile"
                )
            object.__setattr__(self, "reuse_admitted", flag)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "profile_name": self.profile_name,
            "query_family": self.query_family,
            "relevant_dimensions": list(self.relevant_dimensions),
            "irrelevant_normalizations": list(self.irrelevant_normalizations),
            "omitted_heap_regions": list(self.omitted_heap_regions),
            "omitted_value_paths": list(self.omitted_value_paths),
            "heap_omission_proved": self.heap_omission_proved,
            "value_omission_proved": self.value_omission_proved,
            "soundness_claim": self.soundness_claim,
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "environment_binding_cid": self.environment_binding_cid,
            "transition_slice_cid": self.transition_slice_cid,
            "profile_version": self.profile_version,
            "reuse_admitted": self.reuse_admitted,
        }

    @property
    def abstraction_profile_cid(self) -> str:
        return program_abstraction_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_abstraction_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["abstraction_profile_cid"] = self.abstraction_profile_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
            StateAbstractionProfileIdentity,
        )

        identity = StateAbstractionProfileIdentity(
            language=self.language,
            profile_name=self.profile_name,
            dimensions=self.relevant_dimensions,
            unavailable_dimensions=self.unavailable_dimensions,
            soundness_claim=self.soundness_claim,
        )
        return identity.to_dict()

    def declared_irrelevant(self) -> frozenset[str]:
        return frozenset(self.irrelevant_normalizations)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateAbstractionProfile":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class CanonicalAbstractState:
    """Profile-scoped abstract identity that excludes the raw execution CID."""

    language: ProgramLanguage | str
    query_family: QueryFamily | str
    abstraction_profile_cid: str
    tree_cid: str
    environment_binding_cid: str
    code_cid: str
    abstract_state: Mapping[str, Any]
    unavailable_dimensions: Sequence[str] = ()
    observation_status: ObservationStatus | str = ObservationStatus.OBSERVED
    completeness_claim: CompletenessClaim | str = CompletenessClaim.FULL_STATE

    SCHEMA: ClassVar[str] = CANONICAL_ABSTRACT_STATE_SCHEMA
    INTERFACE: ClassVar[str] = CANONICAL_ABSTRACT_STATE_INTERFACE
    CID_FIELD: ClassVar[str] = "canonical_abstract_state_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "query_family",
            "abstraction_profile_cid",
            "tree_cid",
            "environment_binding_cid",
            "code_cid",
            "abstract_state",
            "unavailable_dimensions",
            "observation_status",
            "completeness_claim",
            "canonical_abstract_state_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "query_family", _query_family(self.query_family))
        object.__setattr__(
            self,
            "abstraction_profile_cid",
            _cid(self.abstraction_profile_cid, "abstraction_profile_cid"),
        )
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(self, "code_cid", _cid(self.code_cid, "code_cid"))
        object.__setattr__(
            self, "abstract_state", _mapping(self.abstract_state, "abstract_state")
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        object.__setattr__(
            self,
            "observation_status",
            _enum(self.observation_status, ObservationStatus, "observation_status"),
        )
        object.__setattr__(
            self,
            "completeness_claim",
            _enum(self.completeness_claim, CompletenessClaim, "completeness_claim"),
        )
        if str(self.completeness_claim) == CompletenessClaim.FULL_STATE.value and (
            self.unavailable_dimensions
        ):
            raise ProgramAbstractionError(
                "CanonicalAbstractState cannot claim full state while dimensions are unavailable"
            )
        if str(self.completeness_claim) in {
            CompletenessClaim.PARTIAL.value,
            CompletenessClaim.UNAVAILABLE.value,
        } and not self.unavailable_dimensions:
            raise ProgramAbstractionError(
                "CanonicalAbstractState partial/unavailable completeness requires "
                "unavailable_dimensions"
            )
        if str(self.completeness_claim) == CompletenessClaim.REDACTED.value:
            raise ProgramAbstractionError(
                "canonical abstract state cannot claim redacted completeness"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "query_family": self.query_family,
            "abstraction_profile_cid": self.abstraction_profile_cid,
            "tree_cid": self.tree_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "code_cid": self.code_cid,
            "abstract_state": _thaw_structured(self.abstract_state),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "observation_status": self.observation_status,
            "completeness_claim": self.completeness_claim,
        }

    @property
    def canonical_abstract_state_cid(self) -> str:
        return program_abstraction_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_abstraction_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["canonical_abstract_state_cid"] = self.canonical_abstract_state_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CanonicalAbstractState":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class AbstractionSoundnessResult:
    """Soundness verdict for one profile applied to one raw state."""

    language: ProgramLanguage | str
    query_family: QueryFamily | str
    abstraction_profile_cid: str
    soundness_claim: AbstractionSoundnessClaim | str
    reuse_admitted: bool
    omitted_heap_proved: bool
    omitted_values_proved: bool
    unknown_relevance_dimensions: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()
    transition_slice_cid: str | None = None

    SCHEMA: ClassVar[str] = ABSTRACTION_SOUNDNESS_RESULT_SCHEMA
    INTERFACE: ClassVar[str] = ABSTRACTION_SOUNDNESS_RESULT_INTERFACE
    CID_FIELD: ClassVar[str] = "abstraction_soundness_result_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "query_family",
            "abstraction_profile_cid",
            "soundness_claim",
            "reuse_admitted",
            "omitted_heap_proved",
            "omitted_values_proved",
            "unknown_relevance_dimensions",
            "unavailable_dimensions",
            "transition_slice_cid",
            "abstraction_soundness_result_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "query_family", _query_family(self.query_family))
        object.__setattr__(
            self,
            "abstraction_profile_cid",
            _cid(self.abstraction_profile_cid, "abstraction_profile_cid"),
        )
        object.__setattr__(
            self,
            "soundness_claim",
            _enum(self.soundness_claim, AbstractionSoundnessClaim, "soundness_claim"),
        )
        object.__setattr__(self, "reuse_admitted", _bool(self.reuse_admitted, "reuse_admitted"))
        object.__setattr__(
            self,
            "omitted_heap_proved",
            _bool(self.omitted_heap_proved, "omitted_heap_proved"),
        )
        object.__setattr__(
            self,
            "omitted_values_proved",
            _bool(self.omitted_values_proved, "omitted_values_proved"),
        )
        object.__setattr__(
            self,
            "unknown_relevance_dimensions",
            _unique_sorted_texts(
                self.unknown_relevance_dimensions, "unknown_relevance_dimension"
            ),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        object.__setattr__(
            self,
            "transition_slice_cid",
            _optional_cid(self.transition_slice_cid, "transition_slice_cid"),
        )
        if self.reuse_admitted and str(self.soundness_claim) in {
            AbstractionSoundnessClaim.UNKNOWN.value,
            AbstractionSoundnessClaim.UNDER_APPROXIMATION.value,
        }:
            raise ProgramAbstractionError(
                "reuse is not admitted under unknown or under-approximate soundness"
            )
        if self.reuse_admitted and self.unknown_relevance_dimensions:
            raise ProgramAbstractionError(
                "reuse is not admitted while relevance is unknown"
            )
        if self.reuse_admitted and not self.omitted_heap_proved:
            raise ProgramAbstractionError(
                "reuse is not admitted without proved heap-omission status"
            )
        if self.reuse_admitted and not self.omitted_values_proved:
            raise ProgramAbstractionError(
                "reuse is not admitted without proved value-omission status"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "query_family": self.query_family,
            "abstraction_profile_cid": self.abstraction_profile_cid,
            "soundness_claim": self.soundness_claim,
            "reuse_admitted": self.reuse_admitted,
            "omitted_heap_proved": self.omitted_heap_proved,
            "omitted_values_proved": self.omitted_values_proved,
            "unknown_relevance_dimensions": list(self.unknown_relevance_dimensions),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "transition_slice_cid": self.transition_slice_cid,
        }

    @property
    def abstraction_soundness_result_cid(self) -> str:
        return program_abstraction_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_abstraction_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["abstraction_soundness_result_cid"] = self.abstraction_soundness_result_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AbstractionSoundnessResult":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class StateAbstractionReceipt:
    """Work receipt binding a raw state, profile, canonical abstract identity, and soundness."""

    language: ProgramLanguage | str
    query_family: QueryFamily | str
    raw_execution_state_cid: str
    abstract_program_state_cid: str
    canonical_abstract_state_cid: str
    abstraction_profile_cid: str
    soundness_result_cid: str
    soundness_claim: AbstractionSoundnessClaim | str
    reuse_admitted: bool
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = STATE_ABSTRACTION_RECEIPT_SCHEMA
    INTERFACE: ClassVar[str] = STATE_ABSTRACTION_RECEIPT_INTERFACE
    CID_FIELD: ClassVar[str] = "state_abstraction_receipt_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "query_family",
            "raw_execution_state_cid",
            "abstract_program_state_cid",
            "canonical_abstract_state_cid",
            "abstraction_profile_cid",
            "soundness_result_cid",
            "soundness_claim",
            "reuse_admitted",
            "unavailable_dimensions",
            "state_abstraction_receipt_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "query_family", _query_family(self.query_family))
        object.__setattr__(
            self,
            "raw_execution_state_cid",
            _cid(self.raw_execution_state_cid, "raw_execution_state_cid"),
        )
        object.__setattr__(
            self,
            "abstract_program_state_cid",
            _cid(self.abstract_program_state_cid, "abstract_program_state_cid"),
        )
        object.__setattr__(
            self,
            "canonical_abstract_state_cid",
            _cid(self.canonical_abstract_state_cid, "canonical_abstract_state_cid"),
        )
        object.__setattr__(
            self,
            "abstraction_profile_cid",
            _cid(self.abstraction_profile_cid, "abstraction_profile_cid"),
        )
        object.__setattr__(
            self,
            "soundness_result_cid",
            _cid(self.soundness_result_cid, "soundness_result_cid"),
        )
        object.__setattr__(
            self,
            "soundness_claim",
            _enum(self.soundness_claim, AbstractionSoundnessClaim, "soundness_claim"),
        )
        object.__setattr__(self, "reuse_admitted", _bool(self.reuse_admitted, "reuse_admitted"))
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        if self.raw_execution_state_cid == self.abstract_program_state_cid:
            raise ProgramAbstractionError(
                "raw and abstract execution states must remain distinct"
            )
        if self.raw_execution_state_cid == self.canonical_abstract_state_cid:
            raise ProgramAbstractionError(
                "raw and abstract execution states must remain distinct"
            )
        if self.reuse_admitted and str(self.soundness_claim) in {
            AbstractionSoundnessClaim.UNKNOWN.value,
            AbstractionSoundnessClaim.UNDER_APPROXIMATION.value,
        }:
            raise ProgramAbstractionError(
                "reuse is not admitted under unknown or under-approximate soundness"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "query_family": self.query_family,
            "raw_execution_state_cid": self.raw_execution_state_cid,
            "abstract_program_state_cid": self.abstract_program_state_cid,
            "canonical_abstract_state_cid": self.canonical_abstract_state_cid,
            "abstraction_profile_cid": self.abstraction_profile_cid,
            "soundness_result_cid": self.soundness_result_cid,
            "soundness_claim": self.soundness_claim,
            "reuse_admitted": self.reuse_admitted,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def state_abstraction_receipt_cid(self) -> str:
        return program_abstraction_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_abstraction_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["state_abstraction_receipt_cid"] = self.state_abstraction_receipt_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateAbstractionReceipt":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class AbstractionOutcome:
    """In-memory work product of one abstraction; the receipt is the durable record."""

    profile: StateAbstractionProfile
    receipt: StateAbstractionReceipt
    abstract_program_state: AbstractProgramState
    canonical_abstract_state: CanonicalAbstractState
    soundness: AbstractionSoundnessResult

    @property
    def reuse_admitted(self) -> bool:
        return self.receipt.reuse_admitted

    @property
    def canonical_abstract_state_cid(self) -> str:
        return self.canonical_abstract_state.canonical_abstract_state_cid


# ---------------------------------------------------------------------------
# Slice projection
# ---------------------------------------------------------------------------


def _stack_logical_names(frames: Sequence[StackFrameState]) -> list[str]:
    ordered = sorted(frames, key=lambda frame: int(frame.ordinal))
    return [str(frame.logical_name) for frame in ordered]


def _event_order(events: Sequence[ProgramEvent], declared: frozenset[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in events:
        payload = _normalize_tree(
            _thaw_structured(event.payload),
            declared=declared,
            omitted_value_paths=frozenset(),
            omitted_heap_regions=frozenset(),
            value_omission_proved=False,
            heap_omission_proved=False,
            path=("payload",),
            ordered_relevant=True,
        )
        records.append(
            {
                "event_kind": str(event.event_kind),
                "logical_name": str(event.logical_name),
                "payload": payload,
            }
        )
    return records


def _observed(raw: ProgramExecutionState) -> dict[str, Any]:
    return _thaw_structured(raw.observed_state)


def _project_family_slice(
    *,
    profile: StateAbstractionProfile,
    raw: ProgramExecutionState,
    frames: Sequence[StackFrameState],
    events: Sequence[ProgramEvent],
    trace: ExecutionTrace | None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Return (slice, unavailable, unknown-relevance)."""

    declared = profile.declared_irrelevant()
    observed = _observed(raw)
    relevant = set(profile.relevant_dimensions)
    unavailable: set[str] = set(raw.unavailable_dimensions) | set(
        profile.unavailable_dimensions
    )
    unknown: set[str] = set()
    slice_map: dict[str, Any] = {
        "query_family": str(profile.query_family),
        "normalized": sorted(declared),
    }

    known_extractors = {
        "code_cid": lambda: raw.code_cid,
        "callee": lambda: observed.get("callee", observed.get("logical_callee")),
        "logical_callee": lambda: observed.get("logical_callee", observed.get("callee")),
        "locals": lambda: observed.get("locals"),
        "branch_predicate": lambda: observed.get("branch_predicate"),
        "event_kind": lambda: _extract_event_kind(observed, events),
        "line": lambda: observed.get("line"),
        "exception_active": lambda: raw.exception_snapshot_cid is not None,
        "handler_active": lambda: raw.handler_state_cid is not None,
        "exception_type": lambda: observed.get("exception_type"),
        "handler_kind": lambda: observed.get("handler_kind"),
        "contract_state": lambda: observed.get("contract_state"),
        "failing_locals": lambda: observed.get("failing_locals"),
        "assignments": lambda: observed.get("assignments"),
        "heap_summary": lambda: _thaw_structured(raw.heap_summary),
        "stack_logical_names": lambda: (
            _stack_logical_names(frames)
            if frames
            else observed.get("stack_logical_names")
        ),
        "event_order": lambda: (
            _event_order(events, declared)
            if events
            else observed.get("event_order")
        ),
    }

    for dimension in profile.relevant_dimensions:
        extractor = known_extractors.get(dimension)
        if extractor is None:
            value = observed.get(dimension)
        else:
            value = extractor()
        if value is None:
            if dimension == "heap_summary" and str(raw.heap_bound) == HeapBound.UNAVAILABLE.value:
                unavailable.add("heap")
                unavailable.add("heap_summary")
                continue
            if dimension == "event_order" and not events and "event_order" not in observed:
                unavailable.add("event_order")
                continue
            if dimension == "stack_logical_names" and not frames:
                if "stack_logical_names" not in observed:
                    if not raw.stack_frame_cids:
                        unavailable.add("stack_logical_names")
                        unavailable.add("call_stack")
                    else:
                        unavailable.add("stack_logical_names")
                    continue
            unavailable.add(dimension)
            continue
        slice_map[dimension] = value

    for key in observed:
        if key in relevant or str(key) in KNOWN_SLICE_KEYS:
            continue
        category = _key_category(str(key))
        if category is not None and category in declared:
            continue
        if str(key) in declared:
            continue
        unknown.add(str(key))
        unavailable.add(str(key))

    if "heap_summary" in relevant and str(raw.heap_bound) == HeapBound.UNAVAILABLE.value:
        unavailable.add("heap")
        unavailable.add("heap_summary")
        slice_map.pop("heap_summary", None)

    if profile.query_family == QueryFamily.INVERSE_TRACE.value and trace is not None:
        if "event_order" in relevant and "event_order" not in slice_map and not events:
            unavailable.add("event_order")

    return slice_map, sorted(unavailable), sorted(unknown)


def _extract_event_kind(
    observed: Mapping[str, Any], events: Sequence[ProgramEvent]
) -> Any:
    if "event_kind" in observed:
        return observed["event_kind"]
    if events:
        return str(events[-1].event_kind)
    return None


# ---------------------------------------------------------------------------
# Abstractor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProgramStateAbstractor:
    """Apply one admitted ``StateAbstractionProfile@1`` to a raw execution state."""

    profile: StateAbstractionProfile

    INTERFACE: ClassVar[str] = PROGRAM_STATE_ABSTRACTOR_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.profile, StateAbstractionProfile):
            raise ProgramAbstractionError("abstractor requires a StateAbstractionProfile")

    def abstract(
        self,
        raw: ProgramExecutionState,
        *,
        frames: Sequence[StackFrameState] = (),
        events: Sequence[ProgramEvent] = (),
        trace: ExecutionTrace | None = None,
    ) -> AbstractionOutcome:
        if not isinstance(raw, ProgramExecutionState):
            raise ProgramAbstractionError("abstraction requires a ProgramExecutionState")
        if str(raw.language) != str(self.profile.language):
            raise ProgramAbstractionError(
                "raw state language must match the abstraction profile"
            )
        for frame in frames:
            if not isinstance(frame, StackFrameState):
                raise ProgramAbstractionError("frames must be StackFrameState values")
        for event in events:
            if not isinstance(event, ProgramEvent):
                raise ProgramAbstractionError("events must be ProgramEvent values")
        if trace is not None and not isinstance(trace, ExecutionTrace):
            raise ProgramAbstractionError("trace must be an ExecutionTrace")

        slice_map, unavailable, unknown = _project_family_slice(
            profile=self.profile,
            raw=raw,
            frames=tuple(frames),
            events=tuple(events),
            trace=trace,
        )
        declared = self.profile.declared_irrelevant()
        omitted_values = frozenset(self.profile.omitted_value_paths)
        omitted_heap = frozenset(self.profile.omitted_heap_regions)
        normalized = _normalize_tree(
            slice_map,
            declared=declared,
            omitted_value_paths=omitted_values,
            omitted_heap_regions=omitted_heap,
            value_omission_proved=self.profile.value_omission_proved,
            heap_omission_proved=self.profile.heap_omission_proved,
            path=(),
            ordered_relevant=False,
        )
        if not isinstance(normalized, dict):
            raise ProgramAbstractionError("abstract slice must be a mapping")

        if "heap_summary" in normalized and omitted_heap:
            normalized["heap_summary"] = _drop_heap_regions(
                normalized["heap_summary"],
                omitted_heap,
                proved=self.profile.heap_omission_proved,
            )

        relevant_unavailable = set(unavailable) & set(self.profile.relevant_dimensions)
        if str(self.profile.soundness_claim) == AbstractionSoundnessClaim.EXACT.value and (
            unknown or relevant_unavailable
        ):
            raise ProgramAbstractionError(
                "unsound profile: exact soundness cannot widen unknown relevance"
            )

        heap_proved = bool(self.profile.heap_omission_proved) or not bool(
            self.profile.omitted_heap_regions
        )
        value_proved = bool(self.profile.value_omission_proved) or not bool(
            self.profile.omitted_value_paths
        )
        result_claim = str(self.profile.soundness_claim)
        if unknown:
            result_claim = AbstractionSoundnessClaim.UNKNOWN.value
        reuse = bool(self.profile.reuse_admitted)
        if unknown or relevant_unavailable:
            reuse = False
        if result_claim in {
            AbstractionSoundnessClaim.UNKNOWN.value,
            AbstractionSoundnessClaim.UNDER_APPROXIMATION.value,
        }:
            reuse = False
        if not heap_proved or not value_proved:
            reuse = False
        if str(raw.observation_status) in {
            ObservationStatus.UNAVAILABLE.value,
            ObservationStatus.INFERRED_UNTRUSTED.value,
        }:
            reuse = False
            if result_claim == AbstractionSoundnessClaim.EXACT.value:
                result_claim = AbstractionSoundnessClaim.UNKNOWN.value

        if relevant_unavailable and not unknown:
            if result_claim == AbstractionSoundnessClaim.EXACT.value:
                result_claim = AbstractionSoundnessClaim.UNKNOWN.value

        observation_status = str(raw.observation_status)
        if relevant_unavailable and observation_status == ObservationStatus.OBSERVED.value:
            observation_status = ObservationStatus.UNAVAILABLE.value
        if unknown and observation_status == ObservationStatus.OBSERVED.value:
            observation_status = ObservationStatus.UNAVAILABLE.value

        if not unavailable:
            completeness = CompletenessClaim.FULL_STATE.value
        elif set(self.profile.relevant_dimensions) <= set(unavailable):
            completeness = CompletenessClaim.UNAVAILABLE.value
        else:
            completeness = CompletenessClaim.PARTIAL.value

        canonical = CanonicalAbstractState(
            language=self.profile.language,
            query_family=self.profile.query_family,
            abstraction_profile_cid=self.profile.abstraction_profile_cid,
            tree_cid=raw.tree_cid,
            environment_binding_cid=raw.environment_binding_cid,
            code_cid=raw.code_cid,
            abstract_state=normalized,
            unavailable_dimensions=unavailable,
            observation_status=observation_status,
            completeness_claim=completeness,
        )
        abstract = AbstractProgramState(
            language=raw.language,
            raw_execution_state_cid=raw.program_execution_state_cid,
            abstraction_profile_cid=self.profile.abstraction_profile_cid,
            tree_cid=raw.tree_cid,
            environment_binding_cid=raw.environment_binding_cid,
            abstract_state=normalized,
            stack_frame_cids=raw.stack_frame_cids,
            unavailable_dimensions=unavailable,
            observation_status=observation_status,
            completeness_claim=completeness,
        )
        soundness = AbstractionSoundnessResult(
            language=self.profile.language,
            query_family=self.profile.query_family,
            abstraction_profile_cid=self.profile.abstraction_profile_cid,
            soundness_claim=result_claim,
            reuse_admitted=reuse,
            omitted_heap_proved=heap_proved,
            omitted_values_proved=value_proved,
            unknown_relevance_dimensions=unknown,
            unavailable_dimensions=unavailable,
            transition_slice_cid=self.profile.transition_slice_cid,
        )
        receipt = StateAbstractionReceipt(
            language=self.profile.language,
            query_family=self.profile.query_family,
            raw_execution_state_cid=raw.program_execution_state_cid,
            abstract_program_state_cid=abstract.abstract_program_state_cid,
            canonical_abstract_state_cid=canonical.canonical_abstract_state_cid,
            abstraction_profile_cid=self.profile.abstraction_profile_cid,
            soundness_result_cid=soundness.abstraction_soundness_result_cid,
            soundness_claim=result_claim,
            reuse_admitted=reuse,
            unavailable_dimensions=unavailable,
        )
        return AbstractionOutcome(
            profile=self.profile,
            receipt=receipt,
            abstract_program_state=abstract,
            canonical_abstract_state=canonical,
            soundness=soundness,
        )

    def project(
        self,
        raw: ProgramExecutionState,
        *,
        frames: Sequence[StackFrameState] = (),
        events: Sequence[ProgramEvent] = (),
        trace: ExecutionTrace | None = None,
    ) -> AbstractProgramState:
        return self.abstract(raw, frames=frames, events=events, trace=trace).abstract_program_state

    def assess(
        self,
        raw: ProgramExecutionState,
        *,
        frames: Sequence[StackFrameState] = (),
        events: Sequence[ProgramEvent] = (),
        trace: ExecutionTrace | None = None,
    ) -> AbstractionSoundnessResult:
        return self.abstract(raw, frames=frames, events=events, trace=trace).soundness

    def to_execution_receipt(
        self,
        raw: ProgramExecutionState,
        *,
        frames: Sequence[StackFrameState] = (),
        events: Sequence[ProgramEvent] = (),
        trace: ExecutionTrace | None = None,
    ) -> ExecutionStateAbstractionReceipt:
        outcome = self.abstract(raw, frames=frames, events=events, trace=trace)
        return bind_abstraction_receipt(
            raw,
            outcome.abstract_program_state,
            soundness_claim=outcome.soundness.soundness_claim,
        )


def admitted_abstraction_profile(
    query_family: QueryFamily | str,
    *,
    language: ProgramLanguage | str = ProgramLanguage.PYTHON,
    **overrides: Any,
) -> StateAbstractionProfile:
    """Return the admitted Python profile for one transition query family."""

    family = _query_family(query_family)
    forbidden = FAMILY_FORBIDDEN_NORMALIZATIONS[family]
    fields: dict[str, Any] = {
        "language": language,
        "profile_name": FAMILY_PROFILE_NAMES[family],
        "query_family": family,
        "relevant_dimensions": FAMILY_DEFAULT_RELEVANT[family],
        "irrelevant_normalizations": tuple(
            item for item in DEFAULT_IRRELEVANT_NORMALIZATIONS if item not in forbidden
        ),
        "soundness_claim": AbstractionSoundnessClaim.OVER_APPROXIMATION,
        "reuse_admitted": True,
    }
    fields.update(overrides)
    return StateAbstractionProfile(**fields)


def abstract_program_state(
    raw: ProgramExecutionState,
    profile: StateAbstractionProfile,
    *,
    frames: Sequence[StackFrameState] = (),
    events: Sequence[ProgramEvent] = (),
    trace: ExecutionTrace | None = None,
) -> StateAbstractionReceipt:
    """Abstract ``raw`` under ``profile`` and return the closed work receipt."""

    return ProgramStateAbstractor(profile).abstract(
        raw, frames=frames, events=events, trace=trace
    ).receipt


PROGRAM_ABSTRACTION_RECORD_TYPES: Final[tuple[type, ...]] = (
    StateAbstractionProfile,
    CanonicalAbstractState,
    AbstractionSoundnessResult,
    StateAbstractionReceipt,
)

_SCHEMA_TO_CLASS: Final[dict[str, type]] = {
    cls.SCHEMA: cls for cls in PROGRAM_ABSTRACTION_RECORD_TYPES
}


def decode_program_abstraction_record(data: Mapping[str, Any]) -> Any:
    """Dispatch one closed program-abstraction payload to its versioned record type."""

    if not isinstance(data, Mapping):
        raise ProgramAbstractionError("program-abstraction record must be a mapping")
    schema = data.get("schema")
    record_type = _SCHEMA_TO_CLASS.get(schema) if type(schema) is str else None
    if record_type is None:
        raise ProgramAbstractionError(f"unsupported program-abstraction schema {schema!r}")
    return record_type.from_dict(data)


def load_payload_schema() -> dict[str, Any]:
    """Load the packaged JSON Schema for program-abstraction payloads."""

    from pathlib import Path

    path = (
        Path(__file__).resolve().parent / "schemas" / "program-abstraction.payload.schema.json"
    )
    return loads_program_abstraction_json(path.read_text(encoding="utf-8"))


__all__ = [
    "ABSTRACTION_SOUNDNESS_RESULT_INTERFACE",
    "ABSTRACTION_SOUNDNESS_RESULT_SCHEMA",
    "ADMITTED_LANGUAGES",
    "CANONICAL_ABSTRACT_STATE_INTERFACE",
    "CANONICAL_ABSTRACT_STATE_SCHEMA",
    "COLLECTION_SEMANTICS_DECLARATION",
    "DEFAULT_IRRELEVANT_NORMALIZATIONS",
    "FAMILY_DEFAULT_RELEVANT",
    "FAMILY_FORBIDDEN_NORMALIZATIONS",
    "FAMILY_REQUIRED_RELEVANT",
    "IRRELEVANT_CATEGORIES",
    "PROGRAM_STATE_ABSTRACTOR_INTERFACE",
    "QUERY_FAMILIES",
    "STATE_ABSTRACTION_PROFILE_INTERFACE",
    "STATE_ABSTRACTION_PROFILE_SCHEMA",
    "STATE_ABSTRACTION_RECEIPT_INTERFACE",
    "STATE_ABSTRACTION_RECEIPT_SCHEMA",
    "UNAVAILABLE_LANGUAGES",
    "AbstractionOutcome",
    "AbstractionSoundnessClaim",
    "AbstractionSoundnessResult",
    "CanonicalAbstractState",
    "CompletenessClaim",
    "IrrelevantCategory",
    "ObservationStatus",
    "ProgramAbstractionError",
    "ProgramLanguage",
    "ProgramStateAbstractor",
    "QueryFamily",
    "StateAbstractionProfile",
    "StateAbstractionReceipt",
    "abstract_program_state",
    "admitted_abstraction_profile",
    "canonical_program_abstraction_bytes",
    "canonicalize_program_abstraction_value",
    "decode_program_abstraction_record",
    "load_payload_schema",
    "loads_program_abstraction_json",
    "program_abstraction_cid_for",
]
