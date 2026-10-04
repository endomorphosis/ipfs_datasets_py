"""Deterministic authoritative capsule compilation with verified incremental reuse.

This module is the sole owner of the ``SemanticCapsuleCompiler@1`` interface.
It compiles producer-authoritative capsules from a sealed ISI view and a
bindings-owned per-symbol relevant projection.  It never rediscovers binding
scope, never reimplements :func:`relevant_binding_projection`, never raises
confidence, and never references another capsule or symbol-node CID as a
dependency.

A verified ``previous_bundle`` may accelerate materialization only after the
complete current inputs reverify and the stored block bytes are byte-identical
to the cold path.  Cold and verified-incremental compilation over identical
inputs are therefore always byte-identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
    validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    DependencyEdge,
    RelationType,
    RepositoryState,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.bindings import (
    relevant_binding_projection_for_symbol,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    CAPSULE_COMPILER_VERSION,
    SEMANTIC_CAPSULE_SCHEMA,
    EnvironmentBindingSet,
    RelevantBindingProjection,
    SemanticCapsule,
    SemanticStateBundle,
    SemanticStateModelError,
    SortedPairIndex,
    SymbolFactNode,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

SEMANTIC_CAPSULE_COMPILER_INTERFACE: Final[str] = "SemanticCapsuleCompiler@1"
SEMANTIC_CAPSULE_COMPILER_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-capsule-compiler@1"
)

# Metadata keys promoted into first-class capsule fields or excluded as
# non-authoritative heuristic annotations (never raise confidence / truth).
_PROMOTED_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "defaults",
        "contracts",
        "effects",
        "exception_behavior",
        "docstring",
        "docstring_hint",
    }
)
_HEURISTIC_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "llm_summary",
        "llm_summaries",
        "heuristic_summary",
        "model_summary",
        "summary",
        "ai_summary",
        "generated_summary",
    }
)

# Outgoing relations that form general dependency references on the capsule.
_DEPENDENCY_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        RelationType.IMPORTS.value,
        RelationType.CALLS.value,
        RelationType.INHERITS.value,
        RelationType.IMPLEMENTS.value,
        RelationType.READS_STATE.value,
        RelationType.WRITES_STATE.value,
        RelationType.CONFIGURED_BY.value,
        RelationType.GENERATED_FROM.value,
    }
)
_EFFECT_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        RelationType.READS_STATE.value,
        RelationType.WRITES_STATE.value,
    }
)
_SCHEMA_RELATIONS: Final[frozenset[str]] = frozenset({RelationType.VALIDATES.value})
_SERIALIZATION_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        RelationType.SERIALIZES.value,
        RelationType.DESERIALIZES.value,
    }
)
_TEST_RELATIONS: Final[frozenset[str]] = frozenset({RelationType.TESTED_BY.value})
_FIXTURE_RELATIONS: Final[frozenset[str]] = frozenset({RelationType.USES_FIXTURE.value})
_PROOF_RELATIONS: Final[frozenset[str]] = frozenset(
    {RelationType.PROOF_DEPENDS_ON.value}
)
_EXCEPTION_RAISES: Final[str] = RelationType.RAISES.value
_EXCEPTION_CATCHES: Final[str] = RelationType.CATCHES.value

_CONFIDENCE_RANK: Final[dict[str, int]] = {
    AnalysisConfidence.EXACT.value: 0,
    AnalysisConfidence.CONSERVATIVE.value: 1,
    AnalysisConfidence.HEURISTIC.value: 2,
    AnalysisConfidence.OPAQUE.value: 3,
}


class CapsuleCompilerError(SemanticStateModelError):
    """Raised when capsule compilation inputs or outputs are invalid."""


@runtime_checkable
class SemanticIndexForCapsules(Protocol):
    """Minimal sealed ISI view required by the capsule compiler."""

    @property
    def state_cid(self) -> str: ...

    @property
    def symbols(self) -> Sequence[SymbolRecord]: ...

    @property
    def artifacts(self) -> Sequence: ...

    @property
    def edges(self) -> Sequence[DependencyEdge]: ...

    @property
    def repository_id(self) -> str: ...


# ---------------------------------------------------------------------------
# Intermediate compile results
# ---------------------------------------------------------------------------


def _freeze_blocks(blocks: Mapping[str, bytes]) -> Mapping[str, bytes]:
    if not isinstance(blocks, Mapping):
        raise CapsuleCompilerError("blocks must be a mapping")
    verified: dict[str, bytes] = {}
    for key, data in blocks.items():
        try:
            cid = validate_cid(key)
        except Exception as exc:
            raise CapsuleCompilerError(f"block key must be a valid CID: {key!r}") from exc
        if type(data) is not bytes:
            raise CapsuleCompilerError(f"block {cid} data must be bytes")
        if cid in verified and verified[cid] != data:
            raise CapsuleCompilerError(f"conflicting block bytes for CID {cid}")
        try:
            import json

            payload = json.loads(data.decode("utf-8"))
        except Exception as exc:
            raise CapsuleCompilerError(f"block {cid} is not UTF-8 DAG-JSON") from exc
        if canonical_dag_json_bytes(payload) != data:
            raise CapsuleCompilerError(f"block {cid} is not canonical DAG-JSON")
        recomputed = cid_for_structured(payload)
        if recomputed != cid:
            raise CapsuleCompilerError(
                f"block CID {cid} does not reverify (got {recomputed})"
            )
        verified[cid] = data
    return MappingProxyType(dict(sorted(verified.items())))


def _record_block(identity_payload: Mapping[str, Any], claimed_cid: str) -> tuple[str, bytes]:
    """Return ``(cid, canonical_bytes)`` for one identity payload."""
    data = canonical_dag_json_bytes(dict(identity_payload))
    recomputed = cid_for_structured(dict(identity_payload))
    if recomputed != claimed_cid:
        raise CapsuleCompilerError(
            f"claimed CID {claimed_cid} does not match identity payload {recomputed}"
        )
    return recomputed, data


def _least_confident(*values: str) -> str:
    """Return the least confident analysis confidence; never raise confidence."""
    if not values:
        return AnalysisConfidence.EXACT.value
    return max(values, key=lambda value: _CONFIDENCE_RANK.get(value, 3))


def _as_repository_state(index: object, name: str) -> RepositoryState:
    if isinstance(index, RepositoryState):
        return index
    try:
        return RepositoryState(
            repository_id=index.repository_id,  # type: ignore[attr-defined]
            symbols=tuple(index.symbols),  # type: ignore[attr-defined]
            artifacts=tuple(index.artifacts),  # type: ignore[attr-defined]
            edges=tuple(index.edges),  # type: ignore[attr-defined]
        )
    except Exception as exc:
        raise CapsuleCompilerError(
            f"{name} must be a RepositoryState or SemanticIndexForCapsules"
        ) from exc


def _as_binding_set(
    binding_set: EnvironmentBindingSet | None,
    relevant_bindings: EnvironmentBindingSet | None,
    environment_bindings: Sequence[object] | None,
) -> EnvironmentBindingSet:
    candidates = [item for item in (binding_set, relevant_bindings) if item is not None]
    if len(candidates) > 1:
        raise CapsuleCompilerError(
            "pass only one of binding_set or relevant_bindings"
        )
    if candidates:
        value = candidates[0]
        if not isinstance(value, EnvironmentBindingSet):
            raise CapsuleCompilerError(
                "binding_set/relevant_bindings must be an EnvironmentBindingSet"
            )
        return value
    if environment_bindings is None:
        return EnvironmentBindingSet(bindings=())
    from ipfs_datasets_py.logic.software_contracts.semantic_state.bindings import (
        build_environment_binding_set,
    )

    return build_environment_binding_set(environment_bindings)


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_structured(item) for item in value]
    return value


def _thaw_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        return {}
    return _thaw_structured(dict(value))


def _as_text_sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return ()
    if not isinstance(value, (list, tuple)):
        return ()
    items: list[str] = []
    for item in value:
        if type(item) is str and item:
            items.append(item)
    return tuple(items)


def _docstring_hint(metadata: Mapping[str, Any]) -> str | None:
    for key in ("docstring_hint", "docstring"):
        value = metadata.get(key)
        if type(value) is str and value:
            return value
    return None


def _authoritative_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Strip promoted fields and heuristic/LLM annotations from capsule metadata."""
    result: dict[str, Any] = {}
    for key, value in metadata.items():
        if type(key) is not str:
            continue
        if key in _PROMOTED_METADATA_KEYS or key in _HEURISTIC_METADATA_KEYS:
            continue
        result[key] = value
    return result


