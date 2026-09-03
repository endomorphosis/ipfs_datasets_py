"""Deterministic static program-graph construction and invalidation (SAWM-006)."""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_state.program_graph import (
    ProgramGraphEdgeKind,
    ProgramGraphNodeKind,
    apply_program_graph_delta,
    is_unresolved_dynamic_edge,
    is_unresolved_dynamic_node,
)
from ipfs_datasets_py.logic.software_verification.program_graph_builder import (
    CONSTRUCTED_DIMENSIONS,
    IMPORT_SCAN_PERFORMED,
    PROGRAM_GRAPH_BUILDER_INTERFACE,
    PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE,
    PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE,
    ProgramGraphBuildReceipt,
    ProgramGraphBuilder,
    ProgramGraphBuilderError,
    ProgramGraphCoverageReceipt,
    ProgramGraphInvalidationPlanner,
    build_program_graph,
    compute_program_graph_delta,
    plan_program_graph_invalidation,
)


STABLE = "def const() -> int:\n    return 1\n"
PING_PONG = """
def ping():
    return pong()

def pong():
    return ping()
"""
WRAP = "from pkg.a import ping\n\ndef wrap():\n    return ping()\n"
DYNAMIC = """
def hidden(name):
    return getattr(hidden, name)

def boom(code):
    return eval(code)
"""
TYPED = """
def add(x: int, y: int) -> int:
    assert x >= 0
    if y:
        z = x + y
    else:
        z = x
    return z
"""
EXC = """
class Error(Exception):
    pass

def run():
    try:
        raise Error()
    except Error:
        return 1
"""
NATIVE = """
import ctypes

def load():
    return ctypes.CDLL("libc.so.6")
"""
TEST_A = """
from pkg.a import ping

def test_ping():
    assert ping() is not None
"""
CYCLE_C = "from pkg import d\n\ndef f():\n    return d.g()\n"
CYCLE_D = "from pkg import c\n\ndef g():\n    return c.f()\n"
STAR = "from pkg.a import *\n\ndef use_star(name):\n    return name\n"


def _tree(**overrides: str) -> dict[str, str]:
    sources = {
        "pkg/__init__.py": "",
        "pkg/a.py": PING_PONG,
        "pkg/b.py": WRAP,
        "pkg/dyn.py": DYNAMIC,
        "pkg/typed.py": TYPED,
        "pkg/exc.py": EXC,
        "pkg/native.py": NATIVE,
        "pkg/stable.py": STABLE,
        "pkg/c.py": CYCLE_C,
        "pkg/d.py": CYCLE_D,
        "pkg/star.py": STAR,
        "tests/test_a.py": TEST_A,
    }
    sources.update(overrides)
    return sources


def _kinds(receipt: ProgramGraphBuildReceipt) -> set[str]:
    return {str(node.node_kind) for node in receipt.nodes}


def _edge_kinds(receipt: ProgramGraphBuildReceipt) -> set[str]:
    return {str(edge.edge_kind) for edge in receipt.edges}


def test_public_interfaces_and_symbols_are_versioned() -> None:
    assert PROGRAM_GRAPH_BUILDER_INTERFACE == "ProgramGraphBuilder@1"
    assert PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE == "ProgramGraphBuildReceipt@1"
    assert PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE == "ProgramGraphInvalidationPlanner@1"
    assert callable(build_program_graph)
    assert callable(compute_program_graph_delta)
    assert callable(plan_program_graph_invalidation)
    assert ProgramGraphBuilder.INTERFACE == PROGRAM_GRAPH_BUILDER_INTERFACE
    assert ProgramGraphBuildReceipt.INTERFACE == PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE


def test_import_does_not_scan_a_source_tree() -> None:
    assert IMPORT_SCAN_PERFORMED is False


def test_in_memory_build_does_not_walk_the_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("filesystem scan is forbidden during in-memory construction")

    monkeypatch.setattr(os, "walk", boom)
    monkeypatch.setattr(os, "scandir", boom)
    monkeypatch.setattr(Path, "rglob", boom)
    monkeypatch.setattr(Path, "glob", boom)
    receipt = build_program_graph({"mod.py": STABLE})
    assert receipt.snapshot.node_cids
    assert receipt.coverage.unit_count == 1


