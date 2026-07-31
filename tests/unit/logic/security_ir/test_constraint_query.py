"""Unit tests for SecurityConstraintQuery@1 applicability selection.

Covers hard filters (principal/delegation/capability, trust zone, asset/data
class/channel/network/filesystem, action/state/effect/failure/rollback,
sandbox/environment, threat/policy version and freshness), result-authority
family separation, abstract-model/live-environment substitution rejection,
unknown extensions, contradictions, bounded selection, and stale/mismatched
evidence.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    ApplicabilityStatus,
    PremiseSelectionMethod,
)
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
from ipfs_datasets_py.logic.security_ir.constraint_query import (
    SECURITY_APPLICABILITY_EVIDENCE_INTERFACE,
    SECURITY_CONSTRAINT_QUERY_INTERFACE,
    SECURITY_HARD_FILTER_DIMENSIONS,
    SecurityApplicabilityEvidence,
    SecurityArtifactFamily,
    SecurityConstraintDisposition,
    SecurityConstraintEffect,
    SecurityConstraintQuery,
    SecurityConstraintQueryError,
    SecurityConstraintRecord,
    SecurityEnvironmentKind,
    SecurityEvidenceBinding,
    SecurityPremiseTaintStatus,
    SecuritySelectionDisposition,
    select_applicable_security_constraints,
)


DIGEST_A = "sha256:" + ("a" * 64)
DIGEST_B = "sha256:" + ("b" * 64)


def _query(**overrides: object) -> SecurityConstraintQuery:
    base: dict[str, object] = dict(
        query_id="query:wallet-transfer",
        principal_id="principal:alice",
        as_of="2024-06-15T12:00:00Z",
        delegation_ids=("delegation:session-1",),
        capabilities=("cap:transfer",),
        trust_zone="zone:wallet",
        asset_id="asset:xrp",
        data_class="data:payment",
        channel_id="channel:rpc",
        network="network:mainnet",
        filesystem="fs:keystore",
        action="action:sign",
        state="state:unlocked",
        effect="effect:broadcast",
        failure="failure:reject",
        rollback="rollback:abort",
        sandbox_id="sandbox:none",
        environment_kind=SecurityEnvironmentKind.LIVE_ENVIRONMENT,
        environment_id="env:prod-1",
        threat_model_id="threat:wallet-v1",
        threat_model_version="1.0.0",
        policy_id="policy:transfer",
        policy_version="2024.1",
        required_authority=AuthorityKind.EVIDENCE_READINESS,
        artifact_family=SecurityArtifactFamily.EVIDENCE_GATE,
        invocation_digest=DIGEST_A,
        selection_budget=16,
    )
    base.update(overrides)
    return SecurityConstraintQuery(**base)  # type: ignore[arg-type]


def _record(**overrides: object) -> SecurityConstraintRecord:
    base: dict[str, object] = dict(
        constraint_id="sec:require-attestation",
        effect=SecurityConstraintEffect.REQUIRE,
        principals=("principal:alice",),
        delegation_ids=("delegation:session-1",),
        capabilities=("cap:transfer",),
        trust_zones=("zone:wallet",),
        assets=("asset:xrp",),
        data_classes=("data:payment",),
        channels=("channel:rpc",),
        networks=("network:mainnet",),
        filesystems=("fs:keystore",),
        actions=("action:sign",),
        states=("state:unlocked",),
        effects=("effect:broadcast",),
        failures=("failure:reject",),
        rollbacks=("rollback:abort",),
        sandbox_ids=("sandbox:none",),
        environment_kind=SecurityEnvironmentKind.LIVE_ENVIRONMENT,
        environment_ids=("env:prod-1",),
        threat_model_id="threat:wallet-v1",
        threat_model_version="1.0.0",
        policy_id="policy:transfer",
        policy_version="2024.1",
        artifact_family=SecurityArtifactFamily.EVIDENCE_GATE,
        required_authority=AuthorityKind.EVIDENCE_READINESS,
        source_ref_ids=("source:security-policy",),
        provenance_ids=("prov:security-policy",),
        premise_taint=SecurityPremiseTaintStatus.CLEAN,
        trusted_source=True,
        reviewed=True,
        statement="Transfer requires live attestation evidence.",
        conflict_key="wallet-transfer-attestation",
        precedence=10,
        priority=5,
        retrieval_rank=99,
        retrieval_score=0.01,
    )
    base.update(overrides)
    return SecurityConstraintRecord(**base)  # type: ignore[arg-type]


def _evidence(**overrides: object) -> SecurityEvidenceBinding:
    base: dict[str, object] = dict(
        evidence_id="ev:attestation-1",
        artifact_family=SecurityArtifactFamily.EVIDENCE_GATE,
        content_digest=DIGEST_B,
        observed_at="2024-06-15T11:00:00Z",
        environment_kind=SecurityEnvironmentKind.LIVE_ENVIRONMENT,
        environment_id="env:prod-1",
        authority_kind=AuthorityKind.EVIDENCE_READINESS,
        max_age_seconds=7200,
    )
    base.update(overrides)
    return SecurityEvidenceBinding(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Contract shape / immutability
# ---------------------------------------------------------------------------


def test_query_interface_identity_and_roundtrip() -> None:
    query = _query()
    assert query.INTERFACE == SECURITY_CONSTRAINT_QUERY_INTERFACE
    assert query.digest.startswith("sha256:")
    restored = SecurityConstraintQuery.from_json(query.to_json())
    assert restored.digest == query.digest
    assert restored.principal_id == "principal:alice"
    with pytest.raises(FrozenInstanceError):
        query.principal_id = "principal:bob"  # type: ignore[misc]


def test_query_requires_principal_and_as_of() -> None:
    with pytest.raises(SecurityConstraintQueryError):
        SecurityConstraintQuery(query_id="q", principal_id="", as_of="2024-01-01")
    with pytest.raises(SecurityConstraintQueryError):
        SecurityConstraintQuery(
            query_id="q", principal_id="principal:alice", as_of=""
        )
    with pytest.raises(SecurityConstraintQueryError):
        SecurityConstraintQuery(
            query_id="q", principal_id="principal:alice", as_of="not-a-date"
        )


def test_hard_filter_dimensions_are_documented() -> None:
    required = {
        "principal",
        "delegation",
        "capability",
        "trust_zone",
        "asset",
        "data_class",
        "channel",
        "network",
        "filesystem",
        "action",
        "state",
        "effect",
        "failure",
        "rollback",
        "sandbox",
        "environment",
        "threat_model",
        "policy_version",
        "freshness",
        "result_authority",
        "extension",
        "provenance",
        "premise_taint",
    }
    assert required.issubset(set(SECURITY_HARD_FILTER_DIMENSIONS))


def test_selection_budget_must_be_bounded() -> None:
    with pytest.raises(SecurityConstraintQueryError, match="positive"):
        _query(selection_budget=0)
    with pytest.raises(SecurityConstraintQueryError, match="unbounded"):
        _query(selection_budget=10_000)


def test_artifact_family_must_match_authority() -> None:
    with pytest.raises(SecurityConstraintQueryError, match="must match"):
        _query(
            artifact_family=SecurityArtifactFamily.THEOREM,
            required_authority=AuthorityKind.POLICY_APPROVAL,
        )
    with pytest.raises(SecurityConstraintQueryError, match="must match"):
        _record(
            artifact_family=SecurityArtifactFamily.MONITOR,
            required_authority=AuthorityKind.THEOREM_PROOF,
        )


# ---------------------------------------------------------------------------
# Happy path / principal binding
# ---------------------------------------------------------------------------


def test_selects_applicable_constraint_under_matching_scope() -> None:
    result = _query().select([_record()])
    assert result.disposition is SecuritySelectionDisposition.APPLICABLE
    assert not result.abstains
    assert result.allows_action
    assert len(result.selected) == 1
    assert result.selected[0].constraint_id == "sec:require-attestation"
    assert result.evidence.status is SecuritySelectionDisposition.APPLICABLE
    assert result.evidence.retrieval_rank_used_for_authority is False
    assert result.evidence.artifact_families_distinct is True
    assert result.evidence.shared_applicability is not None
    assert (
        result.evidence.shared_applicability.status
        is ApplicabilityStatus.APPLICABLE
    )
    assert not result.grants_legal_compliance
    assert not result.grants_execution_authority


def test_principal_mismatch_is_not_applicable() -> None:
    result = _query(principal_id="principal:bob").select([_record()])
    assert result.disposition is SecuritySelectionDisposition.NOT_APPLICABLE
    assert result.selected == ()
    assessment = result.assessments[0]
    assert assessment.disposition is SecurityConstraintDisposition.NOT_APPLICABLE
    assert "principal_mismatch" in assessment.reason_codes


def test_capability_delegation_and_trust_zone_mutations() -> None:
    base = _record()
    ok = _query().select([base])
    assert ok.disposition is SecuritySelectionDisposition.APPLICABLE

    wrong_cap = _query(capabilities=("cap:admin",)).select([base])
    assert wrong_cap.disposition is SecuritySelectionDisposition.NOT_APPLICABLE
    assert "capability_mismatch" in wrong_cap.assessments[0].reason_codes

    wrong_delegation = _query(delegation_ids=("delegation:other",)).select([base])
    assert (
        wrong_delegation.disposition is SecuritySelectionDisposition.NOT_APPLICABLE
    )

    wrong_zone = _query(trust_zone="zone:exchange").select([base])
    assert wrong_zone.disposition is SecuritySelectionDisposition.NOT_APPLICABLE
    assert "trust_zone_mismatch" in wrong_zone.assessments[0].reason_codes


def test_asset_channel_network_filesystem_and_action_scope() -> None:
    base = _record()
    for field, value, reason in (
        ("asset_id", "asset:btc", "asset_mismatch"),
        ("data_class", "data:pii", "data_class_mismatch"),
        ("channel_id", "channel:ws", "channel_mismatch"),
        ("network", "network:testnet", "network_mismatch"),
        ("filesystem", "fs:tmp", "filesystem_mismatch"),
        ("action", "action:export", "action_mismatch"),
        ("state", "state:locked", "state_mismatch"),
        ("effect", "effect:persist", "effect_mismatch"),
        ("failure", "failure:retry", "failure_mismatch"),
        ("rollback", "rollback:compensate", "rollback_mismatch"),
        ("sandbox_id", "sandbox:ci", "sandbox_mismatch"),
    ):
        result = _query(**{field: value}).select([base])
        assert result.disposition is SecuritySelectionDisposition.NOT_APPLICABLE, field
        assert reason in result.assessments[0].reason_codes, field


# ---------------------------------------------------------------------------
# Environment boundary / abstract vs live substitution
# ---------------------------------------------------------------------------


def test_abstract_model_cannot_substitute_for_live_environment() -> None:
    result = _query(
        environment_kind=SecurityEnvironmentKind.LIVE_ENVIRONMENT
    ).select(
        [
            _record(
                environment_kind=SecurityEnvironmentKind.ABSTRACT_MODEL,
                environment_ids=(),
            )
        ]
    )
    assert result.disposition is SecuritySelectionDisposition.REVIEW_REQUIRED
    assert (
        result.assessments[0].disposition
        is SecurityConstraintDisposition.ENVIRONMENT_MISMATCH
    )
    assert "abstract_model_live_environment_substitution" in (
        result.assessments[0].reason_codes
    )
    assert result.evidence.environment_substitution_rejected is True


def test_sandbox_cannot_substitute_for_live_environment() -> None:
    result = _query(
        environment_kind=SecurityEnvironmentKind.LIVE_ENVIRONMENT
    ).select(
        [
            _record(
                environment_kind=SecurityEnvironmentKind.SANDBOX,
                environment_ids=(),
            )
        ]
    )
    assert (
        result.assessments[0].disposition
        is SecurityConstraintDisposition.ENVIRONMENT_MISMATCH
    )
    assert "sandbox_live_environment_substitution" in result.assessments[0].reason_codes


def test_matching_live_environments_apply() -> None:
    result = _query(
        environment_kind=SecurityEnvironmentKind.LIVE_ENVIRONMENT,
        environment_id="env:prod-1",
    ).select([_record(environment_kind=SecurityEnvironmentKind.LIVE_ENVIRONMENT)])
    assert result.disposition is SecuritySelectionDisposition.APPLICABLE


# ---------------------------------------------------------------------------
# Result authority families remain distinct
# ---------------------------------------------------------------------------


def test_theorem_cannot_substitute_for_evidence_gate() -> None:
    result = _query(
        required_authority=AuthorityKind.EVIDENCE_READINESS,
        artifact_family=SecurityArtifactFamily.EVIDENCE_GATE,
    ).select(
        [
            _record(
                required_authority=AuthorityKind.THEOREM_PROOF,
                artifact_family=SecurityArtifactFamily.THEOREM,
            )
        ]
    )
    assert result.disposition is SecuritySelectionDisposition.AUTHORITY_MISMATCH
    assert (
        result.assessments[0].disposition
        is SecurityConstraintDisposition.AUTHORITY_MISMATCH
    )
    assert "result_authority_mismatch" in result.assessments[0].reason_codes


def test_monitor_policy_and_theorem_families_are_non_substitutable() -> None:
    families = (
        (AuthorityKind.RUNTIME_MONITOR, SecurityArtifactFamily.MONITOR),
        (AuthorityKind.POLICY_APPROVAL, SecurityArtifactFamily.POLICY),
        (AuthorityKind.THEOREM_PROOF, SecurityArtifactFamily.THEOREM),
    )
    for authority, family in families:
        result = _query(
            required_authority=AuthorityKind.EVIDENCE_READINESS,
            artifact_family=SecurityArtifactFamily.EVIDENCE_GATE,
        ).select(
            [_record(required_authority=authority, artifact_family=family)]
        )
        assert (
            result.assessments[0].disposition
            is SecurityConstraintDisposition.AUTHORITY_MISMATCH
        ), family


def test_matching_policy_family_applies() -> None:
    result = _query(
        required_authority=AuthorityKind.POLICY_APPROVAL,
        artifact_family=SecurityArtifactFamily.POLICY,
    ).select(
        [
            _record(
                required_authority=AuthorityKind.POLICY_APPROVAL,
                artifact_family=SecurityArtifactFamily.POLICY,
            )
        ]
    )
    assert result.disposition is SecuritySelectionDisposition.APPLICABLE


# ---------------------------------------------------------------------------
# Threat / policy version and freshness
# ---------------------------------------------------------------------------


def test_threat_and_policy_version_mismatch() -> None:
    base = _record()
    threat = _query(threat_model_version="9.9.9").select([base])
    assert threat.disposition is SecuritySelectionDisposition.NOT_APPLICABLE
    assert "threat_model_version_mismatch" in threat.assessments[0].reason_codes

    policy = _query(policy_version="1999.1").select([base])
    assert policy.disposition is SecuritySelectionDisposition.NOT_APPLICABLE
    assert "policy_version_mismatch" in policy.assessments[0].reason_codes


def test_stale_evidence_is_rejected() -> None:
    record = _record(
        evidence_ids=("ev:attestation-1",),
        evidence_digests=(DIGEST_B,),
        max_evidence_age_seconds=3600,
    )
    stale = _evidence(
        observed_at="2024-06-14T00:00:00Z",
        max_age_seconds=3600,
    )
    result = _query(as_of="2024-06-15T12:00:00Z").select(
        [record], evidence=[stale]
    )
    assert result.disposition is SecuritySelectionDisposition.STALE
    assert result.assessments[0].disposition is SecurityConstraintDisposition.STALE
    assert any(code.startswith("evidence_stale") for code in result.assessments[0].reason_codes)


def test_mismatched_evidence_digest_is_rejected() -> None:
    record = _record(
        evidence_ids=("ev:attestation-1",),
        evidence_digests=(DIGEST_A,),
    )
    binding = _evidence(content_digest=DIGEST_B)
    result = _query().select([record], evidence=[binding])
    assert result.disposition is SecuritySelectionDisposition.NOT_APPLICABLE
    assert result.assessments[0].disposition is SecurityConstraintDisposition.MISMATCHED
    assert any(
        code.startswith("evidence_digest_mismatch")
        for code in result.assessments[0].reason_codes
    )


def test_fresh_matching_evidence_applies() -> None:
    record = _record(
        evidence_ids=("ev:attestation-1",),
        evidence_digests=(DIGEST_B,),
        max_evidence_age_seconds=7200,
    )
    result = _query().select([record], evidence=[_evidence()])
    assert result.disposition is SecuritySelectionDisposition.APPLICABLE
    assert "freshness" in result.assessments[0].matched_dimensions


def test_evidence_authority_family_must_match_query() -> None:
    record = _record(evidence_ids=("ev:proof-1",))
    binding = _evidence(
        evidence_id="ev:proof-1",
        artifact_family=SecurityArtifactFamily.THEOREM,
        authority_kind=AuthorityKind.THEOREM_PROOF,
        content_digest="",
    )
    result = _query(
        required_authority=AuthorityKind.EVIDENCE_READINESS,
        artifact_family=SecurityArtifactFamily.EVIDENCE_GATE,
    ).select([record], evidence=[binding])
    assert (
        result.assessments[0].disposition
        is SecurityConstraintDisposition.AUTHORITY_MISMATCH
    )


def test_abstract_evidence_cannot_satisfy_live_query() -> None:
    record = _record(evidence_ids=("ev:model-1",), evidence_digests=())
    binding = _evidence(
        evidence_id="ev:model-1",
        environment_kind=SecurityEnvironmentKind.ABSTRACT_MODEL,
        content_digest="",
        max_age_seconds=None,
    )
    result = _query(
        environment_kind=SecurityEnvironmentKind.LIVE_ENVIRONMENT
    ).select([record], evidence=[binding])
    assert (
        result.assessments[0].disposition
        is SecurityConstraintDisposition.ENVIRONMENT_MISMATCH
    )


# ---------------------------------------------------------------------------
# Unknown extensions / provenance / taint
# ---------------------------------------------------------------------------


def test_unknown_extension_vocabulary_fails_closed() -> None:
    result = _query().select(
        [
            _record(
                extension_ids=("ext:custom",),
                extension_vocabularies=("unknown-vocab",),
            )
        ]
    )
    assert result.disposition is SecuritySelectionDisposition.REVIEW_REQUIRED
    assert (
        result.assessments[0].disposition
        is SecurityConstraintDisposition.UNKNOWN_EXTENSION
    )
    assert any(
        code.startswith("unknown_extension_vocabulary")
        for code in result.assessments[0].reason_codes
    )


def test_known_extension_vocabularies_pass() -> None:
    result = _query().select(
        [
            _record(
                extension_ids=("ext:xaman",),
                extension_vocabularies=("security.xaman",),
            )
        ]
    )
    # security.xaman is a built-in known vocabulary.
    assert result.disposition is SecuritySelectionDisposition.APPLICABLE


def test_tainted_premise_requires_review_and_never_applies() -> None:
    result = _query().select(
        [_record(premise_taint=SecurityPremiseTaintStatus.TAINTED)]
    )
    assert result.disposition is SecuritySelectionDisposition.REVIEW_REQUIRED
    assert result.abstains
    assert result.assessments[0].disposition is SecurityConstraintDisposition.TAINTED
    assert result.selected == ()


def test_missing_provenance_or_untrusted_source_fails_closed() -> None:
    missing_prov = _query().select([_record(provenance_ids=())])
    assert missing_prov.disposition is SecuritySelectionDisposition.REVIEW_REQUIRED

    untrusted = _query().select([_record(trusted_source=False)])
    assert untrusted.disposition is SecuritySelectionDisposition.REVIEW_REQUIRED

    unreviewed = _query().select([_record(reviewed=False)])
    assert unreviewed.disposition is SecuritySelectionDisposition.REVIEW_REQUIRED

    ungrounded = _query().select([_record(source_ref_ids=())])
    assert ungrounded.disposition is SecuritySelectionDisposition.REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# Competing constraints / contradictions / bounded selection
# ---------------------------------------------------------------------------


def test_higher_precedence_resolves_opposed_effects() -> None:
    deny = _record(
        constraint_id="sec:deny",
        effect=SecurityConstraintEffect.DENY,
        precedence=20,
        priority=1,
        retrieval_rank=0,
    )
    allow = _record(
        constraint_id="sec:allow",
        effect=SecurityConstraintEffect.ALLOW,
        precedence=5,
        priority=99,
        retrieval_rank=0,
    )
    result = _query().select([allow, deny])
    assert result.disposition is SecuritySelectionDisposition.APPLICABLE
    assert [item.constraint_id for item in result.selected] == ["sec:deny"]
    loser = next(
        item for item in result.assessments if item.constraint_id == "sec:allow"
    )
    assert loser.disposition is SecurityConstraintDisposition.SUPERSEDED
    assert "higher_precedence_constraint" in loser.reason_codes


def test_equal_precedence_conflict_is_preserved_and_abstains() -> None:
    left = _record(
        constraint_id="sec:deny",
        effect=SecurityConstraintEffect.DENY,
        precedence=10,
        priority=1,
    )
    right = _record(
        constraint_id="sec:allow",
        effect=SecurityConstraintEffect.ALLOW,
        precedence=10,
        priority=1,
    )
    result = _query().select([left, right])
    assert result.disposition is SecuritySelectionDisposition.CONFLICT
    assert result.abstains
    assert result.selected == ()
    assert any(not item.resolved for item in result.contradictions)
    for assessment in result.assessments:
        assert assessment.disposition is SecurityConstraintDisposition.CONFLICTING


def test_express_supersession_between_candidates() -> None:
    old = _record(
        constraint_id="sec:old",
        precedence=1,
        retrieval_rank=0,
    )
    new = _record(
        constraint_id="sec:new",
        precedence=5,
        supersedes=("sec:old",),
        retrieval_rank=50,
    )
    result = _query().select([old, new])
    assert result.disposition is SecuritySelectionDisposition.APPLICABLE
    assert [item.constraint_id for item in result.selected] == ["sec:new"]
    old_assessment = next(
        item for item in result.assessments if item.constraint_id == "sec:old"
    )
    assert old_assessment.disposition is SecurityConstraintDisposition.SUPERSEDED
    assert "sec:new" in old_assessment.defeated_by


def test_retrieval_rank_never_selects_authority() -> None:
    weak_but_top_ranked = _record(
        constraint_id="sec:weak",
        effect=SecurityConstraintEffect.ALLOW,
        precedence=1,
        priority=1,
        retrieval_rank=0,
        retrieval_score=0.99,
    )
    strong_but_low_ranked = _record(
        constraint_id="sec:strong",
        effect=SecurityConstraintEffect.DENY,
        precedence=90,
        priority=1,
        retrieval_rank=500,
        retrieval_score=0.01,
    )
    result = _query().select([weak_but_top_ranked, strong_but_low_ranked])
    assert result.selected[0].constraint_id == "sec:strong"
    assert result.evidence.retrieval_rank_used_for_authority is False
    assert "retrieval_rank" not in result.evidence.authority_selection_keys
    assert result.evidence.selection_method is PremiseSelectionMethod.HARD_FILTER


def test_evidence_rejects_retrieval_rank_authority_flag() -> None:
    result = _query().select([_record()])
    payload = result.evidence.to_dict()
    payload["retrieval_rank_used_for_authority"] = True
    with pytest.raises(SecurityConstraintQueryError, match="retrieval rank"):
        SecurityApplicabilityEvidence.from_dict(payload)


def test_evidence_rejects_collapsed_artifact_families() -> None:
    result = _query().select([_record()])
    payload = result.evidence.to_dict()
    payload["artifact_families_distinct"] = False
    with pytest.raises(SecurityConstraintQueryError, match="distinct"):
        SecurityApplicabilityEvidence.from_dict(payload)


def test_selection_budget_bounds_without_using_retrieval_rank() -> None:
    records = [
        _record(
            constraint_id=f"sec:{idx}",
            precedence=idx,
            priority=idx,
            retrieval_rank=100 - idx,
            conflict_key=f"key-{idx}",
            statement=f"Constraint {idx}",
        )
        for idx in range(1, 6)
    ]
    result = _query(selection_budget=2).select(records)
    assert result.disposition is SecuritySelectionDisposition.APPLICABLE
    assert len(result.selected) == 2
    selected_ids = {item.constraint_id for item in result.selected}
    assert selected_ids == {"sec:5", "sec:4"}
    assert result.evidence.selected_count == 2
    assert result.evidence.selection_budget == 2


# ---------------------------------------------------------------------------
# Coverage / empty corpus / declaration binding
# ---------------------------------------------------------------------------


def test_empty_candidates_yield_coverage_gap_abstain() -> None:
    result = _query().select([])
    assert result.disposition is SecuritySelectionDisposition.COVERAGE_GAP
    assert result.abstains
    assert result.evidence.coverage_gaps
    assert result.evidence.INTERFACE == SECURITY_APPLICABILITY_EVIDENCE_INTERFACE


def test_declaration_digest_mismatch() -> None:
    result = _query(declaration_digest=DIGEST_A).select(
        [_record(declaration_digest=DIGEST_B)]
    )
    assert result.disposition is SecuritySelectionDisposition.NOT_APPLICABLE
    assert result.assessments[0].disposition is SecurityConstraintDisposition.MISMATCHED
    assert "declaration_digest_mismatch" in result.assessments[0].reason_codes


# ---------------------------------------------------------------------------
# Evidence / premises / module API
# ---------------------------------------------------------------------------


def test_selected_premises_are_hard_filtered_not_rank_authority() -> None:
    result = _query().select([_record()])
    premises = result.evidence.selected_premises
    assert premises is not None
    assert premises.selection_method is PremiseSelectionMethod.HARD_FILTER
    assert premises.premises[0].selection_method is PremiseSelectionMethod.HARD_FILTER
    meta = premises.premises[0].metadata.to_dict()
    assert meta.get("retrieval_rank_ignored") == 99
    assert meta.get("artifact_family") == "evidence_gate"


def test_function_and_method_entry_points_agree() -> None:
    query = _query()
    candidates = [_record()]
    via_method = query.select(candidates)
    via_function = select_applicable_security_constraints(query, candidates)
    assert via_method.digest == via_function.digest
    assert via_method.evidence.digest == via_function.evidence.digest


def test_evidence_roundtrip_json() -> None:
    result = _query().select([_record()])
    raw = result.evidence.to_json()
    restored = SecurityApplicabilityEvidence.from_dict(json.loads(raw))
    assert restored.status is result.evidence.status
    assert restored.selected_constraint_ids == result.evidence.selected_constraint_ids
    assert restored.retrieval_rank_used_for_authority is False
    assert restored.artifact_families_distinct is True


def test_record_rejects_wildcards() -> None:
    with pytest.raises(SecurityConstraintQueryError):
        _record(principals=("*",))
    with pytest.raises(SecurityConstraintQueryError):
        _record(capabilities=("any",))


def test_query_from_dict_rejects_unknown_interface() -> None:
    payload = _query().to_dict()
    payload["interface"] = "SecurityConstraintQuery@9"
    with pytest.raises(SecurityConstraintQueryError):
        SecurityConstraintQuery.from_dict(payload)


def test_priority_resolves_same_precedence_opposed_effects() -> None:
    low = _record(
        constraint_id="sec:low",
        effect=SecurityConstraintEffect.ALLOW,
        precedence=50,
        priority=1,
    )
    high = _record(
        constraint_id="sec:high",
        effect=SecurityConstraintEffect.DENY,
        precedence=50,
        priority=20,
    )
    result = _query().select([low, high])
    assert [item.constraint_id for item in result.selected] == ["sec:high"]
    loser = next(
        item for item in result.assessments if item.constraint_id == "sec:low"
    )
    assert "higher_priority_constraint" in loser.reason_codes


def test_missing_principal_selector_is_indeterminate_under_closed_world() -> None:
    result = _query().select([_record(principals=())])
    assert result.disposition is SecuritySelectionDisposition.INDETERMINATE
    assert "missing_principal_selector" in result.assessments[0].reason_codes