def capsule_source_key(
    symbol_or_stable_id: SymbolRecord | str,
    version_cid: str | None = None,
    semantic_index_schema: str | None = None,
    extractor_version: str | None = None,
) -> tuple[str, str, str, str]:
    """Return the normative ISI producer key for a capsule.

    Accepts either a :class:`SymbolRecord` or the four explicit key components.
    """
    if isinstance(symbol_or_stable_id, SymbolRecord):
        symbol = symbol_or_stable_id
        return (
            symbol.stable_id,
            symbol.version_cid,
            symbol.semantic_index_schema,
            symbol.extractor_version,
        )
    if type(symbol_or_stable_id) is not str or not symbol_or_stable_id:
        raise CapsuleCompilerError("stable_symbol_id must be a nonempty string")
    if type(version_cid) is not str or not version_cid:
        raise CapsuleCompilerError("version_cid must be a nonempty string")
    if type(semantic_index_schema) is not str or not semantic_index_schema:
        raise CapsuleCompilerError("semantic_index_schema must be a nonempty string")
    if type(extractor_version) is not str or not extractor_version:
        raise CapsuleCompilerError("extractor_version must be a nonempty string")
    return (
        symbol_or_stable_id,
        version_cid,
        semantic_index_schema,
        extractor_version,
    )


