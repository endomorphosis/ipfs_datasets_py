"""Independent current-tree tests for DOEP-085 equivalence elimination.

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
    EQUIVALENCE_KINDS,
    PLAN_ASSUME_GUARANTEE_SCHEMA,
    PLAN_DELTA_SCHEMA,
    PLAN_EQUIVALENCE_ELIMINATION_FORBIDDEN_FIELDS,
    PLAN_EQUIVALENCE_ELIMINATION_SCHEMA,
    PLAN_EQUIVALENCE_ELIMINATION_SCHEMA_VERSION,
    AcceptanceCondition,
    AssumeGuaranteeSubstitution,
    EquivalentPlanClass,
    EquivalentTaskClass,
    ObligationError,
    PlanAssumeGuarantee,
    PlanDelta,
    PlanEquivalenceElimination,
    PlanObligation,
    PlanTerms,
    eliminate_equivalent_plans,
    eliminate_equivalent_tasks,
    prove,
    validate_plan_assume_guarantee,
    validate_plan_delta,
    validate_plan_equivalence_elimination,
    validate_plan_terms,
)

MODULE_PATH = DATASETS_ROOT / "ipfs_datasets_py/logic/external_work_plan_obligations.py"
TEST_PATH = Path(__file__).resolve()
OUTPUT_PATH = (
    DATASETS_ROOT
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-085.json"
)
RECEIPT_PATH = (
    DATASETS_ROOT
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-085.json"
)
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/external_work_plan_obligations.py",
    "tests/doep/test_doep_085_add_equivalent_task_and_equivalent_plan_elimination.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-085.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-085.json",
)
TASK_CID = "sha256:4b2636c5ee51acabc74b04148b4ca01418a5fb1a884a2b37639519ba39e8ce45"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"


def _load_json(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _task_class(**overrides: Any) -> EquivalentTaskClass:
    values: dict[str, Any] = {
        "class_id": "eq-task:semantic-refill-duplicate",
        "retained_task_id": "DOEP-054",
        "eliminated_task_ids": ("DOEP-054-dup",),
        "semantic_fingerprint": "fp:task:semantic-refill",
        "admitted_equivalence_receipt_ids": ("receipt:DOEP-054",),
        "equivalence_kind": "semantic_identity",
    }
    values.update(overrides)
    return EquivalentTaskClass(**values)


def _plan_class(**overrides: Any) -> EquivalentPlanClass:
    values: dict[str, Any] = {
        "class_id": "eq-plan:impact-suffix-duplicate",
        "retained_plan_id": "plan:DOEP-G090.S3",
        "eliminated_plan_ids": ("plan:DOEP-G090.S3-dup",),
        "semantic_fingerprint": "fp:plan:equivalence-suffix",
        "admitted_equivalence_receipt_ids": ("receipt:DOEP-080",),
        "equivalence_kind": "logical_equivalence",
    }
    values.update(overrides)
    return EquivalentPlanClass(**values)


def _elimination(**overrides: Any) -> PlanEquivalenceElimination:
    values: dict[str, Any] = {
        "base_plan_revision": "DOEP-PLAN-V5",
        "task_classes": (_task_class(),),
        "plan_classes": (_plan_class(),),
    }
    values.update(overrides)
    return PlanEquivalenceElimination(**values)


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_equivalence_elimination_extends_obligation_layer_without_competing_subsystem() -> None:
    assert PLAN_EQUIVALENCE_ELIMINATION_SCHEMA == (
        "ipfs_datasets_py/logic/external-work-plan-equivalence-elimination@1"
    )
    assert PLAN_EQUIVALENCE_ELIMINATION_SCHEMA_VERSION == (
        "external-work-plan-equivalence-elimination/v1"
    )
    assert EQUIVALENCE_KINDS == {
        "semantic_identity",
        "logical_equivalence",
        "canonical_equivalent",
    }
    assert dataclasses.is_dataclass(PlanEquivalenceElimination)
    assert dataclasses.is_dataclass(EquivalentTaskClass)
    assert dataclasses.is_dataclass(EquivalentPlanClass)
    assert not issubclass(PlanEquivalenceElimination, PlanObligation)
    assert not issubclass(PlanEquivalenceElimination, PlanTerms)
    assert not issubclass(PlanEquivalenceElimination, PlanDelta)
    assert not issubclass(PlanEquivalenceElimination, PlanAssumeGuarantee)
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "not a new planner" in source
    assert "cannot grant completion authority" in source
    assert "independently verifies" in source
    assert "not a competing operational subsystem" in source
    assert "current admitted equivalence" in source
    assert "equivalent-task" in source
    assert "equivalent-plan" in source
    assert "preserve history" in source or "history is preserved" in source
    assert "equivalence_engine" not in source
    assert "eliminate_and_complete" not in source
    assert "self_granted_elimination" in PLAN_EQUIVALENCE_ELIMINATION_FORBIDDEN_FIELDS
    assert "admission_receipt_cid" in PLAN_EQUIVALENCE_ELIMINATION_FORBIDDEN_FIELDS
    assert "lease_id" in PLAN_EQUIVALENCE_ELIMINATION_FORBIDDEN_FIELDS
    assert "ipfs_accelerate_py" not in MODULE_PATH.read_text(encoding="utf-8")


def test_plan_equivalence_elimination_is_immutable_and_round_trips_canonically() -> None:
    elimination = _elimination()
    assert elimination.completion_authoritative is False
    assert elimination.history_preserving is True
    assert elimination.model_free is True
    assert elimination.elimination_requires_admitted_equivalence is True
    payload = elimination.to_dict()
    assert payload["schema"] == PLAN_EQUIVALENCE_ELIMINATION_SCHEMA
    assert payload["schema_version"] == PLAN_EQUIVALENCE_ELIMINATION_SCHEMA_VERSION
    assert payload["base_plan_revision"] == "DOEP-PLAN-V5"
    assert payload["task_classes"][0]["retained_task_id"] == "DOEP-054"
    assert payload["task_classes"][0]["eliminated_task_ids"] == ["DOEP-054-dup"]
    assert payload["plan_classes"][0]["retained_plan_id"] == "plan:DOEP-G090.S3"
    assert payload["plan_classes"][0]["eliminated_plan_ids"] == [
        "plan:DOEP-G090.S3-dup"
    ]
    assert validate_plan_equivalence_elimination(payload).to_dict() == payload
    with pytest.raises(dataclasses.FrozenInstanceError):
        elimination.task_classes = ()  # type: ignore[misc]


def test_equivalent_task_elimination_collapses_duplicates_onto_retained_identity() -> None:
    elimination = _elimination()
    assert eliminate_equivalent_tasks(
        ("DOEP-054", "DOEP-054-dup", "DOEP-085"),
        elimination,
    ) == ("DOEP-054", "DOEP-085")
    assert eliminate_equivalent_tasks(("DOEP-054-dup",), elimination) == ("DOEP-054",)
    assert eliminate_equivalent_tasks(("DOEP-085",), elimination) == ("DOEP-085",)
    assert eliminate_equivalent_tasks((), elimination) == ()
    assert eliminate_equivalent_tasks(
        ("DOEP-054-dup", "DOEP-054"),
        elimination.to_dict(),
    ) == ("DOEP-054",)


def test_equivalent_plan_elimination_collapses_duplicates_onto_retained_identity() -> None:
    elimination = _elimination()
    assert eliminate_equivalent_plans(
        ("plan:DOEP-G090.S3-dup", "plan:other", "plan:DOEP-G090.S3"),
        elimination,
    ) == ("plan:DOEP-G090.S3", "plan:other")
    assert eliminate_equivalent_plans(
        ("plan:DOEP-G090.S3-dup",),
        elimination,
    ) == ("plan:DOEP-G090.S3",)
    assert eliminate_equivalent_plans(("plan:unrelated",), elimination) == (
        "plan:unrelated",
    )


def test_elimination_requires_current_admitted_equivalence() -> None:
    with pytest.raises(ObligationError, match="current admitted equivalence"):
        _task_class(admitted_equivalence_receipt_ids=())
    with pytest.raises(ObligationError, match="current admitted equivalence"):
        _plan_class(admitted_equivalence_receipt_ids=())
    with pytest.raises(ObligationError, match="current admitted equivalence"):
        _elimination(elimination_requires_admitted_equivalence=False)


def test_worker_or_model_assertion_cannot_establish_equivalence() -> None:
    with pytest.raises(ObligationError, match="independent verification"):
        _task_class(equivalence_kind="worker assertion")
    with pytest.raises(ObligationError, match="independent verification"):
        _plan_class(equivalence_kind="model assertion")
    with pytest.raises(ObligationError, match="unsupported equivalence kind"):
        _task_class(equivalence_kind="syntactic_similarity")


def test_retained_and_eliminated_identities_are_disjoint_and_unique() -> None:
    with pytest.raises(ObligationError, match="disjoint"):
        _task_class(eliminated_task_ids=("DOEP-054",))
    with pytest.raises(ObligationError, match="disjoint"):
        _plan_class(eliminated_plan_ids=("plan:DOEP-G090.S3",))
    with pytest.raises(ObligationError, match="must not be empty"):
        _task_class(eliminated_task_ids=())
    with pytest.raises(ObligationError, match="must not be empty"):
        _plan_class(eliminated_plan_ids=())
    with pytest.raises(ObligationError, match="class IDs must be unique"):
        _elimination(
            task_classes=(
                _task_class(class_id="eq-task:same"),
                _task_class(
                    class_id="eq-task:same",
                    retained_task_id="DOEP-081",
                    eliminated_task_ids=("DOEP-081-dup",),
                    semantic_fingerprint="fp:task:other",
                    admitted_equivalence_receipt_ids=("receipt:DOEP-081",),
                ),
            )
        )
    with pytest.raises(ObligationError, match="semantic fingerprints must be unique"):
        _elimination(
            task_classes=(
                _task_class(),
                _task_class(
                    class_id="eq-task:other",
                    retained_task_id="DOEP-081",
                    eliminated_task_ids=("DOEP-081-dup",),
                    semantic_fingerprint="fp:task:semantic-refill",
                    admitted_equivalence_receipt_ids=("receipt:DOEP-081",),
                ),
            )
        )
    with pytest.raises(ObligationError, match="requires a task or plan class"):
        _elimination(task_classes=(), plan_classes=())


def test_history_authority_and_unknown_fields_fail_closed() -> None:
    with pytest.raises(ObligationError, match="completion authority"):
        _elimination(completion_authoritative=True)
    with pytest.raises(ObligationError, match="preserve history"):
        _elimination(history_preserving=False)
    with pytest.raises(ObligationError, match="model-free"):
        _elimination(model_free=False)
    with pytest.raises(ObligationError, match="unknown equivalence elimination field"):
        PlanEquivalenceElimination.from_dict(
            {**_elimination().to_dict(), "policy_pointer": "forbidden"}
        )
    with pytest.raises(ObligationError, match="operational authority field"):
        PlanEquivalenceElimination.from_dict(
            {**_elimination().to_dict(), "lease_id": "lease:x"}
        )
    with pytest.raises(ObligationError, match="operational authority field"):
        PlanEquivalenceElimination.from_dict(
            {**_elimination().to_dict(), "admission_receipt_cid": "cid:x"}
        )
    with pytest.raises(ObligationError, match="operational authority field"):
        PlanEquivalenceElimination.from_dict(
            {**_elimination().to_dict(), "self_granted_elimination": True}
        )
    with pytest.raises(ObligationError, match="base_plan_revision"):
        _elimination(base_plan_revision="")


def test_existing_plan_terms_delta_assume_guarantee_and_obligations_remain_required() -> None:
    terms = PlanTerms(
        assumptions=("Dependencies provide current admitted receipts.",),
        guarantees=("Equivalent-task and equivalent-plan elimination stay explicit.",),
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
        impacted_task_ids=("DOEP-085",),
        preserved_task_ids=("DOEP-024", "DOEP-080"),
        preserved_receipt_ids=("receipt:DOEP-024", "receipt:DOEP-080"),
        refill_task_ids=("DOEP-085",),
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
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-085"
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["plan_cid"] == receipt["plan_cid"] == PLAN_CID
    assert list(manifest["declared_outputs"]) == list(OWNER_RELATIVE_OUTPUTS)
    assert receipt["expected_outputs"] == list(OWNER_RELATIVE_OUTPUTS)
    assert manifest["completion_authoritative"] is False
    assert receipt["worker_completion_insufficient"] is True
    assert manifest["no_competing_subsystem_created"] is True
    contract = manifest["equivalence_elimination_contract"]
    assert contract["module"] == "ipfs_datasets_py.logic.external_work_plan_obligations"
    assert contract["class_name"] == "PlanEquivalenceElimination"
    assert contract["task_class"] == "EquivalentTaskClass"
    assert contract["plan_class"] == "EquivalentPlanClass"
    assert contract["schema"] == PLAN_EQUIVALENCE_ELIMINATION_SCHEMA
    assert contract["schema_version"] == PLAN_EQUIVALENCE_ELIMINATION_SCHEMA_VERSION
    assert contract["parallel_to"] == "PlanTerms"
    assert contract["competing_subsystem_created"] is False
    assert contract["operational_admission_owner"] == "ipfs_accelerate_py"
    assert contract["semantic_identity_owner"] == "ipfs_datasets_py"
    assert contract["elimination_requires_admitted_equivalence"] is True
    assert contract["history_preserving"] is True
    assert contract["model_free"] is True
    assert contract["completion_authoritative"] is False
    assert contract["entrypoints"] == [
        "eliminate_equivalent_tasks",
        "eliminate_equivalent_plans",
        "validate_plan_equivalence_elimination",
    ]
    for relative in OWNER_RELATIVE_OUTPUTS[:2]:
        assert receipt["path_digests"][relative] == _digest(DATASETS_ROOT / relative)
    assert TEST_PATH.is_file()
    assert MODULE_PATH.is_file()
