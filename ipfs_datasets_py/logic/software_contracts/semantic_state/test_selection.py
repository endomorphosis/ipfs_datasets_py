"""Pure graph-based pytest/proof selection (DSS-007).

Selection is datasets semantic authority.  It consumes previous/current
:class:`SemanticStateView` values and a :class:`SemanticInvalidationPlan`, then
returns a self-verifying :class:`TestSelection`.  It never imports, collects, or
runs target tests, never re-resolves edges, and never invents pytest node IDs
without authoritative graph or metadata evidence.

Seeds and relation-specific traversal cover direct tests, reverse callers and
imports, fixture/usefixtures/autouse dependencies, schemas and
serializers/validators, config/lock/policy/interface bindings, generated inputs,
proof edges, deletion/rename evidence, and explicit user rules.  Dynamic
pytest/plugins, native/opaque reachability, an unknown universe, or insufficient
graph evidence intersecting the cone force a visible full fallback.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    DependencyEdge,
    RelationType,
    RepositoryState,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.invalidation import (
    SemanticRemediation,
    SemanticStateView,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    AnalysisLimitation,
    ReasonPath,
    SelectionFallback,
    SelectionPolicy,
    SelectionRule,
    SelectionRuleKind,
    SemanticInvalidationObligation,
    SemanticInvalidationPlan,
    SemanticLinkNode,
    SemanticStateRoot,
    SortedPairIndex,
    SymbolFactNode,
    TestSelection,
)


class TestSelectionError(ValueError):
    """Raised when test/proof selection inputs fail closed verification."""


class SelectionFallbackReason(str, Enum):
    """Closed vocabulary of visible selection fallback reasons."""

    DYNAMIC_PYTEST_PLUGIN = "dynamic_pytest_plugin"
    NATIVE_OR_OPAQUE_REACHABILITY = "native_or_opaque_reachability"
    UNKNOWN_TEST_UNIVERSE = "unknown_test_universe"
    INSUFFICIENT_GRAPH_EVIDENCE = "insufficient_graph_evidence"
    EXPLICIT_RULE_FORCE_FULL = "explicit_rule_force_full"
    EXPLICIT_RULE_FORCE_FULL_PYTEST = "explicit_rule_force_full_pytest"
    EXPLICIT_RULE_FORCE_FULL_PROOFS = "explicit_rule_force_full_proofs"
    FULL_FALLBACK_OBLIGATION = "full_fallback_obligation"
    FULL_PYTEST_FALLBACK_OBLIGATION = "full_pytest_fallback_obligation"
    FULL_PROOFS_FALLBACK_OBLIGATION = "full_proofs_fallback_obligation"
    POLICY_DISALLOWS_FALLBACK = "policy_disallows_fallback"
    MAX_SELECTED_TESTS_EXCEEDED = "max_selected_tests_exceeded"


TEST_SELECTION_INTERFACE: Final[str] = "TestSelection@1"
PROOF_SELECTION_INTERFACE: Final[str] = "ProofSelection@1"

_OPAQUE_CONFIDENCE: Final[frozenset[str]] = frozenset(
    {
        AnalysisConfidence.OPAQUE.value,
        AnalysisConfidence.HEURISTIC.value,
    }
)

# Relations walked when expanding the impact cone (reverse dependents).
_REVERSE_EXPAND_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        RelationType.CALLS.value,
        RelationType.IMPORTS.value,
        RelationType.INHERITS.value,
        RelationType.IMPLEMENTS.value,
        RelationType.READS_STATE.value,
        RelationType.WRITES_STATE.value,
        RelationType.GENERATED_FROM.value,
    }
)

_PROOF_RELATION: Final[str] = RelationType.PROOF_DEPENDS_ON.value

_ADAPTER_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        RelationType.SERIALIZES.value,
        RelationType.DESERIALIZES.value,
        RelationType.VALIDATES.value,
        RelationType.IMPLEMENTS.value,
    }
)

_NATIVE_OPAQUE_CODES: Final[frozenset[str]] = frozenset(
    {
        "native",
        "opaque",
        "native_extension",
        "opaque_native",
        "dynamic_import",
        "dynamic_plugin",
        "dynamic_pytest",
        "dynamic_dispatch",
        "monkey_patch",
        "uncontrolled_plugin",
    }
)

_FULL_PYTEST_REMEDIATIONS: Final[frozenset[str]] = frozenset(
    {
        SemanticRemediation.FULL_PYTEST_FALLBACK.value,
        SemanticRemediation.FULL_FALLBACK.value,
    }
)
_FULL_PROOFS_REMEDIATIONS: Final[frozenset[str]] = frozenset(
    {
        SemanticRemediation.FULL_PROOFS_FALLBACK.value,
        SemanticRemediation.FULL_FALLBACK.value,
    }
)

_PLUGIN_REASON_FRAGMENTS: Final[frozenset[str]] = frozenset(
    {
        "pytest_plugin",
        "dynamic_plugin",
        "uncontrolled_plugin",
        "pytest_plugins",
    }
)


@runtime_checkable
class SemanticIndexForSelection(Protocol):
    """Minimal ISI view usable as a selection graph source."""

    @property
    def symbols(self) -> Sequence[SymbolRecord]: ...

    @property
    def edges(self) -> Sequence[DependencyEdge]: ...


@dataclass(frozen=True, slots=True)
class _GraphEdge:
    """Normalized selection edge with optional semantic-link CID."""

    edge_id: str
    source_id: str
    target_id: str
    relation: str
    confidence: str
    link_cid: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass
class _SelectionGraph:
    symbols: dict[str, SymbolRecord]
    artifacts: dict[str, ArtifactRecord]
    edges_by_id: dict[str, _GraphEdge]
    outgoing: dict[str, list[_GraphEdge]]
    incoming: dict[str, list[_GraphEdge]]
    test_node_ids: dict[str, str]  # stable_id -> authoritative pytest node id
    proof_ids: set[str]
    limitations: tuple[AnalysisLimitation, ...] = ()

    def neighbors(
        self,
        node_id: str,
        *,
        direction: str = "both",
        relations: frozenset[str] | None = None,
    ) -> list[_GraphEdge]:
        items: list[_GraphEdge] = []
        if direction in {"both", "outgoing"}:
            items.extend(self.outgoing.get(node_id, ()))
        if direction in {"both", "incoming"}:
            items.extend(self.incoming.get(node_id, ()))
        if relations is not None:
            items = [edge for edge in items if edge.relation in relations]
        return items


def _as_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TestSelectionError(f"{name} must be a non-empty string")
    return value


def _load_json_block(view: SemanticStateView, cid: str) -> Mapping[str, object]:
    try:
        data = view.get_block(cid)
    except Exception as exc:
        raise TestSelectionError(f"missing block {cid}") from exc
    if type(data) is not bytes:
        raise TestSelectionError(f"block {cid} must be bytes")
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise TestSelectionError(f"block {cid} is not UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise TestSelectionError(f"block {cid} must be a JSON object")
    if canonical_dag_json_bytes(payload) != data:
        raise TestSelectionError(f"block {cid} is not canonical DAG-JSON")
    if cid_for_structured(payload) != cid:
        raise TestSelectionError(f"block CID {cid} does not reverify")
    return payload


def _optional_index_from_view(
    view: SemanticStateView | None,
) -> SemanticIndexForSelection | None:
    """Return a duck-typed index when the view already exposes symbols/edges."""
    if view is None:
        return None
    if hasattr(view, "symbols") and hasattr(view, "edges"):
        try:
            return RepositoryState(
                repository_id=view.root.repository_id,
                symbols=tuple(view.symbols),  # type: ignore[attr-defined]
                edges=tuple(view.edges),  # type: ignore[attr-defined]
                artifacts=tuple(getattr(view, "artifacts", ()) or ()),
            )
        except Exception as exc:
            raise TestSelectionError(
                "view symbols/edges could not be materialised as a RepositoryState"
            ) from exc
    return None


def _index_from_root_blocks(
    view: SemanticStateView,
) -> tuple[SemanticIndexForSelection, tuple[AnalysisLimitation, ...]] | None:
    """Load symbol facts and reconstruct edges from semantic links when present."""
    root = view.root
    if not isinstance(root, SemanticStateRoot):
        raise TestSelectionError("view.root must be a SemanticStateRoot")
    try:
        index_payload = _load_json_block(view, root.symbol_fact_index_cid)
        fact_index = SortedPairIndex.from_dict(
            {**index_payload, "index_cid": root.symbol_fact_index_cid}
        )
    except Exception:
        return None
    symbols: list[SymbolRecord] = []
    for _key, fact_cid in fact_index.pairs:
        try:
            payload = _load_json_block(view, fact_cid)
            fact = SymbolFactNode.from_dict({**payload, "fact_cid": fact_cid})
            symbols.append(fact.symbol)
        except Exception:
            # Sparse or partial stores are treated as unknown for this path.
            return None

    edges: list[DependencyEdge] = []
    try:
        link_index_payload = _load_json_block(view, root.semantic_link_index_cid)
        link_index = SortedPairIndex.from_dict(
            {**link_index_payload, "index_cid": root.semantic_link_index_cid}
        )
        for _edge_id, link_cid in link_index.pairs:
            payload = _load_json_block(view, link_cid)
            link = SemanticLinkNode.from_dict({**payload, "link_cid": link_cid})
            # Rebuild a DependencyEdge-shaped record for traversal.  source/target
            # IDs are stable IDs; edge_id is preserved via metadata for reasons.
            source = link.source_stable_id
            target = link.target_stable_id or f"unresolved:{link.edge_id}"
            edge = DependencyEdge(
                source,
                target,
                str(link.relation),
                link.extraction_method,
                str(link.confidence),
                link.extractor_version,
                link.source_span,
                {
                    **dict(link.metadata),
                    "isi_edge_id": link.edge_id,
                    "link_cid": link.link_cid,
                },
            )
            edges.append(edge)
    except Exception:
        edges = []

    artifacts: list[ArtifactRecord] = []
    try:
        art_index_payload = _load_json_block(view, root.artifact_fact_index_cid)
        art_index = SortedPairIndex.from_dict(
            {**art_index_payload, "index_cid": root.artifact_fact_index_cid}
        )
        for artifact_id, fact_cid in art_index.pairs:
            # Artifact facts are optional for selection; skip on failure.
            try:
                payload = _load_json_block(view, fact_cid)
                from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
                    ArtifactFactNode,
                )

                fact = ArtifactFactNode.from_dict({**payload, "fact_cid": fact_cid})
                artifacts.append(fact.artifact)
            except Exception:
                continue
            del artifact_id
    except Exception:
        artifacts = []

    limitations: list[AnalysisLimitation] = []
    try:
        lim_index_payload = _load_json_block(view, root.analysis_limitation_index_cid)
        lim_index = SortedPairIndex.from_dict(
            {**lim_index_payload, "index_cid": root.analysis_limitation_index_cid}
        )
        for _key, lim_cid in lim_index.pairs:
            try:
                payload = _load_json_block(view, lim_cid)
                limitations.append(
                    AnalysisLimitation.from_dict({**payload, "limitation_cid": lim_cid})
                )
            except Exception:
                continue
    except Exception:
        limitations = []

    state = RepositoryState(
        repository_id=root.repository_id,
        symbols=tuple(symbols),
        artifacts=tuple(artifacts),
        edges=tuple(edges),
    )
    return state, tuple(limitations)


def _authoritative_pytest_node_id(symbol: SymbolRecord) -> str | None:
    """Return an authoritative pytest node ID; never invent from non-test names.

    Accepted authorities, in order:
    1. Explicit ``pytest_node_id`` / ``nodeid`` / ``node_id`` metadata fields.
    2. Nested ``metadata["pytest"]`` projection carrying the same keys.
    3. For ``SymbolKind.TEST`` symbols that already carry pytest discovery
       evidence (``metadata["pytest"]`` or ``standalone_pytest``), the
       deterministic path-qualified projection
       ``{module_path}::{class::}*name`` derived from the symbol's own
       module path and qualified name.  This is the static analyzer's
       collection identity, not a free-form name guess.
    """
    if str(symbol.kind) != SymbolKind.TEST.value:
        # Non-tests may still carry an explicit node id when they *are* the
        # subject of an explicit selection rule or obligation that already
        # keyed the pytest domain.
        meta = dict(symbol.metadata or {})
        for key in ("pytest_node_id", "nodeid", "node_id"):
            value = meta.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    meta = dict(symbol.metadata or {})
    for key in ("pytest_node_id", "nodeid", "node_id"):
        value = meta.get(key)
        if isinstance(value, str) and value:
            return value

    pytest_proj = meta.get("pytest")
    if isinstance(pytest_proj, Mapping):
        for key in ("pytest_node_id", "nodeid", "node_id"):
            value = pytest_proj.get(key)
            if isinstance(value, str) and value:
                return value

    annotations = dict(symbol.annotations or {})
    pytest_ann = annotations.get("pytest")
    if isinstance(pytest_ann, Mapping):
        for key in ("pytest_node_id", "nodeid", "node_id"):
            value = pytest_ann.get(key)
            if isinstance(value, str) and value:
                return value

    # Deterministic projection only when pytest evidence is bound.
    if pytest_proj is None and not meta.get("standalone_pytest") and pytest_ann is None:
        # Still allow exact TEST symbols with module_path as authority when the
        # producer recorded them as tests — the kind itself is ISI evidence.
        # Without a module path we cannot form a node id.
        if not symbol.module_path:
            return None

    module_path = symbol.module_path.replace("\\", "/")
    if not module_path:
        return None
    qualified = symbol.qualified_name
    if not qualified:
        return None

    # Strip dotted module prefix derived from the path when present.
    module_qual = module_path[:-3] if module_path.endswith(".py") else module_path
    module_qual = module_qual.replace("/", ".")
    tail = qualified
    if tail.startswith(module_qual + "."):
        tail = tail[len(module_qual) + 1 :]
    elif "." in tail:
        # Keep only the trailing class/function path after the last module segment.
        # Prefer the segment after the module file stem.
        stem = module_qual.rsplit(".", 1)[-1]
        parts = tail.split(".")
        if stem in parts:
            idx = parts.index(stem)
            tail = ".".join(parts[idx + 1 :]) or parts[-1]
        else:
            tail = parts[-1]
    if not tail:
        return None
    return f"{module_path}::{tail.replace('.', '::')}"


def _is_test(symbol: SymbolRecord | None) -> bool:
    return symbol is not None and str(symbol.kind) == SymbolKind.TEST.value


def _is_fixture(symbol: SymbolRecord | None) -> bool:
    return symbol is not None and str(symbol.kind) == SymbolKind.FIXTURE.value


def _looks_like_pytest_node_id(value: str) -> bool:
    return "::" in value and not value.startswith("baguqeer")


def _is_proof_subject(
    subject_id: str,
    symbols: Mapping[str, SymbolRecord],
    edges: Iterable[_GraphEdge],
) -> bool:
    if subject_id in symbols:
        meta = dict(symbols[subject_id].metadata or {})
        if meta.get("proof") or meta.get("proof_obligation") or meta.get("is_proof"):
            return True
        kind = str(symbols[subject_id].kind)
        if kind == "proof" or meta.get("symbol_role") == "proof":
            return True
    for edge in edges:
        if edge.relation == _PROOF_RELATION and edge.source_id == subject_id:
            return True
    return False


def _graph_edge_from_dependency(edge: DependencyEdge) -> _GraphEdge:
    meta = dict(edge.metadata or {})
    edge_id = meta.get("isi_edge_id")
    if not isinstance(edge_id, str) or not edge_id:
        edge_id = edge.edge_id
    link_cid = meta.get("link_cid")
    if not isinstance(link_cid, str):
        link_cid = None
    return _GraphEdge(
        edge_id=edge_id,
        source_id=edge.source_id,
        target_id=edge.target_id,
        relation=str(edge.relation),
        confidence=str(edge.confidence),
        link_cid=link_cid,
        metadata=meta,
    )


def _merge_graphs(
    previous: SemanticIndexForSelection | None,
    current: SemanticIndexForSelection | None,
    *,
    limitations: Sequence[AnalysisLimitation] = (),
) -> _SelectionGraph:
    symbols: dict[str, SymbolRecord] = {}
    artifacts: dict[str, ArtifactRecord] = {}
    edges_by_id: dict[str, _GraphEdge] = {}
    outgoing: dict[str, list[_GraphEdge]] = {}
    incoming: dict[str, list[_GraphEdge]] = {}

    def ingest(index: SemanticIndexForSelection | None) -> None:
        if index is None:
            return
        for symbol in index.symbols:
            # Current wins on stable_id collisions so live identity is preferred.
            symbols[symbol.stable_id] = symbol
        for artifact in getattr(index, "artifacts", ()) or ():
            artifacts[artifact.artifact_id] = artifact
        for raw in index.edges:
            edge = _graph_edge_from_dependency(raw)
            edges_by_id[edge.edge_id] = edge
            outgoing.setdefault(edge.source_id, []).append(edge)
            incoming.setdefault(edge.target_id, []).append(edge)

    # Previous first so current overwrites; both retained for deletion evidence.
    ingest(previous)
    ingest(current)

    test_node_ids: dict[str, str] = {}
    for stable_id, symbol in symbols.items():
        node_id = _authoritative_pytest_node_id(symbol)
        if node_id is not None:
            test_node_ids[stable_id] = node_id

    proof_ids: set[str] = set()
    for edge in edges_by_id.values():
        if edge.relation == _PROOF_RELATION:
            proof_ids.add(edge.source_id)
    for stable_id, symbol in symbols.items():
        if _is_proof_subject(stable_id, symbols, edges_by_id.values()):
            proof_ids.add(stable_id)

    return _SelectionGraph(
        symbols=symbols,
        artifacts=artifacts,
        edges_by_id=edges_by_id,
        outgoing=outgoing,
        incoming=incoming,
        test_node_ids=test_node_ids,
        proof_ids=proof_ids,
        limitations=tuple(limitations),
    )


def _seed_subjects(
    invalidation: SemanticInvalidationPlan,
) -> tuple[tuple[str, ...], dict[str, SemanticInvalidationObligation]]:
    by_id: dict[str, SemanticInvalidationObligation] = {
        item.obligation_id: item for item in invalidation.obligations
    }
    seeds: list[str] = []
    seen: set[str] = set()
    for item in invalidation.obligations:
        for candidate in (item.subject_id, *item.supporting_edge_ids):
            # supporting_edge_ids are edge IDs, not subjects — only subject_id seeds.
            pass
        subject = item.subject_id
        if subject not in seen:
            seen.add(subject)
            seeds.append(subject)
        # Old/new identities can carry deleted/renamed subjects.
        for identity in (item.old_identity, item.new_identity):
            if identity and identity not in seen:
                # Identities may be version CIDs, not graph nodes; only keep
                # values that look like stable/node subjects later filtered.
                continue
        details = dict(item.details or {})
        for key in (
            "trigger_symbol_id",
            "trigger_binding_id",
            "binding_id",
            "related_subject_id",
        ):
            value = details.get(key)
            if isinstance(value, str) and value and value not in seen:
                seen.add(value)
                seeds.append(value)
    return tuple(seeds), by_id


def _obligation_forces_fallback(
    item: SemanticInvalidationObligation,
) -> tuple[bool, bool, str | None]:
    """Return ``(force_pytest, force_proofs, reason)`` for one obligation."""
    remediation = str(item.remediation_kind)
    reason_code = str(item.reason_code).lower()
    details = dict(item.details or {})
    detail_blob = " ".join(
        str(value).lower()
        for value in (
            reason_code,
            remediation,
            details.get("fallback_reason", ""),
            details.get("rule", ""),
            details.get("binding_kind", ""),
        )
    )

    force_pytest = remediation in _FULL_PYTEST_REMEDIATIONS
    force_proofs = remediation in _FULL_PROOFS_REMEDIATIONS

    if any(fragment in detail_blob for fragment in _PLUGIN_REASON_FRAGMENTS):
        force_pytest = True
        return True, force_proofs, SelectionFallbackReason.DYNAMIC_PYTEST_PLUGIN.value

    if remediation == SemanticRemediation.FULL_PYTEST_FALLBACK.value:
        return True, force_proofs, SelectionFallbackReason.FULL_PYTEST_FALLBACK_OBLIGATION.value
    if remediation == SemanticRemediation.FULL_PROOFS_FALLBACK.value:
        return force_pytest, True, SelectionFallbackReason.FULL_PROOFS_FALLBACK_OBLIGATION.value
    if remediation == SemanticRemediation.FULL_FALLBACK.value:
        return True, True, SelectionFallbackReason.FULL_FALLBACK_OBLIGATION.value

    if str(item.confidence) in _OPAQUE_CONFIDENCE and (
        "opaque" in detail_blob or "native" in detail_blob or "dynamic" in detail_blob
    ):
        return True, True, SelectionFallbackReason.NATIVE_OR_OPAQUE_REACHABILITY.value

    return force_pytest, force_proofs, None


def _edge_is_opaque_or_native(edge: _GraphEdge) -> bool:
    if edge.confidence in _OPAQUE_CONFIDENCE:
        return True
    meta = edge.metadata
    for key in ("native", "opaque", "dynamic", "confidence_reason", "resolution"):
        value = meta.get(key)
        if value is True:
            return True
        if isinstance(value, str) and value.lower() in _NATIVE_OPAQUE_CODES | {
            "unresolved",
            "opaque",
            "native",
            "dynamic",
        }:
            return True
    return False


def _expand_cone(
    graph: _SelectionGraph,
    seeds: Sequence[str],
) -> tuple[set[str], set[str], list[_GraphEdge]]:
    """Expand reverse-dependent cone; return (cone, opaque_hits, traversed)."""
    cone: set[str] = set()
    opaque_hits: set[str] = set()
    traversed: list[_GraphEdge] = []
    queue: deque[str] = deque()

    for seed in seeds:
        if seed not in cone:
            cone.add(seed)
            queue.append(seed)

    while queue:
        node = queue.popleft()
        # Reverse dependents: callers/importers/... that target this node.
        for edge in graph.neighbors(
            node, direction="incoming", relations=_REVERSE_EXPAND_RELATIONS
        ):
            if _edge_is_opaque_or_native(edge):
                opaque_hits.add(edge.edge_id)
            traversed.append(edge)
            if edge.source_id not in cone:
                cone.add(edge.source_id)
                queue.append(edge.source_id)
        # Also expand adapters that touch the node (either direction).
        for edge in graph.neighbors(node, direction="both", relations=_ADAPTER_RELATIONS):
            if _edge_is_opaque_or_native(edge):
                opaque_hits.add(edge.edge_id)
            traversed.append(edge)
            other = edge.target_id if edge.source_id == node else edge.source_id
            if other not in cone:
                cone.add(other)
                queue.append(other)
        # Generated artifacts: generated_from source depends on target input.
        for edge in graph.neighbors(
            node, direction="incoming", relations=frozenset({RelationType.GENERATED_FROM.value})
        ):
            if _edge_is_opaque_or_native(edge):
                opaque_hits.add(edge.edge_id)
            traversed.append(edge)
            if edge.source_id not in cone:
                cone.add(edge.source_id)
                queue.append(edge.source_id)

    return cone, opaque_hits, traversed


def _collect_tests_and_proofs(
    graph: _SelectionGraph,
    cone: set[str],
    *,
    include_fixtures: bool,
    include_proofs: bool,
) -> tuple[
    dict[str, list[tuple[str, _GraphEdge | None]]],
    dict[str, list[tuple[str, _GraphEdge | None]]],
    set[str],
]:
    """Map selected test node IDs and proof IDs to (seed, edge) reason crumbs.

    Returns
    -------
    selected_tests:
        pytest_node_id -> list of (seed_subject_id, edge_or_none)
    selected_proofs:
        proof_id -> list of (seed_subject_id, edge_or_none)
    opaque_edge_ids:
        edge IDs whose confidence/metadata force fallback visibility
    """
    selected_tests: dict[str, list[tuple[str, _GraphEdge | None]]] = {}
    selected_proofs: dict[str, list[tuple[str, _GraphEdge | None]]] = {}
    opaque: set[str] = set()

    def add_test(node_id: str, seed: str, edge: _GraphEdge | None) -> None:
        selected_tests.setdefault(node_id, []).append((seed, edge))

    def add_proof(proof_id: str, seed: str, edge: _GraphEdge | None) -> None:
        selected_proofs.setdefault(proof_id, []).append((seed, edge))

    for seed in sorted(cone):
        symbol = graph.symbols.get(seed)

        # Direct test seed.
        if _is_test(symbol):
            node_id = graph.test_node_ids.get(seed)
            if node_id is not None:
                add_test(node_id, seed, None)
            elif _looks_like_pytest_node_id(seed):
                add_test(seed, seed, None)

        # Direct proof seed.
        if include_proofs and seed in graph.proof_ids:
            add_proof(seed, seed, None)

        # Explicit pytest node id used as subject (rules / obligations).
        if _looks_like_pytest_node_id(seed):
            add_test(seed, seed, None)

        # Outgoing TESTED_BY: subject --tested_by--> test
        for edge in graph.neighbors(
            seed, direction="outgoing", relations=frozenset({RelationType.TESTED_BY.value})
        ):
            if _edge_is_opaque_or_native(edge):
                opaque.add(edge.edge_id)
            test_symbol = graph.symbols.get(edge.target_id)
            if _is_test(test_symbol) or edge.target_id in graph.test_node_ids:
                node_id = graph.test_node_ids.get(edge.target_id)
                if node_id is None and _looks_like_pytest_node_id(edge.target_id):
                    node_id = edge.target_id
                if node_id is not None:
                    add_test(node_id, seed, edge)

        # Incoming USES_FIXTURE: test --uses_fixture--> fixture/seed
        if include_fixtures:
            for edge in graph.neighbors(
                seed,
                direction="incoming",
                relations=frozenset({RelationType.USES_FIXTURE.value}),
            ):
                if _edge_is_opaque_or_native(edge):
                    opaque.add(edge.edge_id)
                test_symbol = graph.symbols.get(edge.source_id)
                if _is_test(test_symbol) or edge.source_id in graph.test_node_ids:
                    node_id = graph.test_node_ids.get(edge.source_id)
                    if node_id is None and _looks_like_pytest_node_id(edge.source_id):
                        node_id = edge.source_id
                    if node_id is not None:
                        add_test(node_id, seed, edge)

            # Fixture seed: also walk fixture dependency chain reverse.
            if _is_fixture(symbol):
                for edge in graph.neighbors(
                    seed,
                    direction="incoming",
                    relations=frozenset({RelationType.USES_FIXTURE.value}),
                ):
                    if _edge_is_opaque_or_native(edge):
                        opaque.add(edge.edge_id)
                    # Intermediate fixture consumers may themselves be fixtures.
                    mid = edge.source_id
                    if mid in graph.test_node_ids or _is_test(graph.symbols.get(mid)):
                        node_id = graph.test_node_ids.get(mid) or (
                            mid if _looks_like_pytest_node_id(mid) else None
                        )
                        if node_id is not None:
                            add_test(node_id, seed, edge)

        # Incoming CONFIGURED_BY: test --configured_by--> config seed
        for edge in graph.neighbors(
            seed,
            direction="incoming",
            relations=frozenset({RelationType.CONFIGURED_BY.value}),
        ):
            if _edge_is_opaque_or_native(edge):
                opaque.add(edge.edge_id)
            node_id = graph.test_node_ids.get(edge.source_id)
            if node_id is None and _looks_like_pytest_node_id(edge.source_id):
                node_id = edge.source_id
            if node_id is not None:
                add_test(node_id, seed, edge)

        # Adapter relations: tests that validate/serialize the cone subject.
        for edge in graph.neighbors(seed, direction="both", relations=_ADAPTER_RELATIONS):
            if _edge_is_opaque_or_native(edge):
                opaque.add(edge.edge_id)
            for candidate in (edge.source_id, edge.target_id):
                if candidate == seed:
                    continue
                if candidate in graph.test_node_ids or _is_test(graph.symbols.get(candidate)):
                    node_id = graph.test_node_ids.get(candidate)
                    if node_id is not None:
                        add_test(node_id, seed, edge)

        # Proofs depending on seed: proof --proof_depends_on--> seed
        if include_proofs:
            for edge in graph.neighbors(
                seed, direction="incoming", relations=frozenset({_PROOF_RELATION})
            ):
                if _edge_is_opaque_or_native(edge):
                    opaque.add(edge.edge_id)
                add_proof(edge.source_id, seed, edge)
            for edge in graph.neighbors(
                seed, direction="outgoing", relations=frozenset({_PROOF_RELATION})
            ):
                # seed is the proof itself
                if _edge_is_opaque_or_native(edge):
                    opaque.add(edge.edge_id)
                add_proof(edge.source_id, seed, edge)

    return selected_tests, selected_proofs, opaque


def shortest_reason_paths(
    graph: _SelectionGraph,
    *,
    seeds: Sequence[str],
    selected_tests: Mapping[str, Sequence[tuple[str, _GraphEdge | None]]],
    selected_proofs: Mapping[str, Sequence[tuple[str, _GraphEdge | None]]],
) -> tuple[ReasonPath, ...]:
    """Build sorted shortest reason paths for every selected target.

    Each path binds the seed subject, target node/proof id, producer edge IDs,
    optional semantic-link CIDs, and relation steps.  When only a direct seed
    match exists (no edge), the path has empty edge/link sequences.
    """
    paths: list[ReasonPath] = []
    seen: set[str] = set()

    def emit(
        seed: str,
        target: str,
        edge: _GraphEdge | None,
        *,
        relation_hint: str | None = None,
    ) -> None:
        if edge is None:
            path = ReasonPath(
                seed_subject_id=seed,
                target_node_id=target,
                edge_ids=(),
                link_cids=(),
                relation_steps=() if relation_hint is None else (relation_hint,),
            )
        else:
            link_cids = (edge.link_cid,) if edge.link_cid else ()
            path = ReasonPath(
                seed_subject_id=seed,
                target_node_id=target,
                edge_ids=(edge.edge_id,),
                link_cids=link_cids,
                relation_steps=(edge.relation,),
            )
        if path.path_cid not in seen:
            seen.add(path.path_cid)
            paths.append(path)

    # Prefer shortest: direct edge crumbs already are length 0/1.  For multi-hop
    # cone members without a direct attach edge, BFS once per seed→target pair.
    attach_edges: dict[tuple[str, str], _GraphEdge] = {}
    for node_id, crumbs in selected_tests.items():
        for seed, edge in crumbs:
            if edge is not None:
                attach_edges[(seed, node_id)] = edge
            emit(seed, node_id, edge)

    for proof_id, crumbs in selected_proofs.items():
        for seed, edge in crumbs:
            if edge is not None:
                attach_edges[(seed, proof_id)] = edge
            emit(seed, proof_id, edge)

    # Multi-hop: for seeds that selected a target only after cone expansion,
    # record a shortest path through reverse-expand relations when no direct
    # attach edge was stored for that seed/target pair.
    def bfs_path(start: str, goal_nodes: set[str]) -> dict[str, list[_GraphEdge]]:
        if start in goal_nodes:
            return {start: []}
        parent: dict[str, tuple[str, _GraphEdge] | None] = {start: None}
        queue: deque[str] = deque([start])
        found: dict[str, list[_GraphEdge]] = {}
        while queue:
            node = queue.popleft()
            for edge in graph.neighbors(
                node, direction="incoming", relations=_REVERSE_EXPAND_RELATIONS
            ):
                nxt = edge.source_id
                if nxt in parent:
                    continue
                parent[nxt] = (node, edge)
                if nxt in goal_nodes:
                    # reconstruct
                    chain: list[_GraphEdge] = []
                    cur = nxt
                    while parent[cur] is not None:
                        prev, used = parent[cur]  # type: ignore[misc]
                        chain.append(used)
                        cur = prev
                    chain.reverse()
                    found[nxt] = chain
                queue.append(nxt)
            if len(found) == len(goal_nodes):
                break
        return found

    # Only add multi-hop paths when a selected target has no path yet from a
    # cone seed that is not the target itself.
    targets_needing_paths = {
        node_id
        for node_id, crumbs in selected_tests.items()
        if all(edge is None and seed == node_id for seed, edge in crumbs)
    }
    # Map node_id back to stable ids for BFS goals.
    node_to_stables: dict[str, set[str]] = {}
    for stable_id, node_id in graph.test_node_ids.items():
        node_to_stables.setdefault(node_id, set()).add(stable_id)

    for seed in seeds:
        if not targets_needing_paths:
            break
        goal_stables: set[str] = set()
        for node_id in targets_needing_paths:
            goal_stables |= node_to_stables.get(node_id, set())
        if not goal_stables:
            continue
        found = bfs_path(seed, goal_stables)
        for stable_id, chain in found.items():
            node_id = graph.test_node_ids.get(stable_id)
            if node_id is None:
                continue
            if (seed, node_id) in attach_edges:
                continue
            if not chain:
                continue
            link_cids = tuple(edge.link_cid for edge in chain if edge.link_cid)
            path = ReasonPath(
                seed_subject_id=seed,
                target_node_id=node_id,
                edge_ids=tuple(edge.edge_id for edge in chain),
                link_cids=link_cids,
                relation_steps=tuple(edge.relation for edge in chain),
            )
            if path.path_cid not in seen:
                seen.add(path.path_cid)
                paths.append(path)

    return tuple(sorted(paths, key=lambda item: item.path_cid))


def _combine_fallback(pytest_fb: bool, proofs_fb: bool) -> SelectionFallback:
    if pytest_fb and proofs_fb:
        return SelectionFallback.BOTH
    if pytest_fb:
        return SelectionFallback.FULL_PYTEST
    if proofs_fb:
        return SelectionFallback.FULL_PROOFS
    return SelectionFallback.NONE


def _universe_cid(node_ids: Sequence[str]) -> str | None:
    if not node_ids:
        return None
    return cid_for_structured(
        {
            "schema": "ipfs-datasets.software-contracts.known-test-universe@1",
            "pytest_node_ids": list(node_ids),
        }
    )


def _limitations_force_fallback(
    limitations: Sequence[AnalysisLimitation],
    cone: set[str],
) -> tuple[bool, str | None]:
    for item in limitations:
        code = str(item.code).lower()
        conf = str(item.confidence)
        subject = item.subject_id
        intersects = subject is None or subject in cone
        if not intersects:
            continue
        if code in _NATIVE_OPAQUE_CODES or conf in _OPAQUE_CONFIDENCE:
            if any(
                token in code
                for token in ("native", "opaque", "dynamic", "plugin", "monkey")
            ) or conf == AnalysisConfidence.OPAQUE.value:
                return True, SelectionFallbackReason.NATIVE_OR_OPAQUE_REACHABILITY.value
    return False, None


def select_tests_and_proofs(
    previous_state: SemanticStateView | None,
    current_state: SemanticStateView,
    invalidation: SemanticInvalidationPlan,
    *,
    policy: SelectionPolicy,
    explicit_rules: Sequence[SelectionRule] = (),
    previous_index: SemanticIndexForSelection | RepositoryState | None = None,
    current_index: SemanticIndexForSelection | RepositoryState | None = None,
) -> TestSelection:
    """Select affected pytest node IDs and proof IDs from pure graph evidence.

    Parameters
    ----------
    previous_state, current_state:
        Semantic-state views bound to previous/current roots.  ``previous_state``
        may be ``None`` for the first known state.  Views may expose ``symbols``
        and ``edges`` directly (test and cold-path convenience) or provide
        content-addressed fact/link indexes via ``get_block``.
    invalidation:
        Additive invalidation plan whose obligations seed selection.
    policy:
        Closed :class:`SelectionPolicy` controlling proofs, fixtures, caps, and
        whether full fallback is permitted.
    explicit_rules:
        Optional include/exclude/force-full rules applied after graph seeds.
    previous_index, current_index:
        Optional already-materialised ISI graphs.  When omitted, graphs are
        recovered from the views (duck-typed attributes or root indexes).
    """
    if not isinstance(current_state, SemanticStateView) and not (
        hasattr(current_state, "root") and hasattr(current_state, "get_block")
    ):
        raise TestSelectionError("current_state must be a SemanticStateView")
    if previous_state is not None and not (
        isinstance(previous_state, SemanticStateView)
        or (hasattr(previous_state, "root") and hasattr(previous_state, "get_block"))
    ):
        raise TestSelectionError("previous_state must be a SemanticStateView or None")
    if not isinstance(invalidation, SemanticInvalidationPlan):
        raise TestSelectionError("invalidation must be a SemanticInvalidationPlan")
    if not isinstance(policy, SelectionPolicy):
        raise TestSelectionError("policy must be a SelectionPolicy")
    if any(not isinstance(rule, SelectionRule) for rule in explicit_rules):
        raise TestSelectionError("explicit_rules must be SelectionRule values")

    current_root = current_state.root
    if not isinstance(current_root, SemanticStateRoot):
        raise TestSelectionError("current_state.root must be a SemanticStateRoot")
    previous_root_cid: str | None = None
    if previous_state is not None:
        previous_root = previous_state.root
        if not isinstance(previous_root, SemanticStateRoot):
            raise TestSelectionError("previous_state.root must be a SemanticStateRoot")
        previous_root_cid = previous_root.root_cid
        if previous_root.repository_id != current_root.repository_id:
            raise TestSelectionError(
                "previous and current roots must share repository_id"
            )

    if invalidation.current_root_cid != current_root.root_cid:
        raise TestSelectionError(
            "invalidation.current_root_cid must match current_state.root.root_cid"
        )
    if (
        previous_root_cid is not None
        and invalidation.previous_root_cid is not None
        and invalidation.previous_root_cid != previous_root_cid
    ):
        raise TestSelectionError(
            "invalidation.previous_root_cid must match previous_state.root.root_cid"
        )

    # Materialise graphs: explicit indexes win, then view attributes, then blocks.
    prev_idx = previous_index or _optional_index_from_view(previous_state)
    curr_idx = current_index or _optional_index_from_view(current_state)
    limitations: list[AnalysisLimitation] = []
    if curr_idx is None:
        loaded = _index_from_root_blocks(current_state)
        if loaded is not None:
            curr_idx, loaded_limits = loaded
            limitations.extend(loaded_limits)
    if prev_idx is None and previous_state is not None:
        loaded_prev = _index_from_root_blocks(previous_state)
        if loaded_prev is not None:
            prev_idx, loaded_prev_limits = loaded_prev
            limitations.extend(loaded_prev_limits)

    graph = _merge_graphs(prev_idx, curr_idx, limitations=limitations)

    universe_ids = tuple(sorted(set(graph.test_node_ids.values())))
    universe_cid = _universe_cid(universe_ids)
    universe_count = len(universe_ids)
    unknown_universe = universe_count == 0

    seeds, _obligations_by_id = _seed_subjects(invalidation)

    force_pytest = False
    force_proofs = False
    fallback_reasons: set[str] = set()
    covered: set[str] = set()
    unresolved: set[str] = set()

    for obligation in invalidation.obligations:
        pytest_fb, proofs_fb, reason = _obligation_forces_fallback(obligation)
        if pytest_fb or proofs_fb:
            force_pytest = force_pytest or pytest_fb
            force_proofs = force_proofs or proofs_fb
            if reason:
                fallback_reasons.add(reason)
            covered.add(obligation.obligation_id)

    # Explicit force-full rules.
    include_subjects: set[str] = set()
    exclude_subjects: set[str] = set()
    for rule in explicit_rules:
        kind = str(rule.kind)
        if kind == SelectionRuleKind.FORCE_FULL.value:
            force_pytest = True
            force_proofs = True
            fallback_reasons.add(SelectionFallbackReason.EXPLICIT_RULE_FORCE_FULL.value)
        elif kind == SelectionRuleKind.FORCE_FULL_PYTEST.value:
            force_pytest = True
            fallback_reasons.add(
                SelectionFallbackReason.EXPLICIT_RULE_FORCE_FULL_PYTEST.value
            )
        elif kind == SelectionRuleKind.FORCE_FULL_PROOFS.value:
            force_proofs = True
            fallback_reasons.add(
                SelectionFallbackReason.EXPLICIT_RULE_FORCE_FULL_PROOFS.value
            )
        elif kind == SelectionRuleKind.INCLUDE.value:
            include_subjects.update(rule.subjects)
        elif kind == SelectionRuleKind.EXCLUDE.value:
            exclude_subjects.update(rule.subjects)

    if unknown_universe:
        force_pytest = True
        fallback_reasons.add(SelectionFallbackReason.UNKNOWN_TEST_UNIVERSE.value)

    cone, opaque_from_expand, _traversed = _expand_cone(graph, seeds)
    # Include subjects also count as seeds for expansion.
    if include_subjects:
        extra_cone, extra_opaque, _ = _expand_cone(graph, sorted(include_subjects))
        cone |= extra_cone
        opaque_from_expand |= extra_opaque

    lim_force, lim_reason = _limitations_force_fallback(graph.limitations, cone)
    if lim_force:
        force_pytest = True
        force_proofs = True
        if lim_reason:
            fallback_reasons.add(lim_reason)

    selected_tests, selected_proofs, opaque_from_attach = _collect_tests_and_proofs(
        graph,
        cone,
        include_fixtures=policy.include_fixtures,
        include_proofs=policy.include_proofs,
    )

    # Apply explicit include subjects directly.
    for subject in sorted(include_subjects):
        if subject in graph.test_node_ids:
            selected_tests.setdefault(graph.test_node_ids[subject], []).append(
                (subject, None)
            )
        elif _looks_like_pytest_node_id(subject):
            selected_tests.setdefault(subject, []).append((subject, None))
        elif subject in graph.proof_ids or _is_proof_subject(
            subject, graph.symbols, graph.edges_by_id.values()
        ):
            if policy.include_proofs:
                selected_proofs.setdefault(subject, []).append((subject, None))
        else:
            # Include of unknown subject is insufficient evidence if no graph hit.
            unresolved.add(subject)

    # Apply excludes.
    for subject in exclude_subjects:
        if _looks_like_pytest_node_id(subject):
            selected_tests.pop(subject, None)
        if subject in graph.test_node_ids:
            selected_tests.pop(graph.test_node_ids[subject], None)
        selected_proofs.pop(subject, None)
        # Also exclude by stable id match against node values.
        for node_id, crumbs in list(selected_tests.items()):
            if any(seed == subject for seed, _edge in crumbs):
                # Only drop when the subject itself is the test stable id.
                if subject in graph.test_node_ids and graph.test_node_ids[subject] == node_id:
                    selected_tests.pop(node_id, None)

    opaque_edges = opaque_from_expand | opaque_from_attach
    if opaque_edges and cone:
        # Opaque/native evidence intersecting the cone forces visible fallback.
        force_pytest = True
        force_proofs = True
        fallback_reasons.add(
            SelectionFallbackReason.NATIVE_OR_OPAQUE_REACHABILITY.value
        )

    # Covered / unresolved obligations relative to selection results.
    selected_stable_tests = {
        stable
        for stable, node_id in graph.test_node_ids.items()
        if node_id in selected_tests
    }
    selected_node_set = set(selected_tests)
    selected_proof_set = set(selected_proofs)

    for obligation in invalidation.obligations:
        oid = obligation.obligation_id
        subject = obligation.subject_id
        if oid in covered:
            continue
        resolved = False
        if subject in selected_stable_tests or subject in selected_node_set:
            resolved = True
        elif subject in selected_proof_set:
            resolved = True
        elif subject in cone and (
            subject in graph.test_node_ids
            or subject in graph.proof_ids
            or _is_test(graph.symbols.get(subject))
        ):
            resolved = True
        else:
            # Any selected target whose reason seed equals this subject.
            if any(
                any(seed == subject for seed, _ in crumbs)
                for crumbs in selected_tests.values()
            ):
                resolved = True
            if any(
                any(seed == subject for seed, _ in crumbs)
                for crumbs in selected_proofs.values()
            ):
                resolved = True
        # Binding-only subjects that only force stale receipts without derivatives
        # remain unresolved when nothing selectable was reached.
        if resolved:
            covered.add(oid)
        else:
            # Fallback-already-required obligations count as covered above.
            if subject in cone and not selected_tests and not selected_proofs:
                # Cone membership without selectable derivatives → insufficient.
                unresolved.add(oid)
                fallback_reasons.add(
                    SelectionFallbackReason.INSUFFICIENT_GRAPH_EVIDENCE.value
                )
                force_pytest = True
                if policy.include_proofs:
                    force_proofs = True
            elif subject not in graph.symbols and subject not in graph.artifacts and (
                not _looks_like_pytest_node_id(subject)
            ):
                unresolved.add(oid)
            else:
                # Subject known but no test/proof derivative — still unresolved
                # unless remediation was non-selection work (review/rebuild).
                remediation = str(obligation.remediation_kind)
                if remediation in {
                    SemanticRemediation.RERUN_TEST.value,
                    SemanticRemediation.RERUN_PROOF.value,
                    SemanticRemediation.STALE_BOUND_RECEIPTS.value,
                    SemanticRemediation.STALE_BOUND_CAPSULES.value,
                }:
                    unresolved.add(oid)
                    if not selected_tests and not selected_proofs:
                        fallback_reasons.add(
                            SelectionFallbackReason.INSUFFICIENT_GRAPH_EVIDENCE.value
                        )
                        if remediation in {
                            SemanticRemediation.RERUN_TEST.value,
                            SemanticRemediation.STALE_BOUND_RECEIPTS.value,
                            SemanticRemediation.STALE_BOUND_CAPSULES.value,
                        }:
                            force_pytest = True
                        if remediation == SemanticRemediation.RERUN_PROOF.value:
                            force_proofs = True
                else:
                    # Non-selection remediations (review/rebuild/raw source) are
                    # covered as acknowledged without test selection.
                    covered.add(oid)

    # Empty seeds with no rules → empty selection is fine (none fallback).
    if (
        seeds
        and not selected_tests
        and not selected_proofs
        and not force_pytest
        and not force_proofs
    ):
        # Seeds present but nothing selectable → insufficient evidence.
        force_pytest = True
        if policy.include_proofs:
            force_proofs = True
        fallback_reasons.add(SelectionFallbackReason.INSUFFICIENT_GRAPH_EVIDENCE.value)

    # Cap enforcement.
    ordered_tests = tuple(sorted(selected_tests))
    ordered_proofs = tuple(sorted(selected_proofs)) if policy.include_proofs else ()
    if (
        policy.max_selected_tests is not None
        and len(ordered_tests) > policy.max_selected_tests
    ):
        force_pytest = True
        fallback_reasons.add(SelectionFallbackReason.MAX_SELECTED_TESTS_EXCEEDED.value)
        ordered_tests = ()

    fallback = _combine_fallback(force_pytest, force_proofs)

    if fallback != SelectionFallback.NONE and not policy.allow_full_fallback:
        raise TestSelectionError(
            f"{SelectionFallbackReason.POLICY_DISALLOWS_FALLBACK.value}: "
            f"selection requires {fallback.value} but policy.allow_full_fallback is false"
        )

    # On domain-wide fallback, clear the corresponding selection lists so the
    # fallback flag is the authoritative signal (accelerate runs the full set).
    if fallback in {SelectionFallback.FULL_PYTEST, SelectionFallback.BOTH}:
        ordered_tests = ()
        # Paths for cleared tests are dropped below.
        selected_tests = {}
    if fallback in {SelectionFallback.FULL_PROOFS, SelectionFallback.BOTH}:
        ordered_proofs = ()
        selected_proofs = {}

    paths = shortest_reason_paths(
        graph,
        seeds=seeds,
        selected_tests=selected_tests,
        selected_proofs=selected_proofs,
    )
    # Drop paths whose targets were cleared by fallback.
    if fallback != SelectionFallback.NONE:
        allowed_targets = set(ordered_tests) | set(ordered_proofs)
        paths = tuple(
            path for path in paths if path.target_node_id in allowed_targets
        )

    # Seed list reported via covered obligations; also treat include-only work.
    covered_ids = tuple(sorted(covered))
    unresolved_ids = tuple(sorted(unresolved - covered))

    return TestSelection(
        previous_root_cid=previous_root_cid,
        current_root_cid=current_root.root_cid,
        selected_pytest_node_ids=ordered_tests,
        selected_proof_ids=ordered_proofs,
        reason_paths=paths,
        covered_seed_obligation_ids=covered_ids,
        unresolved_obligation_ids=unresolved_ids,
        known_test_universe_cid=universe_cid,
        known_test_universe_count=universe_count,
        fallback=fallback,
        fallback_reasons=tuple(sorted(fallback_reasons)),
        policy_cid=policy.policy_cid,
    )


__all__ = [
    "PROOF_SELECTION_INTERFACE",
    "TEST_SELECTION_INTERFACE",
    "SelectionFallbackReason",
    "SemanticIndexForSelection",
    "TestSelectionError",
    "select_tests_and_proofs",
    "shortest_reason_paths",
]
