"""Independent current-tree tests for DOEP-010 SupervisorObjectiveIntent.

A worker or model assertion alone is insufficient. This module verifies the
plan-bound declared outputs, datasets-owned contract symbols, and candidate
receipt schema required by DOEP-PLAN-V5.
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
    INTENT_IR_SCHEMA_VERSION,
    SUPERVISOR_OBJECTIVE_INTENT_FORBIDDEN_FIELDS,
    SUPERVISOR_OBJECTIVE_INTENT_MAX_IDEA_UTF8_BYTES,
    SUPERVISOR_OBJECTIVE_INTENT_SCHEMA,
    SUPERVISOR_OBJECTIVE_INTENT_SCHEMA_VERSION,
    IntentIRDocument,
    IntentIRValidationError,
    SupervisorObjectiveIntent,
    SupervisorObjectiveSubmitterKind,
    idea_text_sha256,
    validate_supervisor_objective_intent,
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
    / "DOEP-010.json"
)
RECEIPT_PATH = (
    DATASETS_ROOT
    / "artifacts"
    / "agent_supervisor_direct_objective_event_driven_planning"
    / "receipts"
    / "DOEP-010.json"
)

OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/intent_ir/schema.py",
    "tests/doep/test_doep_010_define_supervisorobjectiveintent_contract.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-010.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-010.json",
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

TASK_CID = "sha256:afe56c698131fcdf1f079626b363d4ec616b67de4a1b14571f2b4b228785b1f2"
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
        "title_hint": "Example direct objective",
        "tags": ("direct-objective", "doep"),
    }
    values.update(overrides)
    return SupervisorObjectiveIntent(**values)


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        path = DATASETS_ROOT / relative
        assert path.is_file(), f"missing declared output: {relative}"
    assert SCHEMA_PATH.is_file()
    assert TEST_PATH.is_file()
    assert OUTPUT_PATH.is_file()
    assert RECEIPT_PATH.is_file()


def test_contract_symbols_and_schema_constants() -> None:
    assert SUPERVISOR_OBJECTIVE_INTENT_SCHEMA == (
        "ipfs_datasets_py/logic/intent-ir/supervisor-objective-intent@1"
    )
    assert SUPERVISOR_OBJECTIVE_INTENT_SCHEMA_VERSION == "supervisor-objective-intent/v1"
    assert SUPERVISOR_OBJECTIVE_INTENT_MAX_IDEA_UTF8_BYTES == 16384
    assert INTENT_IR_SCHEMA_VERSION == "intent-ir/v1"
    assert issubclass(SupervisorObjectiveIntent, object)
    assert not issubclass(SupervisorObjectiveIntent, IntentIRDocument)
    source = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "class SupervisorObjectiveIntent" in source
    assert "class IntentIRDocument" in source
    assert "SUPERVISOR_OBJECTIVE_INTENT_SCHEMA" in source
    lowered = source.lower()
    assert "authoritative policy" in lowered
    assert "does not authorize" in lowered


def test_validate_accepts_minimal_valid_intent() -> None:
    intent = _minimal_intent()
    validated = validate_supervisor_objective_intent(intent)
    assert validated is intent
    assert validated.schema == SUPERVISOR_OBJECTIVE_INTENT_SCHEMA
    assert validated.callers_supply_authoritative_policy is False
    payload = intent.to_dict()
    assert payload["schema"] == SUPERVISOR_OBJECTIVE_INTENT_SCHEMA
    assert payload["tags"] == ["direct-objective", "doep"]
    round_trip = SupervisorObjectiveIntent.from_dict(payload)
    validate_supervisor_objective_intent(round_trip)
    assert round_trip.to_dict() == payload


def test_validate_rejects_authority_and_shape_errors() -> None:
    with pytest.raises(IntentIRValidationError):
        validate_supervisor_objective_intent(_minimal_intent(idea_text="   "))
    with pytest.raises(IntentIRValidationError):
        validate_supervisor_objective_intent(
            _minimal_intent(idea_sha256="0" * 64)
        )
    oversized = "x" * (SUPERVISOR_OBJECTIVE_INTENT_MAX_IDEA_UTF8_BYTES + 1)
    with pytest.raises(IntentIRValidationError):
        validate_supervisor_objective_intent(
            _minimal_intent(
                idea_text=oversized,
                idea_sha256=idea_text_sha256(oversized),
            )
        )
    with pytest.raises(IntentIRValidationError):
        validate_supervisor_objective_intent(_minimal_intent(intent_id=""))
    with pytest.raises(IntentIRValidationError):
        SupervisorObjectiveIntent.from_dict(
            {
                **_minimal_intent().to_dict(),
                "policy_id": "policy:forbidden",
            }
        )
    with pytest.raises(IntentIRValidationError):
        SupervisorObjectiveIntent.from_dict(
            {
                **_minimal_intent().to_dict(),
                "unknown_field": "nope",
            }
        )


def test_forbidden_authority_fields_absent() -> None:
    field_names = {item.name for item in dataclasses.fields(SupervisorObjectiveIntent)}
    assert field_names.isdisjoint(SUPERVISOR_OBJECTIVE_INTENT_FORBIDDEN_FIELDS)
    payload_keys = set(_minimal_intent().to_dict())
    assert payload_keys.isdisjoint(SUPERVISOR_OBJECTIVE_INTENT_FORBIDDEN_FIELDS)
    for name in (
        "policy_id",
        "policy_revision",
        "authorization_decision",
        "lease_id",
        "fencing_epoch",
        "expected_effects",
        "objective_cid",
        "plan_root_cid",
    ):
        assert name in SUPERVISOR_OBJECTIVE_INTENT_FORBIDDEN_FIELDS


def test_output_manifest_contract() -> None:
    manifest = _load_json(OUTPUT_PATH)
    assert manifest["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-output@1"
    assert manifest["task_id"] == "DOEP-010"
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
    assert manifest["validation_profile"] == "doep-validation/DOEP-PLAN-V5/DOEP-010@1"
    assert manifest["owning_repository"] == "ipfs_datasets_py"
    assert manifest["goal_id"] == "DOEP-G020.S1"
    assert manifest["parent_goal_id"] == "DOEP-G020"
    assert manifest["root_goal_id"] == "DOEP-G000"
    assert (
        manifest["title"] == "Define SupervisorObjectiveIntent contract"
    )

    ownership = manifest["cross_repository_ownership"]
    for key, value in OWNERSHIP.items():
        assert ownership[key] == value

    contract = manifest["supervisor_objective_intent_contract"]
    assert contract["schema"] == SUPERVISOR_OBJECTIVE_INTENT_SCHEMA
    assert contract["schema_version"] == SUPERVISOR_OBJECTIVE_INTENT_SCHEMA_VERSION
    assert contract["class_name"] == "SupervisorObjectiveIntent"
    assert contract["module"] == "ipfs_datasets_py.logic.intent_ir.schema"
    assert contract["parallel_to"] == "IntentIRDocument"
    assert contract["callers_supply_authoritative_policy"] is False
    assert contract["operational_admission_owner"] == "ipfs_accelerate_py"
    assert contract["competing_subsystem_created"] is False


def test_candidate_receipt_contract() -> None:
    receipt = _load_json(RECEIPT_PATH)
    assert receipt["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-receipt@1"
    assert receipt["task_id"] == "DOEP-010"
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
    assert receipt["goal_id"] == "DOEP-G020.S1"
    assert receipt["parent_goal_id"] == "DOEP-G020"
    assert receipt["root_goal_id"] == "DOEP-G000"

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
        "tests/doep/test_doep_010_define_supervisorobjectiveintent_contract.py",
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
        if not relative.endswith("/receipts/DOEP-010.json")
    ]
    digests = {
        relative: _sha256_file(DATASETS_ROOT / relative) for relative in digested_paths
    }
    canonical = json.dumps(digests, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert receipt["required_evidence"]["changed_path_digest"] == expected
    assert receipt["path_digests"] == digests
    assert set(digests) == set(digested_paths)


def test_output_manifest_and_receipt_agree() -> None:
    manifest = _load_json(OUTPUT_PATH)
    receipt = _load_json(RECEIPT_PATH)
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-010"
    assert manifest["plan_revision"] == receipt["plan_revision"]
    assert manifest["board_namespace"] == receipt["board_namespace"]
    assert manifest["declared_outputs"] == receipt["expected_outputs"]
    assert manifest["base_repositories"] == receipt["required_evidence"][
        "source_commit_tree_gitlinks"
    ]
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["no_competing_subsystem_created"] is True
    assert receipt["no_competing_subsystem_created"] is True