def test_repeated_builds_are_byte_identical() -> None:
    first = build_program_graph(_tree(), environment_binding={"python": "3.12"})
    second = build_program_graph(_tree(), environment_binding={"python": "3.12"})
    assert first.snapshot.program_graph_snapshot_cid == second.snapshot.program_graph_snapshot_cid
    assert first.snapshot.canonical_program_graph_cid == second.snapshot.canonical_program_graph_cid
    assert first.program_graph_build_receipt_cid == second.program_graph_build_receipt_cid
    assert first.snapshot.edge_cids == second.snapshot.edge_cids
    assert first.snapshot.node_cids == second.snapshot.node_cids


def test_source_mapping_order_does_not_change_canonical_identity() -> None:
    tree = _tree()
    forward = build_program_graph(OrderedDict(sorted(tree.items())))
    reverse = build_program_graph(OrderedDict(reversed(list(tree.items()))))
    assert forward.snapshot.canonical_program_graph_cid == reverse.snapshot.canonical_program_graph_cid
    assert forward.snapshot.program_graph_snapshot_cid == reverse.snapshot.program_graph_snapshot_cid
    assert list(forward.snapshot.edge_cids) == sorted(forward.snapshot.edge_cids)
    assert list(forward.snapshot.node_cids) == sorted(forward.snapshot.node_cids)


def test_incremental_matches_full_rebuild() -> None:
    tree = _tree()
    full = build_program_graph(tree)
    incremental = build_program_graph(tree, previous=full, incremental=True)
    assert incremental.incremental is True
    assert full.snapshot.canonical_program_graph_cid == incremental.snapshot.canonical_program_graph_cid
    assert full.snapshot.program_graph_snapshot_cid == incremental.snapshot.program_graph_snapshot_cid
    assert full.snapshot.node_cids == incremental.snapshot.node_cids
    assert full.snapshot.edge_cids == incremental.snapshot.edge_cids


def test_coverage_receipt_lists_every_constructed_dimension() -> None:
    receipt = build_program_graph(_tree())
    assert isinstance(receipt.coverage, ProgramGraphCoverageReceipt)
    assert tuple(receipt.coverage.constructed_dimensions) == CONSTRUCTED_DIMENSIONS
    assert set(_kinds(receipt)) >= {
        ProgramGraphNodeKind.MODULE.value,
        ProgramGraphNodeKind.PACKAGE.value,
        ProgramGraphNodeKind.SOURCE.value,
        ProgramGraphNodeKind.AST.value,
        ProgramGraphNodeKind.FUNCTION.value,
        ProgramGraphNodeKind.CLASS.value,
        ProgramGraphNodeKind.CALLSITE.value,
        ProgramGraphNodeKind.IMPORT_BINDING.value,
        ProgramGraphNodeKind.CFG_BLOCK.value,
        ProgramGraphNodeKind.DATA_FLOW.value,
        ProgramGraphNodeKind.EXCEPTION_HANDLER.value,
        ProgramGraphNodeKind.TYPE_BINDING.value,
        ProgramGraphNodeKind.EFFECT.value,
        ProgramGraphNodeKind.CONTRACT_STATE.value,
        ProgramGraphNodeKind.TEST.value,
        ProgramGraphNodeKind.PROOF_OBLIGATION.value,
        ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
    }
    assert set(_edge_kinds(receipt)) >= {
        ProgramGraphEdgeKind.CONTAINS.value,
        ProgramGraphEdgeKind.DECLARES.value,
        ProgramGraphEdgeKind.IMPORTS.value,
        ProgramGraphEdgeKind.CALLS.value,
        ProgramGraphEdgeKind.CFG_NEXT.value,
        ProgramGraphEdgeKind.DATA_FLOW.value,
        ProgramGraphEdgeKind.EXCEPTION_EDGE.value,
        ProgramGraphEdgeKind.TYPE_OF.value,
        ProgramGraphEdgeKind.EFFECT_OF.value,
        ProgramGraphEdgeKind.BINDS_CONTRACT.value,
        ProgramGraphEdgeKind.TESTED_BY.value,
        ProgramGraphEdgeKind.PROVED_BY.value,
        ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
        ProgramGraphEdgeKind.RAISES.value,
        ProgramGraphEdgeKind.CATCHES.value,
        ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
        ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
    }


