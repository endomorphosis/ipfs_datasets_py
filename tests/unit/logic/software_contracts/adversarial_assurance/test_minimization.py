"""Unit vectors for minimized survivor reports and bounded reproduction evidence (AAE-031)."""

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
    SourceSpan,
    SurvivingMutantReport,
    SurvivorRiskClass,
    verify_survivor_report_identity,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.minimization import (
    BUILD_SURVIVING_MUTANT_REPORT_INTERFACE,
    GENERATOR_ID,
    GENERATOR_VERSION,
    REQUIRED_REPORT_SURFACE_KEYS,
    BoundedLogDigest,
    MinimizationError,
    MinimizationStatus,
    SurvivorMinimizationSubject,
    SurvivorReportBuildResult,
    build_surviving_mutant_report,
    full_log_forbidden_keys,
    logs_remain_bounded,
    minimize_source_spans,
    minimization_statuses,
    report_contains_required_surface,
    verify_survivor_report_build_result_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


REPO_ID = "repository:sha256:test-repo-identity"
REPO_STATE = _cid("repo-state")
CANDIDATE_ID = "cand_control_flow_invert_0"
CANDIDATE_CID = _cid("candidate")
OUTCOME_CID = _cid("outcome")


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "mutation_campaign",
        "generator_version": "1.0.0",
        "interface_id": "generate_mutation_candidates@1",
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
        "artifact_kind": "mutation_candidate",
        "repository_id": REPO_ID,
        "repository_state_cid": REPO_STATE,
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
        "path": "src/mod.py",
        "start_line": 10,
        "end_line": 12,
        "start_col": 0,
        "end_col": 40,
    }
    fields.update(overrides)
    return SourceSpan(**fields)  # type: ignore[arg-type]


def _digest(**overrides: object) -> BoundedLogDigest:
    fields = {
        "digest_cid": _cid("log-digest"),
        "byte_count": 4096,
        "truncated": True,
        "full_log_excluded": True,
        "notes": "first 4 KiB retained under budget",
    }
    fields.update(overrides)
    return BoundedLogDigest(**fields)  # type: ignore[arg-type]


