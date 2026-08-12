"""Deterministic semantic comparison for repository-index states.

The comparison intentionally operates on stable symbol identities and on
semantic projections, rather than raw source bytes or source locations.  A
source reformat can therefore alter a snapshot's provenance without becoming a
symbol or edge change.  Rename correlations are only heuristic annotations:
the old and new stable IDs remain respectively deleted and added.

Facets are independent: a combined body and signature edit retains both, and
schema is reserved for schema-bearing kinds (dataclass / typed dict / enum),
not ordinary function or method annotations.
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
_SCHEMA_KINDS: Final[frozenset[str]] = frozenset(
    {
        SymbolKind.DATACLASS.value,
        SymbolKind.TYPED_DICT.value,
        SymbolKind.ENUM.value,
    }
)
# Only these annotation keys describe a durable schema surface.  Parameter and
# return annotations on ordinary functions/methods are deliberately excluded.
_SCHEMA_ANNOTATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "fields",
        "bases",
        "enum_family",
        "pydantic_model",
        "total",
    }
)
# Analyzer metadata that mirrors normalized AST / inventory and must not drown
# an independent body facet.
_METADATA_BODY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "facets",
        "frontend_declarations",
        "facet_count",
    }
)


class RepositoryStateDeltaError(ValueError):
    """Raised when states cannot be compared under the delta contract."""


def _jsonable(value: Any) -> Any:
    """Return a strict DAG-JSON value (lists, not tuples; plain dicts)."""
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _semantic_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drop body-duplicating analyzer inventory from the metadata facet."""
    if not metadata:
        return {}
    return {
        key: _jsonable(value)
        for key, value in dict(metadata).items()
        if key not in _METADATA_BODY_KEYS
    }


def _schema_projection(symbol: SymbolRecord) -> dict[str, Any]:
    """Return the schema-bearing annotation surface, or empty for non-schemas."""
    if symbol.kind not in _SCHEMA_KINDS:
        return {}
    annotations = dict(symbol.annotations)
    return {
        key: _jsonable(annotations[key])
        for key in sorted(annotations)
        if key in _SCHEMA_ANNOTATION_KEYS
    }


def _symbol_projection(symbol: SymbolRecord) -> dict[str, Any]:
    """Return the semantic portion of a stable symbol record.

    ``source_cid`` and ``span`` are snapshot provenance, not semantic facts.
    ``normalized_ast`` is the body surface; schema annotations are projected
    separately so ordinary function type hints do not become schema edits.
    """
    return {
        "version_cid": symbol.version_cid,
        "normalized_ast": _jsonable(symbol.normalized_ast),
        "signature": _jsonable(dict(symbol.signature)),
        "decorators": list(symbol.decorators),
        "schema": _schema_projection(symbol),
        "annotations": _jsonable(dict(symbol.annotations)),
        "metadata": _semantic_metadata(symbol.metadata),
        "confidence": symbol.confidence,
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
        "metadata": _jsonable(dict(edge.metadata)),
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

    Facets are independent.  A body edit is a ``normalized_ast`` difference and
    is retained alongside signature/schema/etc. when those also change.  Schema
    is emitted only for schema-bearing kinds when their field/base surface
    changes — not for ordinary function or dataclass-method annotations.
    """
    if not isinstance(previous, SymbolRecord) or not isinstance(current, SymbolRecord):
        raise RepositoryStateDeltaError("symbols must be SymbolRecords")
    if previous.stable_id != current.stable_id:
        raise RepositoryStateDeltaError("symbol change classification requires matching stable_id")

    facets: set[str] = set()
    if _jsonable(previous.normalized_ast) != _jsonable(current.normalized_ast):
        facets.add("body")
    if previous.signature != current.signature:
        facets.add("signature")
    if previous.decorators != current.decorators:
        facets.add("decorator")
    if _schema_projection(previous) != _schema_projection(current):
        facets.add("schema")
    if _semantic_metadata(previous.metadata) != _semantic_metadata(current.metadata):
        facets.add("metadata")
    if previous.confidence != current.confidence:
        facets.add("confidence")

    old_facts = _edge_facts(previous_edges, previous.stable_id)
    new_facts = _edge_facts(current_edges, current.stable_id)
    if any(old_facts.get(relation, ()) != new_facts.get(relation, ()) for relation in _EFFECT_RELATIONS):
        facets.add("effects")
    if any(old_facts.get(relation, ()) != new_facts.get(relation, ()) for relation in _EXCEPTION_RELATIONS):
        facets.add("exceptions")

    # Residual version-CID change with no independently represented facet is
    # still body-local (for example annotation-only projections that ride the
    # version CID without altering normalized_ast or schema surface).
    if previous.version_cid != current.version_cid and not facets:
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
        "signature": _jsonable(dict(symbol.signature)),
        "decorators": list(symbol.decorators),
        "annotations": _jsonable(dict(symbol.annotations)),
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

    return RepositoryStateDelta(
        previous_state_cid=previous_state.state_cid,
        current_state_cid=current_state.state_cid,
        added_symbol_ids=added_symbols,
        deleted_symbol_ids=deleted_symbols,
        modified_symbol_ids=modified_symbols,
        unchanged_symbol_ids=unchanged_symbols,
        rename_candidates=_rename_candidates(
            (old_symbols[symbol_id] for symbol_id in deleted_symbols),
            (new_symbols[symbol_id] for symbol_id in added_symbols),
        ),
        added_artifact_ids=added_artifacts,
        deleted_artifact_ids=deleted_artifacts,
        modified_artifact_ids=modified_artifacts,
        added_edge_ids=added_edges,
        deleted_edge_ids=deleted_edges,
    )


__all__ = [
    "RENAME_CANDIDATE_SCHEMA",
    "SYMBOL_CHANGE_FACETS",
    "RepositoryStateDeltaError",
    "classify_symbol_change",
    "diff_repository_states",
]