def _previous_blocks(previous_bundle: object | None) -> Mapping[str, bytes]:
    """Extract rehashed, verified previous blocks eligible for reuse."""
    if previous_bundle is None:
        return MappingProxyType({})
    if isinstance(previous_bundle, SemanticStateBundle):
        # Full reverify of the previous bundle before any reuse.
        previous_bundle.verify()
        return previous_bundle.blocks
    if isinstance(previous_bundle, CapsuleCompileResult):
        return previous_bundle.blocks
    blocks = getattr(previous_bundle, "blocks", None)
    if isinstance(blocks, Mapping):
        return _freeze_blocks(blocks)
    raise CapsuleCompilerError(
        "previous_bundle must be a SemanticStateBundle, CapsuleCompileResult, "
        "or expose a verified blocks mapping"
    )


def _try_reuse_block(
    cid: str,
    data: bytes,
    previous_blocks: Mapping[str, bytes],
) -> tuple[bytes, bool]:
    """Reuse previous bytes only when CID and payload are byte-identical."""
    prior = previous_blocks.get(cid)
    if prior is None:
        return data, False
    if prior == data:
        return prior, True
    # Same content-addressed CID cannot legitimately carry different bytes.
    # Prefer the cold-path canonical bytes; do not trust the divergent prior.
    return data, False


@dataclass(frozen=True, slots=True)
class CapsuleCompileResult:
    """Compiled capsules plus sorted index and content-addressed blocks.

    ``reused_cids`` is a diagnostic only and is never a root input.
    """

    capsules: tuple[SemanticCapsule, ...]
    index: SortedPairIndex
    blocks: Mapping[str, bytes]
    reused_cids: tuple[str, ...] = ()

    def capsule(self, stable_symbol_id: str) -> SemanticCapsule:
        for item in self.capsules:
            if item.stable_symbol_id == stable_symbol_id:
                return item
        raise CapsuleCompilerError(f"unknown capsule {stable_symbol_id!r}")

    @property
    def capsule_index_cid(self) -> str:
        return self.index.index_cid

    def as_pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple(self.index.pairs)


def _outgoing_edges(
    edges: Sequence[DependencyEdge],
    stable_symbol_id: str,
) -> tuple[DependencyEdge, ...]:
    return tuple(
        sorted(
            (edge for edge in edges if edge.source_id == stable_symbol_id),
            key=lambda item: item.edge_id,
        )
    )


def _unique_preserve_sort(values: Iterable[str]) -> list[str]:
    """Return sorted unique strings (SemanticCapsule rejects input duplicates)."""
    return sorted(set(values))


