"""Acceptance vectors for the acyclic symbol Merkle DAG (DSS-003)."""

from __future__ import annotations

import ast
import json
import random
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    DependencyEdge,
    RelationType,
    RepositoryState,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.merkle import (
    MERKLE_COMPILER_VERSION,
    SYMBOL_MERKLE_DAG_INTERFACE,
    MerkleCompilerError,
    SymbolMerkleDag,
    build_symbol_merkle_dag,
    cid_reference_layers,
    compile_artifact_facts,
    compile_semantic_links,
    compile_symbol_facts,
    compile_symbol_nodes,
    verify_symbol_merkle_dag,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    LinkTargetKind,
    SemanticLinkNode,
    SortedPairIndex,
    SymbolFactNode,
    SymbolMerkleNode,
)


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------

REPO = "repo:merkle-example"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _make_symbol(
    qualified_name: str,
    *,
    module_path: str = "pkg/mod.py",
    namespace: str = "pkg",
    kind: SymbolKind | str = SymbolKind.FUNCTION,
    body: str | None = None,
    span: SourceSpan | None = None,
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT,
    signature: dict[str, Any] | None = None,
    decorators: list[str] | None = None,
    annotations: dict[str, Any] | None = None,
) -> SymbolRecord:
    """Build a verified ISI SymbolRecord with a unique semantic body."""
    short = qualified_name.rsplit(".", 1)[-1]
    if body is None:
        source = f"def {short}(value: int) -> int:\n    return value + 1\n"
    else:
        source = body
    node = ast.parse(source).body[0]
    stable = stable_symbol_id(REPO, "python", module_path, qualified_name, kind, namespace)
    sig = signature if signature is not None else {"parameters": ["value"], "return": "int"}
    decs = decorators if decorators is not None else ["public"]
    anns = annotations if annotations is not None else {"value": "int", "return": "int"}
    version = symbol_version_cid(stable, node, sig, decs, anns)
    return SymbolRecord(
        stable,
        version,
        REPO,
        "python",
        module_path,
        qualified_name,
        kind,
        namespace,
        cid_for_bytes(source.encode("utf-8")),
        span,
        confidence,
        sig,
        decs,
        anns,
        normalized_ast=node,
    )


def _mutate_symbol_semantics(symbol: SymbolRecord) -> SymbolRecord:
    """Return a new SymbolRecord with a different version CID (semantic change)."""
    short = symbol.qualified_name.rsplit(".", 1)[-1]
    source = f"def {short}(value: int) -> int:\n    return value + 99\n"
    node = ast.parse(source).body[0]
    sig = {"parameters": ["value"], "return": "int", "semantic_bump": 99}
    version = symbol_version_cid(
        symbol.stable_id, node, sig, list(symbol.decorators), dict(symbol.annotations)
    )
    return SymbolRecord(
        symbol.stable_id,
        version,
        symbol.repository_id,
        symbol.language,
        symbol.module_path,
        symbol.qualified_name,
        symbol.kind,
        symbol.namespace,
        cid_for_bytes(source.encode("utf-8")),
        symbol.span,
        symbol.confidence,
        sig,
        list(symbol.decorators),
        dict(symbol.annotations),
        normalized_ast=node,
    )


def _edge(
    source: SymbolRecord,
    target_id: str,
    relation: RelationType | str = RelationType.CALLS,
    *,
    method: str = "lexical",
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT,
    span: SourceSpan | None = None,
    metadata: dict[str, Any] | None = None,
) -> DependencyEdge:
    return DependencyEdge(
        source.stable_id,
        target_id,
        relation,
        method,
        confidence,
        "1",
        span,
        metadata or {},
    )


def _capsule_index(symbols: list[SymbolRecord], *, salt: str = "cap") -> dict[str, str]:
    """Already-compiled capsule CID map (DSS-004 input; not compiled here)."""
    return {
        symbol.stable_id: _cid(f"{salt}:{symbol.stable_id}:{symbol.version_cid}")
        for symbol in symbols
    }


def _build(
    symbols: list[SymbolRecord],
    *,
    artifacts: list[ArtifactRecord] | None = None,
    edges: list[DependencyEdge] | None = None,
    capsule_index: dict[str, str] | None = None,
) -> SymbolMerkleDag:
    return build_symbol_merkle_dag(
        symbols=symbols,
        artifacts=artifacts or [],
        edges=edges or [],
        capsule_index=capsule_index or _capsule_index(symbols),
    )


