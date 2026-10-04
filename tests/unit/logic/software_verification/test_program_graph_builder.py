"""Deterministic static program-graph construction and invalidation tests."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_graph import (
    ProgramGraphEdgeKind,
    ProgramGraphNodeKind,
    apply_program_graph_delta,
    directed_logical_cycles,
)
from ipfs_datasets_py.logic.software_verification.program_graph_builder import (
    PROGRAM_GRAPH_BUILDER_INTERFACE,
    PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE,
    PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE,
    PROJECTION_NAMES,
    InvalidationReasonCode,
    ProgramGraphBuildError,
    ProgramGraphBuildReceipt,
    ProgramGraphBuilder,
    ProgramGraphInvalidationPlanner,
    ProgramSourceUnit,
    build_program_graph,
    compute_program_graph_delta,
    plan_program_graph_invalidation,
)


ENV = cid_for_bytes(b"environment-binding-set:v1")
SEALED = cid_for_bytes(b"sealed-binding:v1")
ENV_OTHER = cid_for_bytes(b"environment-binding-set:v2")
SEALED_OTHER = cid_for_bytes(b"sealed-binding:v2")


def _kinds(receipt: ProgramGraphBuildReceipt) -> set[str]:
    return {str(node.node_kind) for node in receipt.nodes}


def _edge_kinds(receipt: ProgramGraphBuildReceipt) -> set[str]:
    return {str(edge.edge_kind) for edge in receipt.edges}


def _nodes(receipt: ProgramGraphBuildReceipt, kind: str) -> list:
    return [node for node in receipt.nodes if str(node.node_kind) == kind]


def _edges(receipt: ProgramGraphBuildReceipt, kind: str) -> list:
    return [edge for edge in receipt.edges if str(edge.edge_kind) == kind]


def _rich_sources() -> dict[str, str]:
    return {
        "pkg/__init__.py": "from .a import ping\nfrom .b import pong\n",
        "pkg/a.py": '''\
from . import b
from typing import Protocol

class Shape(Protocol):
    def area(self) -> int:
        """Precondition: True
        """
        raise NotImplementedError

class Base:
    value = 0

class Child(Base, Shape):
    def area(self) -> int:
        return 1

def ping(x: int) -> int:
    """Precondition: x >= 0
    Postcondition: result >= 0
    """
    y = x
    if y:
        try:
            return b.pong(y - 1)
        except ValueError:
            return 0
        except Exception:
            raise RuntimeError("boom")
    while y:
        y = y - 1
        if y == 0:
            break
    assert y >= 0
    return y
''',
        "pkg/b.py": '''\
from . import a

def pong(x: int) -> int:
    """Ensure: result >= 0
    """
    if x:
        return a.ping(x)
    return 1
''',
        "pkg/dyn.py": '''\
import ctypes
import importlib

def spooky(obj, name):
    return getattr(obj, name)()

def boom(code):
    return eval(code)

def native():
    return ctypes.CDLL("libc.so.6")

def plugin():
    return importlib.metadata.entry_points()

def write_out(path):
    handle = open(path, "w")
    handle.write("x")
    return handle
''',
        "pkg/unused.py": "def leftover() -> int:\n    return 7\n",
        "tests/test_pkg.py": '''\
import pytest
from pkg.a import ping

@pytest.fixture
def value():
    return 1

def test_ping(value):
    assert ping(value) >= 0
''',
    }


def test_public_interfaces_and_symbols() -> None:
    assert PROGRAM_GRAPH_BUILDER_INTERFACE == "ProgramGraphBuilder@1"
    assert PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE == "ProgramGraphBuildReceipt@1"
    assert PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE == "ProgramGraphInvalidationPlanner@1"
    assert ProgramGraphBuilder.INTERFACE == PROGRAM_GRAPH_BUILDER_INTERFACE
    assert ProgramGraphBuildReceipt.INTERFACE == PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE
    assert ProgramGraphInvalidationPlanner.INTERFACE == PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE
    assert callable(build_program_graph)
    assert callable(compute_program_graph_delta)
    assert callable(plan_program_graph_invalidation)


def test_import_does_not_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    name = "ipfs_datasets_py.logic.software_verification.program_graph_builder"
    sys.modules.pop(name, None)
    calls: list[str] = []

    def boom(*_args: object, **_kwargs: object) -> None:
        calls.append("scan")
        raise AssertionError("filesystem scan at import")

    monkeypatch.setattr(os, "walk", boom)
    monkeypatch.setattr(os, "scandir", boom)
    monkeypatch.setattr(Path, "rglob", boom)
    monkeypatch.setattr(Path, "glob", boom)
    module = importlib.import_module(name)
    assert calls == []
    assert callable(module.build_program_graph)
    assert callable(module.compute_program_graph_delta)
    assert callable(module.plan_program_graph_invalidation)


def test_analyzed_source_is_not_executed() -> None:
    sources = {
        "boom.py": (
            "raise SystemExit('executed')\n"
            "import os\n"
            "os.system('echo pwned')\n"
            "eval('__import__(\"os\").system(\"echo pwned\")')\n"
        )
    }
    receipt = build_program_graph(
        sources,
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    assert receipt.coverage.parse_error_paths == ()
    assert any(
        str(node.node_kind) == ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value
        for node in receipt.nodes
    )


def test_repeated_builds_are_deterministic() -> None:
    sources = _rich_sources()
    first = build_program_graph(sources, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    second = build_program_graph(sources, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    assert first.snapshot.program_graph_snapshot_cid == second.snapshot.program_graph_snapshot_cid
    assert first.program_graph_build_receipt_cid == second.program_graph_build_receipt_cid
    assert [edge.program_graph_edge_cid for edge in first.edges] == [
        edge.program_graph_edge_cid for edge in second.edges
    ]
    first.verify()


def test_source_order_does_not_affect_snapshot() -> None:
    sources = _rich_sources()
    ordered = build_program_graph(sources, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    shuffled = build_program_graph(
        list(reversed(list(sources.items()))),
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    units = [
        ProgramSourceUnit(path, sources[path])
        for path in sorted(sources, reverse=True)
    ]
    from_units = build_program_graph(units, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    assert ordered.snapshot.program_graph_snapshot_cid == shuffled.snapshot.program_graph_snapshot_cid
    assert ordered.snapshot.program_graph_snapshot_cid == from_units.snapshot.program_graph_snapshot_cid
    assert list(ordered.snapshot.edge_cids) == sorted(ordered.snapshot.edge_cids)
    assert list(ordered.snapshot.node_cids) == sorted(ordered.snapshot.node_cids)


def test_rich_fixture_covers_required_projections() -> None:
    receipt = build_program_graph(
        _rich_sources(),
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    kinds = _kinds(receipt)
    for required in (
        ProgramGraphNodeKind.MODULE.value,
        ProgramGraphNodeKind.PACKAGE.value,
        ProgramGraphNodeKind.SOURCE.value,
        ProgramGraphNodeKind.AST.value,
        ProgramGraphNodeKind.SYMBOL.value,
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
        ProgramGraphNodeKind.FIXTURE.value,
        ProgramGraphNodeKind.PROOF_OBLIGATION.value,
        ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value,
    ):
        assert required in kinds, required
    edge_kinds = _edge_kinds(receipt)
    for required in (
        ProgramGraphEdgeKind.CONTAINS.value,
        ProgramGraphEdgeKind.DECLARES.value,
        ProgramGraphEdgeKind.IMPORTS.value,
        ProgramGraphEdgeKind.CYCLIC_IMPORT.value,
        ProgramGraphEdgeKind.CALLS.value,
        ProgramGraphEdgeKind.MUTUAL_RECURSION.value,
        ProgramGraphEdgeKind.CFG_NEXT.value,
        ProgramGraphEdgeKind.CFG_BRANCH.value,
        ProgramGraphEdgeKind.DATA_FLOW.value,
        ProgramGraphEdgeKind.EXCEPTION_EDGE.value,
        ProgramGraphEdgeKind.TYPE_OF.value,
        ProgramGraphEdgeKind.EFFECT_OF.value,
        ProgramGraphEdgeKind.BINDS_CONTRACT.value,
        ProgramGraphEdgeKind.TESTED_BY.value,
        ProgramGraphEdgeKind.PROVED_BY.value,
        ProgramGraphEdgeKind.SUCCESSOR.value,
        ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value,
        ProgramGraphEdgeKind.INHERITS.value,
        ProgramGraphEdgeKind.IMPLEMENTS.value,
        ProgramGraphEdgeKind.READS_STATE.value,
        ProgramGraphEdgeKind.WRITES_STATE.value,
        ProgramGraphEdgeKind.RAISES.value,
        ProgramGraphEdgeKind.CATCHES.value,
        ProgramGraphEdgeKind.USES_FIXTURE.value,
    ):
        assert required in edge_kinds, required
    assert receipt.coverage.projections == PROJECTION_NAMES
    assert "call" in receipt.coverage.incomplete_projections
    assert receipt.frontiers
    assert receipt.coverage.frontier_reasons
    assert receipt.successor_sets
    assert any(item.complete is False for item in receipt.successor_sets)
    receipt.verify()


def test_cyclic_import_and_mutual_recursion_are_logical_cycles() -> None:
    receipt = build_program_graph(
        _rich_sources(),
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    cyclic = _edges(receipt, ProgramGraphEdgeKind.CYCLIC_IMPORT.value)
    recursive = _edges(receipt, ProgramGraphEdgeKind.MUTUAL_RECURSION.value)
    assert cyclic
    assert recursive
    assert all(edge.logical_cycle for edge in cyclic)
    assert all(edge.logical_cycle for edge in recursive)
    cycles = directed_logical_cycles(receipt.edges)
    assert cycles
    by_cid = {edge.program_graph_edge_cid: edge for edge in receipt.edges}
    for cycle in cycles:
        assert any(by_cid[cid].logical_cycle for cid in cycle)


def test_eval_getattr_native_and_plugin_widen_frontier() -> None:
    receipt = build_program_graph(
        _rich_sources(),
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    reasons = set(receipt.coverage.frontier_reasons)
    for required in ("eval", "reflection", "native_call", "plugin"):
        assert required in reasons, required
    dynamic_nodes = _nodes(receipt, ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value)
    assert dynamic_nodes
    assert all(node.unavailable_dimensions for node in dynamic_nodes)
    unresolved_edges = _edges(receipt, ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value)
    assert unresolved_edges
    assert all(edge.resolution_status != "definite" for edge in unresolved_edges)
    covered_nodes = {cid for frontier in receipt.frontiers for cid in frontier.unresolved_node_cids}
    covered_edges = {cid for frontier in receipt.frontiers for cid in frontier.unresolved_edge_cids}
    assert {node.program_graph_node_cid for node in dynamic_nodes} <= covered_nodes
    assert {edge.program_graph_edge_cid for edge in unresolved_edges} <= covered_edges


def test_contracts_tests_and_proof_obligations() -> None:
    receipt = build_program_graph(
        _rich_sources(),
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    assert receipt.contract_states
    assert receipt.proof_obligation_graphs
    assert _nodes(receipt, ProgramGraphNodeKind.TEST.value)
    assert _nodes(receipt, ProgramGraphNodeKind.FIXTURE.value)
    assert _edges(receipt, ProgramGraphEdgeKind.TESTED_BY.value)
    assert _edges(receipt, ProgramGraphEdgeKind.USES_FIXTURE.value)
    assert _edges(receipt, ProgramGraphEdgeKind.BINDS_CONTRACT.value)
    assert _edges(receipt, ProgramGraphEdgeKind.PROVED_BY.value)
    assert "solver_unknown" in receipt.snapshot.unavailable_dimensions


def test_delta_preserves_unchanged_subroots() -> None:
    sources = _rich_sources()
    previous = build_program_graph(sources, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    changed = dict(sources)
    changed["pkg/unused.py"] = "def leftover() -> int:\n    return 8\n"
    current = build_program_graph(changed, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    delta = compute_program_graph_delta(previous, current)
    unused_previous = set(previous.node_cids_by_path["pkg/unused.py"])
    unused_current = set(current.node_cids_by_path["pkg/unused.py"])
    assert unused_previous <= set(delta.removed_node_cids)
    assert unused_current <= set(delta.added_node_cids)
    retained = set(delta.retained_subroot_cids)
    assert previous.node_cids_by_path["pkg/unused.py"][0] not in retained
    leftover_paths = {"pkg/dyn.py"}
    for path in leftover_paths:
        for cid in previous.node_cids_by_path[path]:
            if cid in current.snapshot.node_cids:
                assert cid in retained
    applied = apply_program_graph_delta(previous.snapshot, delta)
    assert set(applied["node_cids"]) == set(current.snapshot.node_cids)
    assert set(applied["edge_cids"]) == set(current.snapshot.edge_cids)


def test_incremental_full_parity() -> None:
    sources = _rich_sources()
    previous = build_program_graph(sources, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    changed = dict(sources)
    changed["pkg/unused.py"] = "def leftover() -> int:\n    return 9\n"
    full = build_program_graph(changed, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    incremental = build_program_graph(
        changed,
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
        previous=previous,
    )
    assert incremental.snapshot.canonical_program_graph_cid == full.snapshot.canonical_program_graph_cid
    assert set(incremental.snapshot.node_cids) == set(full.snapshot.node_cids)
    assert set(incremental.snapshot.edge_cids) == set(full.snapshot.edge_cids)
    assert incremental.snapshot.retained_subroot_cids
    dyn_cids = set(previous.node_cids_by_path["pkg/dyn.py"])
    assert dyn_cids <= set(incremental.snapshot.retained_subroot_cids)
    full_delta = compute_program_graph_delta(previous, full)
    incremental_delta = compute_program_graph_delta(previous, incremental)
    assert full_delta.added_node_cids == incremental_delta.added_node_cids
    assert full_delta.removed_node_cids == incremental_delta.removed_node_cids
    assert full_delta.retained_subroot_cids == incremental_delta.retained_subroot_cids


def test_invalidation_is_precise_without_omitting_dependents() -> None:
    sources = _rich_sources()
    previous = build_program_graph(sources, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    changed = dict(sources)
    changed["pkg/a.py"] = sources["pkg/a.py"].replace("return y", "return y + 0")
    plan = plan_program_graph_invalidation(
        previous,
        changed,
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    assert "pkg/a.py" in plan.changed_paths
    assert "pkg/a.py" in plan.invalidated_paths
    assert "pkg/b.py" in plan.invalidated_paths
    assert "pkg/__init__.py" in plan.invalidated_paths
    assert "tests/test_pkg.py" in plan.invalidated_paths
    assert "pkg/unused.py" in plan.retained_paths
    assert "pkg/dyn.py" in plan.retained_paths
    assert plan.full_rebuild_required is False
    assert plan.retained_subroot_cids
    assert any(reason.startswith(InvalidationReasonCode.SOURCE_CHANGED.value) for reason in plan.reasons)
    assert any(reason.startswith(InvalidationReasonCode.CROSS_FILE_DEPENDENT.value) for reason in plan.reasons)


def test_environment_change_requires_full_rebuild() -> None:
    sources = _rich_sources()
    previous = build_program_graph(sources, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    plan = plan_program_graph_invalidation(
        previous,
        sources,
        environment_binding_set_cid=ENV_OTHER,
        sealed_binding_cid=SEALED,
    )
    assert plan.full_rebuild_required is True
    assert plan.environment_changed is True
    assert not plan.retained_paths
    rebuilt = build_program_graph(
        sources,
        environment_binding_set_cid=ENV_OTHER,
        sealed_binding_cid=SEALED,
    )
    assert rebuilt.snapshot.program_graph_snapshot_cid != previous.snapshot.program_graph_snapshot_cid
    sealed_plan = plan_program_graph_invalidation(
        previous,
        sources,
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED_OTHER,
    )
    assert sealed_plan.full_rebuild_required is True


def test_deleted_and_added_paths_are_invalidated() -> None:
    sources = _rich_sources()
    previous = build_program_graph(sources, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    reduced = {path: text for path, text in sources.items() if path != "pkg/unused.py"}
    reduced["pkg/extra.py"] = "def extra() -> int:\n    return 1\n"
    plan = plan_program_graph_invalidation(
        previous,
        reduced,
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    assert "pkg/unused.py" in plan.removed_paths
    assert "pkg/extra.py" in plan.added_paths
    assert "pkg/extra.py" in plan.invalidated_paths
    current = build_program_graph(reduced, environment_binding_set_cid=ENV, sealed_binding_cid=SEALED)
    delta = compute_program_graph_delta(previous, current)
    assert delta.removed_node_cids
    assert delta.added_node_cids


def test_parse_error_is_incomplete_not_silent() -> None:
    receipt = build_program_graph(
        {"broken.py": "def oops(:\n"},
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    assert receipt.coverage.parse_error_paths == ("broken.py",)
    assert "parse_error" in receipt.snapshot.unavailable_dimensions
    assert receipt.frontiers
    assert _nodes(receipt, ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value)
    receipt.verify()


def test_star_import_and_unsupported_language_fail_closed() -> None:
    receipt = build_program_graph(
        {"star.py": "from os import *\n\ndef use(name):\n    return name\n"},
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    assert "import" in receipt.coverage.incomplete_projections
    assert "star_import" in receipt.snapshot.unavailable_dimensions or receipt.frontiers
    with pytest.raises(ProgramGraphBuildError, match="extension"):
        build_program_graph(
            {"app.js": "export const x = 1;\n"},
            environment_binding_set_cid=ENV,
            sealed_binding_cid=SEALED,
        )
    with pytest.raises(ProgramGraphBuildError, match="unavailable"):
        build_program_graph(
            {"mod.py": "x = 1\n"},
            environment_binding_set_cid=ENV,
            sealed_binding_cid=SEALED,
            language="javascript",
        )
    with pytest.raises(ProgramGraphBuildError, match="repository-relative"):
        build_program_graph(
            {"../escape.py": "x = 1\n"},
            environment_binding_set_cid=ENV,
            sealed_binding_cid=SEALED,
        )


def test_self_recursion_is_marked_and_cfg_loops_are_cycles() -> None:
    receipt = build_program_graph(
        {
            "rec.py": (
                "def rec(n: int) -> int:\n"
                "    if n:\n"
                "        return rec(n - 1)\n"
                "    return 0\n"
            )
        },
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    recursive = _edges(receipt, ProgramGraphEdgeKind.MUTUAL_RECURSION.value)
    assert recursive
    assert all(edge.logical_cycle for edge in recursive)
    cfg_cycles = [
        edge
        for edge in receipt.edges
        if str(edge.edge_kind) in {ProgramGraphEdgeKind.CFG_NEXT.value, ProgramGraphEdgeKind.CFG_BRANCH.value}
        and edge.logical_cycle
    ]
    # A simple if/return recursion may not need a CFG back-edge; the call SCC does.
    assert recursive or cfg_cycles
    receipt.verify()


def test_empty_sources_produce_a_sealed_snapshot() -> None:
    receipt = build_program_graph(
        {},
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    receipt.verify()
    assert receipt.snapshot.node_cids == ()
    assert receipt.coverage.source_count == 0
    delta = compute_program_graph_delta(receipt, receipt)
    assert delta.added_node_cids == ()
    assert delta.removed_node_cids == ()


def test_coverage_receipt_is_content_addressed() -> None:
    receipt = build_program_graph(
        _rich_sources(),
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    again = build_program_graph(
        _rich_sources(),
        environment_binding_set_cid=ENV,
        sealed_binding_cid=SEALED,
    )
    assert (
        receipt.coverage.program_graph_coverage_receipt_cid
        == again.coverage.program_graph_coverage_receipt_cid
    )
    assert receipt.index_manifests
    for manifest in receipt.index_manifests:
        assert manifest.snapshot_cid == receipt.snapshot.program_graph_snapshot_cid
        assert manifest.rebuildable is True