def test_dynamic_and_reflection_stay_on_the_frontier() -> None:
    receipt = build_program_graph(_tree())
    assert receipt.frontiers
    reasons = set(receipt.coverage.dynamic_reasons)
    assert {"eval", "reflection"} <= reasons or {"exec", "reflection"} <= reasons or "eval" in reasons
    assert any(is_unresolved_dynamic_node(node) for node in receipt.nodes)
    assert any(is_unresolved_dynamic_edge(edge) for edge in receipt.edges)
    frontier = receipt.frontiers[0]
    assert frontier.unresolved_node_cids or frontier.unavailable_dimensions
    hidden = receipt.node_by_name("function", "pkg.dyn.hidden")
    boom = receipt.node_by_name("function", "pkg.dyn.boom")
    assert hidden.unavailable_dimensions or any(
        edge.source_node_cid == hidden.program_graph_node_cid and is_unresolved_dynamic_edge(edge)
        for edge in receipt.edges
    )
    assert boom.unavailable_dimensions or any(
        edge.source_node_cid == boom.program_graph_node_cid and is_unresolved_dynamic_edge(edge)
        for edge in receipt.edges
    )


def test_native_calls_and_star_imports_are_incomplete_not_omitted() -> None:
    receipt = build_program_graph(_tree())
    native = receipt.node_by_name("function", "pkg.native.load")
    assert "effect" in native.unavailable_dimensions or any(
        str(edge.edge_kind) == ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value
        and edge.source_node_cid in {node.program_graph_node_cid for node in receipt.nodes_of_kind("callsite")}
        for edge in receipt.edges
    )
    assert "import" in receipt.coverage.incomplete_dimensions
    star_module = receipt.node_by_name("module", "pkg.star")
    assert star_module.unavailable_dimensions or any(
        str(node.node_kind) == ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value
        and "star" in node.logical_name
        for node in receipt.nodes
    )


def test_mutual_recursion_and_cyclic_imports_are_logical_cycle_records() -> None:
    receipt = build_program_graph(_tree())
    mutual = receipt.edges_of_kind(ProgramGraphEdgeKind.MUTUAL_RECURSION.value)
    assert mutual
    assert all(edge.logical_cycle for edge in mutual)
    cyclic = receipt.edges_of_kind(ProgramGraphEdgeKind.CYCLIC_IMPORT.value)
    assert cyclic
    assert all(edge.logical_cycle for edge in cyclic)
    ping = receipt.node_by_name("function", "pkg.a.ping")
    pong = receipt.node_by_name("function", "pkg.a.pong")
    related = {
        ping.program_graph_node_cid,
        pong.program_graph_node_cid,
    }
    assert any(
        edge.source_node_cid in related and edge.target_node_cid in related for edge in mutual
    )


def test_cfg_data_flow_exception_type_contract_test_and_proof_projections() -> None:
    receipt = build_program_graph(_tree())
    add = receipt.node_by_name("function", "pkg.typed.add")
    assert any(
        str(edge.edge_kind) == ProgramGraphEdgeKind.TYPE_OF.value
        and edge.source_node_cid == add.program_graph_node_cid
        for edge in receipt.edges
    )
    assert any(
        str(edge.edge_kind) == ProgramGraphEdgeKind.BINDS_CONTRACT.value
        and edge.source_node_cid == add.program_graph_node_cid
        for edge in receipt.edges
    )
    assert any(
        str(edge.edge_kind) == ProgramGraphEdgeKind.PROVED_BY.value
        and edge.source_node_cid == add.program_graph_node_cid
        for edge in receipt.edges
    )
    assert receipt.nodes_of_kind("cfg_block")
    assert receipt.nodes_of_kind("data_flow")
    assert receipt.nodes_of_kind("exception_handler")
    assert receipt.nodes_of_kind("test")
    assert receipt.edges_of_kind(ProgramGraphEdgeKind.TESTED_BY.value)
    assert receipt.proof_obligation_graphs
    assert receipt.successor_sets
    assert receipt.index_manifests


def test_parse_errors_are_incomplete_current_tree_nodes() -> None:
    receipt = build_program_graph({"broken.py": "def nope(\n", "ok.py": STABLE})
    assert "broken.py" in receipt.coverage.parse_error_paths
    source = receipt.node_by_name("source", "broken.py")
    assert source.unavailable_dimensions
    assert receipt.node_by_name("function", "ok.const")
    assert set(CONSTRUCTED_DIMENSIONS) <= set(receipt.coverage.incomplete_dimensions) or source.unavailable_dimensions


def test_unsupported_language_fails_closed() -> None:
    with pytest.raises(ProgramGraphBuilderError, match="unavailable"):
        build_program_graph({"mod.py": STABLE}, language="javascript")


