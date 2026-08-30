"""Closed proposal-only program-transition contracts and admission.

This module owns the datasets ``ProgramTransitionQuery@1``,
``ProgramTransitionPrediction@1``, ``ProgramTransitionObservation@1``,
``ProgramTransitionAdmission@1``, and ``RepairOperator@1`` family, together
with candidate, receipt, model-profile, calibration, graph-delta proposal,
and patch-sketch records.

Authority rules (normative):

* Contracts describe proposals and evidence.  They do not implement
  prediction, execution, proof validation, operational acceptance, or
  durable storage.  Operational admission remains accelerator-owned.
* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
  Collection-semantics declarations reuse ``ir_core.canonical``.
* Predictions cannot prove contracts or postconditions, authorize mutation,
  suppress validation or review, establish equivalence, observation, or
  completion, or invent hashes.  Model output may only select or
  parameterize a bounded candidate from a current query universe.
* Predictions and observations are disjoint types.  A prediction cannot
  decode as an observation and cannot self-admit.
* Candidates must bind the current subject, source, environment, and
  family-required graph/state/trace CIDs.  Stale current CIDs fail closed.
* Calibration drift is an integer rational comparison.  Drifted or
  uncalibrated profiles cannot influence admission.
* Existing software-contract ``@1`` identity payloads are not modified.
  Query, prediction, observation, and admission records may project into
  the landed ``TransitionIdentity@1`` envelope.
* Records are recursively immutable, closed to unknown fields, and
  restricted to strict DAG-JSON types.  Unsupported languages remain
  typed unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
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

PROGRAM_TRANSITION_QUERY_INTERFACE: Final[str] = "ProgramTransitionQuery@1"
PROGRAM_TRANSITION_PREDICTION_INTERFACE: Final[str] = "ProgramTransitionPrediction@1"
PROGRAM_TRANSITION_OBSERVATION_INTERFACE: Final[str] = "ProgramTransitionObservation@1"
PROGRAM_TRANSITION_ADMISSION_INTERFACE: Final[str] = "ProgramTransitionAdmission@1"
REPAIR_OPERATOR_INTERFACE: Final[str] = "RepairOperator@1"
PROGRAM_TRANSITION_CANDIDATE_INTERFACE: Final[str] = "ProgramTransitionCandidate@1"
PROGRAM_TRANSITION_RECEIPT_INTERFACE: Final[str] = "ProgramTransitionReceipt@1"
TRANSITION_MODEL_PROFILE_INTERFACE: Final[str] = "TransitionModelProfile@1"
TRANSITION_CALIBRATION_INTERFACE: Final[str] = "TransitionCalibration@1"
PROGRAM_GRAPH_DELTA_PROPOSAL_INTERFACE: Final[str] = "ProgramGraphDeltaProposal@1"
PATCH_SKETCH_IR_INTERFACE: Final[str] = "PatchSketchIR@1"

PROGRAM_TRANSITION_QUERY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-transition-query@1"
)
PROGRAM_TRANSITION_CANDIDATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-transition-candidate@1"
)
PROGRAM_TRANSITION_PREDICTION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-transition-prediction@1"
)
PROGRAM_TRANSITION_OBSERVATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-transition-observation@1"
)
PROGRAM_TRANSITION_ADMISSION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-transition-admission@1"
)
PROGRAM_TRANSITION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-transition-receipt@1"
)
TRANSITION_MODEL_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.transition-model-profile@1"
)
TRANSITION_CALIBRATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.transition-calibration@1"
)
REPAIR_OPERATOR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.repair-operator@1"
)
PROGRAM_GRAPH_DELTA_PROPOSAL_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-graph-delta-proposal@1"
)
PATCH_SKETCH_IR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.patch-sketch-ir@1"
)
TRANSITION_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.transition-identity@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_COLLECTION_ITEMS: Final[int] = 100_000
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
MAX_METADATA_BYTES: Final[int] = 16_384
MAX_CANDIDATES: Final[int] = 256
MAX_SKETCH_STEPS: Final[int] = 32

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
    "/allowed_operator_cids": CollectionSemantics.SET_LIKE.value,
    "/allowed_symbol_cids": CollectionSemantics.SET_LIKE.value,
    "/candidate_cids": CollectionSemantics.ORDERED.value,
    "/evidence_cids": CollectionSemantics.SET_LIKE.value,
    "/hole_cids": CollectionSemantics.ORDERED.value,
    "/limitation_cids": CollectionSemantics.SET_LIKE.value,
    "/operator_cids": CollectionSemantics.ORDERED.value,
    "/parameter_cids": CollectionSemantics.SET_LIKE.value,
    "/unavailable_dimensions": CollectionSemantics.SET_LIKE.value,
    "/validation_evidence_cids": CollectionSemantics.SET_LIKE.value,
    "/added_edge_cids": CollectionSemantics.SET_LIKE.value,
    "/added_node_cids": CollectionSemantics.SET_LIKE.value,
    "/removed_edge_cids": CollectionSemantics.SET_LIKE.value,
    "/removed_node_cids": CollectionSemantics.SET_LIKE.value,
    "/retained_subroot_cids": CollectionSemantics.SET_LIKE.value,
}

FORBIDDEN_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "ann_score",
        "api_key",
        "authorization",
        "completed",
        "completion",
        "content_hash",
        "cookie",
        "credential",
        "distance",
        "embedding",
        "embedding_score",
        "embeddings",
        "fabricated_cid",
        "invented_hash",
        "knn",
        "md5",
        "mutation_authorized",
        "nearest",
        "password",
        "predicted_hash",
        "private_key",
        "rank_score",
        "score",
        "scores",
        "secret",
        "sha256",
        "similarity",
        "timestamp",
        "vector",
        "vector_cid",
        "vectors",
        "wall_clock",
    }
)

HASH_INVENTION_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "blake2",
        "blake2b",
        "content_hash",
        "fabricated_cid",
        "invented_hash",
        "md5",
        "predicted_hash",
        "sha1",
        "sha256",
        "sha512",
    }
)

FORBIDDEN_QUERY_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "embedding_repair",
        "knn_next",
        "nearest_call",
        "similar_call",
        "similarity",
        "vector_next_event",
    }
)

QUERY_FAMILY_CANDIDATE_KINDS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "next_call": frozenset({"call_target"}),
        "next_event": frozenset({"next_event", "next_state"}),
        "inverse_trace": frozenset({"inverse_event", "inverse_trace"}),
        "repair": frozenset({"repair_operator", "graph_delta", "patch_sketch"}),
    }
)

FAMILY_REQUIRED_CURRENT: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "next_call": ("current_state_cid",),
        "next_event": ("current_state_cid",),
        "inverse_trace": ("current_trace_cid",),
        "repair": ("current_graph_cid",),
    }
)

PREDICTION_AUTHORITY_FLAGS: Final[tuple[str, ...]] = (
    "proves_contract",
    "proves_postcondition",
    "authorizes_mutation",
    "suppresses_validation",
    "suppresses_review",
    "establishes_equivalence",
    "establishes_observation",
    "establishes_completion",
    "invents_hashes",
    "proves_impossibility",
    "self_admitted",
    "authoritative",
    "prediction_authoritative",
)


class ProgramTransitionError(ValueError):
    """Raised when a program-transition payload or admission step is malformed."""


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


class CandidateKind(str, Enum):
    CALL_TARGET = "call_target"
    NEXT_EVENT = "next_event"
    NEXT_STATE = "next_state"
    INVERSE_EVENT = "inverse_event"
    INVERSE_TRACE = "inverse_trace"
    REPAIR_OPERATOR = "repair_operator"
    GRAPH_DELTA = "graph_delta"
    PATCH_SKETCH = "patch_sketch"


class RepairOperatorKind(str, Enum):
    REPLACE_CALL_TARGET = "replace_call_target"
    INSERT_GUARD = "insert_guard"
    WRAP_HANDLER = "wrap_handler"
    STRENGTHEN_PRECONDITION = "strengthen_precondition"
    WEAKEN_POSTCONDITION = "weaken_postcondition"
    REWRITE_ASSIGNMENT = "rewrite_assignment"
    DELETE_DEAD_CODE = "delete_dead_code"
    NORMALIZE_EGRAPH = "normalize_egraph"
    BOUNDED_CEGIS = "bounded_cegis"
    NO_OP = "no_op"


class ObservationStatus(str, Enum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    REDACTED = "redacted"
    INFERRED_UNTRUSTED = "inferred_untrusted"


class AdmissionVerdict(str, Enum):
    ADMITTED = "admitted"
    REJECTED = "rejected"
    ABSTAIN = "abstain"
    CONFLICT = "conflict"
    STALE = "stale"
    UNKNOWN = "unknown"


class CalibrationStatus(str, Enum):
    CALIBRATED = "calibrated"
    DRIFTED = "drifted"
    UNCALIBRATED = "uncalibrated"
    UNAVAILABLE = "unavailable"


class SpecialistFamily(str, Enum):
    CALL_TARGET = "call_target"
    NEXT_EVENT = "next_event"
    INVERSE_TRACE = "inverse_trace"
    REPAIR = "repair"


class SketchKind(str, Enum):
    REPAIR = "repair"
    DELTA = "delta"
    CALL_TARGET = "call_target"


QUERY_FAMILIES: Final[frozenset[str]] = frozenset(item.value for item in QueryFamily)
REPAIR_OPERATOR_KINDS: Final[frozenset[str]] = frozenset(
    item.value for item in RepairOperatorKind
)
CANDIDATE_KINDS: Final[frozenset[str]] = frozenset(item.value for item in CandidateKind)
ADMISSION_VERDICTS: Final[frozenset[str]] = frozenset(
    item.value for item in AdmissionVerdict
)
CALIBRATION_STATUSES: Final[frozenset[str]] = frozenset(
    item.value for item in CalibrationStatus
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise ProgramTransitionError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ProgramTransitionError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise ProgramTransitionError(f"{name} contains invalid text")
    return value


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise ProgramTransitionError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ProgramTransitionError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ProgramTransitionError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ProgramTransitionError(f"{name} must be a nonnegative integer")
    if value > MAX_SAFE_INTEGER:
        raise ProgramTransitionError(f"{name} exceeds the safe JSON integer range")
    return value


def _positive_int(value: Any, name: str, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1 or value > maximum:
        raise ProgramTransitionError(f"{name} must be an integer in 1..{maximum}")
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
    invented = keys & HASH_INVENTION_MARKERS
    if invented:
        raise ProgramTransitionError(
            f"{name} rejects invented-hash fields {sorted(invented)}"
        )
    forbidden = keys & FORBIDDEN_FIELD_MARKERS
    if forbidden:
        raise ProgramTransitionError(
            f"{name} rejects non-semantic fields {sorted(forbidden)}"
        )


def _walk_reject_invented_hashes(value: Any, name: str) -> None:
    if isinstance(value, Mapping):
        _reject_forbidden_keys(value, name)
        for key, item in value.items():
            marker = str(key).strip().lower().replace("-", "_")
            if marker in HASH_INVENTION_MARKERS or marker in FORBIDDEN_FIELD_MARKERS:
                raise ProgramTransitionError(
                    f"{name} rejects invented-hash field {key!r}"
                )
            _walk_reject_invented_hashes(item, f"{name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk_reject_invented_hashes(item, f"{name}[{index}]")


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ProgramTransitionError(f"{name} must be a mapping")
    result = _thaw_structured(dict(value))
    _walk_reject_invented_hashes(result, name)
    try:
        validate_structured_value(result)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramTransitionError(f"{name} must be strict DAG-JSON") from exc
    encoded = canonical_dag_json_bytes(result)
    if len(encoded) > MAX_METADATA_BYTES:
        raise ProgramTransitionError(f"{name} exceeds its byte bound")
    return _freeze_structured(result) if frozen else result


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ProgramTransitionError(f"{name} must be a mapping")
    invented = set(data) & HASH_INVENTION_MARKERS
    if invented:
        raise ProgramTransitionError(
            f"{name} rejects invented-hash fields {sorted(invented)}"
        )
    forbidden = set(data) & FORBIDDEN_FIELD_MARKERS
    if forbidden:
        raise ProgramTransitionError(
            f"{name} rejects non-semantic fields {sorted(forbidden)}"
        )
    extra = set(data) - fields
    missing = fields - set(data)
    if extra:
        raise ProgramTransitionError(f"{name} rejects unknown fields {sorted(extra)}")
    if missing:
        raise ProgramTransitionError(f"{name} missing fields {sorted(missing)}")
    return dict(data)


def _unique_sorted_texts(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = [_text(value, name) for value in values]
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramTransitionError(f"{name} exceeds its item bound")
    ordered = tuple(sorted(items))
    if len(ordered) != len(set(ordered)):
        raise ProgramTransitionError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = [_cid(value, name) for value in values]
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ProgramTransitionError(f"{name} exceeds its item bound")
    ordered = tuple(sorted(items))
    if len(ordered) != len(set(ordered)):
        raise ProgramTransitionError(f"{name} must not contain duplicates")
    return ordered


def _ordered_cids(values: Iterable[Any], name: str, *, maximum: int | None = None) -> tuple[str, ...]:
    items = tuple(_cid(value, name) for value in values)
    bound = MAX_COLLECTION_ITEMS if maximum is None else maximum
    if len(items) > bound:
        raise ProgramTransitionError(f"{name} exceeds its item bound")
    return items


def _language(value: Any, name: str = "language") -> str:
    language = _enum(value, ProgramLanguage, name)
    if language not in ADMITTED_LANGUAGES:
        raise ProgramTransitionError(
            f"{name} {language!r} is typed unavailable in this profile"
        )
    return language


def _query_family(value: Any, name: str = "query_family") -> str:
    if type(value) is str:
        marker = value.strip().lower().replace("-", "_").replace(" ", "_")
        if marker in FORBIDDEN_QUERY_FAMILIES:
            raise ProgramTransitionError(
                "similarity/nearest-neighbor is not a program-transition query family"
            )
    return _enum(value, QueryFamily, name)


def _false_flag(value: Any, name: str) -> bool:
    flag = _bool(value, name)
    if flag:
        raise ProgramTransitionError(
            f"predictions cannot set {name}; model output is proposal-only"
        )
    return False


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


def canonicalize_transition_value(value: Any) -> Any:
    """NFC-normalize, apply declared collection semantics, and reject floats."""

    try:
        validate_structured_value(value)
    except (StructuredIdentityError, TypeError, ValueError) as exc:
        raise ProgramTransitionError(
            "transition value must be strict DAG-JSON"
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
        raise ProgramTransitionError(
            "canonical transition value must be strict DAG-JSON"
        ) from exc
    content_bytes = canonical_dag_json_bytes(canonical)
    try:
        ir_bytes = ir_canonical_json_bytes(
            canonical,
            collection_schema=CollectionSchema(None, require_declared=False),
        )
    except CanonicalizationError as exc:
        raise ProgramTransitionError(
            "ir_core rejected the canonical transition value"
        ) from exc
    if ir_bytes != content_bytes:
        raise ProgramTransitionError(
            "ir_core canonical JSON diverged from software-contract DAG-JSON"
        )
    return canonical


def transition_cid_for(payload: Mapping[str, Any]) -> str:
    """Return the structured CID of one canonical transition payload."""

    return cid_for_structured(canonicalize_transition_value(payload))


def canonical_transition_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return canonical DAG-JSON bytes of one transition payload."""

    return canonical_dag_json_bytes(canonicalize_transition_value(payload))


