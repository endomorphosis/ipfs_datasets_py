"""Deterministic semantic comparison for repository-index states.

The comparison intentionally operates on stable symbol identities and on
semantic projections, rather than raw source bytes or source locations.  A
source reformat can therefore alter a snapshot's provenance without becoming a
symbol or edge change.  Rename correlations are only heuristic annotations:
the old and new stable IDs remain respectively deleted and added.

Facet classification keeps body, signature, effects, exceptions, schema,
decorator, metadata, and confidence independently observable so a combined
body+signature edit retains both facts.  Schema is reserved for schema-bearing
kinds; ordinary function annotations are never promoted to a schema change.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any, Final

from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    DependencyEdge,
    RepositoryState,
    RepositoryStateDelta,
    SymbolKind,
    SymbolRecord,
)


RENAME_CANDIDATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-rename-candidate@1"
)

# These strings are a closed public vocabulary for ``classify_symbol_change``.
SYMBOL_CHANGE_FACETS: Final[tuple[str, ...]] = (
    "body",
    "signature",
    "effects",
    "exceptions",
    "schema",
    "decorator",
    "metadata",
    "confidence",
)

_EFFECT_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        "reads_state",
        "writes_state",
        "serializes",
        "deserializes",
        "validates",
    }
)
_EXCEPTION_RELATIONS: Final[frozenset[str]] = frozenset({"raises", "catches"})

# Schema facets apply only to declarations whose durable contract is a field
# or member schema.  Ordinary functions, methods, and modules use annotations
# as version inputs without becoming "schema" changes.
_SCHEMA_KINDS: Final[frozenset[str]] = frozenset(
    {
        SymbolKind.DATACLASS.value,
        SymbolKind.TYPED_DICT.value,
        SymbolKind.ENUM.value,
        SymbolKind.CLASS.value,
    }
)

# Analyzer dumps that restate the version AST must not appear as a separate
# "metadata" facet when only the body changed.
_METADATA_EXCLUDED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "facets",
        "version_evidence",
        "frontend_declarations",
        "facet_count",
    }
)


class RepositoryStateDeltaError(ValueError):
    """Raised when states cannot be compared under the delta contract."""


def _thaw(value: Any) -> Any:
    """Detach mapping proxies and tuples into strict DAG-JSON shapes."""
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _semantic_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project metadata without body/version-evidence dumps."""
    if not metadata:
        return {}
    return {
        key: _thaw(value)
        for key, value in sorted(metadata.items())
        if key not in _METADATA_EXCLUDED_KEYS
    }


def _body_projection(symbol: SymbolRecord) -> Any | None:
    """Return a comparable body projection when durable AST evidence exists."""
    normalized = symbol.normalized_ast
    if normalized is not None:
        thawed = _thaw(normalized)
        if isinstance(thawed, Mapping) and "body" in thawed:
            return thawed.get("body")
        return thawed
    metadata = symbol.metadata or {}
    facets = metadata.get("facets")
    if isinstance(facets, (list, tuple)):
        bodies: list[Any] = []
        for facet in facets:
            if not isinstance(facet, Mapping):
                continue
            evidence = facet.get("version_evidence")
            if isinstance(evidence, Mapping) and "body" in evidence:
                bodies.append(_thaw(evidence.get("body")))
        if bodies:
            return bodies
    return None


def _schema_projection(symbol: SymbolRecord) -> dict[str, Any]:
    """Field/member schema facts for schema-bearing kinds only."""
    annotations = _thaw(dict(symbol.annotations or {}))
    # Prefer explicit field/member maps; fall back to the full annotation set
    # so TypedDict/Enum-style shapes remain comparable.
    fields = annotations.get("fields")
    if isinstance(fields, dict):
        schema_fields = fields
    else:
        schema_fields = {
            key: value
            for key, value in annotations.items()
            if key not in {"return", "pytest", "bases"}
        }
    return {
        "kind": symbol.kind,
        "fields": schema_fields,
        "bases": annotations.get("bases"),
        "decorators": list(symbol.decorators),
    }


def _is_schema_kind(symbol: SymbolRecord) -> bool:
    return symbol.kind in _SCHEMA_KINDS


def _symbol_projection(symbol: SymbolRecord) -> dict[str, Any]:
    """Return the semantic portion of a stable symbol record.

    ``source_cid`` and ``span`` are snapshot provenance, not semantic facts.
    The remaining fields are either the version identity itself or explicit
    semantic facts that are not bound by that identity (notably confidence).
    """
    return {
        "version_cid": symbol.version_cid,
        "signature": _thaw(dict(symbol.signature)),
        "decorators": list(symbol.decorators),
        "annotations": _thaw(dict(symbol.annotations)),
        "metadata": _semantic_metadata(symbol.metadata),
        "confidence": symbol.confidence,
        "normalized_ast": _thaw(symbol.normalized_ast) if symbol.normalized_ast is not None else None,
        "property_role": symbol.property_role,
    }


