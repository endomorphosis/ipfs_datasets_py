"""Closed dynamic execution-state, event, and trace contracts.

This module owns the datasets ``StackFrameState@1``, ``ProgramExecutionState@1``,
``AbstractProgramState@1``, ``ProgramEvent@1``, ``ExecutionTrace@1``,
``ExecutionTraceSegment@1``, ``ExecutionObservation@1``, and
``StateAbstractionReceipt@1`` family, together with the adjacent exception,
handler, and redaction-profile records.

Authority rules (normative):

* Datasets alone defines execution-state, event, and trace meaning.  This
  module does not introduce a tracer, scheduler lifecycle, operational
  acceptance, or storage engine.
* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
  Collection-semantics declarations reuse ``ir_core.canonical``.
* Every event binds exact tree, source, code, and environment identities.
  Call-stack order and exception/handler state are preserved; they are never
  sorted away or treated as absent.
* Raw and abstract execution states always have distinct CIDs.  The versioned
  abstraction profile participates in abstract-state identity.
* Redaction never claims full state.  Secret and non-semantic fields fail
  closed.  Public records cannot carry raw trace bodies.
* Exception snapshots are not future execution.  Predicted and simulated
  events cannot decode as observations.
* Irrelevant wall-clock / host observations are excluded from identity.
  Records are recursively immutable, closed to unknown fields, and restricted
  to strict DAG-JSON types.  Unsupported languages remain typed unavailable.
* Existing software-contract ``@1`` identity payloads are not modified here.
  Execution records may project into the landed identity envelopes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import json
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


# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

STACK_FRAME_STATE_INTERFACE: Final[str] = "StackFrameState@1"
PROGRAM_EXECUTION_STATE_INTERFACE: Final[str] = "ProgramExecutionState@1"
ABSTRACT_PROGRAM_STATE_INTERFACE: Final[str] = "AbstractProgramState@1"
PROGRAM_EVENT_INTERFACE: Final[str] = "ProgramEvent@1"
EXECUTION_TRACE_INTERFACE: Final[str] = "ExecutionTrace@1"
EXECUTION_TRACE_SEGMENT_INTERFACE: Final[str] = "ExecutionTraceSegment@1"
EXECUTION_OBSERVATION_INTERFACE: Final[str] = "ExecutionObservation@1"
STATE_ABSTRACTION_RECEIPT_INTERFACE: Final[str] = "StateAbstractionReceipt@1"
EXCEPTION_SNAPSHOT_INTERFACE: Final[str] = "ExceptionSnapshot@1"
HANDLER_STATE_INTERFACE: Final[str] = "HandlerState@1"
REDACTION_PROFILE_INTERFACE: Final[str] = "RedactionProfile@1"

STACK_FRAME_STATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.stack-frame-state@1"
)
PROGRAM_EXECUTION_STATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-execution-state@1"
)
ABSTRACT_PROGRAM_STATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.abstract-program-state@1"
)
PROGRAM_EVENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-event@1"
)
EXECUTION_TRACE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.execution-trace@1"
)
EXECUTION_TRACE_SEGMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.execution-trace-segment@1"
)
EXECUTION_OBSERVATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.execution-observation@1"
)
STATE_ABSTRACTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.state-abstraction-receipt@1"
)
EXCEPTION_SNAPSHOT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.exception-snapshot@1"
)
HANDLER_STATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.handler-state@1"
)
REDACTION_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.redaction-profile@1"
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

COLLECTION_SEMANTICS_DECLARATION: Final[dict[str, str]] = {
    "/event_cids": CollectionSemantics.ORDERED.value,
    "/raw_execution_state_cids": CollectionSemantics.ORDERED.value,
    "/redacted_dimensions": CollectionSemantics.SET_LIKE.value,
    "/segment_cids": CollectionSemantics.ORDERED.value,
    "/stack_frame_cids": CollectionSemantics.ORDERED.value,
    "/traceback_stack_frame_cids": CollectionSemantics.ORDERED.value,
    "/unavailable_dimensions": CollectionSemantics.SET_LIKE.value,
}

FORBIDDEN_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "continuation_cid",
        "cookie",
        "credential",
        "embedding",
        "embedding_score",
        "embeddings",
        "future_state_cid",
        "hostname",
        "hnsw",
        "next_event_cid",
        "observed_at",
        "password",
        "pid",
        "predicted_event_cid",
        "private_key",
        "raw_memory",
        "refresh_token",
        "resume_event_cid",
        "scheduled_event_cid",
        "secret",
        "session_token",
        "timestamp",
        "timestamps",
        "vector",
        "vector_cid",
        "vectors",
        "wall_clock",
        "worker_id",
    }
)

FUTURE_EXECUTION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "continuation_cid",
        "future_state_cid",
        "next_event_cid",
        "predicted_event_cid",
        "resume_event_cid",
        "scheduled_event_cid",
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

IDENTITY_EVENT_KIND: Final[Mapping[str, str]] = MappingProxyType(
    {
        "call": "call",
        "return": "return",
        "line": "observe",
        "assign": "assign",
        "raise": "raise",
        "catch": "catch",
        "handler": "catch",
        "yield": "observe",
        "await": "observe",
        "branch": "branch",
        "enter": "enter",
        "exit": "exit",
        "external": "observe",
        "observe": "observe",
        "unavailable": "unavailable",
    }
)

STACK_REQUIRED_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "call",
        "return",
        "raise",
        "catch",
        "handler",
        "yield",
        "await",
        "enter",
        "exit",
    }
)

PUBLIC_PRIVACY_CLASSES: Final[frozenset[str]] = frozenset({"public", "internal"})


class ProgramExecutionError(ValueError):
    """Raised when a program-execution payload or catalog is malformed."""


class ProgramLanguage(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    SHELL = "shell"


class ObservationStatus(str, Enum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    REDACTED = "redacted"
    INFERRED_UNTRUSTED = "inferred_untrusted"


class PrivacyClass(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    PRIVATE = "private"


class CompletenessClaim(str, Enum):
    FULL_STATE = "full_state"
    PARTIAL = "partial"
    REDACTED = "redacted"
    UNAVAILABLE = "unavailable"


class EventKind(str, Enum):
    CALL = "call"
    RETURN = "return"
    LINE = "line"
    ASSIGN = "assign"
    RAISE = "raise"
    CATCH = "catch"
    HANDLER = "handler"
    YIELD = "yield"
    AWAIT = "await"
    BRANCH = "branch"
    ENTER = "enter"
    EXIT = "exit"
    EXTERNAL = "external"
    OBSERVE = "observe"
    UNAVAILABLE = "unavailable"


class EventOrigin(str, Enum):
    OBSERVED = "observed"
    PREDICTED = "predicted"
    SIMULATED = "simulated"


class HeapBound(str, Enum):
    BOUNDED_ABSTRACT = "bounded_abstract"
    UNAVAILABLE = "unavailable"


class HandlerKind(str, Enum):
    EXCEPT = "except"
    EXCEPT_STAR = "except_star"
    FINALLY = "finally"
    ELSE = "else"


class AbstractionSoundnessClaim(str, Enum):
    OVER_APPROXIMATION = "over_approximation"
    UNDER_APPROXIMATION = "under_approximation"
    EXACT = "exact"
    UNKNOWN = "unknown"


REQUIRED_EVENT_KINDS: Final[frozenset[str]] = frozenset(item.value for item in EventKind)
NON_OBSERVATION_ORIGINS: Final[frozenset[str]] = frozenset(
    {EventOrigin.PREDICTED.value, EventOrigin.SIMULATED.value}
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise ProgramExecutionError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ProgramExecutionError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise ProgramExecutionError(f"{name} contains invalid text")
    return value


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise ProgramExecutionError(f"{name} has unsupported value {value!r}") from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ProgramExecutionError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ProgramExecutionError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ProgramExecutionError(f"{name} must be a nonnegative integer")
    if value > MAX_SAFE_INTEGER:
        raise ProgramExecutionError(f"{name} exceeds the safe JSON integer range")
    return value


def _optional_nonneg_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _nonneg_int(value, name)


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
                raise ProgramExecutionError(
                    f"{name} rejects secret fields {sorted(secrets)}"
                )
            if forbidden & FUTURE_EXECUTION_FIELDS:
                raise ProgramExecutionError(
                    f"{name} rejects future-execution fields {sorted(forbidden)}"
                )
            raise ProgramExecutionError(
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
        raise ProgramExecutionError(f"{name} must be a mapping")
    result = _thaw_structured(dict(value))
    _reject_forbidden_value(result, name)
    try:
        validate_structured_value(result)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramExecutionError(f"{name} must be strict DAG-JSON") from exc
    encoded = canonical_dag_json_bytes(result)
    if len(encoded) > MAX_METADATA_BYTES:
        raise ProgramExecutionError(f"{name} exceeds its byte bound")
    return _freeze_structured(result)


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ProgramExecutionError(f"{name} must be a mapping")
    extra = set(data) - fields
    missing = fields - set(data)
    if extra:
        if extra & FUTURE_EXECUTION_FIELDS:
            raise ProgramExecutionError(
                f"{name} rejects future-execution fields {sorted(extra)}"
            )
        if extra & SECRET_FIELD_MARKERS:
            raise ProgramExecutionError(
                f"{name} rejects secret fields {sorted(extra)}"
            )
        raise ProgramExecutionError(f"{name} rejects unknown fields {sorted(extra)}")
    if missing:
        raise ProgramExecutionError(f"{name} missing fields {sorted(missing)}")
    _reject_forbidden_value(data, name)
    return dict(data)


def _unique_sorted_texts(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = [_text(value, name) for value in values]
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramExecutionError(f"{name} exceeds its item bound")
    ordered = tuple(sorted(items))
    if len(ordered) != len(set(ordered)):
        raise ProgramExecutionError(f"{name} must not contain duplicates")
    return ordered


def _ordered_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = tuple(_cid(value, name) for value in values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramExecutionError(f"{name} exceeds its item bound")
    return items


def _language(value: Any, name: str = "language") -> str:
    language = _enum(value, ProgramLanguage, name)
    if language not in ADMITTED_LANGUAGES:
        raise ProgramExecutionError(
            f"{name} {language!r} is typed unavailable in this profile"
        )
    return language


def _heap_bound(value: Any, name: str = "heap_bound") -> str:
    if type(value) is str and value.strip().lower().replace("-", "_") == "raw_memory":
        raise ProgramExecutionError("contracts do not promise raw-memory identity")
    return _enum(value, HeapBound, name)


def _assert_completeness(
    *,
    completeness_claim: str,
    redacted_dimensions: Sequence[str],
    unavailable_dimensions: Sequence[str],
    observation_status: str | None = None,
    event_origin: str | None = None,
    name: str,
) -> None:
    if completeness_claim == CompletenessClaim.FULL_STATE.value:
        if redacted_dimensions:
            raise ProgramExecutionError("redaction never claims full state")
        if unavailable_dimensions:
            raise ProgramExecutionError(
                f"{name} cannot claim full state while dimensions are unavailable"
            )
        if observation_status in {
            ObservationStatus.REDACTED.value,
            ObservationStatus.UNAVAILABLE.value,
            ObservationStatus.INFERRED_UNTRUSTED.value,
        }:
            raise ProgramExecutionError(
                f"{name} cannot claim full state under {observation_status} observation"
            )
        if event_origin in NON_OBSERVATION_ORIGINS:
            raise ProgramExecutionError(
                f"{name} cannot claim full state for {event_origin} events"
            )
    if completeness_claim == CompletenessClaim.REDACTED.value and not redacted_dimensions:
        raise ProgramExecutionError(
            f"{name} redacted completeness requires redacted_dimensions"
        )
    if completeness_claim == CompletenessClaim.UNAVAILABLE.value and not unavailable_dimensions:
        raise ProgramExecutionError(
            f"{name} unavailable completeness requires unavailable_dimensions"
        )
    if completeness_claim == CompletenessClaim.PARTIAL.value and not (
        unavailable_dimensions or redacted_dimensions
    ):
        raise ProgramExecutionError(
            f"{name} partial completeness requires unavailable or redacted dimensions"
        )


def _assert_public_raw_separation(*, privacy_class: str, includes_raw_bodies: bool, name: str) -> None:
    if includes_raw_bodies and privacy_class in PUBLIC_PRIVACY_CLASSES:
        raise ProgramExecutionError(
            f"{name} raw bodies remain private and cannot enter public records"
        )


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


def canonicalize_program_execution_value(value: Any) -> Any:
    """NFC-normalize, apply declared collection semantics, and reject floats."""

    try:
        validate_structured_value(value)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramExecutionError(
            "program-execution value must be strict DAG-JSON"
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
        raise ProgramExecutionError(
            "canonical program-execution value must be strict DAG-JSON"
        ) from exc
    content_bytes = canonical_dag_json_bytes(canonical)
    try:
        ir_bytes = ir_canonical_json_bytes(
            canonical,
            collection_schema=CollectionSchema(None, require_declared=False),
        )
    except CanonicalizationError as exc:
        raise ProgramExecutionError(
            "ir_core rejected the canonical program-execution value"
        ) from exc
    if ir_bytes != content_bytes:
        raise ProgramExecutionError(
            "ir_core canonical JSON diverged from software-contract DAG-JSON"
        )
    return canonical


def program_execution_cid_for(payload: Mapping[str, Any]) -> str:
    """Return the structured CID of one canonical program-execution payload."""

    return cid_for_structured(canonicalize_program_execution_value(payload))


def canonical_program_execution_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return canonical DAG-JSON bytes of one program-execution payload."""

    return canonical_dag_json_bytes(canonicalize_program_execution_value(payload))


