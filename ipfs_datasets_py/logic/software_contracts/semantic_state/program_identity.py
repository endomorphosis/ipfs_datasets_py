"""Closed program-world identity envelopes and canonicalization profiles.

This module owns the datasets ``@1`` identity contracts for semantic objects,
canonical graphs, raw/abstract execution states, events, traces, projections,
relation claims, transitions, and semantic world roots.

Authority rules (normative):

* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
  Collection-semantics declarations reuse ``ir_core.canonical`` rather than
  introducing a second CID or envelope encoder.
* Exact bytes under the declared codec/profile determine CIDs.  A CID does not
  establish truth, equivalence, proof, authorization, freshness, or completion.
* Semantic-object identity never includes model-dependent projection material
  (embeddings, scores, tokenizer/model/preprocessor bindings, vectors).
* Projection identity binds those model-dependent dimensions; changing them
  changes ``projection_cid`` only.
* Irrelevant wall-clock / host observations are excluded from semantic
  identity.  Raw and abstract execution states always have distinct CIDs, and
  the versioned abstraction profile participates in abstract-state identity.
* Records are recursively immutable, closed to unknown fields, and restricted
  to strict DAG-JSON types.  Duplicate JSON keys, non-finite numbers, floats,
  arbitrary objects, unknown codecs, and unsupported languages fail closed.
* Existing software-contract ``@1`` payloads and the CID profile v1 encoder
  are not modified here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import json
import unicodedata

from ipfs_datasets_py.logic.ir_core.canonical import (
    CANONICAL_JSON_PROFILE,
    CanonicalizationError,
    CollectionSchema,
    CollectionSemantics,
    canonical_json_bytes as ir_canonical_json_bytes,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    CID_BASE,
    CID_VERSION,
    MULTIHASH_TYPE,
    PROFILE_ID as CID_PROFILE_ID,
    PROFILE_VERSION as CID_PROFILE_VERSION,
    SOURCE_CODEC,
    STRUCTURED_CODEC,
    StructuredIdentityError,
    canonical_dag_json_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
    validate_cid,
    validate_structured_value,
)


# ---------------------------------------------------------------------------
# Schema / profile constants (normative)
# ---------------------------------------------------------------------------

PROGRAM_WORLD_CANONICALIZATION_PROFILE_ID: Final[str] = (
    "program-world-canonicalization-profile-v1"
)
PROGRAM_WORLD_CANONICALIZATION_PROFILE_VERSION: Final[str] = "1.0.0"
PROGRAM_WORLD_CANONICALIZATION_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-world-canonicalization-profile@1"
)
SEMANTIC_OBJECT_ENVELOPE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-object-envelope@1"
)
CANONICAL_PROGRAM_GRAPH_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.canonical-program-graph-identity@1"
)
PROGRAM_GRAPH_SNAPSHOT_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-graph-snapshot-identity@1"
)
PROGRAM_GRAPH_DELTA_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-graph-delta-identity@1"
)
RAW_EXECUTION_STATE_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.raw-execution-state-identity@1"
)
STATE_ABSTRACTION_PROFILE_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.state-abstraction-profile-identity@1"
)
ABSTRACT_EXECUTION_STATE_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.abstract-execution-state-identity@1"
)
STACK_FRAME_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.stack-frame-identity@1"
)
PROGRAM_EVENT_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-event-identity@1"
)
EXECUTION_TRACE_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.execution-trace-identity@1"
)
PROJECTION_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.projection-identity@1"
)
PROJECTION_INDEX_MANIFEST_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.projection-index-manifest-identity@1"
)
RELATION_CLAIM_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.relation-claim-identity@1"
)
TRANSITION_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.transition-identity@1"
)
SEMANTIC_WORLD_ROOT_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-world-root-identity@1"
)

SEMANTIC_OBJECT_ENVELOPE_INTERFACE: Final[str] = "SemanticObjectEnvelope@1"
PROGRAM_WORLD_CANONICALIZATION_PROFILE_INTERFACE: Final[str] = (
    "ProgramWorldCanonicalizationProfile@1"
)
PROJECTION_IDENTITY_INTERFACE: Final[str] = "ProjectionIdentity@1"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_COLLECTION_ITEMS: Final[int] = 100_000
MAX_VECTOR_DIMENSION: Final[int] = 1_048_576
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
    "/added_edge_cids": CollectionSemantics.SET_LIKE.value,
    "/added_node_cids": CollectionSemantics.SET_LIKE.value,
    "/assumption_cids": CollectionSemantics.SET_LIKE.value,
    "/dimensions": CollectionSemantics.SET_LIKE.value,
    "/edge_cids": CollectionSemantics.SET_LIKE.value,
    "/event_cids": CollectionSemantics.ORDERED.value,
    "/evidence_cids": CollectionSemantics.SET_LIKE.value,
    "/invalidator_cids": CollectionSemantics.SET_LIKE.value,
    "/node_cids": CollectionSemantics.SET_LIKE.value,
    "/raw_execution_state_cids": CollectionSemantics.ORDERED.value,
    "/removed_edge_cids": CollectionSemantics.SET_LIKE.value,
    "/removed_node_cids": CollectionSemantics.SET_LIKE.value,
    "/retained_subroot_cids": CollectionSemantics.SET_LIKE.value,
    "/schema_ids": CollectionSemantics.SET_LIKE.value,
    "/segment_cids": CollectionSemantics.ORDERED.value,
    "/stack_frame_cids": CollectionSemantics.ORDERED.value,
    "/unavailable_dimensions": CollectionSemantics.SET_LIKE.value,
}

SEMANTIC_IDENTITY_EXCLUDED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "attempt",
        "byte_order",
        "checkout_path",
        "clock",
        "clocks",
        "distance",
        "dtype",
        "embedding",
        "embedding_score",
        "embeddings",
        "fence",
        "fences",
        "generation",
        "generations",
        "hostname",
        "knn",
        "lease",
        "leases",
        "local_path",
        "local_paths",
        "metric",
        "model",
        "model_cid",
        "model_data",
        "model_output",
        "nearest",
        "normalization_profile_cid",
        "normalizer",
        "observed_at",
        "pid",
        "preprocessing_profile_cid",
        "preprocessor",
        "process_id",
        "prompt",
        "provider",
        "provider_output",
        "quantization",
        "quantization_profile_cid",
        "rank",
        "request_id",
        "score",
        "scores",
        "similarity",
        "store_path",
        "timestamp",
        "timestamps",
        "tokenizer",
        "tokenizer_cid",
        "vector",
        "vector_bytes",
        "vector_cid",
        "vectors",
        "wall_clock",
        "worker_id",
    }
)

PROJECTION_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "subject_cid",
    "subject_kind",
    "projection_kind",
    "model_cid",
    "tokenizer_cid",
    "preprocessing_profile_cid",
    "normalization_profile_cid",
    "dimension",
    "metric",
    "dtype",
    "byte_order",
    "quantization_profile_cid",
    "vector_cid",
    "privacy_class",
    "availability_policy",
    "authoritative",
)

PROJECTION_REJECTION_REASONS: Final[tuple[str, ...]] = (
    "NaN",
    "infinity",
    "dimension mismatch",
    "unspecified byte order",
    "unpinned model or preprocessor",
    "score-derived identity",
    "mutable unresolved document identity",
)

PROJECTION_MATERIAL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "authoritative",
        "availability_policy",
        "byte_order",
        "dimension",
        "dtype",
        "embedding",
        "embedding_score",
        "embeddings",
        "metric",
        "model",
        "model_cid",
        "normalization_profile_cid",
        "normalizer",
        "preprocessing_profile_cid",
        "preprocessor",
        "privacy_class",
        "projection_kind",
        "quantization",
        "quantization_profile_cid",
        "score",
        "scores",
        "similarity",
        "subject_kind",
        "tokenizer",
        "tokenizer_cid",
        "vector",
        "vector_bytes",
        "vector_cid",
        "vectors",
    }
)

PRIVATE_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "hidden_witness",
        "password",
        "private_key",
        "private_premise",
        "private_source",
        "private_witness",
        "raw_private_source",
        "refresh_token",
        "secret",
        "session_token",
        "witness",
    }
)

FORBIDDEN_RELATION_KINDS: Final[frozenset[str]] = frozenset(
    {"similar", "similarity", "nearest", "knn", "embedding_neighbor"}
)

SEMANTIC_OBJECT_DECLARATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "kind",
        "language",
        "repository_id",
        "logical_name",
        "declaration_cid",
        "source_cid",
        "environment_binding_cid",
        "metadata",
        "declaration",
    }
)


class ProgramIdentityError(ValueError):
    """Raised when a program-world identity payload is malformed."""


class ProgramLanguage(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    SHELL = "shell"


class SemanticObjectKind(str, Enum):
    SYMBOL = "symbol"
    ARTIFACT = "artifact"
    SOURCE = "source"
    DOMAIN_STATE = "domain_state"
    PROGRAM_GRAPH = "program_graph"
    EXECUTION_STATE = "execution_state"
    EVENT = "event"
    TRACE = "trace"
    RELATION = "relation"
    TRANSITION = "transition"
    WORLD_ROOT = "world_root"


class ProgramGraphKind(str, Enum):
    STATIC_LOGICAL = "static_logical"
    DYNAMIC_LOGICAL = "dynamic_logical"


class ProjectionKind(str, Enum):
    EMBEDDING = "embedding"
    STRUCTURAL_FEATURE = "structural_feature"
    TOKEN_HISTOGRAM = "token_histogram"
    GRAPH_KERNEL = "graph_kernel"


class ProjectionSubjectKind(str, Enum):
    SEMANTIC_OBJECT = "semantic_object"
    RAW_EXECUTION_STATE = "raw_execution_state"
    ABSTRACT_EXECUTION_STATE = "abstract_execution_state"


class ProjectionMetric(str, Enum):
    COSINE = "cosine"
    DOT_PRODUCT = "dot_product"
    EUCLIDEAN = "euclidean"


class ProjectionDType(str, Enum):
    FLOAT32 = "float32"
    FLOAT16 = "float16"
    BFLOAT16 = "bfloat16"
    INT8 = "int8"
    UINT8 = "uint8"
    INT32 = "int32"


class ByteOrder(str, Enum):
    LITTLE = "little"
    BIG = "big"


class PrivacyClass(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    PRIVATE = "private"


class AvailabilityPolicy(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    REDACTED = "redacted"


class ObservationStatus(str, Enum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    REDACTED = "redacted"
    INFERRED_UNTRUSTED = "inferred_untrusted"


class EventKind(str, Enum):
    CALL = "call"
    RETURN = "return"
    ASSIGN = "assign"
    RAISE = "raise"
    CATCH = "catch"
    BRANCH = "branch"
    ENTER = "enter"
    EXIT = "exit"
    OBSERVE = "observe"
    UNAVAILABLE = "unavailable"


class TransitionKind(str, Enum):
    QUERY = "query"
    PREDICTION = "prediction"
    OBSERVATION = "observation"
    ADMISSION = "admission"
    ACCEPTED = "accepted"


class RelationKind(str, Enum):
    EQUALITY = "equality"
    REFINEMENT = "refinement"
    ENTAILMENT = "entailment"
    CONTRADICTION = "contradiction"
    COMPATIBILITY = "compatibility"
    ALPHA_EQUIVALENCE = "alpha_equivalence"
    STRUCTURAL_EQUIVALENCE = "structural_equivalence"
    LOGICAL_EQUIVALENCE = "logical_equivalence"
    BEHAVIORAL_EQUIVALENCE = "behavioral_equivalence"
    OBSERVATIONAL_EQUIVALENCE = "observational_equivalence"
    INTENT = "intent"
    TRANSITION_BEHAVIOR = "transition_behavior"


class RelationAuthorityStatus(str, Enum):
    CANDIDATE = "candidate"
    ASSERTED = "asserted"
    VALIDATED = "validated"
    PROVED = "proved"
    REFUTED = "refuted"
    UNKNOWN = "unknown"
    STALE = "stale"
    SUPERSEDED = "superseded"


class AbstractionSoundnessClaim(str, Enum):
    OVER_APPROXIMATION = "over_approximation"
    UNDER_APPROXIMATION = "under_approximation"
    EXACT = "exact"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise ProgramIdentityError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ProgramIdentityError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise ProgramIdentityError(f"{name} contains invalid text")
    return value


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise ProgramIdentityError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ProgramIdentityError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ProgramIdentityError(f"{name} must be a nonnegative integer")
    if value > MAX_SAFE_INTEGER:
        raise ProgramIdentityError(f"{name} exceeds the safe JSON integer range")
    return value


def _positive_int(value: Any, name: str, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1 or value > maximum:
        raise ProgramIdentityError(
            f"{name} must be an integer in 1..{maximum}"
        )
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ProgramIdentityError(f"{name} must be a boolean")
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


def _reject_forbidden_keys(mapping: Mapping[str, Any], name: str) -> None:
    keys = set(mapping)
    private = keys & PRIVATE_FIELD_MARKERS
    if private:
        raise ProgramIdentityError(
            f"{name} rejects private fields {sorted(private)}"
        )
    excluded = keys & SEMANTIC_IDENTITY_EXCLUDED_FIELDS
    if excluded:
        raise ProgramIdentityError(
            f"{name} rejects non-semantic fields {sorted(excluded)}"
        )


def _mapping(
    value: Any,
    name: str,
    *,
    frozen: bool = True,
    reject_excluded: bool = True,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProgramIdentityError(f"{name} must be a mapping")
    result = _thaw_structured(dict(value))
    if reject_excluded:
        _reject_forbidden_keys(result, name)
        for key, item in result.items():
            if isinstance(item, Mapping):
                _reject_forbidden_keys(item, f"{name}.{key}")
    try:
        validate_structured_value(result)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramIdentityError(f"{name} must be strict DAG-JSON") from exc
    encoded = canonical_dag_json_bytes(result)
    if len(encoded) > MAX_METADATA_BYTES:
        raise ProgramIdentityError(f"{name} exceeds its byte bound")
    return _freeze_structured(result) if frozen else result


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ProgramIdentityError(f"{name} must be a mapping")
    actual = set(data)
    extra = actual - fields
    missing = fields - actual
    if extra:
        raise ProgramIdentityError(
            f"{name} rejects unknown fields {sorted(extra)}"
        )
    if missing:
        raise ProgramIdentityError(f"{name} missing fields {sorted(missing)}")
    return dict(data)


def _unique_sorted_texts(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = [_text(value, name) for value in values]
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramIdentityError(f"{name} exceeds its item bound")
    ordered = tuple(sorted(items))
    if len(ordered) != len(set(ordered)):
        raise ProgramIdentityError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = [_cid(value, name) for value in values]
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramIdentityError(f"{name} exceeds its item bound")
    ordered = tuple(sorted(items))
    if len(ordered) != len(set(ordered)):
        raise ProgramIdentityError(f"{name} must not contain duplicates")
    return ordered


def _ordered_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = tuple(_cid(value, name) for value in values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramIdentityError(f"{name} exceeds its item bound")
    return items


def _language(value: Any, name: str = "language") -> str:
    language = _enum(value, ProgramLanguage, name)
    if language not in ADMITTED_LANGUAGES:
        raise ProgramIdentityError(
            f"{name} {language!r} is typed unavailable in this profile"
        )
    return language


def _apply_collection_semantics(value: Any, *, path: tuple[str, ...], schema: CollectionSchema) -> Any:
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


def canonicalize_identity_value(value: Any) -> Any:
    """NFC-normalize, apply declared collection semantics, and reject floats."""

    try:
        validate_structured_value(value)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramIdentityError(
            "identity value must be strict DAG-JSON"
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
        raise ProgramIdentityError(
            "canonical identity value must be strict DAG-JSON"
        ) from exc
    content_bytes = canonical_dag_json_bytes(canonical)
    try:
        ir_bytes = ir_canonical_json_bytes(
            canonical,
            collection_schema=CollectionSchema(None, require_declared=False),
        )
    except CanonicalizationError as exc:
        raise ProgramIdentityError(
            "ir_core rejected the canonical identity value"
        ) from exc
    if ir_bytes != content_bytes:
        raise ProgramIdentityError(
            "ir_core canonical JSON diverged from software-contract DAG-JSON"
        )
    return canonical


def identity_cid_for(payload: Mapping[str, Any]) -> str:
    """Return the structured CID of one canonical identity payload."""

    canonical = canonicalize_identity_value(payload)
    return cid_for_structured(canonical)


def canonical_identity_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return canonical DAG-JSON bytes of one identity payload."""

    canonical = canonicalize_identity_value(payload)
    return canonical_dag_json_bytes(canonical)