def _dependency_payload(
    edges: Sequence[DependencyEdge],
    *,
    fact_by_stable_id: Mapping[str, SymbolFactNode],
) -> dict[str, Any]:
    """Derive dependency / relation fields from sealed outgoing edges."""
    dependency_stable_ids: list[str] = []
    dependency_version_cids: list[str] = []
    dependency_fact_cids: list[str] = []
    dependency_link_ids: list[str] = []
    effects: list[str] = []
    schema_relations: list[str] = []
    serialization_relations: list[str] = []
    test_refs: list[str] = []
    fixture_refs: list[str] = []
    proof_obligation_refs: list[str] = []
    raises: list[str] = []
    catches: list[str] = []
    edge_confidences: list[str] = []

    for edge in edges:
        relation = str(edge.relation)
        edge_confidences.append(str(edge.confidence))
        target_id = edge.target_id
        fact = fact_by_stable_id.get(target_id)

        if relation in _DEPENDENCY_RELATIONS:
            dependency_link_ids.append(edge.edge_id)
            if target_id:
                dependency_stable_ids.append(target_id)
            if fact is not None:
                dependency_version_cids.append(fact.version_cid)
                dependency_fact_cids.append(fact.fact_cid)

        if relation in _EFFECT_RELATIONS:
            effects.append(f"{relation}:{target_id}")
        if relation in _SCHEMA_RELATIONS:
            schema_relations.append(target_id)
        if relation in _SERIALIZATION_RELATIONS:
            serialization_relations.append(f"{relation}:{target_id}")
        if relation in _TEST_RELATIONS:
            test_refs.append(target_id)
        if relation in _FIXTURE_RELATIONS:
            fixture_refs.append(target_id)
        if relation in _PROOF_RELATIONS:
            proof_obligation_refs.append(target_id)
        if relation == _EXCEPTION_RAISES:
            raises.append(target_id)
        if relation == _EXCEPTION_CATCHES:
            catches.append(target_id)

    exception_behavior: dict[str, Any] = {}
    if raises:
        exception_behavior["raises"] = _unique_preserve_sort(raises)
    if catches:
        exception_behavior["catches"] = _unique_preserve_sort(catches)

    return {
        "dependency_stable_ids": _unique_preserve_sort(dependency_stable_ids),
        "dependency_version_cids": _unique_preserve_sort(dependency_version_cids),
        "dependency_fact_cids": _unique_preserve_sort(dependency_fact_cids),
        "dependency_link_ids": _unique_preserve_sort(dependency_link_ids),
        "effects": _unique_preserve_sort(effects),
        "schema_relations": _unique_preserve_sort(schema_relations),
        "serialization_relations": _unique_preserve_sort(serialization_relations),
        "test_refs": _unique_preserve_sort(test_refs),
        "fixture_refs": _unique_preserve_sort(fixture_refs),
        "proof_obligation_refs": _unique_preserve_sort(proof_obligation_refs),
        "exception_behavior": exception_behavior,
        "edge_confidences": edge_confidences,
    }


