"""Unit vectors for formal-proof and policy vacuity analysis (AAE-026)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    ArtifactProvenance,
    AssuranceArtifactHeader,
    AssuranceTerminalStatus,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    VersionBinding,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.analysis_contracts import (
    MinimizedEvidenceBinding,
    SourceSpan,
    VacuityFamily,
    VacuityKind,
    verify_vacuity_finding_identity,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.vacuity_formal_policy import (
    ANALYZE_FORMAL_VACUITY_INTERFACE,
    ANALYZE_POLICY_VACUITY_INTERFACE,
    GENERATOR_ID,
    FormalProofVacuitySubject,
    PolicyDefaultAction,
    PolicyEffect,
    PolicyRuleObservation,
    PolicyVacuitySubject,
    VacuityAnalysisResult,
    VacuityFormalPolicyError,
    analyze_formal_vacuity,
    analyze_policy_vacuity,
    policy_default_actions,
    policy_effects,
    verify_vacuity_analysis_result_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "test_fixture",
        "generator_version": "1.0.0",
        "interface_id": "test_fixture@1",
    }
    fields.update(overrides)
    return GeneratorIdentity(**fields)  # type: ignore[arg-type]


def _versions(**overrides: object) -> VersionBinding:
    fields = {
        "operator_id": "control_flow_invert",
        "operator_version": "1",
        "campaign_policy_id": "default_campaign",
        "campaign_policy_version": "1.0.0",
        "generator": _generator(),
    }
    fields.update(overrides)
    return VersionBinding(**fields)  # type: ignore[arg-type]


def _provenance(**overrides: object) -> ArtifactProvenance:
    fields = {
        "producer_id": "adversarial_assurance",
        "producer_version": "1",
        "execution_mode": ExecutionMode.LIVE,
        "authority_source": AuthoritySource.OBSERVED,
        "input_cids": (_cid("input-a"),),
        "tool_ids": ("analyzer.v1",),
        "policy_cid": _cid("policy"),
        "notes": None,
    }
    fields.update(overrides)
    return ArtifactProvenance(**fields)  # type: ignore[arg-type]


def _header(**overrides: object) -> AssuranceArtifactHeader:
    fields = {
        "artifact_kind": "vacuity_finding",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state"),
        "target_symbol_ids": ("mod.fn",),
        "target_artifact_cids": (_cid("artifact-a"),),
        "capsule_cids": (_cid("capsule-a"),),
        "proof_unit_cids": (_cid("proof-unit-a"),),
        "environment_cid": _cid("environment"),
        "dependency_lock_cid": _cid("dependency-lock"),
        "versions": _versions(),
        "provenance": _provenance(),
        "terminal_status": AssuranceTerminalStatus.COMPLETE,
        "receipt_cids": (_cid("receipt-a"),),
        "proof_cids": (_cid("proof-a"),),
        "metadata": {},
    }
    fields.update(overrides)
    return AssuranceArtifactHeader(**fields)  # type: ignore[arg-type]


def _span(**overrides: object) -> SourceSpan:
    fields = {
        "path": "proofs/authz.lean",
        "start_line": 10,
        "end_line": 40,
        "start_col": 0,
        "end_col": 80,
    }
    fields.update(overrides)
    return SourceSpan(**fields)  # type: ignore[arg-type]


def _evidence(**overrides: object) -> MinimizedEvidenceBinding:
    fields = {
        "evidence_cids": (_cid("min-evidence-1"),),
        "minimized": True,
        "minimization_failed": False,
        "reproduction_input_cid": _cid("repro-input"),
        "notes": None,
    }
    fields.update(overrides)
    return MinimizedEvidenceBinding(**fields)  # type: ignore[arg-type]


def _formal_subject(**overrides: object) -> FormalProofVacuitySubject:
    fields = {
        "subject_id": "proof.authz_guard",
        "claimed_property": "authorization guard rejects unauthorized callers",
        "symbol_ids": ("mod.fn", "proof.authz_guard"),
        "source_spans": (_span(),),
        "dependency_path": ("mod.fn", "proof.authz_guard"),
        "minimized_evidence": _evidence(),
        "proposition": "forall caller, authorized(caller) -> admit(caller)",
        "antecedent": "caller has valid capability token",
        "antecedent_satisfiable": True,
        "modeled_state_ids": ("state.authorized", "state.denied"),
        "reachable_state_ids": ("state.authorized", "state.denied"),
        "discharge_possible": True,
        "result_constrained": True,
        "unconstrained_result_ids": (),
        "required_behavior_ids": ("behavior.reject_unauth", "behavior.admit_auth"),
        "modeled_behavior_ids": ("behavior.reject_unauth", "behavior.admit_auth"),
        "assumed_ids": ("asm.token_wellformed",),
        "proven_ids": ("asm.token_wellformed", "lemma.capability_sound"),
        "assumptions_used_as_proven": (),
        "declared_nonclaims": (
            "does not prove hardware root of trust",
            "does not prove side-channel absence",
        ),
        "subject_cid": _cid("formal-subject"),
        "observation_complete": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return FormalProofVacuitySubject(**fields)  # type: ignore[arg-type]


def _rule(**overrides: object) -> PolicyRuleObservation:
    fields = {
        "rule_id": "rule.deny_cross_tenant",
        "effect": PolicyEffect.DENY,
        "reachable": True,
        "is_prohibition": True,
        "shadowed_by_rule_ids": (),
        "obligation_satisfiable": True,
        "is_default": False,
        "interface_reference_id": "iface.authz.v2",
        "interface_obsolete": False,
        "is_confirmation": False,
        "notes": None,
    }
    fields.update(overrides)
    return PolicyRuleObservation(**fields)  # type: ignore[arg-type]


def _policy_subject(**overrides: object) -> PolicyVacuitySubject:
    fields = {
        "subject_id": "policy.authz",
        "claimed_property": "cross-tenant access is denied without confirmation",
        "symbol_ids": ("mod.authz", "policy.authz"),
        "source_spans": (
            _span(path="policies/authz.rego", start_line=1, end_line=80),
        ),
        "dependency_path": ("mod.authz", "policy.authz"),
        "minimized_evidence": _evidence(evidence_cids=(_cid("policy-evidence"),)),
        "rules": (
            _rule(),
            _rule(
                rule_id="rule.confirm_high_value",
                effect=PolicyEffect.CONFIRM,
                is_prohibition=False,
                is_confirmation=True,
                interface_reference_id="iface.authz.v2",
            ),
            _rule(
                rule_id="rule.oblige_audit",
                effect=PolicyEffect.OBLIGE,
                is_prohibition=False,
                obligation_satisfiable=True,
                interface_reference_id="iface.audit.v1",
            ),
        ),
        "default_action": PolicyDefaultAction.DENY,
        "default_dominates_specific_rules": False,
        "obsolete_interface_reference_ids": (),
        "live_interface_reference_ids": ("iface.authz.v2", "iface.audit.v1"),
        "declared_nonclaims": (
            "does not prove physical access control",
            "does not prove key ceremony completeness",
        ),
        "subject_cid": _cid("policy-subject"),
        "observation_complete": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return PolicyVacuitySubject(**fields)  # type: ignore[arg-type]


def _kinds(result: VacuityAnalysisResult) -> set[str]:
    return {finding.vacuity_kind for finding in result.findings}


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


def test_closed_vocabularies() -> None:
    assert PolicyDefaultAction.ALLOW.value in policy_default_actions()
    assert PolicyEffect.DENY.value in policy_effects()
    assert ANALYZE_FORMAL_VACUITY_INTERFACE.endswith("@1")
    assert ANALYZE_POLICY_VACUITY_INTERFACE.endswith("@1")


# ---------------------------------------------------------------------------
# Sound subjects produce no findings
# ---------------------------------------------------------------------------


def test_sound_formal_subject_has_no_findings() -> None:
    result = analyze_formal_vacuity(_formal_subject(), _header())
    assert result.findings == ()
    assert result.finding_cids == ()
    assert result.vacuity_family == VacuityFamily.FORMAL_PROOF.value
    assert result.interface_id == ANALYZE_FORMAL_VACUITY_INTERFACE
    assert result.residual_properties == ()
    # Declared nonclaims remain visible even when no vacuity kind fires.
    assert "does not prove hardware root of trust" in result.precise_nonclaims
    assert "does not prove side-channel absence" in result.precise_nonclaims
    assert verify_vacuity_analysis_result_identity(result) == result.result_cid
    restored = VacuityAnalysisResult.from_dict(result.to_dict())
    assert restored.result_cid == result.result_cid


def test_sound_policy_subject_has_no_findings() -> None:
    result = analyze_policy_vacuity(_policy_subject(), _header())
    assert result.findings == ()
    assert result.vacuity_family == VacuityFamily.POLICY.value
    assert result.interface_id == ANALYZE_POLICY_VACUITY_INTERFACE
    assert "does not prove physical access control" in result.precise_nonclaims
    assert verify_vacuity_analysis_result_identity(result) == result.result_cid


# ---------------------------------------------------------------------------
# Formal-proof detections
# ---------------------------------------------------------------------------


def test_detects_unsatisfiable_antecedent() -> None:
    subject = _formal_subject(
        subject_id="proof.unsat_antecedent",
        antecedent="false /\\ authorized(caller)",
        antecedent_satisfiable=False,
    )
    result = analyze_formal_vacuity(subject, _header())
    assert VacuityKind.UNSATISFIABLE_ANTECEDENT.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.UNSATISFIABLE_ANTECEDENT.value
    )
    assert finding.what_remains_proven
    assert finding.what_is_not_proven
    assert finding.what_remains_proven != finding.what_is_not_proven
    assert "unsatisfiable" in finding.what_remains_proven.lower()
    assert subject.claimed_property in finding.what_is_not_proven
    assert subject.proposition in finding.what_is_not_proven
    assert verify_vacuity_finding_identity(finding) == finding.finding_cid
    assert finding.header.versions.generator.generator_id == GENERATOR_ID
    assert (
        finding.header.versions.generator.interface_id
        == ANALYZE_FORMAL_VACUITY_INTERFACE
    )
    assert finding.what_remains_proven in result.residual_properties


def test_detects_unreachable_modeled_state() -> None:
    subject = _formal_subject(
        subject_id="proof.unreachable_state",
        modeled_state_ids=(
            "state.authorized",
            "state.denied",
            "state.impossible_admin",
        ),
        reachable_state_ids=("state.authorized", "state.denied"),
    )
    result = analyze_formal_vacuity(subject, _header())
    assert VacuityKind.UNREACHABLE_MODELED_STATE.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.UNREACHABLE_MODELED_STATE.value
    )
    assert "state.impossible_admin" in finding.what_remains_proven
    assert "state.impossible_admin" in finding.what_is_not_proven
    assert "executable path" in finding.what_is_not_proven


def test_detects_impossible_discharge() -> None:
    subject = _formal_subject(
        subject_id="proof.impossible_discharge",
        discharge_possible=False,
    )
    result = analyze_formal_vacuity(subject, _header())
    assert VacuityKind.IMPOSSIBLE_DISCHARGE.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.IMPOSSIBLE_DISCHARGE.value
    )
    assert "obligation structure" in finding.what_remains_proven
    assert "cannot be discharged" in finding.what_is_not_proven
    assert subject.claimed_property in finding.what_is_not_proven


def test_detects_unconstrained_result_flag() -> None:
    subject = _formal_subject(
        subject_id="proof.unconstrained_flag",
        result_constrained=False,
        unconstrained_result_ids=(),
    )
    result = analyze_formal_vacuity(subject, _header())
    assert VacuityKind.UNCONSTRAINED_RESULT.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.UNCONSTRAINED_RESULT.value
    )
    assert "without constraining" in finding.what_remains_proven
    assert "unconstrained" in finding.what_is_not_proven


def test_detects_unconstrained_result_ids() -> None:
    subject = _formal_subject(
        subject_id="proof.unconstrained_ids",
        result_constrained=True,
        unconstrained_result_ids=("result.session_token", "result.role_set"),
    )
    result = analyze_formal_vacuity(subject, _header())
    assert VacuityKind.UNCONSTRAINED_RESULT.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.UNCONSTRAINED_RESULT.value
    )
    assert "result.session_token" in finding.what_remains_proven
    assert "result.role_set" in finding.what_is_not_proven


def test_detects_omitted_behavior() -> None:
    subject = _formal_subject(
        subject_id="proof.omitted_behavior",
        required_behavior_ids=(
            "behavior.reject_unauth",
            "behavior.admit_auth",
            "behavior.audit_emit",
        ),
        modeled_behavior_ids=("behavior.reject_unauth", "behavior.admit_auth"),
    )
    result = analyze_formal_vacuity(subject, _header())
    assert VacuityKind.OMITTED_BEHAVIOR.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.OMITTED_BEHAVIOR.value
    )
    assert "behavior.audit_emit" in finding.what_is_not_proven
    assert "behavior.reject_unauth" in finding.what_remains_proven


def test_detects_assumed_not_proven_explicit() -> None:
    subject = _formal_subject(
        subject_id="proof.assumed_explicit",
        assumed_ids=("asm.token_wellformed", "asm.clock_sync"),
        proven_ids=("lemma.capability_sound",),
        assumptions_used_as_proven=("asm.clock_sync",),
    )
    result = analyze_formal_vacuity(subject, _header())
    assert VacuityKind.ASSUMED_NOT_PROVEN.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.ASSUMED_NOT_PROVEN.value
    )
    assert "asm.clock_sync" in finding.what_remains_proven
    assert "not independently proven" in finding.what_is_not_proven
    assert subject.claimed_property in finding.what_is_not_proven


def test_detects_assumed_not_proven_undischarged() -> None:
    subject = _formal_subject(
        subject_id="proof.assumed_undischarged",
        assumed_ids=("asm.network_trusted", "asm.admin_honest"),
        proven_ids=(),
        assumptions_used_as_proven=(),
    )
    result = analyze_formal_vacuity(subject, _header())
    assert VacuityKind.ASSUMED_NOT_PROVEN.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.ASSUMED_NOT_PROVEN.value
    )
    assert "asm.network_trusted" in finding.what_is_not_proven
    assert "asm.admin_honest" in finding.what_remains_proven


def test_formal_precise_nonclaims_merge_declared_and_detected() -> None:
    subject = _formal_subject(
        subject_id="proof.merge_nonclaims",
        antecedent_satisfiable=False,
        declared_nonclaims=(
            "does not prove hardware root of trust",
            "compiler correctness is out of scope",
        ),
    )
    result = analyze_formal_vacuity(subject, _header())
    assert VacuityKind.UNSATISFIABLE_ANTECEDENT.value in _kinds(result)
    assert "does not prove hardware root of trust" in result.precise_nonclaims
    assert "compiler correctness is out of scope" in result.precise_nonclaims
    assert any("not established" in item for item in result.precise_nonclaims)


def test_formal_subject_roundtrip_identity() -> None:
    subject = _formal_subject()
    restored = FormalProofVacuitySubject.from_dict(subject.to_dict())
    assert restored.subject_observation_cid == subject.subject_observation_cid
    assert restored.proposition == subject.proposition


# ---------------------------------------------------------------------------
# Policy detections
# ---------------------------------------------------------------------------


def test_detects_unreachable_rule() -> None:
    subject = _policy_subject(
        subject_id="policy.unreachable_rule",
        rules=(
            _rule(rule_id="rule.live_deny", reachable=True),
            _rule(
                rule_id="rule.dead_deny",
                reachable=False,
                is_prohibition=True,
                effect=PolicyEffect.DENY,
            ),
        ),
    )
    result = analyze_policy_vacuity(subject, _header())
    assert VacuityKind.UNREACHABLE_RULE.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.UNREACHABLE_RULE.value
    )
    assert "rule.dead_deny" in finding.what_remains_proven
    assert "rule.dead_deny" in finding.what_is_not_proven
    assert subject.claimed_property in finding.what_is_not_proven
    assert verify_vacuity_finding_identity(finding) == finding.finding_cid
    assert finding.header.versions.generator.generator_id == GENERATOR_ID
    assert (
        finding.header.versions.generator.interface_id
        == ANALYZE_POLICY_VACUITY_INTERFACE
    )


def test_detects_unreachable_confirmation() -> None:
    subject = _policy_subject(
        subject_id="policy.unreachable_confirm",
        rules=(
            _rule(rule_id="rule.deny_ok", reachable=True),
            _rule(
                rule_id="rule.confirm_dead",
                effect=PolicyEffect.CONFIRM,
                is_prohibition=False,
                is_confirmation=True,
                reachable=False,
            ),
        ),
    )
    result = analyze_policy_vacuity(subject, _header())
    assert VacuityKind.UNREACHABLE_CONFIRMATION.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.UNREACHABLE_CONFIRMATION.value
    )
    assert "rule.confirm_dead" in finding.what_remains_proven
    assert "operator approval" in finding.what_is_not_proven
    # Unreachable confirmation is also an unreachable rule.
    assert VacuityKind.UNREACHABLE_RULE.value in _kinds(result)


def test_detects_shadowed_prohibition() -> None:
    subject = _policy_subject(
        subject_id="policy.shadowed",
        rules=(
            _rule(
                rule_id="rule.allow_admin",
                effect=PolicyEffect.ALLOW,
                is_prohibition=False,
                reachable=True,
            ),
            _rule(
                rule_id="rule.deny_admin",
                effect=PolicyEffect.DENY,
                is_prohibition=True,
                reachable=True,
                shadowed_by_rule_ids=("rule.allow_admin",),
            ),
        ),
    )
    result = analyze_policy_vacuity(subject, _header())
    assert VacuityKind.SHADOWED_PROHIBITION.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.SHADOWED_PROHIBITION.value
    )
    assert "rule.deny_admin" in finding.what_remains_proven
    assert "rule.allow_admin" in finding.what_remains_proven
    assert "never deny" in finding.what_is_not_proven


def test_detects_impossible_obligation() -> None:
    subject = _policy_subject(
        subject_id="policy.impossible_obligation",
        rules=(
            _rule(
                rule_id="rule.oblige_impossible",
                effect=PolicyEffect.OBLIGE,
                is_prohibition=False,
                obligation_satisfiable=False,
            ),
        ),
    )
    result = analyze_policy_vacuity(subject, _header())
    assert VacuityKind.IMPOSSIBLE_OBLIGATION.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.IMPOSSIBLE_OBLIGATION.value
    )
    assert "rule.oblige_impossible" in finding.what_remains_proven
    assert "cannot be satisfied" in finding.what_remains_proven
    assert "compliant outcomes" in finding.what_is_not_proven


def test_detects_dominating_default() -> None:
    subject = _policy_subject(
        subject_id="policy.dominating_default",
        default_action=PolicyDefaultAction.ALLOW,
        default_dominates_specific_rules=True,
        rules=(
            _rule(rule_id="rule.specific_deny", is_default=False),
            _rule(
                rule_id="rule.default_allow",
                effect=PolicyEffect.ALLOW,
                is_prohibition=False,
                is_default=True,
            ),
        ),
    )
    result = analyze_policy_vacuity(subject, _header())
    assert VacuityKind.DOMINATING_DEFAULT.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.DOMINATING_DEFAULT.value
    )
    assert "allow" in finding.what_remains_proven
    assert "rule.specific_deny" in finding.what_remains_proven
    assert "dominating default" in finding.what_is_not_proven


def test_detects_obsolete_interface_reference_subject_level() -> None:
    subject = _policy_subject(
        subject_id="policy.obsolete_iface",
        obsolete_interface_reference_ids=("iface.authz.v1",),
        live_interface_reference_ids=("iface.authz.v2",),
    )
    result = analyze_policy_vacuity(subject, _header())
    assert VacuityKind.OBSOLETE_INTERFACE_REFERENCE.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.OBSOLETE_INTERFACE_REFERENCE.value
    )
    assert "iface.authz.v1" in finding.what_remains_proven
    assert "iface.authz.v2" in finding.what_remains_proven
    assert "do not bind current" in finding.what_is_not_proven


def test_detects_obsolete_interface_reference_from_rule() -> None:
    subject = _policy_subject(
        subject_id="policy.obsolete_rule_iface",
        obsolete_interface_reference_ids=(),
        live_interface_reference_ids=("iface.authz.v2",),
        rules=(
            _rule(
                rule_id="rule.legacy",
                interface_reference_id="iface.legacy.v0",
                interface_obsolete=True,
            ),
        ),
    )
    result = analyze_policy_vacuity(subject, _header())
    assert VacuityKind.OBSOLETE_INTERFACE_REFERENCE.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.OBSOLETE_INTERFACE_REFERENCE.value
    )
    assert "iface.legacy.v0" in finding.what_is_not_proven


def test_policy_precise_nonclaims_merge_declared_and_detected() -> None:
    subject = _policy_subject(
        subject_id="policy.merge_nonclaims",
        default_dominates_specific_rules=True,
        default_action=PolicyDefaultAction.ALLOW,
        declared_nonclaims=(
            "does not prove physical access control",
            "tenant isolation is out of band",
        ),
    )
    result = analyze_policy_vacuity(subject, _header())
    assert VacuityKind.DOMINATING_DEFAULT.value in _kinds(result)
    assert "does not prove physical access control" in result.precise_nonclaims
    assert "tenant isolation is out of band" in result.precise_nonclaims
    assert any("dominating default" in item for item in result.precise_nonclaims)


def test_policy_subject_roundtrip_identity() -> None:
    subject = _policy_subject()
    restored = PolicyVacuitySubject.from_dict(subject.to_dict())
    assert restored.subject_observation_cid == subject.subject_observation_cid
    assert len(restored.rules) == len(subject.rules)


def test_policy_rule_roundtrip() -> None:
    rule = _rule(shadowed_by_rule_ids=("rule.allow_all",))
    restored = PolicyRuleObservation.from_dict(rule.to_dict())
    assert restored.rule_id == rule.rule_id
    assert restored.shadowed_by_rule_ids == rule.shadowed_by_rule_ids


# ---------------------------------------------------------------------------
# Fail-closed / negative cases
# ---------------------------------------------------------------------------


def test_formal_fails_closed_on_incomplete_observation() -> None:
    subject = _formal_subject(observation_complete=False)
    with pytest.raises(VacuityFormalPolicyError, match="observation_complete"):
        analyze_formal_vacuity(subject, _header())


def test_policy_fails_closed_on_incomplete_observation() -> None:
    subject = _policy_subject(observation_complete=False)
    with pytest.raises(VacuityFormalPolicyError, match="observation_complete"):
        analyze_policy_vacuity(subject, _header())


def test_formal_rejects_reachable_not_subset_of_modeled() -> None:
    with pytest.raises(VacuityFormalPolicyError, match="subset"):
        _formal_subject(
            modeled_state_ids=("state.a",),
            reachable_state_ids=("state.a", "state.ghost"),
        )


def test_policy_rejects_overlapping_obsolete_and_live_interfaces() -> None:
    with pytest.raises(VacuityFormalPolicyError, match="disjoint"):
        _policy_subject(
            obsolete_interface_reference_ids=("iface.shared",),
            live_interface_reference_ids=("iface.shared",),
        )


def test_policy_rule_rejects_prohibition_with_allow_effect() -> None:
    with pytest.raises(VacuityFormalPolicyError, match="is_prohibition"):
        _rule(effect=PolicyEffect.ALLOW, is_prohibition=True)


def test_policy_rule_rejects_confirmation_without_confirm_effect() -> None:
    with pytest.raises(VacuityFormalPolicyError, match="is_confirmation"):
        _rule(
            effect=PolicyEffect.DENY,
            is_prohibition=True,
            is_confirmation=True,
        )


def test_policy_rule_rejects_obsolete_without_interface() -> None:
    with pytest.raises(VacuityFormalPolicyError, match="interface_reference_id"):
        _rule(interface_reference_id=None, interface_obsolete=True)


def test_formal_mapping_subject_admitted() -> None:
    subject = _formal_subject(
        subject_id="proof.from_mapping",
        antecedent_satisfiable=False,
    )
    result = analyze_formal_vacuity(subject.to_dict(), _header().to_dict())
    assert VacuityKind.UNSATISFIABLE_ANTECEDENT.value in _kinds(result)


def test_policy_mapping_subject_admitted() -> None:
    subject = _policy_subject(
        subject_id="policy.from_mapping",
        default_dominates_specific_rules=True,
    )
    result = analyze_policy_vacuity(subject.to_dict(), _header().to_dict())
    assert VacuityKind.DOMINATING_DEFAULT.value in _kinds(result)


def test_result_identity_rejects_forged_cid() -> None:
    result = analyze_formal_vacuity(
        _formal_subject(antecedent_satisfiable=False),
        _header(),
    )
    payload = result.to_dict()
    payload["result_cid"] = _cid("forged-result")
    with pytest.raises(VacuityFormalPolicyError, match="identity mismatch"):
        VacuityAnalysisResult.from_dict(payload)


def test_every_finding_states_exact_residual_property() -> None:
    """Acceptance: every vacuity finding states exactly what remains proven."""

    formal = analyze_formal_vacuity(
        _formal_subject(
            subject_id="proof.all_kinds",
            antecedent_satisfiable=False,
            modeled_state_ids=("state.a", "state.b"),
            reachable_state_ids=("state.a",),
            discharge_possible=False,
            result_constrained=False,
            unconstrained_result_ids=("result.x",),
            required_behavior_ids=("behavior.a", "behavior.b"),
            modeled_behavior_ids=("behavior.a",),
            assumed_ids=("asm.x",),
            proven_ids=(),
            assumptions_used_as_proven=("asm.x",),
        ),
        _header(),
    )
    formal_kinds = {
        VacuityKind.UNSATISFIABLE_ANTECEDENT.value,
        VacuityKind.UNREACHABLE_MODELED_STATE.value,
        VacuityKind.IMPOSSIBLE_DISCHARGE.value,
        VacuityKind.UNCONSTRAINED_RESULT.value,
        VacuityKind.OMITTED_BEHAVIOR.value,
        VacuityKind.ASSUMED_NOT_PROVEN.value,
    }
    assert formal_kinds <= _kinds(formal)

    policy = analyze_policy_vacuity(
        _policy_subject(
            subject_id="policy.all_kinds",
            default_dominates_specific_rules=True,
            default_action=PolicyDefaultAction.ALLOW,
            obsolete_interface_reference_ids=("iface.old",),
            live_interface_reference_ids=("iface.new",),
            rules=(
                _rule(
                    rule_id="rule.dead",
                    reachable=False,
                    is_prohibition=True,
                ),
                _rule(
                    rule_id="rule.confirm_dead",
                    effect=PolicyEffect.CONFIRM,
                    is_prohibition=False,
                    is_confirmation=True,
                    reachable=False,
                ),
                _rule(
                    rule_id="rule.shadowed",
                    effect=PolicyEffect.DENY,
                    is_prohibition=True,
                    shadowed_by_rule_ids=("rule.allow_first",),
                ),
                _rule(
                    rule_id="rule.allow_first",
                    effect=PolicyEffect.ALLOW,
                    is_prohibition=False,
                ),
                _rule(
                    rule_id="rule.impossible_obl",
                    effect=PolicyEffect.OBLIGE,
                    is_prohibition=False,
                    obligation_satisfiable=False,
                ),
            ),
        ),
        _header(),
    )
    policy_kinds = {
        VacuityKind.UNREACHABLE_RULE.value,
        VacuityKind.UNREACHABLE_CONFIRMATION.value,
        VacuityKind.SHADOWED_PROHIBITION.value,
        VacuityKind.IMPOSSIBLE_OBLIGATION.value,
        VacuityKind.DOMINATING_DEFAULT.value,
        VacuityKind.OBSOLETE_INTERFACE_REFERENCE.value,
    }
    assert policy_kinds <= _kinds(policy)

    for result in (formal, policy):
        assert result.residual_properties
        assert result.precise_nonclaims
        for finding in result.findings:
            assert finding.what_remains_proven
            assert finding.what_is_not_proven
            assert finding.what_remains_proven != finding.what_is_not_proven
            assert finding.what_remains_proven in result.residual_properties
            assert finding.what_is_not_proven in result.precise_nonclaims
            assert finding.vacuous_claim
            # Family admission is already enforced by VacuityFinding construction.
            assert finding.vacuity_family in {
                VacuityFamily.FORMAL_PROOF.value,
                VacuityFamily.POLICY.value,
            }


def test_deterministic_result_cid() -> None:
    subject = _formal_subject(
        subject_id="proof.deterministic",
        antecedent_satisfiable=False,
    )
    header = _header()
    first = analyze_formal_vacuity(subject, header)
    second = analyze_formal_vacuity(subject, header)
    assert first.result_cid == second.result_cid
    assert first.finding_cids == second.finding_cids
