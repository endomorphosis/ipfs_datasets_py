"""Deterministic static program-graph construction and invalidation tests."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_graph import (
    ProgramGraphEdgeKind,
    ProgramGraphNodeKind,
    ResolutionStatus,
    apply_program_graph_delta,
    directed_logical_cycles,
    verify_program_graph_catalog,
)
from ipfs_datasets_py.logic.software_verification.program_graph_builder import (
    GRAPH_PROJECTIONS,
    PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE,
    PROGRAM_GRAPH_BUILDER_INTERFACE,
    PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE,
    ProgramGraphBuildReceipt,
    ProgramGraphBuilder,
    ProgramGraphBuilderError,
    ProgramGraphInvalidationPlanner,
    ProgramGraphSourceUnit,
    build_program_graph,
    compute_program_graph_delta,
    plan_program_graph_invalidation,
)


PKG_A = '''\
def ping(x: int) -> int:
    """Requires: x >= 0
    Ensures: result >= x
    """
    assert x >= 0
    return pong(x)

def pong(x: int) -> int:
    if x:
        return ping(x - 1)
    return x + 1
'''

PKG_B = '''\
from pkg.a import ping

def use(value: int) -> int:
    return ping(value)
'''

PKG_C = '''\
def isolated() -> int:
    return 1
'''

PKG_TEST = '''\
from pkg.a import ping

def test_ping() -> None:
    assert ping(1) >= 1
'''

PKG_DYN = '''\
def hidden(obj, name):
    return getattr(obj, name)

def boom(code):
    return eval(code)
'''

PKG_LOOP = '''\
def loop(n: int) -> int:
    i = 0
    while i < n:
        i = i + 1
    return i
'''

PKG_EXC = '''\
def guarded(x: int) -> int:
    try:
        if x < 0:
            raise ValueError("neg")
        return x
    except ValueError:
        return 0
'''

PKG_NATIVE = '''\
import ctypes

def native():
    return ctypes.CDLL("libc.so.6")
'''

PKG_C1 = '''\
from pkg import c2

def f():
    return c2.g()
'''

PKG_C2 = '''\
from pkg import c1

def g():
    return c1.f()
'''


def _base_units() -> dict[str, str]:
    return {
        "pkg/__init__.py": "",
        "pkg/a.py": PKG_A,
        "pkg/b.py": PKG_B,
        "pkg/c.py": PKG_C,
        "tests/test_a.py": PKG_TEST,
    }


def _rich_units() -> dict[str, str]:
    units = _base_units()
    units.update(
        {
            "pkg/dyn.py": PKG_DYN,
            "pkg/loop.py": PKG_LOOP,
            "pkg/exc.py": PKG_EXC,
            "pkg/native.py": PKG_NATIVE,
            "pkg/c1.py": PKG_C1,
            "pkg/c2.py": PKG_C2,
        }
    )
    return units


def test_public_interfaces_are_exported() -> None:
    assert PROGRAM_GRAPH_BUILDER_INTERFACE == "ProgramGraphBuilder@1"
    assert PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE == "ProgramGraphBuildReceipt@1"
    assert (
        PROGRAM_GRAPH_INVALIDATION_PLANNER_INTERFACE
        == "ProgramGraphInvalidationPlanner@1"
    )
    assert callable(build_program_graph)
    assert callable(compute_program_graph_delta)
    assert callable(plan_program_graph_invalidation)
    assert ProgramGraphBuilder.INTERFACE == PROGRAM_GRAPH_BUILDER_INTERFACE
    assert ProgramGraphBuildReceipt.INTERFACE == PROGRAM_GRAPH_BUILD_RECEIPT_INTERFACE


def test_repeated_builds_are_bit_identical() -> None:
    units = _base_units()
    first = build_program_graph(units)
    second = build_program_graph(units)
    assert (
        first.snapshot.program_graph_snapshot_cid
        == second.snapshot.program_graph_snapshot_cid
    )
    assert first.program_graph_build_receipt_cid == second.program_graph_build_receipt_cid
    assert first.snapshot.canonical_program_graph_cid == (
        second.snapshot.canonical_program_graph_cid
    )
    assert [edge.program_graph_edge_cid for edge in first.edges] == [
        edge.program_graph_edge_cid for edge in second.edges
    ]


def test_unit_insertion_order_does_not_change_canonical_identity() -> None:
    units = _base_units()
    forward = build_program_graph(units)
    reversed_units = [
        ProgramGraphSourceUnit(path=path, source=source)
        for path, source in reversed(list(units.items()))
    ]
    backward = build_program_graph(reversed_units)
    assert (
        forward.snapshot.program_graph_snapshot_cid
        == backward.snapshot.program_graph_snapshot_cid
    )
    assert list(forward.snapshot.edge_cids) == list(backward.snapshot.edge_cids)
    assert list(forward.snapshot.edge_cids) == sorted(forward.snapshot.edge_cids)


def test_builder_does_not_execute_source() -> None:
    receipt = build_program_graph(
        {"pkg/trap.py": "raise SystemExit('source executed')\n"}
    )
    module = receipt.node_by_logical_name("pkg.trap", ProgramGraphNodeKind.MODULE.value)
    assert module is not None
    assert receipt.snapshot.program_graph_snapshot_cid


def test_coverage_receipt_lists_required_projections() -> None:
    receipt = build_program_graph(_rich_units())
    covered = {name: count for name, count in receipt.coverage}
    assert tuple(covered) == GRAPH_PROJECTIONS
    for name in GRAPH_PROJECTIONS:
        assert covered[name] >= 1, f"projection {name} was not constructed"
    kinds = {str(node.node_kind) for node in receipt.nodes}
    for required in (
        ProgramGraphNodeKind.MODULE.value,
        ProgramGraphNodeKind.AST.value,
        ProgramGraphNodeKind.SOURCE.value,
        ProgramGraphNodeKind.FUNCTION.value,
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
        ProgramGraphNodeKind.PACKAGE.value,
    ):
        assert required in kinds
    verify_program_graph_catalog(
        receipt.snapshot,
        nodes=receipt.nodes,
        edges=receipt.edges,
        callsites=receipt.callsites,
        function_symbols=receipt.function_symbols,
        contract_states=receipt.contract_states,
        proof_obligation_graphs=receipt.proof_obligation_graphs,
        successor_sets=receipt.successor_sets,
        frontiers=receipt.frontiers,
    )


def test_eval_and_reflection_widen_the_dynamic_frontier() -> None:
    receipt = build_program_graph({"pkg/dyn.py": PKG_DYN})
    assert receipt.frontiers
    frontier = receipt.frontiers[0]
    assert frontier.unresolved_node_cids
    assert "eval" in frontier.reasons or "reflection" in frontier.reasons
    assert receipt.incomplete_dimensions
    dynamic_nodes = receipt.nodes_of_kind(ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value)
    assert dynamic_nodes
    unresolved_edges = [
        edge
        for edge in receipt.edges
        if str(edge.edge_kind) == ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value
    ]
    assert unresolved_edges
    assert all(
        str(edge.resolution_status) != ResolutionStatus.DEFINITE.value
        for edge in unresolved_edges
    )
    hidden = receipt.node_by_logical_name("pkg.dyn.hidden", "function")
    assert hidden is not None
    successors = [
        item
        for item in receipt.successor_sets
        if item.subject_node_cid == hidden.program_graph_node_cid
    ]
    assert successors
    assert successors[0].complete is False
    assert successors[0].unavailable_dimensions


def test_native_extension_calls_are_incomplete_not_absent() -> None:
    receipt = build_program_graph({"pkg/native.py": PKG_NATIVE})
    assert receipt.frontiers
    reasons = set(receipt.frontiers[0].reasons)
    assert "native_call" in reasons or "incomplete_analysis" in reasons
    assert receipt.nodes_of_kind(ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value)


def test_cfg_loop_is_a_logical_cycle() -> None:
    receipt = build_program_graph({"pkg/loop.py": PKG_LOOP})
    cfg_edges = [
        edge
        for edge in receipt.edges
        if str(edge.edge_kind)
        in {ProgramGraphEdgeKind.CFG_NEXT.value, ProgramGraphEdgeKind.CFG_BRANCH.value}
    ]
    cycles = directed_logical_cycles(cfg_edges)
    assert cycles
    by_cid = {edge.program_graph_edge_cid: edge for edge in cfg_edges}
    assert any(by_cid[cid].logical_cycle for cycle in cycles for cid in cycle)


def test_cyclic_imports_and_mutual_recursion_use_cycle_records() -> None:
    receipt = build_program_graph(
        {
            "pkg/__init__.py": "",
            "pkg/c1.py": PKG_C1,
            "pkg/c2.py": PKG_C2,
            "pkg/a.py": PKG_A,
        }
    )
    cyclic = receipt.edges_of_kind(ProgramGraphEdgeKind.CYCLIC_IMPORT.value)
    assert cyclic
    assert all(edge.logical_cycle for edge in cyclic)
    mutual = receipt.edges_of_kind(ProgramGraphEdgeKind.MUTUAL_RECURSION.value)
    assert mutual
    assert all(edge.logical_cycle for edge in mutual)


def test_exception_and_contract_and_test_projections() -> None:
    receipt = build_program_graph(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": PKG_A,
            "pkg/exc.py": PKG_EXC,
            "tests/test_a.py": PKG_TEST,
        }
    )
    assert receipt.nodes_of_kind(ProgramGraphNodeKind.EXCEPTION_HANDLER.value)
    assert receipt.edges_of_kind(ProgramGraphEdgeKind.EXCEPTION_EDGE.value)
    assert receipt.contract_states
    assert receipt.proof_obligation_graphs
    assert receipt.nodes_of_kind(ProgramGraphNodeKind.TEST.value)
    assert receipt.edges_of_kind(ProgramGraphEdgeKind.TESTED_BY.value)
    ping = receipt.node_by_logical_name("pkg.a.ping", "function")
    assert ping is not None
    binds = [
        edge
        for edge in receipt.edges_of_kind(ProgramGraphEdgeKind.BINDS_CONTRACT.value)
        if edge.source_node_cid == ping.program_graph_node_cid
    ]
    assert binds


def test_incremental_matches_full_rebuild_and_preserves_unchanged_subroots() -> None:
    original = _base_units()
    full = build_program_graph(original)
    incremental = build_program_graph(original, previous=full, incremental=True)
    assert (
        full.snapshot.program_graph_snapshot_cid
        == incremental.snapshot.program_graph_snapshot_cid
    )
    changed = dict(original)
    changed["pkg/a.py"] = PKG_A + "\n\nCONSTANT = 1\n"
    full_next = build_program_graph(changed)
    incremental_next = build_program_graph(
        changed, previous=full, incremental=True
    )
    assert (
        full_next.snapshot.program_graph_snapshot_cid
        == incremental_next.snapshot.program_graph_snapshot_cid
    )
    delta = compute_program_graph_delta(full, full_next)
    isolated = full.node_by_logical_name("pkg.c", "module")
    changed_module = full.node_by_logical_name("pkg.a", "module")
    assert isolated is not None
    assert changed_module is not None
    assert isolated.program_graph_node_cid in delta.retained_subroot_cids
    assert changed_module.program_graph_node_cid in delta.removed_node_cids
    applied = apply_program_graph_delta(full.snapshot, delta)
    assert applied["node_cids"] == full_next.snapshot.node_cids
    assert applied["edge_cids"] == full_next.snapshot.edge_cids


def test_invalidation_is_precise_and_does_not_omit_dependents() -> None:
    original = _base_units()
    previous = build_program_graph(original)
    changed = dict(original)
    changed["pkg/a.py"] = PKG_A.replace("return x + 1", "return x + 2")
    current = build_program_graph(changed)
    plan = plan_program_graph_invalidation(previous, current)
    planner = ProgramGraphInvalidationPlanner()
    again = planner.plan(previous, current)
    assert plan.program_graph_invalidation_plan_cid == again.program_graph_invalidation_plan_cid
    assert plan.full_fallback is False
    isolated = previous.node_by_logical_name("pkg.c", "module")
    importer = previous.node_by_logical_name("pkg.b", "module")
    changed_module = previous.node_by_logical_name("pkg.a", "module")
    test_node = previous.node_by_logical_name("pkg.a.<test>", "test") or next(
        (
            node
            for node in previous.nodes_of_kind("test")
            if "test_ping" in node.logical_name
        ),
        None,
    )
    assert isolated is not None
    assert importer is not None
    assert changed_module is not None
    assert changed_module.program_graph_node_cid in plan.invalidated_node_cids
    assert importer.program_graph_node_cid in plan.invalidated_node_cids
    assert isolated.program_graph_node_cid in plan.retained_subroot_cids
    assert isolated.program_graph_node_cid not in plan.invalidated_node_cids
    if test_node is not None:
        assert test_node.program_graph_node_cid in plan.invalidated_node_cids
    isolated_fn = previous.node_by_logical_name("pkg.c.isolated", "function")
    assert isolated_fn is not None
    assert isolated_fn.program_graph_node_cid in plan.retained_subroot_cids


def test_environment_change_forces_full_fallback() -> None:
    units = {"pkg/mod.py": "def f():\n    return 1\n"}
    first = ProgramGraphBuilder().build(units)
    alt_env = cid_for_bytes(b"alt-environment-binding")
    alt = ProgramGraphBuilder(environment_binding_set_cid=alt_env).build(units)
    plan = plan_program_graph_invalidation(first, alt)
    assert plan.full_fallback is True
    assert plan.environment_changed is True
    assert plan.retained_subroot_cids == ()


def test_snapshot_only_invalidation_fails_closed_to_full_fallback() -> None:
    units = _base_units()
    previous = build_program_graph(units)
    current = build_program_graph(units)
    plan = plan_program_graph_invalidation(previous.snapshot, current.snapshot)
    assert plan.full_fallback is True
    assert plan.retained_subroot_cids == ()


def test_deleted_snapshot_invalidates_everything() -> None:
    previous = build_program_graph(_base_units())
    plan = plan_program_graph_invalidation(previous, None)
    assert plan.full_fallback is True
    assert set(plan.invalidated_node_cids) == set(previous.snapshot.node_cids)
    assert plan.retained_subroot_cids == ()


def test_unsupported_language_and_absolute_paths_fail_closed() -> None:
    with pytest.raises(ProgramGraphBuilderError, match="typed unavailable"):
        build_program_graph(
            [ProgramGraphSourceUnit(path="mod.py", source="x=1\n", language="javascript")]
        )
    with pytest.raises(ProgramGraphBuilderError, match="repository-relative"):
        build_program_graph({"/tmp/mod.py": "x=1\n"})
    with pytest.raises(ProgramGraphBuilderError, match="Python profile"):
        ProgramGraphSourceUnit(path="mod.js", source="export const x = 1\n")
    with pytest.raises(ProgramGraphBuilderError, match="at least one"):
        build_program_graph({})
    with pytest.raises(ProgramGraphBuilderError, match="incremental"):
        build_program_graph(_base_units(), incremental=True)


def test_parse_error_is_incomplete_not_a_successful_empty_module() -> None:
    receipt = build_program_graph({"pkg/bad.py": "def broken(\n"})
    assert receipt.frontiers
    assert "incomplete_analysis" in receipt.incomplete_dimensions
    assert receipt.nodes_of_kind(ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value)
    module = receipt.node_by_logical_name("pkg.bad", "module")
    assert module is not None
    assert module.unavailable_dimensions


def test_canonical_edge_ordering_is_cid_sorted() -> None:
    receipt = build_program_graph(_base_units())
    assert list(receipt.snapshot.edge_cids) == sorted(receipt.snapshot.edge_cids)
    assert list(receipt.snapshot.node_cids) == sorted(receipt.snapshot.node_cids)
    assert [edge.program_graph_edge_cid for edge in receipt.edges] == list(
        receipt.snapshot.edge_cids
    )


def test_unknown_callee_stays_on_the_frontier() -> None:
    receipt = build_program_graph({"pkg/u.py": "def f():\n    return missing()\n"})
    assert receipt.frontiers
    assert "unknown_callee" in receipt.frontiers[0].reasons
    assert receipt.nodes_of_kind(ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value)


def test_import_performs_no_repository_scan() -> None:
    here = Path(__file__).resolve()
    root = next(
        (
            candidate
            for candidate in [here, *here.parents]
            if (candidate / "ipfs_datasets_py" / "ipfs_datasets_py").is_dir()
            and (candidate / "ipfs_kit_py").is_dir()
        ),
        here.parents[5],
    )
    script = r"""
import os
import sys
import threading

effects = []

def forbidden(name):
    def call(*args, **kwargs):
        effects.append(name)
        raise AssertionError(f"forbidden import side effect: {name}")
    return call

os.walk = forbidden("os.walk")
for name in ("system", "popen", "posix_spawn", "posix_spawnp"):
    if hasattr(os, name):
        setattr(os, name, forbidden("os." + name))

def audit(event, args):
    if event in {"socket.connect", "subprocess.Popen"}:
        effects.append(event)
        raise AssertionError(f"forbidden import side effect: {event}")

sys.addaudithook(audit)
from ipfs_datasets_py.logic.software_verification.program_graph_builder import (
    build_program_graph,
)
assert callable(build_program_graph)
assert effects == []
"""
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": "ipfs_datasets_py:ipfs_kit_py:.",
            "PYTHONDONTWRITEBYTECODE": "1",
            "IPFS_DATASETS_AUTO_INSTALL": "0",
            "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_module_reload_does_not_walk_the_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("repository scan at import")

    monkeypatch.setattr(os, "walk", boom)
    monkeypatch.setattr(os, "scandir", boom)
    import ipfs_datasets_py.logic.software_verification.program_graph_builder as module

    importlib.reload(module)
    assert callable(module.build_program_graph)