def _edge_projection(edge: DependencyEdge) -> dict[str, Any]:
    """Return an edge projection with source locations intentionally omitted."""
    return {
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "relation": edge.relation,
        "extraction_method": edge.extraction_method,
        "confidence": edge.confidence,
        "extractor_version": edge.extractor_version,
        "metadata": _thaw(dict(edge.metadata)),
    }


def _edge_facts(edges: Iterable[DependencyEdge], source_id: str) -> dict[str, tuple[dict[str, Any], ...]]:
    """Group a symbol's semantic edge facts by relation, in stable order."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        if not isinstance(edge, DependencyEdge):
            raise RepositoryStateDeltaError("edges must be DependencyEdges")
        if edge.source_id == source_id:
            grouped[edge.relation].append(_edge_projection(edge))
    return {
        relation: tuple(sorted(values, key=cid_for_structured))
        for relation, values in sorted(grouped.items())
    }


def classify_symbol_change(
    previous: SymbolRecord,
    current: SymbolRecord,
    *,
    previous_edges: Iterable[DependencyEdge] = (),
    current_edges: Iterable[DependencyEdge] = (),
) -> tuple[str, ...]:
    """Classify a stable-ID-preserving semantic change into closed facets.

    Body and interface facets are independent.  A combined body+signature
    edit therefore retains both facets.  Annotation drift on ordinary
    functions is never classified as schema.
    """
    if not isinstance(previous, SymbolRecord) or not isinstance(current, SymbolRecord):
        raise RepositoryStateDeltaError("symbols must be SymbolRecords")
    if previous.stable_id != current.stable_id:
        raise RepositoryStateDeltaError("symbol change classification requires matching stable_id")

    facets: set[str] = set()
    if previous.signature != current.signature:
        facets.add("signature")
    if previous.decorators != current.decorators:
        facets.add("decorator")
    if previous.confidence != current.confidence:
        facets.add("confidence")
    if _semantic_metadata(previous.metadata) != _semantic_metadata(current.metadata):
        facets.add("metadata")

    if _is_schema_kind(previous) or _is_schema_kind(current):
        if _schema_projection(previous) != _schema_projection(current):
            facets.add("schema")

    old_facts = _edge_facts(previous_edges, previous.stable_id)
    new_facts = _edge_facts(current_edges, current.stable_id)
    if any(old_facts.get(relation, ()) != new_facts.get(relation, ()) for relation in _EFFECT_RELATIONS):
        facets.add("effects")
    if any(old_facts.get(relation, ()) != new_facts.get(relation, ()) for relation in _EXCEPTION_RELATIONS):
        facets.add("exceptions")

    body_previous = _body_projection(previous)
    body_current = _body_projection(current)
    if body_previous is not None and body_current is not None:
        if body_previous != body_current:
            facets.add("body")
    elif previous.version_cid != current.version_cid:
        # Residual body: version identity moved while every version-bound
        # interface input stayed equal.  When interface inputs also move and
        # no durable body projection exists, body cannot be asserted.
        version_interface_same = (
            previous.signature == current.signature
            and previous.decorators == current.decorators
            and previous.annotations == current.annotations
            and previous.property_role == current.property_role
            and previous.extractor_name == current.extractor_name
            and previous.extractor_version == current.extractor_version
        )
        if version_interface_same:
            facets.add("body")

    return tuple(facet for facet in SYMBOL_CHANGE_FACETS if facet in facets)


def _edge_delta(previous: Iterable[DependencyEdge], current: Iterable[DependencyEdge]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    old_by_projection: dict[str, list[str]] = defaultdict(list)
    new_by_projection: dict[str, list[str]] = defaultdict(list)
    for edge in previous:
        if not isinstance(edge, DependencyEdge):
            raise RepositoryStateDeltaError("state edges must be DependencyEdges")
        old_by_projection[cid_for_structured(_edge_projection(edge))].append(edge.edge_id)
    for edge in current:
        if not isinstance(edge, DependencyEdge):
            raise RepositoryStateDeltaError("state edges must be DependencyEdges")
        new_by_projection[cid_for_structured(_edge_projection(edge))].append(edge.edge_id)

    deleted: list[str] = []
    added: list[str] = []
    for projection in sorted(set(old_by_projection) | set(new_by_projection)):
        old_ids = sorted(old_by_projection[projection])
        new_ids = sorted(new_by_projection[projection])
        paired = min(len(old_ids), len(new_ids))
        deleted.extend(old_ids[paired:])
        added.extend(new_ids[paired:])
    return tuple(sorted(added)), tuple(sorted(deleted))


def _rename_projection(symbol: SymbolRecord) -> dict[str, Any]:
    """Conservative interface fingerprint used only to rank rename hints."""
    return {
        "language": symbol.language,
        "kind": symbol.kind,
        "namespace": symbol.namespace,
        "signature": _thaw(dict(symbol.signature)),
        "decorators": list(symbol.decorators),
        "annotations": _thaw(dict(symbol.annotations)),
        "metadata": _semantic_metadata(symbol.metadata),
        "confidence": symbol.confidence,
    }


def _rename_candidates(previous: Iterable[SymbolRecord], current: Iterable[SymbolRecord]) -> tuple[dict[str, Any], ...]:
    """Produce only unambiguous, deterministic heuristic rename candidates."""
    old_groups: dict[str, list[SymbolRecord]] = defaultdict(list)
    new_groups: dict[str, list[SymbolRecord]] = defaultdict(list)
    for symbol in previous:
        old_groups[cid_for_structured(_rename_projection(symbol))].append(symbol)
    for symbol in current:
        new_groups[cid_for_structured(_rename_projection(symbol))].append(symbol)

    candidates: list[dict[str, Any]] = []
    for fingerprint in sorted(set(old_groups) & set(new_groups)):
        old_symbols = old_groups[fingerprint]
        new_symbols = new_groups[fingerprint]
        # Ambiguous interfaces (for example two zero-argument functions) must
        # not create arbitrary one-to-one rename claims.
        if len(old_symbols) == len(new_symbols) == 1:
            candidates.append(
                {
                    "schema": RENAME_CANDIDATE_SCHEMA,
                    "previous_symbol_id": old_symbols[0].stable_id,
                    "current_symbol_id": new_symbols[0].stable_id,
                    "confidence": "heuristic",
                    "basis": "unique_matching_interface_projection",
                }
            )
    return tuple(sorted(candidates, key=cid_for_structured))


def diff_repository_states(
    previous_state: RepositoryState,
    current_state: RepositoryState,
) -> RepositoryStateDelta:
    """Compare two states by their semantic projection in deterministic order."""
    if not isinstance(previous_state, RepositoryState) or not isinstance(current_state, RepositoryState):
        raise RepositoryStateDeltaError("previous_state and current_state must be RepositoryStates")
    if previous_state.repository_id != current_state.repository_id:
        raise RepositoryStateDeltaError("repository states must have the same repository_id")

    old_symbols = {symbol.stable_id: symbol for symbol in previous_state.symbols}
    new_symbols = {symbol.stable_id: symbol for symbol in current_state.symbols}
    added_symbols = sorted(set(new_symbols) - set(old_symbols))
    deleted_symbols = sorted(set(old_symbols) - set(new_symbols))
    common_symbols = sorted(set(old_symbols) & set(new_symbols))
    modified_symbols = [
        symbol_id
        for symbol_id in common_symbols
        if _symbol_projection(old_symbols[symbol_id]) != _symbol_projection(new_symbols[symbol_id])
    ]
    unchanged_symbols = sorted(set(common_symbols) - set(modified_symbols))

    old_artifacts = {artifact.artifact_id: artifact for artifact in previous_state.artifacts}
    new_artifacts = {artifact.artifact_id: artifact for artifact in current_state.artifacts}
    added_artifacts = sorted(set(new_artifacts) - set(old_artifacts))
    deleted_artifacts = sorted(set(old_artifacts) - set(new_artifacts))
    modified_artifacts = sorted(
        artifact_id
        for artifact_id in set(old_artifacts) & set(new_artifacts)
        if old_artifacts[artifact_id].to_dict() != new_artifacts[artifact_id].to_dict()
    )
    added_edges, deleted_edges = _edge_delta(previous_state.edges, current_state.edges)
    rename_candidates = _rename_candidates(
        (old_symbols[symbol_id] for symbol_id in deleted_symbols),
        (new_symbols[symbol_id] for symbol_id in added_symbols),
    )
    # RepositoryStateDelta freezes rename candidates then sorts with
    # ``cid_for_structured`` on mappingproxy values, which the content CID
    # authority rejects.  Construct the delta without candidates, then attach
    # frozen candidates sorted by their thawed DAG-JSON projection so rename
    # hints remain durable and content-addressable.
    delta = RepositoryStateDelta(
        previous_state_cid=previous_state.state_cid,
        current_state_cid=current_state.state_cid,
        added_symbol_ids=added_symbols,
        deleted_symbol_ids=deleted_symbols,
        modified_symbol_ids=modified_symbols,
        unchanged_symbol_ids=unchanged_symbols,
        rename_candidates=(),
        added_artifact_ids=added_artifacts,
        deleted_artifact_ids=deleted_artifacts,
        modified_artifact_ids=modified_artifacts,
        added_edge_ids=added_edges,
        deleted_edge_ids=deleted_edges,
    )
    if rename_candidates:
        from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
            _mapping,
            _thaw_structured,
        )

        frozen = tuple(
            sorted(
                (_mapping(item, "rename_candidate") for item in rename_candidates),
                key=lambda item: cid_for_structured(_thaw_structured(item)),
            )
        )
        object.__setattr__(delta, "rename_candidates", frozen)
    return delta


__all__ = [
    "RENAME_CANDIDATE_SCHEMA",
    "SYMBOL_CHANGE_FACETS",
    "RepositoryStateDeltaError",
    "classify_symbol_change",
    "diff_repository_states",
]