# ---------------------------------------------------------------------------
# Core compilation
# ---------------------------------------------------------------------------


def test_compile_symbol_and_artifact_facts_are_deterministic_and_sorted() -> None:
    a = _make_symbol("pkg.mod.alpha", body="def alpha(x: int) -> int:\n    return x\n")
    b = _make_symbol("pkg.mod.beta", body="def beta(x: int) -> int:\n    return x\n")
    # Shuffled input order.
    result_ab = compile_symbol_facts([b, a])
    result_ba = compile_symbol_facts([a, b])
    assert [f.stable_symbol_id for f in result_ab.facts] == sorted(
        [a.stable_id, b.stable_id]
    )
    assert result_ab.index.index_cid == result_ba.index.index_cid
    assert dict(result_ab.blocks) == dict(result_ba.blocks)
    assert result_ab.facts[0].fact_cid == SymbolFactNode(symbol=a if a.stable_id < b.stable_id else b).fact_cid

    art_a = ArtifactRecord("artifact:db", "external", "config/db.json", _cid("db-src"))
    art_b = ArtifactRecord("artifact:cfg", "config", "config/app.toml")
    arts = compile_artifact_facts([art_a, art_b])
    assert [f.artifact_id for f in arts.facts] == ["artifact:cfg", "artifact:db"]
    assert arts.index.pairs[0][0] == "artifact:cfg"


def test_compile_semantic_links_preserve_edge_id_and_classify_targets() -> None:
    caller = _make_symbol("pkg.mod.caller", body="def caller(x: int) -> int:\n    return x\n")
    callee = _make_symbol("pkg.mod.callee", body="def callee(x: int) -> int:\n    return x\n")
    artifact = ArtifactRecord("artifact:database", "external", "config/db.json")
    span = SourceSpan("pkg/mod.py", 1, 0, 1, 10)

    edge_sym = _edge(caller, callee.stable_id, RelationType.CALLS, span=span)
    edge_art = _edge(caller, "artifact:database", RelationType.CALLS, method="import")
    edge_unresolved = _edge(
        caller,
        "lexical:missing_name",
        RelationType.CALLS,
        confidence=AnalysisConfidence.CONSERVATIVE,
        metadata={"resolution": "unresolved", "unresolved_target": "lexical:missing_name"},
    )
    # Inheritance cycle edges: A inherits B, B inherits A (domain cycle).
    edge_inh_ab = _edge(caller, callee.stable_id, RelationType.INHERITS)
    edge_inh_ba = _edge(callee, caller.stable_id, RelationType.INHERITS)
    # Mutual imports.
    edge_imp_ab = _edge(caller, callee.stable_id, RelationType.IMPORTS)
    edge_imp_ba = _edge(callee, caller.stable_id, RelationType.IMPORTS)
    # Recursive call.
    edge_rec = _edge(caller, caller.stable_id, RelationType.CALLS)

    symbol_facts = compile_symbol_facts([caller, callee]).facts
    artifact_facts = compile_artifact_facts([artifact]).facts
    edges = [
        edge_sym,
        edge_art,
        edge_unresolved,
        edge_inh_ab,
        edge_inh_ba,
        edge_imp_ab,
        edge_imp_ba,
        edge_rec,
    ]
    # Shuffled edges.
    shuffled = list(edges)
    random.Random(0).shuffle(shuffled)
    links = compile_semantic_links(
        shuffled,
        symbol_facts=symbol_facts,  # type: ignore[arg-type]
        artifact_facts=artifact_facts,  # type: ignore[arg-type]
    )
    assert [link.edge_id for link in links.links] == sorted(e.edge_id for e in edges)

    by_edge = {link.edge_id: link for link in links.links}
    sym_link = by_edge[edge_sym.edge_id]
    assert sym_link.edge_id == edge_sym.edge_id
    assert sym_link.target_kind == LinkTargetKind.SYMBOL.value
    assert sym_link.target_stable_id == callee.stable_id
    assert sym_link.target_version_cid == callee.version_cid
    assert sym_link.target_fact_cid == SymbolFactNode(symbol=callee).fact_cid
    assert sym_link.source_fact_cid == SymbolFactNode(symbol=caller).fact_cid
    assert sym_link.source_span == span
    assert sym_link.relation == RelationType.CALLS.value

    art_link = by_edge[edge_art.edge_id]
    assert art_link.target_kind == LinkTargetKind.ARTIFACT.value
    assert art_link.target_stable_id == "artifact:database"
    assert art_link.target_version_cid is None
    assert art_link.target_fact_cid is not None

    unresolved = by_edge[edge_unresolved.edge_id]
    assert unresolved.target_kind == LinkTargetKind.UNRESOLVED.value
    assert unresolved.target_stable_id is None
    assert unresolved.target_version_cid is None
    assert unresolved.metadata["resolution"] == "unresolved"

    rec = by_edge[edge_rec.edge_id]
    assert rec.target_kind == LinkTargetKind.SYMBOL.value
    assert rec.target_stable_id == caller.stable_id
    # Link still only references fact CIDs — no node CIDs exist yet.
    assert rec.source_fact_cid == rec.target_fact_cid


