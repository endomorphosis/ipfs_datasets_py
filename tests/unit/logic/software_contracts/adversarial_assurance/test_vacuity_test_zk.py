"""Unit vectors for test/ZK/receipt/seal vacuity analysis (AAE-027)."""

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
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.vacuity_test_zk import (
    ANALYZE_TEST_VACUITY_INTERFACE,
    ANALYZE_ZK_RECEIPT_VACUITY_INTERFACE,
    GENERATOR_ID,
    TestAssertionObservation,
    TestAssertionStrength,
    TestMockObservation,
    TestVacuitySubject,
    VacuityAnalysisResult,
    VacuityTestZkError,
    VerificationKeySource,
    ZkReceiptVacuitySubject,
    analyze_test_vacuity,
    analyze_zk_receipt_vacuity,
    test_assertion_strengths,
    verification_key_sources,
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
        "path": "tests/test_mod.py",
        "start_line": 10,
        "end_line": 20,
        "start_col": 0,
        "end_col": 40,
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


def _assertion(**overrides: object) -> TestAssertionObservation:
    fields = {
        "assertion_id": "a1",
        "strength": TestAssertionStrength.BEHAVIORAL,
        "expression": "result.status == 'denied'",
        "observes_behavior": True,
        "observes_effects": False,
        "notes": None,
    }
    fields.update(overrides)
    return TestAssertionObservation(**fields)  # type: ignore[arg-type]


def _mock(**overrides: object) -> TestMockObservation:
    fields = {
        "mock_id": "m1",
        "target_symbol_id": "mod.fn",
        "behavior_independent": False,
        "notes": None,
    }
    fields.update(overrides)
    return TestMockObservation(**fields)  # type: ignore[arg-type]


def _test_subject(**overrides: object) -> TestVacuitySubject:
    fields = {
        "subject_id": "unit.test_authz",
        "claimed_property": "authorization guard rejects unauthorized callers",
        "symbol_ids": ("mod.fn", "unit.test_authz"),
        "source_spans": (_span(),),
        "dependency_path": ("mod.fn", "unit.test_authz"),
        "minimized_evidence": _evidence(),
        "assertions": (
            _assertion(
                assertion_id="a_effect",
                strength=TestAssertionStrength.EFFECT_OBSERVING,
                expression="ledger.entries == expected",
                observes_behavior=True,
                observes_effects=True,
            ),
        ),
        "mocks": (),
        "target_symbol_ids": ("mod.fn",),
        "targets_called": ("mod.fn",),
        "permanent_skip": False,
        "skip_condition": None,
        "fixture_bypasses_production_path": False,
        "bypassed_path_ids": (),
        "success_declared_before_effect_observation": False,
        "subject_cid": _cid("test-subject"),
        "observation_complete": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return TestVacuitySubject(**fields)  # type: ignore[arg-type]


def _zk_subject(**overrides: object) -> ZkReceiptVacuitySubject:
    fields = {
        "subject_id": "receipt.campaign_1",
        "claimed_property": "campaign receipt proves sealed unit execution",
        "symbol_ids": ("mod.fn", "receipt.campaign_1"),
        "source_spans": (
            _span(path="receipts/campaign.json", start_line=1, end_line=40),
        ),
        "dependency_path": ("mod.fn", "receipt.campaign_1"),
        "minimized_evidence": _evidence(evidence_cids=(_cid("zk-evidence"),)),
        "required_fields": ("repository_state_cid", "environment_cid", "seal_digest"),
        "bound_fields": ("repository_state_cid", "environment_cid", "seal_digest"),
        "source_root_bound": True,
        "environment_bound": True,
        "required_set_ids": ("unit.a", "unit.b"),
        "included_set_ids": ("unit.a", "unit.b"),
        "verification_key_source": VerificationKeySource.AUTHORITY,
        "is_signed_aggregation": False,
        "claims_direct_execution": False,
        "changed_unit_ids": ("unit.a",),
        "sealed_delta_unit_ids": ("unit.a",),
        "declared_nonclaims": (
            "does not prove inventory completeness",
            "does not prove translator soundness",
        ),
        "subject_cid": _cid("zk-subject"),
        "observation_complete": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ZkReceiptVacuitySubject(**fields)  # type: ignore[arg-type]


def _kinds(result: VacuityAnalysisResult) -> set[str]:
    return {finding.vacuity_kind for finding in result.findings}


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


def test_closed_vocabularies() -> None:
    assert TestAssertionStrength.TAUTOLOGY.value in test_assertion_strengths()
    assert VerificationKeySource.CALLER.value in verification_key_sources()
    assert ANALYZE_TEST_VACUITY_INTERFACE.endswith("@1")
    assert ANALYZE_ZK_RECEIPT_VACUITY_INTERFACE.endswith("@1")


# ---------------------------------------------------------------------------
# Sound subjects produce no findings
# ---------------------------------------------------------------------------


def test_sound_test_subject_has_no_findings() -> None:
    result = analyze_test_vacuity(_test_subject(), _header())
    assert result.findings == ()
    assert result.finding_cids == ()
    assert result.vacuity_family == VacuityFamily.TEST.value
    assert result.interface_id == ANALYZE_TEST_VACUITY_INTERFACE
    assert result.residual_properties == ()
    assert result.precise_nonclaims == ()
    assert verify_vacuity_analysis_result_identity(result) == result.result_cid
    restored = VacuityAnalysisResult.from_dict(result.to_dict())
    assert restored.result_cid == result.result_cid


def test_sound_zk_subject_has_no_findings_but_preserves_declared_nonclaims() -> None:
    result = analyze_zk_receipt_vacuity(_zk_subject(), _header())
    assert result.findings == ()
    assert result.vacuity_family == VacuityFamily.ZK_RECEIPT.value
    # Declared nonclaims remain visible even when no vacuity kind fires.
    assert "does not prove inventory completeness" in result.precise_nonclaims
    assert "does not prove translator soundness" in result.precise_nonclaims
    assert verify_vacuity_analysis_result_identity(result) == result.result_cid


# ---------------------------------------------------------------------------
# Test-family detections
# ---------------------------------------------------------------------------


def test_detects_tautology() -> None:
    subject = _test_subject(
        subject_id="unit.test_tautology",
        assertions=(
            _assertion(
                assertion_id="a_true",
                strength=TestAssertionStrength.TAUTOLOGY,
                expression="True",
                observes_behavior=False,
                observes_effects=False,
            ),
        ),
        success_declared_before_effect_observation=False,
    )
    result = analyze_test_vacuity(subject, _header())
    assert VacuityKind.TAUTOLOGY.value in _kinds(result)
    finding = next(
        item for item in result.findings if item.vacuity_kind == VacuityKind.TAUTOLOGY.value
    )
    assert finding.what_remains_proven
    assert finding.what_is_not_proven
    assert finding.what_remains_proven != finding.what_is_not_proven
    assert "True" in finding.what_remains_proven
    assert subject.claimed_property in finding.what_is_not_proven
    assert verify_vacuity_finding_identity(finding) == finding.finding_cid
    assert finding.header.versions.generator.generator_id == GENERATOR_ID
    assert finding.header.versions.generator.interface_id == ANALYZE_TEST_VACUITY_INTERFACE


def test_detects_type_only_assertion() -> None:
    subject = _test_subject(
        subject_id="unit.test_type_only",
        assertions=(
            _assertion(
                assertion_id="a_type",
                strength=TestAssertionStrength.TYPE_ONLY,
                expression="isinstance(result, dict)",
                observes_behavior=False,
                observes_effects=False,
            ),
        ),
    )
    result = analyze_test_vacuity(subject, _header())
    assert VacuityKind.TYPE_ONLY_ASSERTION.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.TYPE_ONLY_ASSERTION.value
    )
    assert "type" in finding.what_remains_proven.lower()
    assert subject.claimed_property in finding.what_is_not_proven


def test_detects_non_null_only_assertion() -> None:
    subject = _test_subject(
        subject_id="unit.test_non_null",
        assertions=(
            _assertion(
                assertion_id="a_nn",
                strength=TestAssertionStrength.NON_NULL_ONLY,
                expression="result is not None",
                observes_behavior=False,
                observes_effects=False,
            ),
        ),
    )
    result = analyze_test_vacuity(subject, _header())
    assert VacuityKind.NON_NULL_ONLY_ASSERTION.value in _kinds(result)


def test_detects_behavior_independent_mock() -> None:
    subject = _test_subject(
        subject_id="unit.test_mock",
        mocks=(
            _mock(
                mock_id="m_indep",
                target_symbol_id="mod.fn",
                behavior_independent=True,
            ),
        ),
    )
    result = analyze_test_vacuity(subject, _header())
    assert VacuityKind.BEHAVIOR_INDEPENDENT_MOCK.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.BEHAVIOR_INDEPENDENT_MOCK.value
    )
    assert "mod.fn" in finding.what_remains_proven
    assert "production behavior" in finding.what_is_not_proven


def test_detects_uncalled_target() -> None:
    subject = _test_subject(
        subject_id="unit.test_uncalled",
        target_symbol_ids=("mod.fn", "mod.other"),
        targets_called=("mod.fn",),
    )
    result = analyze_test_vacuity(subject, _header())
    assert VacuityKind.UNCALLED_TARGET.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.UNCALLED_TARGET.value
    )
    assert "mod.other" in finding.what_is_not_proven


