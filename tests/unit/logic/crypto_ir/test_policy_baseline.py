"""Machine-checked Crypto IR threat and authority policy baseline (CRYPTOIR-001).

Covers CRYPTOIR-G010 acceptance:

* documents bind the reviewed git revisions;
* observation, evidence, proof, monitor, heuristic, designation, policy, and
  authorization authorities are distinct and non-escalating;
* exact ``PROVED``, ``DISPROVED``, ``UNKNOWN``, ``UNSUPPORTED``,
  ``INCONCLUSIVE``, ``STALE``, ``ERROR``, ``ALLOW``, ``REVIEW``, and ``DENY``
  semantics are defined;
* unbounded guilt by association and universal security claims are prohibited;
* unsupported or stale critical inputs fail closed;
* conceptual interfaces AnalysisAuthority, PolicyAuthority,
  TransactionVerdict, and EvidenceFreshness are present;
* positive and rejection fixtures are evaluated without implementing chain
  logic.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[4]
AUTHORITY_PATH = PACKAGE_ROOT / "docs/crypto_ir/AUTHORITY_AND_POLICY.md"
THREAT_MODEL_PATH = PACKAGE_ROOT / "docs/crypto_ir/THREAT_MODEL.md"

POLICY_FENCE_RE = re.compile(
    r"```json\s+crypto-ir-authority-policy-v1\s*\n(.*?)\n```",
    re.DOTALL,
)

CONCEPTUAL_INTERFACES = {
    "AnalysisAuthority",
    "PolicyAuthority",
    "TransactionVerdict",
    "EvidenceFreshness",
}

AUTHORITY_KINDS = {
    "observation",
    "evidence",
    "proof",
    "monitor",
    "heuristic",
    "designation",
    "policy",
    "authorization",
}

ANALYSIS_OUTCOMES = {
    "PROVED",
    "DISPROVED",
    "UNKNOWN",
    "UNSUPPORTED",
    "INCONCLUSIVE",
    "STALE",
    "ERROR",
}

FAIL_CLOSED_ANALYSIS = {
    "DISPROVED",
    "UNKNOWN",
    "UNSUPPORTED",
    "INCONCLUSIVE",
    "STALE",
    "ERROR",
}

TRANSACTION_VERDICTS = {
    "ALLOW",
    "REVIEW",
    "DENY",
    "INCONCLUSIVE",
    "STALE",
    "ERROR",
}

PINNED_BASELINE = {
    "tree_revision": "34b536b59bfb7fcb4c7772b7078fe04709e92fc8",
    "ipfs_datasets_py": "75ae1de0fd5d8bc3625d26de3ccdd65f3a070dc9",
    "ipfs_accelerate_py": "c3988ec5e4c55edf8ce541825d82c10e11318745",
    "ipfs_kit_py": "276d766b8076b725a5a9e53bcf0c057f067acd10",
}

REQUIRED_REJECTION_FIXTURES = {
    "reject_heuristic_as_designation",
    "reject_heuristic_sole_allow",
    "reject_stale_critical_allow",
    "reject_unsupported_as_allow",
    "reject_unknown_as_allow",
    "reject_inconclusive_as_allow",
    "reject_error_as_allow",
    "reject_proof_alone_as_transaction_allow",
    "reject_observation_as_designation",
    "reject_monitor_as_proof",
    "reject_universal_security_claim",
    "reject_guilt_by_association_as_designation",
}

REQUIRED_POSITIVE_FIXTURES = {
    "allow_fresh_exact_candidate_all_required_pass",
}


def _load_policy() -> dict[str, Any]:
    assert AUTHORITY_PATH.is_file(), f"missing authority policy: {AUTHORITY_PATH}"
    assert THREAT_MODEL_PATH.is_file(), f"missing threat model: {THREAT_MODEL_PATH}"
    text = AUTHORITY_PATH.read_text(encoding="utf-8")
    match = POLICY_FENCE_RE.search(text)
    assert match, (
        "AUTHORITY_AND_POLICY.md must embed a fenced JSON block labeled "
        "crypto-ir-authority-policy-v1"
    )
    policy = json.loads(match.group(1))
    assert isinstance(policy, dict)
    return policy


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    return _load_policy()


@pytest.fixture(scope="module")
def authority_doc() -> str:
    return AUTHORITY_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def threat_doc() -> str:
    return THREAT_MODEL_PATH.read_text(encoding="utf-8")


def evaluate_fixture(policy: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one decision fixture against normative fail-closed rules.

    This is intentionally pure policy logic: no chain parsing, networking, or
    signing. A fixture satisfies automated ALLOW only when every hard gate
    passes.
    """

    violations: list[str] = []
    analysis_by_id = {item["id"]: item for item in policy["analysis_outcomes"]}
    verdict_by_id = {item["id"]: item for item in policy["transaction_verdicts"]}
    freshness = policy["freshness_rules"]
    prohibitions = set(policy["prohibitions"])
    non_escalation = set(policy["non_escalation_rules"])

    analysis_id = fixture["analysis_outcome"]
    verdict_id = fixture["transaction_verdict"]
    authority_kind = fixture["authority_kind"]

    assert analysis_id in analysis_by_id, analysis_id
    assert verdict_id in verdict_by_id, verdict_id
    assert authority_kind in AUTHORITY_KINDS, authority_kind

    verdict = verdict_by_id[verdict_id]

    if fixture.get("claims_universal_security"):
        violations.append("universal_security_claim")
    if fixture.get("guilt_by_association"):
        violations.append("unbounded_guilt_by_association")

    if authority_kind == "heuristic":
        if verdict_id == "ALLOW" or fixture.get("heuristic_only"):
            if verdict_id == "ALLOW":
                violations.append("heuristic_sole_allow")
        # Heuristics never create designation-grade blocked-party conclusions.
        if (
            fixture.get("treats_as_designation")
            or (verdict_id == "DENY" and not fixture.get("exact_designation_hit"))
        ):
            violations.append("heuristic_cannot_become_designation")

    if authority_kind == "observation" and (
        fixture.get("treats_as_designation")
        or (verdict_id == "DENY" and not fixture.get("exact_designation_hit"))
    ):
        violations.append("observation_cannot_become_designation")

    if authority_kind == "monitor" and analysis_id == "PROVED":
        violations.append("monitor_cannot_become_proof")

    if authority_kind == "proof" and verdict_id == "ALLOW":
        violations.append("proof_cannot_alone_authorize_transaction")

    if not fixture.get("fresh_critical_inputs", True) and verdict_id == "ALLOW":
        violations.append("stale_critical_allow")

    if analysis_id == "UNSUPPORTED" and verdict_id == "ALLOW":
        violations.append("unsupported_critical_allow")

    if analysis_id in FAIL_CLOSED_ANALYSIS and verdict_id == "ALLOW":
        violations.append(f"fail_closed_analysis:{analysis_id}")

    if fixture.get("required_obligation_disproved") and verdict_id == "ALLOW":
        violations.append("disproved_required_obligation")

    if fixture.get("exact_designation_hit") and verdict_id == "ALLOW":
        violations.append("designation_hit_allow")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered_violations: list[str] = []
    for item in violations:
        if item not in seen:
            seen.add(item)
            ordered_violations.append(item)

    # Automated ALLOW requires authorization authority, fresh proved inputs,
    # and zero authority violations.
    policy_gates_ok = (
        freshness["stale_blocks_allow"] is True
        and freshness["unsupported_critical_blocks_allow"] is True
        and freshness["automation_requires_current_allow"] is True
        and "stale_critical_allow" in prohibitions
        and "unsupported_critical_allow" in prohibitions
        and "heuristic_sole_allow" in prohibitions
        and "universal_security_claim" in prohibitions
        and "unbounded_guilt_by_association" in prohibitions
        and "proof_cannot_alone_authorize_transaction" in non_escalation
    )
    satisfies_allow = (
        policy_gates_ok
        and verdict_id == "ALLOW"
        and authority_kind == "authorization"
        and fixture.get("fresh_critical_inputs", False) is True
        and analysis_id == "PROVED"
        and not fixture.get("exact_designation_hit")
        and not fixture.get("required_obligation_disproved")
        and not fixture.get("heuristic_only")
        and not fixture.get("claims_universal_security")
        and not fixture.get("guilt_by_association")
        and not fixture.get("treats_as_designation")
        and not ordered_violations
    )

    blocks_automation = True
    if satisfies_allow and not verdict["blocks_automation"]:
        blocks_automation = False
    if verdict_id != "ALLOW":
        blocks_automation = True
    if ordered_violations:
        blocks_automation = True
        satisfies_allow = False

    return {
        "satisfies_allow": satisfies_allow,
        "blocks_automation": blocks_automation,
        "violations": ordered_violations,
    }


