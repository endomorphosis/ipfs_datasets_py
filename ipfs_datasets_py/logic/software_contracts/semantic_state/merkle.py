"""Acyclic symbol-level Merkle DAG materialization (DSS-003).

This module is the sole owner of the ``SymbolMerkleDag@1`` interface.  It
consumes only a sealed, already-resolved incremental-semantic-index (ISI) view
and an already-compiled capsule index.  It does not rescan, parse, resolve, or
manufacture targets, and it never compiles capsules.

Layering that keeps content identity acyclic even when the domain graph has
cycles (recursive calls, mutual imports, inheritance):

* ``SymbolFactNode`` / ``ArtifactFactNode`` bind producer records (leaves).
* ``SemanticLinkNode`` references **fact CIDs only** (never symbol-node or
  capsule CIDs) and preserves the authoritative ISI ``edge_id`` verbatim.
* ``SymbolMerkleNode`` references fact CIDs, link CIDs, and capsule CIDs.
* Capsules (compiled elsewhere) reference dependency fact/link IDs, never
  dependency capsule or symbol-node CIDs.

Compilation is order-independent: inputs are sorted by stable logical keys
before emission.  Every emitted fact/link/node/index block is stored under its
content-addressed CID and can be fully re-verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
    validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    DependencyEdge,
    RepositoryState,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    MERKLE_COMPILER_VERSION,
    ArtifactFactNode,
    LinkTargetKind,
    SemanticLinkNode,
    SemanticStateModelError,
    SortedPairIndex,
    SymbolFactNode,
    SymbolMerkleNode,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

SYMBOL_MERKLE_DAG_INTERFACE: Final[str] = "SymbolMerkleDag@1"
SYMBOL_MERKLE_DAG_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.symbol-merkle-dag@1"
)


class MerkleCompilerError(SemanticStateModelError):
    """Raised when Merkle DAG materialization inputs or outputs are invalid."""


# ---------------------------------------------------------------------------
# Intermediate compile results
# ---------------------------------------------------------------------------


def _freeze_blocks(blocks: Mapping[str, bytes]) -> Mapping[str, bytes]:
    if not isinstance(blocks, Mapping):
        raise MerkleCompilerError("blocks must be a mapping")
    verified: dict[str, bytes] = {}
    for key, data in blocks.items():
        try:
            cid = validate_cid(key)
        except Exception as exc:
            raise MerkleCompilerError(f"block key must be a valid CID: {key!r}") from exc
        if type(data) is not bytes:
            raise MerkleCompilerError(f"block {cid} data must be bytes")
        if cid in verified and verified[cid] != data:
            raise MerkleCompilerError(f"conflicting block bytes for CID {cid}")
        # Recompute structured CID from payload bytes.
        try:
            import json

            payload = json.loads(data.decode("utf-8"))
        except Exception as exc:
            raise MerkleCompilerError(
                f"block {cid} is not UTF-8 DAG-JSON"
            ) from exc
        if canonical_dag_json_bytes(payload) != data:
            raise MerkleCompilerError(f"block {cid} is not canonical DAG-JSON")
        recomputed = cid_for_structured(payload)
        if recomputed != cid:
            raise MerkleCompilerError(
                f"block CID {cid} does not reverify (got {recomputed})"
            )
        verified[cid] = data
    return MappingProxyType(dict(sorted(verified.items())))


def _record_block(identity_payload: Mapping[str, Any], claimed_cid: str) -> tuple[str, bytes]:
    """Return ``(cid, canonical_bytes)`` for one identity payload."""
    data = canonical_dag_json_bytes(dict(identity_payload))
    recomputed = cid_for_structured(dict(identity_payload))
    if recomputed != claimed_cid:
        raise MerkleCompilerError(
            f"claimed CID {claimed_cid} does not match identity payload {recomputed}"
        )
    return recomputed, data


def _merge_blocks(*maps: Mapping[str, bytes]) -> dict[str, bytes]:
    merged: dict[str, bytes] = {}
    for mapping in maps:
        for cid, data in mapping.items():
            if cid in merged and merged[cid] != data:
                raise MerkleCompilerError(f"conflicting block bytes for CID {cid}")
            merged[cid] = data
    return merged


def _as_capsule_pairs(
    capsule_index: SortedPairIndex | Mapping[str, str] | Sequence[Sequence[str]],
) -> tuple[tuple[str, str], ...]:
    """Normalize a capsule index to sorted ``(stable_symbol_id, capsule_cid)`` pairs."""
    if isinstance(capsule_index, SortedPairIndex):
        pairs = [(key, cid) for key, cid in capsule_index.pairs]
    elif isinstance(capsule_index, Mapping):
        pairs = [(str(key), str(value)) for key, value in capsule_index.items()]
    else:
        pairs = []
        for item in capsule_index:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise MerkleCompilerError(
                    "capsule_index pairs must be [stable_symbol_id, capsule_cid]"
                )
            pairs.append((str(item[0]), str(item[1])))
    # Validate via SortedPairIndex (sorts, rejects duplicates, validates CIDs).
    index = SortedPairIndex(pairs=pairs)
    return tuple(index.pairs)


def _raw_source_reasons(confidence: str) -> tuple[str, ...]:
    """Derive bounded raw-source-required reasons from producer confidence."""
    if confidence == AnalysisConfidence.OPAQUE.value:
        return ("opaque_confidence",)
    if confidence == AnalysisConfidence.HEURISTIC.value:
        return ("heuristic_confidence",)
    return ()


# ---------------------------------------------------------------------------
# Compile stages
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FactCompileResult:
    """Compiled fact nodes plus their sorted index and content-addressed blocks."""

    facts: tuple[Any, ...]
    index: SortedPairIndex
    blocks: Mapping[str, bytes]


def compile_symbol_facts(
    symbols: Iterable[SymbolRecord],
) -> FactCompileResult:
    """Compile deterministic ``SymbolFactNode`` records from ISI symbols.

    Output order and index keys are ``stable_symbol_id``; duplicate stable IDs
    fail closed.  Input iteration order has no effect on emitted CIDs.
    """
    items = list(symbols)
    if any(not isinstance(item, SymbolRecord) for item in items):
        raise MerkleCompilerError("symbols must be SymbolRecord values")
    ordered = sorted(items, key=lambda item: item.stable_id)
    if len({item.stable_id for item in ordered}) != len(ordered):
        raise MerkleCompilerError("symbols must not contain duplicate stable_id values")

    facts: list[SymbolFactNode] = []
    pairs: list[tuple[str, str]] = []
    blocks: dict[str, bytes] = {}
    for symbol in ordered:
        fact = SymbolFactNode(symbol=symbol)
        cid, data = _record_block(fact.identity_payload(), fact.fact_cid)
        facts.append(fact)
        pairs.append((fact.stable_symbol_id, cid))
        blocks[cid] = data

    index = SortedPairIndex(pairs=pairs)
    index_cid, index_data = _record_block(index.identity_payload(), index.index_cid)
    blocks[index_cid] = index_data
    return FactCompileResult(
        facts=tuple(facts),
        index=index,
        blocks=_freeze_blocks(blocks),
    )


def compile_artifact_facts(
    artifacts: Iterable[ArtifactRecord],
) -> FactCompileResult:
    """Compile deterministic ``ArtifactFactNode`` records from ISI artifacts."""
    items = list(artifacts)
    if any(not isinstance(item, ArtifactRecord) for item in items):
        raise MerkleCompilerError("artifacts must be ArtifactRecord values")
    ordered = sorted(items, key=lambda item: item.artifact_id)
    if len({item.artifact_id for item in ordered}) != len(ordered):
        raise MerkleCompilerError(
            "artifacts must not contain duplicate artifact_id values"
        )

    facts: list[ArtifactFactNode] = []
    pairs: list[tuple[str, str]] = []
    blocks: dict[str, bytes] = {}
    for artifact in ordered:
        fact = ArtifactFactNode(artifact=artifact)
        cid, data = _record_block(fact.identity_payload(), fact.fact_cid)
        facts.append(fact)
        pairs.append((fact.artifact_id, cid))
        blocks[cid] = data

    index = SortedPairIndex(pairs=pairs)
    index_cid, index_data = _record_block(index.identity_payload(), index.index_cid)
    blocks[index_cid] = index_data
    return FactCompileResult(
        facts=tuple(facts),
        index=index,
        blocks=_freeze_blocks(blocks),
    )


@dataclass(frozen=True, slots=True)
class LinkCompileResult:
    """Compiled semantic links plus sorted index and blocks."""

    links: tuple[SemanticLinkNode, ...]
    index: SortedPairIndex
    blocks: Mapping[str, bytes]


def _classify_target(
    target_id: str,
    symbol_by_id: Mapping[str, SymbolFactNode],
    artifact_by_id: Mapping[str, ArtifactFactNode],
) -> tuple[str, str | None, str | None, str | None]:
    """Return ``(target_kind, target_stable_id, target_version_cid, target_fact_cid)``.

    Does not invent targets: membership is decided solely by the sealed fact
    inventories supplied to the compiler.
    """
    if target_id in symbol_by_id:
        fact = symbol_by_id[target_id]
        return (
            LinkTargetKind.SYMBOL.value,
            fact.stable_symbol_id,
            fact.version_cid,
            fact.fact_cid,
        )
    if target_id in artifact_by_id:
        fact = artifact_by_id[target_id]
        return (
            LinkTargetKind.ARTIFACT.value,
            fact.artifact_id,
            None,
            fact.fact_cid,
        )
    return (LinkTargetKind.UNRESOLVED.value, None, None, None)


def compile_semantic_links(
    edges: Iterable[DependencyEdge],
    *,
    symbol_facts: Sequence[SymbolFactNode],
    artifact_facts: Sequence[ArtifactFactNode] = (),
) -> LinkCompileResult:
    """Wrap ISI edges as ``SemanticLinkNode`` values referencing **fact CIDs only**.

    Preserves producer ``edge_id``, relation, source span, extraction method,
    confidence, extractor version, metadata, and unresolved targets.  Unknown
    source symbols fail closed.  Links never reference symbol-node or capsule
    CIDs, so domain cycles cannot form content-identity cycles.
    """
    if any(not isinstance(item, SymbolFactNode) for item in symbol_facts):
        raise MerkleCompilerError("symbol_facts must be SymbolFactNode values")
    if any(not isinstance(item, ArtifactFactNode) for item in artifact_facts):
        raise MerkleCompilerError("artifact_facts must be ArtifactFactNode values")

    symbol_by_id = {fact.stable_symbol_id: fact for fact in symbol_facts}
    if len(symbol_by_id) != len(symbol_facts):
        raise MerkleCompilerError("symbol_facts must not contain duplicate stable IDs")
    artifact_by_id = {fact.artifact_id: fact for fact in artifact_facts}
    if len(artifact_by_id) != len(artifact_facts):
        raise MerkleCompilerError(
            "artifact_facts must not contain duplicate artifact IDs"
        )

    edge_items = list(edges)
    if any(not isinstance(item, DependencyEdge) for item in edge_items):
        raise MerkleCompilerError("edges must be DependencyEdge values")
    ordered = sorted(edge_items, key=lambda item: item.edge_id)
    if len({item.edge_id for item in ordered}) != len(ordered):
        raise MerkleCompilerError("edges must not contain duplicate edge_id values")

    links: list[SemanticLinkNode] = []
    pairs: list[tuple[str, str]] = []
    blocks: dict[str, bytes] = {}
    for edge in ordered:
        source = symbol_by_id.get(edge.source_id)
        if source is None:
            raise MerkleCompilerError(
                f"edge {edge.edge_id} source_id {edge.source_id!r} is not a known symbol"
            )
        target_kind, target_stable_id, target_version_cid, target_fact_cid = (
            _classify_target(edge.target_id, symbol_by_id, artifact_by_id)
        )
        # Metadata is preserved verbatim from the producer edge (already closed).
        metadata = dict(edge.metadata) if edge.metadata else {}
        link = SemanticLinkNode(
            edge_id=edge.edge_id,
            source_stable_id=source.stable_symbol_id,
            source_version_cid=source.version_cid,
            source_fact_cid=source.fact_cid,
            target_kind=target_kind,
            target_stable_id=target_stable_id,
            target_version_cid=target_version_cid,
            target_fact_cid=target_fact_cid,
            relation=edge.relation,
            source_span=edge.span,
            extraction_method=edge.extraction_method,
            confidence=edge.confidence,
            extractor_version=edge.extractor_version,
            metadata=metadata,
        )
        # Authoritative edge_id must be preserved verbatim (no re-derivation).
        if link.edge_id != edge.edge_id:
            raise MerkleCompilerError(
                "SemanticLinkNode edge_id must equal DependencyEdge.edge_id verbatim"
            )
        cid, data = _record_block(link.identity_payload(), link.link_cid)
        links.append(link)
        pairs.append((link.edge_id, cid))
        blocks[cid] = data

    index = SortedPairIndex(pairs=pairs)
    index_cid, index_data = _record_block(index.identity_payload(), index.index_cid)
    blocks[index_cid] = index_data
    return LinkCompileResult(
        links=tuple(links),
        index=index,
        blocks=_freeze_blocks(blocks),
    )


@dataclass(frozen=True, slots=True)
class NodeCompileResult:
    """Compiled symbol Merkle nodes plus sorted index and blocks."""

    nodes: tuple[SymbolMerkleNode, ...]
    index: SortedPairIndex
    blocks: Mapping[str, bytes]


def compile_symbol_nodes(
    symbol_facts: Sequence[SymbolFactNode],
    links: Sequence[SemanticLinkNode],
    *,
    capsule_index: SortedPairIndex | Mapping[str, str] | Sequence[Sequence[str]],
    raw_source_required_reasons: Mapping[str, Sequence[str]] | None = None,
) -> NodeCompileResult:
    """Assemble ``SymbolMerkleNode`` values from facts, links, and capsule CIDs.

    Accepts an already-compiled capsule index and never compiles capsules.
    Incoming/outgoing link CID lists are sorted and duplicate-free.  Nodes
    reference link CIDs and capsule CIDs; they never appear in link payloads.
    """
    if any(not isinstance(item, SymbolFactNode) for item in symbol_facts):
        raise MerkleCompilerError("symbol_facts must be SymbolFactNode values")
    if any(not isinstance(item, SemanticLinkNode) for item in links):
        raise MerkleCompilerError("links must be SemanticLinkNode values")

    capsule_pairs = _as_capsule_pairs(capsule_index)
    capsule_by_symbol = {stable_id: capsule_cid for stable_id, capsule_cid in capsule_pairs}

    ordered_facts = sorted(symbol_facts, key=lambda item: item.stable_symbol_id)
    if len({item.stable_symbol_id for item in ordered_facts}) != len(ordered_facts):
        raise MerkleCompilerError("symbol_facts must not contain duplicate stable IDs")

    missing = [
        fact.stable_symbol_id
        for fact in ordered_facts
        if fact.stable_symbol_id not in capsule_by_symbol
    ]
    if missing:
        raise MerkleCompilerError(
            "capsule_index missing entries for stable symbol IDs: "
            + ", ".join(sorted(missing)[:8])
        )

    outgoing: dict[str, list[str]] = {fact.stable_symbol_id: [] for fact in ordered_facts}
    incoming: dict[str, list[str]] = {fact.stable_symbol_id: [] for fact in ordered_facts}
    for link in links:
        if link.source_stable_id in outgoing:
            outgoing[link.source_stable_id].append(link.link_cid)
        if (
            link.target_kind == LinkTargetKind.SYMBOL.value
            and link.target_stable_id is not None
            and link.target_stable_id in incoming
        ):
            incoming[link.target_stable_id].append(link.link_cid)

    reason_map = raw_source_required_reasons or {}
    nodes: list[SymbolMerkleNode] = []
    pairs: list[tuple[str, str]] = []
    blocks: dict[str, bytes] = {}
    for fact in ordered_facts:
        stable_id = fact.stable_symbol_id
        confidence = str(fact.confidence)
        if stable_id in reason_map:
            reasons = tuple(reason_map[stable_id])
        else:
            reasons = _raw_source_reasons(confidence)
        node = SymbolMerkleNode(
            stable_symbol_id=stable_id,
            version_cid=fact.version_cid,
            symbol_fact_cid=fact.fact_cid,
            capsule_cid=capsule_by_symbol[stable_id],
            incoming_link_cids=incoming[stable_id],
            outgoing_link_cids=outgoing[stable_id],
            confidence=confidence,
            raw_source_required_reasons=reasons,
        )
        cid, data = _record_block(node.identity_payload(), node.node_cid)
        nodes.append(node)
        pairs.append((stable_id, cid))
        blocks[cid] = data

    index = SortedPairIndex(pairs=pairs)
    index_cid, index_data = _record_block(index.identity_payload(), index.index_cid)
    blocks[index_cid] = index_data
    return NodeCompileResult(
        nodes=tuple(nodes),
        index=index,
        blocks=_freeze_blocks(blocks),
    )


# ---------------------------------------------------------------------------
# Materialized DAG (SymbolMerkleDag@1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SymbolMerkleDag:
    """Acyclic symbol-level Merkle DAG materialization (``SymbolMerkleDag@1``).

    All collections are sorted by their logical key.  ``blocks`` maps every
    emitted fact/link/node/index CID to its canonical identity-payload bytes.
    """

    symbol_facts: tuple[SymbolFactNode, ...]
    artifact_facts: tuple[ArtifactFactNode, ...]
    links: tuple[SemanticLinkNode, ...]
    symbol_nodes: tuple[SymbolMerkleNode, ...]
    symbol_fact_index: SortedPairIndex
    artifact_fact_index: SortedPairIndex
    semantic_link_index: SortedPairIndex
    symbol_node_index: SortedPairIndex
    blocks: Mapping[str, bytes]
    merkle_compiler_version: str = MERKLE_COMPILER_VERSION
    interface: str = SYMBOL_MERKLE_DAG_INTERFACE

    def __post_init__(self) -> None:
        if self.merkle_compiler_version != MERKLE_COMPILER_VERSION:
            raise MerkleCompilerError(
                f"unsupported merkle_compiler_version {self.merkle_compiler_version!r}"
            )
        if self.interface != SYMBOL_MERKLE_DAG_INTERFACE:
            raise MerkleCompilerError(f"unsupported interface {self.interface!r}")
        object.__setattr__(self, "blocks", _freeze_blocks(self.blocks))
        # Structural layering check: link payloads must not name node CIDs.
        node_cids = {node.node_cid for node in self.symbol_nodes}
        for link in self.links:
            payload = link.identity_payload()
            for value in (
                payload.get("source_fact_cid"),
                payload.get("target_fact_cid"),
                payload.get("edge_id"),
            ):
                if value in node_cids:
                    raise MerkleCompilerError(
                        "link payload must not reference a symbol-node CID"
                    )
            # Full payload values (no node CIDs anywhere in link identity).
            encoded = canonical_dag_json_bytes(payload)
            for node_cid in node_cids:
                if node_cid.encode("ascii") in encoded:
                    raise MerkleCompilerError(
                        "link identity must not embed a symbol-node CID"
                    )

    @property
    def symbol_fact_index_cid(self) -> str:
        return self.symbol_fact_index.index_cid

    @property
    def artifact_fact_index_cid(self) -> str:
        return self.artifact_fact_index.index_cid

    @property
    def semantic_link_index_cid(self) -> str:
        return self.semantic_link_index.index_cid

    @property
    def symbol_node_index_cid(self) -> str:
        return self.symbol_node_index.index_cid

    def symbol_fact(self, stable_symbol_id: str) -> SymbolFactNode:
        for fact in self.symbol_facts:
            if fact.stable_symbol_id == stable_symbol_id:
                return fact
        raise MerkleCompilerError(f"unknown symbol fact {stable_symbol_id!r}")

    def symbol_node(self, stable_symbol_id: str) -> SymbolMerkleNode:
        for node in self.symbol_nodes:
            if node.stable_symbol_id == stable_symbol_id:
                return node
        raise MerkleCompilerError(f"unknown symbol node {stable_symbol_id!r}")

    def link_by_edge_id(self, edge_id: str) -> SemanticLinkNode:
        for link in self.links:
            if link.edge_id == edge_id:
                return link
        raise MerkleCompilerError(f"unknown link edge_id {edge_id!r}")


def build_symbol_merkle_dag(
    *,
    symbols: Sequence[SymbolRecord] | None = None,
    artifacts: Sequence[ArtifactRecord] | None = None,
    edges: Sequence[DependencyEdge] | None = None,
    capsule_index: SortedPairIndex | Mapping[str, str] | Sequence[Sequence[str]],
    repository_state: RepositoryState | None = None,
    raw_source_required_reasons: Mapping[str, Sequence[str]] | None = None,
) -> SymbolMerkleDag:
    """Materialize a complete acyclic symbol Merkle DAG from a sealed ISI view.

    Prefer ``repository_state`` when available; otherwise pass explicit
    ``symbols`` / ``artifacts`` / ``edges``.  ``capsule_index`` is an input
    produced by the capsule compiler (DSS-004) and is never synthesized here.
    """
    if repository_state is not None:
        if not isinstance(repository_state, RepositoryState):
            raise MerkleCompilerError("repository_state must be a RepositoryState")
        if symbols is not None or artifacts is not None or edges is not None:
            raise MerkleCompilerError(
                "repository_state cannot be combined with symbols/artifacts/edges"
            )
        symbols = repository_state.symbols
        artifacts = repository_state.artifacts
        edges = repository_state.edges
    else:
        if symbols is None:
            symbols = ()
        if artifacts is None:
            artifacts = ()
        if edges is None:
            edges = ()

    symbol_result = compile_symbol_facts(symbols)
    artifact_result = compile_artifact_facts(artifacts)
    link_result = compile_semantic_links(
        edges,
        symbol_facts=symbol_result.facts,  # type: ignore[arg-type]
        artifact_facts=artifact_result.facts,  # type: ignore[arg-type]
    )
    node_result = compile_symbol_nodes(
        symbol_result.facts,  # type: ignore[arg-type]
        link_result.links,
        capsule_index=capsule_index,
        raw_source_required_reasons=raw_source_required_reasons,
    )
    blocks = _merge_blocks(
        symbol_result.blocks,
        artifact_result.blocks,
        link_result.blocks,
        node_result.blocks,
    )
    return SymbolMerkleDag(
        symbol_facts=symbol_result.facts,  # type: ignore[arg-type]
        artifact_facts=artifact_result.facts,  # type: ignore[arg-type]
        links=link_result.links,
        symbol_nodes=node_result.nodes,
        symbol_fact_index=symbol_result.index,
        artifact_fact_index=artifact_result.index,
        semantic_link_index=link_result.index,
        symbol_node_index=node_result.index,
        blocks=blocks,
    )


def verify_symbol_merkle_dag(dag: SymbolMerkleDag) -> SymbolMerkleDag:
    """Reverify every emitted fact/link/node/index block and claimed CID.

    Reconstructs records from stored identity payloads and checks that every
    claimed CID matches the recomputed content identity.  Returns ``dag`` on
    success.
    """
    if not isinstance(dag, SymbolMerkleDag):
        raise MerkleCompilerError("dag must be a SymbolMerkleDag")

    import json

    def _load(cid: str) -> dict[str, Any]:
        try:
            data = dag.blocks[cid]
        except KeyError as exc:
            raise MerkleCompilerError(f"missing block {cid}") from exc
        if canonical_dag_json_bytes(json.loads(data.decode("utf-8"))) != data:
            raise MerkleCompilerError(f"block {cid} is not canonical")
        payload = json.loads(data.decode("utf-8"))
        if cid_for_structured(payload) != cid:
            raise MerkleCompilerError(f"block CID {cid} does not reverify")
        return payload

    for fact in dag.symbol_facts:
        payload = _load(fact.fact_cid)
        if payload != fact.identity_payload():
            raise MerkleCompilerError(
                f"symbol fact block {fact.fact_cid} does not match record"
            )
        restored = SymbolFactNode.from_dict(fact.to_dict())
        if restored.fact_cid != fact.fact_cid:
            raise MerkleCompilerError("symbol fact CID round-trip failed")

    for fact in dag.artifact_facts:
        payload = _load(fact.fact_cid)
        if payload != fact.identity_payload():
            raise MerkleCompilerError(
                f"artifact fact block {fact.fact_cid} does not match record"
            )
        restored = ArtifactFactNode.from_dict(fact.to_dict())
        if restored.fact_cid != fact.fact_cid:
            raise MerkleCompilerError("artifact fact CID round-trip failed")

    for link in dag.links:
        payload = _load(link.link_cid)
        if payload != link.identity_payload():
            raise MerkleCompilerError(
                f"link block {link.link_cid} does not match record"
            )
        restored = SemanticLinkNode.from_dict(link.to_dict())
        if restored.link_cid != link.link_cid:
            raise MerkleCompilerError("link CID round-trip failed")
        # Layering: links must not reference node CIDs.
        node_cids = {node.node_cid for node in dag.symbol_nodes}
        if restored.source_fact_cid in node_cids or (
            restored.target_fact_cid is not None and restored.target_fact_cid in node_cids
        ):
            raise MerkleCompilerError("link references a symbol-node CID")

    for node in dag.symbol_nodes:
        payload = _load(node.node_cid)
        if payload != node.identity_payload():
            raise MerkleCompilerError(
                f"node block {node.node_cid} does not match record"
            )
        restored = SymbolMerkleNode.from_dict(node.to_dict())
        if restored.node_cid != node.node_cid:
            raise MerkleCompilerError("node CID round-trip failed")

    for index in (
        dag.symbol_fact_index,
        dag.artifact_fact_index,
        dag.semantic_link_index,
        dag.symbol_node_index,
    ):
        payload = _load(index.index_cid)
        if payload != index.identity_payload():
            raise MerkleCompilerError(
                f"index block {index.index_cid} does not match record"
            )
        restored = SortedPairIndex.from_dict(index.to_dict())
        if restored.index_cid != index.index_cid:
            raise MerkleCompilerError("index CID round-trip failed")

    # Index membership consistency.
    fact_pairs = {fact.stable_symbol_id: fact.fact_cid for fact in dag.symbol_facts}
    if dict(dag.symbol_fact_index.pairs) != fact_pairs:
        raise MerkleCompilerError("symbol_fact_index membership mismatch")
    art_pairs = {fact.artifact_id: fact.fact_cid for fact in dag.artifact_facts}
    if dict(dag.artifact_fact_index.pairs) != art_pairs:
        raise MerkleCompilerError("artifact_fact_index membership mismatch")
    link_pairs = {link.edge_id: link.link_cid for link in dag.links}
    if dict(dag.semantic_link_index.pairs) != link_pairs:
        raise MerkleCompilerError("semantic_link_index membership mismatch")
    node_pairs = {node.stable_symbol_id: node.node_cid for node in dag.symbol_nodes}
    if dict(dag.symbol_node_index.pairs) != node_pairs:
        raise MerkleCompilerError("symbol_node_index membership mismatch")

    return dag


def cid_reference_layers(dag: SymbolMerkleDag) -> dict[str, frozenset[str]]:
    """Return the explicit CID reference layers that prove content acyclicity.

    Layer order is strict: facts are leaves; links reference only fact CIDs;
    nodes reference fact, link, and capsule CIDs.  No layer may reference a
    higher layer, so domain-level cycles cannot produce CID cycles.
    """
    fact_cids = frozenset(
        {fact.fact_cid for fact in dag.symbol_facts}
        | {fact.fact_cid for fact in dag.artifact_facts}
    )
    link_cids = frozenset(link.link_cid for link in dag.links)
    node_cids = frozenset(node.node_cid for node in dag.symbol_nodes)
    capsule_cids = frozenset(node.capsule_cid for node in dag.symbol_nodes)

    for link in dag.links:
        if link.source_fact_cid not in fact_cids:
            raise MerkleCompilerError("link source_fact_cid is not a known fact")
        if link.target_fact_cid is not None and link.target_fact_cid not in fact_cids:
            # Unresolved targets may omit fact CIDs; optional present facts must
            # still be known facts (never nodes/capsules/links).
            raise MerkleCompilerError("link target_fact_cid is not a known fact")
        if link.link_cid in fact_cids or link.link_cid in node_cids:
            raise MerkleCompilerError("link CID collides with fact/node layer")
        if link.source_fact_cid in link_cids or link.source_fact_cid in node_cids:
            raise MerkleCompilerError("link source references non-fact layer")
        if link.target_fact_cid in link_cids or link.target_fact_cid in node_cids:
            raise MerkleCompilerError("link target references non-fact layer")

    for node in dag.symbol_nodes:
        if node.symbol_fact_cid not in fact_cids:
            raise MerkleCompilerError("node symbol_fact_cid is not a known fact")
        for link_cid in (*node.incoming_link_cids, *node.outgoing_link_cids):
            if link_cid not in link_cids:
                raise MerkleCompilerError(
                    f"node {node.stable_symbol_id} references unknown link {link_cid}"
                )
            if link_cid in fact_cids or link_cid in node_cids:
                raise MerkleCompilerError("node link reference collides layers")
        if node.node_cid in fact_cids or node.node_cid in link_cids:
            raise MerkleCompilerError("node CID collides with fact/link layer")
        # Capsule CIDs are external inputs; they must not equal node CIDs of this
        # DAG (capsules never reference node CIDs by contract).
        if node.capsule_cid in node_cids:
            raise MerkleCompilerError("capsule_cid collides with a symbol-node CID")

    return {
        "fact_cids": fact_cids,
        "link_cids": link_cids,
        "node_cids": node_cids,
        "capsule_cids": capsule_cids,
    }


__all__ = [
    "MERKLE_COMPILER_VERSION",
    "SYMBOL_MERKLE_DAG_INTERFACE",
    "SYMBOL_MERKLE_DAG_SCHEMA",
    "MerkleCompilerError",
    "FactCompileResult",
    "LinkCompileResult",
    "NodeCompileResult",
    "SymbolMerkleDag",
    "compile_symbol_facts",
    "compile_artifact_facts",
    "compile_semantic_links",
    "compile_symbol_nodes",
    "build_symbol_merkle_dag",
    "verify_symbol_merkle_dag",
    "cid_reference_layers",
]
