"""Bounded, evidence-backed invalidation obligations for semantic deltas.

The engine deliberately reports work which must be reconsidered; it never
rewrites a caller, test, schema adapter, or proof.  Every dependent obligation
is attached to the edge which justified it (when an edge exists), making a
plan independently auditable and stable across equivalent input ordering.

Any supplied delta is recomputed from the two states and rejected when it does
not match.  Proof reruns require a recorded ``proof_depends_on`` edge.  Schema
rules fire only on schema facets, not ordinary annotations.
"""

from __future__ import annotations

from enum import Enum
from typing import Final, Iterable, Mapping

from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import (
    classify_symbol_change,
    diff_repository_states,
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
    SourceSpan,
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
    EDGE = "edge"
    PROOF = "proof"


MAX_INVALIDATION_OBLIGATIONS: Final[int] = 1_000
_CONFIDENCE_RANK: Final[dict[str, int]] = {"exact": 0, "conservative": 1, "heuristic": 2, "opaque": 3}
_ADAPTER_RELATIONS: Final[frozenset[str]] = frozenset({"serializes", "deserializes", "validates", "implements"})
_TEST_RELATIONS: Final[frozenset[str]] = frozenset({"tested_by", "uses_fixture", "configured_by"})
_ENVIRONMENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "dependency-lock",
        "dependency_lock",
        "lockfile",
        "environment",
        "requirements",
    }
)
_TEST_CONFIG_KINDS: Final[frozenset[str]] = frozenset(
    {
        "pytest_config",
        "pytest-config",
        "conftest",
        "fixture",
        "test_config",
        "test-config",
    }
)
_SCHEMA_KINDS: Final[frozenset[str]] = frozenset(
    {
        SymbolKind.DATACLASS.value,
        SymbolKind.TYPED_DICT.value,
        SymbolKind.ENUM.value,
    }
)


def _least_confident(*values: str) -> str:
    return max(values, key=lambda value: _CONFIDENCE_RANK[value])


def _is_opaque(record: SymbolRecord | ArtifactRecord | DependencyEdge) -> bool:
    """Opaque confidence only — unresolved is a different evidence class."""
    return record.confidence == AnalysisConfidence.OPAQUE.value


def _is_test(symbol: SymbolRecord | None) -> bool:
    return symbol is not None and symbol.kind == SymbolKind.TEST.value


def _artifact_is_environment(artifact: ArtifactRecord) -> bool:
    """Recognize lock/environment artifacts by recorded kind, not path words."""
    kind = artifact.kind.lower().replace("_", "-")
    return kind in {item.replace("_", "-") for item in _ENVIRONMENT_KINDS} or kind.endswith("-lock")


def _artifact_is_test_configuration(artifact: ArtifactRecord) -> bool:
    """Recognize explicit fixture/config artifacts by recorded kind/path role."""
    kind = artifact.kind.lower().replace("_", "-")
    if kind in {item.replace("_", "-") for item in _TEST_CONFIG_KINDS}:
        return True
    path = artifact.path.lower()
    name = path.rsplit("/", 1)[-1]
    return name in {"conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"}


def _recorded_assumption(edge: DependencyEdge, family: str) -> bool:
    metadata = edge.metadata
    keys = (f"assumes_{family}", f"assumed_{family}", f"{family}_assumptions")
    return any(bool(metadata.get(key)) for key in keys) or (
        family == "effects" and bool(metadata.get("assumes_pure") or metadata.get("security_assumption"))
    )


def _changed_identities(old: SymbolRecord | None, new: SymbolRecord | None) -> tuple[str | None, str | None]:
    return (None if old is None else old.version_cid, None if new is None else new.version_cid)


def _caller_has_catches(caller_id: str, *edge_groups: Iterable[DependencyEdge]) -> bool:
    for edges in edge_groups:
        for edge in edges:
            if edge.source_id == caller_id and edge.relation == RelationType.CATCHES.value:
                return True
    return False