def _compile_one_capsule(
    symbol: SymbolRecord,
    *,
    fact: SymbolFactNode,
    edges: Sequence[DependencyEdge],
    fact_by_stable_id: Mapping[str, SymbolFactNode],
    projection: RelevantBindingProjection,
) -> SemanticCapsule:
    """Compile one authoritative capsule from sealed producer inputs."""
    if projection.stable_symbol_id != symbol.stable_id:
        raise CapsuleCompilerError(
            "relevant binding projection stable_symbol_id does not match symbol"
        )

    metadata = _thaw_mapping(symbol.metadata)
    defaults = _thaw_mapping(metadata.get("defaults"))
    contracts = _thaw_mapping(metadata.get("contracts"))
    meta_exception = _thaw_mapping(metadata.get("exception_behavior"))
    meta_effects = list(_as_text_sequence(metadata.get("effects")))

    dep = _dependency_payload(edges, fact_by_stable_id=fact_by_stable_id)

    effects = sorted(set(meta_effects) | set(dep["effects"]))
    exception_behavior = dict(meta_exception)
    for key, values in dep["exception_behavior"].items():
        existing = exception_behavior.get(key)
        if isinstance(existing, list):
            exception_behavior[key] = sorted(set(existing) | set(values))
        else:
            exception_behavior[key] = list(values)

    confidence = _least_confident(
        str(symbol.confidence),
        *dep["edge_confidences"],
    )

    # Signature / annotations / decorators are producer-authoritative and never
    # invented here.  Defaults/contracts come only from sealed metadata.
    signature = _thaw_mapping(symbol.signature)
    annotations = _thaw_mapping(symbol.annotations)
    decorators = list(symbol.decorators)

    capsule = SemanticCapsule(
        stable_symbol_id=symbol.stable_id,
        version_cid=symbol.version_cid,
        semantic_index_schema=symbol.semantic_index_schema,
        extractor_version=symbol.extractor_version,
        capsule_schema=SEMANTIC_CAPSULE_SCHEMA,
        capsule_compiler_version=CAPSULE_COMPILER_VERSION,
        source_slice_path=symbol.module_path,
        source_cid=symbol.source_cid,
        symbol_fact_cid=fact.fact_cid,
        signature=signature,
        annotations=annotations,
        defaults=defaults,
        decorators=decorators,
        contracts=contracts,
        effects=effects,
        exception_behavior=exception_behavior,
        schema_relations=dep["schema_relations"],
        serialization_relations=dep["serialization_relations"],
        test_refs=dep["test_refs"],
        fixture_refs=dep["fixture_refs"],
        proof_obligation_refs=dep["proof_obligation_refs"],
        dependency_stable_ids=dep["dependency_stable_ids"],
        dependency_version_cids=dep["dependency_version_cids"],
        dependency_fact_cids=dep["dependency_fact_cids"],
        dependency_link_ids=dep["dependency_link_ids"],
        confidence=confidence,
        relevant_binding_projection_cid=projection.projection_cid,
        docstring_hint=_docstring_hint(metadata),
        metadata=_authoritative_metadata(metadata),
    )
    # Producer key must match the sealed symbol identity exactly.
    if capsule.producer_key() != capsule_source_key(symbol):
        raise CapsuleCompilerError("capsule producer key does not match symbol")
    return capsule


def _capsule_bound_projection(
    symbol: SymbolRecord,
    binding_set: EnvironmentBindingSet,
) -> RelevantBindingProjection:
    """Return the projection CID bound into a capsule.

    Membership is decided solely by :func:`relevant_binding_projection_for_symbol`
    over the full environment set.  The capsule then binds a projection of only
    those selected bindings so a known disjoint scoped change (which still
    alters the root binding-set CID) does not change unrelated capsule CIDs.
    Global/unknown selections remain in every affected projection and therefore
    conservatively change every capsule that includes them.
    """
    membership = relevant_binding_projection_for_symbol(symbol, binding_set)
    selected_ids = frozenset(membership.binding_ids)
    if not selected_ids:
        # Empty selection still binds an empty projection against an empty set
        # so the capsule does not track the full root binding-set CID.
        empty = EnvironmentBindingSet(bindings=())
        return relevant_binding_projection_for_symbol(symbol, empty)
    selected = tuple(
        binding
        for binding in binding_set.bindings
        if binding.binding_id in selected_ids
    )
    selected_set = EnvironmentBindingSet(bindings=selected)
    return relevant_binding_projection_for_symbol(symbol, selected_set)


def _resolve_projection(
    symbol: SymbolRecord,
    binding_set: EnvironmentBindingSet,
    projections: Mapping[str, RelevantBindingProjection] | None,
) -> RelevantBindingProjection:
    if projections is not None and symbol.stable_id in projections:
        projection = projections[symbol.stable_id]
        if not isinstance(projection, RelevantBindingProjection):
            raise CapsuleCompilerError(
                "projections values must be RelevantBindingProjection records"
            )
        if projection.stable_symbol_id != symbol.stable_id:
            raise CapsuleCompilerError(
                "projection stable_symbol_id does not match map key/symbol"
            )
        # Caller-supplied projections are trusted only after structural checks.
        # They may intentionally bind a non-root set CID (capsule-relevant view).
        expected = _capsule_bound_projection(symbol, binding_set)
        if set(projection.binding_ids) != set(expected.binding_ids):
            raise CapsuleCompilerError(
                "supplied projection binding_ids do not match bindings membership"
            )
        if projection.includes_global != expected.includes_global:
            raise CapsuleCompilerError(
                "supplied projection includes_global does not match bindings membership"
            )
        return projection
    return _capsule_bound_projection(symbol, binding_set)