def _verify_claimed(name: str, claimed: Any, payload: Mapping[str, Any]) -> str:
    canonical = canonicalize_program_execution_value(payload)
    try:
        return decode_and_recompute_structured(claimed, canonical)
    except Exception as exc:
        raise ProgramExecutionError(f"{name} cid does not verify") from exc


def _reject_nonfinite_constant(token: str) -> None:
    raise ProgramExecutionError(f"nonfinite JSON number {token!r} is rejected")


def _parse_int(token: str) -> int:
    try:
        value = int(token, 10)
    except ValueError as exc:
        raise ProgramExecutionError(f"JSON number {token!r} is not an integer") from exc
    if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
        raise ProgramExecutionError("integer is outside the safe JSON range")
    return value


def _parse_float(token: str) -> None:
    raise ProgramExecutionError(
        f"JSON number {token!r} is not a finite integer; floats are rejected"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProgramExecutionError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def loads_program_execution_json(text: str | bytes) -> Any:
    """Decode JSON text, rejecting duplicate keys, NaN, and floats."""

    if type(text) is bytes:
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProgramExecutionError("program-execution JSON must be UTF-8") from exc
    if type(text) is not str:
        raise ProgramExecutionError("program-execution JSON must be text or UTF-8 bytes")
    try:
        return json.loads(
            text,
            parse_int=_parse_int,
            parse_float=_parse_float,
            parse_constant=_reject_nonfinite_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ProgramExecutionError:
        raise
    except json.JSONDecodeError as exc:
        raise ProgramExecutionError("program-execution JSON is not well-formed") from exc


def _from_closed(cls: type[Any], data: Mapping[str, Any]) -> Any:
    payload = _closed(data, cls._FIELDS, cls.__name__)
    claimed = payload.pop(cls.CID_FIELD)
    if payload.pop("schema") != cls.SCHEMA:
        raise ProgramExecutionError(f"unsupported {cls.__name__} schema version")
    result = cls(**payload)
    _verify_claimed(cls.__name__, claimed, result.identity_payload())
    return result


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RedactionProfile:
    """Explicit redaction profile; never claims full state when dimensions are redacted."""

    privacy_class: PrivacyClass | str
    redacted_dimensions: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()
    completeness_claim: CompletenessClaim | str = CompletenessClaim.FULL_STATE

    SCHEMA: ClassVar[str] = REDACTION_PROFILE_SCHEMA
    INTERFACE: ClassVar[str] = REDACTION_PROFILE_INTERFACE
    CID_FIELD: ClassVar[str] = "redaction_profile_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "privacy_class",
            "redacted_dimensions",
            "unavailable_dimensions",
            "completeness_claim",
            "redaction_profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "privacy_class", _enum(self.privacy_class, PrivacyClass, "privacy_class")
        )
        object.__setattr__(
            self,
            "redacted_dimensions",
            _unique_sorted_texts(self.redacted_dimensions, "redacted_dimension"),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        object.__setattr__(
            self,
            "completeness_claim",
            _enum(self.completeness_claim, CompletenessClaim, "completeness_claim"),
        )
        _assert_completeness(
            completeness_claim=str(self.completeness_claim),
            redacted_dimensions=self.redacted_dimensions,
            unavailable_dimensions=self.unavailable_dimensions,
            name="RedactionProfile",
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "privacy_class": self.privacy_class,
            "redacted_dimensions": list(self.redacted_dimensions),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "completeness_claim": self.completeness_claim,
        }

    @property
    def redaction_profile_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_execution_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["redaction_profile_cid"] = self.redaction_profile_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RedactionProfile":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ExceptionSnapshot:
    """Bounded exception snapshot; never a continuation or future execution."""

    language: ProgramLanguage | str
    exception_type: str
    tree_cid: str
    source_cid: str
    code_cid: str
    environment_binding_cid: str
    exception_value_summary: Mapping[str, Any] = field(default_factory=dict)
    traceback_stack_frame_cids: Sequence[str] = ()
    raised_at_event_cid: str | None = None
    handler_state_cid: str | None = None
    future_execution: bool = False
    unavailable_dimensions: Sequence[str] = ()
    completeness_claim: CompletenessClaim | str = CompletenessClaim.FULL_STATE

    SCHEMA: ClassVar[str] = EXCEPTION_SNAPSHOT_SCHEMA
    INTERFACE: ClassVar[str] = EXCEPTION_SNAPSHOT_INTERFACE
    CID_FIELD: ClassVar[str] = "exception_snapshot_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "exception_type",
            "tree_cid",
            "source_cid",
            "code_cid",
            "environment_binding_cid",
            "exception_value_summary",
            "traceback_stack_frame_cids",
            "raised_at_event_cid",
            "handler_state_cid",
            "future_execution",
            "unavailable_dimensions",
            "completeness_claim",
            "exception_snapshot_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self, "exception_type", _text(self.exception_type, "exception_type")
        )
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(self, "code_cid", _cid(self.code_cid, "code_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self,
            "exception_value_summary",
            _mapping(self.exception_value_summary, "exception_value_summary"),
        )
        object.__setattr__(
            self,
            "traceback_stack_frame_cids",
            _ordered_cids(self.traceback_stack_frame_cids, "traceback_stack_frame_cid"),
        )
        object.__setattr__(
            self,
            "raised_at_event_cid",
            _optional_cid(self.raised_at_event_cid, "raised_at_event_cid"),
        )
        object.__setattr__(
            self,
            "handler_state_cid",
            _optional_cid(self.handler_state_cid, "handler_state_cid"),
        )
        future = _bool(self.future_execution, "future_execution")
        if future:
            raise ProgramExecutionError("exception snapshots are not future execution")
        object.__setattr__(self, "future_execution", False)
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        object.__setattr__(
            self,
            "completeness_claim",
            _enum(self.completeness_claim, CompletenessClaim, "completeness_claim"),
        )
        _assert_completeness(
            completeness_claim=str(self.completeness_claim),
            redacted_dimensions=(),
            unavailable_dimensions=self.unavailable_dimensions,
            name="ExceptionSnapshot",
        )
        if (
            not self.traceback_stack_frame_cids
            and "call_stack" not in self.unavailable_dimensions
        ):
            raise ProgramExecutionError(
                "exception snapshots preserve traceback order or mark call_stack unavailable"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "exception_type": self.exception_type,
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "code_cid": self.code_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "exception_value_summary": _thaw_structured(self.exception_value_summary),
            "traceback_stack_frame_cids": list(self.traceback_stack_frame_cids),
            "raised_at_event_cid": self.raised_at_event_cid,
            "handler_state_cid": self.handler_state_cid,
            "future_execution": False,
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "completeness_claim": self.completeness_claim,
        }

    @property
    def exception_snapshot_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_execution_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["exception_snapshot_cid"] = self.exception_snapshot_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExceptionSnapshot":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class HandlerState:
    """Active or matching exception-handler frame; not a predicted continuation."""

    language: ProgramLanguage | str
    handler_kind: HandlerKind | str
    tree_cid: str
    source_cid: str
    code_cid: str
    environment_binding_cid: str
    logical_name: str
    stack_ordinal: int
    handler_active: bool = False
    matching_exception_snapshot_cid: str | None = None
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = HANDLER_STATE_SCHEMA
    INTERFACE: ClassVar[str] = HANDLER_STATE_INTERFACE
    CID_FIELD: ClassVar[str] = "handler_state_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "handler_kind",
            "tree_cid",
            "source_cid",
            "code_cid",
            "environment_binding_cid",
            "logical_name",
            "stack_ordinal",
            "handler_active",
            "matching_exception_snapshot_cid",
            "unavailable_dimensions",
            "handler_state_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self, "handler_kind", _enum(self.handler_kind, HandlerKind, "handler_kind")
        )
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(self, "code_cid", _cid(self.code_cid, "code_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(self, "logical_name", _text(self.logical_name, "logical_name"))
        object.__setattr__(
            self, "stack_ordinal", _nonneg_int(self.stack_ordinal, "stack_ordinal")
        )
        object.__setattr__(
            self, "handler_active", _bool(self.handler_active, "handler_active")
        )
        object.__setattr__(
            self,
            "matching_exception_snapshot_cid",
            _optional_cid(
                self.matching_exception_snapshot_cid, "matching_exception_snapshot_cid"
            ),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        if self.handler_active and self.matching_exception_snapshot_cid is None:
            if "exception" not in self.unavailable_dimensions:
                raise ProgramExecutionError(
                    "active handlers preserve matching exception state or mark it unavailable"
                )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "handler_kind": self.handler_kind,
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "code_cid": self.code_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "logical_name": self.logical_name,
            "stack_ordinal": self.stack_ordinal,
            "handler_active": self.handler_active,
            "matching_exception_snapshot_cid": self.matching_exception_snapshot_cid,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def handler_state_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_execution_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["handler_state_cid"] = self.handler_state_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HandlerState":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class StackFrameState:
    """One ordered frame with exact code/environment and a bounded summary."""

    ordinal: int
    language: ProgramLanguage | str
    tree_cid: str
    source_cid: str
    code_cid: str
    environment_binding_cid: str
    logical_name: str
    line: int | None = None
    column: int | None = None
    state_summary: Mapping[str, Any] = field(default_factory=dict)
    exception_snapshot_cid: str | None = None
    handler_state_cid: str | None = None
    exception_active: bool = False
    handler_active: bool = False
    redacted_dimensions: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()
    completeness_claim: CompletenessClaim | str = CompletenessClaim.FULL_STATE
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL

    SCHEMA: ClassVar[str] = STACK_FRAME_STATE_SCHEMA
    INTERFACE: ClassVar[str] = STACK_FRAME_STATE_INTERFACE
    CID_FIELD: ClassVar[str] = "stack_frame_state_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "ordinal",
            "language",
            "tree_cid",
            "source_cid",
            "code_cid",
            "environment_binding_cid",
            "logical_name",
            "line",
            "column",
            "state_summary",
            "exception_snapshot_cid",
            "handler_state_cid",
            "exception_active",
            "handler_active",
            "redacted_dimensions",
            "unavailable_dimensions",
            "completeness_claim",
            "privacy_class",
            "stack_frame_state_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordinal", _nonneg_int(self.ordinal, "ordinal"))
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(self, "code_cid", _cid(self.code_cid, "code_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(self, "logical_name", _text(self.logical_name, "logical_name"))
        object.__setattr__(self, "line", _optional_nonneg_int(self.line, "line"))
        object.__setattr__(self, "column", _optional_nonneg_int(self.column, "column"))
        object.__setattr__(
            self, "state_summary", _mapping(self.state_summary, "state_summary")
        )
        object.__setattr__(
            self,
            "exception_snapshot_cid",
            _optional_cid(self.exception_snapshot_cid, "exception_snapshot_cid"),
        )
        object.__setattr__(
            self,
            "handler_state_cid",
            _optional_cid(self.handler_state_cid, "handler_state_cid"),
        )
        object.__setattr__(
            self, "exception_active", _bool(self.exception_active, "exception_active")
        )
        object.__setattr__(
            self, "handler_active", _bool(self.handler_active, "handler_active")
        )
        object.__setattr__(
            self,
            "redacted_dimensions",
            _unique_sorted_texts(self.redacted_dimensions, "redacted_dimension"),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        object.__setattr__(
            self,
            "completeness_claim",
            _enum(self.completeness_claim, CompletenessClaim, "completeness_claim"),
        )
        object.__setattr__(
            self, "privacy_class", _enum(self.privacy_class, PrivacyClass, "privacy_class")
        )
        _assert_completeness(
            completeness_claim=str(self.completeness_claim),
            redacted_dimensions=self.redacted_dimensions,
            unavailable_dimensions=self.unavailable_dimensions,
            name="StackFrameState",
        )
        if self.line is None and "source_location" not in self.unavailable_dimensions:
            raise ProgramExecutionError(
                "stack frames bind source location or mark source_location unavailable"
            )
        if self.exception_active and self.exception_snapshot_cid is None:
            if "exception" not in self.unavailable_dimensions:
                raise ProgramExecutionError(
                    "active exception state must be bound or marked unavailable"
                )
        if self.handler_active and self.handler_state_cid is None:
            if "handler" not in self.unavailable_dimensions:
                raise ProgramExecutionError(
                    "active handler state must be bound or marked unavailable"
                )
        overlap = set(self.redacted_dimensions) & set(self.state_summary)
        if overlap:
            raise ProgramExecutionError(
                "redacted dimensions cannot appear in state_summary"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "ordinal": self.ordinal,
            "language": self.language,
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "code_cid": self.code_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "logical_name": self.logical_name,
            "line": self.line,
            "column": self.column,
            "state_summary": _thaw_structured(self.state_summary),
            "exception_snapshot_cid": self.exception_snapshot_cid,
            "handler_state_cid": self.handler_state_cid,
            "exception_active": self.exception_active,
            "handler_active": self.handler_active,
            "redacted_dimensions": list(self.redacted_dimensions),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "completeness_claim": self.completeness_claim,
            "privacy_class": self.privacy_class,
        }

    @property
    def stack_frame_state_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_execution_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["stack_frame_state_cid"] = self.stack_frame_state_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
            StackFrameIdentity,
        )

        identity = StackFrameIdentity(
            ordinal=self.ordinal,
            language=self.language,
            code_cid=self.code_cid,
            environment_binding_cid=self.environment_binding_cid,
            state_summary=_thaw_structured(self.state_summary),
        )
        return identity.to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StackFrameState":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramExecutionState:
    """Bounded raw execution state under exact capture, tree, and environment."""

    language: ProgramLanguage | str
    capture_profile_cid: str
    tree_cid: str
    source_cid: str
    code_cid: str
    environment_binding_cid: str
    observed_state: Mapping[str, Any] = field(default_factory=dict)
    heap_summary: Mapping[str, Any] = field(default_factory=dict)
    heap_bound: HeapBound | str = HeapBound.BOUNDED_ABSTRACT
    stack_frame_cids: Sequence[str] = ()
    exception_snapshot_cid: str | None = None
    handler_state_cid: str | None = None
    redaction_profile_cid: str | None = None
    redacted_dimensions: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()
    observation_status: ObservationStatus | str = ObservationStatus.OBSERVED
    completeness_claim: CompletenessClaim | str = CompletenessClaim.FULL_STATE
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL
    includes_raw_bodies: bool = False

    SCHEMA: ClassVar[str] = PROGRAM_EXECUTION_STATE_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_EXECUTION_STATE_INTERFACE
    CID_FIELD: ClassVar[str] = "program_execution_state_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "capture_profile_cid",
            "tree_cid",
            "source_cid",
            "code_cid",
            "environment_binding_cid",
            "observed_state",
            "heap_summary",
            "heap_bound",
            "stack_frame_cids",
            "exception_snapshot_cid",
            "handler_state_cid",
            "redaction_profile_cid",
            "redacted_dimensions",
            "unavailable_dimensions",
            "observation_status",
            "completeness_claim",
            "privacy_class",
            "includes_raw_bodies",
            "program_execution_state_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self, "capture_profile_cid", _cid(self.capture_profile_cid, "capture_profile_cid")
        )
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(self, "code_cid", _cid(self.code_cid, "code_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self, "observed_state", _mapping(self.observed_state, "observed_state")
        )
        object.__setattr__(
            self, "heap_summary", _mapping(self.heap_summary, "heap_summary")
        )
        object.__setattr__(self, "heap_bound", _heap_bound(self.heap_bound))
        object.__setattr__(
            self, "stack_frame_cids", _ordered_cids(self.stack_frame_cids, "stack_frame_cid")
        )
        object.__setattr__(
            self,
            "exception_snapshot_cid",
            _optional_cid(self.exception_snapshot_cid, "exception_snapshot_cid"),
        )
        object.__setattr__(
            self,
            "handler_state_cid",
            _optional_cid(self.handler_state_cid, "handler_state_cid"),
        )
        object.__setattr__(
            self,
            "redaction_profile_cid",
            _optional_cid(self.redaction_profile_cid, "redaction_profile_cid"),
        )
        object.__setattr__(
            self,
            "redacted_dimensions",
            _unique_sorted_texts(self.redacted_dimensions, "redacted_dimension"),
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
        object.__setattr__(
            self, "privacy_class", _enum(self.privacy_class, PrivacyClass, "privacy_class")
        )
        object.__setattr__(
            self,
            "includes_raw_bodies",
            _bool(self.includes_raw_bodies, "includes_raw_bodies"),
        )
        _assert_public_raw_separation(
            privacy_class=str(self.privacy_class),
            includes_raw_bodies=self.includes_raw_bodies,
            name="ProgramExecutionState",
        )
        _assert_completeness(
            completeness_claim=str(self.completeness_claim),
            redacted_dimensions=self.redacted_dimensions,
            unavailable_dimensions=self.unavailable_dimensions,
            observation_status=str(self.observation_status),
            name="ProgramExecutionState",
        )
        if not self.stack_frame_cids and "call_stack" not in self.unavailable_dimensions:
            raise ProgramExecutionError(
                "execution state preserves call-stack order or marks call_stack unavailable"
            )
        if str(self.heap_bound) == HeapBound.UNAVAILABLE.value:
            if "heap" not in self.unavailable_dimensions:
                raise ProgramExecutionError(
                    "unavailable heaps must list heap in unavailable_dimensions"
                )
            if self.heap_summary:
                raise ProgramExecutionError("unavailable heaps cannot carry heap_summary")
        overlap = set(self.redacted_dimensions) & set(self.observed_state)
        if overlap:
            raise ProgramExecutionError(
                "redacted dimensions cannot appear in observed_state"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "capture_profile_cid": self.capture_profile_cid,
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "code_cid": self.code_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "observed_state": _thaw_structured(self.observed_state),
            "heap_summary": _thaw_structured(self.heap_summary),
            "heap_bound": self.heap_bound,
            "stack_frame_cids": list(self.stack_frame_cids),
            "exception_snapshot_cid": self.exception_snapshot_cid,
            "handler_state_cid": self.handler_state_cid,
            "redaction_profile_cid": self.redaction_profile_cid,
            "redacted_dimensions": list(self.redacted_dimensions),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "observation_status": self.observation_status,
            "completeness_claim": self.completeness_claim,
            "privacy_class": self.privacy_class,
            "includes_raw_bodies": self.includes_raw_bodies,
        }

    @property
    def program_execution_state_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_execution_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["program_execution_state_cid"] = self.program_execution_state_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
            RawExecutionStateIdentity,
        )

        identity = RawExecutionStateIdentity(
            language=self.language,
            capture_profile_cid=self.capture_profile_cid,
            observed_state=_thaw_structured(self.observed_state),
            stack_frame_cids=self.stack_frame_cids,
            unavailable_dimensions=self.unavailable_dimensions,
            observation_status=self.observation_status,
        )
        return identity.to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramExecutionState":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class AbstractProgramState:
    """Semantic abstraction bound to a raw state and abstraction profile."""

    language: ProgramLanguage | str
    raw_execution_state_cid: str
    abstraction_profile_cid: str
    tree_cid: str
    environment_binding_cid: str
    abstract_state: Mapping[str, Any] = field(default_factory=dict)
    stack_frame_cids: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()
    observation_status: ObservationStatus | str = ObservationStatus.OBSERVED
    completeness_claim: CompletenessClaim | str = CompletenessClaim.FULL_STATE

    SCHEMA: ClassVar[str] = ABSTRACT_PROGRAM_STATE_SCHEMA
    INTERFACE: ClassVar[str] = ABSTRACT_PROGRAM_STATE_INTERFACE
    CID_FIELD: ClassVar[str] = "abstract_program_state_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "raw_execution_state_cid",
            "abstraction_profile_cid",
            "tree_cid",
            "environment_binding_cid",
            "abstract_state",
            "stack_frame_cids",
            "unavailable_dimensions",
            "observation_status",
            "completeness_claim",
            "abstract_program_state_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self,
            "raw_execution_state_cid",
            _cid(self.raw_execution_state_cid, "raw_execution_state_cid"),
        )
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
        object.__setattr__(
            self, "abstract_state", _mapping(self.abstract_state, "abstract_state")
        )
        object.__setattr__(
            self, "stack_frame_cids", _ordered_cids(self.stack_frame_cids, "stack_frame_cid")
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
        _assert_completeness(
            completeness_claim=str(self.completeness_claim),
            redacted_dimensions=(),
            unavailable_dimensions=self.unavailable_dimensions,
            observation_status=str(self.observation_status),
            name="AbstractProgramState",
        )
        abstract_cid = program_execution_cid_for(self.identity_payload())
        if self.raw_execution_state_cid == abstract_cid:
            raise ProgramExecutionError("raw and abstract execution states must remain distinct")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "raw_execution_state_cid": self.raw_execution_state_cid,
            "abstraction_profile_cid": self.abstraction_profile_cid,
            "tree_cid": self.tree_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "abstract_state": _thaw_structured(self.abstract_state),
            "stack_frame_cids": list(self.stack_frame_cids),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "observation_status": self.observation_status,
            "completeness_claim": self.completeness_claim,
        }

    @property
    def abstract_program_state_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_execution_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["abstract_program_state_cid"] = self.abstract_program_state_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
            AbstractExecutionStateIdentity,
        )

        identity = AbstractExecutionStateIdentity(
            language=self.language,
            raw_execution_state_cid=self.raw_execution_state_cid,
            abstraction_profile_cid=self.abstraction_profile_cid,
            abstract_state=_thaw_structured(self.abstract_state),
            unavailable_dimensions=self.unavailable_dimensions,
            observation_status=self.observation_status,
        )
        return identity.to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AbstractProgramState":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramEvent:
    """Closed event-grammar record bound to exact code and environment."""

    event_kind: EventKind | str
    event_origin: EventOrigin | str
    observation_status: ObservationStatus | str
    language: ProgramLanguage | str
    tree_cid: str
    source_cid: str
    code_cid: str
    environment_binding_cid: str
    subject_cid: str
    logical_name: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    line: int | None = None
    column: int | None = None
    predecessor_event_cid: str | None = None
    stack_frame_cids: Sequence[str] = ()
    exception_snapshot_cid: str | None = None
    handler_state_cid: str | None = None
    redaction_profile_cid: str | None = None
    redacted_dimensions: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()
    completeness_claim: CompletenessClaim | str = CompletenessClaim.FULL_STATE
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL

    SCHEMA: ClassVar[str] = PROGRAM_EVENT_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_EVENT_INTERFACE
    CID_FIELD: ClassVar[str] = "program_event_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "event_kind",
            "event_origin",
            "observation_status",
            "language",
            "tree_cid",
            "source_cid",
            "code_cid",
            "environment_binding_cid",
            "subject_cid",
            "logical_name",
            "payload",
            "line",
            "column",
            "predecessor_event_cid",
            "stack_frame_cids",
            "exception_snapshot_cid",
            "handler_state_cid",
            "redaction_profile_cid",
            "redacted_dimensions",
            "unavailable_dimensions",
            "completeness_claim",
            "privacy_class",
            "program_event_cid",
        }
    )

    def __post_init__(self) -> None:
        kind = _enum(self.event_kind, EventKind, "event_kind")
        origin = _enum(self.event_origin, EventOrigin, "event_origin")
        status = _enum(self.observation_status, ObservationStatus, "observation_status")
        object.__setattr__(self, "event_kind", kind)
        object.__setattr__(self, "event_origin", origin)
        object.__setattr__(self, "observation_status", status)
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(self, "code_cid", _cid(self.code_cid, "code_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(self, "logical_name", _text(self.logical_name, "logical_name"))
        object.__setattr__(self, "payload", _mapping(self.payload, "payload"))
        object.__setattr__(self, "line", _optional_nonneg_int(self.line, "line"))
        object.__setattr__(self, "column", _optional_nonneg_int(self.column, "column"))
        object.__setattr__(
            self,
            "predecessor_event_cid",
            _optional_cid(self.predecessor_event_cid, "predecessor_event_cid"),
        )
        object.__setattr__(
            self, "stack_frame_cids", _ordered_cids(self.stack_frame_cids, "stack_frame_cid")
        )
        object.__setattr__(
            self,
            "exception_snapshot_cid",
            _optional_cid(self.exception_snapshot_cid, "exception_snapshot_cid"),
        )
        object.__setattr__(
            self,
            "handler_state_cid",
            _optional_cid(self.handler_state_cid, "handler_state_cid"),
        )
        object.__setattr__(
            self,
            "redaction_profile_cid",
            _optional_cid(self.redaction_profile_cid, "redaction_profile_cid"),
        )
        object.__setattr__(
            self,
            "redacted_dimensions",
            _unique_sorted_texts(self.redacted_dimensions, "redacted_dimension"),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        object.__setattr__(
            self,
            "completeness_claim",
            _enum(self.completeness_claim, CompletenessClaim, "completeness_claim"),
        )
        object.__setattr__(
            self, "privacy_class", _enum(self.privacy_class, PrivacyClass, "privacy_class")
        )
        if origin in NON_OBSERVATION_ORIGINS and status == ObservationStatus.OBSERVED.value:
            raise ProgramExecutionError(
                "predicted/simulated events cannot decode as observations"
            )
        _assert_completeness(
            completeness_claim=str(self.completeness_claim),
            redacted_dimensions=self.redacted_dimensions,
            unavailable_dimensions=self.unavailable_dimensions,
            observation_status=status,
            event_origin=origin,
            name="ProgramEvent",
        )
        if kind in STACK_REQUIRED_EVENT_KINDS and not self.stack_frame_cids:
            if "call_stack" not in self.unavailable_dimensions:
                raise ProgramExecutionError(
                    "call/return/exception/handler events preserve call-stack order"
                )
        if kind == EventKind.RAISE.value and self.exception_snapshot_cid is None:
            if "exception" not in self.unavailable_dimensions:
                raise ProgramExecutionError(
                    "raise events bind an exception snapshot or mark exception unavailable"
                )
        if kind in {EventKind.CATCH.value, EventKind.HANDLER.value}:
            if self.handler_state_cid is None and "handler" not in self.unavailable_dimensions:
                raise ProgramExecutionError(
                    "catch/handler events bind handler state or mark handler unavailable"
                )
        if origin == EventOrigin.OBSERVED.value and status == ObservationStatus.OBSERVED.value:
            if kind == EventKind.UNAVAILABLE.value:
                raise ProgramExecutionError(
                    "unavailable event kinds cannot be observed"
                )
        if self.predecessor_event_cid is not None:
            if self.predecessor_event_cid == program_execution_cid_for(self.identity_payload()):
                raise ProgramExecutionError("events cannot be their own predecessor")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "event_kind": self.event_kind,
            "event_origin": self.event_origin,
            "observation_status": self.observation_status,
            "language": self.language,
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "code_cid": self.code_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "subject_cid": self.subject_cid,
            "logical_name": self.logical_name,
            "payload": _thaw_structured(self.payload),
            "line": self.line,
            "column": self.column,
            "predecessor_event_cid": self.predecessor_event_cid,
            "stack_frame_cids": list(self.stack_frame_cids),
            "exception_snapshot_cid": self.exception_snapshot_cid,
            "handler_state_cid": self.handler_state_cid,
            "redaction_profile_cid": self.redaction_profile_cid,
            "redacted_dimensions": list(self.redacted_dimensions),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "completeness_claim": self.completeness_claim,
            "privacy_class": self.privacy_class,
        }

    @property
    def program_event_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    @property
    def observation_admissible(self) -> bool:
        return (
            str(self.event_origin) == EventOrigin.OBSERVED.value
            and str(self.observation_status) == ObservationStatus.OBSERVED.value
        )

    def canonical_bytes(self) -> bytes:
        return canonical_program_execution_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["program_event_cid"] = self.program_event_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
            ProgramEventIdentity,
        )

        identity = ProgramEventIdentity(
            event_kind=IDENTITY_EVENT_KIND[str(self.event_kind)],
            observation_status=self.observation_status,
            subject_cid=self.subject_cid,
            payload=_thaw_structured(self.payload),
            predecessor_event_cid=self.predecessor_event_cid,
        )
        return identity.to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramEvent":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ExecutionObservation:
    """Admitted observation; predicted and simulated events cannot inhabit this type."""

    event_cid: str
    event_kind: EventKind | str
    language: ProgramLanguage | str
    tree_cid: str
    source_cid: str
    code_cid: str
    environment_binding_cid: str
    subject_cid: str
    event_origin: EventOrigin | str = EventOrigin.OBSERVED
    observation_status: ObservationStatus | str = ObservationStatus.OBSERVED
    payload: Mapping[str, Any] = field(default_factory=dict)
    predecessor_event_cid: str | None = None
    stack_frame_cids: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = EXECUTION_OBSERVATION_SCHEMA
    INTERFACE: ClassVar[str] = EXECUTION_OBSERVATION_INTERFACE
    CID_FIELD: ClassVar[str] = "execution_observation_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "event_cid",
            "event_kind",
            "event_origin",
            "observation_status",
            "language",
            "tree_cid",
            "source_cid",
            "code_cid",
            "environment_binding_cid",
            "subject_cid",
            "payload",
            "predecessor_event_cid",
            "stack_frame_cids",
            "unavailable_dimensions",
            "execution_observation_cid",
        }
    )

    def __post_init__(self) -> None:
        origin = _enum(self.event_origin, EventOrigin, "event_origin")
        status = _enum(self.observation_status, ObservationStatus, "observation_status")
        if origin != EventOrigin.OBSERVED.value or status != ObservationStatus.OBSERVED.value:
            raise ProgramExecutionError(
                "predicted/simulated events cannot decode as observations"
            )
        object.__setattr__(self, "event_cid", _cid(self.event_cid, "event_cid"))
        object.__setattr__(self, "event_kind", _enum(self.event_kind, EventKind, "event_kind"))
        object.__setattr__(self, "event_origin", origin)
        object.__setattr__(self, "observation_status", status)
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(self, "code_cid", _cid(self.code_cid, "code_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(self, "payload", _mapping(self.payload, "payload"))
        object.__setattr__(
            self,
            "predecessor_event_cid",
            _optional_cid(self.predecessor_event_cid, "predecessor_event_cid"),
        )
        object.__setattr__(
            self, "stack_frame_cids", _ordered_cids(self.stack_frame_cids, "stack_frame_cid")
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        if str(self.event_kind) == EventKind.UNAVAILABLE.value:
            raise ProgramExecutionError(
                "unavailable event kinds cannot decode as observations"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "event_cid": self.event_cid,
            "event_kind": self.event_kind,
            "event_origin": EventOrigin.OBSERVED.value,
            "observation_status": ObservationStatus.OBSERVED.value,
            "language": self.language,
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "code_cid": self.code_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "subject_cid": self.subject_cid,
            "payload": _thaw_structured(self.payload),
            "predecessor_event_cid": self.predecessor_event_cid,
            "stack_frame_cids": list(self.stack_frame_cids),
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def execution_observation_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_execution_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["execution_observation_cid"] = self.execution_observation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionObservation":
        return _from_closed(cls, data)

    @classmethod
    def from_event(cls, event: ProgramEvent) -> "ExecutionObservation":
        if not isinstance(event, ProgramEvent):
            raise ProgramExecutionError("observation requires a ProgramEvent")
        if not event.observation_admissible:
            raise ProgramExecutionError(
                "predicted/simulated events cannot decode as observations"
            )
        return cls(
            event_cid=event.program_event_cid,
            event_kind=event.event_kind,
            language=event.language,
            tree_cid=event.tree_cid,
            source_cid=event.source_cid,
            code_cid=event.code_cid,
            environment_binding_cid=event.environment_binding_cid,
            subject_cid=event.subject_cid,
            payload=_thaw_structured(event.payload),
            predecessor_event_cid=event.predecessor_event_cid,
            stack_frame_cids=event.stack_frame_cids,
            unavailable_dimensions=event.unavailable_dimensions,
        )


@dataclass(frozen=True, slots=True)
class ExecutionTraceSegment:
    """Ordered event subsequence with explicit parent-trace identity."""

    language: ProgramLanguage | str
    tree_cid: str
    environment_binding_cid: str
    parent_trace_cid: str
    start_event_cid: str
    end_event_cid: str
    event_cids: Sequence[str]
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = EXECUTION_TRACE_SEGMENT_SCHEMA
    INTERFACE: ClassVar[str] = EXECUTION_TRACE_SEGMENT_INTERFACE
    CID_FIELD: ClassVar[str] = "execution_trace_segment_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "tree_cid",
            "environment_binding_cid",
            "parent_trace_cid",
            "start_event_cid",
            "end_event_cid",
            "event_cids",
            "unavailable_dimensions",
            "execution_trace_segment_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self, "parent_trace_cid", _cid(self.parent_trace_cid, "parent_trace_cid")
        )
        object.__setattr__(
            self, "start_event_cid", _cid(self.start_event_cid, "start_event_cid")
        )
        object.__setattr__(self, "end_event_cid", _cid(self.end_event_cid, "end_event_cid"))
        object.__setattr__(
            self, "event_cids", _ordered_cids(self.event_cids, "event_cid")
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        if not self.event_cids:
            raise ProgramExecutionError("trace segments require at least one event")
        if self.event_cids[0] != self.start_event_cid:
            raise ProgramExecutionError("segment start_event_cid must be the first event")
        if self.event_cids[-1] != self.end_event_cid:
            raise ProgramExecutionError("segment end_event_cid must be the last event")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "tree_cid": self.tree_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "parent_trace_cid": self.parent_trace_cid,
            "start_event_cid": self.start_event_cid,
            "end_event_cid": self.end_event_cid,
            "event_cids": list(self.event_cids),
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def execution_trace_segment_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_execution_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["execution_trace_segment_cid"] = self.execution_trace_segment_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionTraceSegment":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ExecutionTrace:
    """Ordered event/segment identity; repeated states do not erase history."""

    language: ProgramLanguage | str
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    event_cids: Sequence[str]
    segment_cids: Sequence[str] = ()
    raw_execution_state_cids: Sequence[str] = ()
    parent_trace_cid: str | None = None
    redaction_profile_cid: str | None = None
    redacted_dimensions: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()
    completeness_claim: CompletenessClaim | str = CompletenessClaim.FULL_STATE
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL
    includes_raw_bodies: bool = False

    SCHEMA: ClassVar[str] = EXECUTION_TRACE_SCHEMA
    INTERFACE: ClassVar[str] = EXECUTION_TRACE_INTERFACE
    CID_FIELD: ClassVar[str] = "execution_trace_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "tree_cid",
            "source_cid",
            "environment_binding_cid",
            "event_cids",
            "segment_cids",
            "raw_execution_state_cids",
            "parent_trace_cid",
            "redaction_profile_cid",
            "redacted_dimensions",
            "unavailable_dimensions",
            "completeness_claim",
            "privacy_class",
            "includes_raw_bodies",
            "execution_trace_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self, "event_cids", _ordered_cids(self.event_cids, "event_cid")
        )
        object.__setattr__(
            self, "segment_cids", _ordered_cids(self.segment_cids, "segment_cid")
        )
        object.__setattr__(
            self,
            "raw_execution_state_cids",
            _ordered_cids(self.raw_execution_state_cids, "raw_execution_state_cid"),
        )
        object.__setattr__(
            self,
            "parent_trace_cid",
            _optional_cid(self.parent_trace_cid, "parent_trace_cid"),
        )
        object.__setattr__(
            self,
            "redaction_profile_cid",
            _optional_cid(self.redaction_profile_cid, "redaction_profile_cid"),
        )
        object.__setattr__(
            self,
            "redacted_dimensions",
            _unique_sorted_texts(self.redacted_dimensions, "redacted_dimension"),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        object.__setattr__(
            self,
            "completeness_claim",
            _enum(self.completeness_claim, CompletenessClaim, "completeness_claim"),
        )
        object.__setattr__(
            self, "privacy_class", _enum(self.privacy_class, PrivacyClass, "privacy_class")
        )
        object.__setattr__(
            self,
            "includes_raw_bodies",
            _bool(self.includes_raw_bodies, "includes_raw_bodies"),
        )
        if not self.event_cids:
            raise ProgramExecutionError("execution trace requires at least one event")
        _assert_public_raw_separation(
            privacy_class=str(self.privacy_class),
            includes_raw_bodies=self.includes_raw_bodies,
            name="ExecutionTrace",
        )
        _assert_completeness(
            completeness_claim=str(self.completeness_claim),
            redacted_dimensions=self.redacted_dimensions,
            unavailable_dimensions=self.unavailable_dimensions,
            name="ExecutionTrace",
        )
        own_cid = program_execution_cid_for(self.identity_payload())
        if self.parent_trace_cid == own_cid:
            raise ProgramExecutionError("execution traces cannot be their own parent")
        if self.parent_trace_cid is not None and self.parent_trace_cid in self.event_cids:
            raise ProgramExecutionError(
                "parent_trace_cid cannot appear in event_cids; physical DAG remains acyclic"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "event_cids": list(self.event_cids),
            "segment_cids": list(self.segment_cids),
            "raw_execution_state_cids": list(self.raw_execution_state_cids),
            "parent_trace_cid": self.parent_trace_cid,
            "redaction_profile_cid": self.redaction_profile_cid,
            "redacted_dimensions": list(self.redacted_dimensions),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "completeness_claim": self.completeness_claim,
            "privacy_class": self.privacy_class,
            "includes_raw_bodies": self.includes_raw_bodies,
        }

    @property
    def execution_trace_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_execution_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["execution_trace_cid"] = self.execution_trace_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
            ExecutionTraceIdentity,
        )

        identity = ExecutionTraceIdentity(
            event_cids=self.event_cids,
            segment_cids=self.segment_cids,
            raw_execution_state_cids=self.raw_execution_state_cids,
        )
        return identity.to_dict()

    def public_view(self) -> "ExecutionTrace":
        """Return a public trace identity that never includes raw bodies."""

        redacted = set(self.redacted_dimensions)
        claim = str(self.completeness_claim)
        if (
            self.includes_raw_bodies
            or self.raw_execution_state_cids
            or str(self.privacy_class) not in PUBLIC_PRIVACY_CLASSES
        ):
            redacted.add("raw_body")
            claim = CompletenessClaim.REDACTED.value
        if claim == CompletenessClaim.FULL_STATE.value and redacted:
            claim = CompletenessClaim.REDACTED.value
        return ExecutionTrace(
            language=self.language,
            tree_cid=self.tree_cid,
            source_cid=self.source_cid,
            environment_binding_cid=self.environment_binding_cid,
            event_cids=self.event_cids,
            segment_cids=self.segment_cids,
            raw_execution_state_cids=(),
            parent_trace_cid=self.parent_trace_cid,
            redaction_profile_cid=self.redaction_profile_cid,
            redacted_dimensions=tuple(sorted(redacted)),
            unavailable_dimensions=self.unavailable_dimensions,
            completeness_claim=claim,
            privacy_class=PrivacyClass.PUBLIC,
            includes_raw_bodies=False,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionTrace":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class StateAbstractionReceipt:
    """Receipt that a raw state was abstracted under a versioned profile."""

    language: ProgramLanguage | str
    raw_execution_state_cid: str
    abstract_program_state_cid: str
    abstraction_profile_cid: str
    soundness_claim: AbstractionSoundnessClaim | str = AbstractionSoundnessClaim.UNKNOWN
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = STATE_ABSTRACTION_RECEIPT_SCHEMA
    INTERFACE: ClassVar[str] = STATE_ABSTRACTION_RECEIPT_INTERFACE
    CID_FIELD: ClassVar[str] = "state_abstraction_receipt_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "raw_execution_state_cid",
            "abstract_program_state_cid",
            "abstraction_profile_cid",
            "soundness_claim",
            "unavailable_dimensions",
            "state_abstraction_receipt_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
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
            "abstraction_profile_cid",
            _cid(self.abstraction_profile_cid, "abstraction_profile_cid"),
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
        if self.raw_execution_state_cid == self.abstract_program_state_cid:
            raise ProgramExecutionError("raw and abstract execution states must remain distinct")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "raw_execution_state_cid": self.raw_execution_state_cid,
            "abstract_program_state_cid": self.abstract_program_state_cid,
            "abstraction_profile_cid": self.abstraction_profile_cid,
            "soundness_claim": self.soundness_claim,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def state_abstraction_receipt_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_program_execution_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["state_abstraction_receipt_cid"] = self.state_abstraction_receipt_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateAbstractionReceipt":
        return _from_closed(cls, data)


PROGRAM_EXECUTION_RECORD_TYPES: Final[tuple[type, ...]] = (
    RedactionProfile,
    ExceptionSnapshot,
    HandlerState,
    StackFrameState,
    ProgramExecutionState,
    AbstractProgramState,
    ProgramEvent,
    ExecutionObservation,
    ExecutionTraceSegment,
    ExecutionTrace,
    StateAbstractionReceipt,
)

_SCHEMA_TO_CLASS: Final[dict[str, type]] = {
    cls.SCHEMA: cls for cls in PROGRAM_EXECUTION_RECORD_TYPES
}


def decode_program_execution_record(data: Mapping[str, Any]) -> Any:
    """Dispatch one closed program-execution payload to its versioned record type."""

    if not isinstance(data, Mapping):
        raise ProgramExecutionError("program-execution record must be a mapping")
    schema = data.get("schema")
    record_type = _SCHEMA_TO_CLASS.get(schema) if type(schema) is str else None
    if record_type is None:
        raise ProgramExecutionError(f"unsupported program-execution schema {schema!r}")
    return record_type.from_dict(data)


def decode_execution_observation(data: Mapping[str, Any] | ProgramEvent) -> ExecutionObservation:
    """Decode an observation; predicted/simulated events fail closed."""

    if isinstance(data, ProgramEvent):
        return ExecutionObservation.from_event(data)
    if isinstance(data, ExecutionObservation):
        return data
    if not isinstance(data, Mapping):
        raise ProgramExecutionError("execution observation must be a mapping or ProgramEvent")
    schema = data.get("schema")
    if schema == EXECUTION_OBSERVATION_SCHEMA:
        return ExecutionObservation.from_dict(data)
    if schema == PROGRAM_EVENT_SCHEMA:
        event = ProgramEvent.from_dict(data)
        return ExecutionObservation.from_event(event)
    raise ProgramExecutionError(
        "predicted/simulated events cannot decode as observations"
    )


def observe_program_event(event: ProgramEvent) -> ExecutionObservation:
    """Admit an observed event; predicted/simulated events fail closed."""

    return ExecutionObservation.from_event(event)


def load_payload_schema() -> dict[str, Any]:
    """Load the packaged JSON Schema for program-execution payloads."""

    from pathlib import Path

    path = (
        Path(__file__).resolve().parent / "schemas" / "program-execution.payload.schema.json"
    )
    return loads_program_execution_json(path.read_text(encoding="utf-8"))


def _record_cid(record: Any) -> str:
    return getattr(record, record.CID_FIELD)


def _index_records(records: Sequence[Any], expected_type: type, name: str) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for item in records:
        if not isinstance(item, expected_type):
            raise ProgramExecutionError(f"{name} must contain {expected_type.__name__} values")
        cid = _record_cid(item)
        if cid in indexed:
            raise ProgramExecutionError(f"{name} identities must be unique")
        indexed[cid] = item
    return indexed


def _assert_contiguous_stack(frames: Sequence[StackFrameState]) -> None:
    ordinals = [frame.ordinal for frame in frames]
    expected = list(range(len(frames)))
    if ordinals != expected:
        raise ProgramExecutionError(
            "call-stack ordinals must be contiguous from 0 (innermost) without reordering"
        )


def assemble_program_execution_state(
    *,
    language: ProgramLanguage | str = ProgramLanguage.PYTHON,
    capture_profile_cid: str,
    tree_cid: str,
    source_cid: str,
    environment_binding_cid: str,
    frames: Sequence[StackFrameState] = (),
    observed_state: Mapping[str, Any] | None = None,
    heap_summary: Mapping[str, Any] | None = None,
    heap_bound: HeapBound | str = HeapBound.BOUNDED_ABSTRACT,
    exception: ExceptionSnapshot | None = None,
    handler: HandlerState | None = None,
    redaction: RedactionProfile | None = None,
    observation_status: ObservationStatus | str = ObservationStatus.OBSERVED,
    completeness_claim: CompletenessClaim | str | None = None,
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL,
    includes_raw_bodies: bool = False,
    unavailable_dimensions: Sequence[str] = (),
    code_cid: str | None = None,
) -> ProgramExecutionState:
    """Assemble a raw execution state from ordered frames and bound exception/handler state."""

    language_value = _language(language)
    frame_list = tuple(frames)
    _assert_contiguous_stack(frame_list)
    for frame in frame_list:
        if str(frame.language) != language_value:
            raise ProgramExecutionError("stack frames must share the execution language")
        if frame.tree_cid != _cid(tree_cid, "tree_cid"):
            raise ProgramExecutionError("stack frames must bind the same tree_cid")
        if frame.source_cid != _cid(source_cid, "source_cid"):
            raise ProgramExecutionError("stack frames must bind the same source_cid")
        if frame.environment_binding_cid != _cid(
            environment_binding_cid, "environment_binding_cid"
        ):
            raise ProgramExecutionError(
                "stack frames must bind the same environment_binding_cid"
            )
    current_code = (
        frame_list[0].code_cid
        if frame_list
        else _cid(code_cid, "code_cid") if code_cid is not None else None
    )
    if current_code is None:
        raise ProgramExecutionError("execution state requires current code_cid")
    if code_cid is not None and _cid(code_cid, "code_cid") != current_code:
        raise ProgramExecutionError("code_cid must match the innermost stack frame")
    redacted = () if redaction is None else redaction.redacted_dimensions
    unavailable = list(unavailable_dimensions)
    if not frame_list and "call_stack" not in unavailable:
        unavailable.append("call_stack")
    claim = completeness_claim
    if claim is None:
        if redaction is not None:
            claim = redaction.completeness_claim
        elif unavailable or redacted:
            claim = CompletenessClaim.PARTIAL
        else:
            claim = CompletenessClaim.FULL_STATE
    if exception is not None:
        if exception.tree_cid != _cid(tree_cid, "tree_cid"):
            raise ProgramExecutionError("exception snapshot must bind the same tree_cid")
        if exception.source_cid != _cid(source_cid, "source_cid"):
            raise ProgramExecutionError("exception snapshot must bind the same source_cid")
        if exception.environment_binding_cid != _cid(
            environment_binding_cid, "environment_binding_cid"
        ):
            raise ProgramExecutionError(
                "exception snapshot must bind the same environment_binding_cid"
            )
    if handler is not None:
        if handler.tree_cid != _cid(tree_cid, "tree_cid"):
            raise ProgramExecutionError("handler state must bind the same tree_cid")
        if handler.source_cid != _cid(source_cid, "source_cid"):
            raise ProgramExecutionError("handler state must bind the same source_cid")
        if handler.environment_binding_cid != _cid(
            environment_binding_cid, "environment_binding_cid"
        ):
            raise ProgramExecutionError(
                "handler state must bind the same environment_binding_cid"
            )
    return ProgramExecutionState(
        language=language_value,
        capture_profile_cid=capture_profile_cid,
        tree_cid=tree_cid,
        source_cid=source_cid,
        code_cid=current_code,
        environment_binding_cid=environment_binding_cid,
        observed_state={} if observed_state is None else observed_state,
        heap_summary={} if heap_summary is None else heap_summary,
        heap_bound=heap_bound,
        stack_frame_cids=tuple(frame.stack_frame_state_cid for frame in frame_list),
        exception_snapshot_cid=None if exception is None else exception.exception_snapshot_cid,
        handler_state_cid=None if handler is None else handler.handler_state_cid,
        redaction_profile_cid=None if redaction is None else redaction.redaction_profile_cid,
        redacted_dimensions=redacted,
        unavailable_dimensions=unavailable,
        observation_status=observation_status,
        completeness_claim=claim,
        privacy_class=privacy_class,
        includes_raw_bodies=includes_raw_bodies,
    )


def public_execution_view(state: ProgramExecutionState) -> ProgramExecutionState:
    """Project a public state that never carries raw bodies or full private state."""

    if not isinstance(state, ProgramExecutionState):
        raise ProgramExecutionError("public view requires a ProgramExecutionState")
    redacted = set(state.redacted_dimensions)
    observed = _thaw_structured(state.observed_state)
    heap = _thaw_structured(state.heap_summary)
    heap_bound = state.heap_bound
    unavailable = set(state.unavailable_dimensions)
    claim = str(state.completeness_claim)
    observation_status = state.observation_status
    if state.includes_raw_bodies or str(state.privacy_class) not in PUBLIC_PRIVACY_CLASSES:
        redacted.update({"raw_body", "observed_state", "heap"})
        observed = {}
        heap = {}
        heap_bound = HeapBound.UNAVAILABLE
        unavailable.add("heap")
        claim = CompletenessClaim.REDACTED.value
        observation_status = ObservationStatus.REDACTED
    if claim == CompletenessClaim.FULL_STATE.value and redacted:
        claim = CompletenessClaim.REDACTED.value
        observation_status = ObservationStatus.REDACTED
    return ProgramExecutionState(
        language=state.language,
        capture_profile_cid=state.capture_profile_cid,
        tree_cid=state.tree_cid,
        source_cid=state.source_cid,
        code_cid=state.code_cid,
        environment_binding_cid=state.environment_binding_cid,
        observed_state=observed,
        heap_summary=heap,
        heap_bound=heap_bound,
        stack_frame_cids=state.stack_frame_cids,
        exception_snapshot_cid=state.exception_snapshot_cid,
        handler_state_cid=state.handler_state_cid,
        redaction_profile_cid=state.redaction_profile_cid,
        redacted_dimensions=tuple(sorted(redacted)),
        unavailable_dimensions=tuple(sorted(unavailable)),
        observation_status=observation_status,
        completeness_claim=claim,
        privacy_class=PrivacyClass.PUBLIC,
        includes_raw_bodies=False,
    )


def assemble_execution_trace(
    *,
    language: ProgramLanguage | str = ProgramLanguage.PYTHON,
    tree_cid: str,
    source_cid: str,
    environment_binding_cid: str,
    events: Sequence[ProgramEvent],
    states: Sequence[ProgramExecutionState] = (),
    segments: Sequence[ExecutionTraceSegment] = (),
    parent_trace_cid: str | None = None,
    redaction: RedactionProfile | None = None,
    completeness_claim: CompletenessClaim | str | None = None,
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL,
    includes_raw_bodies: bool = False,
    unavailable_dimensions: Sequence[str] = (),
) -> ExecutionTrace:
    """Assemble an ordered trace; repeats are preserved and parent identity is explicit.

    Segments may cite a parent trace by CID, but a trace cannot include a segment
    that cites that same trace CID: physical IPLD blocks remain acyclic.
    """

    language_value = _language(language)
    event_list = tuple(events)
    if not event_list:
        raise ProgramExecutionError("execution trace requires at least one event")
    tree = _cid(tree_cid, "tree_cid")
    source = _cid(source_cid, "source_cid")
    env = _cid(environment_binding_cid, "environment_binding_cid")
    predecessors: set[str] = set()
    previous: str | None = None
    for event in event_list:
        if not isinstance(event, ProgramEvent):
            raise ProgramExecutionError("trace events must be ProgramEvent values")
        if str(event.language) != language_value:
            raise ProgramExecutionError("trace events must share the execution language")
        if (
            event.tree_cid != tree
            or event.source_cid != source
            or event.environment_binding_cid != env
        ):
            raise ProgramExecutionError(
                "trace events must bind the same tree, source, and environment"
            )
        if event.predecessor_event_cid is not None:
            if event.predecessor_event_cid not in predecessors and previous is not None:
                if event.predecessor_event_cid != previous:
                    raise ProgramExecutionError(
                        "event predecessor chain must follow recorded order"
                    )
            if event.predecessor_event_cid == event.program_event_cid:
                raise ProgramExecutionError("events cannot be their own predecessor")
        predecessors.add(event.program_event_cid)
        previous = event.program_event_cid
    event_cids = tuple(event.program_event_cid for event in event_list)
    event_cid_set = set(event_cids)
    for state in states:
        if not isinstance(state, ProgramExecutionState):
            raise ProgramExecutionError("trace states must be ProgramExecutionState values")
        if (
            state.tree_cid != tree
            or state.source_cid != source
            or state.environment_binding_cid != env
        ):
            raise ProgramExecutionError(
                "trace states must bind the same tree, source, and environment"
            )
    for segment in segments:
        if not isinstance(segment, ExecutionTraceSegment):
            raise ProgramExecutionError("trace segments must be ExecutionTraceSegment values")
        if segment.tree_cid != tree or segment.environment_binding_cid != env:
            raise ProgramExecutionError(
                "trace segments must bind the same tree and environment"
            )
        extra = [cid for cid in segment.event_cids if cid not in event_cid_set]
        if extra:
            raise ProgramExecutionError("trace segments must stay within the trace event order")
    redacted = () if redaction is None else redaction.redacted_dimensions
    claim = completeness_claim
    if claim is None:
        if redaction is not None:
            claim = redaction.completeness_claim
        elif unavailable_dimensions or redacted:
            claim = CompletenessClaim.PARTIAL
        else:
            claim = CompletenessClaim.FULL_STATE
    return ExecutionTrace(
        language=language_value,
        tree_cid=tree_cid,
        source_cid=source_cid,
        environment_binding_cid=environment_binding_cid,
        event_cids=event_cids,
        segment_cids=tuple(segment.execution_trace_segment_cid for segment in segments),
        raw_execution_state_cids=tuple(
            state.program_execution_state_cid for state in states
        ),
        parent_trace_cid=parent_trace_cid,
        redaction_profile_cid=None if redaction is None else redaction.redaction_profile_cid,
        redacted_dimensions=redacted,
        unavailable_dimensions=unavailable_dimensions,
        completeness_claim=claim,
        privacy_class=privacy_class,
        includes_raw_bodies=includes_raw_bodies,
    )


def bind_abstraction_receipt(
    raw: ProgramExecutionState,
    abstract: AbstractProgramState,
    *,
    soundness_claim: AbstractionSoundnessClaim | str = AbstractionSoundnessClaim.UNKNOWN,
) -> StateAbstractionReceipt:
    """Bind a raw/abstract pair; identities remain distinct and profile-scoped."""

    if not isinstance(raw, ProgramExecutionState):
        raise ProgramExecutionError("receipt requires a ProgramExecutionState")
    if not isinstance(abstract, AbstractProgramState):
        raise ProgramExecutionError("receipt requires an AbstractProgramState")
    if abstract.raw_execution_state_cid != raw.program_execution_state_cid:
        raise ProgramExecutionError("abstract state is not bound to the supplied raw state")
    if raw.program_execution_state_cid == abstract.abstract_program_state_cid:
        raise ProgramExecutionError("raw and abstract execution states must remain distinct")
    return StateAbstractionReceipt(
        language=raw.language,
        raw_execution_state_cid=raw.program_execution_state_cid,
        abstract_program_state_cid=abstract.abstract_program_state_cid,
        abstraction_profile_cid=abstract.abstraction_profile_cid,
        soundness_claim=soundness_claim,
        unavailable_dimensions=tuple(
            sorted(set(raw.unavailable_dimensions) | set(abstract.unavailable_dimensions))
        ),
    )


__all__ = [
    "ABSTRACT_PROGRAM_STATE_INTERFACE",
    "ABSTRACT_PROGRAM_STATE_SCHEMA",
    "ADMITTED_LANGUAGES",
    "COLLECTION_SEMANTICS_DECLARATION",
    "EXCEPTION_SNAPSHOT_INTERFACE",
    "EXCEPTION_SNAPSHOT_SCHEMA",
    "EXECUTION_OBSERVATION_INTERFACE",
    "EXECUTION_OBSERVATION_SCHEMA",
    "EXECUTION_TRACE_INTERFACE",
    "EXECUTION_TRACE_SCHEMA",
    "EXECUTION_TRACE_SEGMENT_INTERFACE",
    "EXECUTION_TRACE_SEGMENT_SCHEMA",
    "HANDLER_STATE_INTERFACE",
    "HANDLER_STATE_SCHEMA",
    "PROGRAM_EVENT_INTERFACE",
    "PROGRAM_EVENT_SCHEMA",
    "PROGRAM_EXECUTION_STATE_INTERFACE",
    "PROGRAM_EXECUTION_STATE_SCHEMA",
    "REDACTION_PROFILE_INTERFACE",
    "REDACTION_PROFILE_SCHEMA",
    "REQUIRED_EVENT_KINDS",
    "STACK_FRAME_STATE_INTERFACE",
    "STACK_FRAME_STATE_SCHEMA",
    "STATE_ABSTRACTION_RECEIPT_INTERFACE",
    "STATE_ABSTRACTION_RECEIPT_SCHEMA",
    "UNAVAILABLE_LANGUAGES",
    "AbstractProgramState",
    "AbstractionSoundnessClaim",
    "CompletenessClaim",
    "EventKind",
    "EventOrigin",
    "ExceptionSnapshot",
    "ExecutionObservation",
    "ExecutionTrace",
    "ExecutionTraceSegment",
    "HandlerKind",
    "HandlerState",
    "HeapBound",
    "ObservationStatus",
    "PrivacyClass",
    "ProgramEvent",
    "ProgramExecutionError",
    "ProgramExecutionState",
    "ProgramLanguage",
    "RedactionProfile",
    "StackFrameState",
    "StateAbstractionReceipt",
    "assemble_execution_trace",
    "assemble_program_execution_state",
    "bind_abstraction_receipt",
    "canonical_program_execution_bytes",
    "canonicalize_program_execution_value",
    "decode_execution_observation",
    "decode_program_execution_record",
    "load_payload_schema",
    "loads_program_execution_json",
    "observe_program_event",
    "program_execution_cid_for",
    "public_execution_view",
]
