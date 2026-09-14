"""Independent contract tests for SPAR-007 SemanticRefactoringGraphView@1."""

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
    AUTHORITY,
    AUTHORITY_OWNER,
    CAPSULE_ALIGNED_NODE_KINDS,
    DECLARED_EDGE_KINDS,
    DECLARED_NODE_KINDS,
    DUCKLAKE_IS_AUTHORITY,
    FORBIDDEN_EDGE_KINDS,
    GOAL_ID,
    GRAPH_BINDING_INTERFACE,
    GRAPH_CAN_AUTHORIZE_COMPLETION,
    GRAPH_CAN_AUTHORIZE_TRANSITION,
    GRAPH_CAN_CREATE_AUTHORITY,
    GRAPH_CID_CODEC,
    GRAPH_CID_PROFILE,
    GRAPH_CONTRACT_VERSION,
    IDENTITY_EXCLUDED_FIELDS,
    MARKDOWN_IS_NOT_COMPLETION,
    MODEL_OUTPUT_IS_PROPOSAL_ONLY,
    OBSERVED_EDGE_KINDS,
    PLAN_NODE_KINDS,
    QUERY_ADAPTER_DISPOSITION,
    QUERY_ADAPTER_OWNER,
    QUERY_ADAPTER_PATH,
    REFACTORING_GRAPH_EDGE_INTERFACE,
    REFACTORING_GRAPH_NODE_INTERFACE,
    SEMANTIC_REFACTORING_GRAPH_VIEW_INTERFACE,
    SEMANTIC_REFACTORING_GRAPH_VIEW_SCHEMA,
    STRUCTURAL_EDGE_KINDS,
    TASK_ID,
    TEST_PASS_IS_NOT_COMPLETION,
    UNRESOLVED_FRONTIER_INTERFACE,
    VECTOR_SIMILARITY_IS_AUTHORITY,
    WORKER_SELF_APPROVAL,
    FrontierReason,
    GraphBinding,
    GraphConfidence,
    GraphEvidenceClass,
    GraphFreshness,
    ProgramGraphContractError,
    RefactoringEdgeKind,
    RefactoringGraphEdge,
    RefactoringGraphNode,
    RefactoringNodeKind,
    ResolverStatus,
    SemanticRefactoringGraphView,
    UnresolvedFrontier,
    UnresolvedFrontierItem,
    build_semantic_refactoring_graph_view,
    decode_canonical_graph_view,
    encode_canonical_graph_view,
    graph_cid_profile,
    is_forbidden_edge_kind,
    is_structural_edge_kind,
    provider_free_exports,
    query_adapter_contract,
)


ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = (
    ROOT
    / "ipfs_datasets_py"
    / "ipfs_datasets_py"
    / "semantic_refactoring"
    / "program_graph.py"
)
TEST_PATH = Path(__file__).resolve()
INVENTORY = (
    ROOT
    / "docs"
    / "architecture"
    / "semantic_preserving_autonomous_remodularization_inventory"
)
WRITE_SCOPE = (
    "ipfs_datasets_py/ipfs_datasets_py/semantic_refactoring/program_graph.py",
    "ipfs_datasets_py/tests/unit/semantic_refactoring/test_program_graph.py",
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

TREE_ID = "5416da416de11b827dc5c95388e189390fd4522f"


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
    node_id: str = "node:pkg.mod.answer",
    *,
    kind: str = "function",
    qualified_name: str = "pkg.mod.answer",
    module_path: str = "pkg/mod.py",
    **overrides: Any,
) -> RefactoringGraphNode:
    fields: dict[str, Any] = {
        "node_id": node_id,
        "kind": kind,
        "qualified_name": qualified_name,
        "module_path": "" if kind == "repository" else module_path,
        "evidence_class": GraphEvidenceClass.EXACT_STATIC_FACT,
        "confidence": GraphConfidence.EXACT,
        "freshness": GraphFreshness.FRESH,
        "capsule_cid": _cid(f"capsule:{kind}:{qualified_name}")
        if kind in CAPSULE_ALIGNED_NODE_KINDS
        else None,
        "identity_set_cid": _cid(f"identity:{qualified_name}"),
    }
    fields.update(overrides)
    return RefactoringGraphNode(**fields)