# ---------------------------------------------------------------------------
# Document presence and baseline pins
# ---------------------------------------------------------------------------


def test_authority_and_threat_documents_exist() -> None:
    assert AUTHORITY_PATH.is_file()
    assert THREAT_MODEL_PATH.is_file()
    assert AUTHORITY_PATH.stat().st_size > 1000
    assert THREAT_MODEL_PATH.stat().st_size > 1000


def test_policy_is_versioned_normative_json(policy: dict[str, Any]) -> None:
    assert policy["schema_version"] == "ipfs-datasets.crypto-ir-authority-policy.v1"
    assert policy["policy_id"] == "crypto-ir-authority-policy-v1"
    assert policy["policy_version"] == "1.0.0"
    assert policy["normative"] is True
    assert policy["goal_id"] == "CRYPTOIR-G010"
    assert policy["task_id"] == "CRYPTOIR-001"
    assert policy["human_readable_companion"] == THREAT_MODEL_PATH.name
    assert set(policy["conceptual_interfaces"]) == CONCEPTUAL_INTERFACES


def test_documents_bind_reviewed_git_revisions(
    policy: dict[str, Any],
    authority_doc: str,
    threat_doc: str,
) -> None:
    pins = policy["pinned_baseline"]
    assert pins == PINNED_BASELINE
    for name, revision in PINNED_BASELINE.items():
        assert revision in authority_doc, name
        assert revision in threat_doc, name


