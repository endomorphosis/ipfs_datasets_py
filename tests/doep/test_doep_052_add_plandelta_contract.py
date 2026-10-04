"""Independent current-tree tests for DOEP-052 PlanDelta contract.

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
    PLAN_DELTA_FORBIDDEN_FIELDS,
    PLAN_DELTA_SCHEMA,
    PLAN_DELTA_SCHEMA_VERSION,
    AcceptanceCondition,
    ObligationError,
    PlanDelta,
    PlanObligation,
    PlanTerms,
    prove,
    validate_plan_delta,
    validate_plan_terms,
)

MODULE_PATH = DATASETS_ROOT / "ipfs_datasets_py/logic/external_work_plan_obligations.py"
TEST_PATH = Path(__file__).resolve()
OUTPUT_PATH = DATASETS_ROOT / "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-052.json"
RECEIPT_PATH = DATASETS_ROOT / "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-052.json"
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/external_work_plan_obligations.py",
    "tests/doep/test_doep_052_add_plandelta_contract.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-052.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-052.json",
)
TASK_CID = "sha256:d976f744a4e99067273da9285ba8b759827f8a5f2a7081eaea1ef5227420ff73"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"


def _load_json(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _delta(**overrides: Any) -> PlanDelta:
    values: dict[str, Any] = {
        "base_plan_revision": "DOEP-PLAN-V5",
        "triggering_event_id": "event:example-001",
        "impacted_task_ids": ("DOEP-053",),
        "preserved_task_ids": ("DOEP-024", "DOEP-030"),
        "preserved_receipt_ids": ("receipt:DOEP-024", "receipt:DOEP-030"),
        "refill_task_ids": ("DOEP-053",),
    }
    values.update(overrides)
    return PlanDelta(**values)


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_delta_extends_existing_obligation_layer_without_competing_subsystem() -> None:
    assert PLAN_DELTA_SCHEMA == "ipfs_datasets_py/logic/external-work-plan-delta@1"
    assert PLAN_DELTA_SCHEMA_VERSION == "external-work-plan-delta/v1"
    assert dataclasses.is_dataclass(PlanDelta)
    assert not issubclass(PlanDelta, PlanObligation)
    assert not issubclass(PlanDelta, PlanTerms)
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "not a new planner" in source
    assert "cannot grant completion authority" in source
    assert "independently verifies" in source
    assert "not a competing operational subsystem" in source
    assert "preserve unaffected" in source or "preserved unaffected" in source
    assert "plandeltaoperation" not in source
    assert "admission_receipt_cid" in PLAN_DELTA_FORBIDDEN_FIELDS
    assert "items" in PLAN_DELTA_FORBIDDEN_FIELDS
    assert "ipfs_accelerate_py" not in MODULE_PATH.read_text(encoding="utf-8")


def test_plan_delta_is_immutable_and_round_trips_canonically() -> None:
    delta = _delta()
    assert delta.completion_authoritative is False
    assert delta.history_preserving is True
    assert delta.model_free_refill is True
    payload = delta.to_dict()
    assert payload["schema"] == PLAN_DELTA_SCHEMA
    assert payload["schema_version"] == PLAN_DELTA_SCHEMA_VERSION
    assert payload["base_plan_revision"] == "DOEP-PLAN-V5"
    assert payload["impacted_task_ids"] == ["DOEP-053"]
    assert payload["preserved_task_ids"] == ["DOEP-024", "DOEP-030"]
    assert payload["refill_task_ids"] == ["DOEP-053"]
    assert validate_plan_delta(payload).to_dict() == payload
    with pytest.raises(dataclasses.FrozenInstanceError):
        delta.impacted_task_ids = ()  # type: ignore[misc]


def test_impacted_and_preserved_sets_are_disjoint() -> None:
    with pytest.raises(ObligationError, match="disjoint"):
        _delta(
            impacted_task_ids=("DOEP-053", "DOEP-024"),
            preserved_task_ids=("DOEP-024", "DOEP-030"),
        )


def test_refill_is_model_free_and_subset_of_impacted_suffix() -> None:
    with pytest.raises(ObligationError, match="subset of the impacted"):
        _delta(refill_task_ids=("DOEP-999",))
    empty_refill = _delta(refill_task_ids=())
    assert empty_refill.refill_task_ids == ()
    empty_cone = _delta(
        impacted_task_ids=(),
        preserved_task_ids=("DOEP-024",),
        preserved_receipt_ids=("receipt:DOEP-024",),
        refill_task_ids=(),
    )
    assert empty_cone.impacted_task_ids == ()
    with pytest.raises(ObligationError, match="model-free"):
        _delta(model_free_refill=False)


def test_history_rewrite_and_completion_authority_fail_closed() -> None:
    with pytest.raises(ObligationError, match="completion authority"):
        _delta(completion_authoritative=True)
    with pytest.raises(ObligationError, match="preserve history"):
        _delta(history_preserving=False)
    with pytest.raises(ObligationError, match="unknown plan delta field"):
        PlanDelta.from_dict({**_delta().to_dict(), "policy_pointer": "forbidden"})
    with pytest.raises(ObligationError, match="operational authority field"):
        PlanDelta.from_dict({**_delta().to_dict(), "items": []})
    with pytest.raises(ObligationError, match="operational authority field"):
        PlanDelta.from_dict({**_delta().to_dict(), "admission_receipt_cid": "cid:x"})
    with pytest.raises(ObligationError, match="operational authority field"):
        PlanDelta.from_dict({**_delta().to_dict(), "lease_id": "lease:x"})


def test_required_identities_are_non_empty_and_unique() -> None:
    with pytest.raises(ObligationError, match="base_plan_revision"):
        _delta(base_plan_revision="")
    with pytest.raises(ObligationError, match="triggering_event_id"):
        _delta(triggering_event_id="")
    with pytest.raises(ObligationError, match="duplicates"):
        _delta(impacted_task_ids=("DOEP-053", "DOEP-053"))


def test_existing_plan_terms_and_obligations_remain_required() -> None:
    terms = PlanTerms(
        assumptions=("Dependencies provide current admitted receipts.",),
        guarantees=("Plan deltas preserve unaffected history.",),
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
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-052"
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["plan_cid"] == receipt["plan_cid"] == PLAN_CID
    assert list(manifest["declared_outputs"]) == list(OWNER_RELATIVE_OUTPUTS)
    assert receipt["expected_outputs"] == list(OWNER_RELATIVE_OUTPUTS)
    assert manifest["completion_authoritative"] is False
    assert receipt["worker_completion_insufficient"] is True
    assert manifest["no_competing_subsystem_created"] is True
    contract = manifest["plan_delta_contract"]
    assert contract["module"] == "ipfs_datasets_py.logic.external_work_plan_obligations"
    assert contract["class_name"] == "PlanDelta"
    assert contract["schema"] == PLAN_DELTA_SCHEMA
    assert contract["schema_version"] == PLAN_DELTA_SCHEMA_VERSION
    assert contract["parallel_to"] == "PlanTerms"
    assert contract["competing_subsystem_created"] is False
    assert contract["operational_admission_owner"] == "ipfs_accelerate_py"
    assert contract["semantic_identity_owner"] == "ipfs_datasets_py"
    assert contract["history_preserving"] is True
    assert contract["model_free_refill"] is True
    assert contract["completion_authoritative"] is False
    for relative in OWNER_RELATIVE_OUTPUTS[:2]:
        assert receipt["path_digests"][relative] == _digest(DATASETS_ROOT / relative)
