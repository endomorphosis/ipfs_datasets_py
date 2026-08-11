"""Bounded, evidence-backed invalidation obligations for semantic deltas.

The engine deliberately reports work which must be reconsidered; it never
rewrites a caller, test, schema adapter, or proof.  Every dependent obligation
is attached to the edge which justified it, making a plan independently
auditable and stable across equivalent input ordering.
"""

from __future__ import annotations

from enum import Enum
from typing import Final, Iterable

from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import (
    classify_symbol_change,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    DependencyEdge,
    InvalidationObligation,
    InvalidationPlan,
    RelationType,
    RepositoryState,
    RepositoryStateDelta,
    SymbolKind,
    SymbolRecord,
)


class InvalidationError(ValueError):
    """Raised when an invalidation request is not tied to its two states."""


class InvalidationReason(str, Enum):
    """Closed, externally useful vocabulary for obligation explanations."""

    NEW_CAPSULE = "new_capsule"
    PROOF_RERUN = "proof_rerun"
    STALE_TEST_RECEIPT = "stale_test_receipt"
    CALLER_SIGNATURE_MISMATCH = "caller_signature_mismatch"
    OBSOLETE_SCHEMA_ADAPTER = "obsolete_schema_adapter"
    EFFECT_ASSUMPTION_STALE = "effect_assumption_stale"
    EXCEPTION_RECOVERY_STALE = "exception_recovery_stale"
    PURITY_SECURITY_REVIEW = "purity_security_review"
    ENVIRONMENT_RECEIPT_STALE = "environment_receipt_stale"
    DELETED_SYMBOL_DEPENDENCY = "deleted_symbol_dependency"
    RAW_SOURCE_REQUIRED = "raw_source_requirement"


class InvalidationRule(str, Enum):
    """The finite rule families implemented by :func:`calculate_invalidation`."""

    BODY = "body"
    SIGNATURE = "signature"
    EFFECTS = "effects"
    EXCEPTIONS = "exceptions"
    SCHEMA = "schema"
    FIXTURE_CONFIG = "fixture_config"
    ENVIRONMENT = "environment"
    DELETION = "deletion"
    OPAQUE = "opaque"


MAX_INVALIDATION_OBLIGATIONS: Final[int] = 1_000
_CONFIDENCE_RANK: Final[dict[str, int]] = {"exact": 0, "conservative": 1, "heuristic": 2, "opaque": 3}
_ADAPTER_RELATIONS: Final[frozenset[str]] = frozenset({"serializes", "deserializes", "validates", "implements"})
_TEST_RELATIONS: Final[frozenset[str]] = frozenset({"tested_by", "uses_fixture", "configured_by"})
_ENVIRONMENT_WORDS: Final[tuple[str, ...]] = ("lock", "dependency", "environment", "requirements", "poetry", "pipfile")


def _least_confident(*values: str) -> str:
    return max(values, key=lambda value: _CONFIDENCE_RANK[value])


def _is_opaque(record: SymbolRecord | ArtifactRecord | DependencyEdge) -> bool:
    return record.confidence == AnalysisConfidence.OPAQUE.value or (
        isinstance(record, DependencyEdge) and record.metadata.get("resolution") == "unresolved"
    )


def _is_test(symbol: SymbolRecord | None) -> bool:
    return symbol is not None and symbol.kind == SymbolKind.TEST.value


def _artifact_is_environment(artifact: ArtifactRecord) -> bool:
    text = f"{artifact.kind} {artifact.path}".lower()
    return any(word in text for word in _ENVIRONMENT_WORDS)


def _artifact_is_test_configuration(artifact: ArtifactRecord) -> bool:
    """Recognize explicit fixture/config artifacts without guessing source use."""
    text = f"{artifact.kind} {artifact.path}".lower()
    return any(word in text for word in ("fixture", "pytest", "test_config", "test-config"))


def _recorded_assumption(edge: DependencyEdge, family: str) -> bool:
    metadata = edge.metadata
    keys = (f"assumes_{family}", f"assumed_{family}", f"{family}_assumptions")
    return any(bool(metadata.get(key)) for key in keys) or (
        family == "effects" and bool(metadata.get("assumes_pure") or metadata.get("security_assumption"))
    )