def compile_semantic_capsule(
    semantic_index: RepositoryState | SemanticIndexForCapsules,
    stable_symbol_id: str,
    *,
    relevant_bindings: EnvironmentBindingSet | None = None,
    binding_set: EnvironmentBindingSet | None = None,
    environment_bindings: Sequence[object] | None = None,
    relevant_projection: RelevantBindingProjection | None = None,
    projections: Mapping[str, RelevantBindingProjection] | None = None,
) -> SemanticCapsule:
    """Compile one deterministic authoritative capsule for ``stable_symbol_id``.

    Consumes the sealed ISI symbol and its outgoing edges plus a bindings-owned
    relevant projection (computed here via :mod:`bindings` when not supplied).
    """
    if type(stable_symbol_id) is not str or not stable_symbol_id:
        raise CapsuleCompilerError("stable_symbol_id must be a nonempty string")
    state = _as_repository_state(semantic_index, "semantic_index")
    symbols = list(state.symbols)
    if any(not isinstance(item, SymbolRecord) for item in symbols):
        raise CapsuleCompilerError("symbols must be SymbolRecord values")
    by_id = {item.stable_id: item for item in symbols}
    if len(by_id) != len(symbols):
        raise CapsuleCompilerError("symbols must not contain duplicate stable_id values")
    symbol = by_id.get(stable_symbol_id)
    if symbol is None:
        raise CapsuleCompilerError(f"unknown stable_symbol_id {stable_symbol_id!r}")

    resolved_bindings = _as_binding_set(
        binding_set, relevant_bindings, environment_bindings
    )
    if relevant_projection is not None:
        if projections is not None:
            raise CapsuleCompilerError(
                "pass only one of relevant_projection or projections"
            )
        projections = {stable_symbol_id: relevant_projection}
    projection = _resolve_projection(symbol, resolved_bindings, projections)

    facts = {item.stable_id: SymbolFactNode(symbol=item) for item in symbols}
    edges = list(state.edges)
    if any(not isinstance(item, DependencyEdge) for item in edges):
        raise CapsuleCompilerError("edges must be DependencyEdge values")
    outgoing = _outgoing_edges(edges, stable_symbol_id)
    return _compile_one_capsule(
        symbol,
        fact=facts[stable_symbol_id],
        edges=outgoing,
        fact_by_stable_id=facts,
        projection=projection,
    )


def compile_semantic_capsules(
    semantic_index: RepositoryState | SemanticIndexForCapsules,
    *,
    relevant_bindings: EnvironmentBindingSet | None = None,
    binding_set: EnvironmentBindingSet | None = None,
    environment_bindings: Sequence[object] | None = None,
    projections: Mapping[str, RelevantBindingProjection] | None = None,
    previous_bundle: SemanticStateBundle | CapsuleCompileResult | None = None,
) -> CapsuleCompileResult:
    """Compile capsules for every symbol in stable-symbol order.

    ``previous_bundle`` may supply previously verified capsule/index blocks.
    Blocks are reused only when the complete current inputs reverify to the same
    content-addressed CID and the stored bytes are byte-identical.  Cold and
    incremental compilation over identical inputs therefore emit identical
    blocks and index CIDs.
    """
    state = _as_repository_state(semantic_index, "semantic_index")
    symbols = list(state.symbols)
    if any(not isinstance(item, SymbolRecord) for item in symbols):
        raise CapsuleCompilerError("symbols must be SymbolRecord values")
    ordered = sorted(symbols, key=lambda item: item.stable_id)
    if len({item.stable_id for item in ordered}) != len(ordered):
        raise CapsuleCompilerError("symbols must not contain duplicate stable_id values")

    edges = list(state.edges)
    if any(not isinstance(item, DependencyEdge) for item in edges):
        raise CapsuleCompilerError("edges must be DependencyEdge values")

    resolved_bindings = _as_binding_set(
        binding_set, relevant_bindings, environment_bindings
    )
    previous_blocks = _previous_blocks(previous_bundle)

    facts = {item.stable_id: SymbolFactNode(symbol=item) for item in ordered}
    capsules: list[SemanticCapsule] = []
    pairs: list[tuple[str, str]] = []
    blocks: dict[str, bytes] = {}
    reused: list[str] = []

    for symbol in ordered:
        projection = _resolve_projection(symbol, resolved_bindings, projections)
        # Projection blocks are not root inputs for this task, but their CID is
        # bound into the capsule and must reverify as a structured record.
        _ = projection.projection_cid
        outgoing = _outgoing_edges(edges, symbol.stable_id)
        capsule = _compile_one_capsule(
            symbol,
            fact=facts[symbol.stable_id],
            edges=outgoing,
            fact_by_stable_id=facts,
            projection=projection,
        )
        cid, data = _record_block(capsule.identity_payload(), capsule.capsule_cid)
        data, was_reused = _try_reuse_block(cid, data, previous_blocks)
        if was_reused:
            reused.append(cid)
        if cid in blocks and blocks[cid] != data:
            raise CapsuleCompilerError(f"conflicting capsule block bytes for {cid}")
        blocks[cid] = data
        capsules.append(capsule)
        pairs.append((capsule.stable_symbol_id, cid))

    index = SortedPairIndex(pairs=pairs)
    index_cid, index_data = _record_block(index.identity_payload(), index.index_cid)
    index_data, index_reused = _try_reuse_block(index_cid, index_data, previous_blocks)
    if index_reused:
        reused.append(index_cid)
    blocks[index_cid] = index_data

    return CapsuleCompileResult(
        capsules=tuple(capsules),
        index=index,
        blocks=_freeze_blocks(blocks),
        reused_cids=tuple(sorted(set(reused))),
    )