def _annotation_references_schema(symbol: SymbolRecord, schema: SymbolRecord) -> bool:
    """True when a durable annotation names the schema type."""
    short = schema.qualified_name.rsplit(".", 1)[-1]
    qualified = schema.qualified_name
    values: list[str] = []
    for value in dict(symbol.annotations).values():
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, Mapping):
            continue
    # Signature parameters also carry annotations as durable projections.
    parameters = dict(symbol.signature).get("parameters")
    if isinstance(parameters, (list, tuple)):
        for item in parameters:
            if isinstance(item, Mapping):
                annotation = item.get("annotation")
                if isinstance(annotation, str):
                    values.append(annotation)
    return_annotation = dict(symbol.signature).get("return")
    if isinstance(return_annotation, str):
        values.append(return_annotation)
    for value in values:
        if value == short or value == qualified or value.endswith("." + short):
            return True
    return False


def _raw_source_details(
    records: Iterable[SymbolRecord | ArtifactRecord | DependencyEdge],
    *,
    symbols_by_id: Mapping[str, SymbolRecord] | None = None,
    artifacts_by_id: Mapping[str, ArtifactRecord] | None = None,
) -> dict[str, object]:
    """Identify retrievable raw source for opaque evidence, when present."""
    details: dict[str, object] = {"rule": InvalidationRule.OPAQUE.value}
    symbols_by_id = symbols_by_id or {}
    artifacts_by_id = artifacts_by_id or {}

    def _attach_symbol(symbol: SymbolRecord) -> None:
        details["module_path"] = symbol.module_path
        if symbol.source_cid is not None:
            details["source_cid"] = symbol.source_cid
        if isinstance(symbol.span, SourceSpan):
            details["span"] = symbol.span.to_dict()

    # Prefer opaque symbols/artifacts (path/CID/span) over bare edges.
    for record in records:
        if isinstance(record, SymbolRecord) and _is_opaque(record):
            _attach_symbol(record)
            details["subject_kind"] = "symbol"
            return details
        if isinstance(record, ArtifactRecord) and _is_opaque(record):
            details["path"] = record.path
            if record.source_cid is not None:
                details["source_cid"] = record.source_cid
            details["subject_kind"] = "artifact"
            return details
    for record in records:
        if not isinstance(record, DependencyEdge) or not _is_opaque(record):
            continue
        details["edge_id"] = record.edge_id
        details["subject_kind"] = "edge"
        if isinstance(record.span, SourceSpan):
            details["span"] = record.span.to_dict()
        target = record.metadata.get("unresolved_target") or record.target_id
        if isinstance(target, str) and target:
            details["opaque_target"] = target
        # Resolve endpoints to retrievable repository path/source when known.
        for endpoint in (record.source_id, record.target_id):
            symbol = symbols_by_id.get(endpoint)
            if symbol is not None:
                _attach_symbol(symbol)
                break
            artifact = artifacts_by_id.get(endpoint)
            if artifact is not None:
                details["path"] = artifact.path
                if artifact.source_cid is not None:
                    details["source_cid"] = artifact.source_cid
                break
        return details
    return details