# ---------------------------------------------------------------------------
# Interface and vocabulary contracts
# ---------------------------------------------------------------------------


def test_conceptual_interfaces_are_structured(policy: dict[str, Any]) -> None:
    for name in CONCEPTUAL_INTERFACES:
        definition = policy["conceptual_interfaces"][name]
        assert definition.get("role"), name
        assert definition.get("meaning"), name
        assert definition.get("vocabulary_ref"), name
        assert definition.get("required_fields"), name


def test_authority_kinds_are_complete_and_non_escalating(
    policy: dict[str, Any],
) -> None:
    kinds = {item["id"]: item for item in policy["authority_kinds"]}
    assert set(kinds) == AUTHORITY_KINDS
    for kind_id, row in kinds.items():
        assert row["may_assert"], kind_id
        assert row["must_not_assert"], kind_id

    non_escalation = set(policy["non_escalation_rules"])
    for required in (
        "observation_cannot_become_designation",
        "heuristic_cannot_become_designation",
        "monitor_cannot_become_proof",
        "satisfiability_cannot_become_proof",
        "proof_cannot_alone_authorize_transaction",
        "graph_distance_cannot_create_blocked_party",
        "absence_of_findings_is_not_proved",
    ):
        assert required in non_escalation

    prohibitions = set(policy["prohibitions"])
    for required in (
        "unbounded_guilt_by_association",
        "universal_security_claim",
        "heuristic_sole_allow",
        "heuristic_as_designation",
        "stale_critical_allow",
        "unsupported_critical_allow",
        "silent_authority_coercion",
        "bare_boolean_authorization",
    ):
        assert required in prohibitions


