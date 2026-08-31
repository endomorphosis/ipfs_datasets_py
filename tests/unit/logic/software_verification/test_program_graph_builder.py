"""Deterministic static program-graph construction and invalidation tests."""

from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path
from textwrap import dedent

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_graph import (
    ProgramGraphEdgeKind,
    ProgramGraphNodeKind,
    assemble_program_graph_snapshot,
    delta_between_snapshots,
)
from ipfs_datasets_py.logic.software_verification import program_graph_builder as builder_mod
from ipfs_datasets_py.logic.software_verification.program_graph_builder import (
    PROGRAM_GRAPH_BUILDER_INTERFACE,
    PROJECTION_NAMES,
    InvalidationReason,
    ProgramGraphBuildReceipt,
    ProgramGraphBuilder,
    ProgramGraphBuilderError,
    ProgramGraphCoverageReceipt,
    ProgramGraphInvalidationPlanner,
    build_program_graph,
    compute_program_graph_delta,
    plan_program_graph_invalidation,
)


PING_PONG = {
    "pkg/a.py": dedent(
        """
        from pkg.b import pong

        def ping(value):
            return pong(value)

        def ping_again(value):
            return ping(value)
        """
    ).lstrip(),
    "pkg/b.py": dedent(
        """
        from pkg.a import ping

        def pong(value):
            return ping(value)

        def helper(value):
            return value + 1
        """
    ).lstrip(),
    "pkg/c.py": dedent(
        """
        def unrelated(value):
            return value
        """
    ).lstrip(),
}

DYNAMIC_SRC = {
    "pkg/dyn.py": dedent(
        """
        def hidden(name, payload):
            target = getattr(payload, name)
            return eval(target)
        """
    ).lstrip()
}

TEST_CONTRACT_SRC = {
    "pkg/service.py": dedent(
        """
        def add(left, right):
            assert isinstance(left, int)
            return left + right
        """
    ).lstrip(),
    "pkg/test_service.py": dedent(
        """
        import pytest
        from pkg.service import add

        @pytest.fixture
        def sample():
            return 1

        def test_add(sample):
            assert add(sample, 2) == 3
        """
    ).lstrip(),
}

CFG_SRC = {
    "pkg/cfg.py": dedent(
        """
        def classify(value):
            try:
                if value > 0:
                    return "pos"
                while value < 0:
                    value += 1
                return "nonpos"
            except ValueError:
                raise RuntimeError("bad")
        """
    ).lstrip()
}


def _kinds(receipt: ProgramGraphBuildReceipt) -> set[str]:
    return {item.node_kind for item in receipt.nodes}


def _edge_kinds(receipt: ProgramGraphBuildReceipt) -> set[str]:
    return {item.edge_kind for item in receipt.edges}


def _nodes_named(receipt: ProgramGraphBuildReceipt, name: str) -> tuple:
    return tuple(item for item in receipt.nodes if item.logical_name == name)


def test_public_interfaces_and_symbols_are_exported() -> None:
    assert PROGRAM_GRAPH_BUILDER_INTERFACE == "ProgramGraphBuilder@1"
    assert callable(build_program_graph)
    assert callable(compute_program_graph_delta)
    assert callable(plan_program_graph_invalidation)
    assert ProgramGraphBuilder.interface == PROGRAM_GRAPH_BUILDER_INTERFACE
    assert issubclass(ProgramGraphBuilderError, ValueError)


def test_module_source_does_not_scan_a_repository() -> None:
    source = Path(builder_mod.__file__).read_text(encoding="utf-8")
    for needle in (
        "os.walk",
        "os.listdir",
        "Path.rglob",
        "Path.glob",
        "snapshot_repository",
        "scan_repository",
        "watch_repository",
    ):
        assert needle not in source


def test_import_and_build_do_not_walk_the_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("filesystem scan is forbidden")

    monkeypatch.setattr(os, "walk", boom)
    monkeypatch.setattr(Path, "rglob", boom)
    monkeypatch.setattr(Path, "glob", boom)
    importlib.import_module("ipfs_datasets_py.logic.software_verification.program_graph_builder")
    receipt = build_program_graph({"pkg/only.py": "def ready():\n    return 1\n"})
    assert receipt.snapshot.node_cids
    assert receipt.mode == "full"