def calculate_invalidation(
    previous_state: RepositoryState,
    current_state: RepositoryState,
    delta: RepositoryStateDelta,
    *,
    max_obligations: int = MAX_INVALIDATION_OBLIGATIONS,
) -> InvalidationPlan:
    """Return a deterministic, deduplicated and bounded invalidation plan.

    The supplied delta must be the exact recomputed projection for these state
    CIDs.  ``max_obligations`` prevents a pathological graph from turning a
    local change into unbounded work; truncation is intentionally fail-closed.
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

    # Reject fabricated deltas that only forge matching state CIDs.
    expected = diff_repository_states(previous_state, current_state)
    if delta.delta_cid != expected.delta_cid:
        raise InvalidationError("delta does not match recomputed state projection")

    old_symbols = {item.stable_id: item for item in previous_state.symbols}
    new_symbols = {item.stable_id: item for item in current_state.symbols}
    old_artifacts = {item.artifact_id: item for item in previous_state.artifacts}
    new_artifacts = {item.artifact_id: item for item in current_state.artifacts}
    old_edges = tuple(previous_state.edges)
    new_edges = tuple(current_state.edges)
    edge_by_id = {edge.edge_id: edge for edge in (*old_edges, *new_edges)}
    incoming: dict[str, list[DependencyEdge]] = {}
    adjacent: dict[str, list[DependencyEdge]] = {}
    for edge in (*old_edges, *new_edges):
        incoming.setdefault(edge.target_id, []).append(edge)
        adjacent.setdefault(edge.source_id, []).append(edge)
        adjacent.setdefault(edge.target_id, []).append(edge)

    # Edge-only changes still touch their endpoints even when symbol fields are
    # unchanged, so effects/exceptions/test/proof rules remain actionable.
    edge_touched: set[str] = set()
    for edge_id in set(delta.added_edge_ids) | set(delta.deleted_edge_ids):
        edge = edge_by_id.get(edge_id)
        if edge is None:
            continue
        edge_touched.add(edge.source_id)
        if edge.relation in _TEST_RELATIONS | _ADAPTER_RELATIONS | {
            RelationType.PROOF_DEPENDS_ON.value,
            RelationType.CALLS.value,
            RelationType.INHERITS.value,
        }:
            edge_touched.add(edge.target_id)

    obligations: dict[str, InvalidationObligation] = {}

    def emit(
        subject_id: str,
        reason: InvalidationReason,
        remediation: str,
        confidence: str,
        old: str | None,
        new: str | None,
        edges: Iterable[DependencyEdge] = (),
        details: dict[str, object] | None = None,
    ) -> None:
        edge_items = tuple(sorted({edge.edge_id: edge for edge in edges}.values(), key=lambda edge: edge.edge_id))
        if edge_items:
            confidence = _least_confident(confidence, *(edge.confidence for edge in edge_items))
        item = InvalidationObligation(
            subject_id,
            reason.value,
            remediation,
            confidence,
            old,
            new,
            tuple(edge.edge_id for edge in edge_items),
            details or {},
        )
        obligations[item.obligation_id] = item

    def emit_tests(changed_id: str, old: str | None, new: str | None, edges: Iterable[DependencyEdge]) -> None:
        for edge in edges:
            if edge.relation not in _TEST_RELATIONS and not (
                edge.relation == RelationType.CALLS.value
                and (
                    _is_test(old_symbols.get(edge.source_id) or new_symbols.get(edge.source_id))
                )
            ):
                # Prefer typed test relations; CALLS from a test still stale the test.
                if edge.relation != RelationType.CALLS.value:
                    continue
            if edge.relation == RelationType.CALLS.value:
                candidate = edge.source_id
                if not _is_test(old_symbols.get(candidate) or new_symbols.get(candidate)):
                    continue
            else:
                candidate = edge.source_id if edge.target_id == changed_id else edge.target_id
                if edge.relation == RelationType.TESTED_BY.value and edge.source_id == changed_id:
                    candidate = edge.target_id
                elif edge.relation in {RelationType.USES_FIXTURE.value, RelationType.CONFIGURED_BY.value}:
                    # Source depends on fixture/config target.
                    if edge.target_id == changed_id:
                        candidate = edge.source_id
                    elif edge.source_id == changed_id:
                        candidate = edge.source_id
                    else:
                        continue
            emit(
                candidate,
                InvalidationReason.STALE_TEST_RECEIPT,
                "rerun_test",
                edge.confidence,
                old,
                new,
                (edge,),
                {"trigger": changed_id, "rule": InvalidationRule.FIXTURE_CONFIG.value},
            )

    def emit_proof_reruns(changed_id: str, old: str | None, new: str | None, edges: Iterable[DependencyEdge]) -> None:
        """Rerun only proofs recorded via ``proof_depends_on`` edges."""
        for edge in edges:
            if edge.relation != RelationType.PROOF_DEPENDS_ON.value:
                continue
            # proof --proof_depends_on--> changed symbol  ⇒  rerun the proof (source)
            if edge.target_id == changed_id:
                subject = edge.source_id
            elif edge.source_id == changed_id:
                # The proof node itself changed; rerun it.
                subject = edge.source_id
            else:
                continue
            emit(
                subject,
                InvalidationReason.PROOF_RERUN,
                "rerun_proof",
                edge.confidence,
                old,
                new,
                (edge,),
                {"trigger": changed_id, "rule": InvalidationRule.PROOF.value},
            )

    def emit_opaque(
        subject_id: str,
        old: str | None,
        new: str | None,
        records: Iterable[SymbolRecord | ArtifactRecord | DependencyEdge],
    ) -> None:
        opaque = tuple(record for record in records if _is_opaque(record))
        if not opaque:
            return
        edges = tuple(record for record in opaque if isinstance(record, DependencyEdge))
        all_symbols = {**old_symbols, **new_symbols}
        all_artifacts = {**old_artifacts, **new_artifacts}
        emit(
            subject_id,
            InvalidationReason.RAW_SOURCE_REQUIRED,
            "retrieve_raw_source",
            "opaque",
            old,
            new,
            edges,
            _raw_source_details(opaque, symbols_by_id=all_symbols, artifacts_by_id=all_artifacts),
        )

    def emit_schema_adapters(
        schema_id: str,
        schema: SymbolRecord,
        old: str | None,
        new: str | None,
        symbol_edges: Iterable[DependencyEdge],
    ) -> None:
        seen: set[str] = set()
        for edge in symbol_edges:
            if edge.relation in _ADAPTER_RELATIONS:
                subject = edge.source_id if edge.target_id == schema_id else edge.target_id
                if subject == schema_id or subject in seen:
                    continue
                seen.add(subject)
                emit(
                    subject,
                    InvalidationReason.OBSOLETE_SCHEMA_ADAPTER,
                    "review_adapter",
                    edge.confidence,
                    old,
                    new,
                    (edge,),
                    {"trigger": schema_id, "rule": InvalidationRule.SCHEMA.value, "basis": edge.relation},
                )
            elif edge.relation == RelationType.CALLS.value and edge.target_id == schema_id:
                if edge.source_id in seen:
                    continue
                seen.add(edge.source_id)
                emit(
                    edge.source_id,
                    InvalidationReason.OBSOLETE_SCHEMA_ADAPTER,
                    "review_adapter",
                    edge.confidence,
                    old,
                    new,
                    (edge,),
                    {"trigger": schema_id, "rule": InvalidationRule.SCHEMA.value, "basis": "constructor_call"},
                )
        # Durable annotation references (no hand-authored serializes edge required).
        for other in (*old_symbols.values(), *new_symbols.values()):
            if other.stable_id == schema_id or other.stable_id in seen:
                continue
            if _annotation_references_schema(other, schema):
                seen.add(other.stable_id)
                emit(
                    other.stable_id,
                    InvalidationReason.OBSOLETE_SCHEMA_ADAPTER,
                    "review_adapter",
                    other.confidence,
                    old,
                    new,
                    (),
                    {
                        "trigger": schema_id,
                        "rule": InvalidationRule.SCHEMA.value,
                        "basis": "annotation_reference",
                    },
                )

    changed = tuple(
        sorted(
            set(delta.modified_symbol_ids)
            | set(delta.added_symbol_ids)
            | set(delta.deleted_symbol_ids)
            | edge_touched
        )
    )
    for symbol_id in changed:
        old, new = old_symbols.get(symbol_id), new_symbols.get(symbol_id)
        # Pure edge endpoints that are not symbols (artifacts, lexical targets)
        # are handled in the artifact loop or skipped here.
        if old is None and new is None:
            continue
        old_identity, new_identity = _changed_identities(old, new)
        symbol_edges = tuple(adjacent.get(symbol_id, ()))
        confidence = _least_confident(*(item.confidence for item in (old, new) if item is not None))
        if old is None:
            emit(
                symbol_id,
                InvalidationReason.NEW_CAPSULE,
                "build_capsule",
                confidence,
                old_identity,
                new_identity,
                details={"rule": InvalidationRule.BODY.value},
            )
            emit_proof_reruns(symbol_id, old_identity, new_identity, symbol_edges)
            emit_tests(symbol_id, old_identity, new_identity, symbol_edges)
            emit_opaque(symbol_id, old_identity, new_identity, (new, *symbol_edges))
            continue
        if new is None:
            emit(
                symbol_id,
                InvalidationReason.DELETED_SYMBOL_DEPENDENCY,
                "retire_capsule",
                confidence,
                old_identity,
                new_identity,
                details={"rule": InvalidationRule.DELETION.value},
            )
            emit_proof_reruns(symbol_id, old_identity, new_identity, symbol_edges)
            for edge in incoming.get(symbol_id, ()):
                emit(
                    edge.source_id,
                    InvalidationReason.DELETED_SYMBOL_DEPENDENCY,
                    "review_dependent",
                    edge.confidence,
                    old_identity,
                    new_identity,
                    (edge,),
                    {"trigger": symbol_id, "rule": InvalidationRule.DELETION.value},
                )
            emit_tests(symbol_id, old_identity, new_identity, symbol_edges)
            emit_opaque(symbol_id, old_identity, new_identity, (old, *symbol_edges))
            continue

        facets = classify_symbol_change(old, new, previous_edges=old_edges, current_edges=new_edges)
        edge_only = (
            symbol_id in edge_touched
            and symbol_id not in delta.modified_symbol_ids
            and symbol_id not in delta.added_symbol_ids
            and symbol_id not in delta.deleted_symbol_ids
        )
        if not facets and not edge_only:
            continue
        if facets:
            emit(
                symbol_id,
                InvalidationReason.NEW_CAPSULE,
                "build_capsule",
                confidence,
                old_identity,
                new_identity,
                details={"facets": list(facets), "rule": InvalidationRule.EDGE.value if edge_only else facets[0]},
            )
        emit_proof_reruns(symbol_id, old_identity, new_identity, symbol_edges)
        emit_tests(symbol_id, old_identity, new_identity, symbol_edges)

        if "signature" in facets:
            for edge in incoming.get(symbol_id, ()):
                if edge.relation == RelationType.CALLS.value:
                    emit(
                        edge.source_id,
                        InvalidationReason.CALLER_SIGNATURE_MISMATCH,
                        "review_call_site",
                        edge.confidence,
                        old_identity,
                        new_identity,
                        (edge,),
                        {"trigger": symbol_id, "rule": InvalidationRule.SIGNATURE.value},
                    )
                elif edge.relation in {RelationType.INHERITS.value, RelationType.IMPLEMENTS.value}:
                    emit(
                        edge.source_id,
                        InvalidationReason.CALLER_SIGNATURE_MISMATCH,
                        "review_call_site",
                        edge.confidence,
                        old_identity,
                        new_identity,
                        (edge,),
                        {"trigger": symbol_id, "rule": InvalidationRule.SIGNATURE.value, "basis": edge.relation},
                    )
            for edge in symbol_edges:
                if edge.relation in _ADAPTER_RELATIONS:
                    subject = edge.source_id if edge.target_id == symbol_id else edge.target_id
                    emit(
                        subject,
                        InvalidationReason.OBSOLETE_SCHEMA_ADAPTER,
                        "review_adapter",
                        edge.confidence,
                        old_identity,
                        new_identity,
                        (edge,),
                        {"trigger": symbol_id, "rule": InvalidationRule.SIGNATURE.value},
                    )

        if "effects" in facets:
            emit(
                symbol_id,
                InvalidationReason.PURITY_SECURITY_REVIEW,
                "review_security_purity",
                confidence,
                old_identity,
                new_identity,
                details={"rule": InvalidationRule.EFFECTS.value},
            )
            for edge in incoming.get(symbol_id, ()):
                if edge.relation == RelationType.CALLS.value and _recorded_assumption(edge, "effects"):
                    emit(
                        edge.source_id,
                        InvalidationReason.EFFECT_ASSUMPTION_STALE,
                        "review_assumption",
                        edge.confidence,
                        old_identity,
                        new_identity,
                        (edge,),
                        {"trigger": symbol_id, "rule": InvalidationRule.EFFECTS.value},
                    )

        if "exceptions" in facets:
            for edge in incoming.get(symbol_id, ()):
                if edge.relation != RelationType.CALLS.value:
                    continue
                if _recorded_assumption(edge, "exceptions") or _caller_has_catches(
                    edge.source_id, old_edges, new_edges
                ):
                    emit(
                        edge.source_id,
                        InvalidationReason.EXCEPTION_RECOVERY_STALE,
                        "review_recovery",
                        edge.confidence,
                        old_identity,
                        new_identity,
                        (edge,),
                        {"trigger": symbol_id, "rule": InvalidationRule.EXCEPTIONS.value},
                    )
            for edge in symbol_edges:
                if edge.relation == RelationType.CATCHES.value:
                    subject = edge.source_id if edge.target_id == symbol_id else edge.target_id
                    emit(
                        subject,
                        InvalidationReason.EXCEPTION_RECOVERY_STALE,
                        "review_recovery",
                        edge.confidence,
                        old_identity,
                        new_identity,
                        (edge,),
                        {"trigger": symbol_id, "rule": InvalidationRule.EXCEPTIONS.value},
                    )

        # Schema rules require a schema facet — never "any dataclass change".
        if "schema" in facets and new.kind in _SCHEMA_KINDS:
            emit_schema_adapters(symbol_id, new, old_identity, new_identity, symbol_edges)

        emit_opaque(symbol_id, old_identity, new_identity, (old, new, *symbol_edges))

    for artifact_id in sorted(
        set(delta.added_artifact_ids) | set(delta.deleted_artifact_ids) | set(delta.modified_artifact_ids)
    ):
        old, new = old_artifacts.get(artifact_id), new_artifacts.get(artifact_id)
        artifact = new or old
        if artifact is None:
            continue
        old_identity = None if old is None else old.source_cid
        new_identity = None if new is None else new.source_cid
        edges = tuple(adjacent.get(artifact_id, ()))
        if _artifact_is_environment(artifact):
            if not edges:
                emit(
                    artifact_id,
                    InvalidationReason.ENVIRONMENT_RECEIPT_STALE,
                    "refresh_environment_receipt",
                    artifact.confidence,
                    old_identity,
                    new_identity,
                    details={"rule": InvalidationRule.ENVIRONMENT.value, "path": artifact.path},
                )
            for edge in edges:
                subject = edge.source_id if edge.target_id == artifact_id else edge.target_id
                emit(
                    subject,
                    InvalidationReason.ENVIRONMENT_RECEIPT_STALE,
                    "refresh_environment_receipt",
                    edge.confidence,
                    old_identity,
                    new_identity,
                    (edge,),
                    {"trigger": artifact_id, "rule": InvalidationRule.ENVIRONMENT.value, "path": artifact.path},
                )
        if _artifact_is_test_configuration(artifact):
            if not edges:
                emit(
                    artifact_id,
                    InvalidationReason.STALE_TEST_RECEIPT,
                    "rerun_test",
                    artifact.confidence,
                    old_identity,
                    new_identity,
                    details={"rule": InvalidationRule.FIXTURE_CONFIG.value, "path": artifact.path},
                )
            for edge in edges:
                subject = edge.source_id if edge.target_id == artifact_id else edge.target_id
                if edge.relation in _TEST_RELATIONS or _is_test(
                    old_symbols.get(subject) or new_symbols.get(subject)
                ):
                    emit(
                        subject,
                        InvalidationReason.STALE_TEST_RECEIPT,
                        "rerun_test",
                        edge.confidence,
                        old_identity,
                        new_identity,
                        (edge,),
                        {"trigger": artifact_id, "rule": InvalidationRule.FIXTURE_CONFIG.value},
                    )
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
