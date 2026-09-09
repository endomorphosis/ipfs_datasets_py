"""Independent current-tree tests for DOEP-024 plan terms.

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
    PLAN_TERMS_SCHEMA,
    PLAN_TERMS_SCHEMA_VERSION,
    AcceptanceCondition,
    ObligationError,
    PlanObligation,
    PlanTerms,
    prove,
    validate_plan_terms,
)

MODULE_PATH = DATASETS_ROOT / "ipfs_datasets_py/logic/external_work_plan_obligations.py"
TEST_PATH = Path(__file__).resolve()
OUTPUT_PATH = DATASETS_ROOT / "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-024.json"
RECEIPT_PATH = DATASETS_ROOT / "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-024.json"
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/external_work_plan_obligations.py",
    "tests/doep/test_doep_024_add_assumptions_guarantees_non_goals_and_acceptance_.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-024.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-024.json",
)
TASK_CID = "sha256:49d9b700fc52e1c19e77bf738cc27fb6523dce93c3b39958777baa7d9fa32577"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"


def _load_json(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _terms(**overrides: Any) -> PlanTerms:
    values: dict[str, Any] = {
        "assumptions": ("Dependencies provide current admitted receipts.",),
        "guarantees": ("All declared conditions are explicit and immutable.",),
        "non_goals": ("This contract does not grant operational admission.",),
        "acceptance_conditions": (
            AcceptanceCondition(
                "tests-pass", "The selected current-tree tests pass.", "independent pytest",
            ),
        ),
    }
    values.update(overrides)
    return PlanTerms(**values)


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_terms_extend_existing_obligation_layer_without_competing_subsystem() -> None:
    assert PLAN_TERMS_SCHEMA == "ipfs_datasets_py/logic/external-work-plan-terms@1"
    assert PLAN_TERMS_SCHEMA_VERSION == "external-work-plan-terms/v1"
    assert dataclasses.is_dataclass(PlanTerms)
    assert dataclasses.is_dataclass(AcceptanceCondition)
    assert not issubclass(PlanTerms, PlanObligation)
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "not a new planner" in source
    assert "cannot grant completion authority" in source
    assert "independently verifies" in source


def test_plan_terms_are_immutable_and_round_trip_canonically() -> None:
    terms = _terms()
    assert terms.completion_authoritative is False
    payload = terms.to_dict()
    assert payload["schema"] == PLAN_TERMS_SCHEMA
    assert payload["assumptions"] == ["Dependencies provide current admitted receipts."]
    assert payload["guarantees"] == ["All declared conditions are explicit and immutable."]
    assert payload["non_goals"] == ["This contract does not grant operational admission."]
    assert payload["acceptance_conditions"][0]["verification_method"] == "independent pytest"
    assert validate_plan_terms(payload).to_dict() == payload
    with pytest.raises(dataclasses.FrozenInstanceError):
        terms.guarantees = ()  # type: ignore[misc]


@pytest.mark.parametrize("field", ("assumptions", "guarantees", "non_goals"))
def test_each_plan_term_category_is_required(field: str) -> None:
    with pytest.raises(ObligationError, match=field):
        _terms(**{field: ()})


def test_acceptance_is_explicit_independent_and_fail_closed() -> None:
    with pytest.raises(ObligationError, match="acceptance_conditions"):
        _terms(acceptance_conditions=())
    with pytest.raises(ObligationError, match="independent verification"):
        _terms(acceptance_conditions=(AcceptanceCondition("worker", "claimed", "worker assertion"),))
    with pytest.raises(ObligationError, match="completion authority"):
        _terms(completion_authoritative=True)
    with pytest.raises(ObligationError, match="unknown plan terms field"):
        PlanTerms.from_dict({**_terms().to_dict(), "policy_id": "forbidden"})


def test_existing_obligations_remain_required_before_acceptance() -> None:
    complete = [PlanObligation(kind=kind, holds=True) for kind in (
        "child_covers_parent", "safe_parallel_effects", "validation_before_acceptance",
        "immutable_criteria", "no_self_granted_authority",
    )]
    assert prove(complete) == tuple(complete)
    with pytest.raises(ObligationError, match="missing obligation"):
        prove(complete[:-1])


def test_output_manifest_and_candidate_receipt_bind_the_current_tree() -> None:
    manifest = _load_json(OUTPUT_PATH)
    receipt = _load_json(RECEIPT_PATH)
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-024"
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["plan_cid"] == receipt["plan_cid"] == PLAN_CID
    assert list(manifest["declared_outputs"]) == list(OWNER_RELATIVE_OUTPUTS)
    assert receipt["expected_outputs"] == list(OWNER_RELATIVE_OUTPUTS)
    assert manifest["completion_authoritative"] is False
    assert receipt["worker_completion_insufficient"] is True
    assert manifest["plan_terms_contract"]["module"] == "ipfs_datasets_py.logic.external_work_plan_obligations"
    for relative in OWNER_RELATIVE_OUTPUTS[:2]:
        assert receipt["path_digests"][relative] == _digest(DATASETS_ROOT / relative)
