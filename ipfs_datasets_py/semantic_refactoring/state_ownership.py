"""SPAR-009 state ownership, aliasing, lifecycle, and synchronization.

This module extends current ``ipfs_datasets_py`` semantic authority with
``StateOwnershipGraph@1`` and ``StateExtractionCandidate@1``.  It does not replace
capsule, identity, program-graph, or dynamic-frontier contracts, does
not mint a second content-identity profile, and does not import or export
providers, models, or completion authority.

Normative rules:

* Exact static facts and conservative may-facts stay distinct evidence classes.
* Alias sets, owner candidates, read/write summaries, lifecycle, and
  synchronization relations are closed records.
* Unique mutable owners cannot be duplicated; overlapping unique owners fail
  closed.
* Missing release is recorded as absent, never guessed.
* Model, vector, and heuristic output cannot prove unique ownership.
* Observational metadata is excluded from identity.
* Admitted extraction candidates are nominations only and cannot authorize a
  transition or completion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, Mapping, Sequence
import ast
import json
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    PROFILE_ID,
    STRUCTURED_CODEC,
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
)
from ipfs_datasets_py.semantic_refactoring.capsules import (
    EvidenceClass,
    ResourceKind,
    StateOwnerKind,
    StateUniqueness,
)


TASK_ID: Final[str] = "SPAR-009"
GOAL_ID: Final[str] = "SPAR-G022"
PROGRAM: Final[str] = "semantic-preserving-autonomous-remodularization-v1"
AUTHORITY: Final[str] = "formal semantic authority"
AUTHORITY_OWNER: Final[str] = "ipfs_datasets_py"
ANALYZER_ID: Final[str] = "ipfs_datasets_py.semantic_refactoring.state_ownership@1"

STATE_OWNERSHIP_GRAPH_INTERFACE: Final[str] = "StateOwnershipGraph@1"
STATE_EXTRACTION_CANDIDATE_INTERFACE: Final[str] = "StateExtractionCandidate@1"
READ_WRITE_SUMMARY_INTERFACE: Final[str] = "ReadWriteSummary@1"
ALIAS_SET_INTERFACE: Final[str] = "AliasSet@1"
OWNER_CANDIDATE_INTERFACE: Final[str] = "OwnerCandidate@1"
LIFECYCLE_RELATION_INTERFACE: Final[str] = "LifecycleRelation@1"
SYNCHRONIZATION_RELATION_INTERFACE: Final[str] = "SynchronizationRelation@1"
UNRESOLVED_STATE_ITEM_INTERFACE: Final[str] = "UnresolvedStateItem@1"

STATE_OWNERSHIP_GRAPH_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.state-ownership-graph@1"
)
STATE_EXTRACTION_CANDIDATE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.state-extraction-candidate@1"
)
READ_WRITE_SUMMARY_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.read-write-summary@1"
)
ALIAS_SET_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.alias-set@1"
)
OWNER_CANDIDATE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.owner-candidate@1"
)
LIFECYCLE_RELATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.lifecycle-relation@1"
)
SYNCHRONIZATION_RELATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.synchronization-relation@1"
)
UNRESOLVED_STATE_ITEM_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.unresolved-state-item@1"
)

STATE_CONTRACT_VERSION: Final[str] = "1"
STATE_CID_CODEC: Final[str] = STRUCTURED_CODEC
STATE_CID_PROFILE: Final[str] = PROFILE_ID

STATE_CAN_AUTHORIZE_TRANSITION: Final[bool] = False
STATE_CAN_AUTHORIZE_COMPLETION: Final[bool] = False
STATE_CAN_CREATE_AUTHORITY: Final[bool] = False
VECTOR_SIMILARITY_IS_AUTHORITY: Final[bool] = False
MODEL_OUTPUT_IS_PROPOSAL_ONLY: Final[bool] = True
TEST_PASS_IS_NOT_COMPLETION: Final[bool] = True
MARKDOWN_IS_NOT_COMPLETION: Final[bool] = True
WORKER_SELF_APPROVAL: Final[bool] = False
DUCKLAKE_IS_AUTHORITY: Final[bool] = False
DUPLICATED_MUTABLE_STATE_REJECTED: Final[bool] = True
MISSING_RELEASE_IS_NOT_GUESSED: Final[bool] = True
UNKNOWN_UNIQUENESS_WIDENS_FRONTIER: Final[bool] = True

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
        "model",
        "provider",
        "lease",
        "fence",
        "generation",
        "receipt",
        "acceptance",
    }
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_OWNERS: Final[int] = 4_096
MAX_ALIAS_SETS: Final[int] = 4_096
MAX_ALIAS_MEMBERS: Final[int] = 4_096
MAX_SUMMARIES: Final[int] = 8_192
MAX_RELATIONS: Final[int] = 8_192
MAX_CANDIDATES: Final[int] = 4_096
MAX_FRONTIER_ITEMS: Final[int] = 8_192
MAX_NAMES: Final[int] = 8_192

_EXACT_EVIDENCE: Final[frozenset[str]] = frozenset(
    {EvidenceClass.EXACT_STATIC_FACT.value}
)
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
_NON_AUTHORITATIVE_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        EvidenceClass.VECTOR_CANDIDATE.value,
        EvidenceClass.MODEL_HYPOTHESIS.value,
    }
)

_MUTABLE_CTORS: Final[frozenset[str]] = frozenset(
    {
        "dict",
        "list",
        "set",
        "bytearray",
        "deque",
        "defaultdict",
        "OrderedDict",
        "Counter",
        "Lock",
        "RLock",
        "Condition",
        "Event",
        "Semaphore",
        "BoundedSemaphore",
        "Barrier",
        "ContextVar",
        "local",
    }
)
_LOCK_CTORS: Final[frozenset[str]] = frozenset(
    {
        "Lock",
        "RLock",
        "Condition",
        "Semaphore",
        "BoundedSemaphore",
        "Barrier",
        "Event",
    }
)
_CONTEXTVAR_CTORS: Final[frozenset[str]] = frozenset({"ContextVar"})
_THREAD_LOCAL_CTORS: Final[frozenset[str]] = frozenset({"local"})
_ACQUIRE_METHODS: Final[frozenset[str]] = frozenset({"acquire", "begin", "start"})
_RELEASE_METHODS: Final[frozenset[str]] = frozenset(
    {"release", "close", "commit", "rollback", "end", "stop"}
)
_TRANSACTION_NAMES: Final[frozenset[str]] = frozenset(
    {"transaction", "begin", "commit", "rollback", "atomic"}
)


class StateOwnershipError(ValueError):
    """Fail-closed violation of a SPAR-009 state-ownership contract."""


class LifecycleKind(str, Enum):
    INITIALIZE = "initialize"
    ACQUIRE = "acquire"
    RELEASE = "release"
    FINALIZE = "finalize"


class SynchronizationKind(str, Enum):
    LOCK = "lock"
    TRANSACTION = "transaction"
    CONDITION = "condition"


class UnresolvedStateReason(str, Enum):
    UNRESOLVED_ALIAS = "unresolved_alias"
    UNKNOWN_UNIQUENESS = "unknown_uniqueness"
    DYNAMIC_ACCESS = "dynamic_access"
    MISSING_SOURCE = "missing_source"
    UNSUPPORTED_CONSTRUCT = "unsupported_construct"
    ANALYZER_GAP = "analyzer_gap"


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str:
        raise StateOwnershipError(f"{name} must be a string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise StateOwnershipError(f"{name} must be trimmed NFC text")
    if not empty and not value:
        raise StateOwnershipError(f"{name} must be a nonempty string")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise StateOwnershipError(f"{name} contains invalid text")
    return value


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise StateOwnershipError(f"{name} has unsupported value {value!r}") from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise StateOwnershipError(f"{name} must be a valid CID") from exc


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise StateOwnershipError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise StateOwnershipError(f"{name} must be a nonnegative integer")
    return value


def _tree_id(value: Any) -> str:
    text = _text(value, "tree_id")
    if len(text) not in {40, 64} or any(
        char not in "0123456789abcdef" for char in text
    ):
        raise StateOwnershipError(
            "tree_id must be a lowercase hex Git tree identity"
        )
    return text


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping) or isinstance(data, (str, bytes, bytearray)):
        raise StateOwnershipError(f"{name} must be a mapping")
    overlap = FORBIDDEN_OBSERVATIONAL_FIELDS.intersection(data)
    if overlap:
        raise StateOwnershipError(
            f"{name} excludes observational fields {sorted(overlap)}"
        )
    actual = set(data)
    if actual != fields:
        raise StateOwnershipError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _reject_excluded(payload: Mapping[str, Any], name: str) -> None:
    present = FORBIDDEN_OBSERVATIONAL_FIELDS & set(payload)
    if present:
        raise StateOwnershipError(
            f"{name} identity excludes observational fields: {sorted(present)}"
        )


def _require_dag_json(value: Any, name: str) -> None:
    try:
        validate_structured_value(value)
    except Exception as exc:
        raise StateOwnershipError(f"{name} must be strict DAG-JSON") from exc


def _verify_cid(claimed: Any, computed: str, name: str) -> None:
    cid = _cid(claimed, name)
    if cid != computed:
        raise StateOwnershipError(f"{name} does not verify")


def _unique_sorted_text(values: Any, name: str, *, limit: int) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise StateOwnershipError(f"{name} must be a list")
    ordered = tuple(sorted(_text(item, name) for item in values))
    if len(ordered) > limit:
        raise StateOwnershipError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise StateOwnershipError(f"{name} must not contain duplicates")
    return ordered


def _confidence_compatible(confidence: str, evidence: str, name: str) -> None:
    if evidence == EvidenceClass.RUNTIME_OBSERVATION.value:
        if confidence == AnalysisConfidence.EXACT.value:
            raise StateOwnershipError(
                "runtime observation cannot be exact_static_fact"
            )
    if confidence == AnalysisConfidence.EXACT.value:
        if evidence not in _EXACT_EVIDENCE:
            raise StateOwnershipError(
                f"{name} exact confidence requires exact_static_fact evidence"
            )
    elif confidence == AnalysisConfidence.CONSERVATIVE.value:
        if evidence not in _CONSERVATIVE_EVIDENCE:
            raise StateOwnershipError(
                f"{name} conservative confidence has an incompatible evidence_class"
            )
    elif confidence == AnalysisConfidence.HEURISTIC.value:
        if evidence not in _HEURISTIC_EVIDENCE:
            raise StateOwnershipError(
                f"{name} heuristic confidence has an incompatible evidence_class"
            )
    elif confidence == AnalysisConfidence.OPAQUE.value:
        if evidence not in _OPAQUE_EVIDENCE:
            raise StateOwnershipError(
                f"{name} opaque confidence requires unknown evidence_class"
            )
    if evidence == EvidenceClass.RUNTIME_OBSERVATION.value:
        if confidence == AnalysisConfidence.EXACT.value:
            raise StateOwnershipError(
                "runtime observation cannot be exact_static_fact"
            )


def _reject_non_authoritative_uniqueness(uniqueness: str, evidence: str, confidence: str) -> None:
    if uniqueness != StateUniqueness.UNIQUE.value:
        return
    if evidence in _NON_AUTHORITATIVE_EVIDENCE:
        raise StateOwnershipError(
            "model or vector evidence cannot prove unique ownership"
        )
    if confidence in {
        AnalysisConfidence.HEURISTIC.value,
        AnalysisConfidence.OPAQUE.value,
    }:
        raise StateOwnershipError(
            "heuristic or opaque confidence cannot prove unique ownership"
        )
    if confidence != AnalysisConfidence.EXACT.value:
        raise StateOwnershipError(
            "unique ownership requires exact static confidence"
        )


def state_cid_profile() -> dict[str, str]:
    return {
        "profile_id": STATE_CID_PROFILE,
        "codec": STATE_CID_CODEC,
        "contract_version": STATE_CONTRACT_VERSION,
        "rule": (
            "CID identifies exact canonical bytes under declared codec/profile, "
            "not universal meaning"
        ),
    }


@dataclass(frozen=True, slots=True)
class ReadWriteSummary:
    """Exact and conservative read/write summary for one subject."""

    subject_id: str
    reads: Sequence[str] = ()
    writes: Sequence[str] = ()
    may_reads: Sequence[str] = ()
    may_writes: Sequence[str] = ()
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT

    SCHEMA: ClassVar[str] = READ_WRITE_SUMMARY_SCHEMA
    INTERFACE: ClassVar[str] = READ_WRITE_SUMMARY_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "subject_id",
            "reads",
            "writes",
            "may_reads",
            "may_writes",
            "confidence",
            "evidence_class",
            "summary_cid",
        }
    )

    def __post_init__(self) -> None:
        confidence = _enum(self.confidence, AnalysisConfidence, "confidence")
        evidence = _enum(self.evidence_class, EvidenceClass, "evidence_class")
        _confidence_compatible(confidence, evidence, "ReadWriteSummary")
        object.__setattr__(self, "subject_id", _text(self.subject_id, "subject_id"))
        object.__setattr__(
            self, "reads", _unique_sorted_text(list(self.reads), "reads", limit=MAX_NAMES)
        )
        object.__setattr__(
            self,
            "writes",
            _unique_sorted_text(list(self.writes), "writes", limit=MAX_NAMES),
        )
        object.__setattr__(
            self,
            "may_reads",
            _unique_sorted_text(list(self.may_reads), "may_reads", limit=MAX_NAMES),
        )
        object.__setattr__(
            self,
            "may_writes",
            _unique_sorted_text(list(self.may_writes), "may_writes", limit=MAX_NAMES),
        )
        if set(self.reads) & set(self.may_reads):
            raise StateOwnershipError("may_reads must not repeat exact reads")
        if set(self.writes) & set(self.may_writes):
            raise StateOwnershipError("may_writes must not repeat exact writes")
        if self.may_reads or self.may_writes:
            if confidence == AnalysisConfidence.EXACT.value and not (
                self.reads or self.writes
            ):
                raise StateOwnershipError(
                    "exact read/write summaries cannot be only may-facts"
                )
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence_class", evidence)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": READ_WRITE_SUMMARY_SCHEMA,
            "interface": READ_WRITE_SUMMARY_INTERFACE,
            "subject_id": self.subject_id,
            "reads": list(self.reads),
            "writes": list(self.writes),
            "may_reads": list(self.may_reads),
            "may_writes": list(self.may_writes),
            "confidence": self.confidence,
            "evidence_class": self.evidence_class,
        }
        _require_dag_json(payload, "ReadWriteSummary")
        return payload

    @property
    def summary_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["summary_cid"] = self.summary_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReadWriteSummary":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("summary_cid")
        if payload.pop("schema") != READ_WRITE_SUMMARY_SCHEMA:
            raise StateOwnershipError("unsupported ReadWriteSummary schema")
        if payload.pop("interface") != READ_WRITE_SUMMARY_INTERFACE:
            raise StateOwnershipError("unsupported ReadWriteSummary interface")
        result = cls(**payload)
        _verify_cid(claimed, result.summary_cid, "summary_cid")
        return result


@dataclass(frozen=True, slots=True)
class AliasSet:
    """Closed alias set; members share one owner candidate."""

    representative_id: str
    member_ids: Sequence[str]
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    unresolved: bool = False

    SCHEMA: ClassVar[str] = ALIAS_SET_SCHEMA
    INTERFACE: ClassVar[str] = ALIAS_SET_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "representative_id",
            "member_ids",
            "confidence",
            "evidence_class",
            "unresolved",
            "alias_set_cid",
        }
    )

    def __post_init__(self) -> None:
        confidence = _enum(self.confidence, AnalysisConfidence, "confidence")
        evidence = _enum(self.evidence_class, EvidenceClass, "evidence_class")
        _confidence_compatible(confidence, evidence, "AliasSet")
        representative = _text(self.representative_id, "representative_id")
        members = _unique_sorted_text(
            list(self.member_ids), "member_ids", limit=MAX_ALIAS_MEMBERS
        )
        if not members:
            raise StateOwnershipError("alias set member_ids must be nonempty")
        if representative not in members:
            raise StateOwnershipError(
                "representative_id must be a member of the alias set"
            )
        unresolved = _bool(self.unresolved, "unresolved")
        if unresolved and confidence == AnalysisConfidence.EXACT.value:
            raise StateOwnershipError("unresolved alias set forbids exact confidence")
        object.__setattr__(self, "representative_id", representative)
        object.__setattr__(self, "member_ids", members)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "unresolved", unresolved)

    @property
    def alias_set_id(self) -> str:
        return f"alias:{self.representative_id}"

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": ALIAS_SET_SCHEMA,
            "interface": ALIAS_SET_INTERFACE,
            "representative_id": self.representative_id,
            "member_ids": list(self.member_ids),
            "confidence": self.confidence,
            "evidence_class": self.evidence_class,
            "unresolved": self.unresolved,
        }
        _require_dag_json(payload, "AliasSet")
        return payload

    @property
    def alias_set_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["alias_set_cid"] = self.alias_set_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AliasSet":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("alias_set_cid")
        if payload.pop("schema") != ALIAS_SET_SCHEMA:
            raise StateOwnershipError("unsupported AliasSet schema")
        if payload.pop("interface") != ALIAS_SET_INTERFACE:
            raise StateOwnershipError("unsupported AliasSet interface")
        result = cls(**payload)
        _verify_cid(claimed, result.alias_set_cid, "alias_set_cid")
        return result


@dataclass(frozen=True, slots=True)
class OwnerCandidate:
    """Owner candidate bound to one alias set and uniqueness class."""

    owner_id: str
    owner_kind: StateOwnerKind | str
    uniqueness: StateUniqueness | str
    owning_symbol_id: str
    alias_set_id: str
    mutable: bool = True
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    read_write_summary_id: str = ""
    lineno: int = 0
    col_offset: int = 0

    SCHEMA: ClassVar[str] = OWNER_CANDIDATE_SCHEMA
    INTERFACE: ClassVar[str] = OWNER_CANDIDATE_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "owner_id",
            "owner_kind",
            "uniqueness",
            "owning_symbol_id",
            "alias_set_id",
            "mutable",
            "confidence",
            "evidence_class",
            "read_write_summary_id",
            "lineno",
            "col_offset",
            "owner_cid",
        }
    )

    def __post_init__(self) -> None:
        kind = _enum(self.owner_kind, StateOwnerKind, "owner_kind")
        uniqueness = _enum(self.uniqueness, StateUniqueness, "uniqueness")
        confidence = _enum(self.confidence, AnalysisConfidence, "confidence")
        evidence = _enum(self.evidence_class, EvidenceClass, "evidence_class")
        _reject_non_authoritative_uniqueness(uniqueness, evidence, confidence)
        _confidence_compatible(confidence, evidence, "OwnerCandidate")
        mutable = _bool(self.mutable, "mutable")
        if uniqueness == StateUniqueness.UNIQUE.value and not mutable:
            raise StateOwnershipError("unique owners in this contract are mutable")
        if kind == StateOwnerKind.UNKNOWN.value:
            if uniqueness == StateUniqueness.UNIQUE.value:
                raise StateOwnershipError(
                    "unknown owner_kind cannot prove unique ownership"
                )
            if confidence == AnalysisConfidence.EXACT.value:
                raise StateOwnershipError(
                    "unknown owner_kind forbids exact confidence"
                )
        if uniqueness == StateUniqueness.UNKNOWN.value:
            if confidence == AnalysisConfidence.EXACT.value:
                raise StateOwnershipError(
                    "unknown uniqueness forbids exact confidence"
                )
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        object.__setattr__(self, "owner_kind", kind)
        object.__setattr__(self, "uniqueness", uniqueness)
        object.__setattr__(
            self,
            "owning_symbol_id",
            _text(self.owning_symbol_id, "owning_symbol_id"),
        )
        object.__setattr__(
            self, "alias_set_id", _text(self.alias_set_id, "alias_set_id")
        )
        object.__setattr__(self, "mutable", mutable)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(
            self,
            "read_write_summary_id",
            _text(self.read_write_summary_id, "read_write_summary_id", empty=True),
        )
        object.__setattr__(self, "lineno", _nonneg_int(self.lineno, "lineno"))
        object.__setattr__(
            self, "col_offset", _nonneg_int(self.col_offset, "col_offset")
        )

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": OWNER_CANDIDATE_SCHEMA,
            "interface": OWNER_CANDIDATE_INTERFACE,
            "owner_id": self.owner_id,
            "owner_kind": self.owner_kind,
            "uniqueness": self.uniqueness,
            "owning_symbol_id": self.owning_symbol_id,
            "alias_set_id": self.alias_set_id,
            "mutable": self.mutable,
            "confidence": self.confidence,
            "evidence_class": self.evidence_class,
            "read_write_summary_id": self.read_write_summary_id,
            "lineno": self.lineno,
            "col_offset": self.col_offset,
        }
        _require_dag_json(payload, "OwnerCandidate")
        return payload

    @property
    def owner_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["owner_cid"] = self.owner_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OwnerCandidate":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("owner_cid")
        if payload.pop("schema") != OWNER_CANDIDATE_SCHEMA:
            raise StateOwnershipError("unsupported OwnerCandidate schema")
        if payload.pop("interface") != OWNER_CANDIDATE_INTERFACE:
            raise StateOwnershipError("unsupported OwnerCandidate interface")
        result = cls(**payload)
        _verify_cid(claimed, result.owner_cid, "owner_cid")
        return result


@dataclass(frozen=True, slots=True)
class LifecycleRelation:
    """Initialize/acquire/release/finalize relation for one owner."""

    relation_id: str
    kind: LifecycleKind | str
    owner_id: str
    site_id: str
    resource_kind: ResourceKind | str | None = None
    missing_counterpart: bool = False
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT

    SCHEMA: ClassVar[str] = LIFECYCLE_RELATION_SCHEMA
    INTERFACE: ClassVar[str] = LIFECYCLE_RELATION_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "relation_id",
            "kind",
            "owner_id",
            "site_id",
            "resource_kind",
            "missing_counterpart",
            "confidence",
            "evidence_class",
            "relation_cid",
        }
    )

    def __post_init__(self) -> None:
        kind = _enum(self.kind, LifecycleKind, "kind")
        confidence = _enum(self.confidence, AnalysisConfidence, "confidence")
        evidence = _enum(self.evidence_class, EvidenceClass, "evidence_class")
        _confidence_compatible(confidence, evidence, "LifecycleRelation")
        missing = _bool(self.missing_counterpart, "missing_counterpart")
        resource = self.resource_kind
        if resource is None or resource == "":
            resource_value = ""
        else:
            resource_value = _enum(resource, ResourceKind, "resource_kind")
        if missing and kind == LifecycleKind.RELEASE.value:
            if confidence == AnalysisConfidence.EXACT.value:
                raise StateOwnershipError(
                    "missing release cannot be an exact observed release"
                )
        object.__setattr__(self, "relation_id", _text(self.relation_id, "relation_id"))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        object.__setattr__(self, "site_id", _text(self.site_id, "site_id"))
        object.__setattr__(self, "resource_kind", resource_value)
        object.__setattr__(self, "missing_counterpart", missing)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence_class", evidence)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": LIFECYCLE_RELATION_SCHEMA,
            "interface": LIFECYCLE_RELATION_INTERFACE,
            "relation_id": self.relation_id,
            "kind": self.kind,
            "owner_id": self.owner_id,
            "site_id": self.site_id,
            "resource_kind": self.resource_kind,
            "missing_counterpart": self.missing_counterpart,
            "confidence": self.confidence,
            "evidence_class": self.evidence_class,
        }
        _require_dag_json(payload, "LifecycleRelation")
        return payload

    @property
    def relation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["relation_cid"] = self.relation_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LifecycleRelation":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("relation_cid")
        if payload.pop("schema") != LIFECYCLE_RELATION_SCHEMA:
            raise StateOwnershipError("unsupported LifecycleRelation schema")
        if payload.pop("interface") != LIFECYCLE_RELATION_INTERFACE:
            raise StateOwnershipError("unsupported LifecycleRelation interface")
        resource = payload.get("resource_kind") or None
        payload["resource_kind"] = resource
        result = cls(**payload)
        _verify_cid(claimed, result.relation_cid, "relation_cid")
        return result


@dataclass(frozen=True, slots=True)
class SynchronizationRelation:
    """Lock, transaction, or condition relation guarding owner access."""

    relation_id: str
    kind: SynchronizationKind | str
    owner_id: str
    guarded_subject_ids: Sequence[str] = ()
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT

    SCHEMA: ClassVar[str] = SYNCHRONIZATION_RELATION_SCHEMA
    INTERFACE: ClassVar[str] = SYNCHRONIZATION_RELATION_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "relation_id",
            "kind",
            "owner_id",
            "guarded_subject_ids",
            "confidence",
            "evidence_class",
            "relation_cid",
        }
    )

    def __post_init__(self) -> None:
        kind = _enum(self.kind, SynchronizationKind, "kind")
        confidence = _enum(self.confidence, AnalysisConfidence, "confidence")
        evidence = _enum(self.evidence_class, EvidenceClass, "evidence_class")
        _confidence_compatible(confidence, evidence, "SynchronizationRelation")
        object.__setattr__(self, "relation_id", _text(self.relation_id, "relation_id"))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        object.__setattr__(
            self,
            "guarded_subject_ids",
            _unique_sorted_text(
                list(self.guarded_subject_ids),
                "guarded_subject_ids",
                limit=MAX_NAMES,
            ),
        )
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence_class", evidence)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": SYNCHRONIZATION_RELATION_SCHEMA,
            "interface": SYNCHRONIZATION_RELATION_INTERFACE,
            "relation_id": self.relation_id,
            "kind": self.kind,
            "owner_id": self.owner_id,
            "guarded_subject_ids": list(self.guarded_subject_ids),
            "confidence": self.confidence,
            "evidence_class": self.evidence_class,
        }
        _require_dag_json(payload, "SynchronizationRelation")
        return payload

    @property
    def relation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["relation_cid"] = self.relation_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SynchronizationRelation":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("relation_cid")
        if payload.pop("schema") != SYNCHRONIZATION_RELATION_SCHEMA:
            raise StateOwnershipError("unsupported SynchronizationRelation schema")
        if payload.pop("interface") != SYNCHRONIZATION_RELATION_INTERFACE:
            raise StateOwnershipError(
                "unsupported SynchronizationRelation interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.relation_cid, "relation_cid")
        return result


@dataclass(frozen=True, slots=True)
class UnresolvedStateItem:
    """Explicit unresolved residual on the state-ownership frontier."""

    subject_id: str
    reason: UnresolvedStateReason | str
    unresolved_fields: Sequence[str] = ()
    confidence: AnalysisConfidence | str = AnalysisConfidence.CONSERVATIVE
    evidence_class: EvidenceClass | str = EvidenceClass.CONSERVATIVE_MAY_FACT

    SCHEMA: ClassVar[str] = UNRESOLVED_STATE_ITEM_SCHEMA
    INTERFACE: ClassVar[str] = UNRESOLVED_STATE_ITEM_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "subject_id",
            "reason",
            "unresolved_fields",
            "confidence",
            "evidence_class",
            "item_cid",
        }
    )

    def __post_init__(self) -> None:
        reason = _enum(self.reason, UnresolvedStateReason, "reason")
        confidence = _enum(self.confidence, AnalysisConfidence, "confidence")
        evidence = _enum(self.evidence_class, EvidenceClass, "evidence_class")
        _confidence_compatible(confidence, evidence, "UnresolvedStateItem")
        if confidence == AnalysisConfidence.EXACT.value:
            raise StateOwnershipError(
                "unresolved state item forbids exact confidence"
            )
        fields = _unique_sorted_text(
            list(self.unresolved_fields), "unresolved_fields", limit=256
        )
        if confidence == AnalysisConfidence.OPAQUE.value and not fields:
            raise StateOwnershipError(
                "opaque unresolved items require unresolved_fields"
            )
        object.__setattr__(self, "subject_id", _text(self.subject_id, "subject_id"))
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "unresolved_fields", fields)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence_class", evidence)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": UNRESOLVED_STATE_ITEM_SCHEMA,
            "interface": UNRESOLVED_STATE_ITEM_INTERFACE,
            "subject_id": self.subject_id,
            "reason": self.reason,
            "unresolved_fields": list(self.unresolved_fields),
            "confidence": self.confidence,
            "evidence_class": self.evidence_class,
        }
        _require_dag_json(payload, "UnresolvedStateItem")
        return payload

    @property
    def item_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["item_cid"] = self.item_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UnresolvedStateItem":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("item_cid")
        if payload.pop("schema") != UNRESOLVED_STATE_ITEM_SCHEMA:
            raise StateOwnershipError("unsupported UnresolvedStateItem schema")
        if payload.pop("interface") != UNRESOLVED_STATE_ITEM_INTERFACE:
            raise StateOwnershipError("unsupported UnresolvedStateItem interface")
        result = cls(**payload)
        _verify_cid(claimed, result.item_cid, "item_cid")
        return result


@dataclass(frozen=True, slots=True)
class StateExtractionCandidate:
    """Nomination to extract one unique state owner. Not completion authority."""

    owner_id: str
    uniqueness: StateUniqueness | str
    alias_set_id: str
    read_write_summary_ids: Sequence[str] = ()
    lifecycle_ids: Sequence[str] = ()
    synchronization_ids: Sequence[str] = ()
    complete_obligations: bool = False
    admitted: bool = False

    SCHEMA: ClassVar[str] = STATE_EXTRACTION_CANDIDATE_SCHEMA
    INTERFACE: ClassVar[str] = STATE_EXTRACTION_CANDIDATE_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "owner_id",
            "uniqueness",
            "alias_set_id",
            "read_write_summary_ids",
            "lifecycle_ids",
            "synchronization_ids",
            "complete_obligations",
            "admitted",
            "can_authorize_transition",
            "can_authorize_completion",
            "candidate_cid",
        }
    )

    def __post_init__(self) -> None:
        uniqueness = _enum(self.uniqueness, StateUniqueness, "uniqueness")
        complete = _bool(self.complete_obligations, "complete_obligations")
        admitted = _bool(self.admitted, "admitted")
        if admitted:
            if uniqueness != StateUniqueness.UNIQUE.value:
                raise StateOwnershipError(
                    "admitted extraction candidate requires unique ownership"
                )
            if not complete:
                raise StateOwnershipError(
                    "admitted extraction candidate requires complete obligations"
                )
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        object.__setattr__(self, "uniqueness", uniqueness)
        object.__setattr__(
            self, "alias_set_id", _text(self.alias_set_id, "alias_set_id")
        )
        object.__setattr__(
            self,
            "read_write_summary_ids",
            _unique_sorted_text(
                list(self.read_write_summary_ids),
                "read_write_summary_ids",
                limit=MAX_SUMMARIES,
            ),
        )
        object.__setattr__(
            self,
            "lifecycle_ids",
            _unique_sorted_text(
                list(self.lifecycle_ids), "lifecycle_ids", limit=MAX_RELATIONS
            ),
        )
        object.__setattr__(
            self,
            "synchronization_ids",
            _unique_sorted_text(
                list(self.synchronization_ids),
                "synchronization_ids",
                limit=MAX_RELATIONS,
            ),
        )
        object.__setattr__(self, "complete_obligations", complete)
        object.__setattr__(self, "admitted", admitted)

    @property
    def candidate_id(self) -> str:
        return f"extract:{self.owner_id}"

    @property
    def can_authorize_transition(self) -> bool:
        return False

    @property
    def can_authorize_completion(self) -> bool:
        return False

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": STATE_EXTRACTION_CANDIDATE_SCHEMA,
            "interface": STATE_EXTRACTION_CANDIDATE_INTERFACE,
            "owner_id": self.owner_id,
            "uniqueness": self.uniqueness,
            "alias_set_id": self.alias_set_id,
            "read_write_summary_ids": list(self.read_write_summary_ids),
            "lifecycle_ids": list(self.lifecycle_ids),
            "synchronization_ids": list(self.synchronization_ids),
            "complete_obligations": self.complete_obligations,
            "admitted": self.admitted,
            "can_authorize_transition": False,
            "can_authorize_completion": False,
        }
        _require_dag_json(payload, "StateExtractionCandidate")
        return payload

    @property
    def candidate_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["candidate_cid"] = self.candidate_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateExtractionCandidate":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("candidate_cid")
        if payload.pop("schema") != STATE_EXTRACTION_CANDIDATE_SCHEMA:
            raise StateOwnershipError("unsupported StateExtractionCandidate schema")
        if payload.pop("interface") != STATE_EXTRACTION_CANDIDATE_INTERFACE:
            raise StateOwnershipError(
                "unsupported StateExtractionCandidate interface"
            )
        if payload.pop("can_authorize_transition") is not False:
            raise StateOwnershipError(
                "extraction candidate cannot authorize a transition"
            )
        if payload.pop("can_authorize_completion") is not False:
            raise StateOwnershipError(
                "extraction candidate cannot authorize completion"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.candidate_cid, "candidate_cid")
        return result


def _coerce_summary(value: ReadWriteSummary | Mapping[str, Any]) -> ReadWriteSummary:
    if isinstance(value, ReadWriteSummary):
        return value
    if isinstance(value, Mapping):
        if "summary_cid" in value:
            return ReadWriteSummary.from_dict(value)
        return ReadWriteSummary(
            **{
                key: item
                for key, item in value.items()
                if key not in {"schema", "interface", "summary_cid"}
            }
        )
    raise StateOwnershipError("summary must be a ReadWriteSummary record")


def _coerce_alias(value: AliasSet | Mapping[str, Any]) -> AliasSet:
    if isinstance(value, AliasSet):
        return value
    if isinstance(value, Mapping):
        if "alias_set_cid" in value:
            return AliasSet.from_dict(value)
        return AliasSet(
            **{
                key: item
                for key, item in value.items()
                if key not in {"schema", "interface", "alias_set_cid"}
            }
        )
    raise StateOwnershipError("alias set must be an AliasSet record")


def _coerce_owner(value: OwnerCandidate | Mapping[str, Any]) -> OwnerCandidate:
    if isinstance(value, OwnerCandidate):
        return value
    if isinstance(value, Mapping):
        if "owner_cid" in value:
            return OwnerCandidate.from_dict(value)
        return OwnerCandidate(
            **{
                key: item
                for key, item in value.items()
                if key not in {"schema", "interface", "owner_cid"}
            }
        )
    raise StateOwnershipError("owner must be an OwnerCandidate record")


def _coerce_lifecycle(
    value: LifecycleRelation | Mapping[str, Any],
) -> LifecycleRelation:
    if isinstance(value, LifecycleRelation):
        return value
    if isinstance(value, Mapping):
        if "relation_cid" in value:
            return LifecycleRelation.from_dict(value)
        return LifecycleRelation(
            **{
                key: item
                for key, item in value.items()
                if key not in {"schema", "interface", "relation_cid"}
            }
        )
    raise StateOwnershipError("lifecycle must be a LifecycleRelation record")


def _coerce_sync(
    value: SynchronizationRelation | Mapping[str, Any],
) -> SynchronizationRelation:
    if isinstance(value, SynchronizationRelation):
        return value
    if isinstance(value, Mapping):
        if "relation_cid" in value:
            return SynchronizationRelation.from_dict(value)
        return SynchronizationRelation(
            **{
                key: item
                for key, item in value.items()
                if key not in {"schema", "interface", "relation_cid"}
            }
        )
    raise StateOwnershipError(
        "synchronization must be a SynchronizationRelation record"
    )


def _coerce_frontier_item(
    value: UnresolvedStateItem | Mapping[str, Any],
) -> UnresolvedStateItem:
    if isinstance(value, UnresolvedStateItem):
        return value
    if isinstance(value, Mapping):
        if "item_cid" in value:
            return UnresolvedStateItem.from_dict(value)
        return UnresolvedStateItem(
            **{
                key: item
                for key, item in value.items()
                if key not in {"schema", "interface", "item_cid"}
            }
        )
    raise StateOwnershipError("frontier item must be an UnresolvedStateItem record")


def _coerce_candidate(
    value: StateExtractionCandidate | Mapping[str, Any],
) -> StateExtractionCandidate:
    if isinstance(value, StateExtractionCandidate):
        return value
    if isinstance(value, Mapping):
        if "candidate_cid" in value:
            return StateExtractionCandidate.from_dict(value)
        return StateExtractionCandidate(
            **{
                key: item
                for key, item in value.items()
                if key
                not in {
                    "schema",
                    "interface",
                    "candidate_cid",
                    "can_authorize_transition",
                    "can_authorize_completion",
                    "candidate_id",
                }
            }
        )
    raise StateOwnershipError(
        "candidate must be a StateExtractionCandidate record"
    )


def _reject_duplicated_unique_owners(
    owners: Sequence[OwnerCandidate],
    alias_sets: Sequence[AliasSet],
) -> None:
    alias_by_id = {item.alias_set_id: item for item in alias_sets}
    unique_members: dict[str, str] = {}
    for owner in owners:
        if owner.uniqueness != StateUniqueness.UNIQUE.value:
            continue
        alias = alias_by_id.get(owner.alias_set_id)
        if alias is None:
            raise StateOwnershipError(
                f"owner {owner.owner_id} references a missing alias set"
            )
        for member in alias.member_ids:
            prior = unique_members.get(member)
            if prior is not None and prior != owner.owner_id:
                raise StateOwnershipError("duplicated mutable state")
            unique_members[member] = owner.owner_id
    unique_alias_ids = [
        owner.alias_set_id
        for owner in owners
        if owner.uniqueness == StateUniqueness.UNIQUE.value
    ]
    if len(unique_alias_ids) != len(set(unique_alias_ids)):
        raise StateOwnershipError("duplicated mutable state")


@dataclass(frozen=True, slots=True)
class StateOwnershipGraph:
    """Closed SPAR-009 graph of owners, aliases, summaries, and relations."""

    tree_id: str
    subject_cid: str
    source_cid: str
    analyzer_revision: str
    environment_cid: str
    owners: Sequence[OwnerCandidate | Mapping[str, Any]] = ()
    alias_sets: Sequence[AliasSet | Mapping[str, Any]] = ()
    read_write_summaries: Sequence[ReadWriteSummary | Mapping[str, Any]] = ()
    lifecycle_relations: Sequence[LifecycleRelation | Mapping[str, Any]] = ()
    synchronization_relations: Sequence[
        SynchronizationRelation | Mapping[str, Any]
    ] = ()
    extraction_candidates: Sequence[StateExtractionCandidate | Mapping[str, Any]] = ()
    unresolved: Sequence[UnresolvedStateItem | Mapping[str, Any]] = ()
    analyzer_id: str = ANALYZER_ID

    SCHEMA: ClassVar[str] = STATE_OWNERSHIP_GRAPH_SCHEMA
    INTERFACE: ClassVar[str] = STATE_OWNERSHIP_GRAPH_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "tree_id",
            "subject_cid",
            "source_cid",
            "analyzer_id",
            "analyzer_revision",
            "environment_cid",
            "owners",
            "alias_sets",
            "read_write_summaries",
            "lifecycle_relations",
            "synchronization_relations",
            "extraction_candidates",
            "unresolved",
            "graph_cid",
        }
    )

    def __post_init__(self) -> None:
        owners = tuple(sorted((_coerce_owner(item) for item in self.owners), key=lambda item: item.owner_id))
        aliases = tuple(
            sorted((_coerce_alias(item) for item in self.alias_sets), key=lambda item: item.alias_set_id)
        )
        summaries = tuple(
            sorted(
                (_coerce_summary(item) for item in self.read_write_summaries),
                key=lambda item: item.subject_id,
            )
        )
        lifecycle = tuple(
            sorted(
                (_coerce_lifecycle(item) for item in self.lifecycle_relations),
                key=lambda item: item.relation_id,
            )
        )
        sync = tuple(
            sorted(
                (_coerce_sync(item) for item in self.synchronization_relations),
                key=lambda item: item.relation_id,
            )
        )
        candidates = tuple(
            sorted(
                (_coerce_candidate(item) for item in self.extraction_candidates),
                key=lambda item: item.owner_id,
            )
        )
        frontier = tuple(
            sorted(
                (_coerce_frontier_item(item) for item in self.unresolved),
                key=lambda item: item.subject_id,
            )
        )
        if len(owners) > MAX_OWNERS:
            raise StateOwnershipError("owners exceed maximum length")
        if len(aliases) > MAX_ALIAS_SETS:
            raise StateOwnershipError("alias_sets exceed maximum length")
        if len(summaries) > MAX_SUMMARIES:
            raise StateOwnershipError("read_write_summaries exceed maximum length")
        if len(lifecycle) > MAX_RELATIONS or len(sync) > MAX_RELATIONS:
            raise StateOwnershipError("relations exceed maximum length")
        if len(candidates) > MAX_CANDIDATES:
            raise StateOwnershipError("extraction_candidates exceed maximum length")
        if len(frontier) > MAX_FRONTIER_ITEMS:
            raise StateOwnershipError("unresolved exceeds maximum length")
        owner_ids = tuple(item.owner_id for item in owners)
        if len(owner_ids) != len(set(owner_ids)):
            raise StateOwnershipError("owners must not contain duplicate owner_id")
        alias_ids = tuple(item.alias_set_id for item in aliases)
        if len(alias_ids) != len(set(alias_ids)):
            raise StateOwnershipError("alias_sets must not contain duplicate ids")
        summary_ids = tuple(item.subject_id for item in summaries)
        if len(summary_ids) != len(set(summary_ids)):
            raise StateOwnershipError(
                "read_write_summaries must not contain duplicate subject_id"
            )
        lifecycle_ids = tuple(item.relation_id for item in lifecycle)
        if len(lifecycle_ids) != len(set(lifecycle_ids)):
            raise StateOwnershipError("lifecycle relations must not contain duplicates")
        sync_ids = tuple(item.relation_id for item in sync)
        if len(sync_ids) != len(set(sync_ids)):
            raise StateOwnershipError(
                "synchronization relations must not contain duplicates"
            )
        present_owners = set(owner_ids)
        present_aliases = set(alias_ids)
        present_summaries = set(summary_ids)
        for owner in owners:
            if owner.alias_set_id not in present_aliases:
                raise StateOwnershipError(
                    "owner references an alias set that is not present"
                )
            if owner.read_write_summary_id and owner.read_write_summary_id not in present_summaries:
                raise StateOwnershipError(
                    "owner references a read/write summary that is not present"
                )
        for relation in lifecycle:
            if relation.owner_id not in present_owners:
                raise StateOwnershipError(
                    "lifecycle relation references an owner that is not present"
                )
        for relation in sync:
            if relation.owner_id not in present_owners:
                raise StateOwnershipError(
                    "synchronization relation references an owner that is not present"
                )
        for candidate in candidates:
            if candidate.owner_id not in present_owners:
                raise StateOwnershipError(
                    "extraction candidate references an owner that is not present"
                )
            if candidate.alias_set_id not in present_aliases:
                raise StateOwnershipError(
                    "extraction candidate references an alias set that is not present"
                )
            for summary_id in candidate.read_write_summary_ids:
                if summary_id not in present_summaries:
                    raise StateOwnershipError(
                        "extraction candidate references a missing summary"
                    )
            for relation_id in candidate.lifecycle_ids:
                if relation_id not in set(lifecycle_ids):
                    raise StateOwnershipError(
                        "extraction candidate references a missing lifecycle relation"
                    )
            for relation_id in candidate.synchronization_ids:
                if relation_id not in set(sync_ids):
                    raise StateOwnershipError(
                        "extraction candidate references a missing synchronization relation"
                    )
        _reject_duplicated_unique_owners(owners, aliases)
        hidden_unknown = [
            owner.owner_id
            for owner in owners
            if owner.uniqueness == StateUniqueness.UNKNOWN.value
            and owner.owner_id not in {item.subject_id for item in frontier}
        ]
        if hidden_unknown:
            raise StateOwnershipError(
                "unknown uniqueness must appear on the explicit frontier"
            )
        object.__setattr__(self, "tree_id", _tree_id(self.tree_id))
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self,
            "analyzer_id",
            _text(self.analyzer_id, "analyzer_id"),
        )
        if self.analyzer_id != ANALYZER_ID:
            raise StateOwnershipError("analyzer_id must remain the SPAR-009 analyzer")
        object.__setattr__(
            self,
            "analyzer_revision",
            _cid(self.analyzer_revision, "analyzer_revision"),
        )
        object.__setattr__(
            self, "environment_cid", _cid(self.environment_cid, "environment_cid")
        )
        object.__setattr__(self, "owners", owners)
        object.__setattr__(self, "alias_sets", aliases)
        object.__setattr__(self, "read_write_summaries", summaries)
        object.__setattr__(self, "lifecycle_relations", lifecycle)
        object.__setattr__(self, "synchronization_relations", sync)
        object.__setattr__(self, "extraction_candidates", candidates)
        object.__setattr__(self, "unresolved", frontier)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": STATE_OWNERSHIP_GRAPH_SCHEMA,
            "interface": STATE_OWNERSHIP_GRAPH_INTERFACE,
            "tree_id": self.tree_id,
            "subject_cid": self.subject_cid,
            "source_cid": self.source_cid,
            "analyzer_id": self.analyzer_id,
            "analyzer_revision": self.analyzer_revision,
            "environment_cid": self.environment_cid,
            "owners": [item.identity_payload() for item in self.owners],
            "alias_sets": [item.identity_payload() for item in self.alias_sets],
            "read_write_summaries": [
                item.identity_payload() for item in self.read_write_summaries
            ],
            "lifecycle_relations": [
                item.identity_payload() for item in self.lifecycle_relations
            ],
            "synchronization_relations": [
                item.identity_payload() for item in self.synchronization_relations
            ],
            "extraction_candidates": [
                item.identity_payload() for item in self.extraction_candidates
            ],
            "unresolved": [item.identity_payload() for item in self.unresolved],
        }
        _require_dag_json(payload, "StateOwnershipGraph")
        return payload

    @property
    def graph_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["owners"] = [item.to_dict() for item in self.owners]
        payload["alias_sets"] = [item.to_dict() for item in self.alias_sets]
        payload["read_write_summaries"] = [
            item.to_dict() for item in self.read_write_summaries
        ]
        payload["lifecycle_relations"] = [
            item.to_dict() for item in self.lifecycle_relations
        ]
        payload["synchronization_relations"] = [
            item.to_dict() for item in self.synchronization_relations
        ]
        payload["extraction_candidates"] = [
            item.to_dict() for item in self.extraction_candidates
        ]
        payload["unresolved"] = [item.to_dict() for item in self.unresolved]
        payload["graph_cid"] = self.graph_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateOwnershipGraph":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("graph_cid")
        if payload.pop("schema") != STATE_OWNERSHIP_GRAPH_SCHEMA:
            raise StateOwnershipError("unsupported StateOwnershipGraph schema")
        if payload.pop("interface") != STATE_OWNERSHIP_GRAPH_INTERFACE:
            raise StateOwnershipError("unsupported StateOwnershipGraph interface")
        result = cls(**payload)
        _verify_cid(claimed, result.graph_cid, "graph_cid")
        return result

    def unique_owners(self) -> tuple[OwnerCandidate, ...]:
        return tuple(
            owner
            for owner in self.owners
            if owner.uniqueness == StateUniqueness.UNIQUE.value
        )

    def admitted_candidates(self) -> tuple[StateExtractionCandidate, ...]:
        return tuple(
            item for item in self.extraction_candidates if item.admitted
        )


def build_state_ownership_graph(
    *,
    tree_id: str,
    subject_cid: str,
    source_cid: str,
    analyzer_revision: str,
    environment_cid: str,
    owners: Sequence[OwnerCandidate | Mapping[str, Any]] = (),
    alias_sets: Sequence[AliasSet | Mapping[str, Any]] = (),
    read_write_summaries: Sequence[ReadWriteSummary | Mapping[str, Any]] = (),
    lifecycle_relations: Sequence[LifecycleRelation | Mapping[str, Any]] = (),
    synchronization_relations: Sequence[
        SynchronizationRelation | Mapping[str, Any]
    ] = (),
    extraction_candidates: Sequence[StateExtractionCandidate | Mapping[str, Any]] = (),
    unresolved: Sequence[UnresolvedStateItem | Mapping[str, Any]] = (),
) -> StateOwnershipGraph:
    """Construct one closed StateOwnershipGraph@1 record."""

    return StateOwnershipGraph(
        tree_id=tree_id,
        subject_cid=subject_cid,
        source_cid=source_cid,
        analyzer_revision=analyzer_revision,
        environment_cid=environment_cid,
        owners=owners,
        alias_sets=alias_sets,
        read_write_summaries=read_write_summaries,
        lifecycle_relations=lifecycle_relations,
        synchronization_relations=synchronization_relations,
        extraction_candidates=extraction_candidates,
        unresolved=unresolved,
    )


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        self.add(item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while item != root:
            nxt = self.parent[item]
            self.parent[item] = root
            item = nxt
        return root

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left == root_right:
            return
        if root_left > root_right:
            root_left, root_right = root_right, root_left
        self.parent[root_right] = root_left


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _leaf_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_exact_immutable(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return type(node.value) in {int, float, str, bytes, bool, type(None)}
    if isinstance(node, ast.Tuple):
        return all(_is_exact_immutable(elt) for elt in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_exact_immutable(node.operand)
    return False


def _ctor_kind(node: ast.AST) -> tuple[str, StateOwnerKind] | None:
    if isinstance(node, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return ("mutable", StateOwnerKind.MODULE_GLOBAL)
    if not isinstance(node, ast.Call):
        return None
    leaf = _leaf_name(node.func)
    if leaf in _CONTEXTVAR_CTORS:
        return ("mutable", StateOwnerKind.CONTEXTVAR)
    if leaf in _THREAD_LOCAL_CTORS:
        return ("mutable", StateOwnerKind.THREAD_LOCAL)
    if leaf in _LOCK_CTORS:
        return ("mutable", StateOwnerKind.RESOURCE)
    if leaf in _MUTABLE_CTORS:
        return ("mutable", StateOwnerKind.MODULE_GLOBAL)
    return None


def _site(node: ast.AST) -> tuple[int, int]:
    return (getattr(node, "lineno", 0) or 0, getattr(node, "col_offset", 0) or 0)


def _owner_id(kind: StateOwnerKind | str, symbol: str) -> str:
    return f"owner:{kind}:{symbol}"


@dataclass
class _OwnerDraft:
    symbol: str
    kind: StateOwnerKind
    uniqueness: StateUniqueness
    lineno: int
    col_offset: int
    resource: bool = False
    lock: bool = False
    contextvar: bool = False


class _StateVisitor(ast.NodeVisitor):
    def __init__(self, *, subject_name: str) -> None:
        self.subject_name = subject_name
        self.class_stack: list[str] = []
        self.func_stack: list[str] = []
        self.drafts: dict[str, _OwnerDraft] = {}
        self.aliases = _UnionFind()
        self.function_nodes: list[tuple[str, ast.AST]] = []
        self.acquire_sites: list[tuple[str, ast.AST, str]] = []
        self.release_sites: list[tuple[str, ast.AST, str]] = []
        self.with_sites: list[tuple[str, ast.AST, str, tuple[str, ...]]] = []
        self.dynamic_sites: list[tuple[str, ast.AST, str]] = []
        self.init_sites: list[tuple[str, ast.AST]] = []

    def _qualify(self, name: str, *, instance: bool = False) -> str:
        if instance and self.class_stack:
            return f"{self.class_stack[-1]}.{name}"
        if self.class_stack and not self.func_stack:
            return f"{self.class_stack[-1]}.{name}"
        if self.func_stack and not instance:
            return f"{'.'.join(self.func_stack)}.{name}"
        return name

    def _scope_kind(self, *, instance: bool) -> StateOwnerKind:
        if instance:
            return StateOwnerKind.INSTANCE_ATTRIBUTE
        if self.class_stack and not self.func_stack:
            return StateOwnerKind.CLASS_ATTRIBUTE
        if self.func_stack:
            return StateOwnerKind.CLOSURE_CELL
        return StateOwnerKind.MODULE_GLOBAL

    def _record_mutable(
        self,
        names: Sequence[str],
        node: ast.AST,
        kind: StateOwnerKind,
        uniqueness: StateUniqueness,
        *,
        resource: bool = False,
        lock: bool = False,
        contextvar: bool = False,
    ) -> None:
        if not names:
            return
        representative = sorted(names)[0]
        lineno, col = _site(node)
        for name in names:
            self.aliases.add(name)
            self.aliases.union(name, representative)
        existing = [
            self.drafts[name]
            for name in names
            if name in self.drafts
        ]
        if existing and uniqueness == StateUniqueness.UNIQUE:
            unique_existing = [
                item for item in existing if item.uniqueness == StateUniqueness.UNIQUE
            ]
            if unique_existing and unique_existing[0].symbol not in names:
                raise StateOwnershipError("duplicated mutable state")
        draft = _OwnerDraft(
            symbol=representative,
            kind=kind,
            uniqueness=uniqueness,
            lineno=lineno,
            col_offset=col,
            resource=resource,
            lock=lock,
            contextvar=contextvar,
        )
        if representative not in self.drafts:
            self.drafts[representative] = draft
        for name in names:
            self.aliases.add(name)
        if uniqueness == StateUniqueness.UNIQUE:
            self.init_sites.append((representative, node))

    def _names_from_target(
        self, target: ast.AST
    ) -> list[tuple[str, bool]]:
        if isinstance(target, ast.Name):
            instance = False
            if self.func_stack and self.class_stack:
                return [(self._qualify(target.id), False)]
            return [(self._qualify(target.id, instance=instance), False)]
        if isinstance(target, ast.Attribute):
            base = _leaf_name(target.value)
            if base in {"self", "cls"} and self.class_stack:
                return [(self._qualify(target.attr, instance=True), True)]
            if isinstance(target.value, ast.Name):
                return [(f"{target.value.id}.{target.attr}", False)]
        if isinstance(target, (ast.Tuple, ast.List)):
            names: list[tuple[str, bool]] = []
            for elt in target.elts:
                names.extend(self._names_from_target(elt))
            return names
        return []

    def _handle_assignment(self, targets: Sequence[ast.AST], value: ast.AST) -> None:
        collected: list[tuple[str, bool]] = []
        for target in targets:
            collected.extend(self._names_from_target(target))
        if not collected:
            return
        names = tuple(item[0] for item in collected)
        instance = any(item[1] for item in collected)
        ctor = _ctor_kind(value)
        if ctor is not None:
            _mutable, ctor_kind = ctor
            kind = ctor_kind
            if instance:
                kind = StateOwnerKind.INSTANCE_ATTRIBUTE
            elif self.class_stack and not self.func_stack:
                kind = StateOwnerKind.CLASS_ATTRIBUTE
            elif self.func_stack and kind == StateOwnerKind.MODULE_GLOBAL:
                kind = StateOwnerKind.CLOSURE_CELL
            uniqueness = (
                StateUniqueness.SHARED
                if kind
                in {
                    StateOwnerKind.INSTANCE_ATTRIBUTE,
                    StateOwnerKind.CLOSURE_CELL,
                }
                else StateUniqueness.UNIQUE
            )
            leaf = _leaf_name(value.func) if isinstance(value, ast.Call) else ""
            self._record_mutable(
                names,
                value,
                kind,
                uniqueness,
                resource=leaf in _LOCK_CTORS,
                lock=leaf in _LOCK_CTORS,
                contextvar=leaf in _CONTEXTVAR_CTORS,
            )
            return
        if isinstance(value, ast.Name):
            source = self._qualify(value.id)
            for name in names:
                self.aliases.union(name, source)
            return
        if _is_exact_immutable(value):
            return
        kind = self._scope_kind(instance=instance)
        uniqueness = StateUniqueness.UNKNOWN
        self._record_mutable(names, value, kind, uniqueness)
        for name in names:
            self.dynamic_sites.append((name, value, "unknown_uniqueness"))

    def visit_Assign(self, node: ast.Assign) -> None:
        self._handle_assignment(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._handle_assignment((node.target,), node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        names = self._names_from_target(node.target)
        for name, _instance in names:
            self.aliases.add(name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self.class_stack:
            qual = f"{self.class_stack[-1]}.{node.name}"
        elif self.func_stack:
            qual = f"{'.'.join(self.func_stack)}.{node.name}"
        else:
            qual = node.name
        self.function_nodes.append((qual, node))
        self.func_stack.append(node.name)
        self.generic_visit(node)
        self.func_stack.pop()

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        for name in node.names:
            qualified = name
            self.aliases.add(qualified)
            if qualified not in self.drafts:
                lineno, col = _site(node)
                self.drafts[qualified] = _OwnerDraft(
                    symbol=qualified,
                    kind=StateOwnerKind.CLOSURE_CELL,
                    uniqueness=StateUniqueness.SHARED,
                    lineno=lineno,
                    col_offset=col,
                )
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        for name in node.names:
            self.aliases.add(name)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self._visit_with(node)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with(node)
        self.generic_visit(node)

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        guarded = tuple(
            sorted(
                {
                    child.id
                    for child in ast.walk(node)
                    if isinstance(child, ast.Name)
                }
            )
        )
        for item in node.items:
            expr = item.context_expr
            name = _leaf_name(expr) or _call_name(expr)
            if isinstance(expr, ast.Name):
                owner_symbol = expr.id
            elif isinstance(expr, ast.Call):
                owner_symbol = name
            else:
                owner_symbol = name
            kind = "lock"
            leaf = _leaf_name(expr)
            if leaf in _TRANSACTION_NAMES or any(
                token in (name or "").lower() for token in _TRANSACTION_NAMES
            ):
                kind = "transaction"
            self.with_sites.append((owner_symbol, node, kind, guarded))
            self.acquire_sites.append((owner_symbol, node, "with"))
            self.release_sites.append((owner_symbol, node, "with"))

    def visit_Call(self, node: ast.Call) -> None:
        leaf = _leaf_name(node.func)
        name = _call_name(node.func)
        if leaf in {"getattr", "setattr", "delattr"}:
            self.dynamic_sites.append((name or leaf, node, "dynamic_access"))
        if leaf in _ACQUIRE_METHODS or name.endswith(".acquire") or name.endswith(".begin"):
            base = name.rsplit(".", 1)[0] if "." in name else ""
            self.acquire_sites.append((base or leaf, node, leaf))
        if leaf in _RELEASE_METHODS or any(
            name.endswith(f".{method}") for method in _RELEASE_METHODS
        ):
            base = name.rsplit(".", 1)[0] if "." in name else ""
            self.release_sites.append((base or leaf, node, leaf))
        self.generic_visit(node)


def _collect_rw(node: ast.AST, subject_id: str) -> ReadWriteSummary:
    reads: set[str] = set()
    writes: set[str] = set()
    may_reads: set[str] = set()
    may_writes: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            if isinstance(child.ctx, ast.Store):
                writes.add(child.id)
            elif isinstance(child.ctx, ast.Load):
                reads.add(child.id)
            elif isinstance(child.ctx, ast.Del):
                writes.add(child.id)
        elif isinstance(child, ast.Attribute):
            base = _leaf_name(child.value) or _call_name(child.value)
            attr = f"{base}.{child.attr}" if base else child.attr
            if isinstance(child.ctx, ast.Store):
                writes.add(attr)
                if base:
                    writes.add(base)
            elif isinstance(child.ctx, ast.Load):
                reads.add(attr)
                if base:
                    reads.add(base)
        elif isinstance(child, ast.Subscript):
            base = _leaf_name(child.value) or _call_name(child.value)
            if not base:
                continue
            if isinstance(child.ctx, ast.Store):
                writes.add(base)
            elif isinstance(child.ctx, ast.Load):
                reads.add(base)
        elif isinstance(child, ast.Call):
            leaf = _leaf_name(child.func)
            if leaf == "getattr":
                target = _leaf_name(child.args[0]) if child.args else leaf
                may_reads.add(target)
            elif leaf in {"setattr", "delattr"}:
                target = _leaf_name(child.args[0]) if child.args else leaf
                may_writes.add(target)
            elif leaf in {"globals", "locals", "vars"}:
                may_reads.add(leaf)
                may_writes.add(leaf)
    reads -= may_reads
    writes -= may_writes
    confidence = (
        AnalysisConfidence.CONSERVATIVE
        if may_reads or may_writes
        else AnalysisConfidence.EXACT
    )
    evidence = (
        EvidenceClass.CONSERVATIVE_MAY_FACT
        if confidence is AnalysisConfidence.CONSERVATIVE
        else EvidenceClass.EXACT_STATIC_FACT
    )
    return ReadWriteSummary(
        subject_id=subject_id,
        reads=tuple(reads),
        writes=tuple(writes),
        may_reads=tuple(may_reads),
        may_writes=tuple(may_writes),
        confidence=confidence,
        evidence_class=evidence,
    )


def _module_rw(tree: ast.Module) -> ReadWriteSummary:
    writes: set[str] = set()
    reads: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for child in ast.walk(target):
                    if isinstance(child, ast.Name):
                        writes.add(child.id)
            for child in ast.walk(node.value):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    reads.add(child.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            writes.add(node.target.id)
    return ReadWriteSummary(
        subject_id="<module>",
        reads=tuple(reads),
        writes=tuple(writes),
        confidence=AnalysisConfidence.EXACT,
        evidence_class=EvidenceClass.EXACT_STATIC_FACT,
    )


def analyze_source(
    source: str,
    *,
    tree_id: str,
    subject_cid: str,
    source_cid: str | None = None,
    analyzer_revision: str | None = None,
    environment_cid: str | None = None,
    subject_name: str = "module",
) -> StateOwnershipGraph:
    """Infer owners, aliases, summaries, and relations from one Python module."""

    text = source if type(source) is str else None
    if text is None:
        raise StateOwnershipError("source must be a string")
    resolved_source_cid = source_cid or cid_for_bytes(text.encode("utf-8"))
    revision = analyzer_revision or cid_for_bytes(ANALYZER_ID.encode("utf-8"))
    environment = environment_cid or cid_for_bytes(b"environment:hermetic")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise StateOwnershipError("source must be parseable Python") from exc
    if not isinstance(tree, ast.Module):
        raise StateOwnershipError("source must be a Python module")
    visitor = _StateVisitor(subject_name=subject_name)
    visitor.visit(tree)

    components: dict[str, set[str]] = {}
    for name in list(visitor.aliases.parent) + list(visitor.drafts):
        visitor.aliases.add(name)
        root = visitor.aliases.find(name)
        components.setdefault(root, set()).add(name)

    owners: list[OwnerCandidate] = []
    alias_sets: list[AliasSet] = []
    unresolved: list[UnresolvedStateItem] = []
    claimed_unique: dict[str, str] = {}

    for root, members in sorted(components.items()):
        drafts = [visitor.drafts[name] for name in members if name in visitor.drafts]
        unique_drafts = [
            item for item in drafts if item.uniqueness == StateUniqueness.UNIQUE
        ]
        if len({item.symbol for item in unique_drafts}) > 1:
            raise StateOwnershipError("duplicated mutable state")
        if not drafts:
            continue
        if unique_drafts:
            draft = unique_drafts[0]
        else:
            draft = sorted(drafts, key=lambda item: item.symbol)[0]
        representative = sorted(members)[0] if not unique_drafts else draft.symbol
        if unique_drafts:
            representative = sorted(
                {item.symbol for item in unique_drafts}
            )[0]
        member_ids = tuple(sorted(members))
        for member in member_ids:
            if draft.uniqueness == StateUniqueness.UNIQUE:
                prior = claimed_unique.get(member)
                owner_key = _owner_id(draft.kind, representative)
                if prior is not None and prior != owner_key:
                    raise StateOwnershipError("duplicated mutable state")
                claimed_unique[member] = owner_key
        alias = AliasSet(
            representative_id=representative,
            member_ids=member_ids,
            confidence=(
                AnalysisConfidence.CONSERVATIVE
                if draft.uniqueness == StateUniqueness.UNKNOWN
                else AnalysisConfidence.EXACT
            ),
            evidence_class=(
                EvidenceClass.CONSERVATIVE_MAY_FACT
                if draft.uniqueness == StateUniqueness.UNKNOWN
                else EvidenceClass.EXACT_STATIC_FACT
            ),
            unresolved=draft.uniqueness == StateUniqueness.UNKNOWN,
        )
        alias_sets.append(alias)
        owner = OwnerCandidate(
            owner_id=_owner_id(draft.kind, representative),
            owner_kind=draft.kind,
            uniqueness=draft.uniqueness,
            owning_symbol_id=representative,
            alias_set_id=alias.alias_set_id,
            mutable=True,
            confidence=(
                AnalysisConfidence.CONSERVATIVE
                if draft.uniqueness == StateUniqueness.UNKNOWN
                else AnalysisConfidence.EXACT
            ),
            evidence_class=(
                EvidenceClass.CONSERVATIVE_MAY_FACT
                if draft.uniqueness == StateUniqueness.UNKNOWN
                else EvidenceClass.EXACT_STATIC_FACT
            ),
            read_write_summary_id="<module>",
            lineno=draft.lineno,
            col_offset=draft.col_offset,
        )
        owners.append(owner)
        if draft.uniqueness == StateUniqueness.UNKNOWN:
            unresolved.append(
                UnresolvedStateItem(
                    subject_id=owner.owner_id,
                    reason=UnresolvedStateReason.UNKNOWN_UNIQUENESS,
                    unresolved_fields=("uniqueness",),
                    confidence=AnalysisConfidence.CONSERVATIVE,
                    evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT,
                )
            )

    summaries = [_module_rw(tree)]
    for qual, node in visitor.function_nodes:
        summaries.append(_collect_rw(node, qual))

    owner_by_symbol = {
        owner.owning_symbol_id: owner for owner in owners
    }
    for alias in alias_sets:
        owner = next(
            (item for item in owners if item.alias_set_id == alias.alias_set_id),
            None,
        )
        if owner is None:
            continue
        for member in alias.member_ids:
            owner_by_symbol.setdefault(member, owner)

    lifecycle: list[LifecycleRelation] = []
    sync: list[SynchronizationRelation] = []
    for owner in owners:
        draft = visitor.drafts.get(owner.owning_symbol_id)
        if draft is None:
            continue
        if draft.uniqueness == StateUniqueness.UNIQUE:
            lifecycle.append(
                LifecycleRelation(
                    relation_id=f"lifecycle:initialize:{owner.owner_id}",
                    kind=LifecycleKind.INITIALIZE,
                    owner_id=owner.owner_id,
                    site_id=f"{subject_name}:{draft.lineno}",
                    resource_kind=ResourceKind.LOCK if draft.lock else None,
                    missing_counterpart=False,
                )
            )

    acquire_symbols = {symbol for symbol, _node, _kind in visitor.acquire_sites}
    release_symbols = {symbol for symbol, _node, _kind in visitor.release_sites}
    for symbol, node, _kind in visitor.acquire_sites:
        owner = owner_by_symbol.get(symbol)
        if owner is None:
            continue
        draft = visitor.drafts.get(owner.owning_symbol_id)
        lineno, _col = _site(node)
        missing = symbol not in release_symbols
        lifecycle.append(
            LifecycleRelation(
                relation_id=f"lifecycle:acquire:{owner.owner_id}:{lineno}",
                kind=LifecycleKind.ACQUIRE,
                owner_id=owner.owner_id,
                site_id=f"{subject_name}:{lineno}",
                resource_kind=ResourceKind.LOCK if draft and draft.lock else None,
                missing_counterpart=missing,
                confidence=(
                    AnalysisConfidence.CONSERVATIVE
                    if missing
                    else AnalysisConfidence.EXACT
                ),
                evidence_class=(
                    EvidenceClass.CONSERVATIVE_MAY_FACT
                    if missing
                    else EvidenceClass.EXACT_STATIC_FACT
                ),
            )
        )
        if missing:
            lifecycle.append(
                LifecycleRelation(
                    relation_id=f"lifecycle:release-missing:{owner.owner_id}:{lineno}",
                    kind=LifecycleKind.RELEASE,
                    owner_id=owner.owner_id,
                    site_id=f"{subject_name}:missing-release",
                    resource_kind=ResourceKind.LOCK if draft and draft.lock else None,
                    missing_counterpart=True,
                    confidence=AnalysisConfidence.CONSERVATIVE,
                    evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT,
                )
            )
    for symbol, node, _kind in visitor.release_sites:
        owner = owner_by_symbol.get(symbol)
        if owner is None:
            continue
        if symbol not in acquire_symbols:
            continue
        draft = visitor.drafts.get(owner.owning_symbol_id)
        lineno, _col = _site(node)
        lifecycle.append(
            LifecycleRelation(
                relation_id=f"lifecycle:release:{owner.owner_id}:{lineno}",
                kind=LifecycleKind.RELEASE,
                owner_id=owner.owner_id,
                site_id=f"{subject_name}:{lineno}",
                resource_kind=ResourceKind.LOCK if draft and draft.lock else None,
                missing_counterpart=False,
            )
        )

    for symbol, node, kind, guarded in visitor.with_sites:
        owner = owner_by_symbol.get(symbol)
        if owner is None:
            continue
        lineno, _col = _site(node)
        sync.append(
            SynchronizationRelation(
                relation_id=f"sync:{kind}:{owner.owner_id}:{lineno}",
                kind=(
                    SynchronizationKind.TRANSACTION
                    if kind == "transaction"
                    else SynchronizationKind.LOCK
                ),
                owner_id=owner.owner_id,
                guarded_subject_ids=guarded,
                confidence=AnalysisConfidence.CONSERVATIVE,
                evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT,
            )
        )

    for owner in owners:
        draft = visitor.drafts.get(owner.owning_symbol_id)
        if draft is None or not draft.lock:
            continue
        if any(item.owner_id == owner.owner_id for item in sync):
            continue
        sync.append(
            SynchronizationRelation(
                relation_id=f"sync:lock:{owner.owner_id}",
                kind=SynchronizationKind.LOCK,
                owner_id=owner.owner_id,
                guarded_subject_ids=(),
                confidence=AnalysisConfidence.EXACT,
                evidence_class=EvidenceClass.EXACT_STATIC_FACT,
            )
        )

    for symbol, node, reason in visitor.dynamic_sites:
        lineno, _col = _site(node)
        if reason == "dynamic_access":
            unresolved.append(
                UnresolvedStateItem(
                    subject_id=f"dynamic:{symbol}:{lineno}",
                    reason=UnresolvedStateReason.DYNAMIC_ACCESS,
                    unresolved_fields=("alias_ids", "uniqueness"),
                    confidence=AnalysisConfidence.CONSERVATIVE,
                    evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT,
                )
            )

    summary_ids = {item.subject_id for item in summaries}
    candidates: list[StateExtractionCandidate] = []
    for owner in owners:
        owner_lifecycle = [
            item.relation_id
            for item in lifecycle
            if item.owner_id == owner.owner_id
        ]
        owner_sync = [
            item.relation_id
            for item in sync
            if item.owner_id == owner.owner_id
        ]
        missing_release = any(
            item.owner_id == owner.owner_id
            and item.kind == LifecycleKind.RELEASE.value
            and item.missing_counterpart
            for item in lifecycle
        )
        resource_needs_lifecycle = owner.owner_kind == StateOwnerKind.RESOURCE.value
        complete = (not missing_release) and (
            (not resource_needs_lifecycle)
            or any(
                item.kind == LifecycleKind.ACQUIRE.value
                and item.owner_id == owner.owner_id
                and not item.missing_counterpart
                for item in lifecycle
            )
        )
        if resource_needs_lifecycle and not any(
            item.kind == LifecycleKind.ACQUIRE.value and item.owner_id == owner.owner_id
            for item in lifecycle
        ):
            complete = False
        admitted = (
            owner.uniqueness == StateUniqueness.UNIQUE.value
            and complete
            and owner.confidence == AnalysisConfidence.EXACT.value
        )
        bound_summaries: list[str] = []
        if "<module>" in summary_ids:
            bound_summaries.append("<module>")
        for summary in summaries:
            accessed = (
                summary.reads + summary.writes + summary.may_reads + summary.may_writes
            )
            if (
                owner.owning_symbol_id in accessed
                and summary.subject_id not in bound_summaries
            ):
                bound_summaries.append(summary.subject_id)
        candidates.append(
            StateExtractionCandidate(
                owner_id=owner.owner_id,
                uniqueness=owner.uniqueness,
                alias_set_id=owner.alias_set_id,
                read_write_summary_ids=tuple(bound_summaries),
                lifecycle_ids=tuple(owner_lifecycle),
                synchronization_ids=tuple(owner_sync),
                complete_obligations=complete,
                admitted=admitted,
            )
        )

    return StateOwnershipGraph(
        tree_id=tree_id,
        subject_cid=subject_cid,
        source_cid=resolved_source_cid,
        analyzer_revision=revision,
        environment_cid=environment,
        owners=owners,
        alias_sets=alias_sets,
        read_write_summaries=summaries,
        lifecycle_relations=lifecycle,
        synchronization_relations=sync,
        extraction_candidates=candidates,
        unresolved=unresolved,
    )


def encode_canonical_graph(graph: StateOwnershipGraph) -> bytes:
    if type(graph) is not StateOwnershipGraph:
        raise StateOwnershipError("encode requires a StateOwnershipGraph@1 record")
    data = canonical_dag_json_bytes(graph.identity_payload())
    if canonical_dag_json_bytes(json.loads(data.decode("utf-8"))) != data:
        raise StateOwnershipError("graph encoding is not canonical")
    return data


def decode_canonical_graph(data: bytes) -> StateOwnershipGraph:
    if type(data) is not bytes:
        raise StateOwnershipError("canonical graph bytes must be exact bytes")
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise StateOwnershipError("canonical graph bytes must be UTF-8 JSON") from exc
    if canonical_dag_json_bytes(payload) != data:
        raise StateOwnershipError("graph bytes are not canonical DAG-JSON")
    result = StateOwnershipGraph(
        tree_id=payload["tree_id"],
        subject_cid=payload["subject_cid"],
        source_cid=payload["source_cid"],
        analyzer_id=payload["analyzer_id"],
        analyzer_revision=payload["analyzer_revision"],
        environment_cid=payload["environment_cid"],
        owners=payload["owners"],
        alias_sets=payload["alias_sets"],
        read_write_summaries=payload["read_write_summaries"],
        lifecycle_relations=payload["lifecycle_relations"],
        synchronization_relations=payload["synchronization_relations"],
        extraction_candidates=payload["extraction_candidates"],
        unresolved=payload["unresolved"],
    )
    if result.canonical_bytes() != data:
        raise StateOwnershipError(
            "graph bytes are not the normalized identity payload"
        )
    return result


def provider_free_exports() -> tuple[str, ...]:
    return tuple(sorted(__all__))


__all__ = [
    "ANALYZER_ID",
    "ALIAS_SET_INTERFACE",
    "ALIAS_SET_SCHEMA",
    "AUTHORITY",
    "AUTHORITY_OWNER",
    "DUCKLAKE_IS_AUTHORITY",
    "DUPLICATED_MUTABLE_STATE_REJECTED",
    "FORBIDDEN_OBSERVATIONAL_FIELDS",
    "GOAL_ID",
    "LIFECYCLE_RELATION_INTERFACE",
    "LIFECYCLE_RELATION_SCHEMA",
    "MARKDOWN_IS_NOT_COMPLETION",
    "MISSING_RELEASE_IS_NOT_GUESSED",
    "MODEL_OUTPUT_IS_PROPOSAL_ONLY",
    "OWNER_CANDIDATE_INTERFACE",
    "OWNER_CANDIDATE_SCHEMA",
    "PROGRAM",
    "READ_WRITE_SUMMARY_INTERFACE",
    "READ_WRITE_SUMMARY_SCHEMA",
    "STATE_CAN_AUTHORIZE_COMPLETION",
    "STATE_CAN_AUTHORIZE_TRANSITION",
    "STATE_CAN_CREATE_AUTHORITY",
    "STATE_CID_CODEC",
    "STATE_CID_PROFILE",
    "STATE_CONTRACT_VERSION",
    "STATE_EXTRACTION_CANDIDATE_INTERFACE",
    "STATE_EXTRACTION_CANDIDATE_SCHEMA",
    "STATE_OWNERSHIP_GRAPH_INTERFACE",
    "STATE_OWNERSHIP_GRAPH_SCHEMA",
    "SYNCHRONIZATION_RELATION_INTERFACE",
    "SYNCHRONIZATION_RELATION_SCHEMA",
    "TASK_ID",
    "TEST_PASS_IS_NOT_COMPLETION",
    "UNKNOWN_UNIQUENESS_WIDENS_FRONTIER",
    "UNRESOLVED_STATE_ITEM_INTERFACE",
    "UNRESOLVED_STATE_ITEM_SCHEMA",
    "VECTOR_SIMILARITY_IS_AUTHORITY",
    "WORKER_SELF_APPROVAL",
    "AliasSet",
    "LifecycleKind",
    "LifecycleRelation",
    "OwnerCandidate",
    "ReadWriteSummary",
    "StateExtractionCandidate",
    "StateOwnershipError",
    "StateOwnershipGraph",
    "SynchronizationKind",
    "SynchronizationRelation",
    "UnresolvedStateItem",
    "UnresolvedStateReason",
    "analyze_source",
    "build_state_ownership_graph",
    "decode_canonical_graph",
    "encode_canonical_graph",
    "provider_free_exports",
    "state_cid_profile",
]