def _verify_claimed(name: str, claimed: Any, payload: Mapping[str, Any]) -> str:
    canonical = canonicalize_identity_value(payload)
    try:
        return decode_and_recompute_structured(claimed, canonical)
    except Exception as exc:
        raise ProgramIdentityError(f"{name} cid does not verify") from exc


def _reject_nonfinite_constant(token: str) -> None:
    raise ProgramIdentityError(f"nonfinite JSON number {token!r} is rejected")


def _parse_int(token: str) -> int:
    try:
        value = int(token, 10)
    except ValueError as exc:
        raise ProgramIdentityError(f"JSON number {token!r} is not an integer") from exc
    if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
        raise ProgramIdentityError("integer is outside the safe JSON range")
    return value


def _parse_float(token: str) -> None:
    raise ProgramIdentityError(
        f"JSON number {token!r} is not a finite integer; floats are rejected"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProgramIdentityError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def loads_identity_json(text: str | bytes) -> Any:
    """Decode JSON text, rejecting duplicate keys, NaN, and floats."""

    if type(text) is bytes:
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProgramIdentityError("identity JSON must be UTF-8") from exc
    if type(text) is not str:
        raise ProgramIdentityError("identity JSON must be text or UTF-8 bytes")
    try:
        return json.loads(
            text,
            parse_int=_parse_int,
            parse_float=_parse_float,
            parse_constant=_reject_nonfinite_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ProgramIdentityError:
        raise
    except json.JSONDecodeError as exc:
        raise ProgramIdentityError("identity JSON is not well-formed") from exc


def strip_non_semantic_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    """Drop observation and projection keys that must not affect semantic identity."""

    if not isinstance(data, Mapping):
        raise ProgramIdentityError("declaration must be a mapping")
    ignored = SEMANTIC_IDENTITY_EXCLUDED_FIELDS | PROJECTION_MATERIAL_FIELDS
    return {key: value for key, value in data.items() if key not in ignored}


# ---------------------------------------------------------------------------
# Canonicalization profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProgramWorldCanonicalizationProfile:
    """Sealed descriptor for program-world identity canonicalization ``@1``."""

    profile_id: str = PROGRAM_WORLD_CANONICALIZATION_PROFILE_ID
    profile_version: str = PROGRAM_WORLD_CANONICALIZATION_PROFILE_VERSION
    cid_profile_id: str = CID_PROFILE_ID
    cid_profile_version: str = CID_PROFILE_VERSION
    canonical_json_profile: str = CANONICAL_JSON_PROFILE
    cid_version: int = CID_VERSION
    base: str = CID_BASE
    multihash: str = MULTIHASH_TYPE
    source_codec: str = SOURCE_CODEC
    structured_codec: str = STRUCTURED_CODEC
    admitted_languages: Sequence[str] = ADMITTED_LANGUAGES
    unavailable_languages: Sequence[str] = UNAVAILABLE_LANGUAGES
    unknown_fields: str = "reject"
    duplicate_json_keys: str = "reject"
    nonfinite_numbers: str = "reject"
    arbitrary_code_deserialization: str = "forbidden"
    semantic_object_identity_may_derive_from_embedding_score: bool = False
    model_dependent_projection_in_semantic_declaration_identity: bool = False
    irrelevant_wall_clock_observation_in_semantic_identity: bool = False
    existing_v1_payload_may_change: bool = False
    claimed_cid_must_rehash: bool = True
    collection_semantics: Mapping[str, str] = field(
        default_factory=lambda: dict(COLLECTION_SEMANTICS_DECLARATION)
    )
    semantic_identity_excluded_fields: Sequence[str] = field(
        default_factory=lambda: tuple(sorted(SEMANTIC_IDENTITY_EXCLUDED_FIELDS))
    )
    projection_required_fields: Sequence[str] = PROJECTION_REQUIRED_FIELDS
    projection_rejection_reasons: Sequence[str] = PROJECTION_REJECTION_REASONS

    SCHEMA: ClassVar[str] = PROGRAM_WORLD_CANONICALIZATION_PROFILE_SCHEMA
    CID_FIELD: ClassVar[str] = "profile_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "profile_id",
            "profile_version",
            "cid_profile_id",
            "cid_profile_version",
            "canonical_json_profile",
            "cid_version",
            "base",
            "multihash",
            "source_codec",
            "structured_codec",
            "admitted_languages",
            "unavailable_languages",
            "unknown_fields",
            "duplicate_json_keys",
            "nonfinite_numbers",
            "arbitrary_code_deserialization",
            "semantic_object_identity_may_derive_from_embedding_score",
            "model_dependent_projection_in_semantic_declaration_identity",
            "irrelevant_wall_clock_observation_in_semantic_identity",
            "existing_v1_payload_may_change",
            "claimed_cid_must_rehash",
            "collection_semantics",
            "semantic_identity_excluded_fields",
            "projection_required_fields",
            "projection_rejection_reasons",
            "profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        object.__setattr__(
            self, "profile_version", _text(self.profile_version, "profile_version")
        )
        object.__setattr__(
            self, "cid_profile_id", _text(self.cid_profile_id, "cid_profile_id")
        )
        object.__setattr__(
            self,
            "cid_profile_version",
            _text(self.cid_profile_version, "cid_profile_version"),
        )
        object.__setattr__(
            self,
            "canonical_json_profile",
            _text(self.canonical_json_profile, "canonical_json_profile"),
        )
        object.__setattr__(self, "cid_version", _nonneg_int(self.cid_version, "cid_version"))
        object.__setattr__(self, "base", _text(self.base, "base"))
        object.__setattr__(self, "multihash", _text(self.multihash, "multihash"))
        object.__setattr__(self, "source_codec", _text(self.source_codec, "source_codec"))
        object.__setattr__(
            self, "structured_codec", _text(self.structured_codec, "structured_codec")
        )
        object.__setattr__(
            self,
            "admitted_languages",
            _unique_sorted_texts(self.admitted_languages, "admitted_language"),
        )
        object.__setattr__(
            self,
            "unavailable_languages",
            _unique_sorted_texts(self.unavailable_languages, "unavailable_language"),
        )
        for name in (
            "unknown_fields",
            "duplicate_json_keys",
            "nonfinite_numbers",
            "arbitrary_code_deserialization",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "semantic_object_identity_may_derive_from_embedding_score",
            "model_dependent_projection_in_semantic_declaration_identity",
            "irrelevant_wall_clock_observation_in_semantic_identity",
            "existing_v1_payload_may_change",
            "claimed_cid_must_rehash",
        ):
            object.__setattr__(self, name, _bool(getattr(self, name), name))
        semantics = _mapping(self.collection_semantics, "collection_semantics")
        object.__setattr__(self, "collection_semantics", semantics)
        object.__setattr__(
            self,
            "semantic_identity_excluded_fields",
            _unique_sorted_texts(
                self.semantic_identity_excluded_fields,
                "semantic_identity_excluded_field",
            ),
        )
        object.__setattr__(
            self,
            "projection_required_fields",
            tuple(
                _text(item, "projection_required_field")
                for item in self.projection_required_fields
            ),
        )
        object.__setattr__(
            self,
            "projection_rejection_reasons",
            tuple(
                _text(item, "projection_rejection_reason")
                for item in self.projection_rejection_reasons
            ),
        )
        if self.profile_id != PROGRAM_WORLD_CANONICALIZATION_PROFILE_ID:
            raise ProgramIdentityError("unsupported canonicalization profile_id")
        if self.profile_version != PROGRAM_WORLD_CANONICALIZATION_PROFILE_VERSION:
            raise ProgramIdentityError("unsupported canonicalization profile_version")
        if self.cid_profile_id != CID_PROFILE_ID:
            raise ProgramIdentityError(
                "canonicalization profile must reuse software-contract CID profile v1"
            )
        if self.canonical_json_profile != CANONICAL_JSON_PROFILE:
            raise ProgramIdentityError(
                "canonicalization profile must reuse ir-canonical-json-v1"
            )
        if self.unknown_fields != "reject" or self.duplicate_json_keys != "reject":
            raise ProgramIdentityError("profile must reject unknown fields and duplicate keys")
        if self.nonfinite_numbers != "reject":
            raise ProgramIdentityError("profile must reject nonfinite numbers")
        if self.arbitrary_code_deserialization != "forbidden":
            raise ProgramIdentityError("arbitrary code deserialization is forbidden")
        if (
            self.semantic_object_identity_may_derive_from_embedding_score
            or self.model_dependent_projection_in_semantic_declaration_identity
            or self.irrelevant_wall_clock_observation_in_semantic_identity
            or self.existing_v1_payload_may_change
        ):
            raise ProgramIdentityError("profile invariants cannot be relaxed")
        if not self.claimed_cid_must_rehash:
            raise ProgramIdentityError("claimed CIDs must rehash")
        if tuple(self.admitted_languages) != ADMITTED_LANGUAGES:
            raise ProgramIdentityError("admitted languages cannot be expanded here")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "cid_profile_id": self.cid_profile_id,
            "cid_profile_version": self.cid_profile_version,
            "canonical_json_profile": self.canonical_json_profile,
            "cid_version": self.cid_version,
            "base": self.base,
            "multihash": self.multihash,
            "source_codec": self.source_codec,
            "structured_codec": self.structured_codec,
            "admitted_languages": list(self.admitted_languages),
            "unavailable_languages": list(self.unavailable_languages),
            "unknown_fields": self.unknown_fields,
            "duplicate_json_keys": self.duplicate_json_keys,
            "nonfinite_numbers": self.nonfinite_numbers,
            "arbitrary_code_deserialization": self.arbitrary_code_deserialization,
            "semantic_object_identity_may_derive_from_embedding_score": (
                self.semantic_object_identity_may_derive_from_embedding_score
            ),
            "model_dependent_projection_in_semantic_declaration_identity": (
                self.model_dependent_projection_in_semantic_declaration_identity
            ),
            "irrelevant_wall_clock_observation_in_semantic_identity": (
                self.irrelevant_wall_clock_observation_in_semantic_identity
            ),
            "existing_v1_payload_may_change": self.existing_v1_payload_may_change,
            "claimed_cid_must_rehash": self.claimed_cid_must_rehash,
            "collection_semantics": _thaw_structured(self.collection_semantics),
            "semantic_identity_excluded_fields": list(
                self.semantic_identity_excluded_fields
            ),
            "projection_required_fields": list(self.projection_required_fields),
            "projection_rejection_reasons": list(self.projection_rejection_reasons),
        }

    @property
    def profile_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_identity_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["profile_cid"] = self.profile_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramWorldCanonicalizationProfile":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("profile_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError(
                "unsupported ProgramWorldCanonicalizationProfile schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result

    @classmethod
    def normative(cls) -> "ProgramWorldCanonicalizationProfile":
        return cls()


def program_world_profile() -> ProgramWorldCanonicalizationProfile:
    """Return the sealed ``ProgramWorldCanonicalizationProfile@1`` instance."""

    return ProgramWorldCanonicalizationProfile.normative()


# ---------------------------------------------------------------------------
# Identity envelopes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticObjectEnvelope:
    """Canonical semantic-object declaration without projection material."""

    kind: SemanticObjectKind | str
    language: ProgramLanguage | str
    repository_id: str
    logical_name: str
    declaration_cid: str
    source_cid: str | None = None
    environment_binding_cid: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    SCHEMA: ClassVar[str] = SEMANTIC_OBJECT_ENVELOPE_SCHEMA
    CID_FIELD: ClassVar[str] = "semantic_object_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "kind",
            "language",
            "repository_id",
            "logical_name",
            "declaration_cid",
            "source_cid",
            "environment_binding_cid",
            "metadata",
            "semantic_object_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(self.kind, SemanticObjectKind, "kind"))
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "repository_id", _text(self.repository_id, "repository_id"))
        object.__setattr__(self, "logical_name", _text(self.logical_name, "logical_name"))
        object.__setattr__(
            self, "declaration_cid", _cid(self.declaration_cid, "declaration_cid")
        )
        object.__setattr__(self, "source_cid", _optional_cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _optional_cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "kind": self.kind,
            "language": self.language,
            "repository_id": self.repository_id,
            "logical_name": self.logical_name,
            "declaration_cid": self.declaration_cid,
            "source_cid": self.source_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def semantic_object_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_identity_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["semantic_object_cid"] = self.semantic_object_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticObjectEnvelope":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("semantic_object_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError("unsupported SemanticObjectEnvelope schema version")
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


def semantic_object_from_declaration(data: Mapping[str, Any]) -> SemanticObjectEnvelope:
    """Build a semantic object, ignoring observation and projection material."""

    if not isinstance(data, Mapping):
        raise ProgramIdentityError("declaration must be a mapping")
    stripped = strip_non_semantic_fields(data)
    unknown = set(stripped) - SEMANTIC_OBJECT_DECLARATION_FIELDS
    if unknown:
        raise ProgramIdentityError(
            f"semantic object declaration rejects unknown fields {sorted(unknown)}"
        )
    declaration = stripped.get("declaration")
    declaration_cid = stripped.get("declaration_cid")
    if declaration is not None:
        if not isinstance(declaration, Mapping):
            raise ProgramIdentityError("declaration body must be a mapping")
        body = strip_non_semantic_fields(declaration)
        _reject_forbidden_keys(body, "declaration")
        declaration_cid = identity_cid_for(canonicalize_identity_value(body))
    if declaration_cid is None:
        raise ProgramIdentityError("declaration_cid or declaration is required")
    return SemanticObjectEnvelope(
        kind=stripped.get("kind", SemanticObjectKind.SYMBOL),
        language=stripped.get("language", ProgramLanguage.PYTHON),
        repository_id=stripped.get("repository_id", ""),
        logical_name=stripped.get("logical_name", ""),
        declaration_cid=declaration_cid,
        source_cid=stripped.get("source_cid"),
        environment_binding_cid=stripped.get("environment_binding_cid"),
        metadata=stripped.get("metadata") or {},
    )


@dataclass(frozen=True, slots=True)
class CanonicalProgramGraphIdentity:
    """Canonical logical program-graph meaning; never an ANN graph."""

    language: ProgramLanguage | str
    graph_kind: ProgramGraphKind | str
    node_cids: Sequence[str] = ()
    edge_cids: Sequence[str] = ()
    environment_binding_set_cid: str | None = None
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = CANONICAL_PROGRAM_GRAPH_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "canonical_program_graph_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "graph_kind",
            "node_cids",
            "edge_cids",
            "environment_binding_set_cid",
            "unavailable_dimensions",
            "canonical_program_graph_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self, "graph_kind", _enum(self.graph_kind, ProgramGraphKind, "graph_kind")
        )
        if self.graph_kind not in {
            ProgramGraphKind.STATIC_LOGICAL.value,
            ProgramGraphKind.DYNAMIC_LOGICAL.value,
        }:
            raise ProgramIdentityError("canonical graph kind must be logical, not ANN")
        object.__setattr__(self, "node_cids", _unique_sorted_cids(self.node_cids, "node_cid"))
        object.__setattr__(self, "edge_cids", _unique_sorted_cids(self.edge_cids, "edge_cid"))
        object.__setattr__(
            self,
            "environment_binding_set_cid",
            _optional_cid(
                self.environment_binding_set_cid, "environment_binding_set_cid"
            ),
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "graph_kind": self.graph_kind,
            "node_cids": list(self.node_cids),
            "edge_cids": list(self.edge_cids),
            "environment_binding_set_cid": self.environment_binding_set_cid,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def canonical_program_graph_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_identity_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["canonical_program_graph_cid"] = self.canonical_program_graph_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CanonicalProgramGraphIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("canonical_program_graph_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError(
                "unsupported CanonicalProgramGraphIdentity schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class ProgramGraphSnapshotIdentity:
    """Sealed ordered node/edge set at exact environment bindings."""

    canonical_program_graph_cid: str
    node_cids: Sequence[str]
    edge_cids: Sequence[str]
    environment_binding_set_cid: str
    sealed_binding_cid: str

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_SNAPSHOT_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "program_graph_snapshot_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "canonical_program_graph_cid",
            "node_cids",
            "edge_cids",
            "environment_binding_set_cid",
            "sealed_binding_cid",
            "program_graph_snapshot_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_program_graph_cid",
            _cid(self.canonical_program_graph_cid, "canonical_program_graph_cid"),
        )
        object.__setattr__(self, "node_cids", _unique_sorted_cids(self.node_cids, "node_cid"))
        object.__setattr__(self, "edge_cids", _unique_sorted_cids(self.edge_cids, "edge_cid"))
        object.__setattr__(
            self,
            "environment_binding_set_cid",
            _cid(self.environment_binding_set_cid, "environment_binding_set_cid"),
        )
        object.__setattr__(
            self, "sealed_binding_cid", _cid(self.sealed_binding_cid, "sealed_binding_cid")
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "canonical_program_graph_cid": self.canonical_program_graph_cid,
            "node_cids": list(self.node_cids),
            "edge_cids": list(self.edge_cids),
            "environment_binding_set_cid": self.environment_binding_set_cid,
            "sealed_binding_cid": self.sealed_binding_cid,
        }

    @property
    def program_graph_snapshot_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["program_graph_snapshot_cid"] = self.program_graph_snapshot_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramGraphSnapshotIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("program_graph_snapshot_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError(
                "unsupported ProgramGraphSnapshotIdentity schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class ProgramGraphDeltaIdentity:
    """Pure change record that retains unchanged subroots."""

    previous_snapshot_cid: str
    added_node_cids: Sequence[str] = ()
    removed_node_cids: Sequence[str] = ()
    added_edge_cids: Sequence[str] = ()
    removed_edge_cids: Sequence[str] = ()
    retained_subroot_cids: Sequence[str] = ()

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_DELTA_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "program_graph_delta_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "previous_snapshot_cid",
            "added_node_cids",
            "removed_node_cids",
            "added_edge_cids",
            "removed_edge_cids",
            "retained_subroot_cids",
            "program_graph_delta_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "previous_snapshot_cid",
            _cid(self.previous_snapshot_cid, "previous_snapshot_cid"),
        )
        object.__setattr__(
            self, "added_node_cids", _unique_sorted_cids(self.added_node_cids, "added_node_cid")
        )
        object.__setattr__(
            self,
            "removed_node_cids",
            _unique_sorted_cids(self.removed_node_cids, "removed_node_cid"),
        )
        object.__setattr__(
            self, "added_edge_cids", _unique_sorted_cids(self.added_edge_cids, "added_edge_cid")
        )
        object.__setattr__(
            self,
            "removed_edge_cids",
            _unique_sorted_cids(self.removed_edge_cids, "removed_edge_cid"),
        )
        object.__setattr__(
            self,
            "retained_subroot_cids",
            _unique_sorted_cids(self.retained_subroot_cids, "retained_subroot_cid"),
        )
        overlap_nodes = set(self.added_node_cids) & set(self.removed_node_cids)
        overlap_edges = set(self.added_edge_cids) & set(self.removed_edge_cids)
        if overlap_nodes or overlap_edges:
            raise ProgramIdentityError("delta cannot add and remove the same identity")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "previous_snapshot_cid": self.previous_snapshot_cid,
            "added_node_cids": list(self.added_node_cids),
            "removed_node_cids": list(self.removed_node_cids),
            "added_edge_cids": list(self.added_edge_cids),
            "removed_edge_cids": list(self.removed_edge_cids),
            "retained_subroot_cids": list(self.retained_subroot_cids),
        }

    @property
    def program_graph_delta_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["program_graph_delta_cid"] = self.program_graph_delta_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramGraphDeltaIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("program_graph_delta_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError(
                "unsupported ProgramGraphDeltaIdentity schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class RawExecutionStateIdentity:
    """Bounded redacted observed state under an exact capture profile."""

    language: ProgramLanguage | str
    capture_profile_cid: str
    observed_state: Mapping[str, Any]
    stack_frame_cids: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()
    observation_status: ObservationStatus | str = ObservationStatus.OBSERVED

    SCHEMA: ClassVar[str] = RAW_EXECUTION_STATE_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "raw_execution_state_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "capture_profile_cid",
            "observed_state",
            "stack_frame_cids",
            "unavailable_dimensions",
            "observation_status",
            "raw_execution_state_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self, "capture_profile_cid", _cid(self.capture_profile_cid, "capture_profile_cid")
        )
        object.__setattr__(
            self, "observed_state", _mapping(self.observed_state, "observed_state")
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

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "capture_profile_cid": self.capture_profile_cid,
            "observed_state": _thaw_structured(self.observed_state),
            "stack_frame_cids": list(self.stack_frame_cids),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "observation_status": self.observation_status,
        }

    @property
    def raw_execution_state_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_identity_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["raw_execution_state_cid"] = self.raw_execution_state_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RawExecutionStateIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("raw_execution_state_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError(
                "unsupported RawExecutionStateIdentity schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class StateAbstractionProfileIdentity:
    """Versioned abstraction profile participating in abstract-state identity."""

    language: ProgramLanguage | str
    profile_name: str
    dimensions: Sequence[str]
    unavailable_dimensions: Sequence[str] = ()
    soundness_claim: AbstractionSoundnessClaim | str = AbstractionSoundnessClaim.UNKNOWN

    SCHEMA: ClassVar[str] = STATE_ABSTRACTION_PROFILE_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "abstraction_profile_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "profile_name",
            "dimensions",
            "unavailable_dimensions",
            "soundness_claim",
            "abstraction_profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "profile_name", _text(self.profile_name, "profile_name"))
        object.__setattr__(
            self, "dimensions", _unique_sorted_texts(self.dimensions, "dimension")
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        object.__setattr__(
            self,
            "soundness_claim",
            _enum(self.soundness_claim, AbstractionSoundnessClaim, "soundness_claim"),
        )
        overlap = set(self.dimensions) & set(self.unavailable_dimensions)
        if overlap:
            raise ProgramIdentityError(
                "abstraction dimensions cannot also be unavailable"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "profile_name": self.profile_name,
            "dimensions": list(self.dimensions),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "soundness_claim": self.soundness_claim,
        }

    @property
    def abstraction_profile_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["abstraction_profile_cid"] = self.abstraction_profile_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateAbstractionProfileIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("abstraction_profile_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError(
                "unsupported StateAbstractionProfileIdentity schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class AbstractExecutionStateIdentity:
    """Semantic abstraction bound to a raw state and abstraction profile."""

    language: ProgramLanguage | str
    raw_execution_state_cid: str
    abstraction_profile_cid: str
    abstract_state: Mapping[str, Any]
    unavailable_dimensions: Sequence[str] = ()
    observation_status: ObservationStatus | str = ObservationStatus.OBSERVED

    SCHEMA: ClassVar[str] = ABSTRACT_EXECUTION_STATE_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "abstract_execution_state_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "raw_execution_state_cid",
            "abstraction_profile_cid",
            "abstract_state",
            "unavailable_dimensions",
            "observation_status",
            "abstract_execution_state_cid",
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

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "raw_execution_state_cid": self.raw_execution_state_cid,
            "abstraction_profile_cid": self.abstraction_profile_cid,
            "abstract_state": _thaw_structured(self.abstract_state),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "observation_status": self.observation_status,
        }

    @property
    def abstract_execution_state_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_identity_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["abstract_execution_state_cid"] = self.abstract_execution_state_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AbstractExecutionStateIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("abstract_execution_state_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError(
                "unsupported AbstractExecutionStateIdentity schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class StackFrameIdentity:
    """One ordered frame with exact code/environment and a bounded summary."""

    ordinal: int
    language: ProgramLanguage | str
    code_cid: str
    environment_binding_cid: str
    state_summary: Mapping[str, Any] = field(default_factory=dict)

    SCHEMA: ClassVar[str] = STACK_FRAME_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "stack_frame_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "ordinal",
            "language",
            "code_cid",
            "environment_binding_cid",
            "state_summary",
            "stack_frame_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordinal", _nonneg_int(self.ordinal, "ordinal"))
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "code_cid", _cid(self.code_cid, "code_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self, "state_summary", _mapping(self.state_summary, "state_summary")
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "ordinal": self.ordinal,
            "language": self.language,
            "code_cid": self.code_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "state_summary": _thaw_structured(self.state_summary),
        }

    @property
    def stack_frame_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["stack_frame_cid"] = self.stack_frame_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StackFrameIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("stack_frame_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError("unsupported StackFrameIdentity schema version")
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class ProgramEventIdentity:
    """Closed event-grammar record with explicit observation status."""

    event_kind: EventKind | str
    observation_status: ObservationStatus | str
    subject_cid: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    predecessor_event_cid: str | None = None

    SCHEMA: ClassVar[str] = PROGRAM_EVENT_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "program_event_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "event_kind",
            "observation_status",
            "subject_cid",
            "payload",
            "predecessor_event_cid",
            "program_event_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_kind", _enum(self.event_kind, EventKind, "event_kind")
        )
        object.__setattr__(
            self,
            "observation_status",
            _enum(self.observation_status, ObservationStatus, "observation_status"),
        )
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(self, "payload", _mapping(self.payload, "payload"))
        object.__setattr__(
            self,
            "predecessor_event_cid",
            _optional_cid(self.predecessor_event_cid, "predecessor_event_cid"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "event_kind": self.event_kind,
            "observation_status": self.observation_status,
            "subject_cid": self.subject_cid,
            "payload": _thaw_structured(self.payload),
            "predecessor_event_cid": self.predecessor_event_cid,
        }

    @property
    def program_event_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["program_event_cid"] = self.program_event_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramEventIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("program_event_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError("unsupported ProgramEventIdentity schema version")
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class ExecutionTraceIdentity:
    """Ordered event/segment identity; repeated states do not erase history."""

    event_cids: Sequence[str]
    segment_cids: Sequence[str] = ()
    raw_execution_state_cids: Sequence[str] = ()

    SCHEMA: ClassVar[str] = EXECUTION_TRACE_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "execution_trace_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "event_cids",
            "segment_cids",
            "raw_execution_state_cids",
            "execution_trace_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_cids", _ordered_cids(self.event_cids, "event_cid"))
        object.__setattr__(
            self, "segment_cids", _ordered_cids(self.segment_cids, "segment_cid")
        )
        object.__setattr__(
            self,
            "raw_execution_state_cids",
            _ordered_cids(self.raw_execution_state_cids, "raw_execution_state_cid"),
        )
        if not self.event_cids:
            raise ProgramIdentityError("execution trace requires at least one event")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "event_cids": list(self.event_cids),
            "segment_cids": list(self.segment_cids),
            "raw_execution_state_cids": list(self.raw_execution_state_cids),
        }

    @property
    def execution_trace_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["execution_trace_cid"] = self.execution_trace_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionTraceIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("execution_trace_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError(
                "unsupported ExecutionTraceIdentity schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class ProjectionIdentity:
    """Model-bound projection; never semantic-object identity."""

    subject_cid: str
    subject_kind: ProjectionSubjectKind | str
    projection_kind: ProjectionKind | str
    model_cid: str
    tokenizer_cid: str
    preprocessing_profile_cid: str
    normalization_profile_cid: str
    dimension: int
    metric: ProjectionMetric | str
    dtype: ProjectionDType | str
    byte_order: ByteOrder | str
    vector_cid: str
    privacy_class: PrivacyClass | str
    availability_policy: AvailabilityPolicy | str
    quantization_profile_cid: str | None = None
    authoritative: bool = False

    SCHEMA: ClassVar[str] = PROJECTION_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "projection_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "subject_cid",
            "subject_kind",
            "projection_kind",
            "model_cid",
            "tokenizer_cid",
            "preprocessing_profile_cid",
            "normalization_profile_cid",
            "dimension",
            "metric",
            "dtype",
            "byte_order",
            "quantization_profile_cid",
            "vector_cid",
            "privacy_class",
            "availability_policy",
            "authoritative",
            "projection_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(
            self,
            "subject_kind",
            _enum(self.subject_kind, ProjectionSubjectKind, "subject_kind"),
        )
        object.__setattr__(
            self,
            "projection_kind",
            _enum(self.projection_kind, ProjectionKind, "projection_kind"),
        )
        object.__setattr__(self, "model_cid", _cid(self.model_cid, "model_cid"))
        object.__setattr__(self, "tokenizer_cid", _cid(self.tokenizer_cid, "tokenizer_cid"))
        object.__setattr__(
            self,
            "preprocessing_profile_cid",
            _cid(self.preprocessing_profile_cid, "preprocessing_profile_cid"),
        )
        object.__setattr__(
            self,
            "normalization_profile_cid",
            _cid(self.normalization_profile_cid, "normalization_profile_cid"),
        )
        object.__setattr__(
            self,
            "dimension",
            _positive_int(self.dimension, "dimension", MAX_VECTOR_DIMENSION),
        )
        object.__setattr__(self, "metric", _enum(self.metric, ProjectionMetric, "metric"))
        object.__setattr__(self, "dtype", _enum(self.dtype, ProjectionDType, "dtype"))
        object.__setattr__(
            self, "byte_order", _enum(self.byte_order, ByteOrder, "byte_order")
        )
        object.__setattr__(
            self,
            "quantization_profile_cid",
            _optional_cid(self.quantization_profile_cid, "quantization_profile_cid"),
        )
        object.__setattr__(self, "vector_cid", _cid(self.vector_cid, "vector_cid"))
        object.__setattr__(
            self, "privacy_class", _enum(self.privacy_class, PrivacyClass, "privacy_class")
        )
        object.__setattr__(
            self,
            "availability_policy",
            _enum(self.availability_policy, AvailabilityPolicy, "availability_policy"),
        )
        object.__setattr__(self, "authoritative", _bool(self.authoritative, "authoritative"))
        if self.authoritative:
            raise ProgramIdentityError(
                "projections are non-authoritative; they cannot mint semantic identity"
            )
        if self.byte_order not in {ByteOrder.LITTLE.value, ByteOrder.BIG.value}:
            raise ProgramIdentityError("byte_order must be little or big")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "subject_cid": self.subject_cid,
            "subject_kind": self.subject_kind,
            "projection_kind": self.projection_kind,
            "model_cid": self.model_cid,
            "tokenizer_cid": self.tokenizer_cid,
            "preprocessing_profile_cid": self.preprocessing_profile_cid,
            "normalization_profile_cid": self.normalization_profile_cid,
            "dimension": self.dimension,
            "metric": self.metric,
            "dtype": self.dtype,
            "byte_order": self.byte_order,
            "quantization_profile_cid": self.quantization_profile_cid,
            "vector_cid": self.vector_cid,
            "privacy_class": self.privacy_class,
            "availability_policy": self.availability_policy,
            "authoritative": self.authoritative,
        }

    @property
    def projection_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_identity_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["projection_cid"] = self.projection_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectionIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("projection_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError("unsupported ProjectionIdentity schema version")
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


def projection_from_bindings(
    *,
    subject_cid: str,
    subject_kind: ProjectionSubjectKind | str = ProjectionSubjectKind.SEMANTIC_OBJECT,
    projection_kind: ProjectionKind | str = ProjectionKind.EMBEDDING,
    model_cid: str,
    tokenizer_cid: str,
    preprocessing_profile_cid: str,
    normalization_profile_cid: str,
    dimension: int,
    metric: ProjectionMetric | str,
    dtype: ProjectionDType | str,
    byte_order: ByteOrder | str,
    vector_cid: str,
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL,
    availability_policy: AvailabilityPolicy | str = AvailabilityPolicy.AVAILABLE,
    quantization_profile_cid: str | None = None,
) -> ProjectionIdentity:
    """Construct a non-authoritative projection bound to an existing subject CID."""

    return ProjectionIdentity(
        subject_cid=subject_cid,
        subject_kind=subject_kind,
        projection_kind=projection_kind,
        model_cid=model_cid,
        tokenizer_cid=tokenizer_cid,
        preprocessing_profile_cid=preprocessing_profile_cid,
        normalization_profile_cid=normalization_profile_cid,
        dimension=dimension,
        metric=metric,
        dtype=dtype,
        byte_order=byte_order,
        quantization_profile_cid=quantization_profile_cid,
        vector_cid=vector_cid,
        privacy_class=privacy_class,
        availability_policy=availability_policy,
        authoritative=False,
    )


@dataclass(frozen=True, slots=True)
class ProjectionIndexManifestIdentity:
    """Immutable description of a rebuildable non-authoritative index generation."""

    projection_kind: ProjectionKind | str
    model_cid: str
    tokenizer_cid: str
    preprocessing_profile_cid: str
    dimension: int
    metric: ProjectionMetric | str
    dtype: ProjectionDType | str
    byte_order: ByteOrder | str
    source_cid: str
    schema_ids: Sequence[str] = ()
    rebuildable: bool = True
    authoritative: bool = False

    SCHEMA: ClassVar[str] = PROJECTION_INDEX_MANIFEST_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "projection_index_manifest_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "projection_kind",
            "model_cid",
            "tokenizer_cid",
            "preprocessing_profile_cid",
            "dimension",
            "metric",
            "dtype",
            "byte_order",
            "source_cid",
            "schema_ids",
            "rebuildable",
            "authoritative",
            "projection_index_manifest_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "projection_kind",
            _enum(self.projection_kind, ProjectionKind, "projection_kind"),
        )
        object.__setattr__(self, "model_cid", _cid(self.model_cid, "model_cid"))
        object.__setattr__(self, "tokenizer_cid", _cid(self.tokenizer_cid, "tokenizer_cid"))
        object.__setattr__(
            self,
            "preprocessing_profile_cid",
            _cid(self.preprocessing_profile_cid, "preprocessing_profile_cid"),
        )
        object.__setattr__(
            self,
            "dimension",
            _positive_int(self.dimension, "dimension", MAX_VECTOR_DIMENSION),
        )
        object.__setattr__(self, "metric", _enum(self.metric, ProjectionMetric, "metric"))
        object.__setattr__(self, "dtype", _enum(self.dtype, ProjectionDType, "dtype"))
        object.__setattr__(
            self, "byte_order", _enum(self.byte_order, ByteOrder, "byte_order")
        )
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self, "schema_ids", _unique_sorted_texts(self.schema_ids, "schema_id")
        )
        object.__setattr__(self, "rebuildable", _bool(self.rebuildable, "rebuildable"))
        object.__setattr__(self, "authoritative", _bool(self.authoritative, "authoritative"))
        if self.authoritative:
            raise ProgramIdentityError("index manifests are non-authoritative")
        if not self.rebuildable:
            raise ProgramIdentityError("index manifests must be rebuildable")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "projection_kind": self.projection_kind,
            "model_cid": self.model_cid,
            "tokenizer_cid": self.tokenizer_cid,
            "preprocessing_profile_cid": self.preprocessing_profile_cid,
            "dimension": self.dimension,
            "metric": self.metric,
            "dtype": self.dtype,
            "byte_order": self.byte_order,
            "source_cid": self.source_cid,
            "schema_ids": list(self.schema_ids),
            "rebuildable": self.rebuildable,
            "authoritative": self.authoritative,
        }

    @property
    def projection_index_manifest_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["projection_index_manifest_cid"] = self.projection_index_manifest_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectionIndexManifestIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("projection_index_manifest_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError(
                "unsupported ProjectionIndexManifestIdentity schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class RelationClaimIdentity:
    """Typed scoped relation identity; similarity is not a relation kind."""

    relation_kind: RelationKind | str
    left_cid: str
    right_cid: str
    scope_cid: str
    theory_or_policy_cid: str
    environment_binding_cid: str
    authority_status: RelationAuthorityStatus | str
    assumption_cids: Sequence[str] = ()
    evidence_cids: Sequence[str] = ()
    invalidator_cids: Sequence[str] = ()

    SCHEMA: ClassVar[str] = RELATION_CLAIM_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "relation_claim_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "relation_kind",
            "left_cid",
            "right_cid",
            "scope_cid",
            "assumption_cids",
            "theory_or_policy_cid",
            "environment_binding_cid",
            "evidence_cids",
            "invalidator_cids",
            "authority_status",
            "relation_claim_cid",
        }
    )

    def __post_init__(self) -> None:
        if type(self.relation_kind) is str and self.relation_kind in FORBIDDEN_RELATION_KINDS:
            raise ProgramIdentityError(
                "similarity/nearest-neighbor is not a semantic relation kind"
            )
        object.__setattr__(
            self, "relation_kind", _enum(self.relation_kind, RelationKind, "relation_kind")
        )
        object.__setattr__(self, "left_cid", _cid(self.left_cid, "left_cid"))
        object.__setattr__(self, "right_cid", _cid(self.right_cid, "right_cid"))
        object.__setattr__(self, "scope_cid", _cid(self.scope_cid, "scope_cid"))
        object.__setattr__(
            self, "theory_or_policy_cid", _cid(self.theory_or_policy_cid, "theory_or_policy_cid")
        )
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self,
            "authority_status",
            _enum(self.authority_status, RelationAuthorityStatus, "authority_status"),
        )
        object.__setattr__(
            self, "assumption_cids", _unique_sorted_cids(self.assumption_cids, "assumption_cid")
        )
        object.__setattr__(
            self, "evidence_cids", _unique_sorted_cids(self.evidence_cids, "evidence_cid")
        )
        object.__setattr__(
            self,
            "invalidator_cids",
            _unique_sorted_cids(self.invalidator_cids, "invalidator_cid"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "relation_kind": self.relation_kind,
            "left_cid": self.left_cid,
            "right_cid": self.right_cid,
            "scope_cid": self.scope_cid,
            "assumption_cids": list(self.assumption_cids),
            "theory_or_policy_cid": self.theory_or_policy_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "evidence_cids": list(self.evidence_cids),
            "invalidator_cids": list(self.invalidator_cids),
            "authority_status": self.authority_status,
        }

    @property
    def relation_claim_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["relation_claim_cid"] = self.relation_claim_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RelationClaimIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("relation_claim_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError(
                "unsupported RelationClaimIdentity schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class TransitionIdentity:
    """Query, proposal-only prediction, observation, admission, or accepted transition."""

    transition_kind: TransitionKind | str
    subject_cid: str
    evidence_cids: Sequence[str] = ()
    environment_binding_cid: str | None = None
    policy_cid: str | None = None
    model_profile_cid: str | None = None
    proposal_only: bool = False
    observation_status: ObservationStatus | str | None = None

    SCHEMA: ClassVar[str] = TRANSITION_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "transition_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "transition_kind",
            "subject_cid",
            "evidence_cids",
            "environment_binding_cid",
            "policy_cid",
            "model_profile_cid",
            "proposal_only",
            "observation_status",
            "transition_cid",
        }
    )

    def __post_init__(self) -> None:
        kind = _enum(self.transition_kind, TransitionKind, "transition_kind")
        object.__setattr__(self, "transition_kind", kind)
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(
            self, "evidence_cids", _unique_sorted_cids(self.evidence_cids, "evidence_cid")
        )
        object.__setattr__(
            self,
            "environment_binding_cid",
            _optional_cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid"))
        object.__setattr__(
            self, "model_profile_cid", _optional_cid(self.model_profile_cid, "model_profile_cid")
        )
        object.__setattr__(self, "proposal_only", _bool(self.proposal_only, "proposal_only"))
        status = self.observation_status
        if status is not None:
            status = _enum(status, ObservationStatus, "observation_status")
        object.__setattr__(self, "observation_status", status)
        if kind == TransitionKind.PREDICTION.value:
            if not self.proposal_only:
                raise ProgramIdentityError("predictions are proposal-only")
            if self.model_profile_cid is None:
                raise ProgramIdentityError("predictions require model_profile_cid")
        else:
            if self.proposal_only:
                raise ProgramIdentityError(
                    f"{kind} transitions cannot be proposal-only"
                )
            if kind != TransitionKind.QUERY.value and self.model_profile_cid is not None:
                raise ProgramIdentityError(
                    "model_profile_cid is only admitted on predictions"
                )
        if kind == TransitionKind.OBSERVATION.value and self.observation_status is None:
            raise ProgramIdentityError("observations require observation_status")
        if kind == TransitionKind.ADMISSION.value and self.policy_cid is None:
            raise ProgramIdentityError("admissions require policy_cid")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "transition_kind": self.transition_kind,
            "subject_cid": self.subject_cid,
            "evidence_cids": list(self.evidence_cids),
            "environment_binding_cid": self.environment_binding_cid,
            "policy_cid": self.policy_cid,
            "model_profile_cid": self.model_profile_cid,
            "proposal_only": self.proposal_only,
            "observation_status": self.observation_status,
        }

    @property
    def transition_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["transition_cid"] = self.transition_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransitionIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("transition_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError("unsupported TransitionIdentity schema version")
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class SemanticWorldRootIdentity:
    """Datasets semantic world identity; excludes projections and operational CAS."""

    domain_state_cid: str
    canonical_program_graph_cid: str
    program_graph_snapshot_cid: str
    semantic_object_index_cid: str
    environment_binding_set_cid: str
    policy_cid: str
    analysis_limitation_index_cid: str

    SCHEMA: ClassVar[str] = SEMANTIC_WORLD_ROOT_IDENTITY_SCHEMA
    CID_FIELD: ClassVar[str] = "semantic_world_root_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "domain_state_cid",
            "canonical_program_graph_cid",
            "program_graph_snapshot_cid",
            "semantic_object_index_cid",
            "environment_binding_set_cid",
            "policy_cid",
            "analysis_limitation_index_cid",
            "semantic_world_root_cid",
        }
    )

    def __post_init__(self) -> None:
        for name in (
            "domain_state_cid",
            "canonical_program_graph_cid",
            "program_graph_snapshot_cid",
            "semantic_object_index_cid",
            "environment_binding_set_cid",
            "policy_cid",
            "analysis_limitation_index_cid",
        ):
            object.__setattr__(self, name, _cid(getattr(self, name), name))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "domain_state_cid": self.domain_state_cid,
            "canonical_program_graph_cid": self.canonical_program_graph_cid,
            "program_graph_snapshot_cid": self.program_graph_snapshot_cid,
            "semantic_object_index_cid": self.semantic_object_index_cid,
            "environment_binding_set_cid": self.environment_binding_set_cid,
            "policy_cid": self.policy_cid,
            "analysis_limitation_index_cid": self.analysis_limitation_index_cid,
        }

    @property
    def semantic_world_root_cid(self) -> str:
        return identity_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_identity_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["semantic_world_root_cid"] = self.semantic_world_root_cid
        forbidden = SEMANTIC_IDENTITY_EXCLUDED_FIELDS.intersection(value)
        if forbidden:
            raise ProgramIdentityError(
                f"SemanticWorldRootIdentity must not contain excluded fields {sorted(forbidden)}"
            )
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticWorldRootIdentity":
        if not isinstance(data, Mapping):
            raise ProgramIdentityError("SemanticWorldRootIdentity must be a mapping")
        forbidden = SEMANTIC_IDENTITY_EXCLUDED_FIELDS.intersection(data)
        if forbidden:
            raise ProgramIdentityError(
                f"SemanticWorldRootIdentity rejects excluded fields {sorted(forbidden)}"
            )
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("semantic_world_root_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise ProgramIdentityError(
                "unsupported SemanticWorldRootIdentity schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


IDENTITY_RECORD_TYPES: Final[tuple[type, ...]] = (
    ProgramWorldCanonicalizationProfile,
    SemanticObjectEnvelope,
    CanonicalProgramGraphIdentity,
    ProgramGraphSnapshotIdentity,
    ProgramGraphDeltaIdentity,
    RawExecutionStateIdentity,
    StateAbstractionProfileIdentity,
    AbstractExecutionStateIdentity,
    StackFrameIdentity,
    ProgramEventIdentity,
    ExecutionTraceIdentity,
    ProjectionIdentity,
    ProjectionIndexManifestIdentity,
    RelationClaimIdentity,
    TransitionIdentity,
    SemanticWorldRootIdentity,
)

_SCHEMA_TO_CLASS: Final[dict[str, type]] = {
    cls.SCHEMA: cls for cls in IDENTITY_RECORD_TYPES
}


def decode_identity_record(data: Mapping[str, Any]) -> Any:
    """Dispatch one closed identity payload to its versioned record type."""

    if not isinstance(data, Mapping):
        raise ProgramIdentityError("identity record must be a mapping")
    schema = data.get("schema")
    record_type = _SCHEMA_TO_CLASS.get(schema) if type(schema) is str else None
    if record_type is None:
        raise ProgramIdentityError(f"unsupported identity schema {schema!r}")
    return record_type.from_dict(data)


def load_payload_schema() -> dict[str, Any]:
    """Load the packaged JSON Schema for program-identity payloads."""

    from pathlib import Path

    path = Path(__file__).resolve().parent / "schemas" / "program-identity.payload.schema.json"
    return loads_identity_json(path.read_text(encoding="utf-8"))


__all__ = [
    "ABSTRACT_EXECUTION_STATE_IDENTITY_SCHEMA",
    "ADMITTED_LANGUAGES",
    "CANONICAL_PROGRAM_GRAPH_IDENTITY_SCHEMA",
    "COLLECTION_SEMANTICS_DECLARATION",
    "EXECUTION_TRACE_IDENTITY_SCHEMA",
    "PROGRAM_EVENT_IDENTITY_SCHEMA",
    "PROGRAM_WORLD_CANONICALIZATION_PROFILE_ID",
    "PROGRAM_WORLD_CANONICALIZATION_PROFILE_INTERFACE",
    "PROGRAM_WORLD_CANONICALIZATION_PROFILE_SCHEMA",
    "PROJECTION_IDENTITY_INTERFACE",
    "PROJECTION_IDENTITY_SCHEMA",
    "PROJECTION_REQUIRED_FIELDS",
    "RAW_EXECUTION_STATE_IDENTITY_SCHEMA",
    "SEMANTIC_IDENTITY_EXCLUDED_FIELDS",
    "SEMANTIC_OBJECT_ENVELOPE_INTERFACE",
    "SEMANTIC_OBJECT_ENVELOPE_SCHEMA",
    "SEMANTIC_WORLD_ROOT_IDENTITY_SCHEMA",
    "UNAVAILABLE_LANGUAGES",
    "AbstractExecutionStateIdentity",
    "AbstractionSoundnessClaim",
    "AvailabilityPolicy",
    "ByteOrder",
    "CanonicalProgramGraphIdentity",
    "EventKind",
    "ExecutionTraceIdentity",
    "ObservationStatus",
    "PrivacyClass",
    "ProgramEventIdentity",
    "ProgramGraphDeltaIdentity",
    "ProgramGraphKind",
    "ProgramGraphSnapshotIdentity",
    "ProgramIdentityError",
    "ProgramLanguage",
    "ProgramWorldCanonicalizationProfile",
    "ProjectionDType",
    "ProjectionIdentity",
    "ProjectionIndexManifestIdentity",
    "ProjectionKind",
    "ProjectionMetric",
    "ProjectionSubjectKind",
    "RawExecutionStateIdentity",
    "RelationAuthorityStatus",
    "RelationClaimIdentity",
    "RelationKind",
    "SemanticObjectEnvelope",
    "SemanticObjectKind",
    "SemanticWorldRootIdentity",
    "StackFrameIdentity",
    "StateAbstractionProfileIdentity",
    "TransitionIdentity",
    "TransitionKind",
    "canonical_identity_bytes",
    "canonicalize_identity_value",
    "decode_identity_record",
    "identity_cid_for",
    "load_payload_schema",
    "loads_identity_json",
    "program_world_profile",
    "projection_from_bindings",
    "semantic_object_from_declaration",
    "strip_non_semantic_fields",
]
