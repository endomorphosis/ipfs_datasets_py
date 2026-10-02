"""Bounded, evidence-backed invalidation obligations for semantic deltas.

The engine deliberately reports work which must be reconsidered; it never
rewrites a caller, test, schema adapter, or proof.  Every dependent obligation
is attached to the edge which justified it, making a plan independently
auditable and stable across equivalent input ordering.

Supplied deltas are recomputed from the two states and rejected when they do
not match, even if the state CIDs agree.  Proof reruns are emitted only when a
stored ``proof_depends_on`` edge exists.
"""

from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath
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


MAX_INVALIDATION_OBLIGATIONS: Final[int] = 1_000
_CONFIDENCE_RANK: Final[dict[str, int]] = {"exact": 0, "conservative": 1, "heuristic": 2, "opaque": 3}
_ADAPTER_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        RelationType.SERIALIZES.value,
        RelationType.DESERIALIZES.value,
        RelationType.VALIDATES.value,
        RelationType.IMPLEMENTS.value,
    }
)
_TEST_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        RelationType.TESTED_BY.value,
        RelationType.USES_FIXTURE.value,
        RelationType.CONFIGURED_BY.value,
    }
)
_PROOF_RELATION: Final[str] = RelationType.PROOF_DEPENDS_ON.value
_CALLS_RELATION: Final[str] = RelationType.CALLS.value
_CATCHES_RELATION: Final[str] = RelationType.CATCHES.value