def test_repeated_builds_are_deterministic() -> None:
    first = build_program_graph(PING_PONG, repository_id="repo:graph")
    second = build_program_graph(PING_PONG, repository_id="repo:graph")
    assert first.snapshot.program_graph_snapshot_cid == second.snapshot.program_graph_snapshot_cid
    assert first.snapshot.canonical_program_graph_cid == second.snapshot.canonical_program_graph_cid
    assert first.receipt_cid == second.receipt_cid
    assert first.snapshot.edge_cids == tuple(sorted(first.snapshot.edge_cids))
    assert first.snapshot.node_cids == tuple(sorted(first.snapshot.node_cids))


def test_canonical_edge_ordering_is_cid_sorted() -> None:
    receipt = build_program_graph(PING_PONG)
    assert receipt.snapshot.edge_cids == tuple(
        sorted(item.program_graph_edge_cid for item in receipt.edges)
    )
    assert [item.program_graph_edge_cid for item in receipt.edges] == list(
        receipt.snapshot.edge_cids
    )


def test_cyclic_import_and_mutual_recursion_are_logical_cycle_records() -> None:
    receipt = build_program_graph(PING_PONG)
    cyclic = receipt.edges_of_kind(ProgramGraphEdgeKind.CYCLIC_IMPORT.value)
    mutual = receipt.edges_of_kind(ProgramGraphEdgeKind.MUTUAL_RECURSION.value)
    assert cyclic
    assert mutual
    assert all(item.logical_cycle for item in cyclic)
    assert all(item.logical_cycle for item in mutual)
    assert _nodes_named(receipt, "pkg.a.ping")
    assert _nodes_named(receipt, "pkg.b.pong")


def test_dynamic_eval_and_reflection_widen_the_frontier() -> None:
    receipt = build_program_graph(DYNAMIC_SRC)
    assert ProgramGraphNodeKind.UNRESOLVED_DYNAMIC.value in _kinds(receipt)
    assert ProgramGraphEdgeKind.UNRESOLVED_DYNAMIC.value in _edge_kinds(receipt)
    assert receipt.frontiers
    reasons = set(receipt.frontiers[0].reasons)
    assert {"eval", "reflection"} & reasons
    assert receipt.coverage is not None
    assert receipt.coverage.projections["call"] == "incomplete"
    assert receipt.snapshot.unavailable_dimensions
    incomplete = [
        item for item in receipt.successor_sets if item.complete is False
    ]
    assert incomplete
    assert all(item.unavailable_dimensions for item in incomplete)


def test_cfg_data_flow_exception_and_type_projections() -> None:
    receipt = build_program_graph(CFG_SRC)
    kinds = _kinds(receipt)
    edges = _edge_kinds(receipt)
    assert ProgramGraphNodeKind.CFG_BLOCK.value in kinds
    assert ProgramGraphNodeKind.DATA_FLOW.value in kinds
    assert ProgramGraphNodeKind.EXCEPTION_HANDLER.value in kinds
    assert ProgramGraphNodeKind.TYPE_BINDING.value in kinds
    assert ProgramGraphEdgeKind.CFG_NEXT.value in edges
    assert ProgramGraphEdgeKind.CFG_BRANCH.value in edges
    assert ProgramGraphEdgeKind.DATA_FLOW.value in edges
    assert ProgramGraphEdgeKind.EXCEPTION_EDGE.value in edges
    assert ProgramGraphEdgeKind.TYPE_OF.value in edges
    assert any(item.logical_cycle for item in receipt.edges_of_kind("cfg_next"))
    assert "type_inference" in receipt.snapshot.unavailable_dimensions


def test_tests_fixtures_contracts_and_proofs_are_projected() -> None:
    receipt = build_program_graph(TEST_CONTRACT_SRC)
    kinds = _kinds(receipt)
    edges = _edge_kinds(receipt)
    assert ProgramGraphNodeKind.TEST.value in kinds
    assert ProgramGraphNodeKind.FIXTURE.value in kinds
    assert ProgramGraphNodeKind.CONTRACT_STATE.value in kinds
    assert ProgramGraphNodeKind.PROOF_OBLIGATION.value in kinds
    assert ProgramGraphEdgeKind.TESTED_BY.value in edges
    assert ProgramGraphEdgeKind.USES_FIXTURE.value in edges
    assert ProgramGraphEdgeKind.BINDS_CONTRACT.value in edges
    assert ProgramGraphEdgeKind.PROVED_BY.value in edges
    assert receipt.proof_obligation_graphs
    assert receipt.contract_states
    assert receipt.coverage is not None
    assert receipt.coverage.projections["proof"] == "incomplete"
    assert receipt.coverage.projections["test"] in {"complete", "incomplete"}