def _changed_identities(old: SymbolRecord | None, new: SymbolRecord | None) -> tuple[str | None, str | None]:
    return (None if old is None else old.version_cid, None if new is None else new.version_cid)


def calculate_invalidation(
    previous_state: RepositoryState,
    current_state: RepositoryState,
    delta: RepositoryStateDelta,
    *,
    max_obligations: int = MAX_INVALIDATION_OBLIGATIONS,
) -> InvalidationPlan:
    """Return a deterministic, deduplicated and bounded invalidation plan.

    The supplied delta must be the projection delta for these exact state CIDs.
    ``max_obligations`` prevents a pathological graph from turning a local
    change into unbounded work; truncation is intentionally fail-closed.
    """
    if not isinstance(previous_state, RepositoryState) or not isinstance(current_state, RepositoryState):
        raise InvalidationError("previous_state and current_state must be RepositoryStates")
    if not isinstance(delta, RepositoryStateDelta):
        raise InvalidationError("delta must be a RepositoryStateDelta")
    if previous_state.repository_id != current_state.repository_id:
        raise InvalidationError("repository states must have the same repository_id")
    if (delta.previous_state_cid, delta.current_state_cid) != (previous_state.state_cid, current_state.state_cid):
        raise InvalidationError("delta state CIDs must match the supplied states")
    if type(max_obligations) is not int or not 1 <= max_obligations <= MAX_INVALIDATION_OBLIGATIONS:
        raise InvalidationError(f"max_obligations must be between 1 and {MAX_INVALIDATION_OBLIGATIONS}")

    old_symbols = {item.stable_id: item for item in previous_state.symbols}
    new_symbols = {item.stable_id: item for item in current_state.symbols}
    old_artifacts = {item.artifact_id: item for item in previous_state.artifacts}
    new_artifacts = {item.artifact_id: item for item in current_state.artifacts}
    old_edges = tuple(previous_state.edges)
    new_edges = tuple(current_state.edges)
    incoming: dict[str, list[DependencyEdge]] = {}
    adjacent: dict[str, list[DependencyEdge]] = {}
    for edge in (*old_edges, *new_edges):
        incoming.setdefault(edge.target_id, []).append(edge)
        adjacent.setdefault(edge.source_id, []).append(edge)
        adjacent.setdefault(edge.target_id, []).append(edge)

    obligations: dict[str, InvalidationObligation] = {}

    def emit(subject_id: str, reason: InvalidationReason, remediation: str, confidence: str, old: str | None, new: str | None, edges: Iterable[DependencyEdge] = (), details: dict[str, object] | None = None) -> None:
        edge_items = tuple(sorted({edge.edge_id: edge for edge in edges}.values(), key=lambda edge: edge.edge_id))
        if edge_items:
            confidence = _least_confident(confidence, *(edge.confidence for edge in edge_items))
        item = InvalidationObligation(subject_id, reason.value, remediation, confidence, old, new, tuple(edge.edge_id for edge in edge_items), details or {})
        obligations[item.obligation_id] = item

    def emit_tests(changed_id: str, old: str | None, new: str | None, edges: Iterable[DependencyEdge]) -> None:
        for edge in edges:
            candidate = edge.source_id if edge.target_id == changed_id else edge.target_id
            if edge.relation in _TEST_RELATIONS or _is_test(old_symbols.get(candidate) or new_symbols.get(candidate)):
                emit(candidate, InvalidationReason.STALE_TEST_RECEIPT, "rerun_test", edge.confidence, old, new, (edge,), {"trigger": changed_id, "rule": InvalidationRule.FIXTURE_CONFIG.value})

    def emit_opaque(subject_id: str, old: str | None, new: str | None, records: Iterable[SymbolRecord | ArtifactRecord | DependencyEdge]) -> None:
        opaque = tuple(record for record in records if _is_opaque(record))
        if opaque:
            edges = tuple(record for record in opaque if isinstance(record, DependencyEdge))
            emit(subject_id, InvalidationReason.RAW_SOURCE_REQUIRED, "retrieve_raw_source", "opaque", old, new, edges, {"rule": InvalidationRule.OPAQUE.value})

    changed = tuple(sorted(set(delta.modified_symbol_ids) | set(delta.added_symbol_ids) | set(delta.deleted_symbol_ids)))
    for symbol_id in changed:
        old, new = old_symbols.get(symbol_id), new_symbols.get(symbol_id)
        old_identity, new_identity = _changed_identities(old, new)
        symbol_edges = tuple(adjacent.get(symbol_id, ()))
        confidence = _least_confident(*(item.confidence for item in (old, new) if item is not None))
        if old is None:
            emit(symbol_id, InvalidationReason.NEW_CAPSULE, "build_capsule", confidence, old_identity, new_identity, details={"rule": InvalidationRule.BODY.value})
            emit(symbol_id, InvalidationReason.PROOF_RERUN, "rerun_proof", confidence, old_identity, new_identity, details={"rule": InvalidationRule.BODY.value})
            emit_tests(symbol_id, old_identity, new_identity, symbol_edges)
            emit_opaque(symbol_id, old_identity, new_identity, (new, *symbol_edges))
            continue
        if new is None:
            emit(symbol_id, InvalidationReason.DELETED_SYMBOL_DEPENDENCY, "retire_capsule", confidence, old_identity, new_identity, details={"rule": InvalidationRule.DELETION.value})
            emit(symbol_id, InvalidationReason.PROOF_RERUN, "rerun_proof", confidence, old_identity, new_identity, details={"rule": InvalidationRule.DELETION.value})
            for edge in incoming.get(symbol_id, ()):
                emit(edge.source_id, InvalidationReason.DELETED_SYMBOL_DEPENDENCY, "review_dependent", edge.confidence, old_identity, new_identity, (edge,), {"trigger": symbol_id, "rule": InvalidationRule.DELETION.value})
            emit_tests(symbol_id, old_identity, new_identity, symbol_edges)
            emit_opaque(symbol_id, old_identity, new_identity, (old, *symbol_edges))
            continue

        facets = classify_symbol_change(old, new, previous_edges=old_edges, current_edges=new_edges)
        if not facets:
            continue
        emit(symbol_id, InvalidationReason.NEW_CAPSULE, "build_capsule", confidence, old_identity, new_identity, details={"facets": list(facets)})
        emit(symbol_id, InvalidationReason.PROOF_RERUN, "rerun_proof", confidence, old_identity, new_identity, details={"facets": list(facets)})
        emit_tests(symbol_id, old_identity, new_identity, symbol_edges)
        if "signature" in facets:
            for edge in incoming.get(symbol_id, ()):
                if edge.relation == RelationType.CALLS.value:
                    emit(edge.source_id, InvalidationReason.CALLER_SIGNATURE_MISMATCH, "review_call_site", edge.confidence, old_identity, new_identity, (edge,), {"trigger": symbol_id, "rule": InvalidationRule.SIGNATURE.value})
            for edge in symbol_edges:
                if edge.relation in _ADAPTER_RELATIONS:
                    subject = edge.source_id if edge.target_id == symbol_id else edge.target_id
                    emit(subject, InvalidationReason.OBSOLETE_SCHEMA_ADAPTER, "review_adapter", edge.confidence, old_identity, new_identity, (edge,), {"trigger": symbol_id, "rule": InvalidationRule.SIGNATURE.value})
        if "effects" in facets:
            emit(symbol_id, InvalidationReason.PURITY_SECURITY_REVIEW, "review_security_purity", confidence, old_identity, new_identity, details={"rule": InvalidationRule.EFFECTS.value})
            for edge in incoming.get(symbol_id, ()):
                if edge.relation == RelationType.CALLS.value and _recorded_assumption(edge, "effects"):
                    emit(edge.source_id, InvalidationReason.EFFECT_ASSUMPTION_STALE, "review_assumption", edge.confidence, old_identity, new_identity, (edge,), {"trigger": symbol_id, "rule": InvalidationRule.EFFECTS.value})
        if "exceptions" in facets:
            for edge in incoming.get(symbol_id, ()):
                if edge.relation == RelationType.CALLS.value and _recorded_assumption(edge, "exceptions"):
                    emit(edge.source_id, InvalidationReason.EXCEPTION_RECOVERY_STALE, "review_recovery", edge.confidence, old_identity, new_identity, (edge,), {"trigger": symbol_id, "rule": InvalidationRule.EXCEPTIONS.value})
            for edge in symbol_edges:
                if edge.relation == RelationType.CATCHES.value:
                    subject = edge.source_id if edge.target_id == symbol_id else edge.target_id
                    emit(subject, InvalidationReason.EXCEPTION_RECOVERY_STALE, "review_recovery", edge.confidence, old_identity, new_identity, (edge,), {"trigger": symbol_id, "rule": InvalidationRule.EXCEPTIONS.value})
        if "schema" in facets or new.kind in {SymbolKind.DATACLASS.value, SymbolKind.TYPED_DICT.value, SymbolKind.ENUM.value}:
            for edge in symbol_edges:
                if edge.relation in _ADAPTER_RELATIONS:
                    subject = edge.source_id if edge.target_id == symbol_id else edge.target_id
                    emit(subject, InvalidationReason.OBSOLETE_SCHEMA_ADAPTER, "review_adapter", edge.confidence, old_identity, new_identity, (edge,), {"trigger": symbol_id, "rule": InvalidationRule.SCHEMA.value})
        emit_opaque(symbol_id, old_identity, new_identity, (old, new, *symbol_edges))

    for artifact_id in sorted(set(delta.added_artifact_ids) | set(delta.deleted_artifact_ids) | set(delta.modified_artifact_ids)):
        old, new = old_artifacts.get(artifact_id), new_artifacts.get(artifact_id)
        artifact = new or old
        if artifact is None:
            continue
        old_identity, new_identity = (None if old is None else old.source_cid, None if new is None else new.source_cid)
        edges = tuple(adjacent.get(artifact_id, ()))
        if _artifact_is_environment(artifact):
            if not edges:
                emit(artifact_id, InvalidationReason.ENVIRONMENT_RECEIPT_STALE, "refresh_environment_receipt", artifact.confidence, old_identity, new_identity, details={"rule": InvalidationRule.ENVIRONMENT.value})
            for edge in edges:
                emit(edge.source_id if edge.target_id == artifact_id else edge.target_id, InvalidationReason.ENVIRONMENT_RECEIPT_STALE, "refresh_environment_receipt", edge.confidence, old_identity, new_identity, (edge,), {"trigger": artifact_id, "rule": InvalidationRule.ENVIRONMENT.value})
        if _artifact_is_test_configuration(artifact):
            if not edges:
                emit(artifact_id, InvalidationReason.STALE_TEST_RECEIPT, "rerun_test", artifact.confidence, old_identity, new_identity, details={"rule": InvalidationRule.FIXTURE_CONFIG.value})
            for edge in edges:
                subject = edge.source_id if edge.target_id == artifact_id else edge.target_id
                if edge.relation in _TEST_RELATIONS or _is_test(old_symbols.get(subject) or new_symbols.get(subject)):
                    emit(subject, InvalidationReason.STALE_TEST_RECEIPT, "rerun_test", edge.confidence, old_identity, new_identity, (edge,), {"trigger": artifact_id, "rule": InvalidationRule.FIXTURE_CONFIG.value})
        emit_opaque(artifact_id, old_identity, new_identity, (artifact, *edges))

    ordered = tuple(sorted(obligations.values(), key=lambda item: item.obligation_id))
    if len(ordered) > max_obligations:
        raise InvalidationError(f"invalidation plan exceeds max_obligations={max_obligations}")
    return InvalidationPlan(previous_state.state_cid, current_state.state_cid, ordered)


__all__ = [
    "MAX_INVALIDATION_OBLIGATIONS",
    "InvalidationError",
    "InvalidationReason",
    "InvalidationRule",
    "calculate_invalidation",
]
