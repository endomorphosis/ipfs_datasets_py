"""Independent contract tests for SPAR-016 ModuleBoundaryContract@1."""

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
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.semantic_refactoring.capsules import (  # noqa: E402
    EvidenceClass,
    ResourceKind,
    StateOwnerKind,
    StateUniqueness,
)
from ipfs_datasets_py.semantic_refactoring.compatibility import (  # noqa: E402
    ImportEagerness,
    SerializationFormat,
)
from ipfs_datasets_py.semantic_refactoring.boundary_contracts import (  # noqa: E402
    ANALYZER_ID,
    AUTHORITY,
    AUTHORITY_OWNER,
    BOUNDARY_CAN_AUTHORIZE_COMPLETION,
    BOUNDARY_CAN_AUTHORIZE_TRANSITION,
    BOUNDARY_CAN_CREATE_AUTHORITY,
    DECLARED_CLAUSE_KINDS,
    DECLARED_CLAUSE_POLARITIES,
    DECLARED_CUT_EDGE_KINDS,
    DECLARED_DISPOSITIONS,
    DECLARED_EFFECT_POLARITIES,
    DUCKLAKE_IS_AUTHORITY,
    GOAL_ID,
    GUESSED_AXIOMS_REJECTED,
    GUESSED_AXIOM_DISPOSITIONS,
    IDENTITY_EXCLUDED_FIELDS,
    INCOMPLETE_CONTRACTS_ARE_NOT_GUESSED,
    INCOMPLETE_DISPOSITIONS,
    MARKDOWN_IS_NOT_COMPLETION,
    MODEL_OUTPUT_IS_PROPOSAL_ONLY,
    MODULE_BOUNDARY_CONTRACT_INTERFACE,
    MODULE_BOUNDARY_CONTRACT_SCHEMA,
    REQUIRED_CONTRACT_DIMENSIONS,
    TASK_ID,
    TEST_PASS_IS_NOT_COMPLETION,
    UNIQUE_OWNER_REQUIRES_EXACT_EVIDENCE,
    VECTOR_SIMILARITY_IS_AUTHORITY,
    WORKER_SELF_APPROVAL,
    AssumeGuaranteeClause,
    AtomicityKind,
    AuthorizationBinding,
    AuthorizationKind,
    BoundaryContractError,
    BoundaryContractSet,
    BoundaryTerminal,
    BoundaryTerminalKind,
    ClauseKind,
    ClausePolarity,
    ConcurrencyBinding,
    ConcurrencyKind,
    ContractDisposition,
    CutEdge,
    CutEdgeKind,
    EffectClass,
    EffectObligation,
    EffectPolarity,
    ExceptionObligation,
    InitializationBinding,
    ModuleBoundaryContract,
    ProofObligation,
    ProofObligationKind,
    SerializationBinding,
    StateResourceOwnerBinding,
    VersioningBinding,
    VersioningKind,
    provider_free_exports,
    synthesize_boundary_contract,
    synthesize_boundary_contracts,
)


ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = (
    ROOT
    / "ipfs_datasets_py"
    / "ipfs_datasets_py"
    / "semantic_refactoring"
    / "boundary_contracts.py"
)
TEST_PATH = Path(__file__).resolve()
INVENTORY = (
    ROOT
    / "docs"
    / "architecture"
    / "semantic_preserving_autonomous_remodularization_inventory"
)
WRITE_SCOPE = (
    "ipfs_datasets_py/ipfs_datasets_py/semantic_refactoring/boundary_contracts.py",
    "ipfs_datasets_py/tests/unit/semantic_refactoring/test_boundary_contracts.py",
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


def _edge(**overrides: Any) -> CutEdge:
    fields: dict[str, Any] = {
        "edge_id": "edge:pkg.mod.Record:pkg.cli",
        "producer_module": "pkg.mod",
        "consumer_module": "pkg.cli",
        "producer_symbol": "pkg.mod.Record",
        "consumer_symbol": "pkg.cli.build",
        "kind": CutEdgeKind.CALL,
    }
    fields.update(overrides)
    return CutEdge(**fields)


def _clause(
    polarity: ClausePolarity = ClausePolarity.GUARANTEE,
    kind: ClauseKind = ClauseKind.OUTPUT,
    **overrides: Any,
) -> AssumeGuaranteeClause:
    fields: dict[str, Any] = {
        "clause_id": f"clause:{polarity.value}:{kind.value}",
        "polarity": polarity,
        "kind": kind,
        "predicate_id": f"pred:{polarity.value}:{kind.value}",
    }
    fields.update(overrides)
    return AssumeGuaranteeClause(**fields)


def _complete_clauses() -> tuple[AssumeGuaranteeClause, ...]:
    clauses: list[AssumeGuaranteeClause] = []
    for polarity in ClausePolarity:
        for kind in ClauseKind:
            clauses.append(_clause(polarity, kind))
    return tuple(clauses)


def _effect(
    polarity: EffectPolarity = EffectPolarity.ALLOWED,
    effect_class: EffectClass = EffectClass.PURE,
    **overrides: Any,
) -> EffectObligation:
    fields: dict[str, Any] = {
        "effect_id": f"effect:{polarity.value}:{effect_class.value}",
        "polarity": polarity,
        "effect_class": effect_class,
    }
    fields.update(overrides)
    return EffectObligation(**fields)


def _exception(**overrides: Any) -> ExceptionObligation:
    fields: dict[str, Any] = {
        "exception_id": "exc:ValueError",
        "exception_type": "ValueError",
        "guaranteed": True,
    }
    fields.update(overrides)
    return ExceptionObligation(**fields)


def _owner(**overrides: Any) -> StateResourceOwnerBinding:
    fields: dict[str, Any] = {
        "owner_id": "owner:pkg.mod.CACHE",
        "owner_kind": StateOwnerKind.MODULE_GLOBAL,
        "uniqueness": StateUniqueness.UNIQUE,
        "resource_kind": ResourceKind.UNKNOWN,
    }
    fields.update(overrides)
    return StateResourceOwnerBinding(**fields)


def _init(**overrides: Any) -> InitializationBinding:
    fields: dict[str, Any] = {
        "initialization_id": "init:pkg.mod",
        "order_index": 0,
        "eagerness": ImportEagerness.EAGER,
    }
    fields.update(overrides)
    return InitializationBinding(**fields)


def _concurrency(**overrides: Any) -> ConcurrencyBinding:
    fields: dict[str, Any] = {
        "concurrency_id": "conc:pkg.mod.Record",
        "concurrency_kind": ConcurrencyKind.SEQUENTIAL,
        "atomicity": AtomicityKind.ATOMIC,
    }
    fields.update(overrides)
    return ConcurrencyBinding(**fields)


def _authorization(**overrides: Any) -> AuthorizationBinding:
    fields: dict[str, Any] = {
        "authorization_id": "auth:pkg.mod.Record",
        "authorization_kind": AuthorizationKind.PUBLIC,
    }
    fields.update(overrides)
    return AuthorizationBinding(**fields)


def _serialization(**overrides: Any) -> SerializationBinding:
    fields: dict[str, Any] = {
        "serialization_id": "ser:pkg.mod.Record",
        "format": SerializationFormat.DAG_JSON,
    }
    fields.update(overrides)
    return SerializationBinding(**fields)


def _versioning(**overrides: Any) -> VersioningBinding:
    fields: dict[str, Any] = {
        "versioning_id": "ver:pkg.mod.Record",
        "version": "1",
        "kind": VersioningKind.STABLE,
    }
    fields.update(overrides)
    return VersioningBinding(**fields)


def _proof(**overrides: Any) -> ProofObligation:
    fields: dict[str, Any] = {
        "obligation_id": "proof:pkg.mod.Record",
        "kind": ProofObligationKind.EXACT_STATIC,
        "claim_id": "claim:boundary:pkg.mod.Record",
    }
    fields.update(overrides)
    return ProofObligation(**fields)


def _complete_contract(**overrides: Any) -> ModuleBoundaryContract:
    fields: dict[str, Any] = {
        "cut_edge": _edge(),
        "clauses": _complete_clauses(),
        "effects": (
            _effect(EffectPolarity.ALLOWED, EffectClass.PURE),
            _effect(EffectPolarity.FORBIDDEN, EffectClass.NETWORK),
        ),
        "exceptions": (_exception(),),
        "state_resource_owner": _owner(),
        "initialization": _init(),
        "concurrency": _concurrency(),
        "authorization": _authorization(),
        "serialization": _serialization(),
        "versioning": _versioning(),
        "proof_obligations": (_proof(),),
    }
    fields.update(overrides)
    return ModuleBoundaryContract(**fields)


def _set(
    contracts: tuple[ModuleBoundaryContract, ...] | None = None,
    **overrides: Any,
) -> BoundaryContractSet:
    if contracts is None:
        contracts = (_complete_contract(),)
    fields: dict[str, Any] = {
        "tree_id": TREE_ID,
        "source_cid": _cid("source"),
        "partition_cid": _cid("partition"),
        "contracts": contracts,
    }
    fields.update(overrides)
    return BoundaryContractSet(**fields)


def test_owned_paths_and_task_identity_are_exact() -> None:
    assert TASK_ID == "SPAR-016"
    assert GOAL_ID == "SPAR-G033"
    assert MODULE_BOUNDARY_CONTRACT_INTERFACE == "ModuleBoundaryContract@1"
    assert MODULE_BOUNDARY_CONTRACT_SCHEMA.endswith("@1")
    assert MODULE_PATH.is_file()
    assert TEST_PATH.is_file()
    for relative in WRITE_SCOPE:
        assert (ROOT / relative).is_file()


def test_authority_flags_cannot_self_authorize() -> None:
    assert AUTHORITY == "formal semantic authority"
    assert AUTHORITY_OWNER == "ipfs_datasets_py"
    assert BOUNDARY_CAN_AUTHORIZE_COMPLETION is False
    assert BOUNDARY_CAN_AUTHORIZE_TRANSITION is False
    assert BOUNDARY_CAN_CREATE_AUTHORITY is False
    assert VECTOR_SIMILARITY_IS_AUTHORITY is False
    assert MODEL_OUTPUT_IS_PROPOSAL_ONLY is True
    assert TEST_PASS_IS_NOT_COMPLETION is True
    assert MARKDOWN_IS_NOT_COMPLETION is True
    assert WORKER_SELF_APPROVAL is False
    assert DUCKLAKE_IS_AUTHORITY is False
    assert GUESSED_AXIOMS_REJECTED is True
    assert INCOMPLETE_CONTRACTS_ARE_NOT_GUESSED is True
    assert UNIQUE_OWNER_REQUIRES_EXACT_EVIDENCE is True
    assert GUESSED_AXIOM_DISPOSITIONS == frozenset()


def test_closed_vocabularies_cover_plan_dimensions() -> None:
    assert set(REQUIRED_CONTRACT_DIMENSIONS) == {
        "assumptions",
        "guarantees",
        "inputs",
        "outputs",
        "conditions",
        "invariants",
        "exceptions",
        "allowed_effects",
        "forbidden_effects",
        "state_resource_owner",
        "initialization",
        "concurrency",
        "authorization",
        "serialization",
        "versioning",
        "proof_obligations",
    }
    assert DECLARED_CUT_EDGE_KINDS == {kind.value for kind in CutEdgeKind}
    assert DECLARED_CLAUSE_POLARITIES == {kind.value for kind in ClausePolarity}
    assert DECLARED_CLAUSE_KINDS == {kind.value for kind in ClauseKind}
    assert DECLARED_EFFECT_POLARITIES == {kind.value for kind in EffectPolarity}
    assert DECLARED_DISPOSITIONS == {kind.value for kind in ContractDisposition}
    assert INCOMPLETE_DISPOSITIONS == {
        "retrieval",
        "proof",
        "abstention",
        "review",
    }
    assert "guessed" not in DECLARED_DISPOSITIONS
    assert "axiom" not in DECLARED_DISPOSITIONS


def test_module_defines_predicted_symbols_not_capsule_family() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "ModuleBoundaryContract" in names
    assert "BoundaryContractSet" in names
    assert "CutEdge" in names
    assert "AssumeGuaranteeClause" in names
    assert "EffectObligation" in names
    assert "ExceptionObligation" in names
    assert "StateResourceOwnerBinding" in names
    assert "InitializationBinding" in names
    assert "ConcurrencyBinding" in names
    assert "AuthorizationBinding" in names
    assert "SerializationBinding" in names
    assert "VersioningBinding" in names
    assert "ProofObligation" in names
    assert "BoundaryTerminal" in names
    for capsule in CAPSULE_TYPES:
        assert capsule not in names
    assert "InitializationBlock" not in names
    assert "PublicCompatibilityObligation" not in names
    assert "StateOwnershipGraph" not in names


def test_complete_contract_covers_every_required_dimension() -> None:
    contract = _complete_contract()
    assert contract.complete is True
    assert contract.missing_dimensions == ()
    assert set(REQUIRED_CONTRACT_DIMENSIONS).isdisjoint(contract.missing_dimensions)
    assert contract.assumptions
    assert contract.guarantees
    assert {item.kind for item in contract.clauses} == set(DECLARED_CLAUSE_KINDS)
    assert contract.allowed_effects
    assert contract.forbidden_effects
    assert contract.exceptions
    assert contract.state_resource_owner is not None
    assert contract.initialization is not None
    assert contract.concurrency is not None
    assert contract.authorization is not None
    assert contract.serialization is not None
    assert contract.versioning is not None
    assert contract.proof_obligations
    terminal = contract.evaluate()
    assert terminal.kind == BoundaryTerminalKind.ADMITTED.value
    assert terminal.success is True
    assert terminal.authorizes_completion is False
    assert contract.authorizes_completion is False
    assert contract.authorizes_transition is False
    assert contract.disposition == ContractDisposition.ADMITTED.value


def test_complete_contract_round_trips_and_cid_reverifies() -> None:
    contract = _complete_contract()
    restored = ModuleBoundaryContract.from_dict(contract.to_dict())
    assert restored == contract
    assert restored.contract_cid == contract.contract_cid
    assert restored.contract_cid == cid_for_structured(contract.identity_payload())
    via_json = ModuleBoundaryContract.from_dict(
        json.loads(json.dumps(contract.to_dict()))
    )
    assert via_json.to_dict() == contract.to_dict()


def test_synthesis_from_cut_edge_alone_does_not_guess_axioms() -> None:
    edge = _edge()
    contract = synthesize_boundary_contract(edge)
    assert contract.complete is False
    assert contract.missing_dimensions == REQUIRED_CONTRACT_DIMENSIONS
    assert contract.disposition == ContractDisposition.RETRIEVAL.value
    terminal = contract.evaluate()
    assert terminal.success is False
    assert terminal.authorizes_completion is False
    assert terminal.kind == BoundaryTerminalKind.INCOMPLETE_CONTRACT.value
    assert "retrieval" in terminal.reason
    assert terminal.disposition == ContractDisposition.RETRIEVAL.value


def test_incomplete_authoritative_contract_dispositions_are_typed() -> None:
    proof = _complete_contract(
        proof_obligations=(
            _proof(
                kind=ProofObligationKind.COUNTERMODEL,
                evidence_class=EvidenceClass.PROOF_CANDIDATE,
            ),
        ),
        clauses=(),
    )
    assert proof.disposition == ContractDisposition.PROOF.value
    assert proof.evaluate().success is False

    review = _complete_contract(
        clauses=(),
        authorization=_authorization(
            evidence_class=EvidenceClass.HUMAN_POLICY_DECISION
        ),
    )
    assert review.disposition == ContractDisposition.REVIEW.value

    abstain = _complete_contract(
        clauses=(),
        concurrency=_concurrency(
            evidence_class=EvidenceClass.UNKNOWN,
            concurrency_kind=ConcurrencyKind.RACE_UNKNOWN,
            atomicity=AtomicityKind.UNKNOWN,
        ),
    )
    assert abstain.disposition == ContractDisposition.ABSTENTION.value
    assert abstain.evaluate().kind == BoundaryTerminalKind.UNKNOWN_REQUIRED.value


def test_model_and_vector_evidence_cannot_complete_required_clauses() -> None:
    with pytest.raises(BoundaryContractError, match="model or vector"):
        _clause(evidence_class=EvidenceClass.MODEL_HYPOTHESIS)
    with pytest.raises(BoundaryContractError, match="model or vector"):
        _effect(evidence_class=EvidenceClass.VECTOR_CANDIDATE)
    with pytest.raises(BoundaryContractError, match="model or vector"):
        _owner(evidence_class=EvidenceClass.MODEL_HYPOTHESIS)
    with pytest.raises(BoundaryContractError, match="model or vector"):
        _proof(evidence_class=EvidenceClass.VECTOR_CANDIDATE)
    with pytest.raises(BoundaryContractError, match="model or vector"):
        _edge(evidence_class=EvidenceClass.MODEL_HYPOTHESIS)


def test_unique_owner_requires_exact_static_fact() -> None:
    with pytest.raises(BoundaryContractError, match="exact_static_fact"):
        _owner(evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT)
    with pytest.raises(BoundaryContractError, match="exact_static_fact"):
        _owner(evidence_class=EvidenceClass.RUNTIME_OBSERVATION)
    with pytest.raises(BoundaryContractError, match="unknown owner kind"):
        _owner(owner_kind=StateOwnerKind.UNKNOWN)


def test_self_cut_edge_and_race_unknown_atomicity_fail_closed() -> None:
    with pytest.raises(BoundaryContractError, match="must differ"):
        _edge(producer_module="pkg.mod", consumer_module="pkg.mod")
    with pytest.raises(BoundaryContractError, match="atomicity"):
        _concurrency(
            concurrency_kind=ConcurrencyKind.RACE_UNKNOWN,
            atomicity=AtomicityKind.ATOMIC,
        )


def test_conflicting_predicates_and_duplicate_ids_fail_closed() -> None:
    first = _clause(ClausePolarity.GUARANTEE, ClauseKind.OUTPUT)
    conflict = _clause(
        ClausePolarity.GUARANTEE,
        ClauseKind.OUTPUT,
        clause_id="clause:other",
        predicate_id="pred:other",
    )
    others = tuple(
        item
        for item in _complete_clauses()
        if not (
            item.polarity == ClausePolarity.GUARANTEE.value
            and item.kind == ClauseKind.OUTPUT.value
        )
    )
    with pytest.raises(BoundaryContractError, match="conflicting"):
        _complete_contract(clauses=(first, conflict, *others))
    with pytest.raises(BoundaryContractError, match="unique"):
        _complete_contract(clauses=(first, first))
    with pytest.raises(BoundaryContractError, match="unique"):
        _set((_complete_contract(), _complete_contract()))


def test_every_cut_edge_in_a_set_has_a_disposition() -> None:
    second_edge = _edge(
        edge_id="edge:pkg.mod.Record:pkg.api",
        consumer_module="pkg.api",
        consumer_symbol="pkg.api.load",
    )
    complete = _complete_contract()
    incomplete = synthesize_boundary_contract(second_edge)
    contract_set = _set((complete, incomplete))
    assert set(contract_set.edge_ids) == {
        complete.cut_edge.edge_id,
        incomplete.cut_edge.edge_id,
    }
    assert contract_set.complete is False
    assert ContractDisposition.ADMITTED.value in contract_set.dispositions
    assert ContractDisposition.RETRIEVAL.value in contract_set.dispositions
    assert contract_set.contract_for_edge(complete.cut_edge.edge_id).complete
    terminal = contract_set.evaluate()
    assert terminal.success is False
    assert terminal.authorizes_completion is False
    assert terminal.kind == BoundaryTerminalKind.INCOMPLETE_CONTRACT.value


def test_complete_set_covers_declared_edges_and_round_trips() -> None:
    second = _complete_contract(
        cut_edge=_edge(
            edge_id="edge:pkg.mod.Record:pkg.api",
            consumer_module="pkg.api",
            consumer_symbol="pkg.api.load",
        ),
        state_resource_owner=_owner(owner_id="owner:pkg.mod.CACHE"),
    )
    contract_set = synthesize_boundary_contracts(
        (second.cut_edge, _edge()),
        tree_id=TREE_ID,
        source_cid=_cid("source"),
        partition_cid=_cid("partition"),
        contracts=(_complete_contract(), second),
    )
    assert contract_set.complete is True
    assert set(contract_set.covered_dimensions) == set(REQUIRED_CONTRACT_DIMENSIONS)
    assert contract_set.dispositions == (ContractDisposition.ADMITTED.value,)
    terminal = contract_set.evaluate()
    assert terminal.kind == BoundaryTerminalKind.ADMITTED.value
    assert terminal.success is True
    assert terminal.authorizes_completion is False
    restored = BoundaryContractSet.from_dict(
        json.loads(json.dumps(contract_set.to_dict()))
    )
    assert restored == contract_set
    assert restored.set_cid == contract_set.set_cid
    assert restored.set_cid == cid_for_structured(contract_set.identity_payload())


def test_synthesis_without_contracts_covers_edges_as_retrieval() -> None:
    edges = (
        _edge(),
        _edge(
            edge_id="edge:pkg.mod.Record:pkg.api",
            consumer_module="pkg.api",
            consumer_symbol="pkg.api.load",
        ),
    )
    contract_set = synthesize_boundary_contracts(
        edges,
        tree_id=TREE_ID,
        source_cid=_cid("source"),
        partition_cid=_cid("partition"),
    )
    assert len(contract_set.contracts) == 2
    assert contract_set.dispositions == (ContractDisposition.RETRIEVAL.value,)
    assert contract_set.evaluate().success is False
    with pytest.raises(BoundaryContractError, match="exactly the declared"):
        synthesize_boundary_contracts(
            edges,
            tree_id=TREE_ID,
            source_cid=_cid("source"),
            partition_cid=_cid("partition"),
            contracts=(_complete_contract(),),
        )


def test_empty_set_is_incomplete_and_never_completion() -> None:
    contract_set = _set(())
    terminal = contract_set.evaluate()
    assert terminal.kind == BoundaryTerminalKind.INCOMPLETE_CONTRACT.value
    assert terminal.success is False
    assert terminal.authorizes_completion is False
    assert contract_set.authorizes_completion is False
    assert contract_set.complete is False


def test_overlapping_unique_owners_fail_closed() -> None:
    first = _complete_contract()
    second = _complete_contract(
        cut_edge=_edge(
            edge_id="edge:pkg.other.Cache:pkg.cli",
            producer_module="pkg.other",
            producer_symbol="pkg.other.Cache",
        ),
        state_resource_owner=_owner(
            owner_id="owner:pkg.mod.CACHE",
            uniqueness=StateUniqueness.SHARED,
        ),
    )
    with pytest.raises(BoundaryContractError, match="overlapping unique"):
        _set((first, second))


def test_nested_records_round_trip_independently() -> None:
    records = (
        _edge(),
        _clause(),
        _effect(),
        _exception(),
        _owner(),
        _init(),
        _concurrency(),
        _authorization(),
        _serialization(),
        _versioning(),
        _proof(),
        _complete_contract().evaluate(),
    )
    for record in records:
        restored = type(record).from_dict(record.to_dict())
        assert restored == record


def test_unknown_and_missing_fields_are_rejected() -> None:
    contract = _complete_contract()
    payload = contract.to_dict()
    payload["timestamp"] = "now"
    with pytest.raises(BoundaryContractError, match="observational"):
        ModuleBoundaryContract.from_dict(payload)
    payload = contract.to_dict()
    payload["extra"] = "nope"
    with pytest.raises(BoundaryContractError, match="unknown"):
        ModuleBoundaryContract.from_dict(payload)
    payload = contract.to_dict()
    payload.pop("tree_id", None)
    payload.pop("cut_edge")
    with pytest.raises(BoundaryContractError, match="missing"):
        ModuleBoundaryContract.from_dict(payload)


def test_identity_excludes_observational_metadata() -> None:
    assert {
        "timestamp",
        "process_id",
        "pid",
        "local_path",
        "model_output",
        "provider",
        "prompt",
    } <= IDENTITY_EXCLUDED_FIELDS
    payload = _edge().to_dict()
    payload["model_output"] = "guess"
    with pytest.raises(BoundaryContractError, match="observational"):
        CutEdge.from_dict(payload)


def test_tree_id_and_cids_are_exact() -> None:
    with pytest.raises(BoundaryContractError, match="lowercase hex"):
        _set(tree_id="NOT-A-TREE")
    with pytest.raises(BoundaryContractError, match="valid CID"):
        _set(source_cid="not-a-cid")
    with pytest.raises(BoundaryContractError, match="valid CID"):
        _set(partition_cid="not-a-cid")


def test_forged_cids_and_schema_versions_fail_closed() -> None:
    contract = _complete_contract()
    payload = contract.to_dict()
    payload["contract_cid"] = _cid("forged")
    with pytest.raises(BoundaryContractError, match="does not verify"):
        ModuleBoundaryContract.from_dict(payload)
    payload = contract.to_dict()
    payload["schema"] = (
        "ipfs-datasets.semantic-refactoring.module-boundary-contract@0"
    )
    with pytest.raises(BoundaryContractError, match="unsupported"):
        ModuleBoundaryContract.from_dict(payload)
    payload = contract.to_dict()
    payload["interface"] = "ModuleBoundaryContract@0"
    with pytest.raises(BoundaryContractError, match="unsupported"):
        ModuleBoundaryContract.from_dict(payload)
    contract_set = _set()
    payload = contract_set.to_dict()
    payload["set_cid"] = _cid("forged")
    with pytest.raises(BoundaryContractError, match="does not verify"):
        BoundaryContractSet.from_dict(payload)


def test_forged_derived_fields_fail_closed() -> None:
    contract = _complete_contract()
    payload = contract.to_dict()
    payload["complete"] = False
    with pytest.raises(BoundaryContractError, match="complete"):
        ModuleBoundaryContract.from_dict(payload)
    payload = contract.to_dict()
    payload["disposition"] = ContractDisposition.RETRIEVAL.value
    with pytest.raises(BoundaryContractError, match="disposition"):
        ModuleBoundaryContract.from_dict(payload)
    payload = contract.to_dict()
    payload["authorizes_completion"] = True
    with pytest.raises(BoundaryContractError, match="cannot authorize completion"):
        ModuleBoundaryContract.from_dict(payload)
    payload = contract.to_dict()
    payload["missing_dimensions"] = ["assumptions"]
    with pytest.raises(BoundaryContractError, match="missing_dimensions"):
        ModuleBoundaryContract.from_dict(payload)
    contract_set = _set()
    payload = contract_set.to_dict()
    payload["edge_ids"] = []
    with pytest.raises(BoundaryContractError, match="edge_ids"):
        BoundaryContractSet.from_dict(payload)


def test_admitted_terminal_cannot_claim_completion_or_missing_dimensions() -> None:
    terminal = _complete_contract().evaluate()
    assert terminal.success is True
    assert terminal.authorizes_completion is False
    payload = terminal.to_dict()
    payload["authorizes_completion"] = True
    with pytest.raises(BoundaryContractError, match="cannot authorize completion"):
        BoundaryTerminal.from_dict(payload)
    with pytest.raises(BoundaryContractError, match="missing dimensions"):
        BoundaryTerminal(
            kind=BoundaryTerminalKind.ADMITTED,
            reason="cut edge has a complete assume/guarantee contract",
            required=True,
            edge_ids=("edge:pkg.mod.Record:pkg.cli",),
            missing_dimensions=("assumptions",),
        )


def test_records_are_frozen() -> None:
    contract = _complete_contract()
    with pytest.raises(Exception):
        contract.cut_edge.edge_id = "mutated"  # type: ignore[misc]
    with pytest.raises(Exception):
        contract.complete = False  # type: ignore[misc]


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
    assert "ModuleBoundaryContract" in exports
    assert "BoundaryContractSet" in exports
    assert "synthesize_boundary_contracts" in exports
    assert ANALYZER_ID.endswith("boundary_contracts@1")


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
    import ipfs_datasets_py.semantic_refactoring.boundary_contracts as boundary_contracts

    assert boundary_contracts.ModuleBoundaryContract is ModuleBoundaryContract
    assert boundary_contracts.__all__
    assert "llm" not in {name.lower() for name in boundary_contracts.__all__}
    assert "openai" not in boundary_contracts.__all__
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