def _edge(
    source_id: str,
    target_id: str,
    kind: str = "contains",
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


def _frontier_item(
    subject_id: str,
    *,
    subject_kind: str = "node",
    reason: str = FrontierReason.UNRESOLVED_IDENTITY.value,
    **overrides: Any,
) -> UnresolvedFrontierItem:
    fields = {
        "subject_id": subject_id,
        "subject_kind": subject_kind,
        "reason": reason,
        "evidence_class": GraphEvidenceClass.CONSERVATIVE_MAY_FACT,
        "confidence": GraphConfidence.CONSERVATIVE,
        "unresolved_fields": ("symbol_binding_cid",),
    }
    fields.update(overrides)
    return UnresolvedFrontierItem(**fields)


def _view(**overrides: Any) -> SemanticRefactoringGraphView:
    repository = _node(
        "node:repo",
        kind="repository",
        qualified_name="repository:semantic-preserving-autonomous-remodularization-v1",
        module_path="",
        capsule_cid=None,
    )
    module = _node(
        "node:pkg.mod",
        kind="module",
        qualified_name="pkg.mod",
        module_path="pkg/mod.py",
    )
    function = _node()
    fields: dict[str, Any] = {
        "binding": _binding(),
        "nodes": (repository, module, function),
        "edges": (
            _edge("node:repo", "node:pkg.mod", "contains"),
            _edge("node:pkg.mod", "node:pkg.mod.answer", "defines"),
        ),
        "unresolved_frontier": UnresolvedFrontier(),
    }
    fields.update(overrides)
    return SemanticRefactoringGraphView(**fields)


def test_owned_paths_and_task_identity_are_exact() -> None:
    assert TASK_ID == "SPAR-007"
    assert GOAL_ID == "SPAR-G021"
    assert SEMANTIC_REFACTORING_GRAPH_VIEW_INTERFACE == "SemanticRefactoringGraphView@1"
    assert REFACTORING_GRAPH_NODE_INTERFACE == "RefactoringGraphNode@1"
    assert REFACTORING_GRAPH_EDGE_INTERFACE == "RefactoringGraphEdge@1"
    assert GRAPH_BINDING_INTERFACE == "GraphBinding@1"
    assert UNRESOLVED_FRONTIER_INTERFACE == "UnresolvedFrontier@1"
    assert SEMANTIC_REFACTORING_GRAPH_VIEW_SCHEMA.endswith("@1")
    assert GRAPH_CONTRACT_VERSION == "1"
    assert MODULE_PATH.is_file()
    assert TEST_PATH.is_file()
    for relative in WRITE_SCOPE:
        assert (ROOT / relative).is_file()


def test_authority_flags_cannot_self_authorize() -> None:
    assert AUTHORITY == "formal semantic authority"
    assert AUTHORITY_OWNER == "ipfs_datasets_py"
    assert GRAPH_CAN_AUTHORIZE_COMPLETION is False
    assert GRAPH_CAN_AUTHORIZE_TRANSITION is False
    assert GRAPH_CAN_CREATE_AUTHORITY is False
    assert VECTOR_SIMILARITY_IS_AUTHORITY is False
    assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
    assert TEST_PASS_IS_NOT_COMPLETION is True
    assert MARKDOWN_IS_NOT_COMPLETION is True
    assert WORKER_SELF_APPROVAL is False
    assert DUCKLAKE_IS_AUTHORITY is False
    profile = graph_cid_profile()
    assert profile["profile_id"] == PROFILE_ID == GRAPH_CID_PROFILE
    assert profile["codec"] == STRUCTURED_CODEC == GRAPH_CID_CODEC
    assert "not universal meaning" in profile["rule"]


def test_query_adapter_is_reuse_only_and_datasets_owns_meaning() -> None:
    contract = query_adapter_contract()
    assert contract["path"] == QUERY_ADAPTER_PATH
    assert contract["disposition"] == QUERY_ADAPTER_DISPOSITION == "reuse_query_adapter"
    assert contract["owner"] == QUERY_ADAPTER_OWNER == "ipfs_accelerate_py"
    assert contract["semantic_owner"] == "ipfs_datasets_py"
    assert contract["happens_before_edges"] == "absent"
    assert contract["initialization_order_edges"] == "absent"
    adapter = ROOT / QUERY_ADAPTER_PATH
    assert adapter.is_file()
    inventory = json.loads((INVENTORY / "interface_inventory.json").read_text(encoding="utf-8"))
    program_graph = next(
        item for item in inventory["interfaces"] if item["concern"] == "program_graph"
    )
    assert program_graph["disposition"] == "reuse_query_adapter"
    assert program_graph["path"] == QUERY_ADAPTER_PATH
    capability = json.loads(
        (INVENTORY / "verified_capability_matrix.json").read_text(encoding="utf-8")
    )
    row = next(item for item in capability["capabilities"] if item["id"] == "program_graph")
    assert row["disposition"] == "reuse_query_adapter"
    assert "happens-before" in row["notes"]


def test_module_defines_predicted_symbols_not_capsule_family() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "SemanticRefactoringGraphView" in names
    assert "RefactoringGraphNode" in names
    assert "RefactoringGraphEdge" in names
    assert "GraphBinding" in names
    assert "UnresolvedFrontier" in names
    for capsule in CAPSULE_TYPES:
        assert capsule not in names
    assert "ProgramGraph" not in names
    assert "ProgramNodeKind" not in names


def test_closed_vocabularies_cover_plan_and_capsule_kinds() -> None:
    assert set(CAPSULE_ALIGNED_NODE_KINDS) <= DECLARED_NODE_KINDS
    assert set(PLAN_NODE_KINDS) <= DECLARED_NODE_KINDS
    assert DECLARED_NODE_KINDS == {kind.value for kind in RefactoringNodeKind}
    assert DECLARED_EDGE_KINDS == {kind.value for kind in RefactoringEdgeKind}
    assert STRUCTURAL_EDGE_KINDS.isdisjoint(OBSERVED_EDGE_KINDS)
    assert STRUCTURAL_EDGE_KINDS | OBSERVED_EDGE_KINDS == DECLARED_EDGE_KINDS
    assert FORBIDDEN_EDGE_KINDS.isdisjoint(DECLARED_EDGE_KINDS)
    assert "happens_before" in FORBIDDEN_EDGE_KINDS
    assert "initialization_order" in FORBIDDEN_EDGE_KINDS
    assert is_forbidden_edge_kind("happens_before") is True
    assert is_structural_edge_kind("contains") is True
    assert is_structural_edge_kind("calls") is False


def test_binding_and_nested_records_round_trip() -> None:
    binding = _binding()
    restored = GraphBinding.from_dict(binding.to_dict())
    assert restored == binding
    assert restored.binding_cid == cid_for_structured(binding.identity_payload())
    node = _node()
    assert RefactoringGraphNode.from_dict(node.to_dict()) == node
    assert node.node_cid == cid_for_structured(node.identity_payload())
    edge = _edge("node:pkg.mod", "node:pkg.mod.answer", "defines")
    assert RefactoringGraphEdge.from_dict(edge.to_dict()) == edge
    item = _frontier_item("node:pkg.mod.answer")
    assert UnresolvedFrontierItem.from_dict(item.to_dict()) == item
    frontier = UnresolvedFrontier(items=(item,))
    assert UnresolvedFrontier.from_dict(frontier.to_dict()) == frontier
    assert frontier.explicit is True


def test_graph_view_round_trips_and_reverifies_independent_cid() -> None:
    view = _view()
    restored = SemanticRefactoringGraphView.from_dict(view.to_dict())
    assert restored == view
    assert restored.graph_view_cid == view.graph_view_cid
    assert restored.graph_view_cid == cid_for_structured(view.identity_payload())
    payload = view.identity_payload()
    assert payload.get("graph_view_cid") is None
    encoded = encode_canonical_graph_view(view)
    assert decode_canonical_graph_view(encoded).graph_view_cid == view.graph_view_cid
    rebuilt = build_semantic_refactoring_graph_view(
        binding=view.binding,
        nodes=view.nodes,
        edges=view.edges,
        unresolved_frontier=view.unresolved_frontier,
    )
    assert rebuilt.graph_view_cid == view.graph_view_cid
    assert rebuilt.tree_id == TREE_ID


def test_nodes_and_edges_are_canonically_ordered() -> None:
    view = SemanticRefactoringGraphView(
        binding=_binding(),
        nodes=(
            _node("node:b", kind="function", qualified_name="pkg.b"),
            _node("node:a", kind="module", qualified_name="pkg", module_path="pkg/__init__.py"),
        ),
        edges=(
            _edge("node:a", "node:b", "defines"),
            _edge("node:a", "node:b", "contains"),
        ),
    )
    assert view.node_ids == ("node:a", "node:b")
    assert tuple(edge.kind for edge in view.edges) == ("contains", "defines")


def test_duplicate_nodes_and_edges_are_rejected() -> None:
    with pytest.raises(ProgramGraphContractError, match="duplicate node_id"):
        SemanticRefactoringGraphView(
            binding=_binding(),
            nodes=(_node(), _node()),
        )
    with pytest.raises(ProgramGraphContractError, match="duplicate"):
        SemanticRefactoringGraphView(
            binding=_binding(),
            nodes=(
                _node("node:mod", kind="module", qualified_name="pkg.mod"),
                _node(),
            ),
            edges=(
                _edge("node:mod", "node:pkg.mod.answer", "defines"),
                _edge("node:mod", "node:pkg.mod.answer", "defines"),
            ),
        )


def test_dangling_edges_are_rejected() -> None:
    with pytest.raises(ProgramGraphContractError, match="not present"):
        SemanticRefactoringGraphView(
            binding=_binding(),
            nodes=(_node(),),
            edges=(_edge("node:missing", "node:pkg.mod.answer", "calls"),),
        )


def test_structural_cycles_are_illegal_call_cycles_are_retained() -> None:
    left = _node("node:left", kind="function", qualified_name="pkg.left")
    right = _node("node:right", kind="function", qualified_name="pkg.right")
    with pytest.raises(ProgramGraphContractError, match="illegal structural cycle"):
        SemanticRefactoringGraphView(
            binding=_binding(),
            nodes=(left, right),
            edges=(
                _edge("node:left", "node:right", "depends_on"),
                _edge("node:right", "node:left", "depends_on"),
            ),
        )
    cyclic_calls = SemanticRefactoringGraphView(
        binding=_binding(),
        nodes=(left, right),
        edges=(
            _edge("node:left", "node:right", "calls"),
            _edge("node:right", "node:left", "calls"),
        ),
    )
    assert len(cyclic_calls.edges_for_kind("calls")) == 2


@pytest.mark.parametrize("kind", sorted(FORBIDDEN_EDGE_KINDS))
def test_happens_before_and_initialization_order_edges_are_rejected(kind: str) -> None:
    with pytest.raises(ProgramGraphContractError, match="forbidden edge kind"):
        RefactoringGraphEdge(
            source_id="node:a",
            target_id="node:b",
            kind=kind,
        )
    with pytest.raises(ProgramGraphContractError, match="forbidden edge kind"):
        SemanticRefactoringGraphView(
            binding=_binding(),
            nodes=(
                _node("node:a", kind="top_level_block", qualified_name="pkg.mod:block:0"),
                _node("node:b", kind="top_level_block", qualified_name="pkg.mod:block:1"),
            ),
            edges=({"source_id": "node:a", "target_id": "node:b", "kind": kind},),
        )
    with pytest.raises(ProgramGraphContractError, match="forbidden edge kind"):
        _view().edges_for_kind(kind)


def test_exact_capsule_aligned_nodes_require_capsule_cid() -> None:
    with pytest.raises(ProgramGraphContractError, match="capsule_cid"):
        _node(capsule_cid=None)
    opaque = _node(
        capsule_cid=None,
        confidence=GraphConfidence.OPAQUE,
        evidence_class=GraphEvidenceClass.UNKNOWN,
    )
    assert opaque.requires_frontier is True


def test_unresolved_residuals_must_be_explicit_on_the_frontier() -> None:
    dynamic = _node(
        "node:pkg.mod.dispatch",
        kind="callsite",
        qualified_name="pkg.mod.dispatch",
        confidence=GraphConfidence.CONSERVATIVE,
        evidence_class=GraphEvidenceClass.CONSERVATIVE_MAY_FACT,
        capsule_cid=_cid("capsule:callsite:dispatch"),
    )
    exact = _node()
    edge = _edge(
        "node:pkg.mod.answer",
        "node:pkg.mod.dispatch",
        "calls",
        confidence=GraphConfidence.CONSERVATIVE,
        evidence_class=GraphEvidenceClass.CONSERVATIVE_MAY_FACT,
        resolver_status=ResolverStatus.DYNAMIC,
    )
    with pytest.raises(ProgramGraphContractError, match="explicit frontier"):
        SemanticRefactoringGraphView(
            binding=_binding(),
            nodes=(exact, dynamic),
            edges=(edge,),
        )
    view = SemanticRefactoringGraphView(
        binding=_binding(),
        nodes=(exact, dynamic),
        edges=(edge,),
        unresolved_frontier=(
            _frontier_item(
                "node:pkg.mod.dispatch",
                reason=FrontierReason.DYNAMIC_DISPATCH.value,
            ),
        ),
    )
    assert view.unresolved_frontier.explicit is True
    assert "node:pkg.mod.dispatch" in view.unresolved_frontier.subject_ids
    assert view.may_fact_edges()
    assert exact in view.exact_static_nodes()


def test_exact_edges_cannot_be_unresolved() -> None:
    with pytest.raises(ProgramGraphContractError, match="resolved_static"):
        _edge(
            "node:a",
            "node:b",
            "calls",
            resolver_status=ResolverStatus.UNRESOLVED,
        )


def test_forged_cids_are_rejected() -> None:
    view = _view()
    payload = view.to_dict()
    payload["graph_view_cid"] = _cid("forged")
    with pytest.raises(ProgramGraphContractError, match="does not verify"):
        SemanticRefactoringGraphView.from_dict(payload)
    node_payload = _node().to_dict()
    node_payload["node_cid"] = _cid("forged-node")
    with pytest.raises(ProgramGraphContractError, match="does not verify"):
        RefactoringGraphNode.from_dict(node_payload)


def test_unknown_missing_and_observational_fields_are_rejected() -> None:
    payload = _view().to_dict()
    payload["timestamp"] = "now"
    with pytest.raises(ProgramGraphContractError, match="observational"):
        SemanticRefactoringGraphView.from_dict(payload)
    payload = _view().to_dict()
    payload["extra"] = "nope"
    with pytest.raises(ProgramGraphContractError, match="unknown"):
        SemanticRefactoringGraphView.from_dict(payload)
    payload = _view().to_dict()
    payload.pop("binding")
    with pytest.raises(ProgramGraphContractError, match="missing"):
        SemanticRefactoringGraphView.from_dict(payload)
    with pytest.raises(ProgramGraphContractError, match="local filesystem path"):
        _node(qualified_name="/tmp/mod.py")
    with pytest.raises(ProgramGraphContractError, match="relative POSIX"):
        _node(module_path="../escape.py")
    with pytest.raises(ProgramGraphContractError, match="lowercase hex"):
        _binding(tree_id="not-a-tree")
    assert "timestamp" in IDENTITY_EXCLUDED_FIELDS
    assert "model_output" in IDENTITY_EXCLUDED_FIELDS


def test_query_adapter_path_cannot_be_replaced() -> None:
    with pytest.raises(ProgramGraphContractError, match="query_adapter_path"):
        SemanticRefactoringGraphView(
            binding=_binding(),
            nodes=(_node(),),
            query_adapter_path="other/program_graph.py",
        )


def test_records_are_frozen_and_duplicate_construction_is_deterministic() -> None:
    first = _view()
    second = _view()
    assert first.graph_view_cid == second.graph_view_cid
    with pytest.raises(Exception):
        first.tree_id = "mutated"  # type: ignore[misc]
    changed = SemanticRefactoringGraphView(
        binding=_binding(environment_cid=_cid("environment:other")),
        nodes=first.nodes,
        edges=first.edges,
    )
    assert changed.graph_view_cid != first.graph_view_cid


def test_nodes_for_kind_and_adapter_map() -> None:
    view = _view()
    functions = view.nodes_for_kind(RefactoringNodeKind.FUNCTION)
    assert len(functions) == 1
    assert view.query_adapter_node_kind("function") == "symbol"
    assert view.query_adapter_node_kind("module") == "module"
    assert view.query_adapter_node_kind("test") == "test"


def test_opaque_frontier_items_require_unresolved_fields() -> None:
    with pytest.raises(ProgramGraphContractError, match="unresolved_fields"):
        _frontier_item(
            "node:pkg.mod.answer",
            confidence=GraphConfidence.OPAQUE,
            evidence_class=GraphEvidenceClass.UNKNOWN,
            unresolved_fields=(),
        )
    with pytest.raises(ProgramGraphContractError, match="exact confidence"):
        _frontier_item(
            "node:pkg.mod.answer",
            confidence=GraphConfidence.EXACT,
            evidence_class=GraphEvidenceClass.EXACT_STATIC_FACT,
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
    identity = json.loads((INVENTORY / "identity_inventory.json").read_text(encoding="utf-8"))
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    for capsule in identity["capsule_types"]:
        assert capsule.split("@", 1)[0] not in names


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
    assert "ipfs_datasets_py.semantic_refactoring.capsules" not in imported_modules
    assert "ipfs_datasets_py.semantic_refactoring.identities" not in imported_modules
    assert "ipfs_datasets_py.semantic_refactoring.compatibility" not in imported_modules
    assert "ipfs_datasets_py.semantic_refactoring.projections" not in imported_modules
    assert "ipfs_datasets_py.semantic_refactoring.public_compatibility" not in imported_modules
    assert "software_contracts" in source
    assert "cid_for_structured" in source
    assert "does not replace" in source
    assert "happens-before" in source.lower() or "happens_before" in source
    exports = provider_free_exports()
    assert exports == tuple(sorted(exports))
    forbidden_export_names = {
        "openai",
        "anthropic",
        "torch",
        "transformers",
        "model_output",
        "SemanticCapsuleCompiler",
        "FunctionSemanticCapsule",
        "ProgramGraph",
    }
    assert forbidden_export_names.isdisjoint(set(exports))
    assert "SemanticRefactoringGraphView" in exports
    assert "build_semantic_refactoring_graph_view" in exports
    assert "query_adapter_contract" in exports
    assert "llm" not in {name.lower() for name in exports}
