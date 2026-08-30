"""SPAR-016 module-boundary assume/guarantee contracts.

This module extends current ``ipfs_datasets_py`` semantic authority with
``ModuleBoundaryContract@1`` and ``BoundaryContractSet@1``.  It does not replace
capsule, identity, program-graph, SCC, state-ownership, initialization, or
public-compatibility contracts, does not mint a second content-identity
profile, and does not import or export providers, models, or completion
authority.

Normative rules:

* Every cut edge receives explicit assume/guarantee inputs, outputs,
  conditions, invariants, exceptions, allowed/forbidden effects,
  state/resource owner, initialization, authorization, concurrency/atomicity,
  serialization, versioning, and proof obligations.
* Incomplete authoritative contracts cause retrieval, proof, abstention, or
  review.  Guessed axioms are rejected.
* Exact static facts and conservative may-facts stay distinct evidence
  classes.  Model, vector, and heuristic output cannot complete a required
  clause or prove unique ownership.
* Observational metadata is excluded from identity.
* Accepted ``@1`` payloads are never rewritten in place; claimed aggregate
  CIDs must reverify or the record is rejected.
* Model output remains nomination-only and cannot authorize a transition
  or completion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    PROFILE_ID,
    STRUCTURED_CODEC,
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.semantic_refactoring.capsules import (
    EvidenceClass,
    ResourceKind,
    StateOwnerKind,
    StateUniqueness,
)
from ipfs_datasets_py.semantic_refactoring.compatibility import (
    ImportEagerness,
    SerializationFormat,
)


TASK_ID: Final[str] = "SPAR-016"
GOAL_ID: Final[str] = "SPAR-G033"
PROGRAM: Final[str] = "semantic-preserving-autonomous-remodularization-v1"
AUTHORITY: Final[str] = "formal semantic authority"
AUTHORITY_OWNER: Final[str] = "ipfs_datasets_py"
ANALYZER_ID: Final[str] = (
    "ipfs_datasets_py.semantic_refactoring.boundary_contracts@1"
)

MODULE_BOUNDARY_CONTRACT_INTERFACE: Final[str] = "ModuleBoundaryContract@1"
BOUNDARY_CONTRACT_SET_INTERFACE: Final[str] = "BoundaryContractSet@1"
CUT_EDGE_INTERFACE: Final[str] = "CutEdge@1"
ASSUME_GUARANTEE_CLAUSE_INTERFACE: Final[str] = "AssumeGuaranteeClause@1"
EFFECT_OBLIGATION_INTERFACE: Final[str] = "EffectObligation@1"
EXCEPTION_OBLIGATION_INTERFACE: Final[str] = "ExceptionObligation@1"
STATE_RESOURCE_OWNER_BINDING_INTERFACE: Final[str] = (
    "StateResourceOwnerBinding@1"
)
INITIALIZATION_BINDING_INTERFACE: Final[str] = "InitializationBinding@1"
CONCURRENCY_BINDING_INTERFACE: Final[str] = "ConcurrencyBinding@1"
AUTHORIZATION_BINDING_INTERFACE: Final[str] = "AuthorizationBinding@1"
SERIALIZATION_BINDING_INTERFACE: Final[str] = "SerializationBinding@1"
VERSIONING_BINDING_INTERFACE: Final[str] = "VersioningBinding@1"
PROOF_OBLIGATION_INTERFACE: Final[str] = "ProofObligation@1"
BOUNDARY_TERMINAL_INTERFACE: Final[str] = "BoundaryTerminal@1"

MODULE_BOUNDARY_CONTRACT_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.module-boundary-contract@1"
)
BOUNDARY_CONTRACT_SET_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.boundary-contract-set@1"
)
CUT_EDGE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.cut-edge@1"
)
ASSUME_GUARANTEE_CLAUSE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.assume-guarantee-clause@1"
)
EFFECT_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.effect-obligation@1"
)
EXCEPTION_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.exception-obligation@1"
)
STATE_RESOURCE_OWNER_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.state-resource-owner-binding@1"
)
INITIALIZATION_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.initialization-binding@1"
)
CONCURRENCY_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.concurrency-binding@1"
)
AUTHORIZATION_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.authorization-binding@1"
)
SERIALIZATION_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.serialization-binding@1"
)
VERSIONING_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.versioning-binding@1"
)
PROOF_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.proof-obligation@1"
)
BOUNDARY_TERMINAL_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.boundary-terminal@1"
)

BOUNDARY_CONTRACT_VERSION: Final[str] = "1"
BOUNDARY_CID_CODEC: Final[str] = STRUCTURED_CODEC
BOUNDARY_CID_PROFILE: Final[str] = PROFILE_ID

BOUNDARY_CAN_AUTHORIZE_TRANSITION: Final[bool] = False
BOUNDARY_CAN_AUTHORIZE_COMPLETION: Final[bool] = False
BOUNDARY_CAN_CREATE_AUTHORITY: Final[bool] = False
VECTOR_SIMILARITY_IS_AUTHORITY: Final[bool] = False
MODEL_OUTPUT_IS_PROPOSAL_ONLY: Final[bool] = True
TEST_PASS_IS_NOT_COMPLETION: Final[bool] = True
MARKDOWN_IS_NOT_COMPLETION: Final[bool] = True
WORKER_SELF_APPROVAL: Final[bool] = False
DUCKLAKE_IS_AUTHORITY: Final[bool] = False
GUESSED_AXIOMS_REJECTED: Final[bool] = True
INCOMPLETE_CONTRACTS_ARE_NOT_GUESSED: Final[bool] = True
UNIQUE_OWNER_REQUIRES_EXACT_EVIDENCE: Final[bool] = True

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CLAUSES: Final[int] = 8_192
MAX_EFFECTS: Final[int] = 4_096
MAX_EXCEPTIONS: Final[int] = 4_096
MAX_PROOFS: Final[int] = 4_096
MAX_CONTRACTS: Final[int] = 16_384
MAX_EDGES: Final[int] = 16_384

IDENTITY_EXCLUDED_FIELDS: Final[frozenset[str]] = frozenset(
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
        "model",
        "provider",
        "lease",
        "fence",
        "generation",
        "receipt",
        "acceptance",
    }
)

_FORBIDDEN_CAPSULE_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "FunctionSemanticCapsule",
        "MethodSemanticCapsule",
        "ClassSemanticCapsule",
        "TopLevelBlockCapsule",
        "ModuleSemanticCapsule",
        "PackageSemanticCapsule",
        "CallsiteSemanticCapsule",
        "StateOwnerCapsule",
        "RegistrationCapsule",
        "ResourceLifecycleCapsule",
    }
)

_EXACT_EVIDENCE: Final[frozenset[str]] = frozenset(
    {EvidenceClass.EXACT_STATIC_FACT.value}
)
_NON_AUTHORITATIVE_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        EvidenceClass.VECTOR_CANDIDATE.value,
        EvidenceClass.MODEL_HYPOTHESIS.value,
    }
)
_PROOF_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        EvidenceClass.PROOF_CANDIDATE.value,
        EvidenceClass.RECONSTRUCTED_PROOF.value,
        EvidenceClass.COUNTERMODEL.value,
        EvidenceClass.REPLAYED_COUNTEREXAMPLE.value,
    }
)
_REVIEW_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        EvidenceClass.REVIEWED_SPECIFICATION.value,
        EvidenceClass.HUMAN_POLICY_DECISION.value,
    }
)
_ABSTAIN_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        EvidenceClass.UNKNOWN.value,
        EvidenceClass.RUNTIME_OBSERVATION.value,
    }
)


class BoundaryContractError(ValueError):
    """Fail-closed violation of a SPAR-016 boundary contract."""


class CutEdgeKind(str, Enum):
    """Closed cut-edge kinds admitted on a module boundary."""

    IMPORT = "import"
    CALL = "call"
    STATE = "state"
    RESOURCE = "resource"
    REGISTRATION = "registration"
    TYPE = "type"
    SERIALIZATION = "serialization"
    EXTERNAL = "external"


class ClausePolarity(str, Enum):
    ASSUME = "assume"
    GUARANTEE = "guarantee"


class ClauseKind(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    CONDITION = "condition"
    INVARIANT = "invariant"


class EffectPolarity(str, Enum):
    ALLOWED = "allowed"
    FORBIDDEN = "forbidden"


class EffectClass(str, Enum):
    PURE = "pure"
    STATE_MUTATION = "state_mutation"
    IO = "io"
    NETWORK = "network"
    RESOURCE = "resource"
    REGISTRATION = "registration"
    IMPORT = "import"
    EXCEPTION = "exception"
    UNKNOWN = "unknown"


class ConcurrencyKind(str, Enum):
    SEQUENTIAL = "sequential"
    ATOMIC = "atomic"
    LOCKED = "locked"
    RACE_UNKNOWN = "race_unknown"


class AtomicityKind(str, Enum):
    ATOMIC = "atomic"
    NON_ATOMIC = "non_atomic"
    UNKNOWN = "unknown"


class AuthorizationKind(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL = "internal"
    AUTHENTICATED = "authenticated"
    FORBIDDEN = "forbidden"
    UNKNOWN = "unknown"


class VersioningKind(str, Enum):
    STABLE = "stable"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"
    UNKNOWN = "unknown"


class ProofObligationKind(str, Enum):
    EXACT_STATIC = "exact_static"
    RECONSTRUCTED_PROOF = "reconstructed_proof"
    COUNTERMODEL = "countermodel"
    REVIEW = "review"


class ContractDisposition(str, Enum):
    """Disposition of one cut-edge contract. Guessed axioms are not a value."""

    ADMITTED = "admitted"
    RETRIEVAL = "retrieval"
    PROOF = "proof"
    ABSTENTION = "abstention"
    REVIEW = "review"


class BoundaryTerminalKind(str, Enum):
    ADMITTED = "admitted"
    INCOMPLETE_CONTRACT = "incomplete_contract"
    UNKNOWN_REQUIRED = "unknown_required"
    UNSUPPORTED_REQUIRED = "unsupported_required"
    CONFLICT = "conflict"
    GUESSED_AXIOM_REJECTED = "guessed_axiom_rejected"


REQUIRED_CONTRACT_DIMENSIONS: Final[tuple[str, ...]] = (
    "assumptions",
    "guarantees",
    "inputs",
    "outputs",
    "conditions",
    "invariants",
    "exceptions",
    "allowed_effects",
    "forbidden_effects",
    "state_resource_owner",
    "initialization",
    "concurrency",
    "authorization",
    "serialization",
    "versioning",
    "proof_obligations",
)

DECLARED_CUT_EDGE_KINDS: Final[frozenset[str]] = frozenset(
    kind.value for kind in CutEdgeKind
)
DECLARED_CLAUSE_POLARITIES: Final[frozenset[str]] = frozenset(
    kind.value for kind in ClausePolarity
)
DECLARED_CLAUSE_KINDS: Final[frozenset[str]] = frozenset(
    kind.value for kind in ClauseKind
)
DECLARED_EFFECT_POLARITIES: Final[frozenset[str]] = frozenset(
    kind.value for kind in EffectPolarity
)
DECLARED_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    kind.value for kind in ContractDisposition
)
INCOMPLETE_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {
        ContractDisposition.RETRIEVAL.value,
        ContractDisposition.PROOF.value,
        ContractDisposition.ABSTENTION.value,
        ContractDisposition.REVIEW.value,
    }
)
GUESSED_AXIOM_DISPOSITIONS: Final[frozenset[str]] = frozenset()

_TERMINAL_PRECEDENCE: Final[tuple[BoundaryTerminalKind, ...]] = (
    BoundaryTerminalKind.GUESSED_AXIOM_REJECTED,
    BoundaryTerminalKind.CONFLICT,
    BoundaryTerminalKind.UNSUPPORTED_REQUIRED,
    BoundaryTerminalKind.UNKNOWN_REQUIRED,
    BoundaryTerminalKind.INCOMPLETE_CONTRACT,
    BoundaryTerminalKind.ADMITTED,
)


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str:
        raise BoundaryContractError(f"{name} must be a string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise BoundaryContractError(f"{name} must be trimmed NFC text")
    if not empty and not value:
        raise BoundaryContractError(f"{name} must be a nonempty string")
    if any(not char.isprintable() for char in value):
        raise BoundaryContractError(f"{name} contains invalid text")
    if len(value) > MAX_TEXT_CHARS:
        raise BoundaryContractError(f"{name} exceeds text bound")
    return value


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise BoundaryContractError(f"{name} must be a valid CID") from exc


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise BoundaryContractError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise BoundaryContractError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise BoundaryContractError(f"{name} must be a nonnegative integer")
    return value


def _tree_id(value: Any) -> str:
    text = _text(value, "tree_id")
    if len(text) not in {40, 64} or any(
        char not in "0123456789abcdef" for char in text
    ):
        raise BoundaryContractError(
            "tree_id must be a lowercase hex Git tree identity"
        )
    return text


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping) or isinstance(data, (str, bytes, bytearray)):
        raise BoundaryContractError(f"{name} must be an object")
    extra = set(data) - fields
    missing = fields - set(data)
    if extra & IDENTITY_EXCLUDED_FIELDS:
        raise BoundaryContractError(
            f"{name} identity excludes observational fields: "
            f"{sorted(extra & IDENTITY_EXCLUDED_FIELDS)}"
        )
    if extra:
        raise BoundaryContractError(f"unknown {name} field: {sorted(extra)}")
    if missing:
        raise BoundaryContractError(f"missing {name} field: {sorted(missing)}")
    return dict(data)


def _reject_excluded(payload: Mapping[str, Any], name: str) -> None:
    present = IDENTITY_EXCLUDED_FIELDS & set(payload)
    if present:
        raise BoundaryContractError(
            f"{name} identity excludes observational fields: {sorted(present)}"
        )


def _verify_cid(claimed: Any, computed: str, name: str) -> None:
    cid = _cid(claimed, name)
    if cid != computed:
        raise BoundaryContractError(f"{name} does not verify")


def _unique_sorted(values: Iterable[str], name: str) -> tuple[str, ...]:
    ordered = tuple(sorted(_text(item, name) for item in values))
    if len(ordered) != len(set(ordered)):
        raise BoundaryContractError(f"{name} must not contain duplicates")
    return ordered


def _require_dag_json(value: Any, name: str) -> None:
    try:
        validate_structured_value(value)
    except Exception as exc:
        raise BoundaryContractError(f"{name} must be strict DAG-JSON") from exc


def _evidence(value: Any, name: str) -> str:
    return _enum(value, EvidenceClass, name)


def _reject_guessed_axiom(evidence: str, name: str) -> None:
    if evidence in _NON_AUTHORITATIVE_EVIDENCE:
        raise BoundaryContractError(
            f"{name} cannot complete a required clause from model or vector evidence"
        )


def _reject_unique_without_exact(
    uniqueness: str, evidence: str, name: str
) -> None:
    if uniqueness == StateUniqueness.UNIQUE.value:
        if evidence not in _EXACT_EVIDENCE:
            raise BoundaryContractError(
                f"{name} unique ownership requires exact_static_fact evidence"
            )


def _sequence(value: Any, name: str, *, limit: int) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise BoundaryContractError(f"{name} must be a sequence")
    if len(value) > limit:
        raise BoundaryContractError(f"{name} exceeds maximum length")
    return tuple(value)


def _coerce(value: Any, cls: type, name: str) -> Any:
    if isinstance(value, cls):
        return value
    if isinstance(value, Mapping):
        if "schema" in value:
            return cls.from_dict(value)
        return cls(**dict(value))
    raise BoundaryContractError(f"{name} must be a {cls.__name__}")


def _optional_coerce(value: Any, cls: type, name: str) -> Any:
    if value is None:
        return None
    return _coerce(value, cls, name)


# ---------------------------------------------------------------------------
# Closed records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CutEdge:
    """Directed producer-to-consumer cut across a module boundary."""

    edge_id: str
    producer_module: str
    consumer_module: str
    producer_symbol: str
    consumer_symbol: str
    kind: CutEdgeKind | str
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT

    interface: ClassVar[str] = CUT_EDGE_INTERFACE
    schema: ClassVar[str] = CUT_EDGE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "edge_id",
            "producer_module",
            "consumer_module",
            "producer_symbol",
            "consumer_symbol",
            "kind",
            "evidence_class",
            "edge_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _text(self.edge_id, "edge_id"))
        object.__setattr__(
            self, "producer_module", _text(self.producer_module, "producer_module")
        )
        object.__setattr__(
            self, "consumer_module", _text(self.consumer_module, "consumer_module")
        )
        object.__setattr__(
            self, "producer_symbol", _text(self.producer_symbol, "producer_symbol")
        )
        object.__setattr__(
            self, "consumer_symbol", _text(self.consumer_symbol, "consumer_symbol")
        )
        object.__setattr__(self, "kind", _enum(self.kind, CutEdgeKind, "kind"))
        evidence = _evidence(self.evidence_class, "evidence_class")
        _reject_guessed_axiom(evidence, "CutEdge")
        object.__setattr__(self, "evidence_class", evidence)
        if self.producer_module == self.consumer_module:
            raise BoundaryContractError(
                "cut edge producer_module and consumer_module must differ"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CUT_EDGE_SCHEMA,
            "interface": CUT_EDGE_INTERFACE,
            "edge_id": self.edge_id,
            "producer_module": self.producer_module,
            "consumer_module": self.consumer_module,
            "producer_symbol": self.producer_symbol,
            "consumer_symbol": self.consumer_symbol,
            "kind": self.kind,
            "evidence_class": self.evidence_class,
        }

    @property
    def edge_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["edge_cid"] = self.edge_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CutEdge":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("edge_cid")
        if payload.pop("schema") != CUT_EDGE_SCHEMA:
            raise BoundaryContractError("unsupported CutEdge schema")
        if payload.pop("interface") != CUT_EDGE_INTERFACE:
            raise BoundaryContractError("unsupported CutEdge interface")
        result = cls(**payload)
        _verify_cid(claimed, result.edge_cid, "CutEdge edge_cid")
        return result


@dataclass(frozen=True, slots=True)
class AssumeGuaranteeClause:
    """One assume or guarantee clause on a cut edge."""

    clause_id: str
    polarity: ClausePolarity | str
    kind: ClauseKind | str
    predicate_id: str
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    required: bool = True

    interface: ClassVar[str] = ASSUME_GUARANTEE_CLAUSE_INTERFACE
    schema: ClassVar[str] = ASSUME_GUARANTEE_CLAUSE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "clause_id",
            "polarity",
            "kind",
            "predicate_id",
            "evidence_class",
            "required",
            "clause_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "clause_id", _text(self.clause_id, "clause_id"))
        object.__setattr__(
            self, "polarity", _enum(self.polarity, ClausePolarity, "polarity")
        )
        object.__setattr__(self, "kind", _enum(self.kind, ClauseKind, "kind"))
        object.__setattr__(
            self, "predicate_id", _text(self.predicate_id, "predicate_id")
        )
        evidence = _evidence(self.evidence_class, "evidence_class")
        required = _bool(self.required, "required")
        if required:
            _reject_guessed_axiom(evidence, "AssumeGuaranteeClause")
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "required", required)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ASSUME_GUARANTEE_CLAUSE_SCHEMA,
            "interface": ASSUME_GUARANTEE_CLAUSE_INTERFACE,
            "clause_id": self.clause_id,
            "polarity": self.polarity,
            "kind": self.kind,
            "predicate_id": self.predicate_id,
            "evidence_class": self.evidence_class,
            "required": self.required,
        }

    @property
    def clause_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["clause_cid"] = self.clause_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AssumeGuaranteeClause":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("clause_cid")
        if payload.pop("schema") != ASSUME_GUARANTEE_CLAUSE_SCHEMA:
            raise BoundaryContractError("unsupported AssumeGuaranteeClause schema")
        if payload.pop("interface") != ASSUME_GUARANTEE_CLAUSE_INTERFACE:
            raise BoundaryContractError(
                "unsupported AssumeGuaranteeClause interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.clause_cid, "AssumeGuaranteeClause clause_cid")
        return result


@dataclass(frozen=True, slots=True)
class EffectObligation:
    """Allowed or forbidden effect on a cut edge."""

    effect_id: str
    polarity: EffectPolarity | str
    effect_class: EffectClass | str
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    required: bool = True

    interface: ClassVar[str] = EFFECT_OBLIGATION_INTERFACE
    schema: ClassVar[str] = EFFECT_OBLIGATION_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "effect_id",
            "polarity",
            "effect_class",
            "evidence_class",
            "required",
            "effect_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect_id", _text(self.effect_id, "effect_id"))
        object.__setattr__(
            self, "polarity", _enum(self.polarity, EffectPolarity, "polarity")
        )
        object.__setattr__(
            self, "effect_class", _enum(self.effect_class, EffectClass, "effect_class")
        )
        evidence = _evidence(self.evidence_class, "evidence_class")
        required = _bool(self.required, "required")
        if required:
            _reject_guessed_axiom(evidence, "EffectObligation")
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "required", required)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": EFFECT_OBLIGATION_SCHEMA,
            "interface": EFFECT_OBLIGATION_INTERFACE,
            "effect_id": self.effect_id,
            "polarity": self.polarity,
            "effect_class": self.effect_class,
            "evidence_class": self.evidence_class,
            "required": self.required,
        }

    @property
    def effect_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["effect_cid"] = self.effect_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EffectObligation":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("effect_cid")
        if payload.pop("schema") != EFFECT_OBLIGATION_SCHEMA:
            raise BoundaryContractError("unsupported EffectObligation schema")
        if payload.pop("interface") != EFFECT_OBLIGATION_INTERFACE:
            raise BoundaryContractError("unsupported EffectObligation interface")
        result = cls(**payload)
        _verify_cid(claimed, result.effect_cid, "EffectObligation effect_cid")
        return result


@dataclass(frozen=True, slots=True)
class ExceptionObligation:
    """Exception the producer may raise or the consumer must handle."""

    exception_id: str
    exception_type: str
    guaranteed: bool = True
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    required: bool = True

    interface: ClassVar[str] = EXCEPTION_OBLIGATION_INTERFACE
    schema: ClassVar[str] = EXCEPTION_OBLIGATION_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "exception_id",
            "exception_type",
            "guaranteed",
            "evidence_class",
            "required",
            "exception_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "exception_id", _text(self.exception_id, "exception_id")
        )
        object.__setattr__(
            self, "exception_type", _text(self.exception_type, "exception_type")
        )
        object.__setattr__(self, "guaranteed", _bool(self.guaranteed, "guaranteed"))
        evidence = _evidence(self.evidence_class, "evidence_class")
        required = _bool(self.required, "required")
        if required:
            _reject_guessed_axiom(evidence, "ExceptionObligation")
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "required", required)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": EXCEPTION_OBLIGATION_SCHEMA,
            "interface": EXCEPTION_OBLIGATION_INTERFACE,
            "exception_id": self.exception_id,
            "exception_type": self.exception_type,
            "guaranteed": self.guaranteed,
            "evidence_class": self.evidence_class,
            "required": self.required,
        }

    @property
    def exception_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["exception_cid"] = self.exception_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExceptionObligation":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("exception_cid")
        if payload.pop("schema") != EXCEPTION_OBLIGATION_SCHEMA:
            raise BoundaryContractError("unsupported ExceptionObligation schema")
        if payload.pop("interface") != EXCEPTION_OBLIGATION_INTERFACE:
            raise BoundaryContractError("unsupported ExceptionObligation interface")
        result = cls(**payload)
        _verify_cid(
            claimed, result.exception_cid, "ExceptionObligation exception_cid"
        )
        return result


@dataclass(frozen=True, slots=True)
class StateResourceOwnerBinding:
    """State or resource owner bound to one cut edge."""

    owner_id: str
    owner_kind: StateOwnerKind | str
    uniqueness: StateUniqueness | str
    resource_kind: ResourceKind | str = ResourceKind.UNKNOWN
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    required: bool = True

    interface: ClassVar[str] = STATE_RESOURCE_OWNER_BINDING_INTERFACE
    schema: ClassVar[str] = STATE_RESOURCE_OWNER_BINDING_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "owner_id",
            "owner_kind",
            "uniqueness",
            "resource_kind",
            "evidence_class",
            "required",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        object.__setattr__(
            self, "owner_kind", _enum(self.owner_kind, StateOwnerKind, "owner_kind")
        )
        uniqueness = _enum(self.uniqueness, StateUniqueness, "uniqueness")
        object.__setattr__(self, "uniqueness", uniqueness)
        object.__setattr__(
            self,
            "resource_kind",
            _enum(self.resource_kind, ResourceKind, "resource_kind"),
        )
        evidence = _evidence(self.evidence_class, "evidence_class")
        required = _bool(self.required, "required")
        if required:
            _reject_guessed_axiom(evidence, "StateResourceOwnerBinding")
            _reject_unique_without_exact(
                uniqueness, evidence, "StateResourceOwnerBinding"
            )
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "required", required)
        if self.owner_kind == StateOwnerKind.UNKNOWN.value and uniqueness == (
            StateUniqueness.UNIQUE.value
        ):
            raise BoundaryContractError(
                "unknown owner kind cannot be unique"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": STATE_RESOURCE_OWNER_BINDING_SCHEMA,
            "interface": STATE_RESOURCE_OWNER_BINDING_INTERFACE,
            "owner_id": self.owner_id,
            "owner_kind": self.owner_kind,
            "uniqueness": self.uniqueness,
            "resource_kind": self.resource_kind,
            "evidence_class": self.evidence_class,
            "required": self.required,
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["binding_cid"] = self.binding_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateResourceOwnerBinding":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != STATE_RESOURCE_OWNER_BINDING_SCHEMA:
            raise BoundaryContractError(
                "unsupported StateResourceOwnerBinding schema"
            )
        if payload.pop("interface") != STATE_RESOURCE_OWNER_BINDING_INTERFACE:
            raise BoundaryContractError(
                "unsupported StateResourceOwnerBinding interface"
            )
        result = cls(**payload)
        _verify_cid(
            claimed, result.binding_cid, "StateResourceOwnerBinding binding_cid"
        )
        return result


@dataclass(frozen=True, slots=True)
class InitializationBinding:
    """Initialization-order obligation for one cut edge."""

    initialization_id: str
    order_index: int = 0
    eagerness: ImportEagerness | str = ImportEagerness.EAGER
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    required: bool = True

    interface: ClassVar[str] = INITIALIZATION_BINDING_INTERFACE
    schema: ClassVar[str] = INITIALIZATION_BINDING_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "initialization_id",
            "order_index",
            "eagerness",
            "evidence_class",
            "required",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "initialization_id",
            _text(self.initialization_id, "initialization_id"),
        )
        object.__setattr__(
            self, "order_index", _nonneg_int(self.order_index, "order_index")
        )
        object.__setattr__(
            self, "eagerness", _enum(self.eagerness, ImportEagerness, "eagerness")
        )
        evidence = _evidence(self.evidence_class, "evidence_class")
        required = _bool(self.required, "required")
        if required:
            _reject_guessed_axiom(evidence, "InitializationBinding")
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "required", required)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": INITIALIZATION_BINDING_SCHEMA,
            "interface": INITIALIZATION_BINDING_INTERFACE,
            "initialization_id": self.initialization_id,
            "order_index": self.order_index,
            "eagerness": self.eagerness,
            "evidence_class": self.evidence_class,
            "required": self.required,
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["binding_cid"] = self.binding_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InitializationBinding":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != INITIALIZATION_BINDING_SCHEMA:
            raise BoundaryContractError("unsupported InitializationBinding schema")
        if payload.pop("interface") != INITIALIZATION_BINDING_INTERFACE:
            raise BoundaryContractError(
                "unsupported InitializationBinding interface"
            )
        result = cls(**payload)
        _verify_cid(
            claimed, result.binding_cid, "InitializationBinding binding_cid"
        )
        return result


@dataclass(frozen=True, slots=True)
class ConcurrencyBinding:
    """Concurrency and atomicity obligation for one cut edge."""

    concurrency_id: str
    concurrency_kind: ConcurrencyKind | str
    atomicity: AtomicityKind | str
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    required: bool = True

    interface: ClassVar[str] = CONCURRENCY_BINDING_INTERFACE
    schema: ClassVar[str] = CONCURRENCY_BINDING_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "concurrency_id",
            "concurrency_kind",
            "atomicity",
            "evidence_class",
            "required",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "concurrency_id", _text(self.concurrency_id, "concurrency_id")
        )
        object.__setattr__(
            self,
            "concurrency_kind",
            _enum(self.concurrency_kind, ConcurrencyKind, "concurrency_kind"),
        )
        object.__setattr__(
            self, "atomicity", _enum(self.atomicity, AtomicityKind, "atomicity")
        )
        evidence = _evidence(self.evidence_class, "evidence_class")
        required = _bool(self.required, "required")
        if required:
            _reject_guessed_axiom(evidence, "ConcurrencyBinding")
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "required", required)
        if (
            self.concurrency_kind == ConcurrencyKind.RACE_UNKNOWN.value
            and self.atomicity == AtomicityKind.ATOMIC.value
            and required
        ):
            raise BoundaryContractError(
                "race_unknown concurrency cannot claim atomicity"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CONCURRENCY_BINDING_SCHEMA,
            "interface": CONCURRENCY_BINDING_INTERFACE,
            "concurrency_id": self.concurrency_id,
            "concurrency_kind": self.concurrency_kind,
            "atomicity": self.atomicity,
            "evidence_class": self.evidence_class,
            "required": self.required,
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["binding_cid"] = self.binding_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConcurrencyBinding":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != CONCURRENCY_BINDING_SCHEMA:
            raise BoundaryContractError("unsupported ConcurrencyBinding schema")
        if payload.pop("interface") != CONCURRENCY_BINDING_INTERFACE:
            raise BoundaryContractError("unsupported ConcurrencyBinding interface")
        result = cls(**payload)
        _verify_cid(claimed, result.binding_cid, "ConcurrencyBinding binding_cid")
        return result


@dataclass(frozen=True, slots=True)
class AuthorizationBinding:
    """Authorization obligation for one cut edge."""

    authorization_id: str
    authorization_kind: AuthorizationKind | str
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    required: bool = True

    interface: ClassVar[str] = AUTHORIZATION_BINDING_INTERFACE
    schema: ClassVar[str] = AUTHORIZATION_BINDING_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "authorization_id",
            "authorization_kind",
            "evidence_class",
            "required",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authorization_id",
            _text(self.authorization_id, "authorization_id"),
        )
        object.__setattr__(
            self,
            "authorization_kind",
            _enum(self.authorization_kind, AuthorizationKind, "authorization_kind"),
        )
        evidence = _evidence(self.evidence_class, "evidence_class")
        required = _bool(self.required, "required")
        if required:
            _reject_guessed_axiom(evidence, "AuthorizationBinding")
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "required", required)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": AUTHORIZATION_BINDING_SCHEMA,
            "interface": AUTHORIZATION_BINDING_INTERFACE,
            "authorization_id": self.authorization_id,
            "authorization_kind": self.authorization_kind,
            "evidence_class": self.evidence_class,
            "required": self.required,
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["binding_cid"] = self.binding_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AuthorizationBinding":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != AUTHORIZATION_BINDING_SCHEMA:
            raise BoundaryContractError("unsupported AuthorizationBinding schema")
        if payload.pop("interface") != AUTHORIZATION_BINDING_INTERFACE:
            raise BoundaryContractError(
                "unsupported AuthorizationBinding interface"
            )
        result = cls(**payload)
        _verify_cid(
            claimed, result.binding_cid, "AuthorizationBinding binding_cid"
        )
        return result


@dataclass(frozen=True, slots=True)
class SerializationBinding:
    """Serialization obligation for one cut edge."""

    serialization_id: str
    format: SerializationFormat | str
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    required: bool = True

    interface: ClassVar[str] = SERIALIZATION_BINDING_INTERFACE
    schema: ClassVar[str] = SERIALIZATION_BINDING_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "serialization_id",
            "format",
            "evidence_class",
            "required",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "serialization_id",
            _text(self.serialization_id, "serialization_id"),
        )
        object.__setattr__(
            self, "format", _enum(self.format, SerializationFormat, "format")
        )
        evidence = _evidence(self.evidence_class, "evidence_class")
        required = _bool(self.required, "required")
        if required:
            _reject_guessed_axiom(evidence, "SerializationBinding")
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "required", required)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SERIALIZATION_BINDING_SCHEMA,
            "interface": SERIALIZATION_BINDING_INTERFACE,
            "serialization_id": self.serialization_id,
            "format": self.format,
            "evidence_class": self.evidence_class,
            "required": self.required,
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["binding_cid"] = self.binding_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SerializationBinding":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != SERIALIZATION_BINDING_SCHEMA:
            raise BoundaryContractError("unsupported SerializationBinding schema")
        if payload.pop("interface") != SERIALIZATION_BINDING_INTERFACE:
            raise BoundaryContractError(
                "unsupported SerializationBinding interface"
            )
        result = cls(**payload)
        _verify_cid(
            claimed, result.binding_cid, "SerializationBinding binding_cid"
        )
        return result


@dataclass(frozen=True, slots=True)
class VersioningBinding:
    """Versioning obligation for one cut edge."""

    versioning_id: str
    version: str
    kind: VersioningKind | str = VersioningKind.STABLE
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    required: bool = True

    interface: ClassVar[str] = VERSIONING_BINDING_INTERFACE
    schema: ClassVar[str] = VERSIONING_BINDING_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "versioning_id",
            "version",
            "kind",
            "evidence_class",
            "required",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "versioning_id", _text(self.versioning_id, "versioning_id")
        )
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(self, "kind", _enum(self.kind, VersioningKind, "kind"))
        evidence = _evidence(self.evidence_class, "evidence_class")
        required = _bool(self.required, "required")
        if required:
            _reject_guessed_axiom(evidence, "VersioningBinding")
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "required", required)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": VERSIONING_BINDING_SCHEMA,
            "interface": VERSIONING_BINDING_INTERFACE,
            "versioning_id": self.versioning_id,
            "version": self.version,
            "kind": self.kind,
            "evidence_class": self.evidence_class,
            "required": self.required,
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["binding_cid"] = self.binding_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VersioningBinding":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != VERSIONING_BINDING_SCHEMA:
            raise BoundaryContractError("unsupported VersioningBinding schema")
        if payload.pop("interface") != VERSIONING_BINDING_INTERFACE:
            raise BoundaryContractError("unsupported VersioningBinding interface")
        result = cls(**payload)
        _verify_cid(claimed, result.binding_cid, "VersioningBinding binding_cid")
        return result


@dataclass(frozen=True, slots=True)
class ProofObligation:
    """Proof obligation attached to one cut-edge contract."""

    obligation_id: str
    kind: ProofObligationKind | str
    claim_id: str
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    required: bool = True

    interface: ClassVar[str] = PROOF_OBLIGATION_INTERFACE
    schema: ClassVar[str] = PROOF_OBLIGATION_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "obligation_id",
            "kind",
            "claim_id",
            "evidence_class",
            "required",
            "obligation_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _text(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "kind", _enum(self.kind, ProofObligationKind, "kind")
        )
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        evidence = _evidence(self.evidence_class, "evidence_class")
        required = _bool(self.required, "required")
        if required:
            _reject_guessed_axiom(evidence, "ProofObligation")
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "required", required)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PROOF_OBLIGATION_SCHEMA,
            "interface": PROOF_OBLIGATION_INTERFACE,
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "claim_id": self.claim_id,
            "evidence_class": self.evidence_class,
            "required": self.required,
        }

    @property
    def obligation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["obligation_cid"] = self.obligation_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProofObligation":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("obligation_cid")
        if payload.pop("schema") != PROOF_OBLIGATION_SCHEMA:
            raise BoundaryContractError("unsupported ProofObligation schema")
        if payload.pop("interface") != PROOF_OBLIGATION_INTERFACE:
            raise BoundaryContractError("unsupported ProofObligation interface")
        result = cls(**payload)
        _verify_cid(claimed, result.obligation_cid, "ProofObligation obligation_cid")
        return result


def _sorted_clauses(
    values: Sequence[AssumeGuaranteeClause | Mapping[str, Any]],
) -> tuple[AssumeGuaranteeClause, ...]:
    clauses = tuple(
        _coerce(item, AssumeGuaranteeClause, "clause") for item in values
    )
    ids = [item.clause_id for item in clauses]
    if len(ids) != len(set(ids)):
        raise BoundaryContractError("clause_id values must be unique")
    predicates: dict[tuple[str, str], str] = {}
    for item in clauses:
        key = (item.polarity, item.kind)
        previous = predicates.get(key)
        if previous is not None and previous != item.predicate_id:
            raise BoundaryContractError(
                "conflicting assume/guarantee predicates for the same polarity and kind"
            )
        predicates[key] = item.predicate_id
    return tuple(sorted(clauses, key=lambda item: item.clause_id))


def _sorted_effects(
    values: Sequence[EffectObligation | Mapping[str, Any]],
) -> tuple[EffectObligation, ...]:
    effects = tuple(_coerce(item, EffectObligation, "effect") for item in values)
    ids = [item.effect_id for item in effects]
    if len(ids) != len(set(ids)):
        raise BoundaryContractError("effect_id values must be unique")
    return tuple(sorted(effects, key=lambda item: item.effect_id))


def _sorted_exceptions(
    values: Sequence[ExceptionObligation | Mapping[str, Any]],
) -> tuple[ExceptionObligation, ...]:
    exceptions = tuple(
        _coerce(item, ExceptionObligation, "exception") for item in values
    )
    ids = [item.exception_id for item in exceptions]
    if len(ids) != len(set(ids)):
        raise BoundaryContractError("exception_id values must be unique")
    return tuple(sorted(exceptions, key=lambda item: item.exception_id))


def _sorted_proofs(
    values: Sequence[ProofObligation | Mapping[str, Any]],
) -> tuple[ProofObligation, ...]:
    proofs = tuple(_coerce(item, ProofObligation, "proof") for item in values)
    ids = [item.obligation_id for item in proofs]
    if len(ids) != len(set(ids)):
        raise BoundaryContractError("proof obligation_id values must be unique")
    return tuple(sorted(proofs, key=lambda item: item.obligation_id))


def _evidence_classes_of(contract: "ModuleBoundaryContract") -> tuple[str, ...]:
    classes = [contract.cut_edge.evidence_class]
    classes.extend(item.evidence_class for item in contract.clauses)
    classes.extend(item.evidence_class for item in contract.effects)
    classes.extend(item.evidence_class for item in contract.exceptions)
    classes.extend(item.evidence_class for item in contract.proof_obligations)
    for binding in (
        contract.state_resource_owner,
        contract.initialization,
        contract.concurrency,
        contract.authorization,
        contract.serialization,
        contract.versioning,
    ):
        if binding is not None:
            classes.append(binding.evidence_class)
    return tuple(classes)


def _dimension_present(contract: "ModuleBoundaryContract", dimension: str) -> bool:
    if dimension == "assumptions":
        return any(
            item.polarity == ClausePolarity.ASSUME.value for item in contract.clauses
        )
    if dimension == "guarantees":
        return any(
            item.polarity == ClausePolarity.GUARANTEE.value
            for item in contract.clauses
        )
    if dimension == "inputs":
        return any(item.kind == ClauseKind.INPUT.value for item in contract.clauses)
    if dimension == "outputs":
        return any(item.kind == ClauseKind.OUTPUT.value for item in contract.clauses)
    if dimension == "conditions":
        return any(
            item.kind == ClauseKind.CONDITION.value for item in contract.clauses
        )
    if dimension == "invariants":
        return any(
            item.kind == ClauseKind.INVARIANT.value for item in contract.clauses
        )
    if dimension == "exceptions":
        return bool(contract.exceptions)
    if dimension == "allowed_effects":
        return any(
            item.polarity == EffectPolarity.ALLOWED.value for item in contract.effects
        )
    if dimension == "forbidden_effects":
        return any(
            item.polarity == EffectPolarity.FORBIDDEN.value
            for item in contract.effects
        )
    if dimension == "state_resource_owner":
        return contract.state_resource_owner is not None
    if dimension == "initialization":
        return contract.initialization is not None
    if dimension == "concurrency":
        return contract.concurrency is not None
    if dimension == "authorization":
        return contract.authorization is not None
    if dimension == "serialization":
        return contract.serialization is not None
    if dimension == "versioning":
        return contract.versioning is not None
    if dimension == "proof_obligations":
        return bool(contract.proof_obligations)
    raise BoundaryContractError(f"unknown contract dimension {dimension}")


def _disposition_for(contract: "ModuleBoundaryContract") -> str:
    missing = contract.missing_dimensions
    evidence = _evidence_classes_of(contract)
    if missing:
        if any(item in _ABSTAIN_EVIDENCE for item in evidence):
            return ContractDisposition.ABSTENTION.value
        if any(item in _PROOF_EVIDENCE for item in evidence):
            return ContractDisposition.PROOF.value
        if any(item in _REVIEW_EVIDENCE for item in evidence):
            return ContractDisposition.REVIEW.value
        return ContractDisposition.RETRIEVAL.value
    if any(item in _ABSTAIN_EVIDENCE for item in evidence):
        return ContractDisposition.ABSTENTION.value
    if any(
        item in _PROOF_EVIDENCE and item != EvidenceClass.RECONSTRUCTED_PROOF.value
        for item in evidence
    ):
        return ContractDisposition.PROOF.value
    if any(item in _REVIEW_EVIDENCE for item in evidence):
        return ContractDisposition.REVIEW.value
    return ContractDisposition.ADMITTED.value


@dataclass(frozen=True, slots=True)
class ModuleBoundaryContract:
    """Assume/guarantee contract for exactly one cut edge.

    Predicted SPAR-016 symbol: ``ModuleBoundaryContract@1``.
    """

    cut_edge: CutEdge
    clauses: Sequence[AssumeGuaranteeClause] = ()
    effects: Sequence[EffectObligation] = ()
    exceptions: Sequence[ExceptionObligation] = ()
    state_resource_owner: StateResourceOwnerBinding | None = None
    initialization: InitializationBinding | None = None
    concurrency: ConcurrencyBinding | None = None
    authorization: AuthorizationBinding | None = None
    serialization: SerializationBinding | None = None
    versioning: VersioningBinding | None = None
    proof_obligations: Sequence[ProofObligation] = ()

    interface: ClassVar[str] = MODULE_BOUNDARY_CONTRACT_INTERFACE
    schema: ClassVar[str] = MODULE_BOUNDARY_CONTRACT_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "cut_edge",
            "clauses",
            "effects",
            "exceptions",
            "state_resource_owner",
            "initialization",
            "concurrency",
            "authorization",
            "serialization",
            "versioning",
            "proof_obligations",
            "missing_dimensions",
            "disposition",
            "complete",
            "authorizes_completion",
            "authorizes_transition",
            "contract_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "cut_edge", _coerce(self.cut_edge, CutEdge, "cut_edge")
        )
        clauses = _sorted_clauses(
            _sequence(self.clauses, "clauses", limit=MAX_CLAUSES)
        )
        effects = _sorted_effects(
            _sequence(self.effects, "effects", limit=MAX_EFFECTS)
        )
        exceptions = _sorted_exceptions(
            _sequence(self.exceptions, "exceptions", limit=MAX_EXCEPTIONS)
        )
        proofs = _sorted_proofs(
            _sequence(self.proof_obligations, "proof_obligations", limit=MAX_PROOFS)
        )
        object.__setattr__(self, "clauses", clauses)
        object.__setattr__(self, "effects", effects)
        object.__setattr__(self, "exceptions", exceptions)
        object.__setattr__(self, "proof_obligations", proofs)
        object.__setattr__(
            self,
            "state_resource_owner",
            _optional_coerce(
                self.state_resource_owner,
                StateResourceOwnerBinding,
                "state_resource_owner",
            ),
        )
        object.__setattr__(
            self,
            "initialization",
            _optional_coerce(
                self.initialization, InitializationBinding, "initialization"
            ),
        )
        object.__setattr__(
            self,
            "concurrency",
            _optional_coerce(self.concurrency, ConcurrencyBinding, "concurrency"),
        )
        object.__setattr__(
            self,
            "authorization",
            _optional_coerce(
                self.authorization, AuthorizationBinding, "authorization"
            ),
        )
        object.__setattr__(
            self,
            "serialization",
            _optional_coerce(
                self.serialization, SerializationBinding, "serialization"
            ),
        )
        object.__setattr__(
            self,
            "versioning",
            _optional_coerce(self.versioning, VersioningBinding, "versioning"),
        )

    @property
    def assumptions(self) -> tuple[AssumeGuaranteeClause, ...]:
        return tuple(
            item
            for item in self.clauses
            if item.polarity == ClausePolarity.ASSUME.value
        )

    @property
    def guarantees(self) -> tuple[AssumeGuaranteeClause, ...]:
        return tuple(
            item
            for item in self.clauses
            if item.polarity == ClausePolarity.GUARANTEE.value
        )

    @property
    def allowed_effects(self) -> tuple[EffectObligation, ...]:
        return tuple(
            item
            for item in self.effects
            if item.polarity == EffectPolarity.ALLOWED.value
        )

    @property
    def forbidden_effects(self) -> tuple[EffectObligation, ...]:
        return tuple(
            item
            for item in self.effects
            if item.polarity == EffectPolarity.FORBIDDEN.value
        )

    @property
    def missing_dimensions(self) -> tuple[str, ...]:
        return tuple(
            dimension
            for dimension in REQUIRED_CONTRACT_DIMENSIONS
            if not _dimension_present(self, dimension)
        )

    @property
    def complete(self) -> bool:
        return not self.missing_dimensions

    @property
    def disposition(self) -> str:
        return _disposition_for(self)

    @property
    def authorizes_completion(self) -> bool:
        return False

    @property
    def authorizes_transition(self) -> bool:
        return False

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MODULE_BOUNDARY_CONTRACT_SCHEMA,
            "interface": MODULE_BOUNDARY_CONTRACT_INTERFACE,
            "cut_edge": self.cut_edge.identity_payload(),
            "clauses": [item.identity_payload() for item in self.clauses],
            "effects": [item.identity_payload() for item in self.effects],
            "exceptions": [item.identity_payload() for item in self.exceptions],
            "state_resource_owner": (
                None
                if self.state_resource_owner is None
                else self.state_resource_owner.identity_payload()
            ),
            "initialization": (
                None
                if self.initialization is None
                else self.initialization.identity_payload()
            ),
            "concurrency": (
                None
                if self.concurrency is None
                else self.concurrency.identity_payload()
            ),
            "authorization": (
                None
                if self.authorization is None
                else self.authorization.identity_payload()
            ),
            "serialization": (
                None
                if self.serialization is None
                else self.serialization.identity_payload()
            ),
            "versioning": (
                None if self.versioning is None else self.versioning.identity_payload()
            ),
            "proof_obligations": [
                item.identity_payload() for item in self.proof_obligations
            ],
        }

    @property
    def contract_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MODULE_BOUNDARY_CONTRACT_SCHEMA,
            "interface": MODULE_BOUNDARY_CONTRACT_INTERFACE,
            "cut_edge": self.cut_edge.to_dict(),
            "clauses": [item.to_dict() for item in self.clauses],
            "effects": [item.to_dict() for item in self.effects],
            "exceptions": [item.to_dict() for item in self.exceptions],
            "state_resource_owner": (
                None
                if self.state_resource_owner is None
                else self.state_resource_owner.to_dict()
            ),
            "initialization": (
                None if self.initialization is None else self.initialization.to_dict()
            ),
            "concurrency": (
                None if self.concurrency is None else self.concurrency.to_dict()
            ),
            "authorization": (
                None
                if self.authorization is None
                else self.authorization.to_dict()
            ),
            "serialization": (
                None if self.serialization is None else self.serialization.to_dict()
            ),
            "versioning": (
                None if self.versioning is None else self.versioning.to_dict()
            ),
            "proof_obligations": [
                item.to_dict() for item in self.proof_obligations
            ],
            "missing_dimensions": list(self.missing_dimensions),
            "disposition": self.disposition,
            "complete": self.complete,
            "authorizes_completion": False,
            "authorizes_transition": False,
            "contract_cid": self.contract_cid,
        }

    def evaluate(self) -> "BoundaryTerminal":
        disposition = self.disposition
        if disposition == ContractDisposition.ADMITTED.value:
            return BoundaryTerminal(
                kind=BoundaryTerminalKind.ADMITTED,
                reason="cut edge has a complete assume/guarantee contract",
                required=True,
                edge_ids=(self.cut_edge.edge_id,),
                contract_ids=(self.contract_cid,),
                disposition=disposition,
            )
        if disposition == ContractDisposition.ABSTENTION.value:
            kind = BoundaryTerminalKind.UNKNOWN_REQUIRED
            reason = "incomplete authoritative contract requires abstention"
        elif disposition == ContractDisposition.PROOF.value:
            kind = BoundaryTerminalKind.INCOMPLETE_CONTRACT
            reason = "incomplete authoritative contract requires proof"
        elif disposition == ContractDisposition.REVIEW.value:
            kind = BoundaryTerminalKind.INCOMPLETE_CONTRACT
            reason = "incomplete authoritative contract requires review"
        else:
            kind = BoundaryTerminalKind.INCOMPLETE_CONTRACT
            reason = "incomplete authoritative contract requires retrieval"
        return BoundaryTerminal(
            kind=kind,
            reason=reason,
            required=True,
            edge_ids=(self.cut_edge.edge_id,),
            contract_ids=(self.contract_cid,),
            disposition=disposition,
            missing_dimensions=self.missing_dimensions,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModuleBoundaryContract":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("contract_cid")
        claimed_missing = payload.pop("missing_dimensions")
        claimed_disposition = payload.pop("disposition")
        claimed_complete = payload.pop("complete")
        claimed_completion = payload.pop("authorizes_completion")
        claimed_transition = payload.pop("authorizes_transition")
        if payload.pop("schema") != MODULE_BOUNDARY_CONTRACT_SCHEMA:
            raise BoundaryContractError("unsupported ModuleBoundaryContract schema")
        if payload.pop("interface") != MODULE_BOUNDARY_CONTRACT_INTERFACE:
            raise BoundaryContractError(
                "unsupported ModuleBoundaryContract interface"
            )
        if claimed_completion is not False:
            raise BoundaryContractError(
                "ModuleBoundaryContract cannot authorize completion"
            )
        if claimed_transition is not False:
            raise BoundaryContractError(
                "ModuleBoundaryContract cannot authorize transition"
            )
        result = cls(**payload)
        if list(claimed_missing) != list(result.missing_dimensions):
            raise BoundaryContractError("missing_dimensions does not match")
        if claimed_disposition != result.disposition:
            raise BoundaryContractError("disposition does not match")
        if claimed_complete is not result.complete:
            raise BoundaryContractError("complete does not match")
        _verify_cid(claimed, result.contract_cid, "ModuleBoundaryContract contract_cid")
        return result


@dataclass(frozen=True, slots=True)
class BoundaryTerminal:
    """Typed evaluation of one contract or contract set. Never completion."""

    kind: BoundaryTerminalKind | str
    reason: str
    required: bool
    edge_ids: Sequence[str] = ()
    contract_ids: Sequence[str] = ()
    disposition: ContractDisposition | str | None = None
    missing_dimensions: Sequence[str] = ()

    interface: ClassVar[str] = BOUNDARY_TERMINAL_INTERFACE
    schema: ClassVar[str] = BOUNDARY_TERMINAL_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "kind",
            "reason",
            "required",
            "edge_ids",
            "contract_ids",
            "disposition",
            "missing_dimensions",
            "success",
            "authorizes_completion",
            "terminal_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(self.kind, BoundaryTerminalKind, "kind")
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(self, "required", _bool(self.required, "required"))
        object.__setattr__(
            self, "edge_ids", _unique_sorted(self.edge_ids, "edge_id")
        )
        object.__setattr__(
            self, "contract_ids", _unique_sorted(self.contract_ids, "contract_id")
        )
        if self.disposition is None:
            object.__setattr__(self, "disposition", None)
        else:
            object.__setattr__(
                self,
                "disposition",
                _enum(self.disposition, ContractDisposition, "disposition"),
            )
        missing = tuple(
            _text(item, "missing_dimension") for item in self.missing_dimensions
        )
        unknown = set(missing) - set(REQUIRED_CONTRACT_DIMENSIONS)
        if unknown:
            raise BoundaryContractError(
                f"unknown missing dimensions: {sorted(unknown)}"
            )
        object.__setattr__(self, "missing_dimensions", missing)
        if self.kind == BoundaryTerminalKind.ADMITTED.value:
            if not self.edge_ids and not self.contract_ids:
                raise BoundaryContractError(
                    "admitted terminals must name at least one subject"
                )
            if self.missing_dimensions:
                raise BoundaryContractError(
                    "admitted terminals cannot report missing dimensions"
                )
        if (
            self.kind != BoundaryTerminalKind.ADMITTED.value
            and self.success
        ):
            raise BoundaryContractError(
                "non-admitted terminals cannot report success"
            )

    @property
    def success(self) -> bool:
        return self.kind == BoundaryTerminalKind.ADMITTED.value

    @property
    def authorizes_completion(self) -> bool:
        return False

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": BOUNDARY_TERMINAL_SCHEMA,
            "interface": BOUNDARY_TERMINAL_INTERFACE,
            "kind": self.kind,
            "reason": self.reason,
            "required": self.required,
            "edge_ids": list(self.edge_ids),
            "contract_ids": list(self.contract_ids),
            "disposition": self.disposition,
            "missing_dimensions": list(self.missing_dimensions),
        }

    @property
    def terminal_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["success"] = self.success
        payload["authorizes_completion"] = False
        payload["terminal_cid"] = self.terminal_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BoundaryTerminal":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("terminal_cid")
        claimed_success = payload.pop("success")
        claimed_completion = payload.pop("authorizes_completion")
        if payload.pop("schema") != BOUNDARY_TERMINAL_SCHEMA:
            raise BoundaryContractError("unsupported BoundaryTerminal schema")
        if payload.pop("interface") != BOUNDARY_TERMINAL_INTERFACE:
            raise BoundaryContractError("unsupported BoundaryTerminal interface")
        if claimed_completion is not False:
            raise BoundaryContractError(
                "BoundaryTerminal cannot authorize completion"
            )
        result = cls(**payload)
        if claimed_success is not result.success:
            raise BoundaryContractError("success does not match")
        _verify_cid(claimed, result.terminal_cid, "BoundaryTerminal terminal_cid")
        return result


def _merge_terminals(
    terminals: Sequence[BoundaryTerminal],
) -> BoundaryTerminal:
    if not terminals:
        raise BoundaryContractError("evaluation requires at least one terminal")
    by_kind = {item.kind: item for item in terminals}
    for kind in _TERMINAL_PRECEDENCE:
        if kind.value in by_kind and kind is not BoundaryTerminalKind.ADMITTED:
            matching = [item for item in terminals if item.kind == kind.value]
            return BoundaryTerminal(
                kind=kind,
                reason=matching[0].reason,
                required=any(item.required for item in matching),
                edge_ids=tuple(eid for item in matching for eid in item.edge_ids),
                contract_ids=tuple(
                    cid for item in matching for cid in item.contract_ids
                ),
                disposition=matching[0].disposition,
                missing_dimensions=tuple(
                    dim for item in matching for dim in item.missing_dimensions
                ),
            )
    admitted = [
        item
        for item in terminals
        if item.kind == BoundaryTerminalKind.ADMITTED.value
    ]
    return BoundaryTerminal(
        kind=BoundaryTerminalKind.ADMITTED,
        reason="every cut edge has a complete assume/guarantee contract",
        required=any(item.required for item in admitted),
        edge_ids=tuple(eid for item in admitted for eid in item.edge_ids),
        contract_ids=tuple(cid for item in admitted for cid in item.contract_ids),
        disposition=ContractDisposition.ADMITTED,
    )


@dataclass(frozen=True, slots=True)
class BoundaryContractSet:
    """Content-addressed set of module-boundary contracts for one partition."""

    tree_id: str
    source_cid: str
    partition_cid: str
    contracts: Sequence[ModuleBoundaryContract] = ()

    interface: ClassVar[str] = BOUNDARY_CONTRACT_SET_INTERFACE
    schema: ClassVar[str] = BOUNDARY_CONTRACT_SET_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "tree_id",
            "source_cid",
            "partition_cid",
            "contracts",
            "edge_ids",
            "covered_dimensions",
            "dispositions",
            "complete",
            "authorizes_completion",
            "authorizes_transition",
            "set_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "tree_id", _tree_id(self.tree_id))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self, "partition_cid", _cid(self.partition_cid, "partition_cid")
        )
        contracts = tuple(
            _coerce(item, ModuleBoundaryContract, "contract")
            for item in _sequence(self.contracts, "contracts", limit=MAX_CONTRACTS)
        )
        edge_ids = [item.cut_edge.edge_id for item in contracts]
        if len(edge_ids) != len(set(edge_ids)):
            raise BoundaryContractError("cut edge_id values must be unique")
        keys = [
            (
                item.cut_edge.producer_module,
                item.cut_edge.consumer_module,
                item.cut_edge.producer_symbol,
            )
            for item in contracts
        ]
        if len(keys) != len(set(keys)):
            raise BoundaryContractError(
                "producer/consumer/symbol cut edges must be unique"
            )
        owners: dict[str, StateResourceOwnerBinding] = {}
        for item in contracts:
            owner = item.state_resource_owner
            if owner is None:
                continue
            previous = owners.get(owner.owner_id)
            if previous is None:
                owners[owner.owner_id] = owner
                continue
            unique = StateUniqueness.UNIQUE.value
            if previous.binding_cid == owner.binding_cid:
                continue
            if previous.uniqueness == unique or owner.uniqueness == unique:
                raise BoundaryContractError(
                    "overlapping unique state/resource owners fail closed"
                )
        object.__setattr__(
            self,
            "contracts",
            tuple(sorted(contracts, key=lambda item: item.cut_edge.edge_id)),
        )

    @property
    def edge_ids(self) -> tuple[str, ...]:
        return tuple(item.cut_edge.edge_id for item in self.contracts)

    @property
    def covered_dimensions(self) -> tuple[str, ...]:
        if not self.contracts:
            return ()
        present = [
            dimension
            for dimension in REQUIRED_CONTRACT_DIMENSIONS
            if all(_dimension_present(item, dimension) for item in self.contracts)
        ]
        return tuple(present)

    @property
    def dispositions(self) -> tuple[str, ...]:
        return tuple(sorted({item.disposition for item in self.contracts}))

    @property
    def complete(self) -> bool:
        return bool(self.contracts) and all(item.complete for item in self.contracts)

    @property
    def authorizes_completion(self) -> bool:
        return False

    @property
    def authorizes_transition(self) -> bool:
        return False

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": BOUNDARY_CONTRACT_SET_SCHEMA,
            "interface": BOUNDARY_CONTRACT_SET_INTERFACE,
            "tree_id": self.tree_id,
            "source_cid": self.source_cid,
            "partition_cid": self.partition_cid,
            "contracts": [item.identity_payload() for item in self.contracts],
        }

    @property
    def set_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": BOUNDARY_CONTRACT_SET_SCHEMA,
            "interface": BOUNDARY_CONTRACT_SET_INTERFACE,
            "tree_id": self.tree_id,
            "source_cid": self.source_cid,
            "partition_cid": self.partition_cid,
            "contracts": [item.to_dict() for item in self.contracts],
            "edge_ids": list(self.edge_ids),
            "covered_dimensions": list(self.covered_dimensions),
            "dispositions": list(self.dispositions),
            "complete": self.complete,
            "authorizes_completion": False,
            "authorizes_transition": False,
            "set_cid": self.set_cid,
        }

    def contract_for_edge(self, edge_id: str) -> ModuleBoundaryContract:
        wanted = _text(edge_id, "edge_id")
        for item in self.contracts:
            if item.cut_edge.edge_id == wanted:
                return item
        raise BoundaryContractError(f"no contract for cut edge {wanted}")

    def evaluate(self) -> BoundaryTerminal:
        if not self.contracts:
            return BoundaryTerminal(
                kind=BoundaryTerminalKind.INCOMPLETE_CONTRACT,
                reason="boundary contract set requires declared cut edges",
                required=True,
                disposition=ContractDisposition.RETRIEVAL,
            )
        return _merge_terminals(tuple(item.evaluate() for item in self.contracts))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BoundaryContractSet":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("set_cid")
        claimed_edges = payload.pop("edge_ids")
        claimed_dimensions = payload.pop("covered_dimensions")
        claimed_dispositions = payload.pop("dispositions")
        claimed_complete = payload.pop("complete")
        claimed_completion = payload.pop("authorizes_completion")
        claimed_transition = payload.pop("authorizes_transition")
        if payload.pop("schema") != BOUNDARY_CONTRACT_SET_SCHEMA:
            raise BoundaryContractError("unsupported BoundaryContractSet schema")
        if payload.pop("interface") != BOUNDARY_CONTRACT_SET_INTERFACE:
            raise BoundaryContractError("unsupported BoundaryContractSet interface")
        if claimed_completion is not False:
            raise BoundaryContractError(
                "BoundaryContractSet cannot authorize completion"
            )
        if claimed_transition is not False:
            raise BoundaryContractError(
                "BoundaryContractSet cannot authorize transition"
            )
        result = cls(**payload)
        if list(claimed_edges) != list(result.edge_ids):
            raise BoundaryContractError("edge_ids does not match")
        if list(claimed_dimensions) != list(result.covered_dimensions):
            raise BoundaryContractError("covered_dimensions does not match")
        if list(claimed_dispositions) != list(result.dispositions):
            raise BoundaryContractError("dispositions does not match")
        if claimed_complete is not result.complete:
            raise BoundaryContractError("complete does not match")
        _verify_cid(claimed, result.set_cid, "BoundaryContractSet set_cid")
        return result


def synthesize_boundary_contract(
    cut_edge: CutEdge | Mapping[str, Any],
    *,
    clauses: Sequence[AssumeGuaranteeClause | Mapping[str, Any]] = (),
    effects: Sequence[EffectObligation | Mapping[str, Any]] = (),
    exceptions: Sequence[ExceptionObligation | Mapping[str, Any]] = (),
    state_resource_owner: StateResourceOwnerBinding | Mapping[str, Any] | None = None,
    initialization: InitializationBinding | Mapping[str, Any] | None = None,
    concurrency: ConcurrencyBinding | Mapping[str, Any] | None = None,
    authorization: AuthorizationBinding | Mapping[str, Any] | None = None,
    serialization: SerializationBinding | Mapping[str, Any] | None = None,
    versioning: VersioningBinding | Mapping[str, Any] | None = None,
    proof_obligations: Sequence[ProofObligation | Mapping[str, Any]] = (),
) -> ModuleBoundaryContract:
    """Synthesize one cut-edge contract. Missing facts stay incomplete."""

    return ModuleBoundaryContract(
        cut_edge=cut_edge,
        clauses=clauses,
        effects=effects,
        exceptions=exceptions,
        state_resource_owner=state_resource_owner,
        initialization=initialization,
        concurrency=concurrency,
        authorization=authorization,
        serialization=serialization,
        versioning=versioning,
        proof_obligations=proof_obligations,
    )


def synthesize_boundary_contracts(
    cut_edges: Sequence[CutEdge | Mapping[str, Any]],
    *,
    tree_id: str,
    source_cid: str,
    partition_cid: str,
    contracts: Sequence[ModuleBoundaryContract | Mapping[str, Any]] | None = None,
) -> BoundaryContractSet:
    """Synthesize contracts for every cut edge without guessing axioms."""

    edges = tuple(
        _coerce(item, CutEdge, "cut_edge")
        for item in _sequence(cut_edges, "cut_edges", limit=MAX_EDGES)
    )
    if contracts is None:
        synthesized = tuple(synthesize_boundary_contract(edge) for edge in edges)
    else:
        synthesized = tuple(
            _coerce(item, ModuleBoundaryContract, "contract") for item in contracts
        )
        declared = {item.edge_id for item in edges}
        covered = {item.cut_edge.edge_id for item in synthesized}
        if declared != covered:
            raise BoundaryContractError(
                "contracts must cover exactly the declared cut edges"
            )
    return BoundaryContractSet(
        tree_id=tree_id,
        source_cid=source_cid,
        partition_cid=partition_cid,
        contracts=synthesized,
    )


def provider_free_exports() -> tuple[str, ...]:
    """Return the sorted public export surface (no provider or model names)."""

    return tuple(sorted(__all__))


def assert_not_competing_capsule_family() -> None:
    defined = {
        name
        for name, value in globals().items()
        if isinstance(value, type) and name in _FORBIDDEN_CAPSULE_TYPE_NAMES
    }
    if defined:
        raise BoundaryContractError(
            f"boundary contracts must not define capsule-family types: {sorted(defined)}"
        )


assert_not_competing_capsule_family()
assert MODULE_BOUNDARY_CONTRACT_INTERFACE == "ModuleBoundaryContract@1"
assert BOUNDARY_CONTRACT_SET_INTERFACE == "BoundaryContractSet@1"
assert TASK_ID == "SPAR-016"
assert BOUNDARY_CAN_AUTHORIZE_COMPLETION is False
assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
assert GUESSED_AXIOMS_REJECTED is True
assert GUESSED_AXIOM_DISPOSITIONS == frozenset()
validate_structured_value(
    {
        "schema": MODULE_BOUNDARY_CONTRACT_SCHEMA,
        "task_id": TASK_ID,
        "authority_owner": AUTHORITY_OWNER,
    }
)


__all__ = [
    "ANALYZER_ID",
    "ASSUME_GUARANTEE_CLAUSE_INTERFACE",
    "ASSUME_GUARANTEE_CLAUSE_SCHEMA",
    "AUTHORIZATION_BINDING_INTERFACE",
    "AUTHORIZATION_BINDING_SCHEMA",
    "AUTHORITY",
    "AUTHORITY_OWNER",
    "BOUNDARY_CAN_AUTHORIZE_COMPLETION",
    "BOUNDARY_CAN_AUTHORIZE_TRANSITION",
    "BOUNDARY_CAN_CREATE_AUTHORITY",
    "BOUNDARY_CID_CODEC",
    "BOUNDARY_CID_PROFILE",
    "BOUNDARY_CONTRACT_SET_INTERFACE",
    "BOUNDARY_CONTRACT_SET_SCHEMA",
    "BOUNDARY_CONTRACT_VERSION",
    "BOUNDARY_TERMINAL_INTERFACE",
    "BOUNDARY_TERMINAL_SCHEMA",
    "CONCURRENCY_BINDING_INTERFACE",
    "CONCURRENCY_BINDING_SCHEMA",
    "CUT_EDGE_INTERFACE",
    "CUT_EDGE_SCHEMA",
    "DECLARED_CLAUSE_KINDS",
    "DECLARED_CLAUSE_POLARITIES",
    "DECLARED_CUT_EDGE_KINDS",
    "DECLARED_DISPOSITIONS",
    "DECLARED_EFFECT_POLARITIES",
    "DUCKLAKE_IS_AUTHORITY",
    "EFFECT_OBLIGATION_INTERFACE",
    "EFFECT_OBLIGATION_SCHEMA",
    "EXCEPTION_OBLIGATION_INTERFACE",
    "EXCEPTION_OBLIGATION_SCHEMA",
    "GOAL_ID",
    "GUESSED_AXIOMS_REJECTED",
    "GUESSED_AXIOM_DISPOSITIONS",
    "IDENTITY_EXCLUDED_FIELDS",
    "INCOMPLETE_CONTRACTS_ARE_NOT_GUESSED",
    "INCOMPLETE_DISPOSITIONS",
    "INITIALIZATION_BINDING_INTERFACE",
    "INITIALIZATION_BINDING_SCHEMA",
    "MARKDOWN_IS_NOT_COMPLETION",
    "MODEL_OUTPUT_IS_PROPOSAL_ONLY",
    "MODULE_BOUNDARY_CONTRACT_INTERFACE",
    "MODULE_BOUNDARY_CONTRACT_SCHEMA",
    "PROGRAM",
    "PROOF_OBLIGATION_INTERFACE",
    "PROOF_OBLIGATION_SCHEMA",
    "REQUIRED_CONTRACT_DIMENSIONS",
    "SERIALIZATION_BINDING_INTERFACE",
    "SERIALIZATION_BINDING_SCHEMA",
    "STATE_RESOURCE_OWNER_BINDING_INTERFACE",
    "STATE_RESOURCE_OWNER_BINDING_SCHEMA",
    "TASK_ID",
    "TEST_PASS_IS_NOT_COMPLETION",
    "UNIQUE_OWNER_REQUIRES_EXACT_EVIDENCE",
    "VECTOR_SIMILARITY_IS_AUTHORITY",
    "VERSIONING_BINDING_INTERFACE",
    "VERSIONING_BINDING_SCHEMA",
    "WORKER_SELF_APPROVAL",
    "AssumeGuaranteeClause",
    "AtomicityKind",
    "AuthorizationBinding",
    "AuthorizationKind",
    "BoundaryContractError",
    "BoundaryContractSet",
    "BoundaryTerminal",
    "BoundaryTerminalKind",
    "ClauseKind",
    "ClausePolarity",
    "ConcurrencyBinding",
    "ConcurrencyKind",
    "ContractDisposition",
    "CutEdge",
    "CutEdgeKind",
    "EffectClass",
    "EffectObligation",
    "EffectPolarity",
    "ExceptionObligation",
    "InitializationBinding",
    "ModuleBoundaryContract",
    "ProofObligation",
    "ProofObligationKind",
    "SerializationBinding",
    "StateResourceOwnerBinding",
    "VersioningBinding",
    "VersioningKind",
    "provider_free_exports",
    "synthesize_boundary_contract",
    "synthesize_boundary_contracts",
]