def test_detects_permanent_skip() -> None:
    subject = _test_subject(
        subject_id="unit.test_skip",
        permanent_skip=True,
        skip_condition="pytest.mark.skip(reason='flaky')",
    )
    result = analyze_test_vacuity(subject, _header())
    assert VacuityKind.PERMANENT_SKIP.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.PERMANENT_SKIP.value
    )
    assert "flaky" in finding.what_remains_proven
    assert subject.claimed_property in finding.what_is_not_proven


def test_detects_path_bypassing_fixture() -> None:
    subject = _test_subject(
        subject_id="unit.test_bypass",
        fixture_bypasses_production_path=True,
        bypassed_path_ids=("mod.authz.guard",),
    )
    result = analyze_test_vacuity(subject, _header())
    assert VacuityKind.BYPASSING_FIXTURE.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.BYPASSING_FIXTURE.value
    )
    assert "mod.authz.guard" in finding.what_remains_proven
    assert "bypassed" in finding.what_is_not_proven.lower()


def test_detects_early_success_before_effect_observation() -> None:
    subject = _test_subject(
        subject_id="unit.test_early",
        assertions=(
            _assertion(
                assertion_id="a_type",
                strength=TestAssertionStrength.TYPE_ONLY,
                expression="isinstance(x, int)",
                observes_behavior=False,
                observes_effects=False,
            ),
        ),
        success_declared_before_effect_observation=True,
    )
    result = analyze_test_vacuity(subject, _header())
    assert VacuityKind.SUCCESS_BEFORE_EFFECT_OBSERVATION.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.SUCCESS_BEFORE_EFFECT_OBSERVATION.value
    )
    assert "before any effect" in finding.what_remains_proven
    assert "side effects" in finding.what_is_not_proven


