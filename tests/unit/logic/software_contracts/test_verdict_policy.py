"""Contract tests for the DSCON-G030 verdict and soundness policy.

Covers the normative machine policy, human threat model, and the conceptual
interfaces VerificationVerdict, AssuranceLevel, CompletionEvidence, and
ProofAttestation (objective validation repair for DSCON-063 / DSCON-G030).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[4]
POLICY_PATH = PACKAGE_ROOT / "docs/software_contracts/verdict-policy-v1.json"
THREAT_MODEL_PATH = (
    PACKAGE_ROOT / "docs/software_contracts/SOUNDNESS_AND_THREAT_MODEL.md"
)

CONCEPTUAL_INTERFACES = {
    "VerificationVerdict",
    "AssuranceLevel",
    "CompletionEvidence",
    "ProofAttestation",
}
EXPECTED_VERDICTS = {
    "PROVED_WITHIN_MODEL",
    "VIOLATED_WITH_COUNTEREXAMPLE",
    "UNKNOWN",
    "UNSUPPORTED",
    "INCOMPLETE_SCAN",
    "STALE",
    "ERROR",
}
FAIL_CLOSED_VERDICTS = {
    "UNKNOWN",
    "UNSUPPORTED",
    "INCOMPLETE_SCAN",
    "STALE",
    "ERROR",
}
EXPECTED_ASSURANCE_LEVELS = {
    "ADVISORY",
    "EMPIRICAL",
    "CHECKED_WITNESS",
    "FORMAL_WITHIN_MODEL",
    "CRYPTOGRAPHIC_INTEGRITY",
}
BOUNDED_EVIDENCE = {
    "GRAPHRAG_RETRIEVAL",
    "TEST_RESULT",
    "TYPE_CHECK_RESULT",
    "SIMULATED_PROOF",
    "ZK_ATTESTATION",
    "ABSENCE_OF_FINDINGS",
}
PROOF_ATTESTATION_KINDS = frozenset({"FORMAL_PROOF_RECEIPT", "ZK_ATTESTATION"})


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    assert POLICY_PATH.is_file(), f"missing policy: {POLICY_PATH}"
    assert THREAT_MODEL_PATH.is_file(), f"missing threat model: {THREAT_MODEL_PATH}"
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _fixture_satisfies(policy: dict[str, Any], fixture: dict[str, Any]) -> bool:
    """Evaluate only the declarative completion matrix in the policy."""

    requirement = policy["completion_requirements"][fixture["criterion"]]
    authority = policy["evidence_authority"][fixture["evidence_kind"]]
    conditions = fixture["conditions"]
    return (
        fixture["verdict"] in requirement["allowed_verdicts"]
        and fixture["evidence_kind"] in requirement["allowed_evidence_kinds"]
        and fixture["assurance_level"] in requirement["allowed_assurance_levels"]
        and fixture["criterion"] in authority["may_satisfy"]
        and authority["assurance_level"] == fixture["assurance_level"]
        and all(conditions.get(name) is True for name in requirement["required_conditions"])
    )


def test_policy_is_versioned_normative_json(policy: dict[str, Any]) -> None:
    assert policy["schema_version"] == (
        "ipfs-datasets.software-contract-verdict-policy.v1"
    )
    assert policy["policy_id"] == "software-contract-verdict-policy-v1"
    assert policy["policy_version"] == "1.0.0"
    assert policy["normative"] is True
    assert policy["human_readable_companion"] == THREAT_MODEL_PATH.name
    assert set(policy["conceptual_interfaces"]) == CONCEPTUAL_INTERFACES


def test_policy_defines_exact_terminal_verdict_vocabulary(
    policy: dict[str, Any],
) -> None:
    verdicts = policy["verdicts"]
    by_id = {item["id"]: item for item in verdicts}

    assert len(by_id) == len(verdicts), "verdict identifiers must be unique"
    assert set(by_id) == EXPECTED_VERDICTS
    assert all(item["terminal"] is True for item in verdicts)
    assert {
        verdict_id
        for verdict_id, definition in by_id.items()
        if definition["fail_closed"]
    } == FAIL_CLOSED_VERDICTS
    assert by_id["PROVED_WITHIN_MODEL"]["fail_closed"] is False
    assert by_id["VIOLATED_WITH_COUNTEREXAMPLE"]["fail_closed"] is False


def test_conceptual_interfaces_are_structured_and_bound(
    policy: dict[str, Any],
) -> None:
    """VerificationVerdict, AssuranceLevel, CompletionEvidence, ProofAttestation."""

    interfaces = policy["conceptual_interfaces"]
    for name in CONCEPTUAL_INTERFACES:
        definition = interfaces[name]
        assert isinstance(definition, dict), name
        assert definition.get("role"), name
        assert definition.get("meaning"), name
        assert definition.get("authority_field"), name
        assert definition.get("required_fields"), name

    verdict_iface = interfaces["VerificationVerdict"]
    assert verdict_iface["vocabulary_ref"] == "verdicts"
    assert set(item["id"] for item in policy["verdicts"]) == EXPECTED_VERDICTS

    assurance_iface = interfaces["AssuranceLevel"]
    assert assurance_iface["not_totally_ordered"] is True
    level_ids = {item["id"] for item in policy["assurance_levels"]["levels"]}
    assert level_ids == EXPECTED_ASSURANCE_LEVELS

    evidence_iface = interfaces["CompletionEvidence"]
    assert evidence_iface["vocabulary_ref"] == "evidence_authority"
    for field in evidence_iface["required_fields"]:
        for kind, row in policy["evidence_authority"].items():
            assert field in row, f"{kind} missing {field}"

    proof_iface = interfaces["ProofAttestation"]
    assert set(proof_iface["allowed_evidence_kinds"]) == PROOF_ATTESTATION_KINDS
    assert "proof_required" in proof_iface["non_escalation"]
    for kind in PROOF_ATTESTATION_KINDS:
        assert kind in policy["evidence_authority"]
    assert (
        "proof_required"
        not in policy["evidence_authority"]["ZK_ATTESTATION"]["may_satisfy"]
    )
    assert policy["evidence_authority"]["FORMAL_PROOF_RECEIPT"]["may_satisfy"] == [
        "proof_required"
    ]
    assert policy["evidence_authority"]["SIMULATED_PROOF"]["may_satisfy"] == []


def test_only_formal_bound_proof_can_satisfy_proof_completion(
    policy: dict[str, Any],
) -> None:
    proof = policy["completion_requirements"]["proof_required"]
    assert proof["allowed_verdicts"] == ["PROVED_WITHIN_MODEL"]
    assert proof["allowed_evidence_kinds"] == ["FORMAL_PROOF_RECEIPT"]
    assert proof["allowed_assurance_levels"] == ["FORMAL_WITHIN_MODEL"]
    assert set(proof["required_conditions"]) == {
        "model_named",
        "assumptions_bound",
        "scope_bound",
        "coverage_complete",
        "repository_current",
        "policy_bound",
        "analyzer_bound",
        "toolchain_bound",
        "evidence_integrity_verified",
    }


def test_evidence_authority_is_non_substitutable_and_bounded(
    policy: dict[str, Any],
) -> None:
    authority = policy["evidence_authority"]

    assert set(authority) >= BOUNDED_EVIDENCE
    assert authority["TEST_RESULT"]["may_satisfy"] == ["test_required"]
    assert authority["TYPE_CHECK_RESULT"]["may_satisfy"] == [
        "type_check_required"
    ]
    assert authority["ZK_ATTESTATION"]["may_satisfy"] == [
        "attestation_integrity_required"
    ]
    for evidence_kind in (
        "GRAPHRAG_RETRIEVAL",
        "SIMULATED_PROOF",
        "ABSENCE_OF_FINDINGS",
    ):
        assert authority[evidence_kind]["may_satisfy"] == []

    assert policy["assurance_levels"]["not_totally_ordered"] is True
    non_escalation = policy["assurance_levels"]["non_escalation_rule"]
    assert "CRYPTOGRAPHIC_INTEGRITY does not imply FORMAL_WITHIN_MODEL" in (
        non_escalation
    )
    completion_rule = policy["completion_non_escalation_rule"]
    assert "does not satisfy proof_required" in completion_rule
    assert "does not upgrade" in completion_rule


def test_dynamic_behavior_and_absent_findings_fail_conservatively(
    policy: dict[str, Any],
) -> None:
    semantics = policy["semantic_models"]
    scan = policy["scan_completeness"]

    assert semantics["dynamic_or_external_behavior"]
    rule = semantics["dynamic_behavior_rule"]
    assert "UNSUPPORTED" in rule
    assert "UNKNOWN" in rule
    assert "Never infer PROVED_WITHIN_MODEL" in rule
    assert scan["unsupported_is_explicitly_counted"] is True
    assert "cannot establish behavioral proof" in (
        scan["unsupported_disposition_limit"]
    )
    assert "not evidence of safety" in scan["absence_rule"]


def test_scan_completeness_requires_identity_disposition_and_all_shards(
    policy: dict[str, Any],
) -> None:
    scan = policy["scan_completeness"]
    complete = " ".join(scan["complete_when_all"])
    incomplete = " ".join(scan["incomplete_when_any"])

    assert "Every selected tracked object is counted exactly once" in complete
    assert "explicit analyzed, unsupported, excluded-by-policy" in complete
    assert "All expected shards are present" in complete
    assert "gitlinks" in complete
    assert "shard" in incomplete
    assert "INCOMPLETE_SCAN" in policy["verdict_selection"][2]


def test_contract_authority_is_ordered_and_conflicts_fail_closed(
    policy: dict[str, Any],
) -> None:
    contract = policy["contract_authority"]
    assert contract["order_high_to_low"] == [
        "reviewed_policy_or_contract_registry",
        "versioned_public_schema_or_protocol",
        "version_bound_documented_api_contract",
        "declared_type_contract",
        "implementation_inference",
    ]
    assert set(contract["observations_are_evidence_not_contract_authority"]) >= {
        "tests",
        "GraphRAG retrieval",
        "absence of findings",
    }
    assert "ERROR" in contract["conflict_rule"]
    assert "cannot satisfy completion" in contract["conflict_rule"]


def test_policy_names_tcb_adversaries_and_non_goals(
    policy: dict[str, Any],
) -> None:
    assert len(policy["trusted_computing_base"]["components"]) >= 10
    outcomes = policy["threat_outcomes"]
    assert set(outcomes) >= {
        "malicious_or_pathological_source",
        "tampered_evidence_or_cache",
        "stale_or_cross_revision_evidence",
        "scope_omission_or_missing_shard",
        "retrieval_poisoning_or_ranking_drift",
        "forged_counterexample",
        "forged_or_simulated_proof",
        "resource_exhaustion",
    }
    assert len(policy["non_goals"]) >= 6


def test_all_normative_decision_fixtures_match_completion_matrix(
    policy: dict[str, Any],
) -> None:
    fixtures = policy["decision_fixtures"]
    fixture_ids = [fixture["id"] for fixture in fixtures]

    assert len(fixture_ids) == len(set(fixture_ids))
    assert any(item["expected_satisfies_completion"] for item in fixtures)
    assert any(not item["expected_satisfies_completion"] for item in fixtures)
    for fixture in fixtures:
        assert _fixture_satisfies(policy, fixture) is (
            fixture["expected_satisfies_completion"]
        ), fixture["id"]


@pytest.mark.parametrize(
    "fixture_id",
    [
        "reject_test_as_formal_proof",
        "reject_type_check_as_behavior_proof",
        "reject_graphrag_as_proof",
        "reject_simulated_proof",
        "reject_zk_envelope_as_underlying_proof",
        "reject_absence_of_findings_as_safety",
        "reject_unknown_as_completion",
        "reject_unsupported_as_completion",
        "reject_incomplete_scan_as_completion",
        "reject_stale_as_completion",
        "reject_error_as_completion",
        "reject_unbound_assumptions",
    ],
)
def test_required_rejection_fixture_fails_closed(
    policy: dict[str, Any], fixture_id: str
) -> None:
    fixture = next(
        item for item in policy["decision_fixtures"] if item["id"] == fixture_id
    )
    assert fixture["expected_satisfies_completion"] is False
    assert _fixture_satisfies(policy, fixture) is False


def test_human_threat_model_covers_normative_policy(policy: dict[str, Any]) -> None:
    document = THREAT_MODEL_PATH.read_text(encoding="utf-8")

    for verdict in EXPECTED_VERDICTS:
        assert f"`{verdict}`" in document
    for interface in CONCEPTUAL_INTERFACES:
        assert f"`{interface}`" in document
    for phrase in (
        "Conceptual interfaces",
        "Supported semantic models",
        "Trusted computing base",
        "Contract authority",
        "Scan completeness",
        "Evidence and completion authority",
        "GraphRAG",
        "test pass",
        "type-check pass",
        "simulated proof",
        "ZK attestation",
        "absence of findings",
        "fail closed",
        "not totally ordered",
        "proof_required",
    ):
        assert phrase.casefold() in document.casefold()
    assert policy["claim_rule"] in document or (
        "Narrow provable claims are preferable" in document
    )
    assert "verdict-policy-v1.json" in document
    assert policy["policy_version"] in document
