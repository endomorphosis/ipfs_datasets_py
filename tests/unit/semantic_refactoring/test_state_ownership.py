"""Independent contract tests for SPAR-009 StateOwnershipGraph@1."""

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
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (  # noqa: E402
    AnalysisConfidence,
)
from ipfs_datasets_py.semantic_refactoring.capsules import (  # noqa: E402
    EvidenceClass,
    StateOwnerKind,
    StateUniqueness,
)
from ipfs_datasets_py.semantic_refactoring.state_ownership import (  # noqa: E402
    ANALYZER_ID,
    AUTHORITY,
    AUTHORITY_OWNER,
    DUCKLAKE_IS_AUTHORITY,
    DUPLICATED_MUTABLE_STATE_REJECTED,
    FORBIDDEN_OBSERVATIONAL_FIELDS,
    GOAL_ID,
    MARKDOWN_IS_NOT_COMPLETION,
    MISSING_RELEASE_IS_NOT_GUESSED,
    MODEL_OUTPUT_IS_PROPOSAL_ONLY,
    STATE_CAN_AUTHORIZE_COMPLETION,
    STATE_CAN_AUTHORIZE_TRANSITION,
    STATE_CAN_CREATE_AUTHORITY,
    STATE_CID_CODEC,
    STATE_CID_PROFILE,
    STATE_CONTRACT_VERSION,
    STATE_EXTRACTION_CANDIDATE_INTERFACE,
    STATE_OWNERSHIP_GRAPH_INTERFACE,
    TASK_ID,
    TEST_PASS_IS_NOT_COMPLETION,
    UNKNOWN_UNIQUENESS_WIDENS_FRONTIER,
    VECTOR_SIMILARITY_IS_AUTHORITY,
    WORKER_SELF_APPROVAL,
    AliasSet,
    LifecycleKind,
    LifecycleRelation,
    OwnerCandidate,
    ReadWriteSummary,
    StateExtractionCandidate,
    StateOwnershipError,
    StateOwnershipGraph,
    SynchronizationKind,
    SynchronizationRelation,
    UnresolvedStateItem,
    UnresolvedStateReason,
    analyze_source,
    build_state_ownership_graph,
    decode_canonical_graph,
    encode_canonical_graph,
    provider_free_exports,
    state_cid_profile,
)


ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = (
    ROOT
    / "ipfs_datasets_py"
    / "ipfs_datasets_py"
    / "semantic_refactoring"
    / "state_ownership.py"
)
TEST_PATH = Path(__file__).resolve()
INVENTORY = (
    ROOT
    / "docs"
    / "architecture"
    / "semantic_preserving_autonomous_remodularization_inventory"
)
WRITE_SCOPE = (
    "ipfs_datasets_py/ipfs_datasets_py/semantic_refactoring/state_ownership.py",
    "ipfs_datasets_py/tests/unit/semantic_refactoring/test_state_ownership.py",
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


def _analyze(source: str, *, subject: str = "module:pkg.mod") -> StateOwnershipGraph:
    return analyze_source(source, tree_id=TREE_ID, subject_cid=_cid(subject))


def _alias(
    representative: str = "CACHE",
    members: tuple[str, ...] | None = None,
    **overrides: Any,
) -> AliasSet:
    fields: dict[str, Any] = {
        "representative_id": representative,
        "member_ids": members if members is not None else (representative,),
        "confidence": AnalysisConfidence.EXACT,
        "evidence_class": EvidenceClass.EXACT_STATIC_FACT,
        "unresolved": False,
    }
    fields.update(overrides)
    return AliasSet(**fields)


def _owner(
    owner_id: str = "owner:module_global:CACHE",
    *,
    alias_set_id: str = "alias:CACHE",
    **overrides: Any,
) -> OwnerCandidate:
    fields: dict[str, Any] = {
        "owner_id": owner_id,
        "owner_kind": StateOwnerKind.MODULE_GLOBAL,
        "uniqueness": StateUniqueness.UNIQUE,
        "owning_symbol_id": "CACHE",
        "alias_set_id": alias_set_id,
        "mutable": True,
        "confidence": AnalysisConfidence.EXACT,
        "evidence_class": EvidenceClass.EXACT_STATIC_FACT,
        "read_write_summary_id": "",
        "lineno": 1,
        "col_offset": 0,
    }
    fields.update(overrides)
    return OwnerCandidate(**fields)


def _summary(subject_id: str = "<module>", **overrides: Any) -> ReadWriteSummary:
    fields: dict[str, Any] = {
        "subject_id": subject_id,
        "reads": (),
        "writes": ("CACHE",),
        "may_reads": (),
        "may_writes": (),
        "confidence": AnalysisConfidence.EXACT,
        "evidence_class": EvidenceClass.EXACT_STATIC_FACT,
    }
    fields.update(overrides)
    return ReadWriteSummary(**fields)


def _graph(**overrides: Any) -> StateOwnershipGraph:
    fields: dict[str, Any] = {
        "tree_id": TREE_ID,
        "subject_cid": _cid("module:pkg.mod"),
        "source_cid": _cid("source:pkg.mod"),
        "analyzer_revision": _cid("analyzer-revision"),
        "environment_cid": _cid("environment"),
        "owners": (_owner(),),
        "alias_sets": (_alias(),),
        "read_write_summaries": (),
        "lifecycle_relations": (),
        "synchronization_relations": (),
        "extraction_candidates": (),
        "unresolved": (),
    }
    fields.update(overrides)
    return StateOwnershipGraph(**fields)


def test_owned_paths_and_task_identity_are_exact() -> None:
    assert TASK_ID == "SPAR-009"
    assert GOAL_ID == "SPAR-G022"
    assert STATE_OWNERSHIP_GRAPH_INTERFACE == "StateOwnershipGraph@1"
    assert STATE_EXTRACTION_CANDIDATE_INTERFACE == "StateExtractionCandidate@1"
    assert STATE_CONTRACT_VERSION == "1"
    assert MODULE_PATH.is_file()
    assert TEST_PATH.is_file()
    for relative in WRITE_SCOPE:
        assert (ROOT / relative).is_file()


def test_authority_flags_cannot_self_authorize() -> None:
    assert AUTHORITY == "formal semantic authority"
    assert AUTHORITY_OWNER == "ipfs_datasets_py"
    assert STATE_CAN_AUTHORIZE_COMPLETION is False
    assert STATE_CAN_AUTHORIZE_TRANSITION is False
    assert STATE_CAN_CREATE_AUTHORITY is False
    assert VECTOR_SIMILARITY_IS_AUTHORITY is False
    assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
    assert TEST_PASS_IS_NOT_COMPLETION is True
    assert MARKDOWN_IS_NOT_COMPLETION is True
    assert WORKER_SELF_APPROVAL is False
    assert DUCKLAKE_IS_AUTHORITY is False
    assert DUPLICATED_MUTABLE_STATE_REJECTED is True
    assert MISSING_RELEASE_IS_NOT_GUESSED is True
    assert UNKNOWN_UNIQUENESS_WIDENS_FRONTIER is True
    profile = state_cid_profile()
    assert profile["profile_id"] == PROFILE_ID == STATE_CID_PROFILE
    assert profile["codec"] == STRUCTURED_CODEC == STATE_CID_CODEC
    assert "not universal meaning" in profile["rule"]


def test_module_defines_predicted_symbols_not_capsule_family() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "StateOwnershipGraph" in names
    assert "StateExtractionCandidate" in names
    assert "OwnerCandidate" in names
    assert "AliasSet" in names
    assert "ReadWriteSummary" in names
    for capsule in CAPSULE_TYPES:
        assert capsule not in names


def test_immutable_constants_are_not_mutable_owners() -> None:
    graph = _analyze("VERSION = 1\nNAME = 'cache'\nOK = True\n")
    assert graph.owners == ()
    assert graph.unique_owners() == ()
    assert graph.admitted_candidates() == ()


def test_module_global_mutable_is_unique_owner() -> None:
    graph = _analyze("CACHE = {}\n")
    assert len(graph.unique_owners()) == 1
    owner = graph.unique_owners()[0]
    assert owner.owner_kind == StateOwnerKind.MODULE_GLOBAL.value
    assert owner.uniqueness == StateUniqueness.UNIQUE.value
    assert owner.owning_symbol_id == "CACHE"
    assert owner.mutable is True
    assert owner.confidence == AnalysisConfidence.EXACT.value
    alias = graph.alias_sets[0]
    assert alias.member_ids == ("CACHE",)
    admitted = graph.admitted_candidates()
    assert len(admitted) == 1
    assert admitted[0].owner_id == owner.owner_id
    assert admitted[0].complete_obligations is True
    assert admitted[0].can_authorize_completion is False
    assert admitted[0].can_authorize_transition is False


def test_alias_assignment_merges_one_unique_owner() -> None:
    graph = _analyze("CACHE = {}\nSTORE = CACHE\n")
    assert len(graph.unique_owners()) == 1
    alias = graph.alias_sets[0]
    assert set(alias.member_ids) == {"CACHE", "STORE"}
    assert alias.representative_id == "CACHE"
    assert graph.admitted_candidates()[0].admitted is True


def test_chained_mutable_assignment_is_one_alias_set() -> None:
    graph = _analyze("LEFT = RIGHT = []\n")
    assert len(graph.unique_owners()) == 1
    assert set(graph.alias_sets[0].member_ids) == {"LEFT", "RIGHT"}


def test_independent_mutables_are_distinct_unique_owners() -> None:
    graph = _analyze("CACHE = {}\nOTHER = {}\n")
    assert len(graph.unique_owners()) == 2
    symbols = {owner.owning_symbol_id for owner in graph.unique_owners()}
    assert symbols == {"CACHE", "OTHER"}


def test_rebinding_two_unique_owners_together_is_duplicated_mutable_state() -> None:
    with pytest.raises(StateOwnershipError, match="duplicated mutable state"):
        _analyze("CACHE = {}\nOTHER = {}\nOTHER = CACHE\n")


def test_constructed_overlapping_unique_owners_are_rejected() -> None:
    alias = _alias("CACHE", ("CACHE", "OTHER"))
    left = _owner("owner:module_global:CACHE", alias_set_id=alias.alias_set_id)
    right = _owner(
        "owner:module_global:OTHER",
        alias_set_id=alias.alias_set_id,
        owning_symbol_id="OTHER",
    )
    with pytest.raises(StateOwnershipError, match="duplicated mutable state"):
        _graph(owners=(left, right), alias_sets=(alias,))


def test_instance_attribute_is_shared_and_not_admitted() -> None:
    graph = _analyze(
        "class Holder:\n"
        "    def __init__(self) -> None:\n"
        "        self.items = []\n"
    )
    assert graph.unique_owners() == ()
    owner = graph.owners[0]
    assert owner.owner_kind == StateOwnerKind.INSTANCE_ATTRIBUTE.value
    assert owner.uniqueness == StateUniqueness.SHARED.value
    assert owner.owning_symbol_id == "Holder.items"
    assert graph.admitted_candidates() == ()
    candidate = graph.extraction_candidates[0]
    assert candidate.admitted is False
    assert candidate.uniqueness == StateUniqueness.SHARED.value


def test_class_attribute_is_unique() -> None:
    graph = _analyze("class Registry:\n    items = {}\n")
    owner = graph.unique_owners()[0]
    assert owner.owner_kind == StateOwnerKind.CLASS_ATTRIBUTE.value
    assert owner.owning_symbol_id == "Registry.items"
    assert graph.admitted_candidates()[0].admitted is True


def test_contextvar_and_thread_local_are_typed_owners() -> None:
    graph = _analyze(
        "from contextvars import ContextVar\n"
        "import threading\n"
        "CURRENT = ContextVar('current')\n"
        "TLS = threading.local()\n"
    )
    kinds = {owner.owner_kind for owner in graph.unique_owners()}
    symbols = {owner.owning_symbol_id for owner in graph.unique_owners()}
    assert StateOwnerKind.CONTEXTVAR.value in kinds
    assert StateOwnerKind.THREAD_LOCAL.value in kinds
    assert {"CURRENT", "TLS"} <= symbols


def test_lock_with_statement_records_lifecycle_and_synchronization() -> None:
    graph = _analyze(
        "import threading\n"
        "LOCK = threading.Lock()\n"
        "def critical() -> int:\n"
        "    with LOCK:\n"
        "        return 1\n"
    )
    owner = next(
        item
        for item in graph.unique_owners()
        if item.owning_symbol_id == "LOCK"
    )
    assert owner.owner_kind == StateOwnerKind.RESOURCE.value
    kinds = {item.kind for item in graph.lifecycle_relations if item.owner_id == owner.owner_id}
    assert LifecycleKind.INITIALIZE.value in kinds
    assert LifecycleKind.ACQUIRE.value in kinds
    assert LifecycleKind.RELEASE.value in kinds
    assert not any(
        item.missing_counterpart
        for item in graph.lifecycle_relations
        if item.owner_id == owner.owner_id
        and item.kind == LifecycleKind.RELEASE.value
    )
    sync = [
        item
        for item in graph.synchronization_relations
        if item.owner_id == owner.owner_id
    ]
    assert sync
    assert sync[0].kind == SynchronizationKind.LOCK.value
    admitted = next(
        item for item in graph.admitted_candidates() if item.owner_id == owner.owner_id
    )
    assert admitted.complete_obligations is True


def test_missing_release_is_recorded_and_blocks_admission() -> None:
    graph = _analyze(
        "import threading\n"
        "LOCK = threading.Lock()\n"
        "def bad() -> None:\n"
        "    LOCK.acquire()\n"
    )
    owner = next(item for item in graph.owners if item.owning_symbol_id == "LOCK")
    missing = [
        item
        for item in graph.lifecycle_relations
        if item.owner_id == owner.owner_id
        and item.kind == LifecycleKind.RELEASE.value
        and item.missing_counterpart
    ]
    assert missing
    assert missing[0].confidence != AnalysisConfidence.EXACT.value
    candidate = next(
        item
        for item in graph.extraction_candidates
        if item.owner_id == owner.owner_id
    )
    assert candidate.complete_obligations is False
    assert candidate.admitted is False


def test_read_write_summaries_separate_exact_and_may_facts() -> None:
    graph = _analyze(
        "CACHE = {}\n"
        "def put(key, value):\n"
        "    CACHE[key] = value\n"
        "def get(key):\n"
        "    return CACHE[key]\n"
        "def load(name):\n"
        "    return getattr(CACHE, name)\n"
    )
    module = next(item for item in graph.read_write_summaries if item.subject_id == "<module>")
    assert "CACHE" in module.writes
    put = next(item for item in graph.read_write_summaries if item.subject_id == "put")
    assert "CACHE" in put.writes
    get = next(item for item in graph.read_write_summaries if item.subject_id == "get")
    assert "CACHE" in get.reads
    load = next(item for item in graph.read_write_summaries if item.subject_id == "load")
    assert "CACHE" in load.may_reads or "CACHE" in load.reads
    assert load.confidence == AnalysisConfidence.CONSERVATIVE.value
    assert load.evidence_class == EvidenceClass.CONSERVATIVE_MAY_FACT.value
    with pytest.raises(StateOwnershipError, match="may_reads must not repeat"):
        ReadWriteSummary(
            subject_id="dup",
            reads=("CACHE",),
            may_reads=("CACHE",),
        )


def test_dynamic_access_and_unknown_uniqueness_are_explicit() -> None:
    graph = _analyze(
        "CACHE = mystery()\n"
        "def load(name):\n"
        "    return getattr(CACHE, name)\n"
    )
    unknown = [
        owner
        for owner in graph.owners
        if owner.uniqueness == StateUniqueness.UNKNOWN.value
    ]
    assert unknown
    frontier_subjects = {item.subject_id for item in graph.unresolved}
    assert unknown[0].owner_id in frontier_subjects
    assert any(
        item.reason == UnresolvedStateReason.DYNAMIC_ACCESS.value
        for item in graph.unresolved
    )
    assert graph.admitted_candidates() == ()


def test_closure_cell_is_shared() -> None:
    graph = _analyze(
        "def outer():\n"
        "    cell = []\n"
        "    def inner():\n"
        "        nonlocal cell\n"
        "        cell.append(1)\n"
        "    return inner\n"
    )
    owner = next(item for item in graph.owners if "cell" in item.owning_symbol_id)
    assert owner.owner_kind == StateOwnerKind.CLOSURE_CELL.value
    assert owner.uniqueness == StateUniqueness.SHARED.value
    assert graph.admitted_candidates() == ()


def test_model_and_vector_evidence_cannot_prove_unique_ownership() -> None:
    with pytest.raises(StateOwnershipError, match="cannot prove unique ownership"):
        _owner(
            confidence=AnalysisConfidence.HEURISTIC,
            evidence_class=EvidenceClass.MODEL_HYPOTHESIS,
        )
    with pytest.raises(StateOwnershipError, match="cannot prove unique ownership"):
        _owner(
            confidence=AnalysisConfidence.HEURISTIC,
            evidence_class=EvidenceClass.VECTOR_CANDIDATE,
        )
    with pytest.raises(StateOwnershipError, match="cannot prove unique ownership"):
        _owner(
            uniqueness=StateUniqueness.UNIQUE,
            confidence=AnalysisConfidence.HEURISTIC,
            evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT,
        )


def test_runtime_observation_cannot_be_exact() -> None:
    with pytest.raises(StateOwnershipError, match="runtime observation"):
        ReadWriteSummary(
            subject_id="obs",
            writes=("CACHE",),
            confidence=AnalysisConfidence.EXACT,
            evidence_class=EvidenceClass.RUNTIME_OBSERVATION,
        )


def test_unknown_owner_kind_cannot_be_unique_or_exact() -> None:
    with pytest.raises(StateOwnershipError, match="unknown owner_kind"):
        _owner(owner_kind=StateOwnerKind.UNKNOWN)
    with pytest.raises(StateOwnershipError, match="unknown uniqueness"):
        _owner(
            uniqueness=StateUniqueness.UNKNOWN,
            confidence=AnalysisConfidence.EXACT,
            evidence_class=EvidenceClass.EXACT_STATIC_FACT,
        )


def test_admitted_candidate_requires_unique_complete_obligations() -> None:
    with pytest.raises(StateOwnershipError, match="unique ownership"):
        StateExtractionCandidate(
            owner_id="owner:module_global:CACHE",
            uniqueness=StateUniqueness.SHARED,
            alias_set_id="alias:CACHE",
            complete_obligations=True,
            admitted=True,
        )
    with pytest.raises(StateOwnershipError, match="complete obligations"):
        StateExtractionCandidate(
            owner_id="owner:module_global:CACHE",
            uniqueness=StateUniqueness.UNIQUE,
            alias_set_id="alias:CACHE",
            complete_obligations=False,
            admitted=True,
        )
    candidate = StateExtractionCandidate(
        owner_id="owner:module_global:CACHE",
        uniqueness=StateUniqueness.UNIQUE,
        alias_set_id="alias:CACHE",
        complete_obligations=True,
        admitted=True,
    )
    payload = candidate.to_dict()
    payload["can_authorize_completion"] = True
    with pytest.raises(StateOwnershipError, match="cannot authorize completion"):
        StateExtractionCandidate.from_dict(payload)


def test_unknown_uniqueness_cannot_be_hidden() -> None:
    owner = _owner(
        uniqueness=StateUniqueness.UNKNOWN,
        confidence=AnalysisConfidence.CONSERVATIVE,
        evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT,
    )
    with pytest.raises(StateOwnershipError, match="explicit frontier"):
        _graph(owners=(owner,), alias_sets=(_alias(),), unresolved=())
    graph = _graph(
        owners=(owner,),
        alias_sets=(_alias(),),
        unresolved=(
            UnresolvedStateItem(
                subject_id=owner.owner_id,
                reason=UnresolvedStateReason.UNKNOWN_UNIQUENESS,
                unresolved_fields=("uniqueness",),
            ),
        ),
    )
    assert graph.unresolved[0].subject_id == owner.owner_id


def test_observational_fields_are_excluded_from_identity() -> None:
    owner = _owner()
    payload = owner.to_dict()
    payload["timestamp"] = "now"
    with pytest.raises(StateOwnershipError, match="observational"):
        OwnerCandidate.from_dict(payload)
    for name in ("timestamp", "local_path", "model_output", "prompt"):
        assert name in FORBIDDEN_OBSERVATIONAL_FIELDS


def test_records_round_trip_and_cids_reverify() -> None:
    graph = _analyze("CACHE = {}\nSTORE = CACHE\n")
    cloned = StateOwnershipGraph.from_dict(graph.to_dict())
    assert cloned.graph_cid == graph.graph_cid
    assert cloned.graph_cid == cid_for_structured(graph.identity_payload())
    encoded = encode_canonical_graph(graph)
    assert encoded == graph.canonical_bytes()
    assert decode_canonical_graph(encoded).graph_cid == graph.graph_cid
    mutated = graph.to_dict()
    mutated["graph_cid"] = _cid("not-the-graph")
    with pytest.raises(StateOwnershipError, match="does not verify"):
        StateOwnershipGraph.from_dict(mutated)
    rebuilt = build_state_ownership_graph(
        tree_id=graph.tree_id,
        subject_cid=graph.subject_cid,
        source_cid=graph.source_cid,
        analyzer_revision=graph.analyzer_revision,
        environment_cid=graph.environment_cid,
        owners=graph.owners,
        alias_sets=graph.alias_sets,
        read_write_summaries=graph.read_write_summaries,
        lifecycle_relations=graph.lifecycle_relations,
        synchronization_relations=graph.synchronization_relations,
        extraction_candidates=graph.extraction_candidates,
        unresolved=graph.unresolved,
    )
    assert rebuilt.graph_cid == graph.graph_cid


def test_duplicate_owners_and_missing_alias_sets_are_rejected() -> None:
    with pytest.raises(StateOwnershipError, match="duplicate owner_id"):
        _graph(owners=(_owner(), _owner()))
    with pytest.raises(StateOwnershipError, match="alias set that is not present"):
        _graph(alias_sets=())
    with pytest.raises(StateOwnershipError, match="not present"):
        _graph(
            lifecycle_relations=(
                LifecycleRelation(
                    relation_id="lifecycle:initialize:missing",
                    kind=LifecycleKind.INITIALIZE,
                    owner_id="owner:missing",
                    site_id="module:1",
                ),
            )
        )


def test_unparseable_source_is_a_typed_terminal() -> None:
    with pytest.raises(StateOwnershipError, match="parseable Python"):
        _analyze("def broken(\n")


def test_duplicate_analysis_is_deterministic() -> None:
    source = "CACHE = {}\nSTORE = CACHE\n"
    first = _analyze(source)
    second = _analyze(source)
    assert first.graph_cid == second.graph_cid
    assert encode_canonical_graph(first) == encode_canonical_graph(second)
    assert canonical_dag_json_bytes(
        json.loads(first.canonical_bytes().decode("utf-8"))
    ) == first.canonical_bytes()


def test_records_are_frozen() -> None:
    graph = _analyze("CACHE = {}\n")
    with pytest.raises(Exception):
        graph.tree_id = "0" * 40  # type: ignore[misc]
    with pytest.raises(Exception):
        graph.owners[0].mutable = False  # type: ignore[misc]


def test_provider_free_exports_and_no_provider_imports() -> None:
    exports = provider_free_exports()
    assert exports == tuple(sorted(exports))
    forbidden_export_names = {
        "openai",
        "anthropic",
        "torch",
        "transformers",
        "model_output",
        "SemanticCapsuleCompiler",
        "compile_semantic_capsule",
        "StateOwnerCapsule",
    }
    assert forbidden_export_names.isdisjoint(set(exports))
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "openai" not in imported
    assert "anthropic" not in imported
    assert "transformers" not in imported
    assert "torch" not in imported
    text = MODULE_PATH.read_text(encoding="utf-8")
    for capsule_type in CAPSULE_TYPES:
        assert f"class {capsule_type}" not in text
    assert "does not replace" in text
    assert "StateOwnershipGraph" in exports
    assert "StateExtractionCandidate" in exports
    assert "analyze_source" in exports
    assert ANALYZER_ID.endswith("state_ownership@1")


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
    import ipfs_datasets_py.semantic_refactoring.state_ownership as state_ownership

    assert state_ownership.StateOwnershipGraph is StateOwnershipGraph
    assert state_ownership.__all__
    assert "llm" not in {name.lower() for name in state_ownership.__all__}
    assert "openai" not in state_ownership.__all__
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert "ipfs_kit_py" not in imported
    assert "ipfs_accelerate_py" not in imported
