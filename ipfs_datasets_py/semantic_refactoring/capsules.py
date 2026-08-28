"""Closed deterministic SPAR capsule contracts (@1).

This module extends current ``ipfs_datasets_py`` semantic authority with the
refactoring capsule family declared by SPAR-002.  It does not replace
``SemanticCapsule`` / ``SemanticCapsuleCompiler@1``, does not mint a second
content-identity profile, and does not import or export providers, models, or
completion authority.

Normative rules:

* Canonical bytes and CIDv1 come only from ``software_contracts.content``.
* Records are frozen, closed to unknown fields, and restricted to strict
  DAG-JSON types.
* Nested mappings and sequences are recursively immutable.
* Timestamps, process IDs, local filesystem paths, and model output are
  excluded from semantic identity.
* Accepted ``@1`` payloads are never rewritten in place; claimed aggregate
  CIDs must reverify or the record is rejected.
* A move may preserve ``implementation_ir_cid`` / ``interface_contract_cid``
  while changing ``symbol_binding_cid`` / ``public_compatibility_cid``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Sequence
import json
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    PROFILE_ID,
    STRUCTURED_CODEC,
    canonical_dag_json_bytes,
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
)


# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

FUNCTION_SEMANTIC_CAPSULE_INTERFACE: Final[str] = "FunctionSemanticCapsule@1"
METHOD_SEMANTIC_CAPSULE_INTERFACE: Final[str] = "MethodSemanticCapsule@1"
CLASS_SEMANTIC_CAPSULE_INTERFACE: Final[str] = "ClassSemanticCapsule@1"
TOP_LEVEL_BLOCK_CAPSULE_INTERFACE: Final[str] = "TopLevelBlockCapsule@1"
MODULE_SEMANTIC_CAPSULE_INTERFACE: Final[str] = "ModuleSemanticCapsule@1"
PACKAGE_SEMANTIC_CAPSULE_INTERFACE: Final[str] = "PackageSemanticCapsule@1"
CALLSITE_SEMANTIC_CAPSULE_INTERFACE: Final[str] = "CallsiteSemanticCapsule@1"
STATE_OWNER_CAPSULE_INTERFACE: Final[str] = "StateOwnerCapsule@1"
REGISTRATION_CAPSULE_INTERFACE: Final[str] = "RegistrationCapsule@1"
RESOURCE_LIFECYCLE_CAPSULE_INTERFACE: Final[str] = "ResourceLifecycleCapsule@1"

FUNCTION_SEMANTIC_CAPSULE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.function-semantic-capsule@1"
)
METHOD_SEMANTIC_CAPSULE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.method-semantic-capsule@1"
)
CLASS_SEMANTIC_CAPSULE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.class-semantic-capsule@1"
)
TOP_LEVEL_BLOCK_CAPSULE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.top-level-block-capsule@1"
)
MODULE_SEMANTIC_CAPSULE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.module-semantic-capsule@1"
)
PACKAGE_SEMANTIC_CAPSULE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.package-semantic-capsule@1"
)
CALLSITE_SEMANTIC_CAPSULE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.callsite-semantic-capsule@1"
)
STATE_OWNER_CAPSULE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.state-owner-capsule@1"
)
REGISTRATION_CAPSULE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.registration-capsule@1"
)
RESOURCE_LIFECYCLE_CAPSULE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.resource-lifecycle-capsule@1"
)
TYPED_UNCERTAINTY_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.typed-uncertainty@1"
)

CAPSULE_CONTRACT_VERSION: Final[str] = "1"
CAPSULE_CID_CODEC: Final[str] = STRUCTURED_CODEC
CAPSULE_CID_PROFILE: Final[str] = PROFILE_ID

IDENTITY_DIMENSIONS: Final[tuple[str, ...]] = (
    "stable_symbol_id",
    "source_cid",
    "cst_cid",
    "ast_cid",
    "implementation_ir_cid",
    "symbol_binding_cid",
    "interface_contract_cid",
    "effect_summary_cid",
    "state_footprint_cid",
    "dependency_slice_cid",
    "behavior_summary_cid",
    "initialization_dependency_cid",
    "public_compatibility_cid",
    "validation_profile_cid",
    "provenance_cid",
    "semantic_state_root_cid",
)

CAPSULE_TYPES: Final[tuple[str, ...]] = (
    FUNCTION_SEMANTIC_CAPSULE_INTERFACE,
    METHOD_SEMANTIC_CAPSULE_INTERFACE,
    CLASS_SEMANTIC_CAPSULE_INTERFACE,
    TOP_LEVEL_BLOCK_CAPSULE_INTERFACE,
    MODULE_SEMANTIC_CAPSULE_INTERFACE,
    PACKAGE_SEMANTIC_CAPSULE_INTERFACE,
    CALLSITE_SEMANTIC_CAPSULE_INTERFACE,
    STATE_OWNER_CAPSULE_INTERFACE,
    REGISTRATION_CAPSULE_INTERFACE,
    RESOURCE_LIFECYCLE_CAPSULE_INTERFACE,
)

FORBIDDEN_OBSERVATIONAL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "timestamp",
        "timestamps",
        "clock",
        "clocks",
        "wall_clock",
        "process_id",
        "pid",
        "local_path",
        "local_paths",
        "checkout_path",
        "store_path",
        "model_output",
        "provider_output",
        "llm_output",
        "prompt",
        "prompts",
    }
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_ID_LIST: Final[int] = 4_096

_COMMON_PAYLOAD_FIELDS: Final[tuple[str, ...]] = (
    "schema",
    "kind",
    *IDENTITY_DIMENSIONS,
    "freshness",
    "typed_uncertainty",
)


class CapsuleContractError(ValueError):
    """Raised when a SPAR capsule contract record is malformed."""


class CapsuleKind(str, Enum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    TOP_LEVEL_BLOCK = "top_level_block"
    MODULE = "module"
    PACKAGE = "package"
    CALLSITE = "callsite"
    STATE_OWNER = "state_owner"
    REGISTRATION = "registration"
    RESOURCE_LIFECYCLE = "resource_lifecycle"


class CapsuleFreshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class EvidenceClass(str, Enum):
    EXACT_STATIC_FACT = "exact_static_fact"
    CONSERVATIVE_MAY_FACT = "conservative_may_fact"
    RUNTIME_OBSERVATION = "runtime_observation"
    REVIEWED_SPECIFICATION = "reviewed_specification"
    TEST = "test"
    PROOF_CANDIDATE = "proof_candidate"
    RECONSTRUCTED_PROOF = "reconstructed_proof"
    COUNTERMODEL = "countermodel"
    REPLAYED_COUNTEREXAMPLE = "replayed_counterexample"
    VECTOR_CANDIDATE = "vector_candidate"
    MODEL_HYPOTHESIS = "model_hypothesis"
    HUMAN_POLICY_DECISION = "human_policy_decision"
    UNKNOWN = "unknown"


class MethodKind(str, Enum):
    INSTANCE = "instance"
    CLASSMETHOD = "classmethod"
    STATICMETHOD = "staticmethod"
    PROPERTY = "property"


class BlockKind(str, Enum):
    IMPORT_STMT = "import_stmt"
    ASSIGNMENT = "assignment"
    ANNOTATED_ASSIGNMENT = "annotated_assignment"
    EXPRESSION = "expression"
    WITH_STMT = "with_stmt"
    TRY_STMT = "try_stmt"
    IF_STMT = "if_stmt"
    FOR_STMT = "for_stmt"
    WHILE_STMT = "while_stmt"
    MATCH_STMT = "match_stmt"
    ASSERT_STMT = "assert_stmt"
    RAISE_STMT = "raise_stmt"
    DELETE_STMT = "delete_stmt"
    GLOBAL_STMT = "global_stmt"
    NONLOCAL_STMT = "nonlocal_stmt"
    TYPE_ALIAS = "type_alias"
    DECORATOR_APPLICATION = "decorator_application"
    UNKNOWN = "unknown"


class DispatchKind(str, Enum):
    DIRECT = "direct"
    ATTRIBUTE = "attribute"
    DYNAMIC = "dynamic"
    UNRESOLVED = "unresolved"


class StateOwnerKind(str, Enum):
    MODULE_GLOBAL = "module_global"
    CLASS_ATTRIBUTE = "class_attribute"
    INSTANCE_ATTRIBUTE = "instance_attribute"
    CLOSURE_CELL = "closure_cell"
    CONTEXTVAR = "contextvar"
    THREAD_LOCAL = "thread_local"
    TASK_LOCAL = "task_local"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


class StateUniqueness(str, Enum):
    UNIQUE = "unique"
    SHARED = "shared"
    UNKNOWN = "unknown"


class RegistrationKind(str, Enum):
    DECORATOR = "decorator"
    ENTRY_POINT = "entry_point"
    PLUGIN = "plugin"
    CLI_COMMAND = "cli_command"
    WEB_ROUTE = "web_route"
    ORM_MODEL = "orm_model"
    SINGLEDISPATCH = "singledispatch"
    SIGNAL_HANDLER = "signal_handler"
    ATEXIT = "atexit"
    MODULE_GETATTR = "module_getattr"
    UNKNOWN = "unknown"


class ResourceKind(str, Enum):
    FILE = "file"
    LOCK = "lock"
    CONNECTION = "connection"
    THREAD = "thread"
    PROCESS = "process"
    TIMER = "timer"
    CONTEXT_MANAGER = "context_manager"
    SOCKET = "socket"
    UNKNOWN = "unknown"


_EXACT_EVIDENCE: Final[frozenset[str]] = frozenset({EvidenceClass.EXACT_STATIC_FACT.value})
_CONSERVATIVE_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        EvidenceClass.CONSERVATIVE_MAY_FACT.value,
        EvidenceClass.RUNTIME_OBSERVATION.value,
        EvidenceClass.REVIEWED_SPECIFICATION.value,
        EvidenceClass.TEST.value,
        EvidenceClass.PROOF_CANDIDATE.value,
        EvidenceClass.RECONSTRUCTED_PROOF.value,
        EvidenceClass.COUNTERMODEL.value,
        EvidenceClass.REPLAYED_COUNTEREXAMPLE.value,
        EvidenceClass.HUMAN_POLICY_DECISION.value,
    }
)
_HEURISTIC_EVIDENCE: Final[frozenset[str]] = _CONSERVATIVE_EVIDENCE | frozenset(
    {
        EvidenceClass.VECTOR_CANDIDATE.value,
        EvidenceClass.MODEL_HYPOTHESIS.value,
    }
)
_OPAQUE_EVIDENCE: Final[frozenset[str]] = frozenset({EvidenceClass.UNKNOWN.value})


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise CapsuleContractError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise CapsuleContractError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise CapsuleContractError(f"{name} contains invalid text")
    return value


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise CapsuleContractError(f"{name} has unsupported value {value!r}") from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise CapsuleContractError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise CapsuleContractError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise CapsuleContractError(f"{name} must be a nonnegative integer")
    return value


def _logical_name(value: Any, name: str) -> str:
    text = _text(value, name)
    if text.startswith("/") or text.startswith("\\") or text.startswith("file:"):
        raise CapsuleContractError(f"{name} must not be a local filesystem path")
    if len(text) > 1 and text[1] == ":" and text[0].isalpha():
        raise CapsuleContractError(f"{name} must not be a local filesystem path")
    if "\\" in text or text.startswith("~"):
        raise CapsuleContractError(f"{name} must not be a local filesystem path")
    return text


def _unique_sorted_cids(values: Any, name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise CapsuleContractError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(item, name) for item in values))
    if len(ordered) > MAX_ID_LIST:
        raise CapsuleContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise CapsuleContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_identity_fields(values: Any, name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise CapsuleContractError(f"{name} must be a list")
    ordered = tuple(sorted(_text(item, name) for item in values))
    if len(ordered) != len(set(ordered)):
        raise CapsuleContractError(f"{name} must not contain duplicates")
    unknown = [item for item in ordered if item not in IDENTITY_DIMENSIONS]
    if unknown:
        raise CapsuleContractError(
            f"{name} contains unknown identity dimensions {unknown}"
        )
    return ordered


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise CapsuleContractError(f"{name} must be a mapping")
    overlap = FORBIDDEN_OBSERVATIONAL_FIELDS.intersection(data)
    if overlap:
        raise CapsuleContractError(
            f"{name} excludes observational fields {sorted(overlap)}"
        )
    actual = set(data)
    if actual != fields:
        raise CapsuleContractError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


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


def _require_dag_json(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed)
    except Exception as exc:
        raise CapsuleContractError(f"{name} must be strict DAG-JSON") from exc
    return thawed


# ---------------------------------------------------------------------------
# Typed uncertainty
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedUncertainty:
    """Closed uncertainty record bound into every SPAR capsule."""

    confidence: AnalysisConfidence | str
    unresolved_identity_fields: Sequence[str] = ()
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "confidence",
            "unresolved_identity_fields",
            "evidence_class",
        }
    )

    def __post_init__(self) -> None:
        confidence = _enum(self.confidence, AnalysisConfidence, "confidence")
        unresolved = _unique_sorted_identity_fields(
            list(self.unresolved_identity_fields), "unresolved_identity_fields"
        )
        evidence = _enum(self.evidence_class, EvidenceClass, "evidence_class")
        if confidence == AnalysisConfidence.EXACT.value:
            if unresolved:
                raise CapsuleContractError(
                    "exact confidence forbids unresolved identity fields"
                )
            if evidence not in _EXACT_EVIDENCE:
                raise CapsuleContractError(
                    "exact confidence requires exact_static_fact evidence"
                )
        elif confidence == AnalysisConfidence.CONSERVATIVE.value:
            if evidence not in _CONSERVATIVE_EVIDENCE:
                raise CapsuleContractError(
                    "conservative confidence has an incompatible evidence_class"
                )
        elif confidence == AnalysisConfidence.HEURISTIC.value:
            if evidence not in _HEURISTIC_EVIDENCE:
                raise CapsuleContractError(
                    "heuristic confidence has an incompatible evidence_class"
                )
        elif confidence == AnalysisConfidence.OPAQUE.value:
            if not unresolved:
                raise CapsuleContractError(
                    "opaque confidence requires unresolved identity fields"
                )
            if evidence not in _OPAQUE_EVIDENCE:
                raise CapsuleContractError(
                    "opaque confidence requires unknown evidence_class"
                )
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "unresolved_identity_fields", unresolved)
        object.__setattr__(self, "evidence_class", evidence)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TYPED_UNCERTAINTY_SCHEMA,
            "confidence": self.confidence,
            "unresolved_identity_fields": list(self.unresolved_identity_fields),
            "evidence_class": self.evidence_class,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TypedUncertainty":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != TYPED_UNCERTAINTY_SCHEMA:
            raise CapsuleContractError("unsupported TypedUncertainty schema version")
        return cls(
            confidence=payload["confidence"],
            unresolved_identity_fields=payload["unresolved_identity_fields"],
            evidence_class=payload["evidence_class"],
        )


# ---------------------------------------------------------------------------
# Shared capsule operations
# ---------------------------------------------------------------------------


def _normalize_typed_uncertainty(value: Any) -> TypedUncertainty:
    if isinstance(value, TypedUncertainty):
        return value
    if isinstance(value, Mapping):
        return TypedUncertainty.from_dict(value)
    raise CapsuleContractError("typed_uncertainty must be a TypedUncertainty record")


def _core_post_init(capsule: Any) -> None:
    for name in IDENTITY_DIMENSIONS:
        object.__setattr__(capsule, name, _cid(getattr(capsule, name), name))
    object.__setattr__(
        capsule,
        "freshness",
        _enum(capsule.freshness, CapsuleFreshness, "freshness"),
    )
    uncertainty = _normalize_typed_uncertainty(capsule.typed_uncertainty)
    object.__setattr__(capsule, "typed_uncertainty", uncertainty)
    for field_name, normalizer in type(capsule)._EXTRA_NORMALIZERS:
        object.__setattr__(
            capsule,
            field_name,
            normalizer(getattr(capsule, field_name), field_name),
        )
    invariant = getattr(type(capsule), "_invariant", None)
    if invariant is not None:
        invariant(capsule)


def _extra_payload(capsule: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field_name, _normalizer in type(capsule)._EXTRA_NORMALIZERS:
        value = getattr(capsule, field_name)
        if isinstance(value, tuple):
            payload[field_name] = list(value)
        else:
            payload[field_name] = value
    return payload


def _capsule_identity_payload(capsule: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": type(capsule).SCHEMA,
        "kind": type(capsule).KIND,
    }
    for name in IDENTITY_DIMENSIONS:
        payload[name] = getattr(capsule, name)
    payload["freshness"] = capsule.freshness
    payload["typed_uncertainty"] = capsule.typed_uncertainty.to_dict()
    payload.update(_extra_payload(capsule))
    _require_dag_json(payload, type(capsule).__name__)
    return payload


def _capsule_to_dict(capsule: Any) -> dict[str, Any]:
    payload = capsule.identity_payload()
    payload[type(capsule).AGGREGATE_FIELD] = capsule.capsule_cid
    return payload


def _capsule_from_dict(cls: type[Any], data: Mapping[str, Any]) -> Any:
    payload = _closed(data, cls._FIELDS, cls.__name__)
    claimed = payload.pop(cls.AGGREGATE_FIELD)
    schema = payload.pop("schema")
    kind = payload.pop("kind")
    if schema != cls.SCHEMA:
        raise CapsuleContractError(f"unsupported {cls.__name__} schema version")
    if kind != cls.KIND:
        raise CapsuleContractError(f"{cls.__name__} kind must be {cls.KIND!r}")
    payload["typed_uncertainty"] = TypedUncertainty.from_dict(
        payload["typed_uncertainty"]
    )
    result = cls(**payload)
    if claimed != result.capsule_cid:
        raise CapsuleContractError(
            f"{cls.__name__} {cls.AGGREGATE_FIELD} does not verify"
        )
    return result


def _fields_for(*extra: str, aggregate: str) -> frozenset[str]:
    return frozenset((*_COMMON_PAYLOAD_FIELDS, *extra, aggregate))


def _reject_unresolved_exact(capsule: Any, *, flag_name: str, flag_value: str) -> None:
    if flag_value in {"unresolved", "unknown", "dynamic"}:
        if capsule.typed_uncertainty.confidence == AnalysisConfidence.EXACT.value:
            raise CapsuleContractError(
                f"exact confidence forbids {flag_name}={flag_value!r}"
            )


# ---------------------------------------------------------------------------
# Capsule types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FunctionSemanticCapsule:
    """Closed function capsule bound to every declared identity dimension."""

    SCHEMA: ClassVar[str] = FUNCTION_SEMANTIC_CAPSULE_SCHEMA
    KIND: ClassVar[str] = CapsuleKind.FUNCTION.value
    INTERFACE: ClassVar[str] = FUNCTION_SEMANTIC_CAPSULE_INTERFACE
    AGGREGATE_FIELD: ClassVar[str] = "function_capsule_cid"
    _EXTRA_NORMALIZERS: ClassVar[tuple[tuple[str, Any], ...]] = (
        ("logical_qualname", _logical_name),
        ("owner_module_id", _cid),
        ("is_async", _bool),
        ("is_generator", _bool),
        ("positional_arity", _nonneg_int),
    )

    stable_symbol_id: str
    source_cid: str
    cst_cid: str
    ast_cid: str
    implementation_ir_cid: str
    symbol_binding_cid: str
    interface_contract_cid: str
    effect_summary_cid: str
    state_footprint_cid: str
    dependency_slice_cid: str
    behavior_summary_cid: str
    initialization_dependency_cid: str
    public_compatibility_cid: str
    validation_profile_cid: str
    provenance_cid: str
    semantic_state_root_cid: str
    freshness: CapsuleFreshness | str
    typed_uncertainty: TypedUncertainty | Mapping[str, Any]
    logical_qualname: str
    owner_module_id: str
    is_async: bool
    is_generator: bool
    positional_arity: int

    _FIELDS: ClassVar[frozenset[str]] = _fields_for(
        "logical_qualname",
        "owner_module_id",
        "is_async",
        "is_generator",
        "positional_arity",
        aggregate="function_capsule_cid",
    )

    def __post_init__(self) -> None:
        _core_post_init(self)

    def identity_payload(self) -> dict[str, Any]:
        return _capsule_identity_payload(self)

    @property
    def capsule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def function_capsule_cid(self) -> str:
        return self.capsule_cid

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return _capsule_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FunctionSemanticCapsule":
        return _capsule_from_dict(cls, data)


@dataclass(frozen=True, slots=True)
class MethodSemanticCapsule:
    """Closed method capsule; binding identity is owner-class relative."""

    SCHEMA: ClassVar[str] = METHOD_SEMANTIC_CAPSULE_SCHEMA
    KIND: ClassVar[str] = CapsuleKind.METHOD.value
    INTERFACE: ClassVar[str] = METHOD_SEMANTIC_CAPSULE_INTERFACE
    AGGREGATE_FIELD: ClassVar[str] = "method_capsule_cid"
    _EXTRA_NORMALIZERS: ClassVar[tuple[tuple[str, Any], ...]] = (
        ("logical_qualname", _logical_name),
        ("owner_class_id", _cid),
        ("owner_module_id", _cid),
        ("method_kind", lambda value, name: _enum(value, MethodKind, name)),
        ("is_async", _bool),
        ("is_generator", _bool),
        ("positional_arity", _nonneg_int),
    )

    stable_symbol_id: str
    source_cid: str
    cst_cid: str
    ast_cid: str
    implementation_ir_cid: str
    symbol_binding_cid: str
    interface_contract_cid: str
    effect_summary_cid: str
    state_footprint_cid: str
    dependency_slice_cid: str
    behavior_summary_cid: str
    initialization_dependency_cid: str
    public_compatibility_cid: str
    validation_profile_cid: str
    provenance_cid: str
    semantic_state_root_cid: str
    freshness: CapsuleFreshness | str
    typed_uncertainty: TypedUncertainty | Mapping[str, Any]
    logical_qualname: str
    owner_class_id: str
    owner_module_id: str
    method_kind: MethodKind | str
    is_async: bool
    is_generator: bool
    positional_arity: int

    _FIELDS: ClassVar[frozenset[str]] = _fields_for(
        "logical_qualname",
        "owner_class_id",
        "owner_module_id",
        "method_kind",
        "is_async",
        "is_generator",
        "positional_arity",
        aggregate="method_capsule_cid",
    )

    def __post_init__(self) -> None:
        _core_post_init(self)

    def identity_payload(self) -> dict[str, Any]:
        return _capsule_identity_payload(self)

    @property
    def capsule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def method_capsule_cid(self) -> str:
        return self.capsule_cid

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return _capsule_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MethodSemanticCapsule":
        return _capsule_from_dict(cls, data)


@dataclass(frozen=True, slots=True)
class ClassSemanticCapsule:
    """Closed class capsule including bases and members as CID sets."""

    SCHEMA: ClassVar[str] = CLASS_SEMANTIC_CAPSULE_SCHEMA
    KIND: ClassVar[str] = CapsuleKind.CLASS.value
    INTERFACE: ClassVar[str] = CLASS_SEMANTIC_CAPSULE_INTERFACE
    AGGREGATE_FIELD: ClassVar[str] = "class_capsule_cid"
    _EXTRA_NORMALIZERS: ClassVar[tuple[tuple[str, Any], ...]] = (
        ("logical_qualname", _logical_name),
        ("owner_module_id", _cid),
        ("base_class_ids", _unique_sorted_cids),
        ("member_ids", _unique_sorted_cids),
        ("has_metaclass", _bool),
    )

    stable_symbol_id: str
    source_cid: str
    cst_cid: str
    ast_cid: str
    implementation_ir_cid: str
    symbol_binding_cid: str
    interface_contract_cid: str
    effect_summary_cid: str
    state_footprint_cid: str
    dependency_slice_cid: str
    behavior_summary_cid: str
    initialization_dependency_cid: str
    public_compatibility_cid: str
    validation_profile_cid: str
    provenance_cid: str
    semantic_state_root_cid: str
    freshness: CapsuleFreshness | str
    typed_uncertainty: TypedUncertainty | Mapping[str, Any]
    logical_qualname: str
    owner_module_id: str
    base_class_ids: Sequence[str] = ()
    member_ids: Sequence[str] = ()
    has_metaclass: bool = False

    _FIELDS: ClassVar[frozenset[str]] = _fields_for(
        "logical_qualname",
        "owner_module_id",
        "base_class_ids",
        "member_ids",
        "has_metaclass",
        aggregate="class_capsule_cid",
    )

    def __post_init__(self) -> None:
        _core_post_init(self)

    def identity_payload(self) -> dict[str, Any]:
        return _capsule_identity_payload(self)

    @property
    def capsule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def class_capsule_cid(self) -> str:
        return self.capsule_cid

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return _capsule_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClassSemanticCapsule":
        return _capsule_from_dict(cls, data)


def _block_invariant(capsule: "TopLevelBlockCapsule") -> None:
    _reject_unresolved_exact(capsule, flag_name="block_kind", flag_value=capsule.block_kind)


@dataclass(frozen=True, slots=True)
class TopLevelBlockCapsule:
    """Closed top-level block capsule; first-class initialization subject."""

    SCHEMA: ClassVar[str] = TOP_LEVEL_BLOCK_CAPSULE_SCHEMA
    KIND: ClassVar[str] = CapsuleKind.TOP_LEVEL_BLOCK.value
    INTERFACE: ClassVar[str] = TOP_LEVEL_BLOCK_CAPSULE_INTERFACE
    AGGREGATE_FIELD: ClassVar[str] = "block_capsule_cid"
    _EXTRA_NORMALIZERS: ClassVar[tuple[tuple[str, Any], ...]] = (
        ("owner_module_id", _cid),
        ("block_kind", lambda value, name: _enum(value, BlockKind, name)),
        ("predecessor_ids", _unique_sorted_cids),
        ("effect_ids", _unique_sorted_cids),
    )
    _invariant: ClassVar[Any] = _block_invariant

    stable_symbol_id: str
    source_cid: str
    cst_cid: str
    ast_cid: str
    implementation_ir_cid: str
    symbol_binding_cid: str
    interface_contract_cid: str
    effect_summary_cid: str
    state_footprint_cid: str
    dependency_slice_cid: str
    behavior_summary_cid: str
    initialization_dependency_cid: str
    public_compatibility_cid: str
    validation_profile_cid: str
    provenance_cid: str
    semantic_state_root_cid: str
    freshness: CapsuleFreshness | str
    typed_uncertainty: TypedUncertainty | Mapping[str, Any]
    owner_module_id: str
    block_kind: BlockKind | str
    predecessor_ids: Sequence[str] = ()
    effect_ids: Sequence[str] = ()

    _FIELDS: ClassVar[frozenset[str]] = _fields_for(
        "owner_module_id",
        "block_kind",
        "predecessor_ids",
        "effect_ids",
        aggregate="block_capsule_cid",
    )

    def __post_init__(self) -> None:
        _core_post_init(self)

    def identity_payload(self) -> dict[str, Any]:
        return _capsule_identity_payload(self)

    @property
    def capsule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def block_capsule_cid(self) -> str:
        return self.capsule_cid

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return _capsule_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TopLevelBlockCapsule":
        return _capsule_from_dict(cls, data)


@dataclass(frozen=True, slots=True)
class ModuleSemanticCapsule:
    """Closed module capsule using logical names, never checkout paths."""

    SCHEMA: ClassVar[str] = MODULE_SEMANTIC_CAPSULE_SCHEMA
    KIND: ClassVar[str] = CapsuleKind.MODULE.value
    INTERFACE: ClassVar[str] = MODULE_SEMANTIC_CAPSULE_INTERFACE
    AGGREGATE_FIELD: ClassVar[str] = "module_capsule_cid"
    _EXTRA_NORMALIZERS: ClassVar[tuple[tuple[str, Any], ...]] = (
        ("logical_module_name", _logical_name),
        ("owner_package_id", _cid),
        ("member_ids", _unique_sorted_cids),
        ("top_level_block_ids", _unique_sorted_cids),
        ("import_target_ids", _unique_sorted_cids),
    )

    stable_symbol_id: str
    source_cid: str
    cst_cid: str
    ast_cid: str
    implementation_ir_cid: str
    symbol_binding_cid: str
    interface_contract_cid: str
    effect_summary_cid: str
    state_footprint_cid: str
    dependency_slice_cid: str
    behavior_summary_cid: str
    initialization_dependency_cid: str
    public_compatibility_cid: str
    validation_profile_cid: str
    provenance_cid: str
    semantic_state_root_cid: str
    freshness: CapsuleFreshness | str
    typed_uncertainty: TypedUncertainty | Mapping[str, Any]
    logical_module_name: str
    owner_package_id: str
    member_ids: Sequence[str] = ()
    top_level_block_ids: Sequence[str] = ()
    import_target_ids: Sequence[str] = ()

    _FIELDS: ClassVar[frozenset[str]] = _fields_for(
        "logical_module_name",
        "owner_package_id",
        "member_ids",
        "top_level_block_ids",
        "import_target_ids",
        aggregate="module_capsule_cid",
    )

    def __post_init__(self) -> None:
        _core_post_init(self)

    def identity_payload(self) -> dict[str, Any]:
        return _capsule_identity_payload(self)

    @property
    def capsule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def module_capsule_cid(self) -> str:
        return self.capsule_cid

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return _capsule_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModuleSemanticCapsule":
        return _capsule_from_dict(cls, data)


@dataclass(frozen=True, slots=True)
class PackageSemanticCapsule:
    """Closed package capsule; parent may be null at a repository root."""

    SCHEMA: ClassVar[str] = PACKAGE_SEMANTIC_CAPSULE_SCHEMA
    KIND: ClassVar[str] = CapsuleKind.PACKAGE.value
    INTERFACE: ClassVar[str] = PACKAGE_SEMANTIC_CAPSULE_INTERFACE
    AGGREGATE_FIELD: ClassVar[str] = "package_capsule_cid"
    _EXTRA_NORMALIZERS: ClassVar[tuple[tuple[str, Any], ...]] = (
        ("logical_package_name", _logical_name),
        ("parent_package_id", _optional_cid),
        ("module_ids", _unique_sorted_cids),
        ("child_package_ids", _unique_sorted_cids),
    )

    stable_symbol_id: str
    source_cid: str
    cst_cid: str
    ast_cid: str
    implementation_ir_cid: str
    symbol_binding_cid: str
    interface_contract_cid: str
    effect_summary_cid: str
    state_footprint_cid: str
    dependency_slice_cid: str
    behavior_summary_cid: str
    initialization_dependency_cid: str
    public_compatibility_cid: str
    validation_profile_cid: str
    provenance_cid: str
    semantic_state_root_cid: str
    freshness: CapsuleFreshness | str
    typed_uncertainty: TypedUncertainty | Mapping[str, Any]
    logical_package_name: str
    parent_package_id: str | None = None
    module_ids: Sequence[str] = ()
    child_package_ids: Sequence[str] = ()

    _FIELDS: ClassVar[frozenset[str]] = _fields_for(
        "logical_package_name",
        "parent_package_id",
        "module_ids",
        "child_package_ids",
        aggregate="package_capsule_cid",
    )

    def __post_init__(self) -> None:
        _core_post_init(self)

    def identity_payload(self) -> dict[str, Any]:
        return _capsule_identity_payload(self)

    @property
    def capsule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def package_capsule_cid(self) -> str:
        return self.capsule_cid

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return _capsule_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PackageSemanticCapsule":
        return _capsule_from_dict(cls, data)


def _callsite_invariant(capsule: "CallsiteSemanticCapsule") -> None:
    _reject_unresolved_exact(
        capsule, flag_name="dispatch_kind", flag_value=capsule.dispatch_kind
    )


@dataclass(frozen=True, slots=True)
class CallsiteSemanticCapsule:
    """Closed callsite capsule; unresolved dispatch is typed, never guessed."""

    SCHEMA: ClassVar[str] = CALLSITE_SEMANTIC_CAPSULE_SCHEMA
    KIND: ClassVar[str] = CapsuleKind.CALLSITE.value
    INTERFACE: ClassVar[str] = CALLSITE_SEMANTIC_CAPSULE_INTERFACE
    AGGREGATE_FIELD: ClassVar[str] = "callsite_capsule_cid"
    _EXTRA_NORMALIZERS: ClassVar[tuple[tuple[str, Any], ...]] = (
        ("caller_id", _cid),
        ("callee_id", _cid),
        ("enclosing_module_id", _cid),
        ("argument_count", _nonneg_int),
        ("dispatch_kind", lambda value, name: _enum(value, DispatchKind, name)),
    )
    _invariant: ClassVar[Any] = _callsite_invariant

    stable_symbol_id: str
    source_cid: str
    cst_cid: str
    ast_cid: str
    implementation_ir_cid: str
    symbol_binding_cid: str
    interface_contract_cid: str
    effect_summary_cid: str
    state_footprint_cid: str
    dependency_slice_cid: str
    behavior_summary_cid: str
    initialization_dependency_cid: str
    public_compatibility_cid: str
    validation_profile_cid: str
    provenance_cid: str
    semantic_state_root_cid: str
    freshness: CapsuleFreshness | str
    typed_uncertainty: TypedUncertainty | Mapping[str, Any]
    caller_id: str
    callee_id: str
    enclosing_module_id: str
    argument_count: int
    dispatch_kind: DispatchKind | str

    _FIELDS: ClassVar[frozenset[str]] = _fields_for(
        "caller_id",
        "callee_id",
        "enclosing_module_id",
        "argument_count",
        "dispatch_kind",
        aggregate="callsite_capsule_cid",
    )

    def __post_init__(self) -> None:
        _core_post_init(self)

    def identity_payload(self) -> dict[str, Any]:
        return _capsule_identity_payload(self)

    @property
    def capsule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def callsite_capsule_cid(self) -> str:
        return self.capsule_cid

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return _capsule_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CallsiteSemanticCapsule":
        return _capsule_from_dict(cls, data)


def _state_owner_invariant(capsule: "StateOwnerCapsule") -> None:
    _reject_unresolved_exact(
        capsule, flag_name="owner_kind", flag_value=capsule.owner_kind
    )
    _reject_unresolved_exact(
        capsule, flag_name="uniqueness", flag_value=capsule.uniqueness
    )


@dataclass(frozen=True, slots=True)
class StateOwnerCapsule:
    """Closed state-owner capsule; uniqueness unknown is typed uncertainty."""

    SCHEMA: ClassVar[str] = STATE_OWNER_CAPSULE_SCHEMA
    KIND: ClassVar[str] = CapsuleKind.STATE_OWNER.value
    INTERFACE: ClassVar[str] = STATE_OWNER_CAPSULE_INTERFACE
    AGGREGATE_FIELD: ClassVar[str] = "state_owner_capsule_cid"
    _EXTRA_NORMALIZERS: ClassVar[tuple[tuple[str, Any], ...]] = (
        ("owner_kind", lambda value, name: _enum(value, StateOwnerKind, name)),
        ("owning_symbol_id", _cid),
        ("alias_ids", _unique_sorted_cids),
        ("uniqueness", lambda value, name: _enum(value, StateUniqueness, name)),
    )
    _invariant: ClassVar[Any] = _state_owner_invariant

    stable_symbol_id: str
    source_cid: str
    cst_cid: str
    ast_cid: str
    implementation_ir_cid: str
    symbol_binding_cid: str
    interface_contract_cid: str
    effect_summary_cid: str
    state_footprint_cid: str
    dependency_slice_cid: str
    behavior_summary_cid: str
    initialization_dependency_cid: str
    public_compatibility_cid: str
    validation_profile_cid: str
    provenance_cid: str
    semantic_state_root_cid: str
    freshness: CapsuleFreshness | str
    typed_uncertainty: TypedUncertainty | Mapping[str, Any]
    owner_kind: StateOwnerKind | str
    owning_symbol_id: str
    uniqueness: StateUniqueness | str
    alias_ids: Sequence[str] = ()

    _FIELDS: ClassVar[frozenset[str]] = _fields_for(
        "owner_kind",
        "owning_symbol_id",
        "alias_ids",
        "uniqueness",
        aggregate="state_owner_capsule_cid",
    )

    def __post_init__(self) -> None:
        _core_post_init(self)

    def identity_payload(self) -> dict[str, Any]:
        return _capsule_identity_payload(self)

    @property
    def capsule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def state_owner_capsule_cid(self) -> str:
        return self.capsule_cid

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return _capsule_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateOwnerCapsule":
        return _capsule_from_dict(cls, data)


def _registration_invariant(capsule: "RegistrationCapsule") -> None:
    _reject_unresolved_exact(
        capsule, flag_name="registration_kind", flag_value=capsule.registration_kind
    )


@dataclass(frozen=True, slots=True)
class RegistrationCapsule:
    """Closed registration capsule; order_index is initialization-relevant."""

    SCHEMA: ClassVar[str] = REGISTRATION_CAPSULE_SCHEMA
    KIND: ClassVar[str] = CapsuleKind.REGISTRATION.value
    INTERFACE: ClassVar[str] = REGISTRATION_CAPSULE_INTERFACE
    AGGREGATE_FIELD: ClassVar[str] = "registration_capsule_cid"
    _EXTRA_NORMALIZERS: ClassVar[tuple[tuple[str, Any], ...]] = (
        ("registry_id", _cid),
        ("registered_symbol_id", _cid),
        (
            "registration_kind",
            lambda value, name: _enum(value, RegistrationKind, name),
        ),
        ("order_index", _nonneg_int),
    )
    _invariant: ClassVar[Any] = _registration_invariant

    stable_symbol_id: str
    source_cid: str
    cst_cid: str
    ast_cid: str
    implementation_ir_cid: str
    symbol_binding_cid: str
    interface_contract_cid: str
    effect_summary_cid: str
    state_footprint_cid: str
    dependency_slice_cid: str
    behavior_summary_cid: str
    initialization_dependency_cid: str
    public_compatibility_cid: str
    validation_profile_cid: str
    provenance_cid: str
    semantic_state_root_cid: str
    freshness: CapsuleFreshness | str
    typed_uncertainty: TypedUncertainty | Mapping[str, Any]
    registry_id: str
    registered_symbol_id: str
    registration_kind: RegistrationKind | str
    order_index: int

    _FIELDS: ClassVar[frozenset[str]] = _fields_for(
        "registry_id",
        "registered_symbol_id",
        "registration_kind",
        "order_index",
        aggregate="registration_capsule_cid",
    )

    def __post_init__(self) -> None:
        _core_post_init(self)

    def identity_payload(self) -> dict[str, Any]:
        return _capsule_identity_payload(self)

    @property
    def capsule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def registration_capsule_cid(self) -> str:
        return self.capsule_cid

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return _capsule_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RegistrationCapsule":
        return _capsule_from_dict(cls, data)


def _resource_invariant(capsule: "ResourceLifecycleCapsule") -> None:
    _reject_unresolved_exact(
        capsule, flag_name="resource_kind", flag_value=capsule.resource_kind
    )


@dataclass(frozen=True, slots=True)
class ResourceLifecycleCapsule:
    """Closed resource-lifecycle capsule; missing release is null, not guessed."""

    SCHEMA: ClassVar[str] = RESOURCE_LIFECYCLE_CAPSULE_SCHEMA
    KIND: ClassVar[str] = CapsuleKind.RESOURCE_LIFECYCLE.value
    INTERFACE: ClassVar[str] = RESOURCE_LIFECYCLE_CAPSULE_INTERFACE
    AGGREGATE_FIELD: ClassVar[str] = "resource_lifecycle_capsule_cid"
    _EXTRA_NORMALIZERS: ClassVar[tuple[tuple[str, Any], ...]] = (
        ("resource_kind", lambda value, name: _enum(value, ResourceKind, name)),
        ("acquire_site_id", _cid),
        ("release_site_id", _optional_cid),
        ("owner_id", _cid),
    )
    _invariant: ClassVar[Any] = _resource_invariant

    stable_symbol_id: str
    source_cid: str
    cst_cid: str
    ast_cid: str
    implementation_ir_cid: str
    symbol_binding_cid: str
    interface_contract_cid: str
    effect_summary_cid: str
    state_footprint_cid: str
    dependency_slice_cid: str
    behavior_summary_cid: str
    initialization_dependency_cid: str
    public_compatibility_cid: str
    validation_profile_cid: str
    provenance_cid: str
    semantic_state_root_cid: str
    freshness: CapsuleFreshness | str
    typed_uncertainty: TypedUncertainty | Mapping[str, Any]
    resource_kind: ResourceKind | str
    acquire_site_id: str
    owner_id: str
    release_site_id: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = _fields_for(
        "resource_kind",
        "acquire_site_id",
        "release_site_id",
        "owner_id",
        aggregate="resource_lifecycle_capsule_cid",
    )

    def __post_init__(self) -> None:
        _core_post_init(self)

    def identity_payload(self) -> dict[str, Any]:
        return _capsule_identity_payload(self)

    @property
    def capsule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def resource_lifecycle_capsule_cid(self) -> str:
        return self.capsule_cid

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return _capsule_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResourceLifecycleCapsule":
        return _capsule_from_dict(cls, data)


CapsuleRecord = (
    FunctionSemanticCapsule
    | MethodSemanticCapsule
    | ClassSemanticCapsule
    | TopLevelBlockCapsule
    | ModuleSemanticCapsule
    | PackageSemanticCapsule
    | CallsiteSemanticCapsule
    | StateOwnerCapsule
    | RegistrationCapsule
    | ResourceLifecycleCapsule
)

CAPSULE_SCHEMA_REGISTRY: Final[Mapping[str, type[CapsuleRecord]]] = MappingProxyType(
    {
        FUNCTION_SEMANTIC_CAPSULE_SCHEMA: FunctionSemanticCapsule,
        METHOD_SEMANTIC_CAPSULE_SCHEMA: MethodSemanticCapsule,
        CLASS_SEMANTIC_CAPSULE_SCHEMA: ClassSemanticCapsule,
        TOP_LEVEL_BLOCK_CAPSULE_SCHEMA: TopLevelBlockCapsule,
        MODULE_SEMANTIC_CAPSULE_SCHEMA: ModuleSemanticCapsule,
        PACKAGE_SEMANTIC_CAPSULE_SCHEMA: PackageSemanticCapsule,
        CALLSITE_SEMANTIC_CAPSULE_SCHEMA: CallsiteSemanticCapsule,
        STATE_OWNER_CAPSULE_SCHEMA: StateOwnerCapsule,
        REGISTRATION_CAPSULE_SCHEMA: RegistrationCapsule,
        RESOURCE_LIFECYCLE_CAPSULE_SCHEMA: ResourceLifecycleCapsule,
    }
)


def capsule_cid_profile() -> dict[str, str]:
    """Declare the reused datasets structured CID profile (not a second codec)."""

    return {
        "profile_id": CAPSULE_CID_PROFILE,
        "codec": CAPSULE_CID_CODEC,
        "contract_version": CAPSULE_CONTRACT_VERSION,
    }


def encode_canonical_capsule(capsule: CapsuleRecord) -> bytes:
    """Return strict canonical DAG-JSON bytes of the identity payload."""

    if type(capsule) not in set(CAPSULE_SCHEMA_REGISTRY.values()):
        raise CapsuleContractError("encode requires a SPAR @1 capsule record")
    data = capsule.canonical_bytes()
    if canonical_dag_json_bytes(json.loads(data.decode("utf-8"))) != data:
        raise CapsuleContractError("capsule encoding is not canonical")
    return data


def decode_canonical_capsule(data: bytes) -> CapsuleRecord:
    """Decode canonical identity bytes; reject any non-normalized payload."""

    if type(data) is not bytes:
        raise CapsuleContractError("canonical capsule bytes must be exact bytes")
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise CapsuleContractError("canonical capsule bytes must be UTF-8 JSON") from exc
    if canonical_dag_json_bytes(payload) != data:
        raise CapsuleContractError("capsule bytes are not canonical DAG-JSON")
    result = capsule_from_identity_payload(payload)
    if result.canonical_bytes() != data:
        raise CapsuleContractError("capsule bytes are not the normalized identity payload")
    return result


def capsule_from_dict(data: Mapping[str, Any]) -> CapsuleRecord:
    """Dispatch a closed ``to_dict`` payload to the matching @1 type."""

    if not isinstance(data, Mapping):
        raise CapsuleContractError("capsule payload must be a mapping")
    schema = data.get("schema")
    cls = CAPSULE_SCHEMA_REGISTRY.get(schema)  # type: ignore[arg-type]
    if cls is None:
        raise CapsuleContractError(f"unsupported capsule schema {schema!r}")
    return cls.from_dict(data)


def capsule_from_identity_payload(payload: Mapping[str, Any]) -> CapsuleRecord:
    """Load a closed identity payload; the aggregate CID is derived, not stored."""

    if not isinstance(payload, Mapping):
        raise CapsuleContractError("identity payload must be a mapping")
    schema = payload.get("schema")
    cls = CAPSULE_SCHEMA_REGISTRY.get(schema)  # type: ignore[arg-type]
    if cls is None:
        raise CapsuleContractError(f"unsupported capsule schema {schema!r}")
    closed = _closed(payload, cls._FIELDS - {cls.AGGREGATE_FIELD}, cls.__name__)
    schema_v = closed.pop("schema")
    kind = closed.pop("kind")
    if schema_v != cls.SCHEMA:
        raise CapsuleContractError(f"unsupported {cls.__name__} schema version")
    if kind != cls.KIND:
        raise CapsuleContractError(f"{cls.__name__} kind must be {cls.KIND!r}")
    closed["typed_uncertainty"] = TypedUncertainty.from_dict(closed["typed_uncertainty"])
    return cls(**closed)


def provider_free_exports() -> tuple[str, ...]:
    """Return the sorted public export surface (no provider or model names)."""

    return tuple(sorted(__all__))


__all__ = [
    "CAPSULE_CID_CODEC",
    "CAPSULE_CID_PROFILE",
    "CAPSULE_CONTRACT_VERSION",
    "CAPSULE_SCHEMA_REGISTRY",
    "CAPSULE_TYPES",
    "CALLSITE_SEMANTIC_CAPSULE_INTERFACE",
    "CALLSITE_SEMANTIC_CAPSULE_SCHEMA",
    "CLASS_SEMANTIC_CAPSULE_INTERFACE",
    "CLASS_SEMANTIC_CAPSULE_SCHEMA",
    "FORBIDDEN_OBSERVATIONAL_FIELDS",
    "FUNCTION_SEMANTIC_CAPSULE_INTERFACE",
    "FUNCTION_SEMANTIC_CAPSULE_SCHEMA",
    "IDENTITY_DIMENSIONS",
    "METHOD_SEMANTIC_CAPSULE_INTERFACE",
    "METHOD_SEMANTIC_CAPSULE_SCHEMA",
    "MODULE_SEMANTIC_CAPSULE_INTERFACE",
    "MODULE_SEMANTIC_CAPSULE_SCHEMA",
    "PACKAGE_SEMANTIC_CAPSULE_INTERFACE",
    "PACKAGE_SEMANTIC_CAPSULE_SCHEMA",
    "REGISTRATION_CAPSULE_INTERFACE",
    "REGISTRATION_CAPSULE_SCHEMA",
    "RESOURCE_LIFECYCLE_CAPSULE_INTERFACE",
    "RESOURCE_LIFECYCLE_CAPSULE_SCHEMA",
    "STATE_OWNER_CAPSULE_INTERFACE",
    "STATE_OWNER_CAPSULE_SCHEMA",
    "TOP_LEVEL_BLOCK_CAPSULE_INTERFACE",
    "TOP_LEVEL_BLOCK_CAPSULE_SCHEMA",
    "TYPED_UNCERTAINTY_SCHEMA",
    "BlockKind",
    "CallsiteSemanticCapsule",
    "CapsuleContractError",
    "CapsuleFreshness",
    "CapsuleKind",
    "CapsuleRecord",
    "ClassSemanticCapsule",
    "DispatchKind",
    "EvidenceClass",
    "FunctionSemanticCapsule",
    "MethodKind",
    "MethodSemanticCapsule",
    "ModuleSemanticCapsule",
    "PackageSemanticCapsule",
    "RegistrationCapsule",
    "RegistrationKind",
    "ResourceKind",
    "ResourceLifecycleCapsule",
    "StateOwnerCapsule",
    "StateOwnerKind",
    "StateUniqueness",
    "TopLevelBlockCapsule",
    "TypedUncertainty",
    "capsule_cid_profile",
    "capsule_from_dict",
    "capsule_from_identity_payload",
    "decode_canonical_capsule",
    "encode_canonical_capsule",
    "provider_free_exports",
]
