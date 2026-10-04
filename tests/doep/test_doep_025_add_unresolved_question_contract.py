"""Independent current-tree tests for DOEP-025 unresolved-question contract.

A worker or model assertion alone is insufficient. This module verifies the
plan-bound declared outputs, datasets-owned unresolved-question carrier, and
candidate receipt schema required by DOEP-PLAN-V5.
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
    RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA,
    SUPERVISOR_OBJECTIVE_INTENT_SCHEMA,
    UNRESOLVED_QUESTION_AUTHORITY,
    UNRESOLVED_QUESTION_CAPTURE_ID,
    UNRESOLVED_QUESTION_CAPTURE_SCHEMA,
    UNRESOLVED_QUESTION_CAPTURE_SCHEMA_VERSION,
    UNRESOLVED_QUESTION_CAPTURE_VERSION,
    UNRESOLVED_QUESTION_FORBIDDEN_FIELDS,
    UNRESOLVED_QUESTION_MAX_CONTEXT_BUDGET,
    UNRESOLVED_QUESTION_MAX_QUESTIONS,
    UNRESOLVED_QUESTION_SCHEMA,
    UNRESOLVED_QUESTION_SCHEMA_VERSION,
    AdmissibleDecisionImpact,
    DeterministicObjectiveNormalization,
    IntentIRDocument,
    IntentIRValidationError,
    KnownObjectiveClass,
    MinimumSpecialistCapability,
    RuleDrivenObjectiveDecomposition,
    SupervisorObjectiveIntent,
    SupervisorObjectiveSubmitterKind,
    UnresolvedQuestion,
    UnresolvedQuestionCapture,
    build_unresolved_question,
    capture_unresolved_semantic_questions,
    decompose_supervisor_objective_by_rules,
    idea_text_sha256,
    normalize_supervisor_objective_deterministically,
    validate_unresolved_question,
    validate_unresolved_question_capture,
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
    / "DOEP-025.json"
)
RECEIPT_PATH = (
    DATASETS_ROOT
    / "artifacts"
    / "agent_supervisor_direct_objective_event_driven_planning"
    / "receipts"
    / "DOEP-025.json"
)

OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/intent_ir/schema.py",
    "tests/doep/test_doep_025_add_unresolved_question_contract.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-025.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-025.json",
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

TASK_CID = "sha256:6ab3d7038c0788ea08421a7c03f90eecbc0292245276becadd9cad5808f6d381"
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


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        path = DATASETS_ROOT / relative
        assert path.is_file(), f"missing declared output: {relative}"
    assert SCHEMA_PATH.is_file()
    assert TEST_PATH.is_file()
    assert OUTPUT_PATH.is_file()
    assert RECEIPT_PATH.is_file()


def test_unresolved_question_symbols_extend_canonical_schema_without_competing_subsystem() -> None:
    assert UNRESOLVED_QUESTION_SCHEMA == (
        "ipfs_datasets_py/logic/intent-ir/unresolved-question@1"
    )
    assert UNRESOLVED_QUESTION_SCHEMA_VERSION == "unresolved-question/v1"
    assert UNRESOLVED_QUESTION_CAPTURE_SCHEMA == (
        "ipfs_datasets_py/logic/intent-ir/unresolved-question-capture@1"
    )
    assert (
        UNRESOLVED_QUESTION_CAPTURE_SCHEMA_VERSION
        == "unresolved-question-capture/v1"
    )
    assert UNRESOLVED_QUESTION_CAPTURE_ID == (
        "ipfs_datasets_py/logic/intent-ir/unresolved-question-capture@1"
    )
    assert UNRESOLVED_QUESTION_CAPTURE_VERSION == "1"
    assert UNRESOLVED_QUESTION_AUTHORITY == "semantic_only"
    assert UNRESOLVED_QUESTION_MAX_QUESTIONS == 16
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
    assert issubclass(UnresolvedQuestion, object)
    assert issubclass(UnresolvedQuestionCapture, object)
    assert not issubclass(UnresolvedQuestion, IntentIRDocument)
    assert not issubclass(UnresolvedQuestionCapture, IntentIRDocument)
    assert not issubclass(UnresolvedQuestionCapture, SupervisorObjectiveIntent)
    assert not issubclass(
        UnresolvedQuestionCapture, DeterministicObjectiveNormalization
    )
    assert not issubclass(
        UnresolvedQuestionCapture, RuleDrivenObjectiveDecomposition
    )
    source = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "class UnresolvedQuestion" in source
    assert "class UnresolvedQuestionCapture" in source
    assert "def capture_unresolved_semantic_questions" in source
    assert "def build_unresolved_question" in source
    assert "class DeterministicObjectiveNormalization" in source
    assert "class RuleDrivenObjectiveDecomposition" in source
    assert "class SupervisorObjectiveIntent" in source
    assert "class IntentIRDocument" in source
    lowered = source.lower()
    assert "competing" in lowered or "not a second" in lowered
    assert "does not" in lowered and (
        "authorize" in lowered or "dispatch" in lowered or "execute tools" in lowered
    )
    assert "semantic-only" in lowered or "semantic_only" in lowered


def test_build_and_validate_are_deterministic_and_forbid_tool_execution() -> None:
    first = _explicit_question(
        evidence_available=("selected test receipt", "current schema"),
        response_enum=("broad", "narrow"),
    )
    second = _explicit_question(
        evidence_available=("current schema", "selected test receipt"),
        response_enum=("narrow", "broad"),
    )
    assert first.to_dict() == second.to_dict()
    assert first.schema == UNRESOLVED_QUESTION_SCHEMA
    assert first.authority == UNRESOLVED_QUESTION_AUTHORITY
    assert first.is_completion_authority is False
    assert first.can_execute_tools is False
    assert first.callers_supply_authoritative_policy is False
    assert first.question_id.startswith("sha256:")
    assert first.response_schema == {"type": "string", "enum": ["broad", "narrow"]}
    payload = first.to_dict()
    round_trip = UnresolvedQuestion.from_dict(payload)
    assert validate_unresolved_question(round_trip).to_dict() == payload
    with pytest.raises(IntentIRValidationError, match="provided question_id"):
        _explicit_question(question_id="sha256:" + ("f" * 64))
    with pytest.raises(IntentIRValidationError, match="cannot execute tools"):
        UnresolvedQuestion.from_dict({**payload, "can_execute_tools": True})
    with pytest.raises(IntentIRValidationError, match="forbids authoritative/tool"):
        UnresolvedQuestion.from_dict({**payload, "tool_calls": []})
    with pytest.raises(IntentIRValidationError, match="forbids authoritative/tool"):
        UnresolvedQuestion.from_dict({**payload, "dispatch_now": True})


def test_capture_binds_normalization_and_derives_residual_questions() -> None:
    normalization = _minimal_normalization(
        intent=_minimal_intent(tags=("doep",)),
    )
    unknown = decompose_supervisor_objective_by_rules(
        normalization,
        objective_class=KnownObjectiveClass.UNKNOWN,
    )
    derived = capture_unresolved_semantic_questions(
        normalization,
        decomposition=unknown,
    )
    assert derived.schema == UNRESOLVED_QUESTION_CAPTURE_SCHEMA
    assert derived.authority == UNRESOLVED_QUESTION_AUTHORITY
    assert derived.is_completion_authority is False
    assert derived.can_execute_tools is False
    assert derived.capture_id == UNRESOLVED_QUESTION_CAPTURE_ID
    assert derived.capture_version == UNRESOLVED_QUESTION_CAPTURE_VERSION
    assert derived.intent_id == normalization.intent_id
    assert derived.idea_sha256 == normalization.idea_sha256
    assert derived.intent_sha256 == normalization.intent_sha256
    assert derived.normalization_sha256 == normalization.normalization_sha256
    assert derived.decomposition_sha256 == unknown.decomposition_sha256
    assert derived.repository_id == normalization.repository_id
    assert derived.board_namespace == normalization.board_namespace
    assert derived.reason_code.startswith("derived_from_decomposition:")
    assert len(derived.questions) == 1
    assert derived.questions[0].minimum_specialist_capability in {
        item.value for item in MinimumSpecialistCapability
    }
    assert derived.questions == tuple(
        sorted(derived.questions, key=lambda item: item.question_id)
    )
    payload = derived.to_dict()
    assert "capture_sha256" not in payload
    assert len(derived.capture_sha256) == 64
    restored = UnresolvedQuestionCapture.from_dict(payload)
    assert validate_unresolved_question_capture(restored).to_dict() == payload

    matched = decompose_supervisor_objective_by_rules(
        _minimal_normalization(),
        objective_class=KnownObjectiveClass.DIRECT_OBJECTIVE_CONTRACT,
    )
    empty = capture_unresolved_semantic_questions(
        _minimal_normalization(),
        decomposition=matched,
    )
    assert empty.questions == ()
    assert empty.reason_code == "no_unresolved_questions"

    explicit = capture_unresolved_semantic_questions(
        normalization,
        questions=(_explicit_question(),),
        context_pack_hint="contextpack:sha256:example",
    )
    assert explicit.reason_code == "explicit_questions"
    assert len(explicit.questions) == 1
    assert explicit.questions[0].context_pack_hint == "contextpack:sha256:example"


def test_capture_rejects_authority_tool_and_identity_escapes() -> None:
    normalization = _minimal_normalization()
    with pytest.raises(IntentIRValidationError):
        capture_unresolved_semantic_questions(
            {**normalization.to_dict(), "policy_id": "policy:forbidden"}
        )
    with pytest.raises(IntentIRValidationError):
        capture_unresolved_semantic_questions(
            {**normalization.to_dict(), "tool_calls": []}
        )
    question = _explicit_question()
    with pytest.raises(IntentIRValidationError, match="does not match"):
        validate_unresolved_question(
            {
                **question.to_dict(),
                "exact_question": "Could the residual route be changed?",
            }
        )
    with pytest.raises(IntentIRValidationError, match="must not overlap"):
        _explicit_question(evidence_missing=("current schema",))
    with pytest.raises(IntentIRValidationError, match="admissible decisions"):
        _explicit_question(candidate_decisions_answer_could_change=("small_local_model",))
    with pytest.raises(IntentIRValidationError):
        _explicit_question(context_budget=0)
    with pytest.raises(IntentIRValidationError):
        _explicit_question(context_budget=UNRESOLVED_QUESTION_MAX_CONTEXT_BUDGET + 1)
    with pytest.raises(IntentIRValidationError, match="cannot claim authority"):
        UnresolvedQuestionCapture.from_dict(
            {
                **capture_unresolved_semantic_questions(
                    normalization, questions=(question,)
                ).to_dict(),
                "authority": "admitted",
            }
        )
    with pytest.raises(IntentIRValidationError, match="forbids authoritative/tool"):
        UnresolvedQuestionCapture.from_dict(
            {
                **capture_unresolved_semantic_questions(
                    normalization, questions=(question,)
                ).to_dict(),
                "completion_authoritative": True,
            }
        )
    fields = {item.name for item in dataclasses.fields(UnresolvedQuestionCapture)}
    assert fields.isdisjoint(UNRESOLVED_QUESTION_FORBIDDEN_FIELDS)
    assert {
        "policy_id",
        "lease_id",
        "terminalize",
        "tool_calls",
        "dispatch_now",
        "completion_authoritative",
    } <= UNRESOLVED_QUESTION_FORBIDDEN_FIELDS


def test_output_manifest_contract() -> None:
    manifest = _load_json(OUTPUT_PATH)
    assert manifest["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-output@1"
    assert manifest["task_id"] == "DOEP-025"
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
    assert manifest["validation_profile"] == "doep-validation/DOEP-PLAN-V5/DOEP-025@1"
    assert manifest["owning_repository"] == "ipfs_datasets_py"
    assert manifest["goal_id"] == "DOEP-G030.S2"
    assert manifest["parent_goal_id"] == "DOEP-G030"
    assert manifest["root_goal_id"] == "DOEP-G000"
    assert manifest["title"] == "Add unresolved-question contract"

    ownership = manifest["cross_repository_ownership"]
    for key, value in OWNERSHIP.items():
        assert ownership[key] == value

    contract = manifest["unresolved_question_contract"]
    assert contract == {
        "authority": UNRESOLVED_QUESTION_AUTHORITY,
        "capture_class_name": "UnresolvedQuestionCapture",
        "capture_id": UNRESOLVED_QUESTION_CAPTURE_ID,
        "capture_schema": UNRESOLVED_QUESTION_CAPTURE_SCHEMA,
        "capture_schema_version": UNRESOLVED_QUESTION_CAPTURE_SCHEMA_VERSION,
        "capture_version": UNRESOLVED_QUESTION_CAPTURE_VERSION,
        "class_name": "UnresolvedQuestion",
        "competing_subsystem_created": False,
        "entrypoint": "capture_unresolved_semantic_questions",
        "maximum_questions": UNRESOLVED_QUESTION_MAX_QUESTIONS,
        "module": "ipfs_datasets_py.logic.intent_ir.schema",
        "operational_admission_owner": "ipfs_accelerate_py",
        "parallel_to": "RuleDrivenObjectiveDecomposition",
        "question_builder": "build_unresolved_question",
        "schema": UNRESOLVED_QUESTION_SCHEMA,
        "schema_version": UNRESOLVED_QUESTION_SCHEMA_VERSION,
        "semantic_identity_owner": "ipfs_datasets_py",
        "typed_output_can_execute_tools": False,
    }


def test_candidate_receipt_contract() -> None:
    receipt = _load_json(RECEIPT_PATH)
    assert receipt["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-receipt@1"
    assert receipt["task_id"] == "DOEP-025"
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
    assert receipt["title"] == "Add unresolved-question contract"

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
        "tests/doep/test_doep_025_add_unresolved_question_contract.py",
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
        if not relative.endswith("/receipts/DOEP-025.json")
    ]
    digests = {
        relative: _sha256_file(DATASETS_ROOT / relative) for relative in digested_paths
    }
    canonical = json.dumps(digests, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert receipt["required_evidence"]["changed_path_digest"] == expected
    assert receipt["path_digests"] == digests