def test_expression_tautology_marker_without_strength_flag() -> None:
    """Strength may be type_only while expression is still a classic tautology."""

    subject = _test_subject(
        subject_id="unit.test_expr_taut",
        assertions=(
            _assertion(
                assertion_id="a_eq",
                strength=TestAssertionStrength.TYPE_ONLY,
                expression="x == x",
                observes_behavior=False,
                observes_effects=False,
            ),
        ),
    )
    # Consistency rule: type_only with observes_behavior=false is admitted;
    # expression detector still flags tautology independently.
    result = analyze_test_vacuity(subject, _header())
    assert VacuityKind.TAUTOLOGY.value in _kinds(result)


# ---------------------------------------------------------------------------
# ZK / receipt / seal detections
# ---------------------------------------------------------------------------


def test_detects_unbound_required_fields() -> None:
    subject = _zk_subject(
        subject_id="receipt.unbound_fields",
        bound_fields=("repository_state_cid",),
    )
    result = analyze_zk_receipt_vacuity(subject, _header())
    assert VacuityKind.UNBOUND_REQUIRED_FIELD.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.UNBOUND_REQUIRED_FIELD.value
    )
    assert "environment_cid" in finding.what_is_not_proven
    assert "seal_digest" in finding.what_is_not_proven


def test_detects_unbound_source_root() -> None:
    subject = _zk_subject(
        subject_id="receipt.unbound_root",
        source_root_bound=False,
    )
    result = analyze_zk_receipt_vacuity(subject, _header())
    assert VacuityKind.UNBOUND_SOURCE.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.UNBOUND_SOURCE.value
    )
    assert "source" in finding.what_is_not_proven.lower()


def test_detects_unbound_environment() -> None:
    subject = _zk_subject(
        subject_id="receipt.unbound_env",
        environment_bound=False,
    )
    result = analyze_zk_receipt_vacuity(subject, _header())
    assert VacuityKind.UNBOUND_ENVIRONMENT.value in _kinds(result)


