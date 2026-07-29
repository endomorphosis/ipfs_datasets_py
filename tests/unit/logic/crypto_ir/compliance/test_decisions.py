"""CRYPTOIR-G440 explainable compliance decisions and immutable receipts.

Acceptance coverage:

* Decisions bind counterparties, list/graph/entity/ownership/license/policy
  revisions, path evidence, bounds, freshness, uncertainty, reasons, expiry.
* Deterministic precedence prevents permissive downgrade.
* Heuristic evidence can request REVIEW but cannot create designation or ALLOW.
* Receipts reproduce byte-for-byte.
* Explanations cover both the decision and its evidentiary boundary.
"""

from __future__ import annotations

import dataclasses

import pytest

from ipfs_datasets_py.logic.crypto_ir.compliance.decisions import (
    COMPLIANCE_DECISION_SCHEMA_VERSION,
    AuthorityClaim,
    ComplianceDecision,
    DecisionError,
    DecisionReason,
    EvidenceBindings,
    EvidenceChannel,
    PolicyCombiner,
    PolicyFactor,
    emit_compliance_decision,
    factor_from_sanctions_outcome,
    outcome_severity,
)
from ipfs_datasets_py.logic.crypto_ir.compliance.explain import (
    ComplianceExplanation,
    explain_decision,
    explain_evidentiary_boundary,
    explain_factors,
)
from ipfs_datasets_py.logic.crypto_ir.compliance.models import SanctionsPolicyOutcome
from ipfs_datasets_py.logic.crypto_ir.compliance.receipts import (
    ComplianceReceipt,
    ReceiptError,
    assert_receipt_byte_identical,
    issue_compliance_receipt,
    reproduce_receipt_bytes,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import SanctionsMatchLevel
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes


HASH_A = "sha256:" + ("a1" * 32)
HASH_B = "sha256:" + ("b2" * 32)
AT_TIME = "2026-07-15T12:00:00Z"
EXPIRES = "2026-07-15T12:05:00Z"
ISSUED = "2026-07-15T12:00:01Z"


def _bindings(**overrides: object) -> EvidenceBindings:
    payload: dict[str, object] = {
        "counterparty_ids": ("party:counterparty-a", "addr:0xabc"),
        "list_snapshot_id": "snapshot:2026-07-15",
        "list_revision": "revision:2026-07-15",
        "graph_snapshot_id": "graph:snap-1",
        "graph_digest": HASH_A,
        "entity_ids": ("entity:subject",),
        "ownership_evidence_ids": (),
        "license_ids": (),
        "policy_id": "policy:fixture",
        "policy_revision": "revision:1",
        "policy_rules_digest": HASH_B,
        "path_ids": (),
        "bound_max_depth": 3,
        "bound_max_nodes": 256,
        "bound_max_edges": 512,
        "freshness_checked_at": AT_TIME,
        "max_snapshot_age_seconds": 86_400,
        "snapshot_age_seconds": 300,
        "uncertainty_codes": (),
        "effective_at": AT_TIME,
        "expires_at": EXPIRES,
        "subject_party_id": "party:subject",
        "request_id": "request:1",
        "activity_id": "activity:transfer",
    }
    payload.update(overrides)
    return EvidenceBindings(**payload)  # type: ignore[arg-type]


def _direct_deny_factor() -> PolicyFactor:
    return factor_from_sanctions_outcome(
        factor_id="factor:direct-list",
        channel=EvidenceChannel.DIRECT_LIST,
        outcome=SanctionsPolicyOutcome.DENY,
        reason_code="exact_listed_identifier",
        match_level=SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
        evidence_ids=("designation:1",),
        counterparty_ids=("addr:0xabc",),
        human_detail="Exact listed digital-currency identifier matched.",
        machine_detail="identifier=addr:0xabc",
        authority_claim=AuthorityClaim.NONE,
    )


def _ownership_deny_factor() -> PolicyFactor:
    return factor_from_sanctions_outcome(
        factor_id="factor:ownership",
        channel=EvidenceChannel.PARTY_OWNERSHIP,
        outcome=SanctionsPolicyOutcome.DENY,
        reason_code="owned_entity_threshold",
        match_level=SanctionsMatchLevel.OWNED_ENTITY,
        evidence_ids=("ownership:1",),
        human_detail="Ownership evidence met the policy threshold.",
    )


def _bounded_flow_review_factor() -> PolicyFactor:
    return factor_from_sanctions_outcome(
        factor_id="factor:bounded-flow",
        channel=EvidenceChannel.BOUNDED_FLOW,
        outcome=SanctionsPolicyOutcome.REVIEW,
        reason_code="bounded_indirect_exposure",
        match_level=SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE,
        path_ids=("path:1",),
        human_detail="Bounded-flow path found within policy bounds.",
        authority_claim=AuthorityClaim.REVIEW_ONLY,
    )


def _heuristic_review_factor() -> PolicyFactor:
    return factor_from_sanctions_outcome(
        factor_id="factor:heuristic",
        channel=EvidenceChannel.HEURISTIC,
        outcome=SanctionsPolicyOutcome.REVIEW,
        reason_code="heuristic_association",
        match_level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
        human_detail="Heuristic cluster signal for review prioritization only.",
        authority_claim=AuthorityClaim.REVIEW_ONLY,
    )


def _fresh_allow_factor() -> PolicyFactor:
    return factor_from_sanctions_outcome(
        factor_id="factor:no-match",
        channel=EvidenceChannel.DIRECT_LIST,
        outcome=SanctionsPolicyOutcome.ALLOW,
        reason_code="no_match",
        match_level=SanctionsMatchLevel.NO_MATCH,
        human_detail="No direct-list match under the bound snapshot.",
    )


# ---------------------------------------------------------------------------
# PolicyCombiner precedence and fail-closed combination
# ---------------------------------------------------------------------------


def test_outcome_severity_orders_fail_closed() -> None:
    assert outcome_severity(SanctionsPolicyOutcome.ALLOW) < outcome_severity(
        SanctionsPolicyOutcome.REVIEW
    )
    assert outcome_severity(SanctionsPolicyOutcome.REVIEW) < outcome_severity(
        SanctionsPolicyOutcome.INCONCLUSIVE
    )
    assert outcome_severity(SanctionsPolicyOutcome.STALE) < outcome_severity(
        SanctionsPolicyOutcome.ERROR
    )
    assert outcome_severity(SanctionsPolicyOutcome.ERROR) < outcome_severity(
        SanctionsPolicyOutcome.DENY
    )


def test_combiner_prefers_deny_over_allow() -> None:
    combiner = PolicyCombiner.default()
    outcome, factors = combiner.combine(
        (_fresh_allow_factor(), _direct_deny_factor())
    )
    assert outcome is SanctionsPolicyOutcome.DENY
    assert len(factors) == 2


def test_combiner_prefers_stale_over_allow() -> None:
    combiner = PolicyCombiner.default()
    stale = factor_from_sanctions_outcome(
        factor_id="factor:stale",
        channel=EvidenceChannel.FRESHNESS,
        outcome=SanctionsPolicyOutcome.STALE,
        reason_code="stale_snapshot",
        human_detail="Snapshot age exceeded policy maximum.",
    )
    outcome, _ = combiner.combine((_fresh_allow_factor(), stale))
    assert outcome is SanctionsPolicyOutcome.STALE


def test_combiner_prefers_error_over_review() -> None:
    combiner = PolicyCombiner.default()
    error = factor_from_sanctions_outcome(
        factor_id="factor:error",
        channel=EvidenceChannel.UNCERTAINTY,
        outcome=SanctionsPolicyOutcome.ERROR,
        reason_code="evaluation_error",
    )
    outcome, _ = combiner.combine((_heuristic_review_factor(), error))
    assert outcome is SanctionsPolicyOutcome.ERROR


def test_combiner_assert_no_downgrade_refuses_permissive_replacement() -> None:
    combiner = PolicyCombiner.default()
    with pytest.raises(DecisionError, match="permissive downgrade"):
        combiner.assert_no_downgrade(
            SanctionsPolicyOutcome.DENY, SanctionsPolicyOutcome.ALLOW
        )
    combiner.assert_no_downgrade(
        SanctionsPolicyOutcome.ALLOW, SanctionsPolicyOutcome.DENY
    )


def test_combiner_rules_digest_stable() -> None:
    a = PolicyCombiner.default()
    b = PolicyCombiner.from_dict(a.to_dict())
    assert a.rules_digest == b.rules_digest
    assert a.rules_digest.startswith("sha256:")


def test_combiner_rejects_incomplete_precedence() -> None:
    with pytest.raises(DecisionError, match="every SanctionsPolicyOutcome"):
        PolicyCombiner(
            combiner_id="policy-combiner:bad",
            revision="revision:1",
            outcome_precedence=(SanctionsPolicyOutcome.ALLOW,),
        )


def test_uncertainty_factor_blocks_allow() -> None:
    combiner = PolicyCombiner.default()
    uncertain = dataclasses.replace(_fresh_allow_factor(), uncertainty=True)
    outcome, _ = combiner.combine((uncertain,))
    assert outcome is SanctionsPolicyOutcome.INCONCLUSIVE


# ---------------------------------------------------------------------------
# Heuristic authority bounds
# ---------------------------------------------------------------------------


def test_heuristic_cannot_claim_designation() -> None:
    with pytest.raises(DecisionError, match="designation"):
        PolicyFactor(
            factor_id="factor:bad-heuristic",
            channel=EvidenceChannel.HEURISTIC,
            outcome=SanctionsPolicyOutcome.REVIEW,
            authority_claim=AuthorityClaim.DESIGNATION,
            reasons=(
                DecisionReason(
                    reason_id="reason:h",
                    code="heuristic_association",
                    channel=EvidenceChannel.HEURISTIC,
                    outcome=SanctionsPolicyOutcome.REVIEW,
                    match_level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
                ),
            ),
        )


def test_heuristic_cannot_claim_allow_authority() -> None:
    with pytest.raises(DecisionError, match="allow authority"):
        PolicyFactor(
            factor_id="factor:bad-allow-claim",
            channel=EvidenceChannel.HEURISTIC,
            outcome=SanctionsPolicyOutcome.REVIEW,
            authority_claim=AuthorityClaim.ALLOW,
            reasons=(
                DecisionReason(
                    reason_id="reason:h",
                    code="heuristic_association",
                    channel=EvidenceChannel.HEURISTIC,
                    outcome=SanctionsPolicyOutcome.REVIEW,
                    match_level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
                ),
            ),
        )


def test_heuristic_cannot_alone_produce_allow() -> None:
    with pytest.raises(DecisionError, match="cannot alone produce ALLOW"):
        PolicyFactor(
            factor_id="factor:heuristic-allow",
            channel=EvidenceChannel.HEURISTIC,
            outcome=SanctionsPolicyOutcome.ALLOW,
            reasons=(
                DecisionReason(
                    reason_id="reason:h",
                    code="heuristic_association",
                    channel=EvidenceChannel.HEURISTIC,
                    outcome=SanctionsPolicyOutcome.ALLOW,
                    match_level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
                ),
            ),
        )


def test_heuristic_only_decision_is_review_not_deny_or_allow() -> None:
    # Heuristic factor with REVIEW is fine; pure heuristic DENY is forced to REVIEW.
    denyish = factor_from_sanctions_outcome(
        factor_id="factor:heuristic-denyish",
        channel=EvidenceChannel.HEURISTIC,
        outcome=SanctionsPolicyOutcome.REVIEW,
        reason_code="heuristic_association",
        match_level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
        authority_claim=AuthorityClaim.REVIEW_ONLY,
    )
    # Build a factor that tries DENY via channel HEURISTIC — construction allows
    # DENY outcome on the factor only if not pure-heuristic ALLOW; DENY on
    # heuristic is allowed at factor level but emit downgrades.
    heuristic_deny = PolicyFactor(
        factor_id="factor:heuristic-deny",
        channel=EvidenceChannel.HEURISTIC,
        outcome=SanctionsPolicyOutcome.DENY,
        authority_claim=AuthorityClaim.REVIEW_ONLY,
        reasons=(
            DecisionReason(
                reason_id="reason:hd",
                code="heuristic_association",
                channel=EvidenceChannel.HEURISTIC,
                outcome=SanctionsPolicyOutcome.DENY,
                match_level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
            ),
        ),
    )
    decision = emit_compliance_decision(
        (heuristic_deny,),
        _bindings(),
    )
    assert decision.heuristic_only is True
    assert decision.outcome is SanctionsPolicyOutcome.REVIEW
    assert decision.declares_designation is False
    assert "heuristic_review_only" in decision.reason_codes or any(
        r.code == "heuristic_association" for r in decision.reasons
    )


def test_bounded_flow_cannot_claim_designation() -> None:
    with pytest.raises(DecisionError, match="designation"):
        PolicyFactor(
            factor_id="factor:flow-desig",
            channel=EvidenceChannel.BOUNDED_FLOW,
            outcome=SanctionsPolicyOutcome.REVIEW,
            authority_claim=AuthorityClaim.DESIGNATION,
            reasons=(
                DecisionReason(
                    reason_id="reason:f",
                    code="bounded_indirect_exposure",
                    channel=EvidenceChannel.BOUNDED_FLOW,
                    outcome=SanctionsPolicyOutcome.REVIEW,
                    match_level=SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE,
                ),
            ),
        )


def test_heuristic_reason_may_declare_designation_is_false() -> None:
    reason = DecisionReason(
        reason_id="reason:h",
        code="heuristic_association",
        channel=EvidenceChannel.HEURISTIC,
        outcome=SanctionsPolicyOutcome.REVIEW,
        match_level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
    )
    assert reason.is_heuristic is True
    assert reason.may_declare_designation is False


# ---------------------------------------------------------------------------
# emit_compliance_decision bindings and staleness
# ---------------------------------------------------------------------------


def test_emit_decision_binds_counterparties_and_revisions() -> None:
    decision = emit_compliance_decision(
        (_direct_deny_factor(),),
        _bindings(path_ids=("path:1",), ownership_evidence_ids=("ownership:1",)),
    )
    assert decision.outcome is SanctionsPolicyOutcome.DENY
    assert decision.bindings.counterparty_ids == (
        "party:counterparty-a",
        "addr:0xabc",
    )
    assert decision.bindings.list_snapshot_id == "snapshot:2026-07-15"
    assert decision.bindings.list_revision == "revision:2026-07-15"
    assert decision.bindings.graph_snapshot_id == "graph:snap-1"
    assert decision.bindings.policy_id == "policy:fixture"
    assert decision.bindings.policy_revision == "revision:1"
    assert decision.bindings.path_ids == ("path:1",)
    assert decision.bindings.ownership_evidence_ids == ("ownership:1",)
    assert decision.bindings.bound_max_depth == 3
    assert decision.bindings.expires_at == EXPIRES
    assert decision.bindings.effective_at == AT_TIME
    assert decision.schema_version == COMPLIANCE_DECISION_SCHEMA_VERSION
    assert decision.can_authorize_transaction() is False
    assert decision.is_legal_certification is False
    assert decision.declares_designation is False


def test_emit_decision_stale_when_age_exceeds_max() -> None:
    decision = emit_compliance_decision(
        (_fresh_allow_factor(),),
        _bindings(snapshot_age_seconds=200_000, max_snapshot_age_seconds=86_400),
    )
    assert decision.outcome is SanctionsPolicyOutcome.STALE
    assert "stale_evidence" in decision.reason_codes
    assert decision.bindings.is_fresh is False


def test_emit_decision_stale_does_not_downgrade_deny() -> None:
    decision = emit_compliance_decision(
        (_direct_deny_factor(),),
        _bindings(snapshot_age_seconds=200_000, max_snapshot_age_seconds=86_400),
    )
    # DENY severity is higher than STALE, so deny is preserved.
    assert decision.outcome is SanctionsPolicyOutcome.DENY
    assert "stale_evidence" in decision.reason_codes


def test_emit_decision_uncertainty_blocks_allow() -> None:
    decision = emit_compliance_decision(
        (_fresh_allow_factor(),),
        _bindings(uncertainty_codes=("incomplete_frontier",)),
    )
    assert decision.outcome is SanctionsPolicyOutcome.INCONCLUSIVE
    assert "uncertainty_present" in decision.reason_codes


def test_emit_decision_force_error() -> None:
    decision = emit_compliance_decision(
        (_fresh_allow_factor(),),
        _bindings(),
        force_error=True,
    )
    assert decision.outcome is SanctionsPolicyOutcome.ERROR


def test_emit_decision_deterministic_id() -> None:
    a = emit_compliance_decision((_direct_deny_factor(),), _bindings())
    b = emit_compliance_decision((_direct_deny_factor(),), _bindings())
    assert a.decision_id == b.decision_id
    assert a.content_digest == b.content_digest


def test_combined_direct_and_ownership_and_flow() -> None:
    decision = emit_compliance_decision(
        (
            _direct_deny_factor(),
            _ownership_deny_factor(),
            _bounded_flow_review_factor(),
            _heuristic_review_factor(),
        ),
        _bindings(
            path_ids=("path:1",),
            ownership_evidence_ids=("ownership:1",),
        ),
    )
    assert decision.outcome is SanctionsPolicyOutcome.DENY
    assert len(decision.factors) == 4
    codes = set(decision.reason_codes)
    assert "exact_listed_identifier" in codes
    assert "owned_entity_threshold" in codes


def test_decision_round_trip_dict() -> None:
    decision = emit_compliance_decision((_direct_deny_factor(),), _bindings())
    restored = ComplianceDecision.from_dict(decision.to_dict())
    assert restored.decision_id == decision.decision_id
    assert restored.outcome is decision.outcome
    assert restored.content_digest == decision.content_digest
    assert restored.evidentiary_boundary_digest == decision.evidentiary_boundary_digest


def test_decision_rejects_declares_designation_true() -> None:
    base = emit_compliance_decision((_direct_deny_factor(),), _bindings())
    with pytest.raises(DecisionError, match="never declares designation"):
        ComplianceDecision(
            decision_id=base.decision_id,
            outcome=base.outcome,
            reasons=base.reasons,
            factors=base.factors,
            bindings=base.bindings,
            combiner_id=base.combiner_id,
            combiner_revision=base.combiner_revision,
            combiner_rules_digest=base.combiner_rules_digest,
            declares_designation=True,
        )


def test_bindings_expiry_must_follow_effective() -> None:
    with pytest.raises(DecisionError, match="expires_at"):
        _bindings(effective_at=EXPIRES, expires_at=AT_TIME)


def test_binding_digest_changes_on_substitution() -> None:
    a = _bindings()
    b = _bindings(list_revision="revision:tampered")
    assert a.binding_digest() != b.binding_digest()


# ---------------------------------------------------------------------------
# Explanations: decision + evidentiary boundary
# ---------------------------------------------------------------------------


def test_explain_decision_covers_outcome_and_boundary() -> None:
    decision = emit_compliance_decision(
        (_direct_deny_factor(), _heuristic_review_factor()),
        _bindings(),
    )
    explanation = explain_decision(decision)
    assert isinstance(explanation, ComplianceExplanation)
    assert explanation.outcome is SanctionsPolicyOutcome.DENY
    assert explanation.blocks_automation is True
    assert "DENY" in explanation.human_summary or "deny" in explanation.human_summary
    assert decision.decision_id in explanation.machine_summary
    assert explanation.boundary.scope_summary
    assert any("designate" in c.lower() or "designation" in c.lower() for c in explanation.boundary.non_claims)
    assert "list_revision" in explanation.boundary.substitution_invalidates
    assert explanation.boundary.bound_fields["list_snapshot_id"] == "snapshot:2026-07-15"
    assert explanation.boundary.bound_fields["binding_digest"] == decision.evidentiary_boundary_digest


def test_explain_allow_does_not_block_when_allow() -> None:
    decision = emit_compliance_decision((_fresh_allow_factor(),), _bindings())
    explanation = explain_decision(decision)
    assert decision.outcome is SanctionsPolicyOutcome.ALLOW
    assert explanation.blocks_automation is False


def test_explain_evidentiary_boundary_standalone() -> None:
    boundary = explain_evidentiary_boundary(_bindings())
    assert "counterparties" in boundary.scope_summary
    assert boundary.bound_fields["policy_id"] == "policy:fixture"
    assert "Does not authorize" in " ".join(boundary.non_claims)


def test_explain_factors_lists_channels() -> None:
    summaries = explain_factors((_direct_deny_factor(), _heuristic_review_factor()))
    assert len(summaries) == 2
    assert "direct list" in summaries[0]
    assert "heuristic" in summaries[1]


def test_explanation_round_trip() -> None:
    decision = emit_compliance_decision((_bounded_flow_review_factor(),), _bindings())
    explanation = explain_decision(decision)
    restored = ComplianceExplanation.from_dict(explanation.to_dict())
    assert restored.decision_id == explanation.decision_id
    assert restored.human_summary == explanation.human_summary
    assert restored.boundary.scope_summary == explanation.boundary.scope_summary


# ---------------------------------------------------------------------------
# Immutable receipts: byte-for-byte reproduction
# ---------------------------------------------------------------------------


def test_receipt_byte_for_byte_reproduction() -> None:
    decision = emit_compliance_decision((_direct_deny_factor(),), _bindings())
    receipt_a = issue_compliance_receipt(decision, issued_at=ISSUED)
    receipt_b = issue_compliance_receipt(decision, issued_at=ISSUED)
    assert receipt_a.canonical_bytes == receipt_b.canonical_bytes
    assert receipt_a.content_digest == receipt_b.content_digest
    assert receipt_a.receipt_id == receipt_b.receipt_id
    assert_receipt_byte_identical(receipt_a, receipt_b)

    reproduced = reproduce_receipt_bytes(receipt_a)
    assert reproduced == receipt_a.canonical_bytes
    assert receipt_a.verify_bytes(reproduced) is True
    assert receipt_a.verify_decision_digest() is True


def test_receipt_round_trip_preserves_bytes() -> None:
    decision = emit_compliance_decision(
        (_ownership_deny_factor(), _bounded_flow_review_factor()),
        _bindings(path_ids=("path:1",), ownership_evidence_ids=("ownership:1",)),
    )
    receipt = issue_compliance_receipt(decision, issued_at=ISSUED)
    restored = ComplianceReceipt.from_dict(receipt.to_dict())
    assert restored.canonical_bytes == receipt.canonical_bytes
    assert restored.content_digest == receipt.content_digest
    assert restored.decision_content_digest == decision.content_digest
    assert restored.evidentiary_boundary_digest == decision.evidentiary_boundary_digest


def test_receipt_canonical_bytes_are_canonical_json() -> None:
    decision = emit_compliance_decision((_fresh_allow_factor(),), _bindings())
    receipt = issue_compliance_receipt(decision, issued_at=ISSUED)
    assert receipt.canonical_bytes == canonical_json_bytes(receipt.receipt_body())
    # Second encoding matches first (no non-determinism).
    assert canonical_json_bytes(receipt.receipt_body()) == receipt.canonical_bytes


def test_receipt_different_issued_at_differs() -> None:
    decision = emit_compliance_decision((_fresh_allow_factor(),), _bindings())
    a = issue_compliance_receipt(decision, issued_at=ISSUED)
    b = issue_compliance_receipt(decision, issued_at="2026-07-15T12:00:02Z")
    assert a.canonical_bytes != b.canonical_bytes
    with pytest.raises(ReceiptError, match="byte-identical"):
        assert_receipt_byte_identical(a, b)


def test_receipt_rejects_digest_mismatch() -> None:
    decision = emit_compliance_decision((_direct_deny_factor(),), _bindings())
    receipt = issue_compliance_receipt(decision, issued_at=ISSUED)
    with pytest.raises(ReceiptError, match="decision_content_digest"):
        ComplianceReceipt(
            receipt_id=receipt.receipt_id,
            decision_id=receipt.decision_id,
            outcome=receipt.outcome,
            decision=decision,
            decision_content_digest=HASH_A,  # wrong
            evidentiary_boundary_digest=receipt.evidentiary_boundary_digest,
            explanation_digest=receipt.explanation_digest,
            issued_at=ISSUED,
        )


def test_receipt_never_authorizes_or_certifies() -> None:
    decision = emit_compliance_decision((_fresh_allow_factor(),), _bindings())
    receipt = issue_compliance_receipt(decision, issued_at=ISSUED)
    assert receipt.can_authorize_transaction() is False
    assert receipt.is_legal_certification is False


def test_decision_content_digest_stable_across_to_dict() -> None:
    decision = emit_compliance_decision((_direct_deny_factor(),), _bindings())
    d1 = decision.content_digest
    d2 = decision.content_digest
    assert d1 == d2
    # to_dict does not change digest.
    _ = decision.to_dict()
    assert decision.content_digest == d1


def test_license_factor_review_combines() -> None:
    license_factor = factor_from_sanctions_outcome(
        factor_id="factor:license",
        channel=EvidenceChannel.LICENSE,
        outcome=SanctionsPolicyOutcome.REVIEW,
        reason_code="applicable_scoped_license",
        human_detail="Scoped license requires policy disposition REVIEW.",
    )
    decision = emit_compliance_decision(
        (_fresh_allow_factor(), license_factor),
        _bindings(license_ids=("license:1",)),
    )
    assert decision.outcome is SanctionsPolicyOutcome.REVIEW
    assert decision.bindings.license_ids == ("license:1",)


def test_ast_symbols_exported() -> None:
    """AST query surface: ComplianceDecision ComplianceReceipt DecisionReason PolicyCombiner."""

    assert ComplianceDecision is not None
    assert ComplianceReceipt is not None
    assert DecisionReason is not None
    assert PolicyCombiner is not None
    assert EvidenceChannel.DIRECT_LIST.value == "direct_list"
    assert EvidenceChannel.HEURISTIC.value == "heuristic"