def test_recursive_mutual_and_inheritance_cycles_cannot_form_cid_cycles() -> None:
    """Domain cycles must not produce content-identity cycles."""
    a = _make_symbol("pkg.mod.a", body="def a(x: int) -> int:\n    return x\n")
    b = _make_symbol("pkg.mod.b", body="def b(x: int) -> int:\n    return x\n")
    edges = [
        _edge(a, a.stable_id, RelationType.CALLS),  # recursive
        _edge(a, b.stable_id, RelationType.IMPORTS),
        _edge(b, a.stable_id, RelationType.IMPORTS),  # mutual import
        _edge(a, b.stable_id, RelationType.INHERITS),
        _edge(b, a.stable_id, RelationType.INHERITS),  # inheritance cycle
    ]
    dag = _build([a, b], edges=edges)
    layers = cid_reference_layers(dag)
    verify_symbol_merkle_dag(dag)

    # Strict layering: no overlap between fact / link / node CID sets.
    assert layers["fact_cids"].isdisjoint(layers["link_cids"])
    assert layers["fact_cids"].isdisjoint(layers["node_cids"])
    assert layers["link_cids"].isdisjoint(layers["node_cids"])
    assert layers["capsule_cids"].isdisjoint(layers["node_cids"])

    # Links never embed node CIDs; nodes may reference link CIDs only downward.
    node_cids = layers["node_cids"]
    for link in dag.links:
        encoded = canonical_dag_json_bytes(link.identity_payload())
        for node_cid in node_cids:
            assert node_cid.encode("ascii") not in encoded
        assert link.source_fact_cid in layers["fact_cids"]
        if link.target_fact_cid is not None:
            assert link.target_fact_cid in layers["fact_cids"]

    for node in dag.symbol_nodes:
        assert node.symbol_fact_cid in layers["fact_cids"]
        for link_cid in (*node.incoming_link_cids, *node.outgoing_link_cids):
            assert link_cid in layers["link_cids"]
            assert link_cid not in node_cids


def test_shuffled_input_order_has_no_effect_on_dag() -> None:
    symbols = [
        _make_symbol(f"pkg.mod.fn{i}", body=f"def fn{i}(x: int) -> int:\n    return {i}\n")
        for i in range(5)
    ]
    artifacts = [
        ArtifactRecord(f"artifact:{name}", "external", f"cfg/{name}.json")
        for name in ("zulu", "alpha", "mike")
    ]
    edges = [
        _edge(symbols[0], symbols[1].stable_id, RelationType.CALLS),
        _edge(symbols[1], symbols[2].stable_id, RelationType.IMPORTS),
        _edge(symbols[2], symbols[0].stable_id, RelationType.INHERITS),
        _edge(symbols[3], "artifact:alpha", RelationType.CALLS),
        _edge(symbols[4], "lexical:ghost", RelationType.CALLS),
    ]
    capsule = _capsule_index(symbols)

    def permute(seed: int) -> SymbolMerkleDag:
        rng = random.Random(seed)
        s = list(symbols)
        a = list(artifacts)
        e = list(edges)
        rng.shuffle(s)
        rng.shuffle(a)
        rng.shuffle(e)
        # Capsule map iteration order also shuffled.
        items = list(capsule.items())
        rng.shuffle(items)
        return build_symbol_merkle_dag(
            symbols=s,
            artifacts=a,
            edges=e,
            capsule_index=dict(items),
        )

    baseline = permute(1)
    for seed in (2, 3, 7, 42, 99):
        other = permute(seed)
        assert other.symbol_fact_index.index_cid == baseline.symbol_fact_index.index_cid
        assert other.artifact_fact_index.index_cid == baseline.artifact_fact_index.index_cid
        assert other.semantic_link_index.index_cid == baseline.semantic_link_index.index_cid
        assert other.symbol_node_index.index_cid == baseline.symbol_node_index.index_cid
        assert [n.node_cid for n in other.symbol_nodes] == [
            n.node_cid for n in baseline.symbol_nodes
        ]
        assert [link.link_cid for link in other.links] == [
            link.link_cid for link in baseline.links
        ]
        assert dict(other.blocks) == dict(baseline.blocks)