def test_analysis_outcome_vocabulary(policy: dict[str, Any]) -> None:
    outcomes = policy["analysis_outcomes"]
    by_id = {item["id"]: item for item in outcomes}
    assert len(by_id) == len(outcomes)
    assert set(by_id) == ANALYSIS_OUTCOMES
    assert all(item["terminal"] is True for item in outcomes)
    fail_closed = {
        outcome_id
        for outcome_id, definition in by_id.items()
        if definition["fail_closed"]
    }
    assert fail_closed == FAIL_CLOSED_ANALYSIS
    assert by_id["PROVED"]["fail_closed"] is False
    assert "transaction ALLOW" in by_id["PROVED"]["claim_limit"]
    assert "Never invent" in by_id["UNSUPPORTED"]["claim_limit"] or (
        "outside every reviewed model" in by_id["UNSUPPORTED"]["meaning"]
    )


def test_transaction_verdict_vocabulary(policy: dict[str, Any]) -> None:
    verdicts = policy["transaction_verdicts"]
    by_id = {item["id"]: item for item in verdicts}
    assert set(by_id) == TRANSACTION_VERDICTS
    assert by_id["ALLOW"]["blocks_automation"] is False
    for verdict_id in TRANSACTION_VERDICTS - {"ALLOW"}:
        assert by_id[verdict_id]["blocks_automation"] is True


def test_evidence_freshness_blocks_stale_and_unsupported(
    policy: dict[str, Any],
) -> None:
    freshness = policy["freshness_rules"]
    required_inputs = {
        "exact_candidate_digest",
        "sanctions_snapshot",
        "flow_graph_snapshot",
        "code_epoch",
        "policy_jurisdiction_license_revisions",
        "capability_probes",
        "receipt_effective_expiry",
    }
    assert required_inputs <= set(freshness["critical_inputs"])
    assert freshness["stale_blocks_allow"] is True
    assert freshness["unsupported_critical_blocks_allow"] is True
    assert freshness["missing_critical_blocks_allow"] is True
    assert freshness["material_change_invalidates_decision"] is True
    assert freshness["automation_requires_current_allow"] is True


def test_match_authority_levels_preserve_designation_boundary(
    policy: dict[str, Any],
) -> None:
    levels = policy["match_authority_levels"]
    assert levels[0] == "exact_listed_digital_currency_identifier"
    assert levels[-1] == "heuristic_association"
    assert "indirect_flow_exposure" in levels
    assert levels.index("heuristic_association") > levels.index(
        "exact_listed_digital_currency_identifier"
    )


# ---------------------------------------------------------------------------
# Decision fixtures (positive + rejection)
# ---------------------------------------------------------------------------


def test_decision_fixtures_include_positive_and_rejection_cases(
    policy: dict[str, Any],
) -> None:
    fixtures = policy["decision_fixtures"]
    fixture_ids = [item["id"] for item in fixtures]
    assert len(fixture_ids) == len(set(fixture_ids))
    assert REQUIRED_POSITIVE_FIXTURES <= set(fixture_ids)
    assert REQUIRED_REJECTION_FIXTURES <= set(fixture_ids)
    assert any(item.get("expected_satisfies_allow") for item in fixtures)
    assert any(not item.get("expected_satisfies_allow") for item in fixtures)


def test_all_decision_fixtures_match_policy_evaluator(
    policy: dict[str, Any],
) -> None:
    for fixture in policy["decision_fixtures"]:
        result = evaluate_fixture(policy, fixture)
        assert result["satisfies_allow"] is fixture["expected_satisfies_allow"], (
            fixture["id"],
            result,
        )
        assert result["blocks_automation"] is fixture["expected_blocks_automation"], (
            fixture["id"],
            result,
        )
        expected_violation = fixture.get("expected_authority_violation")
        if expected_violation:
            assert expected_violation in result["violations"], (fixture["id"], result)


@pytest.mark.parametrize("fixture_id", sorted(REQUIRED_REJECTION_FIXTURES))
def test_required_rejection_fixture_fails_closed(
    policy: dict[str, Any], fixture_id: str
) -> None:
    fixture = next(
        item for item in policy["decision_fixtures"] if item["id"] == fixture_id
    )
    result = evaluate_fixture(policy, fixture)
    assert fixture["expected_satisfies_allow"] is False
    assert result["satisfies_allow"] is False
    assert result["blocks_automation"] is True