# Environment/lock recognition uses closed kinds and exact basenames, never
# free-form path substring matching.
_ENVIRONMENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "dependency_lock",
        "dependency-lock",
        "lockfile",
        "lock_file",
        "requirements",
        "environment",
        "environment_lock",
    }
)
_ENVIRONMENT_BASENAMES: Final[frozenset[str]] = frozenset(
    {
        "poetry.lock",
        "pipfile.lock",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-test.txt",
        "uv.lock",
        "pdm.lock",
        "cargo.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "composer.lock",
        "gemfile.lock",
        "go.sum",
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
_TEST_CONFIG_BASENAMES: Final[frozenset[str]] = frozenset(
    {
        "pytest.ini",
        "pyproject.toml",
        "tox.ini",
        "setup.cfg",
        "conftest.py",
    }
)


def _least_confident(*values: str) -> str:
    return max(values, key=lambda value: _CONFIDENCE_RANK[value])


def _is_opaque(record: SymbolRecord | ArtifactRecord | DependencyEdge) -> bool:
    """Opaque confidence is the only durable raw-source trigger.

    Unresolved relation targets remain explicit graph facts; they do not by
    themselves require retrieving raw source for an otherwise exact symbol.
    """
    return record.confidence == AnalysisConfidence.OPAQUE.value


def _is_test(symbol: SymbolRecord | None) -> bool:
    return symbol is not None and symbol.kind == SymbolKind.TEST.value


def _is_fixture(symbol: SymbolRecord | None) -> bool:
    return symbol is not None and symbol.kind == SymbolKind.FIXTURE.value


def _basename(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).name.lower()


def _artifact_is_environment(artifact: ArtifactRecord) -> bool:
    kind = artifact.kind.lower().replace("_", "-")
    if kind in {item.replace("_", "-") for item in _ENVIRONMENT_KINDS}:
        return True
    metadata = artifact.metadata or {}
    if metadata.get("environment_bound") or metadata.get("dependency_lock"):
        return True
    return _basename(artifact.path) in _ENVIRONMENT_BASENAMES


def _artifact_is_test_configuration(artifact: ArtifactRecord) -> bool:
    """Recognize explicit fixture/config artifacts without guessing source use."""
    kind = artifact.kind.lower().replace("_", "-")
    if kind in {item.replace("_", "-") for item in _TEST_CONFIG_KINDS}:
        return True
    metadata = artifact.metadata or {}
    if metadata.get("pytest_config") or metadata.get("test_configuration"):
        return True
    return _basename(artifact.path) in _TEST_CONFIG_BASENAMES


def _recorded_assumption(edge: DependencyEdge, family: str) -> bool:
    metadata = edge.metadata
    keys = (f"assumes_{family}", f"assumed_{family}", f"{family}_assumptions")
    return any(bool(metadata.get(key)) for key in keys) or (
        family == "effects" and bool(metadata.get("assumes_pure") or metadata.get("security_assumption"))
    )


def _changed_identities(old: SymbolRecord | None, new: SymbolRecord | None) -> tuple[str | None, str | None]:
    return (None if old is None else old.version_cid, None if new is None else new.version_cid)


def _annotation_references_schema(symbol: SymbolRecord, schema: SymbolRecord) -> bool:
    """True when a durable annotation or signature names the schema type."""
    short = schema.qualified_name.rsplit(".", 1)[-1]
    qualified = schema.qualified_name
    values: list[str] = []
    for value in dict(symbol.annotations).values():
        if isinstance(value, str):
            values.append(value)
    parameters = dict(symbol.signature).get("parameters")
    if isinstance(parameters, (list, tuple)):
        for item in parameters:
            if isinstance(item, Mapping):
                annotation = item.get("annotation")
                if isinstance(annotation, str):
                    values.append(annotation)
            elif isinstance(item, str):
                values.append(item)
    return_annotation = dict(symbol.signature).get("return")
    if isinstance(return_annotation, str):
        values.append(return_annotation)
    for value in values:
        if value == short or value == qualified or value.endswith("." + short):
            return True
    return False


def _raw_source_details(
    records: Iterable[SymbolRecord | ArtifactRecord | DependencyEdge],
) -> dict[str, object]:
    """Identify retrievable raw source for opaque obligations."""
    paths: list[str] = []
    source_cids: list[str] = []
    spans: list[dict[str, object]] = []
    for record in records:
        if isinstance(record, SymbolRecord):
            if record.module_path:
                paths.append(record.module_path)
            if record.source_cid:
                source_cids.append(record.source_cid)
            if isinstance(record.span, SourceSpan):
                spans.append(record.span.to_dict())
        elif isinstance(record, ArtifactRecord):
            if record.path:
                paths.append(record.path)
            if record.source_cid:
                source_cids.append(record.source_cid)
        elif isinstance(record, DependencyEdge):
            if isinstance(record.span, SourceSpan):
                spans.append(record.span.to_dict())
            path = record.metadata.get("path") or record.metadata.get("source_path")
            if isinstance(path, str) and path:
                paths.append(path)
            cid = record.metadata.get("source_cid")
            if isinstance(cid, str) and cid:
                source_cids.append(cid)
    details: dict[str, object] = {"rule": InvalidationRule.OPAQUE.value}
    if paths:
        details["source_paths"] = sorted(set(paths))
    if source_cids:
        details["source_cids"] = sorted(set(source_cids))
    if spans:
        details["spans"] = spans
    return details


def _test_subjects_for_edge(
    edge: DependencyEdge,
    changed_id: str,
    old_symbols: dict[str, SymbolRecord],
    new_symbols: dict[str, SymbolRecord],
) -> list[str]:
    """Return only the test/receipt side of a test-related relation.

    Relation directions are fixed:
    - ``tested_by``: production symbol → test
    - ``uses_fixture``: test → fixture
    - ``configured_by``: test → config artifact
    """
    subjects: list[str] = []
    if edge.relation == RelationType.TESTED_BY.value:
        # Invalidate the test (target), never the production subject as a receipt.
        if edge.source_id == changed_id:
            subjects.append(edge.target_id)
    elif edge.relation == RelationType.USES_FIXTURE.value:
        # Fixture/config change invalidates the test (source).
        if edge.target_id == changed_id:
            subjects.append(edge.source_id)
        elif edge.source_id == changed_id and _is_test(old_symbols.get(edge.source_id) or new_symbols.get(edge.source_id)):
            subjects.append(edge.source_id)
    elif edge.relation == RelationType.CONFIGURED_BY.value:
        if edge.target_id == changed_id:
            subjects.append(edge.source_id)
        elif edge.source_id == changed_id and _is_test(old_symbols.get(edge.source_id) or new_symbols.get(edge.source_id)):
            subjects.append(edge.source_id)
    else:
        candidate = edge.source_id if edge.target_id == changed_id else edge.target_id
        if _is_test(old_symbols.get(candidate) or new_symbols.get(candidate)):
            subjects.append(candidate)
    return subjects


def calculate_invalidation(
    previous_state: RepositoryState,
    current_state: RepositoryState,
    delta: RepositoryStateDelta,
    *,
    max_obligations: int = MAX_INVALIDATION_OBLIGATIONS,
) -> InvalidationPlan:
    """Return a deterministic, deduplicated and bounded invalidation plan.

    The supplied delta must be the exact recomputed projection delta for these
    two states.  Matching state CIDs alone are insufficient: a fabricated delta
    is rejected fail-closed.  ``max_obligations`` prevents a pathological graph
    from turning a local change into unbounded work.
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

    expected = diff_repository_states(previous_state, current_state)
    if delta.delta_cid != expected.delta_cid:
        raise InvalidationError("fabricated or incomplete delta rejected; recompute from the two states")

    old_symbols = {item.stable_id: item for item in previous_state.symbols}
    new_symbols = {item.stable_id: item for item in current_state.symbols}
    old_artifacts = {item.artifact_id: item for item in previous_state.artifacts}
    new_artifacts = {item.artifact_id: item for item in current_state.artifacts}
    old_edges = tuple(previous_state.edges)
    new_edges = tuple(current_state.edges)
    edges_by_id: dict[str, DependencyEdge] = {}
    incoming: dict[str, list[DependencyEdge]] = {}
    outgoing: dict[str, list[DependencyEdge]] = {}
    adjacent: dict[str, list[DependencyEdge]] = {}
    for edge in (*old_edges, *new_edges):
        edges_by_id[edge.edge_id] = edge
        incoming.setdefault(edge.target_id, []).append(edge)
        outgoing.setdefault(edge.source_id, []).append(edge)
        adjacent.setdefault(edge.source_id, []).append(edge)
        adjacent.setdefault(edge.target_id, []).append(edge)

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
                _is_test(old_symbols.get(edge.source_id) or new_symbols.get(edge.source_id))
                or _is_test(old_symbols.get(edge.target_id) or new_symbols.get(edge.target_id))
            ):
                continue
            for subject in _test_subjects_for_edge(edge, changed_id, old_symbols, new_symbols):
                emit(
                    subject,
                    InvalidationReason.STALE_TEST_RECEIPT,
                    "rerun_test",
                    edge.confidence,
                    old,
                    new,
                    (edge,),
                    {"trigger": changed_id, "rule": InvalidationRule.FIXTURE_CONFIG.value},
                )

    def emit_proofs(changed_id: str, old: str | None, new: str | None, edges: Iterable[DependencyEdge]) -> None:
        """Rerun only proofs recorded by ``proof_depends_on`` edges.

        Direction: proof (source) depends on subject (target).  When the
        subject changes, each incoming proof edge names the proof to rerun.
        """
        for edge in edges:
            if edge.relation != _PROOF_RELATION:
                continue
            if edge.target_id == changed_id:
                emit(
                    edge.source_id,
                    InvalidationReason.PROOF_RERUN,
                    "rerun_proof",
                    edge.confidence,
                    old,
                    new,
                    (edge,),
                    {"trigger": changed_id, "rule": InvalidationRule.BODY.value},
                )
            elif edge.source_id == changed_id:
                # The proof itself changed; rerun it.
                emit(
                    edge.source_id,
                    InvalidationReason.PROOF_RERUN,
                    "rerun_proof",
                    edge.confidence,
                    old,
                    new,
                    (edge,),
                    {"trigger": changed_id, "rule": InvalidationRule.BODY.value},
                )

    def emit_opaque(
        subject_id: str,
        old: str | None,
        new: str | None,
        records: Iterable[SymbolRecord | ArtifactRecord | DependencyEdge],
    ) -> None:
        opaque = tuple(record for record in records if record is not None and _is_opaque(record))
        if opaque:
            edges = tuple(record for record in opaque if isinstance(record, DependencyEdge))
            emit(
                subject_id,
                InvalidationReason.RAW_SOURCE_REQUIRED,
                "retrieve_raw_source",
                "opaque",
                old,
                new,
                edges,
                _raw_source_details(opaque),
            )

    def emit_adapters(
        changed_id: str,
        old: str | None,
        new: str | None,
        edges: Iterable[DependencyEdge],
        rule: InvalidationRule,
    ) -> None:
        for edge in edges:
            if edge.relation not in _ADAPTER_RELATIONS:
                continue
            subject = edge.source_id if edge.target_id == changed_id else edge.target_id
            if subject == changed_id:
                continue
            emit(
                subject,
                InvalidationReason.OBSOLETE_SCHEMA_ADAPTER,
                "review_adapter",
                edge.confidence,
                old,
                new,
                (edge,),
                {"trigger": changed_id, "rule": rule.value},
            )

    changed = tuple(sorted(set(delta.modified_symbol_ids) | set(delta.added_symbol_ids) | set(delta.deleted_symbol_ids)))
    for symbol_id in changed:
        old, new = old_symbols.get(symbol_id), new_symbols.get(symbol_id)
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
            emit_proofs(symbol_id, old_identity, new_identity, symbol_edges)
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
            emit_proofs(symbol_id, old_identity, new_identity, symbol_edges)
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
        if not facets:
            # Edge-adjacent proof/test maintenance still applies when the
            # symbol is listed as modified only through non-facet projection.
            emit_proofs(symbol_id, old_identity, new_identity, symbol_edges)
            emit_tests(symbol_id, old_identity, new_identity, symbol_edges)
            emit_opaque(symbol_id, old_identity, new_identity, (old, new, *symbol_edges))
            continue

        emit(
            symbol_id,
            InvalidationReason.NEW_CAPSULE,
            "build_capsule",
            confidence,
            old_identity,
            new_identity,
            details={"facets": list(facets)},
        )
        emit_proofs(symbol_id, old_identity, new_identity, symbol_edges)
        emit_tests(symbol_id, old_identity, new_identity, symbol_edges)

        if "signature" in facets:
            for edge in incoming.get(symbol_id, ()):
                if edge.relation == _CALLS_RELATION:
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
            emit_adapters(symbol_id, old_identity, new_identity, symbol_edges, InvalidationRule.SIGNATURE)

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
                if edge.relation == _CALLS_RELATION and _recorded_assumption(edge, "effects"):
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
                if edge.relation != _CALLS_RELATION:
                    continue
                caller_id = edge.source_id
                caller_edges = tuple(adjacent.get(caller_id, ()))
                catch_edges = tuple(item for item in caller_edges if item.relation == _CATCHES_RELATION)
                if _recorded_assumption(edge, "exceptions") or catch_edges:
                    support = (edge, *catch_edges) if catch_edges else (edge,)
                    emit(
                        caller_id,
                        InvalidationReason.EXCEPTION_RECOVERY_STALE,
                        "review_recovery",
                        edge.confidence,
                        old_identity,
                        new_identity,
                        support,
                        {"trigger": symbol_id, "rule": InvalidationRule.EXCEPTIONS.value},
                    )
            for edge in symbol_edges:
                if edge.relation == _CATCHES_RELATION:
                    subject = edge.source_id if edge.target_id == symbol_id else edge.target_id
                    if subject != symbol_id:
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

        if "schema" in facets:
            emit_adapters(symbol_id, old_identity, new_identity, symbol_edges, InvalidationRule.SCHEMA)
            # Constructor calls and annotation references also name schema adapters
            # when the scanner has no dedicated serializes/deserializes edges.
            seen_adapters = {
                item.subject_id
                for item in obligations.values()
                if item.reason_code == InvalidationReason.OBSOLETE_SCHEMA_ADAPTER.value
                and item.details.get("trigger") == symbol_id
            }
            for edge in incoming.get(symbol_id, ()):
                if edge.relation != _CALLS_RELATION:
                    continue
                if edge.source_id in seen_adapters:
                    continue
                seen_adapters.add(edge.source_id)
                emit(
                    edge.source_id,
                    InvalidationReason.OBSOLETE_SCHEMA_ADAPTER,
                    "review_adapter",
                    edge.confidence,
                    old_identity,
                    new_identity,
                    (edge,),
                    {
                        "trigger": symbol_id,
                        "rule": InvalidationRule.SCHEMA.value,
                        "basis": "constructor_call",
                    },
                )
            schema_symbol = new
            for other in (*old_symbols.values(), *new_symbols.values()):
                if other.stable_id == symbol_id or other.stable_id in seen_adapters:
                    continue
                if _annotation_references_schema(other, schema_symbol):
                    seen_adapters.add(other.stable_id)
                    emit(
                        other.stable_id,
                        InvalidationReason.OBSOLETE_SCHEMA_ADAPTER,
                        "review_adapter",
                        other.confidence,
                        old_identity,
                        new_identity,
                        (),
                        {
                            "trigger": symbol_id,
                            "rule": InvalidationRule.SCHEMA.value,
                            "basis": "annotation_reference",
                        },
                    )

        # Fixture body/signature changes already flow through emit_tests via
        # uses_fixture edges; also mark direct fixture dependents when the
        # changed symbol is itself a fixture.
        if _is_fixture(new) or _is_fixture(old):
            emit_tests(symbol_id, old_identity, new_identity, symbol_edges)

        emit_opaque(symbol_id, old_identity, new_identity, (old, new, *symbol_edges))

    for artifact_id in sorted(set(delta.added_artifact_ids) | set(delta.deleted_artifact_ids) | set(delta.modified_artifact_ids)):
        old, new = old_artifacts.get(artifact_id), new_artifacts.get(artifact_id)
        artifact = new or old
        if artifact is None:
            continue
        old_identity, new_identity = (
            None if old is None else old.source_cid,
            None if new is None else new.source_cid,
        )
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
                for subject in _test_subjects_for_edge(edge, artifact_id, old_symbols, new_symbols):
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

    # Edge-only changes (no symbol/artifact identity drift) remain actionable.
    edge_only_ids = sorted(set(delta.added_edge_ids) | set(delta.deleted_edge_ids))
    for edge_id in edge_only_ids:
        edge = edges_by_id.get(edge_id)
        if edge is None:
            continue
        # Skip edges already justified by a changed endpoint when those
        # endpoints produced obligations above; still emit when endpoints are
        # unchanged so pure graph edits surface work.
        source_changed = edge.source_id in changed or edge.source_id in set(delta.added_artifact_ids) | set(delta.deleted_artifact_ids) | set(delta.modified_artifact_ids)
        target_changed = edge.target_id in changed or edge.target_id in set(delta.added_artifact_ids) | set(delta.deleted_artifact_ids) | set(delta.modified_artifact_ids)
        if source_changed or target_changed:
            continue
        old_identity = new_identity = None
        if edge.relation == _PROOF_RELATION:
            emit(
                edge.source_id,
                InvalidationReason.PROOF_RERUN,
                "rerun_proof",
                edge.confidence,
                old_identity,
                new_identity,
                (edge,),
                {"rule": InvalidationRule.EDGE.value, "edge_id": edge.edge_id},
            )
        elif edge.relation in _TEST_RELATIONS:
            for subject in _test_subjects_for_edge(edge, edge.target_id, old_symbols, new_symbols) or _test_subjects_for_edge(
                edge, edge.source_id, old_symbols, new_symbols
            ):
                emit(
                    subject,
                    InvalidationReason.STALE_TEST_RECEIPT,
                    "rerun_test",
                    edge.confidence,
                    old_identity,
                    new_identity,
                    (edge,),
                    {"rule": InvalidationRule.EDGE.value, "edge_id": edge.edge_id},
                )
        elif edge.relation in _ADAPTER_RELATIONS:
            emit(
                edge.source_id,
                InvalidationReason.OBSOLETE_SCHEMA_ADAPTER,
                "review_adapter",
                edge.confidence,
                old_identity,
                new_identity,
                (edge,),
                {"rule": InvalidationRule.EDGE.value, "edge_id": edge.edge_id},
            )
        elif edge.relation == _CALLS_RELATION:
            emit(
                edge.source_id,
                InvalidationReason.CALLER_SIGNATURE_MISMATCH,
                "review_call_site",
                edge.confidence,
                old_identity,
                new_identity,
                (edge,),
                {"rule": InvalidationRule.EDGE.value, "edge_id": edge.edge_id},
            )
        else:
            # Generic actionable subject for any other stored relation edit.
            emit(
                edge.source_id,
                InvalidationReason.NEW_CAPSULE,
                "build_capsule",
                edge.confidence,
                old_identity,
                new_identity,
                (edge,),
                {"rule": InvalidationRule.EDGE.value, "edge_id": edge.edge_id, "relation": edge.relation},
            )

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