def test_every_emitted_block_and_claimed_cid_reverifies() -> None:
    a = _make_symbol("pkg.mod.a", body="def a(x: int) -> int:\n    return 1\n")
    b = _make_symbol("pkg.mod.b", body="def b(x: int) -> int:\n    return 2\n")
    artifact = ArtifactRecord("artifact:lock", "lock", "poetry.lock", _cid("lock-bytes"))
    edges = [
        _edge(a, b.stable_id, RelationType.CALLS),
        _edge(b, "artifact:lock", RelationType.CONFIGURED_BY),
        _edge(a, "lexical:unknown", RelationType.CALLS),
    ]
    dag = _build([a, b], artifacts=[artifact], edges=edges)
    verified = verify_symbol_merkle_dag(dag)
    assert verified is dag

    # Explicit per-block rehash of every map entry.
    for cid, data in dag.blocks.items():
        payload = json.loads(data.decode("utf-8"))
        assert canonical_dag_json_bytes(payload) == data
        assert cid_for_structured(payload) == cid

    # Record round-trips.
    for fact in dag.symbol_facts:
        assert SymbolFactNode.from_dict(fact.to_dict()).fact_cid == fact.fact_cid
    for link in dag.links:
        assert SemanticLinkNode.from_dict(link.to_dict()).link_cid == link.link_cid
    for node in dag.symbol_nodes:
        assert SymbolMerkleNode.from_dict(node.to_dict()).node_cid == node.node_cid
    for index in (
        dag.symbol_fact_index,
        dag.artifact_fact_index,
        dag.semantic_link_index,
        dag.symbol_node_index,
    ):
        assert SortedPairIndex.from_dict(index.to_dict()).index_cid == index.index_cid