def test_coverage_receipt_covers_every_declared_projection() -> None:
    receipt = build_program_graph({**PING_PONG, **CFG_SRC, **TEST_CONTRACT_SRC, **DYNAMIC_SRC})
    assert receipt.coverage is not None
    assert tuple(receipt.coverage.projections) == PROJECTION_NAMES
    assert receipt.coverage.coverage_cid
    assert receipt.coverage.file_count == 7
    assert receipt.coverage.node_count == len(receipt.nodes)


def test_parse_error_is_explicit_and_not_treated_as_absence() -> None:
    receipt = build_program_graph({"pkg/bad.py": "def broken(:\n"})
    assert ProgramGraphNodeKind.SOURCE.value in _kinds(receipt)
    assert ProgramGraphNodeKind.AST.value in _kinds(receipt)
    ast_nodes = receipt.nodes_of_kind(ProgramGraphNodeKind.AST.value)
    assert ast_nodes
    assert "parse_error" in ast_nodes[0].unavailable_dimensions
    assert any(item.startswith("parse_error:") for item in receipt.diagnostics)


def test_incremental_rebuild_matches_full_rebuild_and_retains_unchanged_subroots() -> None:
    previous = build_program_graph(PING_PONG)
    changed = dict(PING_PONG)
    changed["pkg/b.py"] = dedent(
        """
        from pkg.a import ping

        def pong(value):
            return ping(value) + 1

        def helper(value):
            return value + 1
        """
    ).lstrip()
    full = build_program_graph(changed)
    incremental = build_program_graph(changed, previous=previous)
    assert incremental.mode == "incremental"
    assert "pkg/a.py" in incremental.reused_paths
    assert "pkg/c.py" in incremental.reused_paths
    assert "pkg/b.py" in incremental.rebuilt_paths
    assert full.snapshot.canonical_program_graph_cid == incremental.snapshot.canonical_program_graph_cid
    assert full.snapshot.node_cids == incremental.snapshot.node_cids
    assert full.snapshot.edge_cids == incremental.snapshot.edge_cids
    assert full.snapshot.program_graph_snapshot_cid == incremental.snapshot.program_graph_snapshot_cid
    delta = compute_program_graph_delta(previous, incremental)
    unchanged_a = set(previous.nodes_by_path["pkg/a.py"]) & set(incremental.nodes_by_path["pkg/a.py"])
    unchanged_c = set(previous.nodes_by_path["pkg/c.py"]) & set(incremental.nodes_by_path["pkg/c.py"])
    assert unchanged_a
    assert unchanged_c
    assert set(unchanged_a) <= set(delta.retained_subroot_cids)
    assert set(unchanged_c) <= set(delta.retained_subroot_cids)
    assert set(previous.nodes_by_path["pkg/b.py"]) & set(delta.removed_node_cids)
    assert set(incremental.nodes_by_path["pkg/b.py"]) & set(delta.added_node_cids)


def test_invalidation_is_precise_and_does_not_omit_dependents() -> None:
    previous = build_program_graph(PING_PONG)
    changed = dict(PING_PONG)
    changed["pkg/b.py"] = PING_PONG["pkg/b.py"].replace("return ping(value)", "return ping(value) or 0")
    current = build_program_graph(changed, previous=previous)
    plan = plan_program_graph_invalidation(previous, current)
    delta = compute_program_graph_delta(previous, current)
    assert plan.delta_cid == delta.program_graph_delta_cid
    assert plan.full_rebuild is False
    ping = _nodes_named(previous, "pkg.a.ping")[0]
    unrelated = _nodes_named(previous, "pkg.c.unrelated")[0]
    pong = _nodes_named(previous, "pkg.b.pong")[0]
    assert pong.program_graph_node_cid in plan.invalidated_node_cids
    assert ping.program_graph_node_cid in plan.invalidated_node_cids
    assert unrelated.program_graph_node_cid in plan.retained_subroot_cids
    assert unrelated.program_graph_node_cid not in plan.invalidated_node_cids
    reasons = {item.reason for item in plan.obligations}
    assert InvalidationReason.SOURCE_CHANGED.value in reasons
    assert {
        InvalidationReason.DEPENDENT_OF_CHANGED.value,
        InvalidationReason.CALLEE_CHANGED.value,
        InvalidationReason.IMPORT_TARGET_CHANGED.value,
    } & reasons


