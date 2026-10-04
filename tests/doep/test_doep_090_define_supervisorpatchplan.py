"""Independent current-tree tests for DOEP-090 SupervisorPatchPlan.

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
    PATCH_EDIT_OPERATIONS,
    PATCH_PLAN_KINDS,
    PATCH_SYNTHESIS_ORIGINS,
    PLAN_ASSUME_GUARANTEE_SCHEMA,
    PLAN_DELTA_SCHEMA,
    PLAN_EQUIVALENCE_ELIMINATION_SCHEMA,
    SUPERVISOR_PATCH_PLAN_FORBIDDEN_FIELDS,
    SUPERVISOR_PATCH_PLAN_SCHEMA,
    SUPERVISOR_PATCH_PLAN_SCHEMA_VERSION,
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
    SupervisorPatchEdit,
    SupervisorPatchPlan,
    declared_supervisor_patch_scope,
    prove,
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
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-090.json"
)
RECEIPT_PATH = (
    DATASETS_ROOT
    / "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-090.json"
)
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/external_work_plan_obligations.py",
    "tests/doep/test_doep_090_define_supervisorpatchplan.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-090.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-090.json",
)
TASK_CID = "sha256:5229e3dfff281ca24ffc0bbc4f074f19c2a768fc359a56e1084ab1e5fe908c7e"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"


def _load_json(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _edit(**overrides: Any) -> SupervisorPatchEdit:
    values: dict[str, Any] = {
        "edit_id": "edit:named-contract",
        "path": "ipfs_datasets_py/logic/external_work_plan_obligations.py",
        "operation": "replace",
        "intent": "Name SupervisorPatchPlan without relocating operational admission.",
    }
    values.update(overrides)
    return SupervisorPatchEdit(**values)


def _acceptance(**overrides: Any) -> AcceptanceCondition:
    values: dict[str, Any] = {
        "condition_id": "tests-pass",
        "description": "The selected current-tree tests pass.",
        "verification_method": "independent pytest",
    }
    values.update(overrides)
    return AcceptanceCondition(**values)


def _plan(**overrides: Any) -> SupervisorPatchPlan:
    values: dict[str, Any] = {
        "patch_plan_id": "patch:DOEP-090",
        "base_plan_revision": "DOEP-PLAN-V5",
        "task_id": "DOEP-090",
        "context_pack_id": "contextpack:DOEP-060",
        "kind": "typed_edit",
        "synthesis_origin": "deterministic_allowlist",
        "target_paths": (
            "ipfs_datasets_py/logic/external_work_plan_obligations.py",
        ),
        "edits": (_edit(),),
        "acceptance_conditions": (_acceptance(),),
    }
    values.update(overrides)
    return SupervisorPatchPlan(**values)


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_supervisor_patch_plan_extends_obligation_layer_without_competing_subsystem() -> None:
    assert SUPERVISOR_PATCH_PLAN_SCHEMA == (
        "ipfs_datasets_py/logic/external-work-plan-supervisor-patch-plan@1"
    )
    assert SUPERVISOR_PATCH_PLAN_SCHEMA_VERSION == (
        "external-work-plan-supervisor-patch-plan/v1"
    )
    assert PATCH_PLAN_KINDS == {
        "typed_edit",
        "unresolved_question",
        "no_change",
        "refusal",
    }
    assert PATCH_SYNTHESIS_ORIGINS == {
        "deterministic_allowlist",
        "bounded_model_assisted",
        "none",
    }
    assert PATCH_EDIT_OPERATIONS == {"replace", "insert", "delete"}
    assert dataclasses.is_dataclass(SupervisorPatchPlan)
    assert dataclasses.is_dataclass(SupervisorPatchEdit)
    assert not issubclass(SupervisorPatchPlan, PlanObligation)
    assert not issubclass(SupervisorPatchPlan, PlanTerms)
    assert not issubclass(SupervisorPatchPlan, PlanDelta)
    assert not issubclass(SupervisorPatchPlan, PlanAssumeGuarantee)
    assert not issubclass(SupervisorPatchPlan, PlanEquivalenceElimination)
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "not a new planner" in source
    assert "cannot grant completion authority" in source
    assert "independently verifies" in source
    assert "not a competing operational subsystem" in source
    assert "model assertion is never patch acceptance" in source
    assert "typed patch plan" in source
    assert "semantically nonempty" in source
    assert "declared scope" in source
    assert "supervisorpatchplan" in source
    assert "patchplanengine" not in source
    assert "patchplansubsystem" not in source
    assert "apply_supervisor_patch" not in source
    assert "admit_and_merge" not in source
    assert "self_granted_acceptance" in SUPERVISOR_PATCH_PLAN_FORBIDDEN_FIELDS
    assert "admission_receipt_cid" in SUPERVISOR_PATCH_PLAN_FORBIDDEN_FIELDS
    assert "lease_id" in SUPERVISOR_PATCH_PLAN_FORBIDDEN_FIELDS
    assert "applied_diff" in SUPERVISOR_PATCH_PLAN_FORBIDDEN_FIELDS
    assert "merge_decision" in SUPERVISOR_PATCH_PLAN_FORBIDDEN_FIELDS
    assert "ipfs_accelerate_py" not in MODULE_PATH.read_text(encoding="utf-8")


def test_supervisor_patch_plan_is_immutable_and_round_trips_canonically() -> None:
    plan = _plan()
    assert plan.completion_authoritative is False
    assert plan.mutation_authoritative is False
    assert plan.history_preserving is True
    assert plan.scope_bounded is True
    assert plan.semantic_nonempty is True
    assert plan.model_assertion_is_acceptance is False
    assert plan.acceptance_requires_independent_evidence is True
    payload = plan.to_dict()
    assert payload["schema"] == SUPERVISOR_PATCH_PLAN_SCHEMA
    assert payload["schema_version"] == SUPERVISOR_PATCH_PLAN_SCHEMA_VERSION
    assert payload["patch_plan_id"] == "patch:DOEP-090"
    assert payload["base_plan_revision"] == "DOEP-PLAN-V5"
    assert payload["task_id"] == "DOEP-090"
    assert payload["context_pack_id"] == "contextpack:DOEP-060"
    assert payload["kind"] == "typed_edit"
    assert payload["synthesis_origin"] == "deterministic_allowlist"
    assert payload["target_paths"] == [
        "ipfs_datasets_py/logic/external_work_plan_obligations.py"
    ]
    assert payload["edits"][0]["operation"] == "replace"
    assert payload["acceptance_conditions"][0]["verification_method"] == (
        "independent pytest"
    )
    assert validate_supervisor_patch_plan(payload).to_dict() == payload
    assert declared_supervisor_patch_scope(plan) == (
        "ipfs_datasets_py/logic/external_work_plan_obligations.py",
    )
    assert declared_supervisor_patch_scope(payload) == (
        "ipfs_datasets_py/logic/external_work_plan_obligations.py",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.edits = ()  # type: ignore[misc]


def test_typed_edit_requires_declared_scope_and_semantic_nonempty() -> None:
    with pytest.raises(ObligationError, match="declared scope"):
        _plan(target_paths=())
    with pytest.raises(ObligationError, match="at least one named edit"):
        _plan(edits=())
    with pytest.raises(ObligationError, match="semantically nonempty"):
        _plan(semantic_nonempty=False)
    with pytest.raises(ObligationError, match="independent acceptance evidence"):
        _plan(acceptance_conditions=())
    with pytest.raises(ObligationError, match="inside the declared scope"):
        _plan(
            edits=(
                _edit(path="undeclared/path.py"),
            )
        )
    with pytest.raises(ObligationError, match="deterministic-first synthesis origin"):
        _plan(synthesis_origin="none")
    with pytest.raises(ObligationError, match="scope-bounded"):
        _plan(scope_bounded=False)
    empty_scope = _plan(
        kind="refusal",
        synthesis_origin="none",
        target_paths=(),
        edits=(),
        acceptance_conditions=(),
        semantic_nonempty=False,
    )
    assert empty_scope.target_paths == ()
    assert declared_supervisor_patch_scope(empty_scope) == ()


def test_model_assertion_is_never_patch_acceptance_evidence() -> None:
    with pytest.raises(ObligationError, match="model assertion is never patch acceptance"):
        _plan(model_assertion_is_acceptance=True)
    with pytest.raises(ObligationError, match="independent verification"):
        _plan(
            acceptance_conditions=(
                _acceptance(verification_method="model assertion"),
            )
        )
    with pytest.raises(ObligationError, match="independent verification"):
        _plan(
            acceptance_conditions=(
                _acceptance(verification_method="worker assertion"),
            )
        )
    with pytest.raises(ObligationError, match="independent evidence"):
        _plan(acceptance_requires_independent_evidence=False)
    with pytest.raises(ObligationError, match="independent verification"):
        _plan(kind="model assertion")


def test_closed_kinds_and_synthesis_origins() -> None:
    refusal = _plan(
        kind="refusal",
        synthesis_origin="none",
        edits=(),
        acceptance_conditions=(),
        semantic_nonempty=False,
    )
    assert refusal.kind == "refusal"
    assert refusal.semantic_nonempty is False
    no_change = _plan(
        kind="no_change",
        synthesis_origin="none",
        edits=(),
        acceptance_conditions=(),
        semantic_nonempty=False,
    )
    assert no_change.kind == "no_change"
    question = _plan(
        kind="unresolved_question",
        synthesis_origin="none",
        edits=(),
        acceptance_conditions=(),
        semantic_nonempty=False,
    )
    assert question.kind == "unresolved_question"
    bounded = _plan(synthesis_origin="bounded_model_assisted")
    assert bounded.synthesis_origin == "bounded_model_assisted"
    with pytest.raises(ObligationError, match="unsupported patch plan kind"):
        _plan(kind="freeform_diff")
    with pytest.raises(ObligationError, match="unsupported patch synthesis origin"):
        _plan(synthesis_origin="unbounded_frontier")
    with pytest.raises(ObligationError, match="unsupported patch edit operation"):
        _edit(operation="apply")
    with pytest.raises(ObligationError, match="must not contain edits"):
        _plan(
            kind="no_change",
            synthesis_origin="none",
            semantic_nonempty=False,
        )
    with pytest.raises(ObligationError, match="must not claim semantic-nonempty"):
        _plan(
            kind="refusal",
            synthesis_origin="none",
            edits=(),
            semantic_nonempty=True,
        )
    with pytest.raises(ObligationError, match="synthesis origin must be none"):
        _plan(
            kind="refusal",
            synthesis_origin="deterministic_allowlist",
            edits=(),
            semantic_nonempty=False,
        )


def test_history_authority_and_unknown_fields_fail_closed() -> None:
    with pytest.raises(ObligationError, match="completion authority"):
        _plan(completion_authoritative=True)
    with pytest.raises(ObligationError, match="mutation authority"):
        _plan(mutation_authoritative=True)
    with pytest.raises(ObligationError, match="preserve history"):
        _plan(history_preserving=False)
    with pytest.raises(ObligationError, match="unknown supervisor patch plan field"):
        SupervisorPatchPlan.from_dict({**_plan().to_dict(), "policy_pointer": "forbidden"})
    with pytest.raises(ObligationError, match="operational authority field"):
        SupervisorPatchPlan.from_dict({**_plan().to_dict(), "lease_id": "lease:x"})
    with pytest.raises(ObligationError, match="operational authority field"):
        SupervisorPatchPlan.from_dict(
            {**_plan().to_dict(), "admission_receipt_cid": "cid:x"}
        )
    with pytest.raises(ObligationError, match="operational authority field"):
        SupervisorPatchPlan.from_dict({**_plan().to_dict(), "applied_diff": "--- a"})
    with pytest.raises(ObligationError, match="operational authority field"):
        SupervisorPatchPlan.from_dict({**_plan().to_dict(), "merge_decision": "merge"})
    with pytest.raises(ObligationError, match="operational authority field"):
        SupervisorPatchPlan.from_dict(
            {**_plan().to_dict(), "self_granted_acceptance": True}
        )
    with pytest.raises(ObligationError, match="base_plan_revision"):
        _plan(base_plan_revision="")
    with pytest.raises(ObligationError, match="patch_plan_id"):
        _plan(patch_plan_id="")
    with pytest.raises(ObligationError, match="duplicates"):
        _plan(
            target_paths=(
                "ipfs_datasets_py/logic/external_work_plan_obligations.py",
                "ipfs_datasets_py/logic/external_work_plan_obligations.py",
            )
        )
    with pytest.raises(ObligationError, match="edit IDs must be unique"):
        _plan(
            target_paths=(
                "ipfs_datasets_py/logic/external_work_plan_obligations.py",
                "tests/doep/test_doep_090_define_supervisorpatchplan.py",
            ),
            edits=(
                _edit(),
                _edit(
                    path="tests/doep/test_doep_090_define_supervisorpatchplan.py",
                    intent="Name the independent current-tree tests.",
                ),
            ),
        )


def test_existing_plan_terms_delta_assume_guarantee_equivalence_and_obligations_remain_required() -> None:
    terms = PlanTerms(
        assumptions=("Dependencies provide current admitted receipts.",),
        guarantees=("A model assertion is never patch acceptance evidence.",),
        non_goals=("This contract does not grant operational admission.",),
        acceptance_conditions=(_acceptance(),),
    )
    assert validate_plan_terms(terms).completion_authoritative is False
    delta = PlanDelta(
        base_plan_revision="DOEP-PLAN-V5",
        triggering_event_id="event:example-001",
        impacted_task_ids=("DOEP-090",),
        preserved_task_ids=("DOEP-024", "DOEP-080"),
        preserved_receipt_ids=("receipt:DOEP-024", "receipt:DOEP-080"),
        refill_task_ids=("DOEP-090",),
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
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-090"
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["plan_cid"] == receipt["plan_cid"] == PLAN_CID
    assert list(manifest["declared_outputs"]) == list(OWNER_RELATIVE_OUTPUTS)
    assert receipt["expected_outputs"] == list(OWNER_RELATIVE_OUTPUTS)
    assert manifest["completion_authoritative"] is False
    assert receipt["worker_completion_insufficient"] is True
    assert manifest["no_competing_subsystem_created"] is True
    contract = manifest["supervisor_patch_plan_contract"]
    assert contract["module"] == "ipfs_datasets_py.logic.external_work_plan_obligations"
    assert contract["class_name"] == "SupervisorPatchPlan"
    assert contract["edit_class"] == "SupervisorPatchEdit"
    assert contract["schema"] == SUPERVISOR_PATCH_PLAN_SCHEMA
    assert contract["schema_version"] == SUPERVISOR_PATCH_PLAN_SCHEMA_VERSION
    assert contract["parallel_to"] == "PlanTerms"
    assert contract["competing_subsystem_created"] is False
    assert contract["operational_admission_owner"] == "ipfs_accelerate_py"
    assert contract["semantic_identity_owner"] == "ipfs_datasets_py"
    assert contract["model_assertion_is_acceptance"] is False
    assert contract["acceptance_requires_independent_evidence"] is True
    assert contract["semantic_nonempty_required_for_typed_edit"] is True
    assert contract["scope_bounded"] is True
    assert contract["history_preserving"] is True
    assert contract["mutation_authoritative"] is False
    assert contract["completion_authoritative"] is False
    assert contract["kinds"] == sorted(PATCH_PLAN_KINDS)
    assert contract["synthesis_origins"] == sorted(PATCH_SYNTHESIS_ORIGINS)
    assert contract["entrypoints"] == [
        "declared_supervisor_patch_scope",
        "validate_supervisor_patch_plan",
    ]
    for relative in OWNER_RELATIVE_OUTPUTS[:2]:
        assert receipt["path_digests"][relative] == _digest(DATASETS_ROOT / relative)
    assert TEST_PATH.is_file()
    assert MODULE_PATH.is_file()