def test_one_semantic_symbol_mutation_changes_only_bounded_cone() -> None:
    """Mutating one symbol changes only its fact/link/node/index cone."""
    a = _make_symbol("pkg.mod.a", body="def a(x: int) -> int:\n    return 1\n")
    b = _make_symbol("pkg.mod.b", body="def b(x: int) -> int:\n    return 2\n")
    c = _make_symbol("pkg.mod.c", body="def c(x: int) -> int:\n    return 3\n")
    # A -> B, C isolated.
    edges = [_edge(a, b.stable_id, RelationType.CALLS)]
    capsules = _capsule_index([a, b, c])

    baseline = build_symbol_merkle_dag(
        symbols=[a, b, c],
        edges=edges,
        capsule_index=capsules,
    )

    a2 = _mutate_symbol_semantics(a)
    # Capsule for A changes with version (producer key); B/C capsules stable.
    capsules2 = dict(capsules)
    capsules2[a2.stable_id] = _cid(f"cap:{a2.stable_id}:{a2.version_cid}")
    mutated = build_symbol_merkle_dag(
        symbols=[a2, b, c],
        edges=[_edge(a2, b.stable_id, RelationType.CALLS)],
        capsule_index=capsules2,
    )

    # C is outside the cone: fact and node CIDs unchanged.
    assert baseline.symbol_fact(c.stable_id).fact_cid == mutated.symbol_fact(
        c.stable_id
    ).fact_cid
    assert baseline.symbol_node(c.stable_id).node_cid == mutated.symbol_node(
        c.stable_id
    ).node_cid

    # B's fact is unchanged (semantics of B did not change).
    assert baseline.symbol_fact(b.stable_id).fact_cid == mutated.symbol_fact(
        b.stable_id
    ).fact_cid

    # A's fact changes.
    assert baseline.symbol_fact(a.stable_id).fact_cid != mutated.symbol_fact(
        a2.stable_id
    ).fact_cid

    # Link A->B changes (source_fact_cid).
    base_link = baseline.links[0]
    mut_link = mutated.links[0]
    assert base_link.link_cid != mut_link.link_cid
    assert mut_link.source_fact_cid == mutated.symbol_fact(a2.stable_id).fact_cid

    # A's node changes (fact + outgoing + capsule).
    assert baseline.symbol_node(a.stable_id).node_cid != mutated.symbol_node(
        a2.stable_id
    ).node_cid

    # B's node changes only because its incoming link CID list changed
    # (still bounded: no C involvement, B fact unchanged).
    assert baseline.symbol_node(b.stable_id).node_cid != mutated.symbol_node(
        b.stable_id
    ).node_cid
    assert set(mutated.symbol_node(b.stable_id).incoming_link_cids) == {
        mut_link.link_cid
    }

    # Unrelated index pairs for C remain byte-identical entries.
    base_c_pair = dict(baseline.symbol_fact_index.pairs)[c.stable_id]
    mut_c_pair = dict(mutated.symbol_fact_index.pairs)[c.stable_id]
    assert base_c_pair == mut_c_pair
    base_c_node = dict(baseline.symbol_node_index.pairs)[c.stable_id]
    mut_c_node = dict(mutated.symbol_node_index.pairs)[c.stable_id]
    assert base_c_node == mut_c_node

    # Indexes that contain the mutated cone do change overall.
    assert baseline.symbol_fact_index.index_cid != mutated.symbol_fact_index.index_cid
    assert baseline.semantic_link_index.index_cid != mutated.semantic_link_index.index_cid
    assert baseline.symbol_node_index.index_cid != mutated.symbol_node_index.index_cid

    # Blocks for C's fact/node bytes are reused identically.
    c_fact = baseline.symbol_fact(c.stable_id).fact_cid
    c_node = baseline.symbol_node(c.stable_id).node_cid
    assert baseline.blocks[c_fact] == mutated.blocks[c_fact]
    assert baseline.blocks[c_node] == mutated.blocks[c_node]


def test_symbol_nodes_accept_capsule_index_and_never_compile_capsules() -> None:
    symbol = _make_symbol("pkg.mod.only")
    facts = compile_symbol_facts([symbol]).facts
    links = compile_semantic_links([], symbol_facts=facts).links  # type: ignore[arg-type]
    capsule_cid = _cid("precompiled-capsule")
    nodes = compile_symbol_nodes(
        facts,  # type: ignore[arg-type]
        links,
        capsule_index={symbol.stable_id: capsule_cid},
    )
    assert len(nodes.nodes) == 1
    assert nodes.nodes[0].capsule_cid == capsule_cid
    assert nodes.nodes[0].symbol_fact_cid == facts[0].fact_cid

    with pytest.raises(MerkleCompilerError, match="capsule_index missing"):
        compile_symbol_nodes(facts, links, capsule_index={})  # type: ignore[arg-type]


def test_build_from_repository_state_matches_explicit_inputs() -> None:
    a = _make_symbol("pkg.mod.a", body="def a(x: int) -> int:\n    return 1\n")
    b = _make_symbol("pkg.mod.b", body="def b(x: int) -> int:\n    return 2\n")
    artifact = ArtifactRecord("artifact:x", "external", "x.json")
    edges = [_edge(a, b.stable_id, RelationType.CALLS)]
    state = RepositoryState(
        repository_id=REPO,
        symbols=[a, b],
        artifacts=[artifact],
        edges=edges,
    )
    capsules = _capsule_index([a, b])
    from_state = build_symbol_merkle_dag(
        repository_state=state,
        capsule_index=capsules,
    )
    explicit = build_symbol_merkle_dag(
        symbols=[a, b],
        artifacts=[artifact],
        edges=edges,
        capsule_index=capsules,
    )
    assert from_state.symbol_node_index.index_cid == explicit.symbol_node_index.index_cid
    assert dict(from_state.blocks) == dict(explicit.blocks)
    assert from_state.interface == SYMBOL_MERKLE_DAG_INTERFACE
    assert from_state.merkle_compiler_version == MERKLE_COMPILER_VERSION