def test_detects_inclusion_without_required_set_completeness() -> None:
    subject = _zk_subject(
        subject_id="receipt.incomplete_set",
        required_set_ids=("unit.a", "unit.b", "unit.c"),
        included_set_ids=("unit.a",),
    )
    result = analyze_zk_receipt_vacuity(subject, _header())
    assert VacuityKind.INCLUSION_WITHOUT_COMPLETENESS.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.INCLUSION_WITHOUT_COMPLETENESS.value
    )
    assert "unit.a" in finding.what_remains_proven
    assert "unit.b" in finding.what_is_not_proven or "unit.c" in finding.what_is_not_proven


def test_detects_caller_selected_verification_key() -> None:
    subject = _zk_subject(
        subject_id="receipt.caller_key",
        verification_key_source=VerificationKeySource.CALLER,
    )
    result = analyze_zk_receipt_vacuity(subject, _header())
    assert VacuityKind.CALLER_SELECTED_VERIFICATION_KEY.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.CALLER_SELECTED_VERIFICATION_KEY.value
    )
    assert "caller" in finding.what_remains_proven.lower()
    assert "authority-bound" in finding.what_is_not_proven


def test_detects_unbound_verification_key() -> None:
    subject = _zk_subject(
        subject_id="receipt.unbound_key",
        verification_key_source=VerificationKeySource.UNBOUND,
    )
    result = analyze_zk_receipt_vacuity(subject, _header())
    assert VacuityKind.CALLER_SELECTED_VERIFICATION_KEY.value in _kinds(result)


def test_detects_signed_aggregation_direct_execution_overclaim() -> None:
    subject = _zk_subject(
        subject_id="receipt.agg_exec",
        is_signed_aggregation=True,
        claims_direct_execution=True,
    )
    result = analyze_zk_receipt_vacuity(subject, _header())
    assert VacuityKind.SIGNED_AGGREGATION_AS_EXECUTION.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.SIGNED_AGGREGATION_AS_EXECUTION.value
    )
    assert "signed aggregation" in finding.what_remains_proven.lower()
    assert "direct execution" in finding.what_is_not_proven.lower()


def test_signed_aggregation_without_execution_claim_is_not_vacuous() -> None:
    subject = _zk_subject(
        subject_id="receipt.agg_ok",
        is_signed_aggregation=True,
        claims_direct_execution=False,
    )
    result = analyze_zk_receipt_vacuity(subject, _header())
    assert VacuityKind.SIGNED_AGGREGATION_AS_EXECUTION.value not in _kinds(result)


def test_detects_delta_seal_unit_omission() -> None:
    subject = _zk_subject(
        subject_id="receipt.delta_miss",
        changed_unit_ids=("unit.a", "unit.b", "unit.c"),
        sealed_delta_unit_ids=("unit.a",),
    )
    result = analyze_zk_receipt_vacuity(subject, _header())
    assert VacuityKind.MISSING_DELTA_SEAL_UNIT.value in _kinds(result)
    finding = next(
        item
        for item in result.findings
        if item.vacuity_kind == VacuityKind.MISSING_DELTA_SEAL_UNIT.value
    )
    assert "unit.b" in finding.what_is_not_proven
    assert "unit.c" in finding.what_is_not_proven


def test_zk_precise_nonclaims_merge_declared_and_detected() -> None:
    subject = _zk_subject(
        subject_id="receipt.merge_nonclaims",
        source_root_bound=False,
        declared_nonclaims=(
            "does not prove inventory completeness",
            "trace validity is not translator soundness",
        ),
    )
    result = analyze_zk_receipt_vacuity(subject, _header())
    assert VacuityKind.UNBOUND_SOURCE.value in _kinds(result)
    assert "does not prove inventory completeness" in result.precise_nonclaims
    assert "trace validity is not translator soundness" in result.precise_nonclaims
    # Detected residual nonclaim also present.
    assert any("source-rooted" in item for item in result.precise_nonclaims)


# ---------------------------------------------------------------------------
# Fail-closed / identity / determinism
# ---------------------------------------------------------------------------


def test_incomplete_observation_fails_closed() -> None:
    with pytest.raises(VacuityTestZkError, match="observation_complete"):
        analyze_test_vacuity(
            _test_subject(observation_complete=False),
            _header(),
        )
    with pytest.raises(VacuityTestZkError, match="observation_complete"):
        analyze_zk_receipt_vacuity(
            _zk_subject(observation_complete=False),
            _header(),
        )