def _verify_claimed(name: str, claimed: Any, payload: Mapping[str, Any]) -> str:
    canonical = canonicalize_transition_value(payload)
    try:
        return decode_and_recompute_structured(claimed, canonical)
    except Exception as exc:
        raise ProgramTransitionError(f"{name} cid does not verify") from exc


def _reject_nonfinite_constant(token: str) -> None:
    raise ProgramTransitionError(f"nonfinite JSON number {token!r} is rejected")


def _parse_int(token: str) -> int:
    try:
        value = int(token, 10)
    except ValueError as exc:
        raise ProgramTransitionError(f"JSON number {token!r} is not an integer") from exc
    if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
        raise ProgramTransitionError("integer is outside the safe JSON range")
    return value


def _parse_float(token: str) -> None:
    raise ProgramTransitionError(
        f"JSON number {token!r} is not a finite integer; floats are rejected"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProgramTransitionError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def loads_transition_json(text: str | bytes) -> Any:
    """Decode JSON text, rejecting duplicate keys, NaN, and floats."""

    if type(text) is bytes:
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProgramTransitionError("transition JSON must be UTF-8") from exc
    if type(text) is not str:
        raise ProgramTransitionError("transition JSON must be text or UTF-8 bytes")
    try:
        return json.loads(
            text,
            parse_int=_parse_int,
            parse_float=_parse_float,
            parse_constant=_reject_nonfinite_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ProgramTransitionError:
        raise
    except json.JSONDecodeError as exc:
        raise ProgramTransitionError("transition JSON is not well-formed") from exc


def _from_closed(cls: type[Any], data: Mapping[str, Any]) -> Any:
    payload = _closed(data, cls._FIELDS, cls.__name__)
    claimed = payload.pop(cls.CID_FIELD)
    if payload.pop("schema") != cls.SCHEMA:
        raise ProgramTransitionError(f"unsupported {cls.__name__} schema version")
    result = cls(**payload)
    _verify_claimed(cls.__name__, claimed, result.identity_payload())
    return result


def _require_current_match(name: str, bound: str | None, current: str | None) -> None:
    if bound != current:
        raise ProgramTransitionError(
            f"{name} is not the current CID bound by the query"
        )


def _identity_transition(
    *,
    transition_kind: str,
    subject_cid: str,
    evidence_cids: Sequence[str] = (),
    environment_binding_cid: str | None = None,
    policy_cid: str | None = None,
    model_profile_cid: str | None = None,
    proposal_only: bool = False,
    observation_status: str | None = None,
) -> dict[str, Any]:
    from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
        TransitionIdentity,
    )

    identity = TransitionIdentity(
        transition_kind=transition_kind,
        subject_cid=subject_cid,
        evidence_cids=evidence_cids,
        environment_binding_cid=environment_binding_cid,
        policy_cid=policy_cid,
        model_profile_cid=model_profile_cid,
        proposal_only=proposal_only,
        observation_status=observation_status,
    )
    return identity.to_dict()


def _computed_calibration_status(
    *,
    trial_count: int,
    disagreement_count: int,
    bound_numerator: int,
    bound_denominator: int,
    expected_observation_cid: str | None,
    actual_observation_cid: str | None,
) -> str:
    if trial_count == 0 or expected_observation_cid is None:
        return CalibrationStatus.UNCALIBRATED.value
    if actual_observation_cid is None and disagreement_count == 0:
        return CalibrationStatus.UNCALIBRATED.value
    if disagreement_count * bound_denominator > bound_numerator * trial_count:
        return CalibrationStatus.DRIFTED.value
    return CalibrationStatus.CALIBRATED.value


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransitionModelProfile:
    """Pinned specialist profile; predictions remain proposal-only."""

    profile_name: str
    specialist_family: SpecialistFamily | str
    model_cid: str
    tokenizer_cid: str
    preprocessing_profile_cid: str
    abstain_on_ood: bool = True
    proposal_only: bool = True
    authoritative: bool = False

    SCHEMA: ClassVar[str] = TRANSITION_MODEL_PROFILE_SCHEMA
    INTERFACE: ClassVar[str] = TRANSITION_MODEL_PROFILE_INTERFACE
    CID_FIELD: ClassVar[str] = "model_profile_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "profile_name",
            "specialist_family",
            "model_cid",
            "tokenizer_cid",
            "preprocessing_profile_cid",
            "abstain_on_ood",
            "proposal_only",
            "authoritative",
            "model_profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_name", _text(self.profile_name, "profile_name"))
        object.__setattr__(
            self,
            "specialist_family",
            _enum(self.specialist_family, SpecialistFamily, "specialist_family"),
        )
        object.__setattr__(self, "model_cid", _cid(self.model_cid, "model_cid"))
        object.__setattr__(self, "tokenizer_cid", _cid(self.tokenizer_cid, "tokenizer_cid"))
        object.__setattr__(
            self,
            "preprocessing_profile_cid",
            _cid(self.preprocessing_profile_cid, "preprocessing_profile_cid"),
        )
        object.__setattr__(
            self, "abstain_on_ood", _bool(self.abstain_on_ood, "abstain_on_ood")
        )
        object.__setattr__(
            self, "proposal_only", _bool(self.proposal_only, "proposal_only")
        )
        object.__setattr__(
            self, "authoritative", _bool(self.authoritative, "authoritative")
        )
        if not self.proposal_only:
            raise ProgramTransitionError("model profiles are proposal-only")
        if self.authoritative:
            raise ProgramTransitionError("model profiles cannot be authoritative")
        if not self.abstain_on_ood:
            raise ProgramTransitionError("specialists must abstain on out-of-distribution inputs")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "profile_name": self.profile_name,
            "specialist_family": self.specialist_family,
            "model_cid": self.model_cid,
            "tokenizer_cid": self.tokenizer_cid,
            "preprocessing_profile_cid": self.preprocessing_profile_cid,
            "abstain_on_ood": self.abstain_on_ood,
            "proposal_only": self.proposal_only,
            "authoritative": self.authoritative,
        }

    @property
    def model_profile_cid(self) -> str:
        return transition_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_transition_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["model_profile_cid"] = self.model_profile_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransitionModelProfile":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class TransitionCalibration:
    """Integer-rational calibration; drift cannot grant admission."""

    model_profile_cid: str
    query_family: QueryFamily | str
    trial_count: int
    disagreement_count: int
    bound_numerator: int
    bound_denominator: int
    expected_observation_cid: str | None = None
    actual_observation_cid: str | None = None
    status: CalibrationStatus | str | None = None

    SCHEMA: ClassVar[str] = TRANSITION_CALIBRATION_SCHEMA
    INTERFACE: ClassVar[str] = TRANSITION_CALIBRATION_INTERFACE
    CID_FIELD: ClassVar[str] = "calibration_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "model_profile_cid",
            "query_family",
            "trial_count",
            "disagreement_count",
            "bound_numerator",
            "bound_denominator",
            "expected_observation_cid",
            "actual_observation_cid",
            "status",
            "calibration_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "model_profile_cid", _cid(self.model_profile_cid, "model_profile_cid")
        )
        object.__setattr__(self, "query_family", _query_family(self.query_family))
        object.__setattr__(self, "trial_count", _nonneg_int(self.trial_count, "trial_count"))
        object.__setattr__(
            self,
            "disagreement_count",
            _nonneg_int(self.disagreement_count, "disagreement_count"),
        )
        object.__setattr__(
            self, "bound_numerator", _nonneg_int(self.bound_numerator, "bound_numerator")
        )
        object.__setattr__(
            self,
            "bound_denominator",
            _positive_int(self.bound_denominator, "bound_denominator", MAX_SAFE_INTEGER),
        )
        object.__setattr__(
            self,
            "expected_observation_cid",
            _optional_cid(self.expected_observation_cid, "expected_observation_cid"),
        )
        object.__setattr__(
            self,
            "actual_observation_cid",
            _optional_cid(self.actual_observation_cid, "actual_observation_cid"),
        )
        if self.disagreement_count > self.trial_count:
            raise ProgramTransitionError("disagreement_count cannot exceed trial_count")
        computed = _computed_calibration_status(
            trial_count=self.trial_count,
            disagreement_count=self.disagreement_count,
            bound_numerator=self.bound_numerator,
            bound_denominator=self.bound_denominator,
            expected_observation_cid=self.expected_observation_cid,
            actual_observation_cid=self.actual_observation_cid,
        )
        if self.status is None:
            object.__setattr__(self, "status", computed)
        else:
            claimed = _enum(self.status, CalibrationStatus, "status")
            if claimed != computed:
                raise ProgramTransitionError(
                    f"calibration status {claimed!r} does not match computed {computed!r}"
                )
            object.__setattr__(self, "status", claimed)

    @property
    def drifted(self) -> bool:
        return self.status == CalibrationStatus.DRIFTED.value

    @property
    def may_propose(self) -> bool:
        return self.status == CalibrationStatus.CALIBRATED.value

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "model_profile_cid": self.model_profile_cid,
            "query_family": self.query_family,
            "trial_count": self.trial_count,
            "disagreement_count": self.disagreement_count,
            "bound_numerator": self.bound_numerator,
            "bound_denominator": self.bound_denominator,
            "expected_observation_cid": self.expected_observation_cid,
            "actual_observation_cid": self.actual_observation_cid,
            "status": self.status,
        }

    @property
    def calibration_cid(self) -> str:
        return transition_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_transition_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["calibration_cid"] = self.calibration_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransitionCalibration":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class RepairOperator:
    """Bounded repair operator; never an authorized mutation."""

    operator_kind: RepairOperatorKind | str
    language: ProgramLanguage | str
    target_symbol_cid: str
    parameter_cids: Sequence[str] = ()
    pre_state_cid: str | None = None
    proposal_only: bool = True
    authorizes_mutation: bool = False
    bounded: bool = True

    SCHEMA: ClassVar[str] = REPAIR_OPERATOR_SCHEMA
    INTERFACE: ClassVar[str] = REPAIR_OPERATOR_INTERFACE
    CID_FIELD: ClassVar[str] = "repair_operator_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "operator_kind",
            "language",
            "target_symbol_cid",
            "parameter_cids",
            "pre_state_cid",
            "proposal_only",
            "authorizes_mutation",
            "bounded",
            "repair_operator_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operator_kind",
            _enum(self.operator_kind, RepairOperatorKind, "operator_kind"),
        )
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self, "target_symbol_cid", _cid(self.target_symbol_cid, "target_symbol_cid")
        )
        object.__setattr__(
            self,
            "parameter_cids",
            _unique_sorted_cids(self.parameter_cids, "parameter_cid"),
        )
        object.__setattr__(
            self, "pre_state_cid", _optional_cid(self.pre_state_cid, "pre_state_cid")
        )
        object.__setattr__(
            self, "proposal_only", _bool(self.proposal_only, "proposal_only")
        )
        object.__setattr__(
            self,
            "authorizes_mutation",
            _bool(self.authorizes_mutation, "authorizes_mutation"),
        )
        object.__setattr__(self, "bounded", _bool(self.bounded, "bounded"))
        if not self.proposal_only:
            raise ProgramTransitionError("repair operators are proposal-only")
        if self.authorizes_mutation:
            raise ProgramTransitionError("repair operators cannot authorize mutation")
        if not self.bounded:
            raise ProgramTransitionError("repair operators must remain bounded")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "operator_kind": self.operator_kind,
            "language": self.language,
            "target_symbol_cid": self.target_symbol_cid,
            "parameter_cids": list(self.parameter_cids),
            "pre_state_cid": self.pre_state_cid,
            "proposal_only": self.proposal_only,
            "authorizes_mutation": self.authorizes_mutation,
            "bounded": self.bounded,
        }

    @property
    def repair_operator_cid(self) -> str:
        return transition_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_transition_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["repair_operator_cid"] = self.repair_operator_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RepairOperator":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramGraphDeltaProposal:
    """Proposal-only graph delta; not an accepted ``ProgramGraphDelta@1``."""

    previous_snapshot_cid: str
    query_cid: str
    candidate_cid: str
    added_node_cids: Sequence[str] = ()
    removed_node_cids: Sequence[str] = ()
    added_edge_cids: Sequence[str] = ()
    removed_edge_cids: Sequence[str] = ()
    retained_subroot_cids: Sequence[str] = ()
    proposal_only: bool = True
    authorizes_mutation: bool = False

    SCHEMA: ClassVar[str] = PROGRAM_GRAPH_DELTA_PROPOSAL_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_GRAPH_DELTA_PROPOSAL_INTERFACE
    CID_FIELD: ClassVar[str] = "program_graph_delta_proposal_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "previous_snapshot_cid",
            "query_cid",
            "candidate_cid",
            "added_node_cids",
            "removed_node_cids",
            "added_edge_cids",
            "removed_edge_cids",
            "retained_subroot_cids",
            "proposal_only",
            "authorizes_mutation",
            "program_graph_delta_proposal_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "previous_snapshot_cid",
            _cid(self.previous_snapshot_cid, "previous_snapshot_cid"),
        )
        object.__setattr__(self, "query_cid", _cid(self.query_cid, "query_cid"))
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
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
        object.__setattr__(
            self, "proposal_only", _bool(self.proposal_only, "proposal_only")
        )
        object.__setattr__(
            self,
            "authorizes_mutation",
            _bool(self.authorizes_mutation, "authorizes_mutation"),
        )
        if not self.proposal_only:
            raise ProgramTransitionError("graph-delta proposals are proposal-only")
        if self.authorizes_mutation:
            raise ProgramTransitionError("graph-delta proposals cannot authorize mutation")
        overlap_nodes = set(self.added_node_cids) & set(self.removed_node_cids)
        overlap_edges = set(self.added_edge_cids) & set(self.removed_edge_cids)
        if overlap_nodes or overlap_edges:
            raise ProgramTransitionError("delta cannot add and remove the same identity")
        retained_removed = set(self.retained_subroot_cids) & set(self.removed_node_cids)
        if retained_removed:
            raise ProgramTransitionError("unchanged subroots cannot be removed")
        retained_added = set(self.retained_subroot_cids) & set(self.added_node_cids)
        if retained_added:
            raise ProgramTransitionError("unchanged subroots cannot be added")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "previous_snapshot_cid": self.previous_snapshot_cid,
            "query_cid": self.query_cid,
            "candidate_cid": self.candidate_cid,
            "added_node_cids": list(self.added_node_cids),
            "removed_node_cids": list(self.removed_node_cids),
            "added_edge_cids": list(self.added_edge_cids),
            "removed_edge_cids": list(self.removed_edge_cids),
            "retained_subroot_cids": list(self.retained_subroot_cids),
            "proposal_only": self.proposal_only,
            "authorizes_mutation": self.authorizes_mutation,
        }

    @property
    def program_graph_delta_proposal_cid(self) -> str:
        return transition_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_transition_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["program_graph_delta_proposal_cid"] = self.program_graph_delta_proposal_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramGraphDeltaProposal":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class PatchSketchIR:
    """Bounded patch sketch; never a complete or authorized patch."""

    language: ProgramLanguage | str
    sketch_kind: SketchKind | str
    source_cid: str
    hole_cids: Sequence[str] = ()
    operator_cids: Sequence[str] = ()
    proposal_only: bool = True
    authorizes_mutation: bool = False
    complete_patch: bool = False

    SCHEMA: ClassVar[str] = PATCH_SKETCH_IR_SCHEMA
    INTERFACE: ClassVar[str] = PATCH_SKETCH_IR_INTERFACE
    CID_FIELD: ClassVar[str] = "patch_sketch_ir_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "language",
            "sketch_kind",
            "source_cid",
            "hole_cids",
            "operator_cids",
            "proposal_only",
            "authorizes_mutation",
            "complete_patch",
            "patch_sketch_ir_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self, "sketch_kind", _enum(self.sketch_kind, SketchKind, "sketch_kind")
        )
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self,
            "hole_cids",
            _ordered_cids(self.hole_cids, "hole_cid", maximum=MAX_SKETCH_STEPS),
        )
        object.__setattr__(
            self,
            "operator_cids",
            _ordered_cids(self.operator_cids, "operator_cid", maximum=MAX_SKETCH_STEPS),
        )
        object.__setattr__(
            self, "proposal_only", _bool(self.proposal_only, "proposal_only")
        )
        object.__setattr__(
            self,
            "authorizes_mutation",
            _bool(self.authorizes_mutation, "authorizes_mutation"),
        )
        object.__setattr__(
            self, "complete_patch", _bool(self.complete_patch, "complete_patch")
        )
        if not self.proposal_only:
            raise ProgramTransitionError("patch sketches are proposal-only")
        if self.authorizes_mutation:
            raise ProgramTransitionError("patch sketches cannot authorize mutation")
        if self.complete_patch:
            raise ProgramTransitionError("patch sketches cannot claim a complete patch")
        if not self.hole_cids and not self.operator_cids:
            raise ProgramTransitionError("patch sketches require at least one hole or operator")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "sketch_kind": self.sketch_kind,
            "source_cid": self.source_cid,
            "hole_cids": list(self.hole_cids),
            "operator_cids": list(self.operator_cids),
            "proposal_only": self.proposal_only,
            "authorizes_mutation": self.authorizes_mutation,
            "complete_patch": self.complete_patch,
        }

    @property
    def patch_sketch_ir_cid(self) -> str:
        return transition_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_transition_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["patch_sketch_ir_cid"] = self.patch_sketch_ir_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PatchSketchIR":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramTransitionQuery:
    """Current-bound transition query for one closed family."""

    query_family: QueryFamily | str
    language: ProgramLanguage | str
    subject_cid: str
    current_source_cid: str
    environment_binding_cid: str
    policy_cid: str
    current_graph_cid: str | None = None
    current_state_cid: str | None = None
    current_trace_cid: str | None = None
    abstraction_profile_cid: str | None = None
    allowed_symbol_cids: Sequence[str] = ()
    allowed_operator_cids: Sequence[str] = ()
    evidence_cids: Sequence[str] = ()
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = PROGRAM_TRANSITION_QUERY_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRANSITION_QUERY_INTERFACE
    CID_FIELD: ClassVar[str] = "query_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "query_family",
            "language",
            "subject_cid",
            "current_source_cid",
            "current_graph_cid",
            "current_state_cid",
            "current_trace_cid",
            "environment_binding_cid",
            "policy_cid",
            "abstraction_profile_cid",
            "allowed_symbol_cids",
            "allowed_operator_cids",
            "evidence_cids",
            "unavailable_dimensions",
            "query_cid",
        }
    )

    def __post_init__(self) -> None:
        family = _query_family(self.query_family)
        object.__setattr__(self, "query_family", family)
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(
            self, "current_source_cid", _cid(self.current_source_cid, "current_source_cid")
        )
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(self, "policy_cid", _cid(self.policy_cid, "policy_cid"))
        object.__setattr__(
            self,
            "current_graph_cid",
            _optional_cid(self.current_graph_cid, "current_graph_cid"),
        )
        object.__setattr__(
            self,
            "current_state_cid",
            _optional_cid(self.current_state_cid, "current_state_cid"),
        )
        object.__setattr__(
            self,
            "current_trace_cid",
            _optional_cid(self.current_trace_cid, "current_trace_cid"),
        )
        object.__setattr__(
            self,
            "abstraction_profile_cid",
            _optional_cid(self.abstraction_profile_cid, "abstraction_profile_cid"),
        )
        object.__setattr__(
            self,
            "allowed_symbol_cids",
            _unique_sorted_cids(self.allowed_symbol_cids, "allowed_symbol_cid"),
        )
        object.__setattr__(
            self,
            "allowed_operator_cids",
            _unique_sorted_cids(self.allowed_operator_cids, "allowed_operator_cid"),
        )
        object.__setattr__(
            self, "evidence_cids", _unique_sorted_cids(self.evidence_cids, "evidence_cid")
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(self.unavailable_dimensions, "unavailable_dimension"),
        )
        for field_name in FAMILY_REQUIRED_CURRENT[family]:
            if getattr(self, field_name) is None:
                raise ProgramTransitionError(
                    f"{family} queries require {field_name}"
                )

    def allowed_universe_for(self, candidate_kind: str) -> tuple[str, ...]:
        if candidate_kind in {"call_target", "next_event", "next_state", "inverse_event", "inverse_trace"}:
            return self.allowed_symbol_cids
        return self.allowed_operator_cids

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "query_family": self.query_family,
            "language": self.language,
            "subject_cid": self.subject_cid,
            "current_source_cid": self.current_source_cid,
            "current_graph_cid": self.current_graph_cid,
            "current_state_cid": self.current_state_cid,
            "current_trace_cid": self.current_trace_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "policy_cid": self.policy_cid,
            "abstraction_profile_cid": self.abstraction_profile_cid,
            "allowed_symbol_cids": list(self.allowed_symbol_cids),
            "allowed_operator_cids": list(self.allowed_operator_cids),
            "evidence_cids": list(self.evidence_cids),
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def query_cid(self) -> str:
        return transition_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_transition_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["query_cid"] = self.query_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        return _identity_transition(
            transition_kind="query",
            subject_cid=self.subject_cid,
            evidence_cids=self.evidence_cids,
            environment_binding_cid=self.environment_binding_cid,
            policy_cid=self.policy_cid,
            proposal_only=False,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramTransitionQuery":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramTransitionCandidate:
    """Bounded current-CID candidate; model output may only select/parameterize this."""

    query_cid: str
    candidate_kind: CandidateKind | str
    selected_cid: str
    query_family: QueryFamily | str
    current_subject_cid: str
    current_source_cid: str
    current_environment_binding_cid: str
    current_graph_cid: str | None = None
    current_state_cid: str | None = None
    current_trace_cid: str | None = None
    parameterization: Mapping[str, Any] | None = None
    rank: int = 0
    proposal_only: bool = True

    SCHEMA: ClassVar[str] = PROGRAM_TRANSITION_CANDIDATE_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRANSITION_CANDIDATE_INTERFACE
    CID_FIELD: ClassVar[str] = "candidate_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "query_cid",
            "candidate_kind",
            "selected_cid",
            "query_family",
            "current_subject_cid",
            "current_source_cid",
            "current_environment_binding_cid",
            "current_graph_cid",
            "current_state_cid",
            "current_trace_cid",
            "parameterization",
            "rank",
            "proposal_only",
            "candidate_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_cid", _cid(self.query_cid, "query_cid"))
        kind = _enum(self.candidate_kind, CandidateKind, "candidate_kind")
        object.__setattr__(self, "candidate_kind", kind)
        object.__setattr__(self, "selected_cid", _cid(self.selected_cid, "selected_cid"))
        family = _query_family(self.query_family)
        object.__setattr__(self, "query_family", family)
        if kind not in QUERY_FAMILY_CANDIDATE_KINDS[family]:
            raise ProgramTransitionError(
                f"candidate kind {kind!r} is not admitted for {family} queries"
            )
        object.__setattr__(
            self,
            "current_subject_cid",
            _cid(self.current_subject_cid, "current_subject_cid"),
        )
        object.__setattr__(
            self, "current_source_cid", _cid(self.current_source_cid, "current_source_cid")
        )
        object.__setattr__(
            self,
            "current_environment_binding_cid",
            _cid(
                self.current_environment_binding_cid,
                "current_environment_binding_cid",
            ),
        )
        object.__setattr__(
            self,
            "current_graph_cid",
            _optional_cid(self.current_graph_cid, "current_graph_cid"),
        )
        object.__setattr__(
            self,
            "current_state_cid",
            _optional_cid(self.current_state_cid, "current_state_cid"),
        )
        object.__setattr__(
            self,
            "current_trace_cid",
            _optional_cid(self.current_trace_cid, "current_trace_cid"),
        )
        params = self.parameterization
        if isinstance(params, MappingProxyType):
            params = dict(params)
        object.__setattr__(
            self, "parameterization", _mapping(params, "parameterization")
        )
        object.__setattr__(self, "rank", _nonneg_int(self.rank, "rank"))
        if self.rank >= MAX_CANDIDATES:
            raise ProgramTransitionError("rank exceeds the bounded candidate limit")
        object.__setattr__(
            self, "proposal_only", _bool(self.proposal_only, "proposal_only")
        )
        if not self.proposal_only:
            raise ProgramTransitionError("candidates are proposal-only")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "query_cid": self.query_cid,
            "candidate_kind": self.candidate_kind,
            "selected_cid": self.selected_cid,
            "query_family": self.query_family,
            "current_subject_cid": self.current_subject_cid,
            "current_source_cid": self.current_source_cid,
            "current_environment_binding_cid": self.current_environment_binding_cid,
            "current_graph_cid": self.current_graph_cid,
            "current_state_cid": self.current_state_cid,
            "current_trace_cid": self.current_trace_cid,
            "parameterization": _thaw_structured(self.parameterization),
            "rank": self.rank,
            "proposal_only": self.proposal_only,
        }

    @property
    def candidate_cid(self) -> str:
        return transition_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_transition_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["candidate_cid"] = self.candidate_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramTransitionCandidate":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramTransitionPrediction:
    """Proposal-only prediction; cannot admit, observe, prove, or complete."""

    query_cid: str
    subject_cid: str
    model_profile_cid: str
    candidate_cids: Sequence[str]
    evidence_cids: Sequence[str] = ()
    environment_binding_cid: str | None = None
    policy_cid: str | None = None
    calibration_cid: str | None = None
    abstain: bool = False
    proposal_only: bool = True
    proves_contract: bool = False
    proves_postcondition: bool = False
    authorizes_mutation: bool = False
    suppresses_validation: bool = False
    suppresses_review: bool = False
    establishes_equivalence: bool = False
    establishes_observation: bool = False
    establishes_completion: bool = False
    invents_hashes: bool = False
    proves_impossibility: bool = False
    self_admitted: bool = False
    authoritative: bool = False
    prediction_authoritative: bool = False

    SCHEMA: ClassVar[str] = PROGRAM_TRANSITION_PREDICTION_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRANSITION_PREDICTION_INTERFACE
    CID_FIELD: ClassVar[str] = "prediction_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "query_cid",
            "subject_cid",
            "model_profile_cid",
            "candidate_cids",
            "evidence_cids",
            "environment_binding_cid",
            "policy_cid",
            "calibration_cid",
            "abstain",
            "proposal_only",
            "proves_contract",
            "proves_postcondition",
            "authorizes_mutation",
            "suppresses_validation",
            "suppresses_review",
            "establishes_equivalence",
            "establishes_observation",
            "establishes_completion",
            "invents_hashes",
            "proves_impossibility",
            "self_admitted",
            "authoritative",
            "prediction_authoritative",
            "prediction_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_cid", _cid(self.query_cid, "query_cid"))
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(
            self, "model_profile_cid", _cid(self.model_profile_cid, "model_profile_cid")
        )
        object.__setattr__(
            self,
            "candidate_cids",
            _ordered_cids(self.candidate_cids, "candidate_cid", maximum=MAX_CANDIDATES),
        )
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
            self, "calibration_cid", _optional_cid(self.calibration_cid, "calibration_cid")
        )
        object.__setattr__(self, "abstain", _bool(self.abstain, "abstain"))
        object.__setattr__(
            self, "proposal_only", _bool(self.proposal_only, "proposal_only")
        )
        if not self.proposal_only:
            raise ProgramTransitionError("predictions are proposal-only")
        for flag in PREDICTION_AUTHORITY_FLAGS:
            object.__setattr__(self, flag, _false_flag(getattr(self, flag), flag))
        if self.abstain:
            if self.candidate_cids:
                raise ProgramTransitionError(
                    "abstaining predictions cannot carry candidates"
                )
        elif not self.candidate_cids:
            raise ProgramTransitionError(
                "non-abstaining predictions require bounded candidates; "
                "an empty set cannot prove impossibility"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "query_cid": self.query_cid,
            "subject_cid": self.subject_cid,
            "model_profile_cid": self.model_profile_cid,
            "candidate_cids": list(self.candidate_cids),
            "evidence_cids": list(self.evidence_cids),
            "environment_binding_cid": self.environment_binding_cid,
            "policy_cid": self.policy_cid,
            "calibration_cid": self.calibration_cid,
            "abstain": self.abstain,
            "proposal_only": self.proposal_only,
            "proves_contract": self.proves_contract,
            "proves_postcondition": self.proves_postcondition,
            "authorizes_mutation": self.authorizes_mutation,
            "suppresses_validation": self.suppresses_validation,
            "suppresses_review": self.suppresses_review,
            "establishes_equivalence": self.establishes_equivalence,
            "establishes_observation": self.establishes_observation,
            "establishes_completion": self.establishes_completion,
            "invents_hashes": self.invents_hashes,
            "proves_impossibility": self.proves_impossibility,
            "self_admitted": self.self_admitted,
            "authoritative": self.authoritative,
            "prediction_authoritative": self.prediction_authoritative,
        }

    @property
    def prediction_cid(self) -> str:
        return transition_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_transition_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["prediction_cid"] = self.prediction_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        return _identity_transition(
            transition_kind="prediction",
            subject_cid=self.subject_cid,
            evidence_cids=self.evidence_cids,
            environment_binding_cid=self.environment_binding_cid,
            policy_cid=self.policy_cid,
            model_profile_cid=self.model_profile_cid,
            proposal_only=True,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramTransitionPrediction":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramTransitionObservation:
    """Independent observation; disjoint from prediction records."""

    query_cid: str
    subject_cid: str
    observed_cid: str
    observation_status: ObservationStatus | str
    environment_binding_cid: str
    query_family: QueryFamily | str
    evidence_cids: Sequence[str] = ()
    policy_cid: str | None = None
    proposal_only: bool = False

    SCHEMA: ClassVar[str] = PROGRAM_TRANSITION_OBSERVATION_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRANSITION_OBSERVATION_INTERFACE
    CID_FIELD: ClassVar[str] = "observation_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "query_cid",
            "subject_cid",
            "observed_cid",
            "observation_status",
            "environment_binding_cid",
            "query_family",
            "evidence_cids",
            "policy_cid",
            "proposal_only",
            "observation_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_cid", _cid(self.query_cid, "query_cid"))
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(self, "observed_cid", _cid(self.observed_cid, "observed_cid"))
        object.__setattr__(
            self,
            "observation_status",
            _enum(self.observation_status, ObservationStatus, "observation_status"),
        )
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(self, "query_family", _query_family(self.query_family))
        object.__setattr__(
            self, "evidence_cids", _unique_sorted_cids(self.evidence_cids, "evidence_cid")
        )
        object.__setattr__(self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid"))
        object.__setattr__(
            self, "proposal_only", _bool(self.proposal_only, "proposal_only")
        )
        if self.proposal_only:
            raise ProgramTransitionError("observations cannot be proposal-only")

    @property
    def is_authoritative_observation(self) -> bool:
        return self.observation_status == ObservationStatus.OBSERVED.value

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "query_cid": self.query_cid,
            "subject_cid": self.subject_cid,
            "observed_cid": self.observed_cid,
            "observation_status": self.observation_status,
            "environment_binding_cid": self.environment_binding_cid,
            "query_family": self.query_family,
            "evidence_cids": list(self.evidence_cids),
            "policy_cid": self.policy_cid,
            "proposal_only": self.proposal_only,
        }

    @property
    def observation_cid(self) -> str:
        return transition_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_transition_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["observation_cid"] = self.observation_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        return _identity_transition(
            transition_kind="observation",
            subject_cid=self.subject_cid,
            evidence_cids=self.evidence_cids,
            environment_binding_cid=self.environment_binding_cid,
            policy_cid=self.policy_cid,
            proposal_only=False,
            observation_status=str(self.observation_status),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramTransitionObservation":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramTransitionAdmission:
    """Independent admission; predictions cannot self-approve."""

    query_cid: str
    policy_cid: str
    current_subject_cid: str
    current_environment_binding_cid: str
    verdict: AdmissionVerdict | str
    prediction_cid: str | None = None
    observation_cid: str | None = None
    validation_evidence_cids: Sequence[str] = ()
    limitation_cids: Sequence[str] = ()
    prediction_authoritative: bool = False
    authorizes_mutation: bool = False
    suppresses_validation: bool = False
    suppresses_review: bool = False
    establishes_completion: bool = False
    establishes_equivalence: bool = False

    SCHEMA: ClassVar[str] = PROGRAM_TRANSITION_ADMISSION_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRANSITION_ADMISSION_INTERFACE
    CID_FIELD: ClassVar[str] = "admission_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "query_cid",
            "policy_cid",
            "current_subject_cid",
            "current_environment_binding_cid",
            "verdict",
            "prediction_cid",
            "observation_cid",
            "validation_evidence_cids",
            "limitation_cids",
            "prediction_authoritative",
            "authorizes_mutation",
            "suppresses_validation",
            "suppresses_review",
            "establishes_completion",
            "establishes_equivalence",
            "admission_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_cid", _cid(self.query_cid, "query_cid"))
        object.__setattr__(self, "policy_cid", _cid(self.policy_cid, "policy_cid"))
        object.__setattr__(
            self,
            "current_subject_cid",
            _cid(self.current_subject_cid, "current_subject_cid"),
        )
        object.__setattr__(
            self,
            "current_environment_binding_cid",
            _cid(
                self.current_environment_binding_cid,
                "current_environment_binding_cid",
            ),
        )
        object.__setattr__(
            self, "verdict", _enum(self.verdict, AdmissionVerdict, "verdict")
        )
        object.__setattr__(
            self, "prediction_cid", _optional_cid(self.prediction_cid, "prediction_cid")
        )
        object.__setattr__(
            self, "observation_cid", _optional_cid(self.observation_cid, "observation_cid")
        )
        object.__setattr__(
            self,
            "validation_evidence_cids",
            _unique_sorted_cids(
                self.validation_evidence_cids, "validation_evidence_cid"
            ),
        )
        object.__setattr__(
            self,
            "limitation_cids",
            _unique_sorted_cids(self.limitation_cids, "limitation_cid"),
        )
        for flag in (
            "prediction_authoritative",
            "authorizes_mutation",
            "suppresses_validation",
            "suppresses_review",
            "establishes_completion",
            "establishes_equivalence",
        ):
            object.__setattr__(self, flag, _false_flag(getattr(self, flag), flag))
        if self.verdict == AdmissionVerdict.ADMITTED.value:
            if self.observation_cid is None and not self.validation_evidence_cids:
                raise ProgramTransitionError(
                    "admitted transitions require observation or validation evidence; "
                    "predictions cannot self-admit"
                )

    @property
    def may_influence_planning(self) -> bool:
        return (
            self.verdict == AdmissionVerdict.ADMITTED.value
            and not self.prediction_authoritative
            and not self.authorizes_mutation
            and not self.suppresses_validation
            and not self.suppresses_review
            and not self.establishes_completion
            and (self.observation_cid is not None or bool(self.validation_evidence_cids))
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "query_cid": self.query_cid,
            "policy_cid": self.policy_cid,
            "current_subject_cid": self.current_subject_cid,
            "current_environment_binding_cid": self.current_environment_binding_cid,
            "verdict": self.verdict,
            "prediction_cid": self.prediction_cid,
            "observation_cid": self.observation_cid,
            "validation_evidence_cids": list(self.validation_evidence_cids),
            "limitation_cids": list(self.limitation_cids),
            "prediction_authoritative": self.prediction_authoritative,
            "authorizes_mutation": self.authorizes_mutation,
            "suppresses_validation": self.suppresses_validation,
            "suppresses_review": self.suppresses_review,
            "establishes_completion": self.establishes_completion,
            "establishes_equivalence": self.establishes_equivalence,
        }

    @property
    def admission_cid(self) -> str:
        return transition_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_transition_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["admission_cid"] = self.admission_cid
        return value

    def to_identity_record(self) -> dict[str, Any]:
        return _identity_transition(
            transition_kind="admission",
            subject_cid=self.current_subject_cid,
            evidence_cids=self.validation_evidence_cids,
            environment_binding_cid=self.current_environment_binding_cid,
            policy_cid=self.policy_cid,
            proposal_only=False,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramTransitionAdmission":
        return _from_closed(cls, data)


@dataclass(frozen=True, slots=True)
class ProgramTransitionReceipt:
    """Closed query/prediction/observation/admission bundle."""

    query_cid: str
    admission_cid: str
    verdict: AdmissionVerdict | str
    prediction_cid: str | None = None
    observation_cid: str | None = None
    may_influence_planning: bool = False
    prediction_authoritative: bool = False

    SCHEMA: ClassVar[str] = PROGRAM_TRANSITION_RECEIPT_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_TRANSITION_RECEIPT_INTERFACE
    CID_FIELD: ClassVar[str] = "receipt_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "query_cid",
            "admission_cid",
            "verdict",
            "prediction_cid",
            "observation_cid",
            "may_influence_planning",
            "prediction_authoritative",
            "receipt_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_cid", _cid(self.query_cid, "query_cid"))
        object.__setattr__(self, "admission_cid", _cid(self.admission_cid, "admission_cid"))
        object.__setattr__(
            self, "verdict", _enum(self.verdict, AdmissionVerdict, "verdict")
        )
        object.__setattr__(
            self, "prediction_cid", _optional_cid(self.prediction_cid, "prediction_cid")
        )
        object.__setattr__(
            self, "observation_cid", _optional_cid(self.observation_cid, "observation_cid")
        )
        object.__setattr__(
            self,
            "may_influence_planning",
            _bool(self.may_influence_planning, "may_influence_planning"),
        )
        object.__setattr__(
            self,
            "prediction_authoritative",
            _bool(self.prediction_authoritative, "prediction_authoritative"),
        )
        if self.prediction_authoritative:
            raise ProgramTransitionError("receipts cannot treat predictions as authoritative")
        if self.may_influence_planning and self.verdict != AdmissionVerdict.ADMITTED.value:
            raise ProgramTransitionError(
                "only admitted receipts may influence planning"
            )
        if self.may_influence_planning and self.observation_cid is None:
            raise ProgramTransitionError(
                "planning influence requires an independent observation"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "query_cid": self.query_cid,
            "admission_cid": self.admission_cid,
            "verdict": self.verdict,
            "prediction_cid": self.prediction_cid,
            "observation_cid": self.observation_cid,
            "may_influence_planning": self.may_influence_planning,
            "prediction_authoritative": self.prediction_authoritative,
        }

    @property
    def receipt_cid(self) -> str:
        return transition_cid_for(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_transition_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["receipt_cid"] = self.receipt_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramTransitionReceipt":
        return _from_closed(cls, data)


TRANSITION_RECORD_TYPES: Final[tuple[type, ...]] = (
    TransitionModelProfile,
    TransitionCalibration,
    RepairOperator,
    ProgramGraphDeltaProposal,
    PatchSketchIR,
    ProgramTransitionQuery,
    ProgramTransitionCandidate,
    ProgramTransitionPrediction,
    ProgramTransitionObservation,
    ProgramTransitionAdmission,
    ProgramTransitionReceipt,
)

_SCHEMA_TO_CLASS: Final[dict[str, type]] = {
    cls.SCHEMA: cls for cls in TRANSITION_RECORD_TYPES
}


def decode_transition_record(data: Mapping[str, Any]) -> Any:
    """Dispatch one closed transition payload to its versioned record type."""

    if not isinstance(data, Mapping):
        raise ProgramTransitionError("transition record must be a mapping")
    schema = data.get("schema")
    record_type = _SCHEMA_TO_CLASS.get(schema) if type(schema) is str else None
    if record_type is None:
        raise ProgramTransitionError(f"unsupported transition schema {schema!r}")
    return record_type.from_dict(data)


def decode_transition_observation(
    data: Mapping[str, Any] | ProgramTransitionObservation,
) -> ProgramTransitionObservation:
    """Decode an observation; predictions and proposals fail closed."""

    if isinstance(data, ProgramTransitionObservation):
        return data
    if not isinstance(data, Mapping):
        raise ProgramTransitionError(
            "transition observation must be a mapping or ProgramTransitionObservation"
        )
    schema = data.get("schema")
    if schema == PROGRAM_TRANSITION_OBSERVATION_SCHEMA:
        return ProgramTransitionObservation.from_dict(data)
    if schema == PROGRAM_TRANSITION_PREDICTION_SCHEMA:
        raise ProgramTransitionError(
            "predictions cannot decode as observations"
        )
    if schema in {
        PROGRAM_TRANSITION_CANDIDATE_SCHEMA,
        PROGRAM_GRAPH_DELTA_PROPOSAL_SCHEMA,
        PATCH_SKETCH_IR_SCHEMA,
        REPAIR_OPERATOR_SCHEMA,
    }:
        raise ProgramTransitionError(
            "proposals cannot decode as observations"
        )
    raise ProgramTransitionError("predictions cannot decode as observations")


def load_payload_schema() -> dict[str, Any]:
    """Load the packaged JSON Schema for program-transition payloads."""

    from pathlib import Path

    path = (
        Path(__file__).resolve().parent
        / "schemas"
        / "program-transition.payload.schema.json"
    )
    return loads_transition_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Selection, binding, calibration, and admission
# ---------------------------------------------------------------------------


def bind_candidate_to_query(
    query: ProgramTransitionQuery,
    candidate: ProgramTransitionCandidate,
) -> ProgramTransitionCandidate:
    """Fail closed unless the candidate is bound to the query's current CIDs."""

    if not isinstance(query, ProgramTransitionQuery):
        raise ProgramTransitionError("query must be a ProgramTransitionQuery")
    if not isinstance(candidate, ProgramTransitionCandidate):
        raise ProgramTransitionError("candidate must be a ProgramTransitionCandidate")
    if candidate.query_cid != query.query_cid:
        raise ProgramTransitionError("candidate is not bound to the supplied query")
    if candidate.query_family != query.query_family:
        raise ProgramTransitionError("candidate query_family does not match the query")
    _require_current_match(
        "current_subject_cid", candidate.current_subject_cid, query.subject_cid
    )
    _require_current_match(
        "current_source_cid", candidate.current_source_cid, query.current_source_cid
    )
    _require_current_match(
        "current_environment_binding_cid",
        candidate.current_environment_binding_cid,
        query.environment_binding_cid,
    )
    _require_current_match(
        "current_graph_cid", candidate.current_graph_cid, query.current_graph_cid
    )
    _require_current_match(
        "current_state_cid", candidate.current_state_cid, query.current_state_cid
    )
    _require_current_match(
        "current_trace_cid", candidate.current_trace_cid, query.current_trace_cid
    )
    universe = query.allowed_universe_for(str(candidate.candidate_kind))
    if not universe:
        raise ProgramTransitionError(
            "empty candidate universe is incomplete analysis, not proved impossibility"
        )
    if candidate.selected_cid not in universe:
        raise ProgramTransitionError(
            "selected_cid is outside the query's current allowed CID universe"
        )
    return candidate


def select_and_parameterize_candidate(
    query: ProgramTransitionQuery,
    *,
    candidate_kind: CandidateKind | str,
    selected_cid: str,
    parameterization: Mapping[str, Any] | None = None,
    rank: int = 0,
) -> ProgramTransitionCandidate:
    """The only model-facing constructor: select and parameterize a bounded candidate."""

    if not isinstance(query, ProgramTransitionQuery):
        raise ProgramTransitionError("query must be a ProgramTransitionQuery")
    candidate = ProgramTransitionCandidate(
        query_cid=query.query_cid,
        candidate_kind=candidate_kind,
        selected_cid=selected_cid,
        query_family=query.query_family,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=query.environment_binding_cid,
        current_graph_cid=query.current_graph_cid,
        current_state_cid=query.current_state_cid,
        current_trace_cid=query.current_trace_cid,
        parameterization=parameterization or {},
        rank=rank,
        proposal_only=True,
    )
    return bind_candidate_to_query(query, candidate)


def propose_program_transition(
    query: ProgramTransitionQuery,
    candidates: Sequence[ProgramTransitionCandidate],
    *,
    model_profile: TransitionModelProfile,
    calibration: TransitionCalibration | None = None,
    abstain: bool = False,
    evidence_cids: Sequence[str] = (),
) -> ProgramTransitionPrediction:
    """Assemble a proposal-only prediction from bounded current candidates."""

    if not isinstance(query, ProgramTransitionQuery):
        raise ProgramTransitionError("query must be a ProgramTransitionQuery")
    if not isinstance(model_profile, TransitionModelProfile):
        raise ProgramTransitionError("model_profile must be a TransitionModelProfile")
    if calibration is not None and not isinstance(calibration, TransitionCalibration):
        raise ProgramTransitionError("calibration must be a TransitionCalibration")
    if calibration is not None:
        if calibration.model_profile_cid != model_profile.model_profile_cid:
            raise ProgramTransitionError("calibration is not bound to the model profile")
        if calibration.query_family != query.query_family:
            raise ProgramTransitionError("calibration query_family does not match the query")
    bound: list[ProgramTransitionCandidate] = []
    if abstain:
        if candidates:
            raise ProgramTransitionError("abstaining predictions cannot carry candidates")
    else:
        if not candidates:
            raise ProgramTransitionError(
                "non-abstaining predictions require bounded candidates"
            )
        if len(candidates) > MAX_CANDIDATES:
            raise ProgramTransitionError("prediction exceeds the bounded candidate limit")
        seen: set[str] = set()
        for item in candidates:
            bound_item = bind_candidate_to_query(query, item)
            if bound_item.candidate_cid in seen:
                raise ProgramTransitionError("prediction candidates must be unique")
            seen.add(bound_item.candidate_cid)
            bound.append(bound_item)
    expected_family = {
        QueryFamily.NEXT_CALL.value: SpecialistFamily.CALL_TARGET.value,
        QueryFamily.NEXT_EVENT.value: SpecialistFamily.NEXT_EVENT.value,
        QueryFamily.INVERSE_TRACE.value: SpecialistFamily.INVERSE_TRACE.value,
        QueryFamily.REPAIR.value: SpecialistFamily.REPAIR.value,
    }[str(query.query_family)]
    if model_profile.specialist_family != expected_family:
        raise ProgramTransitionError(
            "model profile specialist_family does not match the query family"
        )
    return ProgramTransitionPrediction(
        query_cid=query.query_cid,
        subject_cid=query.subject_cid,
        model_profile_cid=model_profile.model_profile_cid,
        candidate_cids=tuple(item.candidate_cid for item in bound),
        evidence_cids=evidence_cids,
        environment_binding_cid=query.environment_binding_cid,
        policy_cid=query.policy_cid,
        calibration_cid=None if calibration is None else calibration.calibration_cid,
        abstain=abstain,
        proposal_only=True,
    )


def assess_calibration_drift(
    calibration: TransitionCalibration,
) -> TransitionCalibration:
    """Recompute calibration status from integer trial/disagreement counts."""

    if not isinstance(calibration, TransitionCalibration):
        raise ProgramTransitionError("calibration must be a TransitionCalibration")
    return TransitionCalibration(
        model_profile_cid=calibration.model_profile_cid,
        query_family=calibration.query_family,
        trial_count=calibration.trial_count,
        disagreement_count=calibration.disagreement_count,
        bound_numerator=calibration.bound_numerator,
        bound_denominator=calibration.bound_denominator,
        expected_observation_cid=calibration.expected_observation_cid,
        actual_observation_cid=calibration.actual_observation_cid,
    )


def observe_program_transition(
    query: ProgramTransitionQuery,
    *,
    observed_cid: str,
    observation_status: ObservationStatus | str = ObservationStatus.OBSERVED,
    evidence_cids: Sequence[str] = (),
) -> ProgramTransitionObservation:
    """Admit an independent observation; predictions cannot be supplied here."""

    if not isinstance(query, ProgramTransitionQuery):
        raise ProgramTransitionError("query must be a ProgramTransitionQuery")
    return ProgramTransitionObservation(
        query_cid=query.query_cid,
        subject_cid=query.subject_cid,
        observed_cid=observed_cid,
        observation_status=observation_status,
        environment_binding_cid=query.environment_binding_cid,
        query_family=query.query_family,
        evidence_cids=evidence_cids,
        policy_cid=query.policy_cid,
        proposal_only=False,
    )


def _current_mismatch(
    query: ProgramTransitionQuery,
    *,
    current_subject_cid: str,
    current_source_cid: str,
    current_environment_binding_cid: str,
    current_graph_cid: str | None,
    current_state_cid: str | None,
    current_trace_cid: str | None,
) -> bool:
    return (
        query.subject_cid != current_subject_cid
        or query.current_source_cid != current_source_cid
        or query.environment_binding_cid != current_environment_binding_cid
        or query.current_graph_cid != current_graph_cid
        or query.current_state_cid != current_state_cid
        or query.current_trace_cid != current_trace_cid
    )


def admit_program_transition(
    query: ProgramTransitionQuery,
    *,
    current_subject_cid: str,
    current_source_cid: str,
    current_environment_binding_cid: str,
    prediction: ProgramTransitionPrediction | None = None,
    observation: ProgramTransitionObservation | None = None,
    validation_evidence_cids: Sequence[str] = (),
    current_graph_cid: str | None = None,
    current_state_cid: str | None = None,
    current_trace_cid: str | None = None,
    calibration: TransitionCalibration | None = None,
    policy_cid: str | None = None,
) -> ProgramTransitionAdmission:
    """Independently assess a transition.  Predictions cannot self-admit."""

    if not isinstance(query, ProgramTransitionQuery):
        raise ProgramTransitionError("query must be a ProgramTransitionQuery")
    if prediction is not None and not isinstance(prediction, ProgramTransitionPrediction):
        raise ProgramTransitionError("prediction must be a ProgramTransitionPrediction")
    if observation is not None and not isinstance(
        observation, ProgramTransitionObservation
    ):
        raise ProgramTransitionError(
            "observation must be a ProgramTransitionObservation"
        )
    subject = _cid(current_subject_cid, "current_subject_cid")
    source = _cid(current_source_cid, "current_source_cid")
    environment = _cid(
        current_environment_binding_cid, "current_environment_binding_cid"
    )
    graph = _optional_cid(current_graph_cid, "current_graph_cid")
    state = _optional_cid(current_state_cid, "current_state_cid")
    trace = _optional_cid(current_trace_cid, "current_trace_cid")
    policy = _cid(query.policy_cid if policy_cid is None else policy_cid, "policy_cid")
    evidence = _unique_sorted_cids(validation_evidence_cids, "validation_evidence_cid")
    if prediction is not None and prediction.query_cid != query.query_cid:
        raise ProgramTransitionError("prediction is not bound to the supplied query")
    if observation is not None and observation.query_cid != query.query_cid:
        raise ProgramTransitionError("observation is not bound to the supplied query")
    if _current_mismatch(
        query,
        current_subject_cid=subject,
        current_source_cid=source,
        current_environment_binding_cid=environment,
        current_graph_cid=graph,
        current_state_cid=state,
        current_trace_cid=trace,
    ):
        verdict = AdmissionVerdict.STALE.value
        observation_cid = None if observation is None else observation.observation_cid
        return ProgramTransitionAdmission(
            query_cid=query.query_cid,
            policy_cid=policy,
            current_subject_cid=subject,
            current_environment_binding_cid=environment,
            verdict=verdict,
            prediction_cid=None if prediction is None else prediction.prediction_cid,
            observation_cid=observation_cid,
            validation_evidence_cids=evidence,
        )
    independent = (
        observation is not None and observation.is_authoritative_observation
    ) or bool(evidence)
    if independent:
        if observation is not None and not observation.is_authoritative_observation:
            independent = bool(evidence)
    if independent:
        verdict = AdmissionVerdict.ADMITTED.value
    elif observation is not None and observation.observation_status in {
        ObservationStatus.UNAVAILABLE.value,
        ObservationStatus.REDACTED.value,
    }:
        verdict = AdmissionVerdict.UNKNOWN.value
    elif observation is not None and (
        observation.observation_status == ObservationStatus.INFERRED_UNTRUSTED.value
    ):
        verdict = AdmissionVerdict.ABSTAIN.value
    elif prediction is not None:
        if calibration is not None and calibration.drifted:
            verdict = AdmissionVerdict.ABSTAIN.value
        elif prediction.abstain:
            verdict = AdmissionVerdict.ABSTAIN.value
        else:
            verdict = AdmissionVerdict.ABSTAIN.value
    else:
        verdict = AdmissionVerdict.UNKNOWN.value
    return ProgramTransitionAdmission(
        query_cid=query.query_cid,
        policy_cid=policy,
        current_subject_cid=subject,
        current_environment_binding_cid=environment,
        verdict=verdict,
        prediction_cid=None if prediction is None else prediction.prediction_cid,
        observation_cid=None if observation is None else observation.observation_cid,
        validation_evidence_cids=evidence,
    )


def issue_transition_receipt(
    query: ProgramTransitionQuery,
    admission: ProgramTransitionAdmission,
    *,
    prediction: ProgramTransitionPrediction | None = None,
    observation: ProgramTransitionObservation | None = None,
) -> ProgramTransitionReceipt:
    """Bundle one independently admitted (or rejected) transition."""

    if not isinstance(query, ProgramTransitionQuery):
        raise ProgramTransitionError("query must be a ProgramTransitionQuery")
    if not isinstance(admission, ProgramTransitionAdmission):
        raise ProgramTransitionError("admission must be a ProgramTransitionAdmission")
    if admission.query_cid != query.query_cid:
        raise ProgramTransitionError("admission is not bound to the supplied query")
    prediction_cid = None if prediction is None else prediction.prediction_cid
    observation_cid = None if observation is None else observation.observation_cid
    if prediction is not None and admission.prediction_cid not in {None, prediction_cid}:
        raise ProgramTransitionError("receipt prediction does not match admission")
    if observation is not None and admission.observation_cid not in {
        None,
        observation_cid,
    }:
        raise ProgramTransitionError("receipt observation does not match admission")
    influence = (
        admission.may_influence_planning and admission.observation_cid is not None
    )
    return ProgramTransitionReceipt(
        query_cid=query.query_cid,
        admission_cid=admission.admission_cid,
        verdict=admission.verdict,
        prediction_cid=admission.prediction_cid,
        observation_cid=admission.observation_cid,
        may_influence_planning=influence,
        prediction_authoritative=False,
    )


def may_influence_planning(admission: ProgramTransitionAdmission) -> bool:
    if not isinstance(admission, ProgramTransitionAdmission):
        raise ProgramTransitionError("admission must be a ProgramTransitionAdmission")
    return admission.may_influence_planning


def prediction_authority_violations(
    prediction: ProgramTransitionPrediction,
) -> tuple[str, ...]:
    """Return names of any authority flags that would be illegal if true."""

    if not isinstance(prediction, ProgramTransitionPrediction):
        raise ProgramTransitionError("prediction must be a ProgramTransitionPrediction")
    violations = [
        flag for flag in PREDICTION_AUTHORITY_FLAGS if getattr(prediction, flag)
    ]
    if not prediction.proposal_only:
        violations.append("proposal_only")
    return tuple(violations)


__all__ = [
    "ADMISSION_VERDICTS",
    "ADMITTED_LANGUAGES",
    "CALIBRATION_STATUSES",
    "CANDIDATE_KINDS",
    "COLLECTION_SEMANTICS_DECLARATION",
    "FAMILY_REQUIRED_CURRENT",
    "MAX_CANDIDATES",
    "PATCH_SKETCH_IR_INTERFACE",
    "PATCH_SKETCH_IR_SCHEMA",
    "PREDICTION_AUTHORITY_FLAGS",
    "PROGRAM_GRAPH_DELTA_PROPOSAL_INTERFACE",
    "PROGRAM_GRAPH_DELTA_PROPOSAL_SCHEMA",
    "PROGRAM_TRANSITION_ADMISSION_INTERFACE",
    "PROGRAM_TRANSITION_ADMISSION_SCHEMA",
    "PROGRAM_TRANSITION_CANDIDATE_INTERFACE",
    "PROGRAM_TRANSITION_CANDIDATE_SCHEMA",
    "PROGRAM_TRANSITION_OBSERVATION_INTERFACE",
    "PROGRAM_TRANSITION_OBSERVATION_SCHEMA",
    "PROGRAM_TRANSITION_PREDICTION_INTERFACE",
    "PROGRAM_TRANSITION_PREDICTION_SCHEMA",
    "PROGRAM_TRANSITION_QUERY_INTERFACE",
    "PROGRAM_TRANSITION_QUERY_SCHEMA",
    "PROGRAM_TRANSITION_RECEIPT_INTERFACE",
    "PROGRAM_TRANSITION_RECEIPT_SCHEMA",
    "QUERY_FAMILIES",
    "QUERY_FAMILY_CANDIDATE_KINDS",
    "REPAIR_OPERATOR_INTERFACE",
    "REPAIR_OPERATOR_KINDS",
    "REPAIR_OPERATOR_SCHEMA",
    "TRANSITION_CALIBRATION_INTERFACE",
    "TRANSITION_CALIBRATION_SCHEMA",
    "TRANSITION_MODEL_PROFILE_INTERFACE",
    "TRANSITION_MODEL_PROFILE_SCHEMA",
    "UNAVAILABLE_LANGUAGES",
    "AdmissionVerdict",
    "CalibrationStatus",
    "CandidateKind",
    "ObservationStatus",
    "PatchSketchIR",
    "ProgramGraphDeltaProposal",
    "ProgramLanguage",
    "ProgramTransitionAdmission",
    "ProgramTransitionCandidate",
    "ProgramTransitionError",
    "ProgramTransitionObservation",
    "ProgramTransitionPrediction",
    "ProgramTransitionQuery",
    "ProgramTransitionReceipt",
    "QueryFamily",
    "RepairOperator",
    "RepairOperatorKind",
    "SketchKind",
    "SpecialistFamily",
    "TransitionCalibration",
    "TransitionModelProfile",
    "admit_program_transition",
    "assess_calibration_drift",
    "bind_candidate_to_query",
    "canonical_transition_bytes",
    "canonicalize_transition_value",
    "decode_transition_observation",
    "decode_transition_record",
    "issue_transition_receipt",
    "load_payload_schema",
    "loads_transition_json",
    "may_influence_planning",
    "observe_program_transition",
    "prediction_authority_violations",
    "propose_program_transition",
    "select_and_parameterize_candidate",
    "transition_cid_for",
]