def test_unknown_source_and_duplicate_inputs_fail_closed() -> None:
    a = _make_symbol("pkg.mod.a", body="def a(x: int) -> int:\n    return 1\n")
    orphan_edge = DependencyEdge(
        _cid("not-a-real-symbol-stable-id"),
        a.stable_id,
        RelationType.CALLS,
        "lexical",
        "exact",
        "1",
    )
    facts = compile_symbol_facts([a]).facts
    with pytest.raises(MerkleCompilerError, match="not a known symbol"):
        compile_semantic_links([orphan_edge], symbol_facts=facts)  # type: ignore[arg-type]

    with pytest.raises(MerkleCompilerError, match="duplicate stable_id"):
        compile_symbol_facts([a, a])

    with pytest.raises(MerkleCompilerError, match="cannot be combined"):
        build_symbol_merkle_dag(
            repository_state=RepositoryState(repository_id=REPO, symbols=[a]),
            symbols=[a],
            capsule_index=_capsule_index([a]),
        )


def test_opaque_confidence_sets_raw_source_required_reasons() -> None:
    opaque = _make_symbol(
        "pkg.mod.opaque",
        body="def opaque(x: int) -> int:\n    return x\n",
        confidence=AnalysisConfidence.OPAQUE,
    )
    dag = _build([opaque])
    node = dag.symbol_node(opaque.stable_id)
    assert node.confidence == AnalysisConfidence.OPAQUE.value
    assert "opaque_confidence" in node.raw_source_required_reasons


def test_forged_block_fails_verify() -> None:
    a = _make_symbol("pkg.mod.a", body="def a(x: int) -> int:\n    return 1\n")
    dag = _build([a])
    bad_blocks = dict(dag.blocks)
    victim = dag.symbol_facts[0].fact_cid
    bad_blocks[victim] = canonical_dag_json_bytes({"forged": True})
    with pytest.raises(MerkleCompilerError, match="does not reverify|not canonical"):
        SymbolMerkleDag(
            symbol_facts=dag.symbol_facts,
            artifact_facts=dag.artifact_facts,
            links=dag.links,
            symbol_nodes=dag.symbol_nodes,
            symbol_fact_index=dag.symbol_fact_index,
            artifact_fact_index=dag.artifact_fact_index,
            semantic_link_index=dag.semantic_link_index,
            symbol_node_index=dag.symbol_node_index,
            blocks=bad_blocks,
        )


def test_sorted_pair_index_from_capsule_sequence_input() -> None:
    a = _make_symbol("pkg.mod.a", body="def a(x: int) -> int:\n    return 1\n")
    b = _make_symbol("pkg.mod.b", body="def b(x: int) -> int:\n    return 2\n")
    pairs = [
        (b.stable_id, _cid("cap-b")),
        (a.stable_id, _cid("cap-a")),
    ]
    index = SortedPairIndex(pairs=pairs)
    dag = build_symbol_merkle_dag(
        symbols=[a, b],
        capsule_index=index,
    )
    assert dag.symbol_node(a.stable_id).capsule_cid == _cid("cap-a")
    assert dag.symbol_node(b.stable_id).capsule_cid == _cid("cap-b")
    verify_symbol_merkle_dag(dag)


def test_incoming_and_outgoing_link_cids_are_sorted_and_complete() -> None:
    a = _make_symbol("pkg.mod.a", body="def a(x: int) -> int:\n    return 1\n")
    b = _make_symbol("pkg.mod.b", body="def b(x: int) -> int:\n    return 2\n")
    c = _make_symbol("pkg.mod.c", body="def c(x: int) -> int:\n    return 3\n")
    edges = [
        _edge(a, b.stable_id, RelationType.CALLS),
        _edge(c, b.stable_id, RelationType.CALLS),
        _edge(b, a.stable_id, RelationType.IMPORTS),
    ]
    dag = _build([a, b, c], edges=edges)
    node_b = dag.symbol_node(b.stable_id)
    # Incoming: A->B and C->B
    assert len(node_b.incoming_link_cids) == 2
    assert list(node_b.incoming_link_cids) == sorted(node_b.incoming_link_cids)
    # Outgoing: B->A
    assert len(node_b.outgoing_link_cids) == 1
    assert list(node_b.outgoing_link_cids) == sorted(node_b.outgoing_link_cids)

    # All link CIDs appear on exactly the expected endpoints.
    link_cids = {link.link_cid for link in dag.links}
    referenced = set()
    for node in dag.symbol_nodes:
        referenced.update(node.incoming_link_cids)
        referenced.update(node.outgoing_link_cids)
    assert referenced == link_cids
