"""CRYPTOIR-G400 sanctions authority, evidence, and policy contract tests."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.crypto_ir.compliance import (
    AssociationEvidence,
    AssociationKind,
    ComplianceModelError,
    DesignationRecord,
    DigitalCurrencyIdentifier,
    Jurisdiction,
    LegalPolicyApproval,
    LicenseDisposition,
    LicenseRecord,
    OwnershipEvidence,
    OwnershipInterest,
    OwnershipKind,
    PolicyRule,
    SanctionsAuthority,
    SanctionsList,
    SanctionsMatch,
    SanctionsPolicy,
    SanctionsPolicyOutcome,
    SanctionsProgram,
    SanctionsScreeningRequest,
    SanctionsSnapshot,
    evaluate_sanctions_policy,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import SanctionsMatchLevel


PACKAGE_ROOT = Path(__file__).resolve().parents[5]
POLICY_DOC = PACKAGE_ROOT / "docs/crypto_ir/SANCTIONS_POLICY.md"
HASH_A = "sha256:" + ("a1" * 32)
HASH_B = "sha256:" + ("b2" * 32)
HASH_C = "sha256:" + ("c3" * 32)
AT_TIME = "2026-07-15T12:00:00Z"


def _identifier(address: str = "0x1234") -> DigitalCurrencyIdentifier:
    return DigitalCurrencyIdentifier(
        identifier_id=f"identifier:{address.removeprefix('0x')}",
        chain_namespace="eip155",
        network="ethereum-mainnet",
        address=address,
        asset_reference="eth",
    )


def _designation() -> DesignationRecord:
    return DesignationRecord(
        designation_id="designation:1",
        party_id="party:blocked",
        primary_name="Fixture Blocked Party",
        authority_id="authority:fixture",
        program_ids=("program:alpha",),
        jurisdiction_codes=("XZ",),
        identifiers=(_identifier(),),
        aliases=("Fixture Alias",),
        effective_from="2026-01-01T00:00:00Z",
        effective_until="2027-01-01T00:00:00Z",
    )


def _snapshot(*, complete: bool = True) -> SanctionsSnapshot:
    authority = SanctionsAuthority(
        authority_id="authority:fixture",
        name="Fixture Sanctions Authority",
        jurisdiction=Jurisdiction(code="XZ", name="Fixture Jurisdiction"),
        source_uri="https://authority.invalid/list",
    )
    return SanctionsSnapshot(
        snapshot_id="snapshot:2026-07-15",
        authority=authority,
        sanctions_list=SanctionsList(
            list_id="list:fixture",
            name="Fixture Designated Parties List",
            authority_id=authority.authority_id,
        ),
        programs=(
            SanctionsProgram(
                program_id="program:alpha",
                name="Fixture Program",
                authority_id=authority.authority_id,
            ),
        ),
        jurisdictions=(Jurisdiction(code="XZ", name="Fixture Jurisdiction"),),
        revision="revision:2026-07-15",
        published_at="2026-07-15T00:00:00Z",
        effective_at="2026-07-15T00:00:00Z",
        retrieved_at="2026-07-15T00:05:00Z",
        content_digest=HASH_A,
        designations=(_designation(),),
        complete=complete,
    )


def _rules() -> tuple[PolicyRule, ...]:
    outcomes = {
        SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER: SanctionsPolicyOutcome.DENY,
        SanctionsMatchLevel.NAMED_DESIGNATED_PARTY: SanctionsPolicyOutcome.DENY,
        SanctionsMatchLevel.OWNED_ENTITY: SanctionsPolicyOutcome.DENY,
        SanctionsMatchLevel.DIRECT_ASSOCIATION: SanctionsPolicyOutcome.REVIEW,
        SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE: (
            SanctionsPolicyOutcome.REVIEW
        ),
        SanctionsMatchLevel.HEURISTIC_ASSOCIATION: SanctionsPolicyOutcome.REVIEW,
        SanctionsMatchLevel.NO_MATCH: SanctionsPolicyOutcome.ALLOW,
    }
    return tuple(
        PolicyRule(
            level=level,
            outcome=outcome,
            reason_code=f"fixture.{level.value}",
        )
        for level, outcome in outcomes.items()
    )


def _policy(
    *,
    approved: bool = True,
    threshold: int = 5_000,
    revision: str = "revision:1",
) -> SanctionsPolicy:
    draft = SanctionsPolicy(
        policy_id="policy:fixture",
        revision=revision,
        jurisdiction_code="XZ",
        authority_ids=("authority:fixture",),
        list_ids=("list:fixture",),
        program_ids=("program:alpha",),
        rules=_rules(),
        ownership_threshold_basis_points=threshold,
        maximum_snapshot_age_seconds=86_400,
        license_disposition=LicenseDisposition.APPLY_POLICY_RULE,
        license_outcome=SanctionsPolicyOutcome.REVIEW,
        outcome_precedence=(
            SanctionsPolicyOutcome.ALLOW,
            SanctionsPolicyOutcome.REVIEW,
            SanctionsPolicyOutcome.DENY,
            SanctionsPolicyOutcome.INCONCLUSIVE,
            SanctionsPolicyOutcome.STALE,
            SanctionsPolicyOutcome.ERROR,
        ),
        effective_from="2026-01-01T00:00:00Z",
        effective_until="2027-01-01T00:00:00Z",
    )
    if not approved:
        return draft
    approval = LegalPolicyApproval(
        approval_id=f"approval:{revision}",
        legal_owner_id="legal-owner:fixture",
        policy_id=draft.policy_id,
        policy_revision=draft.revision,
        rules_digest=draft.rules_digest,
        approved_at="2025-12-15T00:00:00Z",
        effective_from="2026-01-01T00:00:00Z",
        effective_until="2027-01-01T00:00:00Z",
        approval_artifact_digest=HASH_C,
        production_enforcement=True,
    )
    return dataclasses.replace(draft, approval=approval)


def _request(**overrides: object) -> SanctionsScreeningRequest:
    payload = {
        "request_id": "request:1",
        "subject_party_id": "party:subject",
        "at_time": AT_TIME,
        "activity_id": "activity:transfer",
        "snapshot": _snapshot(),
        "production_enforcement": True,
    }
    payload.update(overrides)
    return SanctionsScreeningRequest(**payload)  # type: ignore[arg-type]


def _ownership(
    *basis_points: int,
    complete: bool = True,
) -> OwnershipEvidence:
    interests = tuple(
        OwnershipInterest(
            owner_party_id=f"party:owner:{index}",
            ownership_basis_points=value,
            designation_ids=("designation:1",),
        )
        for index, value in enumerate(basis_points, start=1)
    )
    return OwnershipEvidence(
        evidence_id=f"ownership:{len(interests)}",
        subject_party_id="party:subject",
        kind=OwnershipKind.ENTITY if len(interests) == 1 else OwnershipKind.AGGREGATE,
        interests=interests,
        source_digests=(HASH_B,),
        observed_at="2026-07-15T01:00:00Z",
        effective_from="2026-07-01T00:00:00Z",
        effective_until="2026-08-01T00:00:00Z",
        complete=complete,
    )


def _association(kind: AssociationKind) -> AssociationEvidence:
    return AssociationEvidence(
        evidence_id=f"association:{kind.value}",
        kind=kind,
        subject_party_id="party:subject",
        target_party_id="party:blocked",
        source_digests=(HASH_B,),
        observed_at="2026-07-15T01:00:00Z",
        complete=True,
        path_depth=2 if kind is AssociationKind.BOUNDED_INDIRECT else 1,
        exposure_basis_points=250,
    )


def test_typed_snapshot_is_frozen_content_addressed_and_round_trippable() -> None:
    snapshot = _snapshot()
    assert SanctionsSnapshot.from_dict(snapshot.to_dict()) == snapshot
    assert snapshot.identity == SanctionsSnapshot.from_dict(snapshot.to_dict()).identity
    assert snapshot.authority.jurisdiction.code == "XZ"
    assert snapshot.sanctions_list.authority_id == snapshot.authority.authority_id
    assert snapshot.designations[0].program_ids == ("program:alpha",)
    assert snapshot.designations[0].is_effective_at(AT_TIME)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.revision = "replacement"  # type: ignore[misc]
    payload = snapshot.to_dict()
    payload["live_fetch"] = True
    with pytest.raises(ComplianceModelError, match="unknown"):
        SanctionsSnapshot.from_dict(payload)


def test_list_authority_policy_authority_and_result_authority_are_distinct() -> None:
    snapshot = _snapshot()
    policy = _policy()
    decision = evaluate_sanctions_policy(policy, _request())
    assert snapshot.LAYER.value == "evidence"
    assert policy.approval is not None
    assert policy.approval.LAYER.value == "authorization"
    assert policy.approval.can_authorize_transaction() is False
    assert decision.LAYER.value == "result"
    assert decision.is_legal_certification is False
    assert decision.can_authorize_transaction() is False


def test_policy_requires_closed_non_interchangeable_rule_levels() -> None:
    rules = _rules()[:-1]
    with pytest.raises(ComplianceModelError, match="every evidence level"):
        dataclasses.replace(_policy(approved=False), rules=rules)
    assert {
        rule.level for rule in _policy().rules
    } == {
        SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
        SanctionsMatchLevel.NAMED_DESIGNATED_PARTY,
        SanctionsMatchLevel.OWNED_ENTITY,
        SanctionsMatchLevel.DIRECT_ASSOCIATION,
        SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE,
        SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
        SanctionsMatchLevel.NO_MATCH,
    }


def test_match_evidence_references_cannot_be_relabelled() -> None:
    with pytest.raises(ComplianceModelError, match="association cannot cite"):
        SanctionsMatch(
            match_id="match:confused",
            level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
            subject_party_id="party:subject",
            snapshot_id="snapshot:1",
            designation_ids=("designation:1",),
            identifier_id="identifier:1",
            association_evidence_id="association:1",
        )
    with pytest.raises(ComplianceModelError, match="named party cannot cite"):
        SanctionsMatch(
            match_id="match:confused-name",
            level=SanctionsMatchLevel.NAMED_DESIGNATED_PARTY,
            subject_party_id="party:subject",
            snapshot_id="snapshot:1",
            designation_ids=("designation:1",),
            association_evidence_id="association:1",
        )


def test_legal_owner_approval_binds_exact_versioned_rule_inputs() -> None:
    approved = _policy()
    assert approved.approval is not None
    assert approved.approval.rules_digest == approved.rules_digest
    changed_rule = PolicyRule(
        level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
        outcome=SanctionsPolicyOutcome.ALLOW,
        reason_code="fixture.changed",
    )
    changed_rules = tuple(
        changed_rule
        if item.level is SanctionsMatchLevel.HEURISTIC_ASSOCIATION
        else item
        for item in approved.rules
    )
    with pytest.raises(ComplianceModelError, match="exact policy rules digest"):
        dataclasses.replace(approved, rules=changed_rules)


def test_missing_legal_policy_authority_blocks_production_enforcement() -> None:
    decision = evaluate_sanctions_policy(_policy(approved=False), _request())
    assert decision.outcome is SanctionsPolicyOutcome.INCONCLUSIVE
    assert decision.reason_codes == ("missing_legal_policy_authority",)
    assert decision.legal_policy_authority_present is False
    assert decision.production_policy_enforceable is False


def test_allow_is_bound_to_named_policy_and_snapshot_not_legal_certification() -> None:
    policy = _policy()
    decision = evaluate_sanctions_policy(policy, _request())
    assert decision.outcome is SanctionsPolicyOutcome.ALLOW
    assert decision.policy_id == policy.policy_id
    assert decision.policy_revision == policy.revision
    assert decision.policy_rules_digest == policy.rules_digest
    assert decision.snapshot_id == _snapshot().snapshot_id
    assert decision.snapshot_revision == _snapshot().revision
    assert decision.matched_levels == ()
    assert decision.reason_codes == ("fixture.no_match",)
    assert not decision.is_legal_certification
    assert SanctionsDecision_round_trip(decision)


def SanctionsDecision_round_trip(decision: object) -> bool:
    """Keep the round-trip assertion readable in the acceptance test."""

    from ipfs_datasets_py.logic.crypto_ir.compliance import SanctionsDecision

    assert isinstance(decision, SanctionsDecision)
    return SanctionsDecision.from_dict(decision.to_dict()) == decision


def test_exact_identifier_and_named_party_remain_separate_matches() -> None:
    request = _request(
        identifiers=(_identifier(),),
        asserted_party_ids=("party:blocked",),
    )
    decision = evaluate_sanctions_policy(_policy(), request)
    assert decision.outcome is SanctionsPolicyOutcome.DENY
    assert set(decision.matched_levels) == {
        SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
        SanctionsMatchLevel.NAMED_DESIGNATED_PARTY,
    }
    by_level = {match.level: match for match in decision.matches}
    assert by_level[SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER].identifier_id
    assert not by_level[
        SanctionsMatchLevel.NAMED_DESIGNATED_PARTY
    ].identifier_id


def test_ownership_threshold_is_versioned_input_not_universal_conclusion() -> None:
    evidence = _ownership(2_000, 2_000)
    below_policy = evaluate_sanctions_policy(
        _policy(threshold=5_000),
        _request(ownership_evidence=(evidence,)),
    )
    assert below_policy.outcome is SanctionsPolicyOutcome.ALLOW
    assert SanctionsMatchLevel.OWNED_ENTITY not in below_policy.matched_levels

    lower_reviewed_threshold = evaluate_sanctions_policy(
        _policy(threshold=3_000, revision="revision:lower-threshold"),
        _request(ownership_evidence=(evidence,)),
    )
    assert lower_reviewed_threshold.outcome is SanctionsPolicyOutcome.DENY
    assert SanctionsMatchLevel.OWNED_ENTITY in (
        lower_reviewed_threshold.matched_levels
    )
    match = lower_reviewed_threshold.matches[0]
    assert match.ownership_evidence_id == evidence.evidence_id
    assert match.level is SanctionsMatchLevel.OWNED_ENTITY


@pytest.mark.parametrize(
    ("kind", "expected_level"),
    [
        (AssociationKind.DIRECT, SanctionsMatchLevel.DIRECT_ASSOCIATION),
        (
            AssociationKind.BOUNDED_INDIRECT,
            SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE,
        ),
        (AssociationKind.HEURISTIC, SanctionsMatchLevel.HEURISTIC_ASSOCIATION),
    ],
)
def test_association_evidence_classes_are_non_interchangeable(
    kind: AssociationKind,
    expected_level: SanctionsMatchLevel,
) -> None:
    evidence = _association(kind)
    decision = evaluate_sanctions_policy(
        _policy(), _request(association_evidence=(evidence,))
    )
    assert decision.outcome is SanctionsPolicyOutcome.REVIEW
    assert decision.matched_levels == (expected_level,)
    assert decision.matches[0].association_evidence_id == evidence.evidence_id
    assert decision.matches[0].designation_ids == ("designation:1",)


def test_incomplete_ownership_evidence_fails_closed_without_owned_conclusion() -> None:
    decision = evaluate_sanctions_policy(
        _policy(), _request(ownership_evidence=(_ownership(10_000, complete=False),))
    )
    assert decision.outcome is SanctionsPolicyOutcome.INCONCLUSIVE
    assert decision.reason_codes == ("incomplete_ownership_evidence",)
    assert SanctionsMatchLevel.OWNED_ENTITY not in decision.matched_levels


def test_license_is_scoped_typed_and_policy_selected() -> None:
    license_record = LicenseRecord(
        license_id="license:fixture",
        authority_id="authority:fixture",
        license_type="specific",
        subject_party_ids=("party:subject",),
        program_ids=("program:alpha",),
        jurisdiction_codes=("XZ",),
        activity_ids=("activity:transfer",),
        effective_from="2026-07-01T00:00:00Z",
        effective_until="2026-08-01T00:00:00Z",
        approval_artifact_digest=HASH_C,
    )
    decision = evaluate_sanctions_policy(
        _policy(),
        _request(
            identifiers=(_identifier(),),
            licenses=(license_record,),
        ),
    )
    # The reviewed precedence says DENY outranks the reviewed license REVIEW;
    # the engine does not invent an exemption.
    assert decision.outcome is SanctionsPolicyOutcome.DENY
    assert decision.applicable_license_ids == ("license:fixture",)
    assert "applicable_scoped_license" in decision.reason_codes

    wrong_activity = dataclasses.replace(
        license_record, activity_ids=("activity:withdraw",)
    )
    no_license = evaluate_sanctions_policy(
        _policy(),
        _request(identifiers=(_identifier(),), licenses=(wrong_activity,)),
    )
    assert no_license.applicable_license_ids == ()


def test_stale_or_incomplete_snapshot_fails_closed() -> None:
    stale_request = _request(at_time="2026-07-20T12:00:00Z")
    stale = evaluate_sanctions_policy(_policy(), stale_request)
    assert stale.outcome is SanctionsPolicyOutcome.STALE
    assert stale.reason_codes == ("stale_snapshot",)

    incomplete = evaluate_sanctions_policy(
        _policy(), _request(snapshot=_snapshot(complete=False))
    )
    assert incomplete.outcome is SanctionsPolicyOutcome.INCONCLUSIVE
    assert incomplete.reason_codes == ("incomplete_snapshot",)


def test_human_review_document_states_normative_boundaries() -> None:
    text = POLICY_DOC.read_text(encoding="utf-8")
    for term in (
        "legal-owner",
        "versioned",
        "rules digest",
        "Exact listed identifier",
        "Named designated party",
        "Evidence-backed ownership",
        "Direct association",
        "Bounded indirect exposure",
        "Heuristic association",
        "not a legal certification",
        "do not fetch live lists",
    ):
        assert term in text