def _subject(**overrides: object) -> SurvivorMinimizationSubject:
    fields = {
        "subject_id": "subj.survivor.1",
        "report_id": "survivor_1",
        "candidate_id": CANDIDATE_ID,
        "candidate_cid": CANDIDATE_CID,
        "outcome_cid": OUTCOME_CID,
        "risk_class": SurvivorRiskClass.AUTHORIZATION,
        "symbol_ids": ("mod.fn",),
        "violated_or_missing_property": "authorization check must remain present",
        "source_spans": (_span(),),
        "detectors_run": ("unit.test_branch",),
        "detectors_omitted": ("static.authz_rule",),
        "expected_behavior": "reject unauthorized caller",
        "observed_behavior": "unauthorized caller accepted",
        "dependency_path": ("mod.fn", "authz.check"),
        "reproduction_command": "pytest -q tests/test_authz.py::test_reject",
        "evidence_cids": (_cid("min-evidence-1"),),
        "reproduction_input_cid": _cid("repro-input"),
        "proof_cids": (_cid("proof-a"),),
        "receipt_cids": (_cid("receipt-a"),),
        "equivalence_assessment_cid": None,
        "minimization_status": MinimizationStatus.MINIMIZED,
        "minimization_failure_reason": None,
        "bounded_log_digest": None,
        "observation_complete": True,
        "repository_state_cid": REPO_STATE,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return SurvivorMinimizationSubject(**fields)  # type: ignore[arg-type]


def _build(**overrides: object) -> SurvivorReportBuildResult:
    subject = overrides.pop("subject", _subject())
    header = overrides.pop("header", _header())
    return build_surviving_mutant_report(subject, header, **overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


def test_minimization_status_vocabulary_is_closed() -> None:
    assert minimization_statuses() == (
        MinimizationStatus.MINIMIZED.value,
        MinimizationStatus.FAILED.value,
    )
    assert "full_log" in full_log_forbidden_keys()
    assert "raw_traceback" in full_log_forbidden_keys()
    with pytest.raises(ValueError):
        MinimizationStatus("partially_minimized")


# ---------------------------------------------------------------------------
# Span minimization — smallest changed region
# ---------------------------------------------------------------------------


def test_minimize_source_spans_merges_overlapping_region() -> None:
    spans = (
        _span(start_line=10, end_line=12),
        _span(start_line=11, end_line=14, start_col=0, end_col=20),
        _span(path="src/other.py", start_line=1, end_line=1),
    )
    minimized = minimize_source_spans(spans)
    assert len(minimized) == 2
    primary = next(item for item in minimized if item.path == "src/mod.py")
    assert primary.start_line == 10
    assert primary.end_line == 14
    other = next(item for item in minimized if item.path == "src/other.py")
    assert other.start_line == 1


def test_minimize_source_spans_merges_adjacent_lines() -> None:
    spans = (
        _span(start_line=10, end_line=11),
        _span(start_line=12, end_line=13, start_col=None, end_col=None),
    )
    minimized = minimize_source_spans(spans)
    assert len(minimized) == 1
    assert minimized[0].start_line == 10
    assert minimized[0].end_line == 13


def test_minimize_source_spans_rejects_empty() -> None:
    with pytest.raises(MinimizationError, match="must not be empty"):
        minimize_source_spans(())


# ---------------------------------------------------------------------------
# build_surviving_mutant_report — acceptance surface
# ---------------------------------------------------------------------------


def test_build_report_contains_required_plan_surface() -> None:
    """Acceptance: smallest region/input, identities, property, detectors,
    behavior delta, spans, dependency path, proof/receipt IDs, command, risk;
    logs remain bounded.
    """

    result = _build()
    report = result.surviving_mutant_report()

    assert result.interface_id == BUILD_SURVIVING_MUTANT_REPORT_INTERFACE
    assert result.logs_bounded is True
    assert result.minimization_status == MinimizationStatus.MINIMIZED.value
    assert result.minimization_failed is False
    assert result.reproduction_input_cid == _cid("repro-input")
    assert result.candidate_id == CANDIDATE_ID
    assert result.candidate_cid == CANDIDATE_CID
    assert result.outcome_cid == OUTCOME_CID
    assert result.risk_class == SurvivorRiskClass.AUTHORIZATION.value
    assert result.detectors_run == ("unit.test_branch",)
    assert result.detectors_omitted == ("static.authz_rule",)
    assert result.smallest_region_span_cids

    # Report surface fields
    assert report.candidate_id == CANDIDATE_ID
    assert report.candidate_cid == CANDIDATE_CID
    assert report.outcome_cid == OUTCOME_CID
    assert report.symbol_ids == ("mod.fn",)
    assert report.violated_or_missing_property == (
        "authorization check must remain present"
    )
    assert report.detectors_run == ("unit.test_branch",)
    assert report.detectors_omitted == ("static.authz_rule",)
    assert report.expected_behavior == "reject unauthorized caller"
    assert report.observed_behavior == "unauthorized caller accepted"
    assert report.source_spans
    assert report.dependency_path == ("authz.check", "mod.fn")  # sorted
    assert report.reproduction_command.startswith("pytest")
    assert report.risk_class == SurvivorRiskClass.AUTHORIZATION.value
    assert report.proof_cids == (_cid("proof-a"),)
    assert report.receipt_cids == (_cid("receipt-a"),)
    assert report.minimized_evidence.minimized is True
    assert report.minimized_evidence.minimization_failed is False
    assert report.minimized_evidence.reproduction_input_cid == _cid("repro-input")
    assert report.minimized_evidence.evidence_cids

    assert report_contains_required_surface(report) is True
    assert logs_remain_bounded(result) is True
    assert logs_remain_bounded(report) is True
    for key in REQUIRED_REPORT_SURFACE_KEYS:
        assert key in report.to_dict()

    assert report.header.artifact_kind == "surviving_mutant_report"
    assert report.header.versions.generator.generator_id == GENERATOR_ID
    assert report.header.versions.generator.generator_version == GENERATOR_VERSION
    assert (
        report.header.versions.generator.interface_id
        == BUILD_SURVIVING_MUTANT_REPORT_INTERFACE
    )
    assert verify_survivor_report_identity(report) == report.report_cid
    verify_survivor_report_build_result_identity(result)


def test_build_collapses_to_smallest_changed_region() -> None:
    subject = _subject(
        source_spans=(
            _span(start_line=10, end_line=12),
            _span(start_line=11, end_line=20, start_col=0, end_col=5),
            _span(start_line=10, end_line=12),  # duplicate region
        )
    )
    result = _build(subject=subject)
    report = result.surviving_mutant_report()
    assert len(report.source_spans) == 1
    assert report.source_spans[0].start_line == 10
    assert report.source_spans[0].end_line == 20
    assert result.metadata["input_span_count"] == 3
    assert result.metadata["minimized_span_count"] == 1
    assert report.metadata["span_reduction"] == 2


def test_build_records_behavior_delta_and_detector_inventory() -> None:
    result = _build(
        subject=_subject(
            detectors_run=("unit.test_branch", "unit.test_authz"),
            detectors_omitted=("static.authz_rule", "formal.obligation"),
            expected_behavior="deny cross-tenant access",
            observed_behavior="allow cross-tenant access",
        )
    )
    report = result.surviving_mutant_report()
    assert report.expected_behavior != report.observed_behavior
    assert "unit.test_authz" in report.detectors_run
    assert "formal.obligation" in report.detectors_omitted
    assert set(report.detectors_run).isdisjoint(report.detectors_omitted)


def test_build_binds_proof_and_receipt_identities() -> None:
    proof_b = _cid("proof-b")
    receipt_b = _cid("receipt-b")
    result = _build(
        subject=_subject(
            proof_cids=(_cid("proof-a"), proof_b),
            receipt_cids=(_cid("receipt-a"), receipt_b),
            equivalence_assessment_cid=_cid("eq-assessment"),
        )
    )
    report = result.surviving_mutant_report()
    assert proof_b in report.proof_cids
    assert receipt_b in report.receipt_cids
    assert report.equivalence_assessment_cid == _cid("eq-assessment")


# ---------------------------------------------------------------------------
# Bounded logs and minimization failure
# ---------------------------------------------------------------------------


def test_logs_remain_bounded_on_success() -> None:
    result = _build()
    payload = result.to_dict()
    assert "full_log" not in payload
    assert "raw_log" not in str(payload).lower() or "full_logs_excluded" in str(payload)
    assert result.surviving_mutant_report().metadata["full_logs_excluded"] is True
    assert result.surviving_mutant_report().metadata["logs_bounded"] is True


def test_minimization_failure_is_explicit_with_bounded_digest() -> None:
    subject = _subject(
        report_id="survivor_failed",
        evidence_cids=(),
        reproduction_input_cid=None,
        minimization_status=MinimizationStatus.FAILED,
        minimization_failure_reason="counterexample minimizer exhausted budget",
        bounded_log_digest=_digest(),
    )
    result = _build(subject=subject)
    report = result.surviving_mutant_report()

    assert result.minimization_failed is True
    assert result.minimization_status == MinimizationStatus.FAILED.value
    assert result.logs_bounded is True
    assert report.minimized_evidence.minimized is False
    assert report.minimized_evidence.minimization_failed is True
    assert _cid("log-digest") in report.minimized_evidence.evidence_cids
    assert "minimization_failed" in (report.minimized_evidence.notes or "")
    assert report.metadata["bounded_log_digest_cid"]
    assert report.metadata["bounded_log_byte_count"] == 4096
    assert logs_remain_bounded(report) is True
    # Full log body never appears on the sealed report.
    assert "counterexample minimizer exhausted budget" in (
        report.minimized_evidence.notes or ""
    )
    dumped = report.to_dict()
    assert "full_log" not in dumped
    assert "raw_traceback" not in dumped


def test_full_log_fields_are_rejected_on_subject_metadata() -> None:
    with pytest.raises(MinimizationError, match="forbidden"):
        _subject(metadata={"full_log": "enormous execution dump"})
    with pytest.raises(MinimizationError, match="forbidden"):
        _subject(metadata={"raw_traceback": "Traceback (most recent call last)..."})
    with pytest.raises(MinimizationError, match="forbidden"):
        _subject(metadata={"nested": {"unbounded_output": "x" * 100}})


def test_bounded_log_digest_rejects_admitting_full_log() -> None:
    with pytest.raises(MinimizationError, match="full_log_excluded"):
        BoundedLogDigest(
            digest_cid=_cid("d"),
            byte_count=10,
            full_log_excluded=False,
        )


def test_success_requires_reproduction_input_and_evidence() -> None:
    with pytest.raises(MinimizationError, match="evidence_cids"):
        _subject(evidence_cids=(), reproduction_input_cid=_cid("i"))
    with pytest.raises(MinimizationError, match="reproduction_input_cid"):
        _subject(reproduction_input_cid=None)


def test_failure_requires_reason_and_bounded_digest() -> None:
    with pytest.raises(MinimizationError, match="minimization_failure_reason"):
        _subject(
            evidence_cids=(),
            reproduction_input_cid=None,
            minimization_status=MinimizationStatus.FAILED,
            minimization_failure_reason=None,
            bounded_log_digest=_digest(),
        )
    with pytest.raises(MinimizationError, match="bounded_log_digest"):
        _subject(
            evidence_cids=(),
            reproduction_input_cid=None,
            minimization_status=MinimizationStatus.FAILED,
            minimization_failure_reason="budget exhausted",
            bounded_log_digest=None,
        )


# ---------------------------------------------------------------------------
# Fail-closed gates
# ---------------------------------------------------------------------------


def test_incomplete_observation_fails_closed() -> None:
    with pytest.raises(MinimizationError, match="observation_complete"):
        _build(subject=_subject(observation_complete=False))


def test_disjoint_detector_inventory_enforced() -> None:
    with pytest.raises(MinimizationError, match="disjoint"):
        _subject(
            detectors_run=("unit.test_branch",),
            detectors_omitted=("unit.test_branch",),
        )


def test_empty_symbols_spans_dependency_fail_closed() -> None:
    with pytest.raises(MinimizationError, match="symbol_ids"):
        _subject(symbol_ids=())
    with pytest.raises(MinimizationError, match="source_spans"):
        _subject(source_spans=())
    with pytest.raises(MinimizationError, match="dependency_path"):
        _subject(dependency_path=())


def test_unknown_risk_class_fails_closed() -> None:
    with pytest.raises(MinimizationError, match="closed set"):
        _subject(risk_class="invented_risk")


def test_private_and_model_authority_rejected() -> None:
    with pytest.raises(Exception):
        _subject(metadata={"api_key": "secret"})
    with pytest.raises(Exception):
        _subject(metadata={"model_authority": "claimed"})
    with pytest.raises(Exception):
        _subject(metadata={"host_path": "/tmp/work"})


# ---------------------------------------------------------------------------
# Identity / round-trip
# ---------------------------------------------------------------------------


def test_subject_and_result_round_trip_identities() -> None:
    subject = _subject()
    restored_subject = SurvivorMinimizationSubject.from_dict(subject.to_dict())
    assert restored_subject.subject_observation_cid == subject.subject_observation_cid

    result = _build(subject=subject)
    restored = SurvivorReportBuildResult.from_dict(result.to_dict())
    assert restored.result_cid == result.result_cid
    assert restored.report_cid == result.report_cid
    report = restored.surviving_mutant_report()
    assert isinstance(report, SurvivingMutantReport)
    assert report.report_cid == result.report_cid


def test_forged_result_cid_fails_closed() -> None:
    result = _build()
    payload = result.to_dict()
    payload["result_cid"] = _cid("forged")
    with pytest.raises(MinimizationError, match="identity mismatch"):
        SurvivorReportBuildResult.from_dict(payload)


def test_mapping_subject_is_accepted() -> None:
    subject = _subject()
    result = build_surviving_mutant_report(subject.to_dict(), _header().to_dict())
    assert result.candidate_id == CANDIDATE_ID
    assert logs_remain_bounded(result)


def test_digest_round_trip() -> None:
    digest = _digest()
    restored = BoundedLogDigest.from_dict(digest.to_dict())
    assert restored.digest_binding_cid == digest.digest_binding_cid
    assert restored.full_log_excluded is True
    assert restored.truncated is True