def test_positive_allow_fixture_requires_authorization_and_freshness(
    policy: dict[str, Any],
) -> None:
    fixture = next(
        item
        for item in policy["decision_fixtures"]
        if item["id"] == "allow_fresh_exact_candidate_all_required_pass"
    )
    result = evaluate_fixture(policy, fixture)
    assert result["satisfies_allow"] is True
    assert result["blocks_automation"] is False
    assert fixture["authority_kind"] == "authorization"
    assert fixture["analysis_outcome"] == "PROVED"
    assert fixture["fresh_critical_inputs"] is True


def test_mutated_allow_without_freshness_is_rejected(policy: dict[str, Any]) -> None:
    honest = next(
        item
        for item in policy["decision_fixtures"]
        if item["id"] == "allow_fresh_exact_candidate_all_required_pass"
    )
    stale = dict(honest)
    stale["fresh_critical_inputs"] = False
    result = evaluate_fixture(policy, stale)
    assert result["satisfies_allow"] is False
    assert "stale_critical_allow" in result["violations"]


def test_mutated_heuristic_cannot_mint_allow(policy: dict[str, Any]) -> None:
    result = evaluate_fixture(
        policy,
        {
            "analysis_outcome": "PROVED",
            "authority_kind": "heuristic",
            "transaction_verdict": "ALLOW",
            "fresh_critical_inputs": True,
            "heuristic_only": True,
            "exact_designation_hit": False,
            "required_obligation_disproved": False,
        },
    )
    assert result["satisfies_allow"] is False
    assert "heuristic_sole_allow" in result["violations"]


# ---------------------------------------------------------------------------
# Human documents cover normative terms
# ---------------------------------------------------------------------------


def test_authority_document_covers_normative_vocabulary(
    authority_doc: str, policy: dict[str, Any]
) -> None:
    for interface in CONCEPTUAL_INTERFACES:
        assert f"`{interface}`" in authority_doc
    for outcome in ANALYSIS_OUTCOMES:
        assert f"`{outcome}`" in authority_doc
    for verdict in ("ALLOW", "REVIEW", "DENY"):
        assert f"`{verdict}`" in authority_doc
    for kind in AUTHORITY_KINDS:
        assert f"`{kind}`" in authority_doc or kind in authority_doc
    for phrase in (
        "fail closed",
        "guilt by association",
        "universal security",
        "EvidenceFreshness",
        "one-use capability",
        "Narrow evidence-bound claims",
    ):
        assert phrase.casefold() in authority_doc.casefold()
    assert policy["claim_rule"].split(".")[0] in authority_doc or (
        "Narrow evidence-bound claims are preferable" in authority_doc
    )
    assert "crypto-ir-authority-policy-v1" in authority_doc
    assert policy["policy_version"] in authority_doc


def test_threat_model_covers_tcb_adversaries_and_fail_closed(
    threat_doc: str, policy: dict[str, Any]
) -> None:
    for interface in CONCEPTUAL_INTERFACES:
        assert f"`{interface}`" in threat_doc
    for outcome in ANALYSIS_OUTCOMES:
        assert f"`{outcome}`" in threat_doc
    for phrase in (
        "Trusted computing base",
        "fail closed",
        "guilt by association",
        "universal security",
        "Transaction substitution",
        "Non-goals",
        "one-use capability",
        "CRYPTOIR-G010",
        "crypto-ir-authority-policy-v1",
    ):
        assert phrase.casefold() in threat_doc.casefold()
    assert policy["policy_version"] in threat_doc
    assert "AUTHORITY_AND_POLICY.md" in threat_doc
    # Pin table present
    for revision in PINNED_BASELINE.values():
        assert revision in threat_doc


def test_claim_rule_prefers_narrow_evidence_bound_claims(
    policy: dict[str, Any], threat_doc: str
) -> None:
    claim_rule = policy["claim_rule"]
    assert "Narrow evidence-bound claims are preferable" in claim_rule
    assert "cannot prove" in claim_rule
    assert "Narrow evidence-bound claims are preferable" in threat_doc