def test_non_python_units_are_marked_incomplete() -> None:
    receipt = build_program_graph({"readme.txt": "not python\n", "mod.py": STABLE})
    source = receipt.node_by_name("source", "readme.txt")
    assert source.unavailable_dimensions
    assert receipt.node_by_name("function", "mod.const")


def test_changed_and_unchanged_subroots_and_exact_delta() -> None:
    previous = build_program_graph(_tree())
    changed = _tree(
        **{
            "pkg/a.py": "def ping():\n    return pong()\n\ndef pong():\n    return 2\n",
        }
    )
    current = build_program_graph(changed)
    delta = compute_program_graph_delta(previous, current)
    assert delta.previous_snapshot_cid == previous.snapshot.program_graph_snapshot_cid
    ping_prev = previous.node_by_name("function", "pkg.a.ping")
    pong_prev = previous.node_by_name("function", "pkg.a.pong")
    stable_prev = previous.node_by_name("function", "pkg.stable.const")
    wrap_prev = previous.node_by_name("function", "pkg.b.wrap")
    assert ping_prev.program_graph_node_cid in delta.removed_node_cids
    assert pong_prev.program_graph_node_cid in delta.removed_node_cids
    assert stable_prev.program_graph_node_cid in delta.retained_subroot_cids
    assert wrap_prev.program_graph_node_cid in delta.retained_subroot_cids
    applied = apply_program_graph_delta(previous.snapshot, delta)
    assert set(applied["node_cids"]) == set(current.snapshot.node_cids)
    assert set(applied["edge_cids"]) == set(current.snapshot.edge_cids)


def test_invalidation_is_precise_and_never_omits_dependents() -> None:
    previous = build_program_graph(_tree())
    current = build_program_graph(
        _tree(
            **{
                "pkg/a.py": "def ping():\n    return pong()\n\ndef pong():\n    return 2\n",
            }
        )
    )
    plan = plan_program_graph_invalidation(previous, current)
    assert plan.omitted_dependents is False
    assert plan.conservative is True
    ping = previous.node_by_name("function", "pkg.a.ping")
    wrap = previous.node_by_name("function", "pkg.b.wrap")
    stable = previous.node_by_name("function", "pkg.stable.const")
    test_ping = previous.node_by_name("test", "tests.test_a.test_ping")
    assert ping.program_graph_node_cid in plan.invalidated_node_cids
    assert wrap.program_graph_node_cid in plan.invalidated_node_cids
    assert test_ping.program_graph_node_cid in plan.invalidated_node_cids
    assert stable.program_graph_node_cid in plan.retained_subroot_cids
    assert stable.program_graph_node_cid not in plan.invalidated_node_cids
    planner = ProgramGraphInvalidationPlanner()
    again = planner.plan(previous, current)
    assert again.invalidated_node_cids == plan.invalidated_node_cids


def test_environment_change_invalidates_the_whole_previous_graph() -> None:
    previous = build_program_graph(_tree(), environment_binding={"python": "3.12"})
    current = build_program_graph(_tree(), environment_binding={"python": "3.13"})
    plan = plan_program_graph_invalidation(previous, current)
    assert plan.environment_changed is True
    assert set(plan.invalidated_node_cids) == set(previous.snapshot.node_cids)
    assert plan.retained_subroot_cids == ()


def test_dynamic_frontier_widens_invalidation_without_treating_unknown_as_absent() -> None:
    previous = build_program_graph(_tree())
    current = build_program_graph(
        _tree(**{"pkg/typed.py": "def add(x: int, y: int) -> int:\n    return x - y\n"})
    )
    plan = plan_program_graph_invalidation(previous, current)
    dynamic_nodes = [
        node.program_graph_node_cid
        for node in previous.nodes
        if is_unresolved_dynamic_node(node)
    ]
    assert dynamic_nodes
    assert set(dynamic_nodes) <= set(plan.invalidated_node_cids)
    assert previous.node_by_name("function", "pkg.stable.const").program_graph_node_cid in plan.retained_subroot_cids


def test_builder_rejects_absolute_and_parent_paths() -> None:
    with pytest.raises(ProgramGraphBuilderError):
        build_program_graph({"/tmp/mod.py": STABLE})
    with pytest.raises(ProgramGraphBuilderError):
        build_program_graph({"../mod.py": STABLE})
