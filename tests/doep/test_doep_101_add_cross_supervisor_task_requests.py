"""Independent current-tree tests for DOEP-101 cross-supervisor task requests.

These tests exercise the canonical obligation module rather than treating a
worker assertion as acceptance evidence.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

DATASETS_ROOT = Path(__file__).resolve().parents[2]
if str(DATASETS_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASETS_ROOT))

from ipfs_datasets_py.logic.external_work_plan_obligations import (  # noqa: E402
    CROSS_SUPERVISOR_TASK_REQUEST_CAPABILITIES,
    CROSS_SUPERVISOR_TASK_REQUEST_CAPABILITY,
    CROSS_SUPERVISOR_TASK_REQUEST_CARRIERS,
    CROSS_SUPERVISOR_TASK_REQUEST_EFFECTS,
    CROSS_SUPERVISOR_TASK_REQUEST_FORBIDDEN_FIELDS,
    CROSS_SUPERVISOR_TASK_REQUEST_SCHEMA,
    CROSS_SUPERVISOR_TASK_REQUEST_SCHEMA_VERSION,
    PLAN_ASSUME_GUARANTEE_SCHEMA,
    PLAN_DELTA_SCHEMA,
    PLAN_EQUIVALENCE_ELIMINATION_SCHEMA,
    SUPERVISOR_PATCH_PLAN_SCHEMA,
    AcceptanceCondition,
    AssumeGuaranteeSubstitution,
    CrossSupervisorTaskRequest,
    EquivalentPlanClass,
    EquivalentTaskClass,
    ObligationError,
    PlanAssumeGuarantee,
    PlanDelta,
    PlanEquivalenceElimination,
    PlanObligation,
    PlanTerms,
    SupervisorPatchEdit,
    SupervisorPatchPlan,
    declared_cross_supervisor_task_request_parties,
    prove,
    validate_cross_supervisor_task_request,
    validate_plan_assume_guarantee,
    validate_plan_delta,
    validate_plan_equivalence_elimination,
    validate_plan_terms,
    validate_supervisor_patch_plan,
)

MODULE_PATH = DATASETS_ROOT / "ipfs_datasets_py/logic/external_work_plan_obligations.py"
TEST_PATH = Path(__file__).resolve()
OUTPUT_PATH = (
    DATASETS_ROOT
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-101.json"
)
RECEIPT_PATH = (
    DATASETS_ROOT
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-101.json"
)
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/external_work_plan_obligations.py",
    "tests/doep/test_doep_101_add_cross_supervisor_task_requests.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-101.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-101.json",
)
TASK_CID = "sha256:cb18791854d0bb217017d3e60773b6b30a0f4c7361222ee3a68321da409d7a0a"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"
BASE_REPOSITORIES = {
    "ipfs_accelerate_py": {
        "commit": "87715e9295626e7918f7fc8a7b1a1531ab04208f",
        "tree": "1c9a399cc7a599d5904e5be2ae58c6be3650cff7",
    },
    "ipfs_datasets_py": {
        "commit": "3668b8857a9aa7b1a3c847be12725b5cd057d2e7",
        "tree": "456e09b51d6a07a3a5873436df24054768195320",
    },
    "ipfs_kit_py": {
        "commit": "b6c65ba732733d7e33852713ba18aa3b12235668",
        "tree": "14da7d92e130b7ba3523d0d6741a3ef7ef1e1bc2",
    },
    "lift_coding": {
        "commit": "bb8869ed72eb7002434345d9969efee729c4f7f6",
        "tree": "99e85bfe584b7688ffbeff86da1e612dd6893a42",
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _acceptance(**overrides: Any) -> AcceptanceCondition:
    values: dict[str, Any] = {
        "condition_id": "tests-pass",
        "description": "The selected current-tree tests pass.",
        "verification_method": "independent pytest",
    }
    values.update(overrides)
    return AcceptanceCondition(**values)


def _request(**overrides: Any) -> CrossSupervisorTaskRequest:
    values: dict[str, Any] = {
        "request_id": "request:DOEP-101",
        "base_plan_revision": "DOEP-PLAN-V5",
        "requesting_supervisor_id": "supervisor:local",
        "receiving_supervisor_id": "supervisor:peer",
        "task_id": "DOEP-101",
        "intent_id": "intent:DOEP-010",
        "context_pack_id": "contextpack:DOEP-060",
        "patch_plan_id": "patch:DOEP-090",
        "carrier_event_id": "event:task-request-101",
        "acceptance_conditions": (_acceptance(),),
    }
    values.update(overrides)
    return CrossSupervisorTaskRequest(**values)


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_cross_supervisor_task_request_extends_obligation_layer_without_competing_subsystem() -> None:
    assert CROSS_SUPERVISOR_TASK_REQUEST_SCHEMA == (
        "ipfs_datasets_py/logic/external-work-plan-cross-supervisor-task-request@1"
    )
    assert CROSS_SUPERVISOR_TASK_REQUEST_SCHEMA_VERSION == (
        "external-work-plan-cross-supervisor-task-request/v1"
    )
    assert CROSS_SUPERVISOR_TASK_REQUEST_CAPABILITY == "task-request"
    assert CROSS_SUPERVISOR_TASK_REQUEST_CAPABILITIES == {"task-request"}
    assert CROSS_SUPERVISOR_TASK_REQUEST_CARRIERS == {"event"}
    assert CROSS_SUPERVISOR_TASK_REQUEST_EFFECTS == {"event_exchange"}
    assert dataclasses.is_dataclass(CrossSupervisorTaskRequest)
    assert not issubclass(CrossSupervisorTaskRequest, PlanObligation)
    assert not issubclass(CrossSupervisorTaskRequest, PlanTerms)
    assert not issubclass(CrossSupervisorTaskRequest, PlanDelta)
    assert not issubclass(CrossSupervisorTaskRequest, PlanAssumeGuarantee)
    assert not issubclass(CrossSupervisorTaskRequest, PlanEquivalenceElimination)
    assert not issubclass(CrossSupervisorTaskRequest, SupervisorPatchPlan)
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "not a new planner" in source
    assert "cannot grant completion authority" in source
    assert "independently verifies" in source
    assert "not a competing operational subsystem" in source
    assert "exchange as events" in source
    assert "never as database writes" in source
    assert "crosssupervisortaskrequest" in source
    assert "crosssupervisortaskbus" not in source
    assert "crosssupervisortaskdatabase" not in source
    assert "competingtaskrequestsubsystem" not in source
    assert "dispatch_cross_supervisor_task" not in source
    assert "write_sibling_database" not in source
    assert "create table" not in source
    assert "admission_receipt_cid" in CROSS_SUPERVISOR_TASK_REQUEST_FORBIDDEN_FIELDS
    assert "lease_id" in CROSS_SUPERVISOR_TASK_REQUEST_FORBIDDEN_FIELDS
    assert "sql" in CROSS_SUPERVISOR_TASK_REQUEST_FORBIDDEN_FIELDS
    assert "duckdb_path" in CROSS_SUPERVISOR_TASK_REQUEST_FORBIDDEN_FIELDS
    assert "consume" in CROSS_SUPERVISOR_TASK_REQUEST_FORBIDDEN_FIELDS
    assert "ipfs_accelerate_py" not in MODULE_PATH.read_text(encoding="utf-8")


def test_cross_supervisor_task_request_is_immutable_and_round_trips_canonically() -> None:
    request = _request()
    assert request.completion_authoritative is False
    assert request.mutation_authoritative is False
    assert request.history_preserving is True
    assert request.database_write is False
    assert request.direct_state_write is False
    assert request.terminalize_task is False
    assert request.worker_assertion_is_authority is False
    assert request.acceptance_requires_independent_evidence is True
    assert request.capability == "task-request"
    assert request.carrier == "event"
    assert request.requested_effect == "event_exchange"
    payload = request.to_dict()
    assert payload["schema"] == CROSS_SUPERVISOR_TASK_REQUEST_SCHEMA
    assert payload["schema_version"] == CROSS_SUPERVISOR_TASK_REQUEST_SCHEMA_VERSION
    assert payload["request_id"] == "request:DOEP-101"
    assert payload["base_plan_revision"] == "DOEP-PLAN-V5"
    assert payload["requesting_supervisor_id"] == "supervisor:local"
    assert payload["receiving_supervisor_id"] == "supervisor:peer"
    assert payload["task_id"] == "DOEP-101"
    assert payload["intent_id"] == "intent:DOEP-010"
    assert payload["context_pack_id"] == "contextpack:DOEP-060"
    assert payload["patch_plan_id"] == "patch:DOEP-090"
    assert payload["carrier_event_id"] == "event:task-request-101"
    assert payload["capability"] == "task-request"
    assert payload["carrier"] == "event"
    assert payload["requested_effect"] == "event_exchange"
    assert payload["acceptance_conditions"][0]["verification_method"] == (
        "independent pytest"
    )
    assert payload["database_write"] is False
    assert payload["direct_state_write"] is False
    assert payload["terminalize_task"] is False
    assert payload["completion_authoritative"] is False
    assert validate_cross_supervisor_task_request(payload).to_dict() == payload
    assert declared_cross_supervisor_task_request_parties(request) == (
        "supervisor:local",
        "supervisor:peer",
    )
    assert declared_cross_supervisor_task_request_parties(payload) == (
        "supervisor:local",
        "supervisor:peer",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.task_id = "DOEP-999"  # type: ignore[misc]


def test_sibling_identity_capability_carrier_and_evidence_fail_closed() -> None:
    with pytest.raises(ObligationError, match="not its own sibling"):
        _request(receiving_supervisor_id="supervisor:local")
    with pytest.raises(ObligationError, match="independent acceptance evidence"):
        _request(acceptance_conditions=())
    with pytest.raises(ObligationError, match="independent verification"):
        _request(
            acceptance_conditions=(
                _acceptance(verification_method="model assertion"),
            )
        )
    with pytest.raises(ObligationError, match="independent verification"):
        _request(
            acceptance_conditions=(
                _acceptance(verification_method="worker assertion"),
            )
        )
    with pytest.raises(ObligationError, match="independent evidence"):
        _request(acceptance_requires_independent_evidence=False)
    with pytest.raises(ObligationError, match="unsupported cross-supervisor task request capability"):
        _request(capability="database-write")
    with pytest.raises(ObligationError, match="unsupported cross-supervisor task request capability"):
        _request(capability="event-exchange")
    with pytest.raises(ObligationError, match="unsupported cross-supervisor task request carrier"):
        _request(carrier="database")
    with pytest.raises(ObligationError, match="unsupported cross-supervisor task request effect"):
        _request(requested_effect="authoritative_state")
    with pytest.raises(ObligationError, match="request_id"):
        _request(request_id="")
    with pytest.raises(ObligationError, match="acceptance condition IDs must be unique"):
        _request(
            acceptance_conditions=(
                _acceptance(),
                _acceptance(description="Repeated identifier is rejected."),
            )
        )


def test_history_authority_and_unknown_fields_fail_closed() -> None:
    with pytest.raises(ObligationError, match="completion authority"):
        _request(completion_authoritative=True)
    with pytest.raises(ObligationError, match="mutation authority"):
        _request(mutation_authoritative=True)
    with pytest.raises(ObligationError, match="preserve history"):
        _request(history_preserving=False)
    with pytest.raises(ObligationError, match="cannot write a database"):
        _request(database_write=True)
    with pytest.raises(ObligationError, match="direct state write"):
        _request(direct_state_write=True)
    with pytest.raises(ObligationError, match="cannot terminalize"):
        _request(terminalize_task=True)
    with pytest.raises(ObligationError, match="worker assertion is not"):
        _request(worker_assertion_is_authority=True)
    with pytest.raises(ObligationError, match="operational authority field"):
        CrossSupervisorTaskRequest.from_dict(
            {**_request().to_dict(), "policy_pointer": "forbidden"}
        )
    with pytest.raises(ObligationError, match="unknown cross-supervisor task request field"):
        CrossSupervisorTaskRequest.from_dict(
            {**_request().to_dict(), "foreign_bus": "forbidden"}
        )
    with pytest.raises(ObligationError, match="operational authority field"):
        CrossSupervisorTaskRequest.from_dict({**_request().to_dict(), "lease_id": "lease:x"})
    with pytest.raises(ObligationError, match="operational authority field"):
        CrossSupervisorTaskRequest.from_dict(
            {**_request().to_dict(), "admission_receipt_cid": "cid:x"}
        )
    with pytest.raises(ObligationError, match="operational authority field"):
        CrossSupervisorTaskRequest.from_dict(
            {**_request().to_dict(), "duckdb_path": "/tmp/control.duckdb"}
        )
    with pytest.raises(ObligationError, match="operational authority field"):
        CrossSupervisorTaskRequest.from_dict(
            {**_request().to_dict(), "sql": "UPDATE tasks SET status='done'"}
        )
    with pytest.raises(ObligationError, match="operational authority field"):
        CrossSupervisorTaskRequest.from_dict({**_request().to_dict(), "consume": True})


def test_existing_plan_terms_delta_assume_guarantee_equivalence_patch_and_obligations_remain_required() -> None:
    terms = PlanTerms(
        assumptions=("Dependencies provide current admitted receipts.",),
        guarantees=("Sibling supervisors exchange events, never database writes.",),
        non_goals=("This contract does not grant operational admission.",),
        acceptance_conditions=(_acceptance(),),
    )
    assert validate_plan_terms(terms).completion_authoritative is False
    delta = PlanDelta(
        base_plan_revision="DOEP-PLAN-V5",
        triggering_event_id="event:example-001",
        impacted_task_ids=("DOEP-101",),
        preserved_task_ids=("DOEP-024", "DOEP-090"),
        preserved_receipt_ids=("receipt:DOEP-024", "receipt:DOEP-090"),
        refill_task_ids=("DOEP-101",),
    )
    assert validate_plan_delta(delta).history_preserving is True
    assert delta.to_dict()["schema"] == PLAN_DELTA_SCHEMA
    contract = PlanAssumeGuarantee(
        base_plan_revision="DOEP-PLAN-V5",
        substitutions=(
            AssumeGuaranteeSubstitution(
                substitution_id="sub:producer-to-consumer",
                producer_component_id="component:producer",
                consumer_component_id="component:consumer",
                guarantees=("Preserved unaffected history is named explicitly.",),
                assumptions=("Dependencies provide current admitted receipts.",),
                admitted_guarantee_receipt_ids=("receipt:DOEP-024",),
            ),
        ),
        satisfied_assumptions=("Dependencies provide current admitted receipts.",),
    )
    assert validate_plan_assume_guarantee(contract).to_dict()["schema"] == (
        PLAN_ASSUME_GUARANTEE_SCHEMA
    )
    elimination = PlanEquivalenceElimination(
        base_plan_revision="DOEP-PLAN-V5",
        task_classes=(
            EquivalentTaskClass(
                class_id="eq-task:semantic-refill-duplicate",
                retained_task_id="DOEP-054",
                eliminated_task_ids=("DOEP-054-dup",),
                semantic_fingerprint="fp:task:semantic-refill",
                admitted_equivalence_receipt_ids=("receipt:DOEP-054",),
            ),
        ),
        plan_classes=(
            EquivalentPlanClass(
                class_id="eq-plan:impact-suffix-duplicate",
                retained_plan_id="plan:DOEP-G090.S3",
                eliminated_plan_ids=("plan:DOEP-G090.S3-dup",),
                semantic_fingerprint="fp:plan:equivalence-suffix",
                admitted_equivalence_receipt_ids=("receipt:DOEP-080",),
                equivalence_kind="logical_equivalence",
            ),
        ),
    )
    assert validate_plan_equivalence_elimination(elimination).to_dict()["schema"] == (
        PLAN_EQUIVALENCE_ELIMINATION_SCHEMA
    )
    patch = SupervisorPatchPlan(
        patch_plan_id="patch:DOEP-090",
        base_plan_revision="DOEP-PLAN-V5",
        task_id="DOEP-090",
        context_pack_id="contextpack:DOEP-060",
        kind="typed_edit",
        synthesis_origin="deterministic_allowlist",
        target_paths=("ipfs_datasets_py/logic/external_work_plan_obligations.py",),
        edits=(
            SupervisorPatchEdit(
                edit_id="edit:named-contract",
                path="ipfs_datasets_py/logic/external_work_plan_obligations.py",
                operation="replace",
                intent="Name CrossSupervisorTaskRequest without relocating operational admission.",
            ),
        ),
        acceptance_conditions=(_acceptance(),),
    )
    assert validate_supervisor_patch_plan(patch).to_dict()["schema"] == (
        SUPERVISOR_PATCH_PLAN_SCHEMA
    )
    complete = [
        PlanObligation(kind=kind, holds=True)
        for kind in (
            "child_covers_parent",
            "safe_parallel_effects",
            "validation_before_acceptance",
            "immutable_criteria",
            "no_self_granted_authority",
        )
    ]
    assert prove(complete) == tuple(complete)
    with pytest.raises(ObligationError, match="missing obligation"):
        prove(complete[:-1])


def test_output_manifest_and_candidate_receipt_bind_the_current_tree() -> None:
    manifest = _load_json(OUTPUT_PATH)
    receipt = _load_json(RECEIPT_PATH)
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-101"
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["plan_cid"] == receipt["plan_cid"] == PLAN_CID
    assert list(manifest["declared_outputs"]) == list(OWNER_RELATIVE_OUTPUTS)
    assert receipt["expected_outputs"] == list(OWNER_RELATIVE_OUTPUTS)
    assert manifest["completion_authoritative"] is False
    assert receipt["worker_completion_insufficient"] is True
    assert manifest["no_competing_subsystem_created"] is True
    contract = manifest["cross_supervisor_task_request_contract"]
    assert contract["module"] == "ipfs_datasets_py.logic.external_work_plan_obligations"
    assert contract["class_name"] == "CrossSupervisorTaskRequest"
    assert contract["schema"] == CROSS_SUPERVISOR_TASK_REQUEST_SCHEMA
    assert contract["schema_version"] == CROSS_SUPERVISOR_TASK_REQUEST_SCHEMA_VERSION
    assert contract["parallel_to"] == "PlanTerms"
    assert contract["competing_subsystem_created"] is False
    assert contract["operational_admission_owner"] == "ipfs_accelerate_py"
    assert contract["semantic_identity_owner"] == "ipfs_datasets_py"
    assert contract["capability"] == "task-request"
    assert contract["carrier"] == "event"
    assert contract["requested_effect"] == "event_exchange"
    assert contract["database_write"] is False
    assert contract["direct_state_write"] is False
    assert contract["terminalize_task"] is False
    assert contract["history_preserving"] is True
    assert contract["mutation_authoritative"] is False
    assert contract["completion_authoritative"] is False
    assert contract["acceptance_requires_independent_evidence"] is True
    assert contract["worker_assertion_is_authority"] is False
    assert contract["entrypoints"] == [
        "declared_cross_supervisor_task_request_parties",
        "validate_cross_supervisor_task_request",
    ]
    evidence = receipt["required_evidence"]
    assert evidence["source_commit_tree_gitlinks"] == BASE_REPOSITORIES
    assert evidence["test_proof_results"]["validation_command"] == [
        "python3",
        "-m",
        "pytest",
        "tests/doep/test_doep_101_add_cross_supervisor_task_requests.py",
        "-q",
    ]
    for relative in OWNER_RELATIVE_OUTPUTS[:2]:
        assert receipt["path_digests"][relative] == _digest(DATASETS_ROOT / relative)
    assert TEST_PATH.is_file()
    assert MODULE_PATH.is_file()
    assert receipt["outputs_present"][OWNER_RELATIVE_OUTPUTS[0]] is True
    assert receipt["supervisor_acceptance"]["completion_authoritative"] is False
