"""Independent contract tests for SPAR-012 SCCSnapshot@1."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "0")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS", "0")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.software_contracts.content import (  # noqa: E402
    PROFILE_ID,
    STRUCTURED_CODEC,
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.semantic_refactoring.program_graph import (  # noqa: E402
    GraphBinding,
    GraphConfidence,
    GraphEvidenceClass,
    GraphFreshness,
    RefactoringGraphEdge,
    RefactoringGraphNode,
    ResolverStatus,
    SemanticRefactoringGraphView,
    UnresolvedFrontier,
    UnresolvedFrontierItem,
    FrontierReason,
)
from ipfs_datasets_py.semantic_refactoring.scc import (  # noqa: E402
    ANALYZER_ID,
    AUTHORITY,
    AUTHORITY_OWNER,
    CONSERVATIVE_EDGES_ARE_PRESERVED,
    DEFAULT_HARD_EDGE_KINDS,
    DUCKLAKE_IS_AUTHORITY,
    EXTRACTION_CONDENSATION_DAG_INTERFACE,
    GOAL_ID,
    HARD_EDGE_POLICY_ID,
    HARD_EDGE_POLICY_INTERFACE,
    HARD_EDGE_POLICY_REVISION,
    HEURISTIC_EDGES_ARE_NOT_HARD,
    INCREMENTAL_EQUALS_CLEAN_REBUILD,
    MARKDOWN_IS_NOT_COMPLETION,
    MODEL_OUTPUT_IS_PROPOSAL_ONLY,
    SCC_CAN_AUTHORIZE_COMPLETION,
    SCC_CAN_AUTHORIZE_TRANSITION,
    SCC_CAN_CREATE_AUTHORITY,
    SCC_CID_CODEC,
    SCC_CID_PROFILE,
    SCC_CONTRACT_VERSION,
    SCC_SNAPSHOT_INTERFACE,
    SOFT_EDGE_KINDS,
    TASK_ID,
    TEST_PASS_IS_NOT_COMPLETION,
    VECTOR_SIMILARITY_IS_AUTHORITY,
    WORKER_SELF_APPROVAL,
    CondensationEdge,
    EdgeAdmission,
    ExtractionCondensationDAG,
    HardEdgePolicy,
    OversizedCycleGap,
    SCCSnapshot,
    SccContractError,
    build_extraction_condensation_dag,
    build_scc_snapshot,
    classify_edge,
    decode_canonical_condensation_dag,
    decode_canonical_scc_snapshot,
    default_hard_edge_policy,
    encode_canonical_condensation_dag,
    encode_canonical_scc_snapshot,
    is_default_hard_edge_kind,
    is_soft_edge_kind,
    provider_free_exports,
    rebuild_scc_snapshot,
    scc_cid_profile,
)


ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = (
    ROOT
    / "ipfs_datasets_py"
    / "ipfs_datasets_py"
    / "semantic_refactoring"
    / "scc.py"
)
TEST_PATH = Path(__file__).resolve()
INVENTORY = (
    ROOT
    / "docs"
    / "architecture"
    / "semantic_preserving_autonomous_remodularization_inventory"
)
WRITE_SCOPE = (
    "ipfs_datasets_py/ipfs_datasets_py/semantic_refactoring/scc.py",
    "ipfs_datasets_py/tests/unit/semantic_refactoring/test_scc.py",
)
PROTECTED_PATHS = (
    ".gitignore",
    "benchmarks/agent_supervisor/semantic_refactoring/preregistration.json",
    "config/agent_supervisor_semantic_preserving_remodularization_scheduler.json",
    "config/semantic_preserving_autonomous_remodularization_dependencies.seal.json",
    "docs/architecture/SEMANTIC_PRESERVING_AUTONOMOUS_REMODULARIZATION_PLAN.md",
    "docs/architecture/semantic_preserving_autonomous_remodularization.objectives.md",
    "docs/architecture/semantic_preserving_autonomous_remodularization.todo.md",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/authority_matrix.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/benchmark_preregistration.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/dynamic_python_risk_inventory.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/identity_inventory.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/interface_inventory.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/overlap_gap_matrix.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/repository_baseline.json",
    "docs/architecture/semantic_preserving_autonomous_remodularization_inventory/rollout_baseline.json",
    "scripts/materialize_semantic_preserving_remodularization_program.py",
    "scripts/ops/agent_supervisor/semantic_preserving_remodularization.py",
    "scripts/validate_semantic_preserving_remodularization_board.py",
    "scripts/validate_semantic_preserving_remodularization_dependencies.py",
    "test/api/semantic_refactoring/test_bootstrap_controls.py",
)
CAPSULE_TYPES = (
    "FunctionSemanticCapsule",
    "MethodSemanticCapsule",
    "ClassSemanticCapsule",
    "TopLevelBlockCapsule",
    "ModuleSemanticCapsule",
    "PackageSemanticCapsule",
    "CallsiteSemanticCapsule",
    "StateOwnerCapsule",
    "RegistrationCapsule",
    "ResourceLifecycleCapsule",
)
TREE_ID = "fbc6fa1ddefb2f9ecb7b5c718d618e3b60aa3051"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _binding(**overrides: Any) -> GraphBinding:
    fields = {
        "tree_id": TREE_ID,
        "analyzer_id": "ipfs_datasets_py.semantic_refactoring.program_graph@1",
        "analyzer_revision": _cid("analyzer-revision"),
        "environment_cid": _cid("environment"),
    }
    fields.update(overrides)
    return GraphBinding(**fields)


def _node(
    node_id: str,
    *,
    kind: str = "function",
    qualified_name: str | None = None,
    module_path: str = "pkg/mod.py",
    **overrides: Any,
) -> RefactoringGraphNode:
    fields: dict[str, Any] = {
        "node_id": node_id,
        "kind": kind,
        "qualified_name": qualified_name or node_id.replace("node:", ""),
        "module_path": "" if kind == "repository" else module_path,
        "evidence_class": GraphEvidenceClass.EXACT_STATIC_FACT,
        "confidence": GraphConfidence.EXACT,
        "freshness": GraphFreshness.FRESH,
        "capsule_cid": _cid(f"capsule:{kind}:{node_id}")
        if kind
        in {
            "function",
            "method",
            "class",
            "callsite",
            "top_level_block",
            "module",
            "package",
            "state_owner",
            "registration",
            "resource_lifecycle",
        }
        else None,
        "identity_set_cid": _cid(f"identity:{node_id}"),
    }
    fields.update(overrides)
    return RefactoringGraphNode(**fields)


def _edge(
    source_id: str,
    target_id: str,
    kind: str = "calls",
    **overrides: Any,
) -> RefactoringGraphEdge:
    fields = {
        "source_id": source_id,
        "target_id": target_id,
        "kind": kind,
        "evidence_class": GraphEvidenceClass.EXACT_STATIC_FACT,
        "confidence": GraphConfidence.EXACT,
        "resolver_status": ResolverStatus.RESOLVED_STATIC,
    }
    fields.update(overrides)
    return RefactoringGraphEdge(**fields)


def _view(
    nodes: tuple[RefactoringGraphNode, ...],
    edges: tuple[RefactoringGraphEdge, ...] = (),
    **overrides: Any,
) -> SemanticRefactoringGraphView:
    fields: dict[str, Any] = {
        "binding": _binding(),
        "nodes": nodes,
        "edges": edges,
        "unresolved_frontier": UnresolvedFrontier(),
    }
    fields.update(overrides)
    return SemanticRefactoringGraphView(**fields)


def _mutual_calls() -> SemanticRefactoringGraphView:
    left = _node("node:left")
    right = _node("node:right")
    return _view(
        (left, right),
        (
            _edge("node:left", "node:right", "calls"),
            _edge("node:right", "node:left", "calls"),
        ),
    )


def test_owned_paths_and_task_identity_are_exact() -> None:
    assert TASK_ID == "SPAR-012"
    assert GOAL_ID == "SPAR-G031"
    assert SCC_SNAPSHOT_INTERFACE == "SCCSnapshot@1"
    assert EXTRACTION_CONDENSATION_DAG_INTERFACE == "ExtractionCondensationDAG@1"
    assert HARD_EDGE_POLICY_INTERFACE == "HardEdgePolicy@1"
    assert HARD_EDGE_POLICY_ID == "hard-edge-policy@1"
    assert HARD_EDGE_POLICY_REVISION == "1"
    assert SCC_CONTRACT_VERSION == "1"
    assert ANALYZER_ID.endswith("scc@1")
    assert MODULE_PATH.is_file()
    assert TEST_PATH.is_file()
    for relative in WRITE_SCOPE:
        assert (ROOT / relative).is_file()


def test_authority_flags_cannot_self_authorize() -> None:
    assert AUTHORITY == "formal semantic authority"
    assert AUTHORITY_OWNER == "ipfs_datasets_py"
    assert SCC_CAN_AUTHORIZE_COMPLETION is False
    assert SCC_CAN_AUTHORIZE_TRANSITION is False
    assert SCC_CAN_CREATE_AUTHORITY is False
    assert VECTOR_SIMILARITY_IS_AUTHORITY is False
    assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
    assert TEST_PASS_IS_NOT_COMPLETION is True
    assert MARKDOWN_IS_NOT_COMPLETION is True
    assert WORKER_SELF_APPROVAL is False
    assert DUCKLAKE_IS_AUTHORITY is False
    assert HEURISTIC_EDGES_ARE_NOT_HARD is True
    assert CONSERVATIVE_EDGES_ARE_PRESERVED is True
    assert INCREMENTAL_EQUALS_CLEAN_REBUILD is True
    profile = scc_cid_profile()
    assert profile["profile_id"] == PROFILE_ID == SCC_CID_PROFILE
    assert profile["codec"] == STRUCTURED_CODEC == SCC_CID_CODEC
    assert "not universal meaning" in profile["rule"]


def test_module_defines_predicted_symbols_not_capsule_family() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "SCCSnapshot" in names
    assert "ExtractionCondensationDAG" in names
    assert "HardEdgePolicy" in names
    assert "SCCComponent" in names
    for capsule in CAPSULE_TYPES:
        assert capsule not in names


def test_hard_edge_policy_is_versioned_and_closed() -> None:
    policy = default_hard_edge_policy()
    assert policy.policy_id == HARD_EDGE_POLICY_ID
    assert policy.revision == HARD_EDGE_POLICY_REVISION
    assert policy.include_conservative_hard_edges is True
    assert tuple(policy.hard_edge_kinds) == DEFAULT_HARD_EDGE_KINDS
    assert set(DEFAULT_HARD_EDGE_KINDS).isdisjoint(SOFT_EDGE_KINDS)
    assert is_default_hard_edge_kind("calls") is True
    assert is_soft_edge_kind("tests") is True
    restored = HardEdgePolicy.from_dict(policy.to_dict())
    assert restored == policy
    assert restored.policy_cid == cid_for_structured(policy.identity_payload())
    with pytest.raises(SccContractError, match="forbidden edge kind"):
        HardEdgePolicy(hard_edge_kinds=("calls", "happens_before"))
    with pytest.raises(SccContractError, match="unknown hard edge kind"):
        HardEdgePolicy(hard_edge_kinds=("calls", "invented"))


def test_mutual_calls_form_one_cyclic_scc() -> None:
    snapshot = build_scc_snapshot(_mutual_calls())
    assert len(snapshot.components) == 1
    component = snapshot.components[0]
    assert component.member_ids == ("node:left", "node:right")
    assert component.cyclic is True
    assert component.oversized is False
    assert component.extraction_supported is True
    assert snapshot.component_for_node("node:left") == component
    assert snapshot.tree_id == TREE_ID
    assert snapshot.analyzer_id == ANALYZER_ID


def test_soft_edges_do_not_create_hard_sccs() -> None:
    left = _node("node:left")
    right = _node("node:right")
    view = _view(
        (left, right),
        (
            _edge("node:left", "node:right", "tests"),
            _edge("node:right", "node:left", "documents"),
        ),
    )
    snapshot = build_scc_snapshot(view)
    assert len(snapshot.components) == 2
    assert all(item.cyclic is False for item in snapshot.components)
    dag = build_extraction_condensation_dag(snapshot)
    assert dag.edges == ()
    assert set(dag.extraction_order) == {item.scc_id for item in snapshot.components}


def test_heuristic_hard_kinds_remain_advisory() -> None:
    left = _node("node:left")
    right = _node("node:right")
    frontier = (
        UnresolvedFrontierItem(
            subject_id="node:left",
            subject_kind="node",
            reason=FrontierReason.ANALYZER_GAP,
            evidence_class=GraphEvidenceClass.VECTOR_CANDIDATE,
            confidence=GraphConfidence.HEURISTIC,
            unresolved_fields=("symbol_binding_cid",),
        ),
        UnresolvedFrontierItem(
            subject_id="node:right",
            subject_kind="node",
            reason=FrontierReason.ANALYZER_GAP,
            evidence_class=GraphEvidenceClass.MODEL_HYPOTHESIS,
            confidence=GraphConfidence.HEURISTIC,
            unresolved_fields=("symbol_binding_cid",),
        ),
    )
    view = _view(
        (left, right),
        (
            _edge(
                "node:left",
                "node:right",
                "calls",
                confidence=GraphConfidence.HEURISTIC,
                evidence_class=GraphEvidenceClass.VECTOR_CANDIDATE,
            ),
            _edge(
                "node:right",
                "node:left",
                "calls",
                confidence=GraphConfidence.HEURISTIC,
                evidence_class=GraphEvidenceClass.MODEL_HYPOTHESIS,
            ),
        ),
        unresolved_frontier=frontier,
    )
    snapshot = build_scc_snapshot(view)
    assert len(snapshot.components) == 2
    assert snapshot.preserved_conservative_edges == ()
    edge = view.edges[0]
    assert classify_edge(edge, default_hard_edge_policy()) is EdgeAdmission.ADVISORY


def test_conservative_hard_edges_are_preserved_and_participate() -> None:
    left = _node("node:left")
    right = _node(
        "node:right",
        confidence=GraphConfidence.CONSERVATIVE,
        evidence_class=GraphEvidenceClass.CONSERVATIVE_MAY_FACT,
    )
    view = _view(
        (left, right),
        (
            _edge(
                "node:left",
                "node:right",
                "calls",
                confidence=GraphConfidence.CONSERVATIVE,
                evidence_class=GraphEvidenceClass.CONSERVATIVE_MAY_FACT,
                resolver_status=ResolverStatus.DYNAMIC,
            ),
            _edge(
                "node:right",
                "node:left",
                "imports",
                confidence=GraphConfidence.CONSERVATIVE,
                evidence_class=GraphEvidenceClass.CONSERVATIVE_MAY_FACT,
                resolver_status=ResolverStatus.DYNAMIC,
            ),
        ),
        unresolved_frontier=(
            UnresolvedFrontierItem(
                subject_id="node:right",
                subject_kind="node",
                reason=FrontierReason.DYNAMIC_DISPATCH,
                evidence_class=GraphEvidenceClass.CONSERVATIVE_MAY_FACT,
                confidence=GraphConfidence.CONSERVATIVE,
                unresolved_fields=("symbol_binding_cid",),
            ),
        ),
    )
    snapshot = build_scc_snapshot(view)
    assert len(snapshot.components) == 1
    assert snapshot.components[0].cyclic is True
    assert snapshot.preserved_conservative_edges
    admissions = {item.admission for item in snapshot.preserved_conservative_edges}
    assert EdgeAdmission.HARD_CONSERVATIVE.value in admissions
    dropped = HardEdgePolicy(include_conservative_hard_edges=False)
    split = build_scc_snapshot(view, policy=dropped)
    assert len(split.components) == 2
    assert split.preserved_conservative_edges
    assert split.snapshot_cid != snapshot.snapshot_cid


def test_condensation_dag_is_acyclic_and_extraction_ordered() -> None:
    leaf = _node("node:leaf")
    mid = _node("node:mid")
    root = _node("node:root")
    view = _view(
        (leaf, mid, root),
        (
            _edge("node:root", "node:mid", "calls"),
            _edge("node:mid", "node:leaf", "imports"),
        ),
    )
    snapshot = build_scc_snapshot(view)
    dag = build_extraction_condensation_dag(snapshot)
    assert dag.snapshot_cid == snapshot.snapshot_cid
    assert len(dag.scc_ids) == 3
    assert len(dag.edges) == 2
    order = dag.extraction_order
    leaf_scc = snapshot.component_for_node("node:leaf").scc_id
    mid_scc = snapshot.component_for_node("node:mid").scc_id
    root_scc = snapshot.component_for_node("node:root").scc_id
    assert order.index(leaf_scc) < order.index(mid_scc)
    assert order.index(mid_scc) < order.index(root_scc)
    restored = decode_canonical_condensation_dag(
        encode_canonical_condensation_dag(dag)
    )
    assert restored == dag
    assert restored.dag_cid == cid_for_structured(dag.identity_payload())


def test_snapshot_round_trips_and_reverifies_independent_cid() -> None:
    snapshot = build_scc_snapshot(_mutual_calls())
    restored = SCCSnapshot.from_dict(snapshot.to_dict())
    assert restored == snapshot
    assert restored.snapshot_cid == snapshot.snapshot_cid
    assert restored.snapshot_cid == cid_for_structured(snapshot.identity_payload())
    encoded = encode_canonical_scc_snapshot(snapshot)
    assert decode_canonical_scc_snapshot(encoded).snapshot_cid == snapshot.snapshot_cid
    rebuilt = build_scc_snapshot(_mutual_calls())
    assert rebuilt.snapshot_cid == snapshot.snapshot_cid


def test_oversized_cyclic_scc_is_a_typed_gap() -> None:
    nodes = tuple(_node(f"node:n{index}") for index in range(3))
    edges = (
        _edge("node:n0", "node:n1", "calls"),
        _edge("node:n1", "node:n2", "calls"),
        _edge("node:n2", "node:n0", "calls"),
    )
    view = _view(nodes, edges)
    policy = HardEdgePolicy(max_scc_members=2)
    snapshot = build_scc_snapshot(view, policy=policy)
    assert len(snapshot.components) == 1
    assert snapshot.components[0].oversized is True
    assert snapshot.components[0].extraction_supported is False
    assert len(snapshot.oversized_cycle_gaps) == 1
    gap = snapshot.oversized_cycle_gaps[0]
    assert gap.member_count == 3
    assert gap.extraction_supported is False
    with pytest.raises(SccContractError, match="cannot support extraction"):
        OversizedCycleGap(
            scc_id=gap.scc_id,
            member_count=3,
            extraction_supported=True,
        )


def test_state_uniqueness_rejects_duplicated_owners() -> None:
    owner_a = _node(
        "node:owner-a",
        kind="state_owner",
        qualified_name="pkg.mod.OwnerA",
        identity_set_cid=_cid("owner-identity"),
    )
    owner_b = _node(
        "node:owner-b",
        kind="state_owner",
        qualified_name="pkg.mod.OwnerB",
        identity_set_cid=_cid("owner-identity"),
    )
    view = _view((owner_a, owner_b))
    with pytest.raises(SccContractError, match="state uniqueness"):
        build_scc_snapshot(view)
    unique = _view(
        (
            _node("node:owner-a", kind="state_owner", qualified_name="pkg.mod.OwnerA"),
            _node("node:owner-b", kind="state_owner", qualified_name="pkg.mod.OwnerB"),
        )
    )
    snapshot = build_scc_snapshot(unique)
    owners = [
        member
        for item in snapshot.components
        for member in item.state_owner_ids
    ]
    assert sorted(owners) == ["node:owner-a", "node:owner-b"]


def test_incremental_invalidation_is_identity_equivalent() -> None:
    view = _mutual_calls()
    snapshot = build_scc_snapshot(view)
    assert snapshot.affected_sccs(()) == ()
    affected = snapshot.affected_sccs(("node:left",))
    assert affected == snapshot.scc_ids
    rebuilt = rebuild_scc_snapshot(view, previous=snapshot)
    assert rebuilt.snapshot_cid == snapshot.snapshot_cid
    assert rebuilt is snapshot
    changed = rebuild_scc_snapshot(
        view,
        previous=snapshot,
        changed_node_ids=("node:left", "node:right"),
    )
    assert changed.snapshot_cid == snapshot.snapshot_cid
    isolated = _view((_node("node:left"), _node("node:right")))
    with pytest.raises(SccContractError, match="without incremental invalidation"):
        rebuild_scc_snapshot(isolated, previous=snapshot)
    next_snapshot = rebuild_scc_snapshot(
        isolated,
        previous=snapshot,
        changed_node_ids=("node:left", "node:right"),
    )
    assert next_snapshot.snapshot_cid != snapshot.snapshot_cid
    assert len(next_snapshot.components) == 2


def test_self_recursive_call_is_cyclic_singleton() -> None:
    node = _node("node:rec")
    view = _view((node,), (_edge("node:rec", "node:rec", "calls"),))
    snapshot = build_scc_snapshot(view)
    assert len(snapshot.components) == 1
    assert snapshot.components[0].cyclic is True
    assert snapshot.components[0].member_ids == ("node:rec",)


def test_forged_cids_and_observational_fields_are_rejected() -> None:
    snapshot = build_scc_snapshot(_mutual_calls())
    payload = snapshot.to_dict()
    payload["snapshot_cid"] = _cid("forged")
    with pytest.raises(SccContractError, match="does not verify"):
        SCCSnapshot.from_dict(payload)
    payload = snapshot.to_dict()
    payload["timestamp"] = "now"
    with pytest.raises(SccContractError, match="observational"):
        SCCSnapshot.from_dict(payload)
    payload = snapshot.to_dict()
    payload["extra"] = "nope"
    with pytest.raises(SccContractError, match="unknown"):
        SCCSnapshot.from_dict(payload)
    payload = snapshot.to_dict()
    payload.pop("components")
    with pytest.raises(SccContractError, match="missing"):
        SCCSnapshot.from_dict(payload)
    with pytest.raises(SccContractError, match="analyzer_id"):
        SCCSnapshot(
            tree_id=snapshot.tree_id,
            graph_view_cid=snapshot.graph_view_cid,
            policy=snapshot.policy,
            components=snapshot.components,
            preserved_conservative_edges=snapshot.preserved_conservative_edges,
            oversized_cycle_gaps=snapshot.oversized_cycle_gaps,
            condensation_edges=snapshot.condensation_edges,
            invalidation_index=snapshot.invalidation_index,
            analyzer_id="other.analyzer@1",
        )


def test_protected_controls_are_outside_write_scope_and_remain() -> None:
    protected = set(PROTECTED_PATHS)
    assert protected.isdisjoint(WRITE_SCOPE)
    for relative in PROTECTED_PATHS:
        path = ROOT / relative
        assert path.exists(), relative
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))


def test_authority_matrix_and_safety_floors_do_not_regress() -> None:
    authority = json.loads((INVENTORY / "authority_matrix.json").read_text(encoding="utf-8"))
    owners = {row["authority"]: row["owner"] for row in authority["rules"]}
    assert owners["formal semantic authority"] == "ipfs_datasets_py"
    assert owners["storage and retrieval authority"] == "ipfs_kit_py"
    assert owners["operational refactoring authority"] == "ipfs_accelerate_py"
    preregistration = json.loads(
        (INVENTORY / "benchmark_preregistration.json").read_text(encoding="utf-8")
    )
    floors = preregistration["zero_safety_floors"]
    assert floors and all(value == 0 for value in floors.values())


def test_import_is_provider_free() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
            imported_modules.add(node.module)
    assert "openai" not in imported
    assert "anthropic" not in imported
    assert "torch" not in imported
    assert "transformers" not in imported
    assert "ipfs_kit_py" not in imported
    assert "ipfs_accelerate_py" not in imported
    exports = provider_free_exports()
    assert "SCCSnapshot" in exports
    assert "ExtractionCondensationDAG" in exports
    assert "build_scc_snapshot" in exports


def test_records_are_frozen_and_policy_changes_identity() -> None:
    first = build_scc_snapshot(_mutual_calls())
    second = build_scc_snapshot(_mutual_calls())
    assert first.snapshot_cid == second.snapshot_cid
    with pytest.raises(Exception):
        first.tree_id = "mutated"  # type: ignore[misc]
    narrowed = HardEdgePolicy(hard_edge_kinds=("imports",))
    other = build_scc_snapshot(_mutual_calls(), policy=narrowed)
    assert other.snapshot_cid != first.snapshot_cid
    assert len(other.components) == 2
