"""Independent contract tests for SPAR-010 initialization-order graphs."""

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
from ipfs_datasets_py.semantic_refactoring.compatibility import (  # noqa: E402
    EvidenceClass,
    InitializationEffectKind,
    SupportStatus,
)
from ipfs_datasets_py.semantic_refactoring.dynamic_frontier import (  # noqa: E402
    DEFAULT_HERMETIC_PROFILE,
    NETWORK_DENY,
)
from ipfs_datasets_py.semantic_refactoring.program_graph import (  # noqa: E402
    FORBIDDEN_EDGE_KINDS,
    QUERY_ADAPTER_PATH,
    RefactoringGraphEdge,
)
from ipfs_datasets_py.semantic_refactoring.initialization import (  # noqa: E402
    ANALYZER_ID,
    AUTHORITY,
    AUTHORITY_OWNER,
    DECLARED_NODE_KINDS,
    DECLARED_RELATION_KINDS,
    DUCKLAKE_IS_AUTHORITY,
    GOAL_ID,
    IDENTITY_EXCLUDED_FIELDS,
    INIT_CAN_AUTHORIZE_COMPLETION,
    INIT_CAN_AUTHORIZE_TRANSITION,
    INIT_CAN_CREATE_AUTHORITY,
    INIT_CID_CODEC,
    INIT_CID_PROFILE,
    INITIALIZATION_ORDER_GRAPH_INTERFACE,
    INITIALIZATION_ORDER_GRAPH_SCHEMA,
    INITIALIZATION_STATE_MACHINE_INTERFACE,
    MARKDOWN_IS_NOT_COMPLETION,
    MODEL_OUTPUT_IS_PROPOSAL_ONLY,
    OWNED_SPAR007_FORBIDDEN_RELATIONS,
    RUNTIME_OBSERVATION_IS_NOT_STATIC_FACT,
    TASK_ID,
    TEST_PASS_IS_NOT_COMPLETION,
    VECTOR_SIMILARITY_IS_AUTHORITY,
    WORKER_SELF_APPROVAL,
    InitializationCandidate,
    InitializationCandidateKind,
    InitializationConfidence,
    InitializationContractError,
    InitializationGraphNode,
    InitializationMachineEvent,
    InitializationMachineState,
    InitializationNodeKind,
    InitializationOrderEdge,
    InitializationOrderGraph,
    InitializationRelationKind,
    InitializationStateMachine,
    InitializationTerminal,
    InitializationTerminalKind,
    analyze_source,
    build_initialization_order_graph,
    decode_canonical_initialization_graph,
    encode_canonical_initialization_graph,
    evaluate_initialization_order,
    initialization_cid_profile,
    provider_free_exports,
    relation_ownership_contract,
)


ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = (
    ROOT
    / "ipfs_datasets_py"
    / "ipfs_datasets_py"
    / "semantic_refactoring"
    / "initialization.py"
)
TEST_PATH = Path(__file__).resolve()
INVENTORY = (
    ROOT
    / "docs"
    / "architecture"
    / "semantic_preserving_autonomous_remodularization_inventory"
)
WRITE_SCOPE = (
    "ipfs_datasets_py/ipfs_datasets_py/semantic_refactoring/initialization.py",
    "ipfs_datasets_py/tests/unit/semantic_refactoring/test_initialization.py",
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
MODULE_FILE = "pkg/mod.py"
MODULE_NAME = "pkg.mod"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _analyze(source: str, *, module_name: str = MODULE_NAME) -> InitializationOrderGraph:
    return analyze_source(
        source,
        tree_id=TREE_ID,
        module_path=MODULE_FILE,
        module_name=module_name,
    )


def _node(
    node_id: str = "block:pkg.mod:toplevel:0",
    **overrides: Any,
) -> InitializationGraphNode:
    fields: dict[str, Any] = {
        "node_id": node_id,
        "kind": InitializationNodeKind.TOP_LEVEL_BLOCK,
        "qualified_name": "pkg.mod:block:0",
        "module_path": MODULE_FILE,
        "order_index": 0,
        "start_line": 1,
        "end_line": 1,
    }
    fields.update(overrides)
    return InitializationGraphNode(**fields)


def _edge(
    source_id: str,
    target_id: str,
    kind: str = "happens_before",
    **overrides: Any,
) -> InitializationOrderEdge:
    fields: dict[str, Any] = {
        "source_id": source_id,
        "target_id": target_id,
        "kind": kind,
    }
    fields.update(overrides)
    return InitializationOrderEdge(**fields)


def test_owned_paths_and_task_identity_are_exact() -> None:
    assert TASK_ID == "SPAR-010"
    assert GOAL_ID == "SPAR-G022"
    assert INITIALIZATION_ORDER_GRAPH_INTERFACE == "InitializationOrderGraph@1"
    assert INITIALIZATION_STATE_MACHINE_INTERFACE == "InitializationStateMachine@1"
    assert INITIALIZATION_ORDER_GRAPH_SCHEMA.endswith("@1")
    assert MODULE_PATH.is_file()
    assert TEST_PATH.is_file()
    for relative in WRITE_SCOPE:
        assert (ROOT / relative).is_file()


def test_authority_flags_cannot_self_authorize() -> None:
    assert AUTHORITY == "formal semantic authority"
    assert AUTHORITY_OWNER == "ipfs_datasets_py"
    assert ANALYZER_ID == "spar-010-initialization"
    assert INIT_CAN_AUTHORIZE_COMPLETION is False
    assert INIT_CAN_AUTHORIZE_TRANSITION is False
    assert INIT_CAN_CREATE_AUTHORITY is False
    assert VECTOR_SIMILARITY_IS_AUTHORITY is False
    assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
    assert TEST_PASS_IS_NOT_COMPLETION is True
    assert MARKDOWN_IS_NOT_COMPLETION is True
    assert WORKER_SELF_APPROVAL is False
    assert DUCKLAKE_IS_AUTHORITY is False
    assert RUNTIME_OBSERVATION_IS_NOT_STATIC_FACT is True
    profile = initialization_cid_profile()
    assert profile["profile_id"] == PROFILE_ID == INIT_CID_PROFILE
    assert profile["codec"] == STRUCTURED_CODEC == INIT_CID_CODEC
    assert "not universal meaning" in profile["rule"]


def test_module_defines_predicted_symbols_not_capsule_family() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "InitializationOrderGraph" in names
    assert "InitializationStateMachine" in names
    assert "InitializationGraphNode" in names
    assert "InitializationOrderEdge" in names
    for capsule in CAPSULE_TYPES:
        assert capsule not in names
    assert "SemanticRefactoringGraphView" not in names
    assert "ProgramGraph" not in names


def test_spar010_owns_relations_forbidden_on_spar007() -> None:
    contract = relation_ownership_contract()
    assert contract["happens_before_edges"] == "owned"
    assert contract["initialization_order_edges"] == "owned"
    assert contract["spar007_happens_before_edges"] == "absent"
    assert contract["spar007_initialization_order_edges"] == "absent"
    assert contract["semantic_owner"] == "ipfs_datasets_py"
    assert contract["query_adapter_path"] == QUERY_ADAPTER_PATH
    assert OWNED_SPAR007_FORBIDDEN_RELATIONS <= FORBIDDEN_EDGE_KINDS
    assert DECLARED_RELATION_KINDS == {
        "happens_before",
        "initialization_order",
    }
    assert DECLARED_NODE_KINDS == {"top_level_block"}
    with pytest.raises(Exception, match="forbidden edge kind"):
        RefactoringGraphEdge(
            source_id="node:a",
            target_id="node:b",
            kind="happens_before",
        )
    with pytest.raises(Exception, match="forbidden edge kind"):
        RefactoringGraphEdge(
            source_id="node:a",
            target_id="node:b",
            kind="initialization_order",
        )


def test_closed_vocabularies_cover_owned_relations() -> None:
    assert DECLARED_RELATION_KINDS == {
        kind.value for kind in InitializationRelationKind
    }
    assert DECLARED_NODE_KINDS == {kind.value for kind in InitializationNodeKind}
    assert "timestamp" in IDENTITY_EXCLUDED_FIELDS
    assert "current_state" in IDENTITY_EXCLUDED_FIELDS
    assert "model_output" in IDENTITY_EXCLUDED_FIELDS


def test_top_level_execution_is_partitioned_into_content_addressed_blocks() -> None:
    source = "import os\n\nVALUE = 1\n\ndef answer() -> int:\n    return VALUE\n"
    graph = _analyze(source)
    assert len(graph.nodes) == 3
    assert [node.order_index for node in graph.nodes] == [0, 1, 2]
    assert graph.nodes[0].effect_kinds == (InitializationEffectKind.IMPORT.value,)
    assert "VALUE" in graph.nodes[1].defined_names
    assert "answer" in graph.nodes[2].defined_names
    assert graph.nodes[0].node_cid == cid_for_structured(graph.nodes[0].identity_payload())
    restored = InitializationGraphNode.from_dict(graph.nodes[0].to_dict())
    assert restored == graph.nodes[0]


def test_sequential_happens_before_and_initialization_order_are_exact() -> None:
    graph = _analyze("import os\nVALUE = 1\n")
    happens = graph.edges_for_kind("happens_before")
    order = graph.edges_for_kind("initialization_order")
    assert len(happens) == 1
    assert happens[0].source_id == graph.nodes[0].node_id
    assert happens[0].target_id == graph.nodes[1].node_id
    assert happens[0].evidence_class == EvidenceClass.EXACT_STATIC_FACT.value
    assert happens[0].confidence == InitializationConfidence.EXACT.value
    assert any(
        edge.source_id == graph.nodes[0].node_id
        and edge.target_id == graph.nodes[1].node_id
        for edge in order
    )
    assert graph.linearization == (graph.nodes[0].node_id, graph.nodes[1].node_id)
    assert graph.cyclic is False


def test_graph_round_trips_and_reverifies_independent_cid() -> None:
    graph = _analyze("import os\nVALUE = 1\n")
    restored = InitializationOrderGraph.from_dict(graph.to_dict())
    assert restored == graph
    assert restored.graph_cid == graph.graph_cid
    assert restored.graph_cid == cid_for_structured(graph.identity_payload())
    payload = graph.identity_payload()
    assert payload.get("graph_cid") is None
    encoded = encode_canonical_initialization_graph(graph)
    assert decode_canonical_initialization_graph(encoded).graph_cid == graph.graph_cid
    rebuilt = build_initialization_order_graph(
        tree_id=graph.tree_id,
        source_cid=graph.source_cid,
        module_path=graph.module_path,
        module_name=graph.module_name,
        nodes=graph.nodes,
        edges=graph.edges,
        candidates=graph.candidates,
        state_machine=graph.state_machine,
        observation_profile_cid=graph.observation_profile_cid,
    )
    assert rebuilt.graph_cid == graph.graph_cid
    via_json = InitializationOrderGraph.from_dict(json.loads(json.dumps(graph.to_dict())))
    assert via_json.graph_cid == graph.graph_cid


def test_import_time_registrations_decorators_and_resources_are_typed() -> None:
    source = (
        "import atexit\n"
        "REGISTRY = {}\n"
        "\n"
        "def _stop() -> None:\n"
        "    return None\n"
        "\n"
        "@atexit.register\n"
        "def close() -> None:\n"
        "    return None\n"
        "\n"
        "REGISTRY['build'] = close\n"
        "HANDLE = open('x', 'w')\n"
    )
    graph = _analyze(source)
    kinds = {kind for node in graph.nodes for kind in node.effect_kinds}
    assert InitializationEffectKind.IMPORT.value in kinds
    assert InitializationEffectKind.DECORATOR.value in kinds
    assert InitializationEffectKind.ATEXIT.value in kinds or (
        InitializationEffectKind.DECORATOR.value in kinds
    )
    assert InitializationEffectKind.REGISTRATION.value in kinds
    assert InitializationEffectKind.RESOURCE.value in kinds
    candidate_kinds = {item.kind for item in graph.candidates}
    assert InitializationCandidateKind.EXPLICIT_INITIALIZER.value in candidate_kinds
    assert InitializationCandidateKind.PRESERVE_ORDER.value in candidate_kinds


def test_use_before_definition_is_an_explicit_cycle() -> None:
    graph = _analyze("VALUE = helper()\n\ndef helper() -> int:\n    return 1\n")
    assert graph.cyclic is True
    assert graph.linearization == ()
    order = graph.edges_for_kind("initialization_order")
    assert any(
        edge.confidence == InitializationConfidence.CONSERVATIVE.value
        for edge in order
    )
    terminal = graph.evaluate()
    assert terminal.kind == InitializationTerminalKind.CYCLIC.value
    assert terminal.success is False
    assert terminal.authorizes_completion is False
    lazy = next(
        item
        for item in graph.candidates
        if item.kind == InitializationCandidateKind.LAZY_IMPORT.value
    )
    assert lazy.required is True


def test_self_import_is_an_explicit_cycle() -> None:
    graph = _analyze("import pkg.mod\nVALUE = 1\n")
    assert graph.self_import_ids
    assert graph.cyclic is True
    terminal = evaluate_initialization_order(graph)
    assert terminal.kind == InitializationTerminalKind.CYCLIC.value
    assert terminal.success is False


def test_eval_at_import_time_is_unsupported_required_never_success() -> None:
    graph = _analyze("VALUE = eval('1 + 1')\n")
    node = graph.nodes[0]
    assert node.support_status == SupportStatus.UNSUPPORTED.value
    assert node.unresolved is True
    terminal = graph.evaluate()
    assert terminal.kind == InitializationTerminalKind.UNSUPPORTED_REQUIRED.value
    assert terminal.success is False
    assert terminal.authorizes_completion is False


def test_relative_import_stays_conservative_and_unresolved() -> None:
    graph = _analyze("from . import sibling\n")
    node = graph.nodes[0]
    assert node.confidence == InitializationConfidence.CONSERVATIVE.value
    assert node.evidence_class == EvidenceClass.CONSERVATIVE_MAY_FACT.value
    assert node.unresolved is True
    assert InitializationEffectKind.IMPORT.value in node.effect_kinds


def test_observation_profile_is_bound_and_cannot_upgrade_runtime_evidence() -> None:
    graph = _analyze("VALUE = 1\n")
    assert graph.observation_profile_cid == DEFAULT_HERMETIC_PROFILE.profile_cid
    assert DEFAULT_HERMETIC_PROFILE.network == NETWORK_DENY
    with pytest.raises(InitializationContractError, match="runtime observation"):
        _node(
            evidence_class=EvidenceClass.RUNTIME_OBSERVATION,
            confidence=InitializationConfidence.EXACT,
        )
    with pytest.raises(InitializationContractError, match="cannot be unresolved"):
        _node(unresolved=True)


def test_state_machine_is_closed_and_has_no_live_runtime_pointer() -> None:
    graph = _analyze("import os\nVALUE = 1\n")
    machine = graph.state_machine
    assert isinstance(machine, InitializationStateMachine)
    assert machine.initial_state == InitializationMachineState.UNINITIALIZED.value
    assert InitializationMachineState.INITIALIZED.value in machine.accepting_states
    assert InitializationMachineState.CYCLIC.value in machine.failure_states
    assert machine.block_ids == graph.node_ids
    assert machine.step(
        InitializationMachineState.UNINITIALIZED.value,
        InitializationMachineEvent.START.value,
    ) == InitializationMachineState.IMPORTING.value
    assert machine.step(
        InitializationMachineState.IMPORTING.value,
        InitializationMachineEvent.EXECUTE.value,
    ) == InitializationMachineState.EXECUTING.value
    assert machine.step(
        InitializationMachineState.EXECUTING.value,
        InitializationMachineEvent.COMPLETE.value,
    ) == InitializationMachineState.INITIALIZED.value
    assert machine.step(
        InitializationMachineState.IMPORTING.value,
        InitializationMachineEvent.CYCLE.value,
    ) == InitializationMachineState.CYCLIC.value
    restored = InitializationStateMachine.from_dict(machine.to_dict())
    assert restored == machine
    assert restored.machine_cid == cid_for_structured(machine.identity_payload())
    payload = machine.to_dict()
    payload["current_state"] = "importing"
    with pytest.raises(InitializationContractError, match="observational"):
        InitializationStateMachine.from_dict(payload)


def test_admitted_evaluation_does_not_authorize_completion() -> None:
    graph = _analyze("import os\nVALUE = 1\n")
    terminal = graph.evaluate()
    assert terminal.kind == InitializationTerminalKind.ADMITTED.value
    assert terminal.success is True
    assert terminal.authorizes_completion is False
    restored = InitializationTerminal.from_dict(terminal.to_dict())
    assert restored == terminal
    assert restored.authorizes_completion is False


def test_missing_observation_profile_is_incomplete_not_success() -> None:
    node = _node()
    graph = InitializationOrderGraph(
        tree_id=TREE_ID,
        source_cid=_cid("source"),
        module_path=MODULE_FILE,
        module_name=MODULE_NAME,
        nodes=(node,),
        observation_profile_cid=None,
    )
    terminal = graph.evaluate()
    assert terminal.kind == InitializationTerminalKind.INCOMPLETE_CONTRACT.value
    assert terminal.success is False


def test_reflexive_and_dangling_edges_are_rejected() -> None:
    with pytest.raises(InitializationContractError, match="reflexive"):
        _edge("block:pkg.mod:toplevel:0", "block:pkg.mod:toplevel:0")
    with pytest.raises(InitializationContractError, match="not present"):
        InitializationOrderGraph(
            tree_id=TREE_ID,
            source_cid=_cid("source"),
            module_path=MODULE_FILE,
            module_name=MODULE_NAME,
            nodes=(_node(),),
            edges=(_edge("block:missing", "block:pkg.mod:toplevel:0"),),
            observation_profile_cid=DEFAULT_HERMETIC_PROFILE.profile_cid,
        )


def test_duplicate_nodes_and_edges_fail_closed() -> None:
    with pytest.raises(InitializationContractError, match="duplicate node_id"):
        InitializationOrderGraph(
            tree_id=TREE_ID,
            source_cid=_cid("source"),
            module_path=MODULE_FILE,
            module_name=MODULE_NAME,
            nodes=(_node(), _node()),
            observation_profile_cid=DEFAULT_HERMETIC_PROFILE.profile_cid,
        )
    left = _node()
    right = _node(
        "block:pkg.mod:toplevel:1",
        qualified_name="pkg.mod:block:1",
        order_index=1,
        start_line=2,
        end_line=2,
    )
    with pytest.raises(InitializationContractError, match="duplicate"):
        InitializationOrderGraph(
            tree_id=TREE_ID,
            source_cid=_cid("source"),
            module_path=MODULE_FILE,
            module_name=MODULE_NAME,
            nodes=(left, right),
            edges=(
                _edge(left.node_id, right.node_id),
                _edge(left.node_id, right.node_id),
            ),
            observation_profile_cid=DEFAULT_HERMETIC_PROFILE.profile_cid,
        )


def test_unknown_and_observational_fields_are_rejected() -> None:
    graph = _analyze("VALUE = 1\n")
    payload = graph.to_dict()
    payload["timestamp"] = "now"
    with pytest.raises(InitializationContractError, match="observational"):
        InitializationOrderGraph.from_dict(payload)
    payload = graph.to_dict()
    payload["extra"] = "nope"
    with pytest.raises(InitializationContractError, match="unknown"):
        InitializationOrderGraph.from_dict(payload)
    payload = graph.to_dict()
    payload.pop("module_path")
    with pytest.raises(InitializationContractError, match="missing"):
        InitializationOrderGraph.from_dict(payload)


def test_forged_cids_and_schema_versions_fail_closed() -> None:
    graph = _analyze("VALUE = 1\n")
    payload = graph.to_dict()
    payload["graph_cid"] = _cid("forged")
    with pytest.raises(InitializationContractError, match="does not verify"):
        InitializationOrderGraph.from_dict(payload)
    payload = graph.to_dict()
    payload["schema"] = "ipfs-datasets.semantic-refactoring.initialization-order-graph@0"
    with pytest.raises(InitializationContractError, match="unsupported"):
        InitializationOrderGraph.from_dict(payload)
    node = graph.nodes[0]
    node_payload = node.to_dict()
    node_payload["interface"] = "InitializationGraphNode@0"
    with pytest.raises(InitializationContractError, match="unsupported"):
        InitializationGraphNode.from_dict(node_payload)


def test_absolute_paths_and_unknown_relations_are_rejected() -> None:
    with pytest.raises(InitializationContractError, match="repository-relative"):
        _node(module_path="/tmp/mod.py")
    with pytest.raises(InitializationContractError, match="POSIX"):
        _node(module_path="../outside.py")
    with pytest.raises(InitializationContractError, match="unsupported"):
        _edge("block:a", "block:b", kind="calls")


def test_empty_module_admits_without_hiding_the_observation_profile() -> None:
    graph = _analyze("")
    assert graph.nodes == ()
    assert graph.edges == ()
    assert graph.linearization == ()
    assert graph.cyclic is False
    assert graph.observation_profile_cid == DEFAULT_HERMETIC_PROFILE.profile_cid
    terminal = graph.evaluate()
    assert terminal.kind == InitializationTerminalKind.ADMITTED.value
    assert terminal.success is True
    assert terminal.authorizes_completion is False
    assert terminal.required is False


def test_candidates_are_content_addressed_and_cannot_name_missing_nodes() -> None:
    graph = _analyze("REGISTRY = {}\nREGISTRY['x'] = 1\n")
    candidate = graph.candidates[0]
    restored = InitializationCandidate.from_dict(candidate.to_dict())
    assert restored == candidate
    assert restored.candidate_cid == cid_for_structured(candidate.identity_payload())
    with pytest.raises(InitializationContractError, match="subject_ids"):
        InitializationOrderGraph(
            tree_id=TREE_ID,
            source_cid=_cid("source"),
            module_path=MODULE_FILE,
            module_name=MODULE_NAME,
            nodes=(_node(),),
            candidates=(
                InitializationCandidate(
                    candidate_id="candidate:missing",
                    kind=InitializationCandidateKind.PRESERVE_ORDER,
                    subject_ids=("block:missing",),
                    reason="subject must exist",
                ),
            ),
            observation_profile_cid=DEFAULT_HERMETIC_PROFILE.profile_cid,
        )


def test_provider_free_exports_omit_model_and_provider_names() -> None:
    exports = provider_free_exports()
    assert "InitializationOrderGraph" in exports
    assert "InitializationStateMachine" in exports
    lowered = {name.lower() for name in exports}
    assert "provider" not in lowered
    assert "model" not in lowered
    assert "openai" not in lowered


def test_protected_control_paths_were_not_nominated() -> None:
    for relative in PROTECTED_PATHS:
        assert (ROOT / relative).is_file()
    assert WRITE_SCOPE == (
        "ipfs_datasets_py/ipfs_datasets_py/semantic_refactoring/initialization.py",
        "ipfs_datasets_py/tests/unit/semantic_refactoring/test_initialization.py",
    )
