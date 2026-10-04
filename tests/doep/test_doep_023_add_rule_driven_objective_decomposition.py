"""Independent current-tree tests for DOEP-023 rule-driven objective decomposition.

A worker or model assertion alone is insufficient. This module verifies the
plan-bound declared outputs, datasets-owned decomposition carrier, and
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
    RULE_DRIVEN_DECOMPOSITION_MAX_CHILDREN,
    RULE_DRIVEN_OBJECTIVE_DECOMPOSER_ID,
    RULE_DRIVEN_OBJECTIVE_DECOMPOSER_VERSION,
    RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_AUTHORITY,
    RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_FORBIDDEN_FIELDS,
    RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA,
    RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA_VERSION,
    SUPERVISOR_OBJECTIVE_INTENT_SCHEMA,
    DeterministicObjectiveNormalization,
    IntentIRDocument,
    IntentIRValidationError,
    KnownObjectiveClass,
    RuleDrivenObjectiveDecomposition,
    SupervisorObjectiveIntent,
    SupervisorObjectiveSubmitterKind,
    decompose_supervisor_objective_by_rules,
    idea_text_sha256,
    list_known_objective_class_rules,
    normalize_supervisor_objective_deterministically,
    validate_rule_driven_objective_decomposition,
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
    / "DOEP-023.json"
)
RECEIPT_PATH = (
    DATASETS_ROOT
    / "artifacts"
    / "agent_supervisor_direct_objective_event_driven_planning"
    / "receipts"
    / "DOEP-023.json"
)

OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/intent_ir/schema.py",
    "tests/doep/test_doep_023_add_rule_driven_objective_decomposition.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-023.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-023.json",
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

TASK_CID = "sha256:1e73cc9a3cc1497b35f69a69be882a35555de72c1fa2a81a015d56997336c27c"
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


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        path = DATASETS_ROOT / relative
        assert path.is_file(), f"missing declared output: {relative}"
    assert SCHEMA_PATH.is_file()
    assert TEST_PATH.is_file()
    assert OUTPUT_PATH.is_file()
    assert RECEIPT_PATH.is_file()


def test_decomposition_symbols_extend_canonical_schema_without_competing_subsystem() -> None:
    assert RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA == (
        "ipfs_datasets_py/logic/intent-ir/rule-driven-objective-decomposition@1"
    )
    assert (
        RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA_VERSION
        == "rule-driven-objective-decomposition/v1"
    )
    assert RULE_DRIVEN_OBJECTIVE_DECOMPOSER_ID == (
        "ipfs_datasets_py/logic/intent-ir/rule-driven-objective-decomposer@1"
    )
    assert RULE_DRIVEN_OBJECTIVE_DECOMPOSER_VERSION == "1"
    assert RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_AUTHORITY == "semantic_only"
    assert RULE_DRIVEN_DECOMPOSITION_MAX_CHILDREN == 12
    assert INTENT_IR_SCHEMA_VERSION == "intent-ir/v1"
    assert SUPERVISOR_OBJECTIVE_INTENT_SCHEMA.startswith(
        "ipfs_datasets_py/logic/intent-ir/"
    )
    assert DETERMINISTIC_NORMALIZATION_SCHEMA.startswith(
        "ipfs_datasets_py/logic/intent-ir/"
    )
    assert issubclass(RuleDrivenObjectiveDecomposition, object)
    assert not issubclass(RuleDrivenObjectiveDecomposition, IntentIRDocument)
    assert not issubclass(RuleDrivenObjectiveDecomposition, SupervisorObjectiveIntent)
    assert not issubclass(
        RuleDrivenObjectiveDecomposition, DeterministicObjectiveNormalization
    )
    source = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "class RuleDrivenObjectiveDecomposition" in source
    assert "def decompose_supervisor_objective_by_rules" in source
    assert "class DeterministicObjectiveNormalization" in source
    assert "class SupervisorObjectiveIntent" in source
    assert "class IntentIRDocument" in source
    lowered = source.lower()
    assert "competing" in lowered or "not a second" in lowered
    assert "does not authorize" in lowered or "semantic-only" in lowered
    assert "authoritative policy" in lowered or "admission authority" in lowered
    rules = list_known_objective_class_rules()
    assert rules
    assert all(rule.objective_class is not KnownObjectiveClass.UNKNOWN for rule in rules)


def test_decompose_is_deterministic_and_binds_normalization() -> None:
    normalization = _minimal_normalization()
    first = decompose_supervisor_objective_by_rules(
        normalization,
        objective_class=KnownObjectiveClass.DIRECT_OBJECTIVE_CONTRACT,
        available_capability_ids=("capability:schema", "capability:test"),
        repository_analysis_cid="analysis:sha256:example",
    )
    second = decompose_supervisor_objective_by_rules(
        normalization.to_dict(),
        objective_class="direct_objective_contract",
        available_capability_ids=("capability:test", "capability:schema"),
        repository_analysis_cid="analysis:sha256:example",
    )
    assert first.to_dict() == second.to_dict()
    assert first.schema == RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA
    assert first.authority == RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_AUTHORITY
    assert first.is_completion_authority is False
    assert first.callers_supply_authoritative_policy is False
    assert first.decomposer_id == RULE_DRIVEN_OBJECTIVE_DECOMPOSER_ID
    assert first.decomposer_version == RULE_DRIVEN_OBJECTIVE_DECOMPOSER_VERSION
    assert first.intent_id == normalization.intent_id
    assert first.idea_sha256 == normalization.idea_sha256
    assert first.intent_sha256 == normalization.intent_sha256
    assert first.normalization_sha256 == normalization.normalization_sha256
    assert first.repository_id == normalization.repository_id
    assert first.board_namespace == normalization.board_namespace
    assert first.scope_paths == normalization.scope_paths
    assert first.matched is True
    assert first.reason_code == "matched_template"
    assert first.objective_class == KnownObjectiveClass.DIRECT_OBJECTIVE_CONTRACT.value
    assert first.matched_rule_id == "rule:direct-objective-contract/v1"
    assert first.truncated is False
    assert len(first.children) == 3
    assert [child.child_id for child in first.children] == sorted(
        child.child_id for child in first.children
    )
    assert first.dependency_edges
    assert first.available_capability_ids == (
        "capability:schema",
        "capability:test",
    )
    payload = first.to_dict()
    round_trip = RuleDrivenObjectiveDecomposition.from_dict(payload)
    assert validate_rule_driven_objective_decomposition(round_trip).to_dict() == payload
    assert "decomposition_sha256" not in payload
    assert len(first.decomposition_sha256) == 64


def test_unknown_and_ambiguous_classes_fail_closed_without_invented_children() -> None:
    normalization = _minimal_normalization(
        intent=_minimal_intent(tags=("doep",)),
    )
    unknown = decompose_supervisor_objective_by_rules(
        normalization,
        objective_class=KnownObjectiveClass.UNKNOWN,
    )
    assert unknown.matched is False
    assert unknown.children == ()
    assert unknown.dependency_edges == ()
    assert unknown.reason_code == "unknown_objective_class"
    assert unknown.objective_class == KnownObjectiveClass.UNKNOWN.value
    assert unknown.matched_rule_id == ""

    ambiguous = decompose_supervisor_objective_by_rules(normalization)
    assert ambiguous.matched is False
    assert ambiguous.children == ()
    assert ambiguous.reason_code == "ambiguous_objective_class"

    tagged = decompose_supervisor_objective_by_rules(
        _minimal_normalization(
            intent=_minimal_intent(tags=("contract", "direct-objective", "doep"))
        )
    )
    assert tagged.matched is True
    assert tagged.objective_class == KnownObjectiveClass.DIRECT_OBJECTIVE_CONTRACT.value
    assert tagged.children


def test_decompose_rejects_authority_and_path_escapes() -> None:
    normalization = _minimal_normalization()
    with pytest.raises(IntentIRValidationError):
        decompose_supervisor_objective_by_rules(
            {**normalization.to_dict(), "policy_id": "policy:forbidden"}
        )
    with pytest.raises(IntentIRValidationError):
        decompose_supervisor_objective_by_rules(
            {**normalization.to_dict(), "lease_id": "lease:forbidden"}
        )
    with pytest.raises(IntentIRValidationError):
        decompose_supervisor_objective_by_rules(
            {**normalization.to_dict(), "plan_root_cid": "plan:forbidden"}
        )
    with pytest.raises(IntentIRValidationError):
        decompose_supervisor_objective_by_rules(
            normalization,
            objective_class="not_a_known_class",
        )
    with pytest.raises(IntentIRValidationError):
        RuleDrivenObjectiveDecomposition.from_dict(
            {
                **decompose_supervisor_objective_by_rules(
                    normalization,
                    objective_class=KnownObjectiveClass.DIRECT_OBJECTIVE_CONTRACT,
                ).to_dict(),
                "completion_authoritative": True,
            }
        )
    with pytest.raises(IntentIRValidationError):
        RuleDrivenObjectiveDecomposition.from_dict(
            {
                **decompose_supervisor_objective_by_rules(
                    normalization,
                    objective_class=KnownObjectiveClass.DIRECT_OBJECTIVE_CONTRACT,
                ).to_dict(),
                "authority": "admitted",
            }
        )
    with pytest.raises(IntentIRValidationError):
        validate_rule_driven_objective_decomposition(
            {
                **decompose_supervisor_objective_by_rules(
                    normalization,
                    objective_class=KnownObjectiveClass.DIRECT_OBJECTIVE_CONTRACT,
                ).to_dict(),
                "children": [
                    {
                        "child_id": "escape.child",
                        "title": "Escape scope",
                        "role": "escape",
                        "scope_paths": ["../escape"],
                        "depends_on": [],
                        "covers": ["escape"],
                    }
                ],
                "dependency_edges": [],
            }
        )
    fields = {item.name for item in dataclasses.fields(RuleDrivenObjectiveDecomposition)}
    assert fields.isdisjoint(RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_FORBIDDEN_FIELDS)
    assert {
        "policy_id",
        "lease_id",
        "terminalize",
        "plan_root_cid",
        "completion_authoritative",
    } <= RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_FORBIDDEN_FIELDS


def test_staged_compiler_rule_preserves_partial_order() -> None:
    result = decompose_supervisor_objective_by_rules(
        _minimal_normalization(),
        objective_class=KnownObjectiveClass.STAGED_OBJECTIVE_COMPILER,
    )
    assert result.matched is True
    assert len(result.children) == 7
    assert [child.child_id for child in result.children] == sorted(
        child.child_id for child in result.children
    )
    by_role = {child.role: child for child in result.children}
    assert set(by_role) == {
        "normalize",
        "analyze",
        "decompose",
        "obligations",
        "questions",
        "residual",
        "validate_plan",
    }
    assert by_role["analyze"].depends_on == (by_role["normalize"].child_id,)
    assert by_role["decompose"].depends_on == (by_role["analyze"].child_id,)
    assert by_role["validate_plan"].depends_on == (by_role["residual"].child_id,)
    assert result.dependency_edges == tuple(sorted(result.dependency_edges))
    child_ids = {child.child_id for child in result.children}
    for source, target in result.dependency_edges:
        assert source in child_ids
        assert target in child_ids


def test_output_manifest_contract() -> None:
    manifest = _load_json(OUTPUT_PATH)
    assert manifest["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-output@1"
    assert manifest["task_id"] == "DOEP-023"
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
    assert manifest["validation_profile"] == "doep-validation/DOEP-PLAN-V5/DOEP-023@1"
    assert manifest["owning_repository"] == "ipfs_datasets_py"
    assert manifest["goal_id"] == "DOEP-G030.S2"
    assert manifest["parent_goal_id"] == "DOEP-G030"
    assert manifest["root_goal_id"] == "DOEP-G000"
    assert manifest["title"] == "Add rule-driven objective decomposition"

    ownership = manifest["cross_repository_ownership"]
    for key, value in OWNERSHIP.items():
        assert ownership[key] == value

    contract = manifest["rule_driven_objective_decomposition_contract"]
    assert contract == {
        "authority": RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_AUTHORITY,
        "class_name": "RuleDrivenObjectiveDecomposition",
        "competing_subsystem_created": False,
        "decomposer_id": RULE_DRIVEN_OBJECTIVE_DECOMPOSER_ID,
        "decomposer_version": RULE_DRIVEN_OBJECTIVE_DECOMPOSER_VERSION,
        "entrypoint": "decompose_supervisor_objective_by_rules",
        "known_objective_classes": [
            item.value
            for item in KnownObjectiveClass
            if item is not KnownObjectiveClass.UNKNOWN
        ]
        + [KnownObjectiveClass.UNKNOWN.value],
        "module": "ipfs_datasets_py.logic.intent_ir.schema",
        "operational_admission_owner": "ipfs_accelerate_py",
        "parallel_to": "DeterministicObjectiveNormalization",
        "schema": RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA,
        "schema_version": RULE_DRIVEN_OBJECTIVE_DECOMPOSITION_SCHEMA_VERSION,
        "semantic_identity_owner": "ipfs_datasets_py",
    }


def test_candidate_receipt_contract() -> None:
    receipt = _load_json(RECEIPT_PATH)
    assert receipt["schema"] == "ipfs_accelerate_py/agent-supervisor/doep-task-receipt@1"
    assert receipt["task_id"] == "DOEP-023"
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
        "tests/doep/test_doep_023_add_rule_driven_objective_decomposition.py",
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
        if not relative.endswith("/receipts/DOEP-023.json")
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
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-023"
    assert manifest["plan_revision"] == receipt["plan_revision"]
    assert manifest["board_namespace"] == receipt["board_namespace"]
    assert manifest["declared_outputs"] == receipt["expected_outputs"]
    assert manifest["base_repositories"] == receipt["required_evidence"][
        "source_commit_tree_gitlinks"
    ]
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["no_competing_subsystem_created"] is True
    assert receipt["no_competing_subsystem_created"] is True
    # Keep the validated intent helper exercised for import/contract stability.
    assert validate_supervisor_objective_intent(_minimal_intent()).intent_id