def test_bypass_without_path_ids_fails_closed() -> None:
    with pytest.raises(VacuityTestZkError, match="bypassed_path_ids"):
        _test_subject(
            fixture_bypasses_production_path=True,
            bypassed_path_ids=(),
        )


def test_targets_called_must_subset_targets() -> None:
    with pytest.raises(VacuityTestZkError, match="targets_called"):
        _test_subject(
            target_symbol_ids=("mod.fn",),
            targets_called=("mod.other",),
        )


def test_determinism_same_inputs_same_cids() -> None:
    subject = _test_subject(
        subject_id="unit.test_det",
        permanent_skip=True,
        skip_condition="always",
    )
    header = _header()
    a = analyze_test_vacuity(subject, header)
    b = analyze_test_vacuity(subject, header)
    assert a.result_cid == b.result_cid
    assert a.finding_cids == b.finding_cids
    assert [f.finding_cid for f in a.findings] == [f.finding_cid for f in b.findings]


def test_mapping_round_trip_for_subjects_and_results() -> None:
    test_subject = _test_subject(
        subject_id="unit.test_roundtrip",
        permanent_skip=True,
        skip_condition="x",
    )
    restored_subject = TestVacuitySubject.from_dict(test_subject.to_dict())
    assert restored_subject.subject_observation_cid == test_subject.subject_observation_cid

    zk_subject = _zk_subject(
        subject_id="receipt.roundtrip",
        environment_bound=False,
    )
    restored_zk = ZkReceiptVacuitySubject.from_dict(zk_subject.to_dict())
    assert restored_zk.subject_observation_cid == zk_subject.subject_observation_cid

    result = analyze_zk_receipt_vacuity(zk_subject, _header())
    restored = VacuityAnalysisResult.from_dict(result.to_dict())
    assert restored.result_cid == result.result_cid
    assert len(restored.findings) == len(result.findings)


def test_analyze_accepts_mapping_subjects() -> None:
    subject = _test_subject(
        subject_id="unit.test_mapping",
        permanent_skip=True,
        skip_condition="skip forever",
    )
    result = analyze_test_vacuity(subject.to_dict(), _header().to_dict())
    assert VacuityKind.PERMANENT_SKIP.value in _kinds(result)


def test_every_test_family_kind_is_reachable() -> None:
    """Matrix covering every admitted test vacuity kind at least once."""

    cases = [
        (
            VacuityKind.TAUTOLOGY,
            _test_subject(
                subject_id="unit.k_tautology",
                assertions=(
                    _assertion(
                        assertion_id="t",
                        strength=TestAssertionStrength.TAUTOLOGY,
                        expression="1",
                        observes_behavior=False,
                        observes_effects=False,
                    ),
                ),
            ),
        ),
        (
            VacuityKind.TYPE_ONLY_ASSERTION,
            _test_subject(
                subject_id="unit.k_type",
                assertions=(
                    _assertion(
                        assertion_id="t",
                        strength=TestAssertionStrength.TYPE_ONLY,
                        expression="type(x) is int",
                        observes_behavior=False,
                        observes_effects=False,
                    ),
                ),
            ),
        ),
        (
            VacuityKind.NON_NULL_ONLY_ASSERTION,
            _test_subject(
                subject_id="unit.k_nn",
                assertions=(
                    _assertion(
                        assertion_id="t",
                        strength=TestAssertionStrength.NON_NULL_ONLY,
                        expression="x is not None",
                        observes_behavior=False,
                        observes_effects=False,
                    ),
                ),
            ),
        ),
        (
            VacuityKind.BEHAVIOR_INDEPENDENT_MOCK,
            _test_subject(
                subject_id="unit.k_mock",
                mocks=(_mock(behavior_independent=True),),
            ),
        ),
        (
            VacuityKind.UNCALLED_TARGET,
            _test_subject(
                subject_id="unit.k_uncalled",
                target_symbol_ids=("mod.fn",),
                targets_called=(),
            ),
        ),
        (
            VacuityKind.PERMANENT_SKIP,
            _test_subject(subject_id="unit.k_skip", permanent_skip=True),
        ),
        (
            VacuityKind.BYPASSING_FIXTURE,
            _test_subject(
                subject_id="unit.k_bypass",
                fixture_bypasses_production_path=True,
                bypassed_path_ids=("mod.path",),
            ),
        ),
        (
            VacuityKind.SUCCESS_BEFORE_EFFECT_OBSERVATION,
            _test_subject(
                subject_id="unit.k_early",
                assertions=(
                    _assertion(
                        assertion_id="t",
                        strength=TestAssertionStrength.TYPE_ONLY,
                        expression="isinstance(x, str)",
                        observes_behavior=False,
                        observes_effects=False,
                    ),
                ),
                success_declared_before_effect_observation=True,
            ),
        ),
    ]
    seen: set[str] = set()
    for kind, subject in cases:
        result = analyze_test_vacuity(subject, _header())
        assert kind.value in _kinds(result), kind
        seen.add(kind.value)
        for finding in result.findings:
            assert finding.vacuity_family == VacuityFamily.TEST.value
            assert finding.what_remains_proven != finding.what_is_not_proven
            assert finding.what_remains_proven
            assert finding.what_is_not_proven
    assert seen == {
        VacuityKind.TAUTOLOGY.value,
        VacuityKind.TYPE_ONLY_ASSERTION.value,
        VacuityKind.NON_NULL_ONLY_ASSERTION.value,
        VacuityKind.BEHAVIOR_INDEPENDENT_MOCK.value,
        VacuityKind.UNCALLED_TARGET.value,
        VacuityKind.PERMANENT_SKIP.value,
        VacuityKind.BYPASSING_FIXTURE.value,
        VacuityKind.SUCCESS_BEFORE_EFFECT_OBSERVATION.value,
    }


