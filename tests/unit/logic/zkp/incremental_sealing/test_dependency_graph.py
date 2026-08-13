"""Regression tests for the reason-labeled ProofDependencyGraph (IPS-013)."""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing.dependency_graph import (
    DEPENDENCY_EDGE_TYPES,
    DEPENDENCY_GRAPH_SCHEMA_VERSION,
    DEPENDENCY_GRAPH_SUBSET,
    DEPENDENCY_NODE_KINDS,
    DependencyEdgeType,
    DependencyGraphError,
    DependencyNodeKind,
    DependencyRoot,
    ProofDependencyEdge,
    ProofDependencyGraph,
    ProofDependencyNode,
    closed_dependency_edge_types,
    closed_dependency_node_kinds,
    compute_dependency_root,
    known_vectors,
    mint_reason_cid,
    parse_dependency_edge_type,
    parse_dependency_node_kind,
    sample_dependency_graph,
    sample_reason,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.identity import canonical_cid

MODULE_NAME = "ipfs_datasets_py.logic.zkp.incremental_sealing.dependency_graph"


def _reason(label: str) -> str:
    return mint_reason_cid({"test_reason": label, "v": 1})


# ---------------------------------------------------------------------------
# Closed surface
# ---------------------------------------------------------------------------


def test_subset_and_eleven_edge_types_are_closed() -> None:
    assert DEPENDENCY_GRAPH_SUBSET == "ips/dependency-graph@1"
    assert DEPENDENCY_GRAPH_SCHEMA_VERSION == "graph@1"
    assert closed_dependency_edge_types() == frozenset(DEPENDENCY_EDGE_TYPES)
    assert list(DEPENDENCY_EDGE_TYPES) == [
        "source_depends_on",
        "imports",
        "calls",
        "schema_depends_on",
        "test_covers",
        "fixture_depends_on",
        "config_depends_on",
        "proof_depends_on",
        "aggregate_contains",
        "supersedes",
        "invalidates",
    ]
    assert len(DEPENDENCY_EDGE_TYPES) == 11
    assert len(DependencyEdgeType) == 11
    for name in DEPENDENCY_EDGE_TYPES:
        assert parse_dependency_edge_type(name).value == name
    with pytest.raises(DependencyGraphError, match="unknown DependencyEdgeType"):
        parse_dependency_edge_type("maybe_depends")


def test_closed_node_kinds() -> None:
    assert closed_dependency_node_kinds() == frozenset(DEPENDENCY_NODE_KINDS)
    assert "artifact" in DEPENDENCY_NODE_KINDS
    assert "symbol" in DEPENDENCY_NODE_KINDS
    assert "unit" in DEPENDENCY_NODE_KINDS
    assert "aggregate" in DEPENDENCY_NODE_KINDS
    for name in DEPENDENCY_NODE_KINDS:
        assert parse_dependency_node_kind(name).value == name
    with pytest.raises(DependencyGraphError, match="unknown DependencyNodeKind"):
        parse_dependency_node_kind("blob")


def test_all_eleven_edge_types_are_insertable() -> None:
    """Every closed edge type can be stored and recovered."""

    graph = ProofDependencyGraph()
    for index, edge_type in enumerate(DEPENDENCY_EDGE_TYPES):
        prereq = f"prereq/{index}"
        dep = f"dep/{index}"
        graph.add_node(prereq, DependencyNodeKind.UNIT)
        graph.add_node(dep, DependencyNodeKind.UNIT)
        edge = graph.add_edge(prereq, dep, edge_type, _reason(edge_type))
        assert edge.edge_type.value == edge_type
        assert edge.from_id == prereq
        assert edge.to_id == dep
    recovered_types = {edge.edge_type.value for edge in graph.edges()}
    assert recovered_types == set(DEPENDENCY_EDGE_TYPES)
    assert graph.edge_count() == 11


# ---------------------------------------------------------------------------
# Fail-closed mutation rules
# ---------------------------------------------------------------------------


def test_unknown_edge_self_loop_cycle_and_contradiction_fail_closed() -> None:
    graph = ProofDependencyGraph()
    graph.add_node("a", DependencyNodeKind.UNIT)
    graph.add_node("b", DependencyNodeKind.UNIT)
    graph.add_node("c", DependencyNodeKind.UNIT)

    with pytest.raises(DependencyGraphError, match="unknown DependencyEdgeType"):
        graph.add_edge("a", "b", "not_an_edge", _reason("x"))

    with pytest.raises(DependencyGraphError, match="self-loop"):
        graph.add_edge("a", "a", DependencyEdgeType.IMPORTS, _reason("loop"))

    graph.add_edge("a", "b", DependencyEdgeType.IMPORTS, _reason("ab"))
    graph.add_edge("b", "c", DependencyEdgeType.CALLS, _reason("bc"))
    with pytest.raises(DependencyGraphError, match="illegal cycle"):
        graph.add_edge("c", "a", DependencyEdgeType.PROOF_DEPENDS_ON, _reason("ca"))

    # Idempotent re-add with the same reason succeeds.
    again = graph.add_edge("a", "b", DependencyEdgeType.IMPORTS, _reason("ab"))
    assert again.reason_cid == _reason("ab")

    # Same endpoints + type with a different reason is a contradiction.
    with pytest.raises(DependencyGraphError, match="duplicate edge contradiction"):
        graph.add_edge("a", "b", DependencyEdgeType.IMPORTS, _reason("other"))

    with pytest.raises(DependencyGraphError, match="unknown from_id"):
        ProofDependencyGraph().add_edge(
            "missing", "also", DependencyEdgeType.IMPORTS, _reason("x")
        )


def test_node_contradiction_and_truncated_frontier() -> None:
    graph = ProofDependencyGraph()
    graph.add_node("n", DependencyNodeKind.UNIT, label="unit-n")
    with pytest.raises(DependencyGraphError, match="duplicate node contradiction"):
        graph.add_node("n", DependencyNodeKind.ARTIFACT)
    truncated = graph.mark_truncated("n")
    assert truncated.truncated is True
    with pytest.raises(DependencyGraphError, match="truncated dependency root"):
        compute_dependency_root(graph, "n", require_complete=True)
    incomplete = compute_dependency_root(graph, "n", require_complete=False)
    assert incomplete.complete is False
    with pytest.raises(DependencyGraphError, match="truncated dependency roots fail closed"):
        incomplete.root_cid()


# ---------------------------------------------------------------------------
# Acceptance: insertion order cannot affect roots
# ---------------------------------------------------------------------------


def test_insertion_order_cannot_affect_roots_or_graph_cid() -> None:
    forward = sample_dependency_graph()
    reverse = ProofDependencyGraph()
    for node in reversed(forward.nodes()):
        reverse.add_node(
            node.node_id, node.kind, label=node.label, truncated=node.truncated
        )
    for edge in reversed(forward.edges()):
        reverse.add_edge(
            edge.from_id, edge.to_id, edge.edge_type, edge.reason_cid
        )

    assert forward.graph_cid() == reverse.graph_cid()
    assert forward.to_canonical_json() == reverse.to_canonical_json()
    assert [e.sort_key() for e in forward.edges()] == [
        e.sort_key() for e in reverse.edges()
    ]

    for unit_id in ("unit/formal", "unit/test", "aggregate/receipt", "unit/static"):
        left = compute_dependency_root(forward, unit_id)
        right = compute_dependency_root(reverse, unit_id)
        assert left.root_cid() == right.root_cid()
        assert left.prerequisite_node_ids == right.prerequisite_node_ids
        assert left.reason_cids == right.reason_cids
        assert left.edge_cids == right.edge_cids
        assert left.complete is True


def test_shuffled_edge_batches_yield_identical_roots() -> None:
    """Different construction orders of the same logical edges share roots."""

    specs = [
        ("src", "mid", DependencyEdgeType.SOURCE_DEPENDS_ON, "r1"),
        ("mid", "leaf", DependencyEdgeType.PROOF_DEPENDS_ON, "r2"),
        ("fix", "leaf", DependencyEdgeType.FIXTURE_DEPENDS_ON, "r3"),
        ("cfg", "leaf", DependencyEdgeType.CONFIG_DEPENDS_ON, "r4"),
        ("leaf", "agg", DependencyEdgeType.AGGREGATE_CONTAINS, "r5"),
    ]
    roots: list[str] = []
    for order in (specs, list(reversed(specs)), [specs[i] for i in (2, 0, 4, 1, 3)]):
        graph = ProofDependencyGraph()
        for node_id, kind in (
            ("src", DependencyNodeKind.ARTIFACT),
            ("mid", DependencyNodeKind.UNIT),
            ("leaf", DependencyNodeKind.UNIT),
            ("fix", DependencyNodeKind.FIXTURE),
            ("cfg", DependencyNodeKind.CONFIG),
            ("agg", DependencyNodeKind.AGGREGATE),
        ):
            graph.add_node(node_id, kind)
        for from_id, to_id, edge_type, reason in order:
            graph.add_edge(from_id, to_id, edge_type, _reason(reason))
        roots.append(compute_dependency_root(graph, "leaf").root_cid())
        roots.append(compute_dependency_root(graph, "agg").root_cid())
    assert roots[0] == roots[2] == roots[4]
    assert roots[1] == roots[3] == roots[5]


# ---------------------------------------------------------------------------
# Acceptance: changed prerequisite reaches every dependent aggregate
# ---------------------------------------------------------------------------


def test_changed_prerequisite_reaches_every_dependent_aggregate() -> None:
    graph = sample_dependency_graph()
    closure = graph.invalidation_closure("artifact/mod.py")
    # Source change walks: artifact -> symbol / static; symbol -> test / static;
    # static/test -> formal; formal/test -> aggregate/receipt.
    assert "artifact/mod.py" in closure
    assert "symbol/mod.fn" in closure
    assert "unit/static" in closure
    assert "unit/test" in closure
    assert "unit/formal" in closure
    assert "aggregate/receipt" in closure

    # Fixture change reaches test and its aggregate, not the static-only path alone.
    fixture_closure = graph.invalidation_closure("fixture/data")
    assert "fixture/data" in fixture_closure
    assert "unit/test" in fixture_closure
    assert "unit/formal" in fixture_closure
    assert "aggregate/receipt" in fixture_closure

    # Schema change reaches static analysis, formal, and aggregate.
    schema_closure = set(graph.invalidation_closure("schema/api"))
    assert {"schema/api", "unit/static", "unit/formal", "aggregate/receipt"} <= schema_closure

    # Direct aggregate containment: child change reaches the aggregate.
    child_graph = ProofDependencyGraph()
    child_graph.add_node("child", DependencyNodeKind.UNIT)
    child_graph.add_node("agg-a", DependencyNodeKind.AGGREGATE)
    child_graph.add_node("agg-b", DependencyNodeKind.AGGREGATE)
    child_graph.add_edge(
        "child", "agg-a", DependencyEdgeType.AGGREGATE_CONTAINS, _reason("a")
    )
    child_graph.add_edge(
        "child", "agg-b", DependencyEdgeType.AGGREGATE_CONTAINS, _reason("b")
    )
    child_closure = set(child_graph.forward_dependents("child"))
    assert child_closure == {"child", "agg-a", "agg-b"}


def test_supersedes_and_invalidates_forward_walk() -> None:
    graph = ProofDependencyGraph()
    graph.add_node("old", DependencyNodeKind.UNIT)
    graph.add_node("new", DependencyNodeKind.UNIT)
    graph.add_node("poisoned", DependencyNodeKind.UNIT)
    graph.add_edge("old", "new", DependencyEdgeType.SUPERSEDES, _reason("sup"))
    graph.add_edge(
        "old", "poisoned", DependencyEdgeType.INVALIDATES, _reason("inv")
    )
    closure = set(graph.invalidation_closure("old"))
    assert closure == {"old", "new", "poisoned"}


# ---------------------------------------------------------------------------
# Acceptance: unrelated nodes remain outside closure
# ---------------------------------------------------------------------------


def test_unrelated_nodes_remain_outside_closure() -> None:
    graph = sample_dependency_graph()
    from_artifact = set(graph.invalidation_closure("artifact/mod.py"))
    assert "unit/unrelated" not in from_artifact
    assert "aggregate/unrelated" not in from_artifact

    from_unrelated = set(graph.invalidation_closure("unit/unrelated"))
    assert from_unrelated == {"unit/unrelated", "aggregate/unrelated"}
    assert "unit/formal" not in from_unrelated
    assert "aggregate/receipt" not in from_unrelated
    assert "artifact/mod.py" not in from_unrelated

    # Prerequisite roots for formal must not pull in the unrelated island.
    formal_root = compute_dependency_root(graph, "unit/formal")
    assert "unit/unrelated" not in formal_root.prerequisite_node_ids
    assert "aggregate/unrelated" not in formal_root.prerequisite_node_ids
    # Aggregate is a dependent of formal, not a prerequisite.
    assert "aggregate/receipt" not in formal_root.prerequisite_node_ids
    assert "artifact/mod.py" in formal_root.prerequisite_node_ids
    assert "fixture/data" in formal_root.prerequisite_node_ids


def test_forward_dependents_can_exclude_seeds() -> None:
    graph = sample_dependency_graph()
    only_dependents = set(
        graph.forward_dependents("fixture/data", include_seeds=False)
    )
    assert "fixture/data" not in only_dependents
    assert "unit/test" in only_dependents
    assert "aggregate/receipt" in only_dependents
    assert "unit/unrelated" not in only_dependents


# ---------------------------------------------------------------------------
# Roots, paths, and determinism
# ---------------------------------------------------------------------------


def test_compute_dependency_root_commits_to_nodes_and_reasons() -> None:
    graph = sample_dependency_graph()
    root = compute_dependency_root(graph, "unit/formal")
    assert root.complete is True
    assert root.unit_id == "unit/formal"
    assert root.dependency_graph_schema_version == "graph@1"
    # Transitive prerequisites include the full relevant chain.
    expected = {
        "unit/formal",
        "unit/static",
        "unit/test",
        "symbol/mod.fn",
        "artifact/mod.py",
        "fixture/data",
        "config/env",
        "schema/api",
    }
    assert set(root.prerequisite_node_ids) == expected
    assert list(root.prerequisite_node_ids) == sorted(expected)
    assert root.reason_cids
    assert root.edge_cids
    assert list(root.reason_cids) == sorted(root.reason_cids)
    # Recompute is byte-identical.
    again = compute_dependency_root(graph, "unit/formal")
    assert again.root_cid() == root.root_cid()
    assert again.to_canonical_json() == root.to_canonical_json()


def test_explanation_paths_are_deterministic() -> None:
    graph = sample_dependency_graph()
    paths_a = graph.explanation_paths("artifact/mod.py", "aggregate/receipt")
    paths_b = graph.explanation_paths("artifact/mod.py", "aggregate/receipt")
    assert paths_a == paths_b
    assert paths_a  # at least one path exists
    # Every path is a connected prerequisite -> dependent chain.
    for path in paths_a:
        assert path[0].from_id == "artifact/mod.py"
        assert path[-1].to_id == "aggregate/receipt"
        for left, right in zip(path, path[1:]):
            assert left.to_id == right.from_id
    # Unrelated endpoints yield no path.
    assert graph.explanation_paths("unit/unrelated", "aggregate/receipt") == ()


def test_edge_and_node_round_trip() -> None:
    edge = ProofDependencyEdge(
        from_id="a",
        to_id="b",
        edge_type=DependencyEdgeType.TEST_COVERS,
        reason_cid=_reason("covers"),
    )
    restored_edge = ProofDependencyEdge.from_canonical(edge.to_canonical())
    assert restored_edge == edge
    assert restored_edge.edge_cid() == edge.edge_cid()
    assert restored_edge.prerequisite_id == "a"
    assert restored_edge.dependent_id == "b"

    node = ProofDependencyNode(
        node_id="symbol/x",
        kind=DependencyNodeKind.SYMBOL,
        label="x",
    )
    restored_node = ProofDependencyNode.from_canonical(node.to_canonical())
    assert restored_node == node

    graph = sample_dependency_graph()
    restored = ProofDependencyGraph.from_canonical(graph.to_canonical())
    assert restored.graph_cid() == graph.graph_cid()
    assert restored.edge_count() == graph.edge_count()


def test_known_vectors_are_deterministic_and_order_invariant() -> None:
    first = known_vectors()
    second = known_vectors()
    assert first == second
    assert first["subset"] == DEPENDENCY_GRAPH_SUBSET
    assert first["graph_cid"] == first["reversed_graph_cid"]
    assert first["formal_root_cid"] == first["reversed_formal_root_cid"]
    assert "unit/unrelated" not in first["invalidation_from_artifact"]
    assert "aggregate/receipt" in first["invalidation_from_artifact"]
    assert first["closed_edge_types"] == list(DEPENDENCY_EDGE_TYPES)
    # Root CID is a strict profile CID.
    assert first["formal_root_cid"] == canonical_cid(
        compute_dependency_root(
            sample_dependency_graph(), "unit/formal"
        ).to_canonical()
    )


def test_dependency_root_rejects_unsorted_inputs() -> None:
    with pytest.raises(DependencyGraphError, match="canonically sorted"):
        DependencyRoot(
            unit_id="u",
            prerequisite_node_ids=("b", "a"),
            reason_cids=(),
            edge_cids=(),
            complete=True,
        )


def test_module_import_is_hermetic() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, sys; "
                "assert 'multiformats' not in sys.modules; "
                "mod = importlib.import_module("
                f"'{MODULE_NAME}'"
                "); "
                "assert mod.DEPENDENCY_GRAPH_SUBSET == 'ips/dependency-graph@1'; "
                "assert len(mod.DEPENDENCY_EDGE_TYPES) == 11; "
                "g = mod.ProofDependencyGraph(); "
                "g.add_node('a', mod.DependencyNodeKind.UNIT); "
                "g.add_node('b', mod.DependencyNodeKind.UNIT); "
                # Edge add without minting a CID must not pull multiformats until reason is validated;
                # constructing with a non-CID reason fails closed before provider load for pseudo forms,
                # but we only check that import of the module stayed hermetic.
                "assert 'multiformats' not in sys.modules; "
                "assert 'provekit' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_sample_reason_and_mint_are_stable() -> None:
    assert sample_reason("x") == sample_reason("x")
    assert sample_reason("x") != sample_reason("y")
    assert mint_reason_cid({"k": 1}) == mint_reason_cid({"k": 1})


def test_adjacency_helpers_are_sorted() -> None:
    graph = ProofDependencyGraph()
    graph.add_node("p", DependencyNodeKind.UNIT)
    graph.add_node("z", DependencyNodeKind.UNIT)
    graph.add_node("a", DependencyNodeKind.UNIT)
    graph.add_edge("p", "z", DependencyEdgeType.CALLS, _reason("z"))
    graph.add_edge("p", "a", DependencyEdgeType.CALLS, _reason("a"))
    assert graph.dependents("p") == ("a", "z")
    assert graph.prerequisites("a") == ("p",)
    out = graph.outgoing_edges("p")
    assert [edge.to_id for edge in out] == ["a", "z"]


def test_module_reloads_cleanly() -> None:
    module = importlib.import_module(MODULE_NAME)
    reloaded = importlib.reload(module)
    assert reloaded.DEPENDENCY_GRAPH_SUBSET == "ips/dependency-graph@1"
    assert len(reloaded.closed_dependency_edge_types()) == 11