def test_environment_change_forces_full_invalidation() -> None:
    previous = build_program_graph(PING_PONG)
    current = build_program_graph(
        PING_PONG,
        sealed_binding_cid=cid_for_bytes(b"program-graph-seal:alt"),
        environment_binding_set_cid=previous.environment_binding_set_cid,
    )
    plan = plan_program_graph_invalidation(previous, current)
    assert plan.full_rebuild is True
    assert plan.retained_subroot_cids == ()
    assert previous.snapshot.node_cids[0] in plan.invalidated_node_cids
    assert any(item.reason == InvalidationReason.ENVIRONMENT_CHANGED.value for item in plan.obligations)


def test_builder_rejects_non_relative_paths_and_non_mappings() -> None:
    with pytest.raises(ProgramGraphBuilderError):
        build_program_graph({"/abs/mod.py": "x = 1\n"})
    with pytest.raises(ProgramGraphBuilderError):
        build_program_graph("../escape.py")  # type: ignore[arg-type]
    with pytest.raises(ProgramGraphBuilderError):
        ProgramGraphBuilder().build(["not a mapping"])  # type: ignore[arg-type]


def test_receipt_catalog_assembles_and_delta_round_trips() -> None:
    first = build_program_graph(PING_PONG)
    second = build_program_graph(CFG_SRC)
    # Distinct trees: applying the snapshot catalog still verifies.
    assemble_program_graph_snapshot(
        nodes=first.nodes,
        edges=first.edges,
        environment_binding_set_cid=first.environment_binding_set_cid,
        sealed_binding_cid=first.sealed_binding_cid,
        callsites=first.callsites,
        function_symbols=first.function_symbols,
        contract_states=first.contract_states,
        proof_obligation_graphs=first.proof_obligation_graphs,
        successor_sets=first.successor_sets,
        frontiers=first.frontiers,
        unavailable_dimensions=first.snapshot.unavailable_dimensions,
    )
    delta = compute_program_graph_delta(first, second)
    assert delta.previous_snapshot_cid == first.snapshot.program_graph_snapshot_cid
    assert set(delta.removed_node_cids) == set(first.snapshot.node_cids) - set(
        second.snapshot.node_cids
    )
    rebuilt = delta_between_snapshots(first.snapshot, second.snapshot)
    assert rebuilt.program_graph_delta_cid == delta.program_graph_delta_cid


def test_ast_projection_is_position_free_and_source_bound() -> None:
    spaced = build_program_graph({"pkg/mod.py": "def answer():\n    return 1\n"})
    extra_blank = build_program_graph({"pkg/mod.py": "\n\ndef answer():\n    return 1\n"})
    ast_a = spaced.nodes_of_kind(ProgramGraphNodeKind.AST.value)[0]
    ast_b = extra_blank.nodes_of_kind(ProgramGraphNodeKind.AST.value)[0]
    assert ast_a.metadata["ast_cid"] == ast_b.metadata["ast_cid"]
    assert ast_a.source_cid != ast_b.source_cid
    tree = ast.parse("def answer():\n    return 1\n")
    assert ast_a.metadata["ast_cid"]
    assert "lineno" not in ast.dump(tree, include_attributes=False)


def test_planner_and_builder_classes_are_usable_directly() -> None:
    builder = ProgramGraphBuilder(repository_id="repo:direct")
    previous = builder.build(TEST_CONTRACT_SRC)
    current = builder.build(TEST_CONTRACT_SRC, previous=previous)
    assert current.mode == "incremental"
    assert current.reused_paths == tuple(sorted(TEST_CONTRACT_SRC))
    plan = ProgramGraphInvalidationPlanner().plan(previous, current)
    assert plan.invalidated_node_cids == ()
    assert set(plan.retained_subroot_cids) == set(previous.snapshot.node_cids)


def test_coverage_projection_set_is_closed() -> None:
    with pytest.raises(ProgramGraphBuilderError):
        ProgramGraphCoverageReceipt(projections={"ast": "complete"})
    with pytest.raises(ProgramGraphBuilderError):
        ProgramGraphCoverageReceipt(
            projections={name: "complete" for name in (*PROJECTION_NAMES, "extra")}
        )


def test_index_manifests_bind_the_snapshot() -> None:
    receipt = build_program_graph(PING_PONG)
    assert receipt.index_manifests
    for manifest in receipt.index_manifests:
        assert manifest.snapshot_cid == receipt.snapshot.program_graph_snapshot_cid
        assert manifest.rebuildable is True