def verify_capsule_compile_result(result: CapsuleCompileResult) -> CapsuleCompileResult:
    """Reverify every capsule/index block and claimed CID."""
    if not isinstance(result, CapsuleCompileResult):
        raise CapsuleCompilerError("result must be a CapsuleCompileResult")

    import json

    for capsule in result.capsules:
        try:
            data = result.blocks[capsule.capsule_cid]
        except KeyError as exc:
            raise CapsuleCompilerError(
                f"missing capsule block {capsule.capsule_cid}"
            ) from exc
        payload = json.loads(data.decode("utf-8"))
        if canonical_dag_json_bytes(payload) != data:
            raise CapsuleCompilerError(
                f"capsule block {capsule.capsule_cid} is not canonical"
            )
        if cid_for_structured(payload) != capsule.capsule_cid:
            raise CapsuleCompilerError(
                f"capsule block {capsule.capsule_cid} does not reverify"
            )
        if payload != capsule.identity_payload():
            raise CapsuleCompilerError(
                f"capsule block {capsule.capsule_cid} does not match record"
            )
        restored = SemanticCapsule.from_dict(capsule.to_dict())
        if restored.capsule_cid != capsule.capsule_cid:
            raise CapsuleCompilerError("capsule CID round-trip failed")

    try:
        index_data = result.blocks[result.index.index_cid]
    except KeyError as exc:
        raise CapsuleCompilerError(
            f"missing index block {result.index.index_cid}"
        ) from exc
    index_payload = json.loads(index_data.decode("utf-8"))
    if canonical_dag_json_bytes(index_payload) != index_data:
        raise CapsuleCompilerError("capsule index block is not canonical")
    if cid_for_structured(index_payload) != result.index.index_cid:
        raise CapsuleCompilerError("capsule index block does not reverify")
    if index_payload != result.index.identity_payload():
        raise CapsuleCompilerError("capsule index block does not match record")
    restored_index = SortedPairIndex.from_dict(result.index.to_dict())
    if restored_index.index_cid != result.index.index_cid:
        raise CapsuleCompilerError("capsule index CID round-trip failed")

    membership = {
        capsule.stable_symbol_id: capsule.capsule_cid for capsule in result.capsules
    }
    if dict(result.index.pairs) != membership:
        raise CapsuleCompilerError("capsule index membership mismatch")
    return result


__all__ = [
    "CAPSULE_COMPILER_VERSION",
    "SEMANTIC_CAPSULE_COMPILER_INTERFACE",
    "SEMANTIC_CAPSULE_COMPILER_SCHEMA",
    "SEMANTIC_CAPSULE_SCHEMA",
    "CapsuleCompileResult",
    "CapsuleCompilerError",
    "SemanticIndexForCapsules",
    "capsule_source_key",
    "compile_semantic_capsule",
    "compile_semantic_capsules",
    "verify_capsule_compile_result",
]
