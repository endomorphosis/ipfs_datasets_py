"""Independent current-tree tests for DOEP-026 residual interpretation.

A worker or model assertion alone is insufficient. This module verifies the
plan-bound declared outputs, datasets-owned logic-constrained residual
interpretation carrier, and candidate receipt schema required by DOEP-PLAN-V5.
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

from ipfs_datasets_py.logic.intent_ir.schema import (  # noqa: E402
    DETERMINISTIC_NORMALIZATION_SCHEMA,
    INTENT_IR_SCHEMA_VERSION,
    LOGIC_CONSTRAINED_RESIDUAL_ANSWER_SCHEMA,
    LOGIC_CONSTRAINED_RESIDUAL_ANSWER_SCHEMA_VERSION,
    LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_AUTHORITY,
    LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_FORBIDDEN_FIELDS,
    LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_MAX_ANSWERS,
    LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_SCHEMA,
    LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_SCHEMA_VERSION,
    LOGIC_CONSTRAINED_RESIDUAL_INTERPRETER_ID,
    LOGIC_CONSTRAINED_RESIDUAL_INTERPRETER_VERSION,
    RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA,
    SUPERVISOR_OBJECTIVE_INTENT_SCHEMA,
    UNRESOLVED_QUESTION_CAPTURE_SCHEMA,
    UNRESOLVED_QUESTION_SCHEMA,
    AdmissibleDecisionImpact,
    DeterministicObjectiveNormalization,
    IntentIRDocument,
    IntentIRValidationError,
    KnownObjectiveClass,
    LogicConstrainedResidualAnswer,
    LogicConstrainedResidualInterpretation,
    MinimumSpecialistCapability,
    RuleDrivenObjectiveDecomposition,
    SupervisorObjectiveIntent,
    SupervisorObjectiveSubmitterKind,
    UnresolvedQuestion,
    UnresolvedQuestionCapture,
    build_logic_constrained_residual_answer,
    build_unresolved_question,
    capture_unresolved_semantic_questions,
    decompose_supervisor_objective_by_rules,
    idea_text_sha256,
    interpret_logic_constrained_residuals,
    normalize_supervisor_objective_deterministically,
    validate_logic_constrained_residual_answer,
    validate_logic_constrained_residual_interpretation,
)

SCHEMA_PATH = (
    DATASETS_ROOT / "ipfs_datasets_py" / "logic" / "intent_ir" / "schema.py"
)
TEST_PATH = Path(__file__).resolve()
OUTPUT_PATH = (
    DATASETS_ROOT
    / "artifacts"
    / "agent_supervisor_direct_objective_event_driven_planning"
    / "outputs"
    / "DOEP-026.json"
)
RECEIPT_PATH = (
    DATASETS_ROOT
    / "artifacts"
    / "agent_supervisor_direct_objective_event_driven_planning"
    / "receipts"
    / "DOEP-026.json"
)

OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/intent_ir/schema.py",
    "tests/doep/test_doep_026_add_logic_constrained_residual_interpretation.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-026.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-026.json",
)

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

OWNERSHIP = {
    "canonical_semantic_identity": "ipfs_datasets_py",
    "ducklake_authority": False,
    "exact_bytes_cid_storage": "ipfs_kit_py",
    "model_output_is_completion_authority": False,
    "operational_admission": "ipfs_accelerate_py",
}

TASK_CID = "sha256:4ab35f3d7e16a40e9c3ca9447929d149d79c54daf9f62ff955a45b37cea2c3fc"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{path} root must be an object"
    return payload


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _minimal_intent(**overrides: Any) -> SupervisorObjectiveIntent:
    idea = "Submit one bounded high-level idea to the existing supervisor."
    values: dict[str, Any] = {
        "intent_id": "doep.objective.intent.example",
        "idea_text": idea,
        "idea_sha256": idea_text_sha256(idea),
        "submitter_kind": SupervisorObjectiveSubmitterKind.HUMAN,
        "caller": "caller:example-principal",
        "repository_id": "repository:sha256:example",
        "board_namespace": "agent-supervisor-direct-objective-and-event-driven-planning-v1",
        "title_hint": " Example direct objective ",
        "tags": ("contract", "direct-objective", "doep"),
    }
    values.update(overrides)
    return SupervisorObjectiveIntent(**values)


def _minimal_normalization(**overrides: Any) -> DeterministicObjectiveNormalization:
    intent = overrides.pop("intent", None) or _minimal_intent()
    values: dict[str, Any] = {
        "scope_paths": (
            "ipfs_datasets_py/logic/intent_ir/schema.py",
            "tests/doep",
        ),
        "proposed_budget_profile": "B2",
        "proposed_risk_class": "R2",
        "policy_binding": "policy:implementation-daemon",
    }
    values.update(overrides)
    return normalize_supervisor_objective_deterministically(intent, **values)


def _explicit_question(**overrides: Any) -> UnresolvedQuestion:
    values: dict[str, Any] = {
        "exact_question": "Which bounded route should resolve the residual semantic gap?",
        "why_prior_deterministic_stages_could_not_resolve": (
            "Rule and template stages left two admissible interpretations."
        ),
        "evidence_available": ("current schema", "selected test receipt"),
        "evidence_missing": ("authoritative residual interpretation",),
        "candidate_decisions_answer_could_change": (
            AdmissibleDecisionImpact.SMALL_LOCAL_MODEL.value,
            AdmissibleDecisionImpact.MEDIUM_MODEL.value,
        ),
        "minimum_specialist_capability": (
            MinimumSpecialistCapability.LOCAL_SMALL_SPECIALIST.value
        ),
        "response_enum": ("narrow", "broad"),
        "context_budget": 4096,
    }
    values.update(overrides)
    return build_unresolved_question(**values)


def _residual_capture(**overrides: Any) -> UnresolvedQuestionCapture:
    normalization = overrides.pop("normalization", None) or _minimal_normalization()
    questions = overrides.pop("questions", None)
    if questions is None:
        questions = (_explicit_question(),)
    return capture_unresolved_semantic_questions(
        normalization,
        questions=questions,
        **overrides,
    )


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        path = DATASETS_ROOT / relative
        assert path.is_file(), f"missing declared output: {relative}"
    assert SCHEMA_PATH.is_file()
    assert TEST_PATH.is_file()
    assert OUTPUT_PATH.is_file()
    assert RECEIPT_PATH.is_file()


def test_residual_interpretation_symbols_extend_canonical_schema_without_competing_subsystem() -> None:
    assert LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_SCHEMA == (
        "ipfs_datasets_py/logic/intent-ir/logic-constrained-residual-interpretation@1"
    )
    assert (
        LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_SCHEMA_VERSION
        == "logic-constrained-residual-interpretation/v1"
    )
    assert LOGIC_CONSTRAINED_RESIDUAL_ANSWER_SCHEMA == (
        "ipfs_datasets_py/logic/intent-ir/logic-constrained-residual-answer@1"
    )
    assert (
        LOGIC_CONSTRAINED_RESIDUAL_ANSWER_SCHEMA_VERSION
        == "logic-constrained-residual-answer/v1"
    )
    assert LOGIC_CONSTRAINED_RESIDUAL_INTERPRETER_ID == (
        "ipfs_datasets_py/logic/intent-ir/logic-constrained-residual-interpreter@1"
    )
    assert LOGIC_CONSTRAINED_RESIDUAL_INTERPRETER_VERSION == "1"
    assert LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_AUTHORITY == "semantic_only"
    assert LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_MAX_ANSWERS == 16
    assert INTENT_IR_SCHEMA_VERSION == "intent-ir/v1"
    assert SUPERVISOR_OBJECTIVE_INTENT_SCHEMA.startswith(
        "ipfs_datasets_py/logic/intent-ir/"
    )
    assert DETERMINISTIC_NORMALIZATION_SCHEMA.startswith(
        "ipfs_datasets_py/logic/intent-ir/"
    )
    assert RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA.startswith(
        "ipfs_datasets_py/logic/intent-ir/"
    )
    assert UNRESOLVED_QUESTION_SCHEMA.startswith("ipfs_datasets_py/logic/intent-ir/")
    assert UNRESOLVED_QUESTION_CAPTURE_SCHEMA.startswith(
        "ipfs_datasets_py/logic/intent-ir/"
    )
    assert issubclass(LogicConstrainedResidualAnswer, object)
    assert issubclass(LogicConstrainedResidualInterpretation, object)
    assert not issubclass(LogicConstrainedResidualAnswer, IntentIRDocument)
    assert not issubclass(LogicConstrainedResidualInterpretation, IntentIRDocument)
    assert not issubclass(
        LogicConstrainedResidualInterpretation, UnresolvedQuestionCapture
    )
    assert not issubclass(
        LogicConstrainedResidualInterpretation, RuleDrivenObjectiveDecomposition
    )
    assert not issubclass(
        LogicConstrainedResidualInterpretation, DeterministicObjectiveNormalization
    )
    source = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "class LogicConstrainedResidualAnswer" in source
    assert "class LogicConstrainedResidualInterpretation" in source
    assert "def interpret_logic_constrained_residuals" in source
    assert "def build_logic_constrained_residual_answer" in source
    assert "class UnresolvedQuestionCapture" in source
    assert "class RuleDrivenObjectiveDecomposition" in source
    assert "class DeterministicObjectiveNormalization" in source
    assert "class IntentIRDocument" in source
    lowered = source.lower()
    assert "competing" in lowered or "not a second" in lowered
    assert "does not" in lowered and (
        "dispatch" in lowered or "execute tools" in lowered or "authorize" in lowered
    )
    assert "semantic-only" in lowered or "semantic_only" in lowered
    assert "logic-constrained" in lowered or "logic_constrained" in lowered


def test_build_and_validate_are_deterministic_and_forbid_tool_execution() -> None:
    question = _explicit_question()
    first = build_logic_constrained_residual_answer(
        question=question,
        selected_answer="broad",
    )
    second = build_logic_constrained_residual_answer(
        question=question,
        selected_answer="broad",
    )
    assert first.to_dict() == second.to_dict()
    assert first.schema == LOGIC_CONSTRAINED_RESIDUAL_ANSWER_SCHEMA
    assert first.authority == LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_AUTHORITY
    assert first.is_completion_authority is False
    assert first.can_execute_tools is False
    assert first.callers_supply_authoritative_policy is False
    assert first.question_id == question.question_id
    assert first.selected_answer == "broad"
    payload = first.to_dict()
    round_trip = LogicConstrainedResidualAnswer.from_dict(payload)
    assert validate_logic_constrained_residual_answer(
        round_trip, allowed_answers=question.response_enum
    ).to_dict() == payload
    with pytest.raises(IntentIRValidationError, match="outside the question"):
        build_logic_constrained_residual_answer(
            question=question,
            selected_answer="unbounded_freeform",
        )
    with pytest.raises(IntentIRValidationError, match="cannot execute tools"):
        LogicConstrainedResidualAnswer.from_dict({**payload, "can_execute_tools": True})
    with pytest.raises(IntentIRValidationError, match="forbids authoritative/tool"):
        LogicConstrainedResidualAnswer.from_dict({**payload, "tool_calls": []})
    with pytest.raises(IntentIRValidationError, match="forbids authoritative/tool"):
        LogicConstrainedResidualAnswer.from_dict({**payload, "freeform_answer": "x"})


def test_interpret_binds_capture_and_enforces_closed_enum_coverage() -> None:
    normalization = _minimal_normalization()
    capture = _residual_capture(normalization=normalization)
    interpreted = interpret_logic_constrained_residuals(
        normalization,
        question_capture=capture,
        answers=(
            {
                "question_id": capture.questions[0].question_id,
                "selected_answer": "narrow",
            },
        ),
        available_capability_ids=("capability:analysis", "capability:schema"),
        repository_analysis_cid="analysis:sha256:example",
    )
    assert interpreted.schema == LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_SCHEMA
    assert interpreted.authority == LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_AUTHORITY
    assert interpreted.is_completion_authority is False
    assert interpreted.can_execute_tools is False
    assert interpreted.interpreter_id == LOGIC_CONSTRAINED_RESIDUAL_INTERPRETER_ID
    assert interpreted.interpreter_version == LOGIC_CONSTRAINED_RESIDUAL_INTERPRETER_VERSION
    assert interpreted.intent_id == normalization.intent_id
    assert interpreted.idea_sha256 == normalization.idea_sha256
    assert interpreted.intent_sha256 == normalization.intent_sha256
    assert interpreted.normalization_sha256 == normalization.normalization_sha256
    assert interpreted.capture_sha256 == capture.capture_sha256
    assert interpreted.repository_id == normalization.repository_id
    assert interpreted.board_namespace == normalization.board_namespace
    assert interpreted.reason_code == "explicit_answers"
    assert interpreted.available_capability_ids == (
        "capability:analysis",
        "capability:schema",
    )
    assert interpreted.repository_analysis_cid == "analysis:sha256:example"
    assert len(interpreted.answers) == 1
    assert interpreted.answers[0].selected_answer == "narrow"
    assert interpreted.answers == tuple(
        sorted(interpreted.answers, key=lambda item: item.question_id)
    )
    payload = interpreted.to_dict()
    assert "interpretation_sha256" not in payload
    assert len(interpreted.interpretation_sha256) == 64
    restored = LogicConstrainedResidualInterpretation.from_dict(payload)
    assert (
        validate_logic_constrained_residual_interpretation(
            restored, question_capture=capture
        ).to_dict()
        == payload
    )

    matched = decompose_supervisor_objective_by_rules(
        normalization,
        objective_class=KnownObjectiveClass.DIRECT_OBJECTIVE_CONTRACT,
    )
    empty_capture = capture_unresolved_semantic_questions(
        normalization,
        decomposition=matched,
    )
    empty = interpret_logic_constrained_residuals(
        normalization,
        question_capture=empty_capture,
    )
    assert empty.answers == ()
    assert empty.reason_code == "no_residuals"
    assert empty.capture_sha256 == empty_capture.capture_sha256

    with pytest.raises(IntentIRValidationError, match="exactly once"):
        interpret_logic_constrained_residuals(
            normalization,
            question_capture=capture,
            answers=(),
        )
    with pytest.raises(IntentIRValidationError, match="outside the question"):
        interpret_logic_constrained_residuals(
            normalization,
            question_capture=capture,
            answers=((capture.questions[0].question_id, "not-in-enum"),),
        )


def test_interpret_rejects_authority_tool_and_identity_escapes() -> None:
    normalization = _minimal_normalization()
    capture = _residual_capture(normalization=normalization)
    with pytest.raises(IntentIRValidationError):
        interpret_logic_constrained_residuals(
            {**normalization.to_dict(), "policy_id": "policy:forbidden"},
            question_capture=capture,
            answers=((capture.questions[0].question_id, "narrow"),),
        )
    with pytest.raises(IntentIRValidationError):
        interpret_logic_constrained_residuals(
            {**normalization.to_dict(), "tool_calls": []},
            question_capture=capture,
            answers=((capture.questions[0].question_id, "narrow"),),
        )
    good = interpret_logic_constrained_residuals(
        normalization,
        question_capture=capture,
        answers=((capture.questions[0].question_id, "broad"),),
    )
    with pytest.raises(IntentIRValidationError, match="cannot claim authority"):
        LogicConstrainedResidualInterpretation.from_dict(
            {**good.to_dict(), "authority": "admitted"}
        )
    with pytest.raises(IntentIRValidationError, match="forbids authoritative/tool"):
        LogicConstrainedResidualInterpretation.from_dict(
            {**good.to_dict(), "completion_authoritative": True}
        )
    with pytest.raises(IntentIRValidationError, match="does not match"):
        validate_logic_constrained_residual_interpretation(
            {
                **good.to_dict(),
                "capture_sha256": "0" * 64,
            },
            question_capture=capture,
        )
    fields = {
        item.name for item in dataclasses.fields(LogicConstrainedResidualInterpretation)
    }
    assert fields.isdisjoint(LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_FORBIDDEN_FIELDS)
    assert {
        "policy_id",
        "lease_id",
        "terminalize",
        "tool_calls",
        "dispatch_now",
        "completion_authoritative",
        "freeform_answer",
    } <= LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_FORBIDDEN_FIELDS


def test_output_manifest_contract() -> None:
    manifest = _load_json(OUTPUT_PATH)
    assert manifest["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-output@1"
    assert manifest["task_id"] == "DOEP-026"
    assert manifest["plan_revision"] == "DOEP-PLAN-V5"
    assert manifest["plan_cid"] == PLAN_CID
    assert (
        manifest["board_namespace"]
        == "agent-supervisor-direct-objective-and-event-driven-planning-v1"
    )
    assert manifest["completion_authoritative"] is False
    assert manifest["worker_completion_insufficient"] is True
    assert manifest["no_competing_subsystem_created"] is True
    assert manifest["primary_output"] == OWNER_RELATIVE_OUTPUTS[0]
    assert list(manifest["declared_outputs"]) == list(OWNER_RELATIVE_OUTPUTS)
    assert manifest["base_repositories"] == BASE_REPOSITORIES
    assert manifest["task_cid"] == TASK_CID
    assert manifest["validation_profile"] == "doep-validation/DOEP-PLAN-V5/DOEP-026@1"
    assert manifest["owning_repository"] == "ipfs_datasets_py"
    assert manifest["goal_id"] == "DOEP-G030.S2"
    assert manifest["parent_goal_id"] == "DOEP-G030"
    assert manifest["root_goal_id"] == "DOEP-G000"
    assert manifest["title"] == "Add logic-constrained residual interpretation"

    ownership = manifest["cross_repository_ownership"]
    for key, value in OWNERSHIP.items():
        assert ownership[key] == value

    contract = manifest["logic_constrained_residual_interpretation_contract"]
    assert contract == {
        "answer_builder": "build_logic_constrained_residual_answer",
        "answer_class_name": "LogicConstrainedResidualAnswer",
        "answer_schema": LOGIC_CONSTRAINED_RESIDUAL_ANSWER_SCHEMA,
        "answer_schema_version": LOGIC_CONSTRAINED_RESIDUAL_ANSWER_SCHEMA_VERSION,
        "authority": LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_AUTHORITY,
        "class_name": "LogicConstrainedResidualInterpretation",
        "competing_subsystem_created": False,
        "entrypoint": "interpret_logic_constrained_residuals",
        "interpreter_id": LOGIC_CONSTRAINED_RESIDUAL_INTERPRETER_ID,
        "interpreter_version": LOGIC_CONSTRAINED_RESIDUAL_INTERPRETER_VERSION,
        "maximum_answers": LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_MAX_ANSWERS,
        "module": "ipfs_datasets_py.logic.intent_ir.schema",
        "operational_admission_owner": "ipfs_accelerate_py",
        "parallel_to": "UnresolvedQuestionCapture",
        "schema": LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_SCHEMA,
        "schema_version": LOGIC_CONSTRAINED_RESIDUAL_INTERPRETATION_SCHEMA_VERSION,
        "semantic_identity_owner": "ipfs_datasets_py",
        "typed_output_can_execute_tools": False,
    }


def test_candidate_receipt_contract() -> None:
    receipt = _load_json(RECEIPT_PATH)
    assert receipt["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-receipt@1"
    assert receipt["task_id"] == "DOEP-026"
    assert receipt["task_cid"] == TASK_CID
    assert receipt["plan_revision"] == "DOEP-PLAN-V5"
    assert receipt["plan_cid"] == PLAN_CID
    assert (
        receipt["board_namespace"]
        == "agent-supervisor-direct-objective-and-event-driven-planning-v1"
    )
    assert receipt["candidate_status"] == "implemented"
    assert receipt["completion_authoritative"] is False
    assert receipt["worker_completion_insufficient"] is True
    assert receipt["no_competing_subsystem_created"] is True
    assert list(receipt["changed_paths"]) == list(OWNER_RELATIVE_OUTPUTS)
    assert list(receipt["write_scope"]) == list(OWNER_RELATIVE_OUTPUTS)
    assert list(receipt["expected_outputs"]) == list(OWNER_RELATIVE_OUTPUTS)
    assert receipt["goal_id"] == "DOEP-G030.S2"
    assert receipt["parent_goal_id"] == "DOEP-G030"
    assert receipt["root_goal_id"] == "DOEP-G000"
    assert receipt["title"] == "Add logic-constrained residual interpretation"

    outputs_present = receipt["outputs_present"]
    assert isinstance(outputs_present, dict)
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert outputs_present.get(relative) is True

    evidence = receipt["required_evidence"]
    assert isinstance(evidence, dict)
    assert evidence["source_commit_tree_gitlinks"] == BASE_REPOSITORIES
    assert isinstance(evidence["changed_path_digest"], str)
    assert evidence["changed_path_digest"].startswith("sha256:")
    assert evidence["test_proof_results"]["validation_command"] == [
        "python3",
        "-m",
        "pytest",
        "tests/doep/test_doep_026_add_logic_constrained_residual_interpretation.py",
        "-q",
    ]
    assert isinstance(evidence["limitations"], list) and evidence["limitations"]
    assert evidence["verifier_admission"] == "pending_independent_fenced_supervisor"
    assert evidence["receipt_cid"]["status"] == "unavailable"

    authority = receipt["authority"]
    assert authority["ducklake_authority"] is False
    assert authority["model_output_is_completion_authority"] is False
    assert authority["canonical_semantic_identity"] == "ipfs_datasets_py"
    assert authority["exact_bytes_cid_storage"] == "ipfs_kit_py"
    assert authority["operational_admission"] == "ipfs_accelerate_py"

    assert receipt["supervisor_acceptance"]["state"] == (
        "pending_independent_fenced_supervisor"
    )
    assert receipt["supervisor_acceptance"]["completion_authoritative"] is False
    assert receipt["validation"]["commands"][0]["cwd"] == "external/ipfs_datasets"


def test_changed_path_digest_matches_current_files() -> None:
    """Digest non-receipt declared outputs; the receipt embeds those digests."""
    receipt = _load_json(RECEIPT_PATH)
    digested_paths = [
        relative
        for relative in OWNER_RELATIVE_OUTPUTS
        if not relative.endswith("/receipts/DOEP-026.json")
    ]
    digests = {
        relative: _sha256_file(DATASETS_ROOT / relative) for relative in digested_paths
    }
    canonical = json.dumps(digests, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert receipt["required_evidence"]["changed_path_digest"] == expected
    assert receipt["path_digests"] == digests
