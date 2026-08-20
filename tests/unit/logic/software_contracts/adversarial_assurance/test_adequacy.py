"""Unit vectors for test/proof/policy/capsule adequacy profiles (AAE-029)."""

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
    AdequacyVerdict,
    CapsuleAdequacyGapClass,
    CapsuleAdequacyProfile,
    MinimizedEvidenceBinding,
    PolicyAdequacyGapClass,
    PolicyAdequacyProfile,
    ProofAdequacyGapClass,
    ProofAdequacyProfile,
    SourceSpan,
    TestAdequacyGapClass,
    TestAdequacyProfile,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.adequacy import (
    BUILD_CAPSULE_ADEQUACY_PROFILE_INTERFACE,
    BUILD_POLICY_ADEQUACY_PROFILE_INTERFACE,
    BUILD_PROOF_ADEQUACY_PROFILE_INTERFACE,
    BUILD_TEST_ADEQUACY_PROFILE_INTERFACE,
    GENERATOR_ID,
    AdequacyClaimBinding,
    AdequacyError,
    AdequacyProfileBuildResult,
    AdequacyScopeBinding,
    CapsuleAdequacySubject,
    DetectorAdequacyBinding,
    DetectorAdequacyRole,
    FalseAssuranceEvidenceBinding,
    FalseAssuranceEvidenceKind,
    PolicyAdequacySubject,
    ProofAdequacySubject,
    ReachableBehaviorBinding,
    TestAdequacySubject,
    UncertaintyBinding,
    UncertaintyKind,
    build_capsule_adequacy_profile,
    build_policy_adequacy_profile,
    build_proof_adequacy_profile,
    build_test_adequacy_profile,
    detector_adequacy_roles,
    false_assurance_evidence_kinds,
    score_authority_forbidden_keys,
    uncertainty_kinds,
    verify_adequacy_profile_build_result_identity,
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
        "artifact_kind": "test_adequacy_profile",
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


def _claim(**overrides: object) -> AdequacyClaimBinding:
    fields = {
        "claim_id": "claim.authz.preserves_tenant",
        "claim_text": "authorization must preserve tenant boundary",
        "property_class": "authorization",
        "symbol_ids": ("mod.fn",),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return AdequacyClaimBinding(**fields)  # type: ignore[arg-type]


def _behavior(**overrides: object) -> ReachableBehaviorBinding:
    fields = {
        "behavior_id": "behavior.authz.check",
        "description": "tenant authorization check executes on request path",
        "reachable": True,
        "exercised": True,
        "required": True,
        "symbol_ids": ("mod.fn",),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ReachableBehaviorBinding(**fields)  # type: ignore[arg-type]


def _detector(
    detector_id: str = "unit.test_authz",
    *,
    role: DetectorAdequacyRole = DetectorAdequacyRole.COVERED,
    **overrides: object,
) -> DetectorAdequacyBinding:
    fields = {
        "detector_id": detector_id,
        "role": role,
        "detector_kind": "unit_test",
        "claim_ids": ("claim.authz.preserves_tenant",),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return DetectorAdequacyBinding(**fields)  # type: ignore[arg-type]


def _false_assurance(**overrides: object) -> FalseAssuranceEvidenceBinding:
    fields = {
        "evidence_id": "fa.survivor.1",
        "evidence_kind": FalseAssuranceEvidenceKind.SURVIVING_MUTANT,
        "evidence_cid": _cid("survivor-1"),
        "summary": "mutant survived predicted unit test",
        "claim_ids": ("claim.authz.preserves_tenant",),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return FalseAssuranceEvidenceBinding(**fields)  # type: ignore[arg-type]


def _uncertainty(**overrides: object) -> UncertaintyBinding:
    fields = {
        "uncertainty_id": "unc.human.1",
        "kind": UncertaintyKind.HUMAN_REVIEW_REQUIRED,
        "description": "high-value residual requires human review",
        "blocks_adequacy": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return UncertaintyBinding(**fields)  # type: ignore[arg-type]


def _scope(**overrides: object) -> AdequacyScopeBinding:
    fields = {
        "scope_id": "scope.mod.fn",
        "target_symbol_ids": ("mod.fn",),
        "in_scope_artifact_cids": (_cid("artifact-a"),),
        "out_of_scope_symbol_ids": ("mod.helpers",),
        "out_of_scope_notes": ("helpers are out of campaign scope",),
        "repository_state_cid": _cid("repo-state"),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return AdequacyScopeBinding(**fields)  # type: ignore[arg-type]


def _test_subject(**overrides: object) -> TestAdequacySubject:
    fields = {
        "subject_id": "subj.test.1",
        "profile_id": "test_adeq.1",
        "claims": (_claim(),),
        "reachable_behaviors": (_behavior(),),
        "detectors": (_detector(),),
        "scope": _scope(),
        "source_spans": (_span(),),
        "minimized_evidence": _evidence(),
        "false_assurance_evidence": (),
        "uncertainty": (),
        "gap_signals": (),
        "weak_assertions": False,
        "tautology_assertions": False,
        "uncalled_targets": False,
        "permanent_skips": False,
        "mock_bypasses": False,
        "fixture_bypasses": False,
        "success_before_effect": False,
        "type_only_coverage": False,
        "selection_misses": False,
        "observation_complete": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return TestAdequacySubject(**fields)  # type: ignore[arg-type]


def _proof_subject(**overrides: object) -> ProofAdequacySubject:
    fields = {
        "subject_id": "subj.proof.1",
        "profile_id": "proof_adeq.1",
        "claims": (_claim(claim_id="claim.proof.authz"),),
        "reachable_behaviors": (
            _behavior(behavior_id="behavior.proof.discharge", exercised=True),
        ),
        "detectors": (
            _detector(
                "formal.authz_obligation",
                role=DetectorAdequacyRole.COVERED,
                detector_kind="formal_obligation",
                claim_ids=("claim.proof.authz",),
            ),
        ),
        "scope": _scope(scope_id="scope.proof.mod.fn"),
        "source_spans": (_span(path="proofs/authz.lean"),),
        "minimized_evidence": _evidence(),
        "proof_unit_cids": (_cid("proof-unit-a"),),
        "missing_obligation_ids": (),
        "false_assurance_evidence": (),
        "uncertainty": (),
        "gap_signals": (),
        "vacuous_proof": False,
        "unsatisfiable_antecedent": False,
        "unreachable_state": False,
        "assumed_not_proven": False,
        "omitted_behavior": False,
        "stale_proof_unit": False,
        "observation_complete": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ProofAdequacySubject(**fields)  # type: ignore[arg-type]


def _policy_subject(**overrides: object) -> PolicyAdequacySubject:
    fields = {
        "subject_id": "subj.policy.1",
        "profile_id": "policy_adeq.1",
        "claims": (_claim(claim_id="claim.policy.deny_default"),),
        "reachable_behaviors": (
            _behavior(behavior_id="behavior.policy.deny", exercised=True),
        ),
        "detectors": (
            _detector(
                "policy.deny_default",
                role=DetectorAdequacyRole.COVERED,
                detector_kind="policy_rule",
                claim_ids=("claim.policy.deny_default",),
            ),
        ),
        "scope": _scope(scope_id="scope.policy.mod.fn"),
        "source_spans": (_span(path="policy/authz.json"),),
        "minimized_evidence": _evidence(),
        "policy_cids": (_cid("policy"),),
        "missing_constraint_ids": (),
        "false_assurance_evidence": (),
        "uncertainty": (),
        "gap_signals": (),
        "unreachable_rule": False,
        "shadowed_prohibition": False,
        "dominating_default": False,
        "impossible_obligation": False,
        "obsolete_interface": False,
        "stale_policy": False,
        "observation_complete": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return PolicyAdequacySubject(**fields)  # type: ignore[arg-type]


def _capsule_subject(**overrides: object) -> CapsuleAdequacySubject:
    fields = {
        "subject_id": "subj.capsule.1",
        "profile_id": "capsule_adeq.1",
        "claims": (_claim(claim_id="claim.capsule.complete"),),
        "reachable_behaviors": (
            _behavior(behavior_id="behavior.capsule.effect", exercised=True),
        ),
        "detectors": (
            _detector(
                "capsule.freshness",
                role=DetectorAdequacyRole.COVERED,
                detector_kind="static_rule",
                claim_ids=("claim.capsule.complete",),
            ),
        ),
        "scope": _scope(scope_id="scope.capsule.mod.fn"),
        "source_spans": (_span(path="src/mod.py"),),
        "minimized_evidence": _evidence(),
        "capsule_cids": (_cid("capsule-a"),),
        "omitted_edge_ids": (),
        "false_assurance_evidence": (),
        "uncertainty": (),
        "gap_signals": (),
        "omitted_dependency": False,
        "omitted_config": False,
        "omitted_fixture": False,
        "omitted_exception": False,
        "omitted_effect": False,
        "stale_capsule": False,
        "wrong_root": False,
        "heuristic_as_exact": False,
        "opaque_as_exact": False,
        "selection_miss": False,
        "observation_complete": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return CapsuleAdequacySubject(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


def test_closed_detector_roles_and_uncertainty_kinds() -> None:
    assert detector_adequacy_roles() == (
        "covered",
        "missing",
        "predicted",
        "optional",
        "omitted",
    )
    assert "score_only_signal" in uncertainty_kinds()
    assert "surviving_mutant" in false_assurance_evidence_kinds()
    assert "mutation_score" in score_authority_forbidden_keys()
    with pytest.raises(ValueError):
        DetectorAdequacyRole("maybe_covered")
    with pytest.raises(ValueError):
        UncertaintyKind("vibes")


# ---------------------------------------------------------------------------
# Binding records — identity and invariants
# ---------------------------------------------------------------------------


def test_claim_and_behavior_bindings_seal_identity() -> None:
    claim = _claim()
    restored = AdequacyClaimBinding.from_dict(claim.to_dict())
    assert restored.binding_cid == claim.binding_cid
    behavior = _behavior(exercised=False)
    restored_b = ReachableBehaviorBinding.from_dict(behavior.to_dict())
    assert restored_b.binding_cid == behavior.binding_cid
    with pytest.raises(AdequacyError, match="exercised behavior must also"):
        _behavior(reachable=False, exercised=True)


def test_scope_rejects_in_and_out_overlap() -> None:
    with pytest.raises(AdequacyError, match="disjoint"):
        _scope(
            target_symbol_ids=("mod.fn",),
            out_of_scope_symbol_ids=("mod.fn",),
        )


def test_detector_ids_must_be_unique_across_roles() -> None:
    with pytest.raises(AdequacyError, match="unique"):
        TestAdequacySubject(
            subject_id="subj.bad",
            profile_id="test_adeq.bad",
            claims=(_claim(),),
            reachable_behaviors=(_behavior(),),
            detectors=(
                _detector("unit.dup", role=DetectorAdequacyRole.COVERED),
                DetectorAdequacyBinding(
                    detector_id="unit.dup",
                    role=DetectorAdequacyRole.MISSING,
                ),
            ),
            scope=_scope(),
            source_spans=(_span(),),
            minimized_evidence=_evidence(),
        )


# ---------------------------------------------------------------------------
# build_test_adequacy_profile
# ---------------------------------------------------------------------------


def test_build_test_profile_adequate_binds_all_facets() -> None:
    result = build_test_adequacy_profile(_test_subject(), _header())
    assert result.interface_id == BUILD_TEST_ADEQUACY_PROFILE_INTERFACE
    assert result.surface == "test"
    assert result.verdict == AdequacyVerdict.ADEQUATE.value
    assert list(result.gap_classes) == ["none"]
    assert result.score_establishes_correctness is False
    assert "claim.authz.preserves_tenant" in result.claim_ids
    assert "behavior.authz.check" in result.reachable_behavior_ids
    assert "unit.test_authz" in result.detector_ids
    assert result.scope_id == "scope.mod.fn"

    profile = TestAdequacyProfile.from_dict(result.profile)
    assert profile.verdict == AdequacyVerdict.ADEQUATE.value
    assert profile.covered_detector_ids == ("unit.test_authz",)
    assert profile.missing_detector_ids == ()
    # Metadata binds claims, behaviors, detectors, false-assurance, uncertainty, scope.
    meta = dict(profile.metadata)
    assert meta["score_establishes_correctness"] is False
    assert meta["bindings_complete"] is True
    assert list(meta["claim_ids"]) == ["claim.authz.preserves_tenant"]
    assert list(meta["reachable_behavior_ids"]) == ["behavior.authz.check"]
    assert list(meta["covered_detector_ids"]) == ["unit.test_authz"]
    assert list(meta["false_assurance_evidence_ids"]) == []
    assert list(meta["uncertainty_ids"]) == []
    assert meta["scope_id"] == "scope.mod.fn"
    assert meta["generator_id"] == GENERATOR_ID
    assert profile.header.versions.generator.generator_id == GENERATOR_ID
    assert (
        profile.header.versions.generator.interface_id
        == BUILD_TEST_ADEQUACY_PROFILE_INTERFACE
    )

    verify_adequacy_profile_build_result_identity(result)
    restored = AdequacyProfileBuildResult.from_dict(result.to_dict())
    assert restored.result_cid == result.result_cid


def test_build_test_profile_inadequate_on_weak_assertion_and_false_assurance() -> None:
    subject = _test_subject(
        weak_assertions=True,
        false_assurance_evidence=(_false_assurance(),),
        detectors=(
            _detector("unit.smoke", role=DetectorAdequacyRole.COVERED),
            _detector("unit.authz", role=DetectorAdequacyRole.MISSING),
        ),
        reachable_behaviors=(
            _behavior(behavior_id="behavior.authz.check", exercised=False),
        ),
    )
    result = build_test_adequacy_profile(subject, _header())
    assert result.verdict in {
        AdequacyVerdict.INADEQUATE.value,
        AdequacyVerdict.PARTIAL.value,
    }
    assert TestAdequacyGapClass.WEAK_ASSERTION.value in result.gap_classes
    assert TestAdequacyGapClass.MISSING_BEHAVIOR_ASSERTION.value in result.gap_classes
    assert "fa.survivor.1" in result.false_assurance_evidence_ids
    profile = TestAdequacyProfile.from_dict(result.profile)
    assert "unit.smoke" in profile.covered_detector_ids
    assert "unit.authz" in profile.missing_detector_ids
    assert profile.metadata["false_assurance_evidence_cids"]


def test_build_test_profile_maps_all_test_gap_flags() -> None:
    subject = _test_subject(
        tautology_assertions=True,
        uncalled_targets=True,
        permanent_skips=True,
        mock_bypasses=True,
        fixture_bypasses=True,
        success_before_effect=True,
        type_only_coverage=True,
        selection_misses=True,
        detectors=(
            _detector("unit.selected", role=DetectorAdequacyRole.MISSING),
        ),
        reachable_behaviors=(
            _behavior(behavior_id="behavior.authz.check", exercised=False),
        ),
    )
    result = build_test_adequacy_profile(subject, _header())
    gaps = set(result.gap_classes)
    assert TestAdequacyGapClass.TAUTOLOGY.value in gaps
    assert TestAdequacyGapClass.UNCALLED_TARGET.value in gaps
    assert TestAdequacyGapClass.PERMANENT_SKIP.value in gaps
    assert TestAdequacyGapClass.MOCK_BYPASS.value in gaps
    assert TestAdequacyGapClass.FIXTURE_BYPASS.value in gaps
    assert TestAdequacyGapClass.SUCCESS_BEFORE_EFFECT.value in gaps
    assert TestAdequacyGapClass.TYPE_ONLY_COVERAGE.value in gaps
    assert TestAdequacyGapClass.SELECTION_MISS.value in gaps
    assert result.verdict != AdequacyVerdict.ADEQUATE.value


def test_build_test_profile_fails_closed_on_incomplete_observation() -> None:
    with pytest.raises(AdequacyError, match="observation_complete"):
        build_test_adequacy_profile(
            _test_subject(observation_complete=False),
            _header(),
        )


def test_build_test_profile_rejects_score_as_correctness_authority() -> None:
    with pytest.raises(AdequacyError, match="score"):
        _test_subject(metadata={"mutation_score": "0.99"})
    with pytest.raises(AdequacyError, match="score"):
        build_test_adequacy_profile(
            _test_subject(),
            _header(),
            metadata={"score_establishes_correctness": True},
        )
    with pytest.raises(AdequacyError, match="score"):
        _claim(metadata={"kill_rate": "1"})
    # Explicit non-authority documentation is admitted.
    ok = _test_subject(metadata={"score_establishes_correctness": False})
    assert ok.metadata["score_establishes_correctness"] is False


def test_build_test_profile_inconclusive_on_blocking_uncertainty_only() -> None:
    subject = _test_subject(
        uncertainty=(
            _uncertainty(
                uncertainty_id="unc.score",
                kind=UncertaintyKind.SCORE_ONLY_SIGNAL,
                description="only a composite score is available; not authority",
            ),
        ),
    )
    result = build_test_adequacy_profile(subject, _header())
    assert result.verdict == AdequacyVerdict.INCONCLUSIVE.value
    assert result.score_establishes_correctness is False
    assert "unc.score" in result.uncertainty_ids


def test_build_test_profile_explicit_gap_signals() -> None:
    subject = _test_subject(
        gap_signals=(TestAdequacyGapClass.MOCK_BYPASS,),
        detectors=(_detector("unit.smoke", role=DetectorAdequacyRole.COVERED),),
    )
    result = build_test_adequacy_profile(subject, _header())
    assert TestAdequacyGapClass.MOCK_BYPASS.value in result.gap_classes
    assert result.verdict in {
        AdequacyVerdict.PARTIAL.value,
        AdequacyVerdict.INADEQUATE.value,
    }


def test_build_test_profile_rejects_none_in_gap_signals() -> None:
    with pytest.raises(AdequacyError, match="must not include 'none'"):
        _test_subject(gap_signals=("none",))


# ---------------------------------------------------------------------------
# build_proof_adequacy_profile
# ---------------------------------------------------------------------------


def test_build_proof_profile_adequate() -> None:
    result = build_proof_adequacy_profile(_proof_subject(), _header())
    assert result.interface_id == BUILD_PROOF_ADEQUACY_PROFILE_INTERFACE
    assert result.surface == "proof"
    assert result.verdict == AdequacyVerdict.ADEQUATE.value
    profile = ProofAdequacyProfile.from_dict(result.profile)
    assert profile.proof_unit_cids == (_cid("proof-unit-a"),)
    assert profile.missing_obligation_ids == ()
    assert profile.metadata["claim_ids"]
    assert profile.metadata["scope_id"] == "scope.proof.mod.fn"
    assert profile.header.artifact_kind == "proof_adequacy_profile"
    verify_adequacy_profile_build_result_identity(result)


def test_build_proof_profile_inadequate_on_vacuity_and_missing_obligation() -> None:
    subject = _proof_subject(
        vacuous_proof=True,
        unsatisfiable_antecedent=True,
        unreachable_state=True,
        assumed_not_proven=True,
        omitted_behavior=True,
        stale_proof_unit=True,
        missing_obligation_ids=("authz.preserves_tenant",),
        false_assurance_evidence=(
            _false_assurance(
                evidence_id="fa.vacuity.1",
                evidence_kind=FalseAssuranceEvidenceKind.VACUITY_FINDING,
                evidence_cid=_cid("vacuity-1"),
                summary="antecedent unsatisfiable",
            ),
        ),
    )
    result = build_proof_adequacy_profile(subject, _header())
    gaps = set(result.gap_classes)
    assert ProofAdequacyGapClass.VACUOUS_PROOF.value in gaps
    assert ProofAdequacyGapClass.UNSATISFIABLE_ANTECEDENT.value in gaps
    assert ProofAdequacyGapClass.UNREACHABLE_STATE.value in gaps
    assert ProofAdequacyGapClass.ASSUMED_NOT_PROVEN.value in gaps
    assert ProofAdequacyGapClass.OMITTED_BEHAVIOR.value in gaps
    assert ProofAdequacyGapClass.STALE_PROOF_UNIT.value in gaps
    assert ProofAdequacyGapClass.MISSING_OBLIGATION.value in gaps
    assert result.verdict != AdequacyVerdict.ADEQUATE.value
    profile = ProofAdequacyProfile.from_dict(result.profile)
    assert "authz.preserves_tenant" in profile.missing_obligation_ids


def test_build_proof_profile_fails_closed_incomplete() -> None:
    with pytest.raises(AdequacyError, match="observation_complete"):
        build_proof_adequacy_profile(
            _proof_subject(observation_complete=False),
            _header(),
        )


# ---------------------------------------------------------------------------
# build_policy_adequacy_profile
# ---------------------------------------------------------------------------


def test_build_policy_profile_adequate() -> None:
    result = build_policy_adequacy_profile(_policy_subject(), _header())
    assert result.interface_id == BUILD_POLICY_ADEQUACY_PROFILE_INTERFACE
    assert result.surface == "policy"
    assert result.verdict == AdequacyVerdict.ADEQUATE.value
    profile = PolicyAdequacyProfile.from_dict(result.profile)
    assert profile.policy_cids == (_cid("policy"),)
    assert profile.metadata["bindings_complete"] is True
    assert profile.metadata["score_establishes_correctness"] is False
    verify_adequacy_profile_build_result_identity(result)


def test_build_policy_profile_inadequate_on_policy_gaps() -> None:
    subject = _policy_subject(
        missing_constraint_ids=("deny_default",),
        unreachable_rule=True,
        shadowed_prohibition=True,
        dominating_default=True,
        impossible_obligation=True,
        obsolete_interface=True,
        stale_policy=True,
        false_assurance_evidence=(
            _false_assurance(
                evidence_id="fa.gap.1",
                evidence_kind=FalseAssuranceEvidenceKind.ASSURANCE_GAP,
                evidence_cid=_cid("gap-1"),
                summary="default allow accepted unauthorized caller",
            ),
        ),
    )
    result = build_policy_adequacy_profile(subject, _header())
    gaps = set(result.gap_classes)
    assert PolicyAdequacyGapClass.MISSING_CONSTRAINT.value in gaps
    assert PolicyAdequacyGapClass.UNREACHABLE_RULE.value in gaps
    assert PolicyAdequacyGapClass.SHADOWED_PROHIBITION.value in gaps
    assert PolicyAdequacyGapClass.DOMINATING_DEFAULT.value in gaps
    assert PolicyAdequacyGapClass.IMPOSSIBLE_OBLIGATION.value in gaps
    assert PolicyAdequacyGapClass.OBSOLETE_INTERFACE.value in gaps
    assert PolicyAdequacyGapClass.STALE_POLICY.value in gaps
    profile = PolicyAdequacyProfile.from_dict(result.profile)
    assert "deny_default" in profile.missing_constraint_ids


def test_build_policy_profile_uses_header_policy_cid_when_subject_empty() -> None:
    subject = _policy_subject(policy_cids=())
    result = build_policy_adequacy_profile(subject, _header())
    profile = PolicyAdequacyProfile.from_dict(result.profile)
    assert profile.policy_cids == (_cid("policy"),)


# ---------------------------------------------------------------------------
# build_capsule_adequacy_profile
# ---------------------------------------------------------------------------


def test_build_capsule_profile_adequate() -> None:
    result = build_capsule_adequacy_profile(_capsule_subject(), _header())
    assert result.interface_id == BUILD_CAPSULE_ADEQUACY_PROFILE_INTERFACE
    assert result.surface == "capsule"
    assert result.verdict == AdequacyVerdict.ADEQUATE.value
    profile = CapsuleAdequacyProfile.from_dict(result.profile)
    assert profile.capsule_cids == (_cid("capsule-a"),)
    assert profile.omitted_edge_ids == ()
    assert profile.metadata["reachable_behavior_ids"]
    verify_adequacy_profile_build_result_identity(result)


def test_build_capsule_profile_inadequate_on_omissions() -> None:
    subject = _capsule_subject(
        omitted_edge_ids=("edge.config", "edge.effect"),
        omitted_dependency=True,
        omitted_config=True,
        omitted_fixture=True,
        omitted_exception=True,
        omitted_effect=True,
        stale_capsule=True,
        wrong_root=True,
        heuristic_as_exact=True,
        opaque_as_exact=True,
        selection_miss=True,
        false_assurance_evidence=(
            _false_assurance(
                evidence_id="fa.capsule.1",
                evidence_kind=FalseAssuranceEvidenceKind.DETECTION_FAILURE,
                evidence_cid=_cid("detfail-1"),
                summary="capsule omitted required effect edge",
            ),
        ),
    )
    result = build_capsule_adequacy_profile(subject, _header())
    gaps = set(result.gap_classes)
    assert CapsuleAdequacyGapClass.OMITTED_DEPENDENCY.value in gaps
    assert CapsuleAdequacyGapClass.OMITTED_CONFIG.value in gaps
    assert CapsuleAdequacyGapClass.OMITTED_FIXTURE.value in gaps
    assert CapsuleAdequacyGapClass.OMITTED_EXCEPTION.value in gaps
    assert CapsuleAdequacyGapClass.OMITTED_EFFECT.value in gaps
    assert CapsuleAdequacyGapClass.STALE_CAPSULE.value in gaps
    assert CapsuleAdequacyGapClass.WRONG_ROOT.value in gaps
    assert CapsuleAdequacyGapClass.HEURISTIC_AS_EXACT.value in gaps
    assert CapsuleAdequacyGapClass.OPAQUE_AS_EXACT.value in gaps
    assert CapsuleAdequacyGapClass.SELECTION_MISS.value in gaps
    profile = CapsuleAdequacyProfile.from_dict(result.profile)
    assert "edge.config" in profile.omitted_edge_ids
    assert result.verdict != AdequacyVerdict.ADEQUATE.value


def test_build_capsule_profile_fails_closed_incomplete() -> None:
    with pytest.raises(AdequacyError, match="observation_complete"):
        build_capsule_adequacy_profile(
            _capsule_subject(observation_complete=False),
            _header(),
        )


# ---------------------------------------------------------------------------
# Cross-surface acceptance properties
# ---------------------------------------------------------------------------


def test_all_builders_bind_claims_behavior_detectors_evidence_uncertainty_gaps_scope() -> None:
    """Acceptance: profiles bind all required facets; scores never correct."""

    subjects_and_builders = (
        (
            _test_subject(
                false_assurance_evidence=(_false_assurance(),),
                uncertainty=(_uncertainty(blocks_adequacy=False),),
                weak_assertions=True,
            ),
            build_test_adequacy_profile,
            "test",
        ),
        (
            _proof_subject(
                missing_obligation_ids=("obl.1",),
                false_assurance_evidence=(
                    _false_assurance(
                        evidence_id="fa.p.1",
                        evidence_cid=_cid("fa-p"),
                    ),
                ),
                uncertainty=(_uncertainty(uncertainty_id="unc.p.1", blocks_adequacy=False),),
            ),
            build_proof_adequacy_profile,
            "proof",
        ),
        (
            _policy_subject(
                missing_constraint_ids=("c.1",),
                false_assurance_evidence=(
                    _false_assurance(
                        evidence_id="fa.pol.1",
                        evidence_cid=_cid("fa-pol"),
                    ),
                ),
                uncertainty=(
                    _uncertainty(uncertainty_id="unc.pol.1", blocks_adequacy=False),
                ),
            ),
            build_policy_adequacy_profile,
            "policy",
        ),
        (
            _capsule_subject(
                omitted_edge_ids=("e.1",),
                false_assurance_evidence=(
                    _false_assurance(
                        evidence_id="fa.cap.1",
                        evidence_cid=_cid("fa-cap"),
                    ),
                ),
                uncertainty=(
                    _uncertainty(uncertainty_id="unc.cap.1", blocks_adequacy=False),
                ),
            ),
            build_capsule_adequacy_profile,
            "capsule",
        ),
    )

    for subject, builder, surface in subjects_and_builders:
        result = builder(subject, _header())
        assert result.surface == surface
        assert result.claim_ids
        assert result.reachable_behavior_ids
        assert result.detector_ids
        assert result.false_assurance_evidence_ids
        assert result.uncertainty_ids
        assert result.scope_id
        assert result.gap_classes
        assert "none" not in result.gap_classes or result.verdict == AdequacyVerdict.ADEQUATE.value
        assert result.score_establishes_correctness is False
        profile_meta = dict(result.profile["metadata"])
        assert profile_meta["score_establishes_correctness"] is False
        assert profile_meta["bindings_complete"] is True
        assert profile_meta["claim_ids"]
        assert profile_meta["reachable_behavior_ids"]
        assert profile_meta["detector_ids"]
        assert profile_meta["false_assurance_evidence_ids"]
        assert profile_meta["uncertainty_ids"]
        assert profile_meta["scope_id"]
        assert profile_meta["subject_observation_cid"] == result.subject_observation_cid


def test_score_never_upgrades_to_adequate() -> None:
    """High-looking residual coverage still inadequate when gaps exist."""

    subject = _test_subject(
        weak_assertions=True,
        detectors=(
            _detector("unit.a", role=DetectorAdequacyRole.COVERED),
            _detector("unit.b", role=DetectorAdequacyRole.COVERED),
            _detector("unit.c", role=DetectorAdequacyRole.COVERED),
            _detector("unit.d", role=DetectorAdequacyRole.MISSING),
        ),
        # Attempting to smuggle score authority is rejected at subject construction.
    )
    result = build_test_adequacy_profile(subject, _header())
    assert result.verdict != AdequacyVerdict.ADEQUATE.value
    assert result.score_establishes_correctness is False


def test_subject_round_trip_identity() -> None:
    for subject in (
        _test_subject(),
        _proof_subject(),
        _policy_subject(),
        _capsule_subject(),
    ):
        restored = type(subject).from_dict(subject.to_dict())
        assert restored.subject_observation_cid == subject.subject_observation_cid


def test_deterministic_build_results() -> None:
    a = build_test_adequacy_profile(_test_subject(), _header())
    b = build_test_adequacy_profile(_test_subject(), _header())
    assert a.result_cid == b.result_cid
    assert a.profile_cid == b.profile_cid


def test_false_assurance_alone_prevents_adequate() -> None:
    subject = _test_subject(
        false_assurance_evidence=(_false_assurance(),),
    )
    result = build_test_adequacy_profile(subject, _header())
    assert result.verdict != AdequacyVerdict.ADEQUATE.value
    assert result.gap_classes != ("none",)


def test_build_result_rejects_score_establishes_correctness_true() -> None:
    base = build_test_adequacy_profile(_test_subject(), _header())
    payload = base.to_dict()
    payload["score_establishes_correctness"] = True
    # Recompute cid after mutation would mismatch; mutate after drop.
    payload.pop("result_cid")
    # Reconstruct without claimed cid path uses constructor.
    with pytest.raises(AdequacyError, match="score_establishes_correctness"):
        AdequacyProfileBuildResult(
            interface_id=payload["interface_id"],
            surface=payload["surface"],
            subject_id=payload["subject_id"],
            subject_observation_cid=payload["subject_observation_cid"],
            profile_id=payload["profile_id"],
            profile_cid=payload["profile_cid"],
            verdict=payload["verdict"],
            gap_classes=payload["gap_classes"],
            claim_ids=payload["claim_ids"],
            reachable_behavior_ids=payload["reachable_behavior_ids"],
            detector_ids=payload["detector_ids"],
            false_assurance_evidence_ids=payload["false_assurance_evidence_ids"],
            uncertainty_ids=payload["uncertainty_ids"],
            scope_id=payload["scope_id"],
            score_establishes_correctness=True,
            profile=payload["profile"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
