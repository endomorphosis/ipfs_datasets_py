"""Exact incremental verification planning over existing semantic authorities.

This module is deliberately a composition adapter.  Repository facts and the
base invalidation plan remain owned by ``software_contracts.semantic_index``;
component semantics remain owned by :class:`CompositionalContract`; and cache
identity remains owned by :class:`CanonicalProofCacheKey`.  No repository
graph, semantic-state root, proof cache, or mutable solver store is introduced
here.

The adapter closes the base invalidation frontier over producer-to-consumer
contract edges and strongly connected components.  Previously produced
evidence is reusable only when it is outside that frontier, is exact, and its
complete canonical cache key is independently re-admitted against the key for
the current request.  A ``solver_session`` binding denotes an immutable replay
manifest/context identity, never permission to reuse a process by pathname.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Final, cast

from ipfs_datasets_py.logic.common.canonical_cache_key import (
    CanonicalCacheKeyError,
    CanonicalProofCacheKey,
    admit_cache_hit,
    admit_canonical_cache_key,
)
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.software_contracts.compositional import (
    CompositionalContract,
    ContractConfidence,
    SemanticSupport,
)
from ipfs_datasets_py.logic.software_contracts.content import validate_cid
from ipfs_datasets_py.logic.software_contracts.semantic_index.index import (
    calculate_invalidation,
    diff_repository_states,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    InvalidationPlan,
    RepositoryState,
    RepositoryStateDelta,
)
from ipfs_datasets_py.logic.software_verification.assume_guarantee import (
    ComponentCompositionGraph,
)

INCREMENTAL_VERIFICATION_INTERFACE: Final = "IncrementalVerificationPlan@1"
INCREMENTAL_VERIFICATION_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.software-verification.incremental-plan-receipt@1"
)
VERIFICATION_EVIDENCE_BINDING_SCHEMA: Final = (
    "ipfs-datasets.software-verification.evidence-binding@1"
)
EVIDENCE_REUSE_REQUEST_SCHEMA: Final = (
    "ipfs-datasets.software-verification.evidence-reuse-request@1"
)
EVIDENCE_DECISION_SCHEMA: Final = "ipfs-datasets.software-verification.evidence-decision@1"


class IncrementalVerificationError(ValueError):
    """Raised when an incremental verification request is malformed."""


class IncrementalVerificationStaleError(IncrementalVerificationError):
    """Raised when a supplied graph, delta, plan, or binding is stale."""


class VerificationBindingKind(StrEnum):
    """Closed categories of verification work affected by a semantic delta."""

    ABSTRACT_STATE = "abstract_state"
    CONTRACT = "contract"
    SOLVER_SESSION = "solver_session"
    CAPSULE = "capsule"
    PROOF = "proof"
    TEST = "test"


class EvidenceDecisionDisposition(StrEnum):
    """Whether one existing evidence binding may serve the current request."""

    REUSED = "reused"
    INVALIDATED = "invalidated"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise IncrementalVerificationError(f"{label} must be a trimmed non-empty string")
    return value


def _cid(value: object, label: str) -> str:
    try:
        return validate_cid(value)
    except (TypeError, ValueError) as error:
        raise IncrementalVerificationError(f"{label} must be a valid CID") from error


def _unique_texts(
    values: Sequence[str] | object,
    label: str,
    *,
    nonempty: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise IncrementalVerificationError(f"{label} must be a sequence")
    result = tuple(sorted(_text(item, f"{label} item") for item in values))
    if len(result) != len(set(result)):
        raise IncrementalVerificationError(f"{label} must not contain duplicates")
    if nonempty and not result:
        raise IncrementalVerificationError(f"{label} must not be empty")
    return result


def _unique_cids(values: Sequence[str] | object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise IncrementalVerificationError(f"{label} must be a sequence")
    result = tuple(sorted(_cid(item, f"{label} item") for item in values))
    if len(result) != len(set(result)):
        raise IncrementalVerificationError(f"{label} must not contain duplicates")
    return result


def _closed(value: Mapping[str, Any], fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise IncrementalVerificationError(f"{label} must be a mapping")
    actual = set(value)
    if actual != fields:
        raise IncrementalVerificationError(
            f"{label} fields are closed (missing={sorted(fields - actual)}, "
            f"extra={sorted(actual - fields)})"
        )
    return dict(value)


@dataclass(frozen=True, slots=True)
class VerificationEvidenceBinding:
    """Reference to one immutable prior artifact and its semantic cache key.

    ``observed_state_cid`` records provenance rather than declaring repository
    authority.  ``subject_ids`` bind the artifact to existing semantic-index or
    component identities; ``dependency_ids`` carry exact additional selectors.
    Large artifact bodies remain in the existing content-addressed store.
    """

    binding_id: str
    kind: VerificationBindingKind | str
    artifact_cid: str
    observed_state_cid: str
    subject_ids: tuple[str, ...]
    dependency_ids: tuple[str, ...]
    contract_cids: tuple[str, ...]
    cache_key: CanonicalProofCacheKey
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    dynamic_frontier: bool = False
    schema: str = VERIFICATION_EVIDENCE_BINDING_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "artifact_cid",
            "binding_id",
            "cache_key",
            "confidence",
            "contract_cids",
            "dependency_ids",
            "dynamic_frontier",
            "kind",
            "observed_state_cid",
            "schema",
            "subject_ids",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _text(self.binding_id, "binding_id"))
        try:
            kind = (
                self.kind
                if isinstance(self.kind, VerificationBindingKind)
                else VerificationBindingKind(self.kind)
            )
            confidence = (
                self.confidence
                if isinstance(self.confidence, AnalysisConfidence)
                else AnalysisConfidence(self.confidence)
            )
        except ValueError as error:
            raise IncrementalVerificationError(str(error)) from error
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "artifact_cid", _cid(self.artifact_cid, "artifact_cid"))
        object.__setattr__(
            self,
            "observed_state_cid",
            _cid(self.observed_state_cid, "observed_state_cid"),
        )
        object.__setattr__(
            self,
            "subject_ids",
            _unique_texts(self.subject_ids, "subject_ids", nonempty=True),
        )
        object.__setattr__(
            self,
            "dependency_ids",
            _unique_texts(self.dependency_ids, "dependency_ids"),
        )
        object.__setattr__(self, "contract_cids", _unique_cids(self.contract_cids, "contract_cids"))
        object.__setattr__(self, "cache_key", admit_canonical_cache_key(self.cache_key))
        if not isinstance(self.dynamic_frontier, bool):
            raise IncrementalVerificationError("dynamic_frontier must be bool")
        if self.schema != VERIFICATION_EVIDENCE_BINDING_SCHEMA:
            raise IncrementalVerificationError("unsupported evidence binding schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_cid": self.artifact_cid,
            "binding_id": self.binding_id,
            "cache_key": self.cache_key.to_dict(),
            "confidence": cast(AnalysisConfidence, self.confidence).value,
            "contract_cids": list(self.contract_cids),
            "dependency_ids": list(self.dependency_ids),
            "dynamic_frontier": self.dynamic_frontier,
            "kind": cast(VerificationBindingKind, self.kind).value,
            "observed_state_cid": self.observed_state_cid,
            "schema": self.schema,
            "subject_ids": list(self.subject_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> VerificationEvidenceBinding:
        payload = _closed(value, cls._FIELDS, cls.__name__)
        payload["cache_key"] = CanonicalProofCacheKey.from_dict(payload["cache_key"])
        payload["subject_ids"] = tuple(payload["subject_ids"])
        payload["dependency_ids"] = tuple(payload["dependency_ids"])
        payload["contract_cids"] = tuple(payload["contract_cids"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class EvidenceReuseRequest:
    """A prior binding paired with a freshly derived complete cache key."""

    binding: VerificationEvidenceBinding
    current_cache_key: CanonicalProofCacheKey
    schema: str = EVIDENCE_REUSE_REQUEST_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"binding", "current_cache_key", "schema"})

    def __post_init__(self) -> None:
        if not isinstance(self.binding, VerificationEvidenceBinding):
            raise IncrementalVerificationError("binding must be a VerificationEvidenceBinding")
        object.__setattr__(
            self,
            "current_cache_key",
            admit_canonical_cache_key(self.current_cache_key),
        )
        if self.schema != EVIDENCE_REUSE_REQUEST_SCHEMA:
            raise IncrementalVerificationError("unsupported evidence reuse schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding": self.binding.to_dict(),
            "current_cache_key": self.current_cache_key.to_dict(),
            "schema": self.schema,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvidenceReuseRequest:
        payload = _closed(value, cls._FIELDS, cls.__name__)
        return cls(
            binding=VerificationEvidenceBinding.from_dict(payload["binding"]),
            current_cache_key=CanonicalProofCacheKey.from_dict(payload["current_cache_key"]),
            schema=payload["schema"],
        )


@dataclass(frozen=True, slots=True)
class EvidenceDecision:
    """Auditable reuse or invalidation decision for one prior binding."""

    binding_id: str
    kind: VerificationBindingKind | str
    artifact_cid: str
    disposition: EvidenceDecisionDisposition | str
    reason_codes: tuple[str, ...]
    admitted_cache_key_id: str
    evidence_kind: str
    authority_ceiling: str
    schema: str = EVIDENCE_DECISION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _text(self.binding_id, "binding_id"))
        object.__setattr__(self, "artifact_cid", _cid(self.artifact_cid, "artifact_cid"))
        try:
            kind = (
                self.kind
                if isinstance(self.kind, VerificationBindingKind)
                else VerificationBindingKind(self.kind)
            )
            disposition = (
                self.disposition
                if isinstance(self.disposition, EvidenceDecisionDisposition)
                else EvidenceDecisionDisposition(self.disposition)
            )
        except ValueError as error:
            raise IncrementalVerificationError(str(error)) from error
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(
            self,
            "reason_codes",
            _unique_texts(self.reason_codes, "reason_codes", nonempty=True),
        )
        for name in ("admitted_cache_key_id", "evidence_kind", "authority_ceiling"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.schema != EVIDENCE_DECISION_SCHEMA:
            raise IncrementalVerificationError("unsupported evidence decision schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_cache_key_id": self.admitted_cache_key_id,
            "artifact_cid": self.artifact_cid,
            "authority_ceiling": self.authority_ceiling,
            "binding_id": self.binding_id,
            "disposition": cast(EvidenceDecisionDisposition, self.disposition).value,
            "evidence_kind": self.evidence_kind,
            "kind": cast(VerificationBindingKind, self.kind).value,
            "reason_codes": list(self.reason_codes),
            "schema": self.schema,
        }


def _decision_ids(
    decisions: tuple[EvidenceDecision, ...],
    kind: VerificationBindingKind,
) -> tuple[str, ...]:
    return tuple(
        item.binding_id
        for item in decisions
        if item.kind is kind and item.disposition is EvidenceDecisionDisposition.INVALIDATED
    )


@dataclass(frozen=True, slots=True)
class IncrementalVerificationPlanReceipt:
    """Content-addressed result of one exact incremental planning operation."""

    repository_id: str
    previous_state_cid: str
    current_state_cid: str
    semantic_delta_cid: str
    invalidation_plan_cid: str
    previous_composition_graph_cid: str
    composition_graph_cid: str
    previous_contract_root: str
    contract_root: str
    changed_symbol_ids: tuple[str, ...]
    changed_artifact_ids: tuple[str, ...]
    changed_edge_ids: tuple[str, ...]
    direct_affected_component_ids: tuple[str, ...]
    reverse_contract_closure: tuple[str, ...]
    affected_sccs: tuple[tuple[str, ...], ...]
    invalidated_contract_cids: tuple[str, ...]
    base_invalidation_obligation_ids: tuple[str, ...]
    selected_test_ids: tuple[str, ...]
    selected_proof_ids: tuple[str, ...]
    dynamic_frontier: tuple[str, ...]
    evidence_decisions: tuple[EvidenceDecision, ...]
    limitations: tuple[str, ...]
    schema: str = INCREMENTAL_VERIFICATION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _text(self.repository_id, "repository_id"))
        for name in (
            "previous_state_cid",
            "current_state_cid",
            "semantic_delta_cid",
            "invalidation_plan_cid",
            "composition_graph_cid",
            "contract_root",
        ):
            object.__setattr__(self, name, _cid(getattr(self, name), name))
        for name in ("previous_composition_graph_cid", "previous_contract_root"):
            value = getattr(self, name)
            if value:
                object.__setattr__(self, name, _cid(value, name))
        for name in (
            "changed_symbol_ids",
            "changed_artifact_ids",
            "changed_edge_ids",
            "direct_affected_component_ids",
            "reverse_contract_closure",
            "selected_test_ids",
            "selected_proof_ids",
            "dynamic_frontier",
            "limitations",
        ):
            object.__setattr__(self, name, _unique_texts(getattr(self, name), name))
        object.__setattr__(
            self,
            "invalidated_contract_cids",
            _unique_cids(self.invalidated_contract_cids, "invalidated_contract_cids"),
        )
        object.__setattr__(
            self,
            "base_invalidation_obligation_ids",
            _unique_cids(
                self.base_invalidation_obligation_ids,
                "base_invalidation_obligation_ids",
            ),
        )
        sccs = tuple(sorted(tuple(sorted(item)) for item in self.affected_sccs))
        if any(not item for item in sccs) or len(sccs) != len(set(sccs)):
            raise IncrementalVerificationError("affected_sccs must be unique and non-empty")
        object.__setattr__(self, "affected_sccs", sccs)
        decisions = tuple(sorted(self.evidence_decisions, key=lambda item: item.binding_id))
        if any(not isinstance(item, EvidenceDecision) for item in decisions):
            raise IncrementalVerificationError(
                "evidence_decisions must contain EvidenceDecision values"
            )
        if len({item.binding_id for item in decisions}) != len(decisions):
            raise IncrementalVerificationError("evidence decision binding IDs must be unique")
        object.__setattr__(self, "evidence_decisions", decisions)
        if self.schema != INCREMENTAL_VERIFICATION_RECEIPT_SCHEMA:
            raise IncrementalVerificationError("unsupported incremental receipt schema")

    @property
    def reused_evidence_binding_ids(self) -> tuple[str, ...]:
        return tuple(
            item.binding_id
            for item in self.evidence_decisions
            if item.disposition is EvidenceDecisionDisposition.REUSED
        )

    @property
    def invalidated_abstract_state_binding_ids(self) -> tuple[str, ...]:
        return _decision_ids(self.evidence_decisions, VerificationBindingKind.ABSTRACT_STATE)

    @property
    def invalidated_contract_binding_ids(self) -> tuple[str, ...]:
        return _decision_ids(self.evidence_decisions, VerificationBindingKind.CONTRACT)

    @property
    def invalidated_solver_binding_ids(self) -> tuple[str, ...]:
        return _decision_ids(self.evidence_decisions, VerificationBindingKind.SOLVER_SESSION)

    @property
    def invalidated_capsule_binding_ids(self) -> tuple[str, ...]:
        return _decision_ids(self.evidence_decisions, VerificationBindingKind.CAPSULE)

    @property
    def invalidated_proof_binding_ids(self) -> tuple[str, ...]:
        return _decision_ids(self.evidence_decisions, VerificationBindingKind.PROOF)

    @property
    def invalidated_test_binding_ids(self) -> tuple[str, ...]:
        return _decision_ids(self.evidence_decisions, VerificationBindingKind.TEST)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "affected_sccs": [list(item) for item in self.affected_sccs],
            "base_invalidation_obligation_ids": list(self.base_invalidation_obligation_ids),
            "changed_artifact_ids": list(self.changed_artifact_ids),
            "changed_edge_ids": list(self.changed_edge_ids),
            "changed_symbol_ids": list(self.changed_symbol_ids),
            "composition_graph_cid": self.composition_graph_cid,
            "contract_root": self.contract_root,
            "current_state_cid": self.current_state_cid,
            "direct_affected_component_ids": list(self.direct_affected_component_ids),
            "dynamic_frontier": list(self.dynamic_frontier),
            "evidence_decisions": [item.to_dict() for item in self.evidence_decisions],
            "interface": INCREMENTAL_VERIFICATION_INTERFACE,
            "invalidated_abstract_state_binding_ids": list(
                self.invalidated_abstract_state_binding_ids
            ),
            "invalidated_capsule_binding_ids": list(self.invalidated_capsule_binding_ids),
            "invalidated_contract_binding_ids": list(self.invalidated_contract_binding_ids),
            "invalidated_contract_cids": list(self.invalidated_contract_cids),
            "invalidated_proof_binding_ids": list(self.invalidated_proof_binding_ids),
            "invalidated_solver_binding_ids": list(self.invalidated_solver_binding_ids),
            "invalidated_test_binding_ids": list(self.invalidated_test_binding_ids),
            "invalidation_plan_cid": self.invalidation_plan_cid,
            "limitations": list(self.limitations),
            "previous_composition_graph_cid": self.previous_composition_graph_cid,
            "previous_contract_root": self.previous_contract_root,
            "previous_state_cid": self.previous_state_cid,
            "repository_id": self.repository_id,
            "reused_evidence_binding_ids": list(self.reused_evidence_binding_ids),
            "reverse_contract_closure": list(self.reverse_contract_closure),
            "schema": self.schema,
            "selected_proof_ids": list(self.selected_proof_ids),
            "selected_test_ids": list(self.selected_test_ids),
            "semantic_delta_cid": self.semantic_delta_cid,
        }

    @property
    def receipt_cid(self) -> str:
        return canonical_identity(
            self.identity_payload(),
            domain="logic.software-verification.incremental-plan-receipt",
            schema_version=self.schema,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        result = self.identity_payload()
        result["receipt_cid"] = self.receipt_cid
        return result


def _contract_symbol_id(contract: CompositionalContract, known_symbol_ids: set[str]) -> str | None:
    """Resolve only an explicit or identity-equal semantic-index binding."""

    explicit = contract.attributes.to_dict().get("semantic_index_symbol_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    if contract.component_id in known_symbol_ids:
        return contract.component_id
    return None


def _validate_graph_freshness(
    graph: ComponentCompositionGraph,
    state: RepositoryState,
    *,
    label: str,
) -> None:
    if not isinstance(graph, ComponentCompositionGraph):
        raise IncrementalVerificationError(f"{label} must be a ComponentCompositionGraph")
    if graph.semantic_state_root != state.state_cid:
        raise IncrementalVerificationStaleError(
            f"{label}.semantic_state_root does not match the supplied state"
        )
    symbols = {item.stable_id: item for item in state.symbols}
    for contract in graph.contracts:
        explicit = contract.attributes.to_dict().get("semantic_index_symbol_id")
        if explicit is None:
            continue
        if not isinstance(explicit, str) or explicit not in symbols:
            raise IncrementalVerificationStaleError(
                f"contract {contract.contract_id} has an unresolved semantic-index symbol"
            )
        symbol = symbols[explicit]
        if contract.symbol_version_root != symbol.version_cid:
            raise IncrementalVerificationStaleError(
                f"contract {contract.contract_id} has a stale symbol-version root"
            )
        if symbol.source_cid and contract.source_root != symbol.source_cid:
            raise IncrementalVerificationStaleError(
                f"contract {contract.contract_id} has a stale source root"
            )


def _tarjan_sccs(
    components: set[str], adjacency: Mapping[str, set[str]]
) -> tuple[tuple[str, ...], ...]:
    """Return cyclic SCCs of the existing composition graph projection."""

    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lows: dict[str, int] = {}
    result: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lows[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(adjacency.get(node, set())):
            if target not in indexes:
                visit(target)
                lows[node] = min(lows[node], lows[target])
            elif target in on_stack:
                lows[node] = min(lows[node], indexes[target])
        if lows[node] != indexes[node]:
            return
        members: list[str] = []
        while True:
            item = stack.pop()
            on_stack.remove(item)
            members.append(item)
            if item == node:
                break
        has_self_edge = node in adjacency.get(node, set())
        if len(members) > 1 or has_self_edge:
            result.append(tuple(sorted(members)))

    for component in sorted(components):
        if component not in indexes:
            visit(component)
    return tuple(sorted(result))


def _close_contract_frontier(
    direct: set[str],
    components: set[str],
    adjacency: Mapping[str, set[str]],
    sccs: tuple[tuple[str, ...], ...],
) -> set[str]:
    """Compute reverse consumer closure and close every touched SCC."""

    affected = set(direct)
    changed = True
    while changed:
        changed = False
        queue: deque[str] = deque(sorted(affected))
        seen = set(affected)
        while queue:
            producer = queue.popleft()
            for consumer in sorted(adjacency.get(producer, set())):
                if consumer not in seen:
                    seen.add(consumer)
                    queue.append(consumer)
        if seen != affected:
            affected = seen
            changed = True
        for scc in sccs:
            if affected.intersection(scc) and not set(scc) <= affected:
                affected.update(scc)
                changed = True
    return affected.intersection(components)


def _change_selectors(
    previous: RepositoryState,
    current: RepositoryState,
    delta: RepositoryStateDelta,
) -> set[str]:
    changed_symbols = (
        set(delta.added_symbol_ids) | set(delta.deleted_symbol_ids) | set(delta.modified_symbol_ids)
    )
    changed_artifacts = (
        set(delta.added_artifact_ids)
        | set(delta.deleted_artifact_ids)
        | set(delta.modified_artifact_ids)
    )
    selectors = (
        set(changed_symbols)
        | set(changed_artifacts)
        | set(delta.added_edge_ids)
        | set(delta.deleted_edge_ids)
    )
    for state in (previous, current):
        for symbol in state.symbols:
            if symbol.stable_id in changed_symbols:
                selectors.add(symbol.version_cid)
                selectors.add(symbol.source_cid)
                selectors.add(symbol.module_path)
        for artifact in state.artifacts:
            if artifact.artifact_id in changed_artifacts:
                selectors.add(artifact.path)
                if artifact.source_cid:
                    selectors.add(artifact.source_cid)
    return selectors


def _dynamic_frontier(
    previous: RepositoryState,
    current: RepositoryState,
    affected_components: set[str],
    changed_symbols: set[str],
    changed_artifacts: set[str],
    graph_contracts: Mapping[str, CompositionalContract],
    base_plan: InvalidationPlan,
) -> tuple[str, ...]:
    frontier: set[str] = set()
    symbol_ids = affected_components | changed_symbols
    for state in (previous, current):
        for symbol in state.symbols:
            if (
                symbol.stable_id in symbol_ids
                and symbol.confidence != AnalysisConfidence.EXACT.value
            ):
                frontier.add(f"symbol:{symbol.stable_id}:{symbol.confidence}")
        for artifact in state.artifacts:
            if (
                artifact.artifact_id in changed_artifacts
                and artifact.confidence != AnalysisConfidence.EXACT.value
            ):
                frontier.add(f"artifact:{artifact.artifact_id}:{artifact.confidence}")
        for edge in state.edges:
            if (
                edge.source_id in symbol_ids or edge.target_id in symbol_ids
            ) and edge.confidence != AnalysisConfidence.EXACT.value:
                frontier.add(f"edge:{edge.edge_id}:{edge.confidence}")
    for component_id in sorted(affected_components):
        contract = graph_contracts.get(component_id)
        if contract is None:
            frontier.add(f"component:{component_id}:removed_or_unbound")
            continue
        if contract.open_world:
            frontier.add(f"contract:{component_id}:open_world")
        if contract.confidence in {
            ContractConfidence.HEURISTIC,
            ContractConfidence.OPAQUE,
        }:
            confidence = (
                contract.confidence.value
                if isinstance(contract.confidence, ContractConfidence)
                else contract.confidence
            )
            frontier.add(f"contract:{component_id}:{confidence}")
        if any(
            clause.support is SemanticSupport.OPAQUE for clause in contract.all_semantic_clauses
        ):
            frontier.add(f"contract:{component_id}:opaque_clause")
    for obligation in base_plan.obligations:
        if obligation.remediation_kind == "retrieve_raw_source":
            frontier.add(f"obligation:{obligation.obligation_id}:raw_source")
    return tuple(sorted(frontier))


def _evidence_decisions(
    requests: Sequence[EvidenceReuseRequest],
    *,
    previous_state_cid: str,
    current_state_cid: str,
    affected_components: set[str],
    changed_selectors: set[str],
    base_subjects: set[str],
    current_contract_cids: set[str],
) -> tuple[EvidenceDecision, ...]:
    decisions: list[EvidenceDecision] = []
    seen: set[str] = set()
    for request in requests:
        if not isinstance(request, EvidenceReuseRequest):
            raise IncrementalVerificationError(
                "evidence_requests must contain EvidenceReuseRequest values"
            )
        binding = request.binding
        if binding.binding_id in seen:
            raise IncrementalVerificationError("evidence binding IDs must be unique")
        seen.add(binding.binding_id)
        if binding.observed_state_cid not in {previous_state_cid, current_state_cid}:
            raise IncrementalVerificationStaleError(
                f"evidence binding {binding.binding_id} references an unrelated state"
            )

        reasons: set[str] = set()
        subjects = set(binding.subject_ids)
        dependencies = set(binding.dependency_ids)
        if subjects & (affected_components | base_subjects | changed_selectors):
            reasons.add("affected_semantic_frontier")
        if dependencies & changed_selectors:
            reasons.add("changed_dependency")
        if any(cid not in current_contract_cids for cid in binding.contract_cids):
            reasons.add("stale_contract_binding")
        if binding.dynamic_frontier:
            reasons.add("dynamic_frontier")
        if binding.confidence is not AnalysisConfidence.EXACT:
            reasons.add("non_exact_evidence")

        admitted_key_id = request.current_cache_key.key_id
        if not reasons:
            try:
                admitted = admit_cache_hit(binding.cache_key, request.current_cache_key)
            except CanonicalCacheKeyError:
                reasons.add("cache_key_mismatch")
            else:
                admitted_key_id = admitted.key_id

        disposition = (
            EvidenceDecisionDisposition.INVALIDATED
            if reasons
            else EvidenceDecisionDisposition.REUSED
        )
        decisions.append(
            EvidenceDecision(
                binding_id=binding.binding_id,
                kind=binding.kind,
                artifact_cid=binding.artifact_cid,
                disposition=disposition,
                reason_codes=tuple(sorted(reasons or {"exact_cache_key_revalidated"})),
                admitted_cache_key_id=admitted_key_id,
                evidence_kind=request.current_cache_key.evidence_kind.value,
                authority_ceiling=request.current_cache_key.authority_ceiling.value,
            )
        )
    return tuple(sorted(decisions, key=lambda item: item.binding_id))


def plan_incremental_verification(
    previous_state: RepositoryState,
    current_state: RepositoryState,
    *,
    composition_graph: ComponentCompositionGraph,
    previous_composition_graph: ComponentCompositionGraph | None = None,
    evidence_requests: Sequence[EvidenceReuseRequest] = (),
    supplied_delta: RepositoryStateDelta | None = None,
    supplied_invalidation_plan: InvalidationPlan | None = None,
) -> IncrementalVerificationPlanReceipt:
    """Plan the minimal conservative verification frontier for one mutation.

    Supplied deltas and invalidation plans are merely replay optimizations: both
    are recomputed from the two repository states and rejected when stale.
    Composition graphs must bind the exact corresponding state roots.  Cache
    admission never raises evidence authority and cannot override an affected
    semantic, contract, SCC, or dynamic frontier.
    """

    if not isinstance(previous_state, RepositoryState) or not isinstance(
        current_state, RepositoryState
    ):
        raise IncrementalVerificationError(
            "previous_state and current_state must be RepositoryState values"
        )
    if previous_state.repository_id != current_state.repository_id:
        raise IncrementalVerificationError("repository IDs must match")
    _validate_graph_freshness(composition_graph, current_state, label="composition_graph")
    if previous_composition_graph is not None:
        _validate_graph_freshness(
            previous_composition_graph,
            previous_state,
            label="previous_composition_graph",
        )

    delta = diff_repository_states(previous_state, current_state)
    if supplied_delta is not None:
        if not isinstance(supplied_delta, RepositoryStateDelta):
            raise IncrementalVerificationError("supplied_delta must be a RepositoryStateDelta")
        if supplied_delta.delta_cid != delta.delta_cid:
            raise IncrementalVerificationStaleError("supplied semantic delta is stale")
    base_plan = calculate_invalidation(previous_state, current_state, delta)
    if supplied_invalidation_plan is not None:
        if not isinstance(supplied_invalidation_plan, InvalidationPlan):
            raise IncrementalVerificationError(
                "supplied_invalidation_plan must be an InvalidationPlan"
            )
        if supplied_invalidation_plan.plan_cid != base_plan.plan_cid:
            raise IncrementalVerificationStaleError("supplied invalidation plan is stale")

    changed_symbols = (
        set(delta.added_symbol_ids) | set(delta.deleted_symbol_ids) | set(delta.modified_symbol_ids)
    )
    changed_artifacts = (
        set(delta.added_artifact_ids)
        | set(delta.deleted_artifact_ids)
        | set(delta.modified_artifact_ids)
    )
    changed_edges = set(delta.added_edge_ids) | set(delta.deleted_edge_ids)
    selectors = _change_selectors(previous_state, current_state, delta)
    base_subjects = {item.subject_id for item in base_plan.obligations}

    graphs = tuple(
        graph for graph in (previous_composition_graph, composition_graph) if graph is not None
    )
    contracts_by_component: dict[str, list[CompositionalContract]] = defaultdict(list)
    current_contracts = {item.component_id: item for item in composition_graph.contracts}
    previous_contracts = (
        {}
        if previous_composition_graph is None
        else {item.component_id: item for item in previous_composition_graph.contracts}
    )
    components: set[str] = set()
    adjacency: dict[str, set[str]] = defaultdict(set)
    known_symbol_ids = {
        item.stable_id for item in (*previous_state.symbols, *current_state.symbols)
    }
    direct: set[str] = set()
    for graph in graphs:
        for contract in graph.contracts:
            components.add(contract.component_id)
            contracts_by_component[contract.component_id].append(contract)
            symbol_id = _contract_symbol_id(contract, known_symbol_ids)
            if symbol_id in changed_symbols or symbol_id in base_subjects:
                direct.add(contract.component_id)
            if set(contract.invalidation_selectors) & selectors:
                direct.add(contract.component_id)
            if {contract.source_root, contract.symbol_version_root} & selectors:
                direct.add(contract.component_id)
        for edge in graph.edges:
            components.update((edge.producer_component_id, edge.consumer_component_id))
            adjacency[edge.producer_component_id].add(edge.consumer_component_id)

    all_component_ids = set(previous_contracts) | set(current_contracts)
    for component_id in all_component_ids:
        old = previous_contracts.get(component_id)
        new = current_contracts.get(component_id)
        if old is None or new is None or old.cid != new.cid:
            direct.add(component_id)

    sccs = _tarjan_sccs(components, adjacency)
    affected = _close_contract_frontier(direct, components, adjacency, sccs)
    affected_sccs = tuple(scc for scc in sccs if set(scc) & affected)
    invalidated_contract_cids = {
        contract.cid
        for component_id in affected
        for contract in contracts_by_component.get(component_id, ())
    }
    current_contract_cids = {item.cid for item in composition_graph.contracts}

    decisions = _evidence_decisions(
        evidence_requests,
        previous_state_cid=previous_state.state_cid,
        current_state_cid=current_state.state_cid,
        affected_components=affected,
        changed_selectors=selectors,
        base_subjects=base_subjects,
        current_contract_cids=current_contract_cids,
    )

    selected_tests = {
        item.subject_id for item in base_plan.obligations if item.remediation_kind == "rerun_test"
    }
    selected_proofs = {
        item.subject_id for item in base_plan.obligations if item.remediation_kind == "rerun_proof"
    }
    request_by_id = {item.binding.binding_id: item for item in evidence_requests}
    for decision in decisions:
        if decision.disposition is not EvidenceDecisionDisposition.INVALIDATED:
            continue
        binding = request_by_id[decision.binding_id].binding
        if decision.kind is VerificationBindingKind.TEST:
            selected_tests.update(binding.subject_ids)
        elif decision.kind is VerificationBindingKind.PROOF:
            selected_proofs.update(binding.subject_ids)

    dynamic = _dynamic_frontier(
        previous_state,
        current_state,
        affected,
        changed_symbols,
        changed_artifacts,
        current_contracts,
        base_plan,
    )
    limitations = {"dynamic_frontier_requires_raw_source_or_full_verification" for _item in dynamic}
    if previous_composition_graph is None:
        limitations.add("previous_contract_graph_unavailable")

    return IncrementalVerificationPlanReceipt(
        repository_id=current_state.repository_id,
        previous_state_cid=previous_state.state_cid,
        current_state_cid=current_state.state_cid,
        semantic_delta_cid=delta.delta_cid,
        invalidation_plan_cid=base_plan.plan_cid,
        previous_composition_graph_cid=(
            "" if previous_composition_graph is None else previous_composition_graph.graph_cid
        ),
        composition_graph_cid=composition_graph.graph_cid,
        previous_contract_root=(
            "" if previous_composition_graph is None else previous_composition_graph.contract_root
        ),
        contract_root=composition_graph.contract_root,
        changed_symbol_ids=tuple(sorted(changed_symbols)),
        changed_artifact_ids=tuple(sorted(changed_artifacts)),
        changed_edge_ids=tuple(sorted(changed_edges)),
        direct_affected_component_ids=tuple(sorted(direct)),
        reverse_contract_closure=tuple(sorted(affected)),
        affected_sccs=affected_sccs,
        invalidated_contract_cids=tuple(sorted(invalidated_contract_cids)),
        base_invalidation_obligation_ids=tuple(
            item.obligation_id for item in base_plan.obligations
        ),
        selected_test_ids=tuple(sorted(selected_tests)),
        selected_proof_ids=tuple(sorted(selected_proofs)),
        dynamic_frontier=dynamic,
        evidence_decisions=decisions,
        limitations=tuple(sorted(limitations)),
    )


__all__ = [
    "EVIDENCE_DECISION_SCHEMA",
    "EVIDENCE_REUSE_REQUEST_SCHEMA",
    "INCREMENTAL_VERIFICATION_INTERFACE",
    "INCREMENTAL_VERIFICATION_RECEIPT_SCHEMA",
    "VERIFICATION_EVIDENCE_BINDING_SCHEMA",
    "EvidenceDecision",
    "EvidenceDecisionDisposition",
    "EvidenceReuseRequest",
    "IncrementalVerificationError",
    "IncrementalVerificationPlanReceipt",
    "IncrementalVerificationStaleError",
    "VerificationBindingKind",
    "VerificationEvidenceBinding",
    "plan_incremental_verification",
]
