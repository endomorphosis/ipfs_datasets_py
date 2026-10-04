"""Independent current-tree tests for DOEP-080 assume-guarantee contracts.

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
    PLAN_ASSUME_GUARANTEE_FORBIDDEN_FIELDS,
    PLAN_ASSUME_GUARANTEE_SCHEMA,
    PLAN_ASSUME_GUARANTEE_SCHEMA_VERSION,
    AcceptanceCondition,
    AssumeGuaranteeSubstitution,
    ObligationError,
    PlanAssumeGuarantee,
    PlanDelta,
    PlanObligation,
    PlanTerms,
    prove,
    validate_plan_assume_guarantee,
    validate_plan_delta,
    validate_plan_terms,
)

MODULE_PATH = DATASETS_ROOT / "ipfs_datasets_py/logic/external_work_plan_obligations.py"
TEST_PATH = Path(__file__).resolve()
OUTPUT_PATH = (
    DATASETS_ROOT
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-080.json"
)
RECEIPT_PATH = (
    DATASETS_ROOT
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-080.json"
)
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/external_work_plan_obligations.py",
    "tests/doep/test_doep_080_add_assume_guarantee_planning_contracts.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-080.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-080.json",
)
TASK_CID = "sha256:eba385c7c88c70cc9ff10427b1ebbf48c641b28e0e870781ebbb3a1a8c10af15"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"


def _load_json(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _substitution(**overrides: Any) -> AssumeGuaranteeSubstitution:
    values: dict[str, Any] = {
        "substitution_id": "sub:producer-to-consumer",
        "producer_component_id": "component:producer",
        "consumer_component_id": "component:consumer",
        "guarantees": ("Preserved unaffected history is named explicitly.",),
        "assumptions": ("Dependencies provide current admitted receipts.",),
        "admitted_guarantee_receipt_ids": ("receipt:DOEP-024",),
    }
    values.update(overrides)
    return AssumeGuaranteeSubstitution(**values)


def _contract(**overrides: Any) -> PlanAssumeGuarantee:
    values: dict[str, Any] = {
        "base_plan_revision": "DOEP-PLAN-V5",
        "substitutions": (_substitution(),),
        "satisfied_assumptions": ("Dependencies provide current admitted receipts.",),
    }
    values.update(overrides)
    return PlanAssumeGuarantee(**values)


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_assume_guarantee_extends_obligation_layer_without_competing_subsystem() -> None:
    assert PLAN_ASSUME_GUARANTEE_SCHEMA == (
        "ipfs_datasets_py/logic/external-work-plan-assume-guarantee@1"
    )
    assert PLAN_ASSUME_GUARANTEE_SCHEMA_VERSION == (
        "external-work-plan-assume-guarantee/v1"
    )
    assert dataclasses.is_dataclass(PlanAssumeGuarantee)
    assert dataclasses.is_dataclass(AssumeGuaranteeSubstitution)
    assert not issubclass(PlanAssumeGuarantee, PlanObligation)
    assert not issubclass(PlanAssumeGuarantee, PlanTerms)
    assert not issubclass(PlanAssumeGuarantee, PlanDelta)
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "not a new planner" in source
    assert "cannot grant completion authority" in source
    assert "independently verifies" in source
    assert "not a competing operational subsystem" in source
    assert "current admitted guarantees" in source
    assert "satisfied assumptions" in source
    assert "assume_guarantee_engine" not in source
    assert "discharge_assume_guarantee" not in source
    assert "admission_receipt_cid" in PLAN_ASSUME_GUARANTEE_FORBIDDEN_FIELDS
    assert "lease_id" in PLAN_ASSUME_GUARANTEE_FORBIDDEN_FIELDS
    assert "ipfs_accelerate_py" not in MODULE_PATH.read_text(encoding="utf-8")


def test_plan_assume_guarantee_is_immutable_and_round_trips_canonically() -> None:
    contract = _contract()
    assert contract.completion_authoritative is False
    assert contract.substitution_requires_admitted_guarantees is True
    assert contract.substitution_requires_satisfied_assumptions is True
    payload = contract.to_dict()
    assert payload["schema"] == PLAN_ASSUME_GUARANTEE_SCHEMA
    assert payload["schema_version"] == PLAN_ASSUME_GUARANTEE_SCHEMA_VERSION
    assert payload["base_plan_revision"] == "DOEP-PLAN-V5"
    assert payload["substitutions"][0]["producer_component_id"] == "component:producer"
    assert payload["substitutions"][0]["admitted_guarantee_receipt_ids"] == [
        "receipt:DOEP-024"
    ]
    assert payload["satisfied_assumptions"] == [
        "Dependencies provide current admitted receipts."
    ]
    assert validate_plan_assume_guarantee(payload).to_dict() == payload
    with pytest.raises(dataclasses.FrozenInstanceError):
        contract.substitutions = ()  # type: ignore[misc]


def test_substitution_requires_current_admitted_guarantees() -> None:
    with pytest.raises(ObligationError, match="current admitted guarantees"):
        _substitution(admitted_guarantee_receipt_ids=())
    with pytest.raises(ObligationError, match="current admitted guarantees"):
        _contract(substitution_requires_admitted_guarantees=False)


def test_substitution_requires_satisfied_assumptions() -> None:
    with pytest.raises(ObligationError, match="satisfied assumptions"):
        _contract(satisfied_assumptions=())
    with pytest.raises(ObligationError, match="satisfied assumptions"):
        _contract(
            satisfied_assumptions=("An unrelated satisfied assumption.",),
        )
    with pytest.raises(ObligationError, match="satisfied assumptions"):
        _contract(substitution_requires_satisfied_assumptions=False)


def test_guarantees_and_assumptions_are_required_and_unique() -> None:
    with pytest.raises(ObligationError, match="guarantees"):
        _substitution(guarantees=())
    with pytest.raises(ObligationError, match="assumptions"):
        _substitution(assumptions=())
    with pytest.raises(ObligationError, match="duplicates"):
        _substitution(
            guarantees=(
                "Preserved unaffected history is named explicitly.",
                "Preserved unaffected history is named explicitly.",
            )
        )
    with pytest.raises(ObligationError, match="substitution IDs must be unique"):
        _contract(
            substitutions=(
                _substitution(substitution_id="sub:a"),
                _substitution(substitution_id="sub:a"),
            )
        )


def test_history_authority_and_unknown_fields_fail_closed() -> None:
    with pytest.raises(ObligationError, match="completion authority"):
        _contract(completion_authoritative=True)
    with pytest.raises(ObligationError, match="unknown assume-guarantee field"):
        PlanAssumeGuarantee.from_dict(
            {**_contract().to_dict(), "policy_pointer": "forbidden"}
        )
    with pytest.raises(ObligationError, match="operational authority field"):
        PlanAssumeGuarantee.from_dict({**_contract().to_dict(), "lease_id": "lease:x"})
    with pytest.raises(ObligationError, match="operational authority field"):
        PlanAssumeGuarantee.from_dict(
            {**_contract().to_dict(), "admission_receipt_cid": "cid:x"}
        )
    with pytest.raises(ObligationError, match="operational authority field"):
        PlanAssumeGuarantee.from_dict(
            {**_contract().to_dict(), "self_granted_substitution": True}
        )
    with pytest.raises(ObligationError, match="substitutions must not be empty"):
        _contract(substitutions=())
    with pytest.raises(ObligationError, match="base_plan_revision"):
        _contract(base_plan_revision="")


def test_existing_plan_terms_delta_and_obligations_remain_required() -> None:
    terms = PlanTerms(
        assumptions=("Dependencies provide current admitted receipts.",),
        guarantees=("Assume-guarantee substitutions stay explicit and fail-closed.",),
        non_goals=("This contract does not grant operational admission.",),
        acceptance_conditions=(
            AcceptanceCondition(
                "tests-pass",
                "The selected current-tree tests pass.",
                "independent pytest",
            ),
        ),
    )
    assert validate_plan_terms(terms).completion_authoritative is False
    delta = PlanDelta(
        base_plan_revision="DOEP-PLAN-V5",
        triggering_event_id="event:example-001",
        impacted_task_ids=("DOEP-081",),
        preserved_task_ids=("DOEP-024", "DOEP-080"),
        preserved_receipt_ids=("receipt:DOEP-024", "receipt:DOEP-080"),
        refill_task_ids=("DOEP-081",),
    )
    assert validate_plan_delta(delta).history_preserving is True
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
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-080"
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["plan_cid"] == receipt["plan_cid"] == PLAN_CID
    assert list(manifest["declared_outputs"]) == list(OWNER_RELATIVE_OUTPUTS)
    assert receipt["expected_outputs"] == list(OWNER_RELATIVE_OUTPUTS)
    assert manifest["completion_authoritative"] is False
    assert receipt["worker_completion_insufficient"] is True
    assert manifest["no_competing_subsystem_created"] is True
    contract = manifest["assume_guarantee_contract"]
    assert contract["module"] == "ipfs_datasets_py.logic.external_work_plan_obligations"
    assert contract["class_name"] == "PlanAssumeGuarantee"
    assert contract["substitution_class"] == "AssumeGuaranteeSubstitution"
    assert contract["schema"] == PLAN_ASSUME_GUARANTEE_SCHEMA
    assert contract["schema_version"] == PLAN_ASSUME_GUARANTEE_SCHEMA_VERSION
    assert contract["parallel_to"] == "PlanTerms"
    assert contract["competing_subsystem_created"] is False
    assert contract["operational_admission_owner"] == "ipfs_accelerate_py"
    assert contract["semantic_identity_owner"] == "ipfs_datasets_py"
    assert contract["substitution_requires_admitted_guarantees"] is True
    assert contract["substitution_requires_satisfied_assumptions"] is True
    assert contract["completion_authoritative"] is False
    for relative in OWNER_RELATIVE_OUTPUTS[:2]:
        assert receipt["path_digests"][relative] == _digest(DATASETS_ROOT / relative)