def test_every_zk_receipt_family_kind_is_reachable() -> None:
    cases = [
        (
            VacuityKind.UNBOUND_REQUIRED_FIELD,
            _zk_subject(
                subject_id="zk.k_field",
                bound_fields=(),
            ),
        ),
        (
            VacuityKind.UNBOUND_SOURCE,
            _zk_subject(subject_id="zk.k_src", source_root_bound=False),
        ),
        (
            VacuityKind.UNBOUND_ENVIRONMENT,
            _zk_subject(subject_id="zk.k_env", environment_bound=False),
        ),
        (
            VacuityKind.INCLUSION_WITHOUT_COMPLETENESS,
            _zk_subject(
                subject_id="zk.k_incl",
                required_set_ids=("a", "b"),
                included_set_ids=("a",),
            ),
        ),
        (
            VacuityKind.CALLER_SELECTED_VERIFICATION_KEY,
            _zk_subject(
                subject_id="zk.k_key",
                verification_key_source=VerificationKeySource.CALLER,
            ),
        ),
        (
            VacuityKind.SIGNED_AGGREGATION_AS_EXECUTION,
            _zk_subject(
                subject_id="zk.k_agg",
                is_signed_aggregation=True,
                claims_direct_execution=True,
            ),
        ),
        (
            VacuityKind.MISSING_DELTA_SEAL_UNIT,
            _zk_subject(
                subject_id="zk.k_delta",
                changed_unit_ids=("u1", "u2"),
                sealed_delta_unit_ids=("u1",),
            ),
        ),
    ]
    seen: set[str] = set()
    for kind, subject in cases:
        result = analyze_zk_receipt_vacuity(subject, _header())
        assert kind.value in _kinds(result), kind
        seen.add(kind.value)
        for finding in result.findings:
            assert finding.vacuity_family == VacuityFamily.ZK_RECEIPT.value
            assert finding.what_remains_proven != finding.what_is_not_proven
    assert seen == {
        VacuityKind.UNBOUND_REQUIRED_FIELD.value,
        VacuityKind.UNBOUND_SOURCE.value,
        VacuityKind.UNBOUND_ENVIRONMENT.value,
        VacuityKind.INCLUSION_WITHOUT_COMPLETENESS.value,
        VacuityKind.CALLER_SELECTED_VERIFICATION_KEY.value,
        VacuityKind.SIGNED_AGGREGATION_AS_EXECUTION.value,
        VacuityKind.MISSING_DELTA_SEAL_UNIT.value,
    }


def test_forged_result_cid_rejected() -> None:
    result = analyze_test_vacuity(
        _test_subject(subject_id="unit.forge", permanent_skip=True),
        _header(),
    )
    payload = result.to_dict()
    payload["result_cid"] = _cid("forged")
    with pytest.raises(VacuityTestZkError, match="identity mismatch"):
        VacuityAnalysisResult.from_dict(payload)
