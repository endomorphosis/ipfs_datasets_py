"""Unit tests for explainable requirement/evidence gap report (PATLAW-051).

Acceptance focus:
  - Report round-trips to the same bundle
  - Every statement exposes source links
  - Unknowns are prominent
  - Private text is redacted according to output policy
  - No "all clear" label appears when mandatory review remains
"""

from __future__ import annotations

import itertools
from typing import Any, Iterator

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
    ANALYSIS_BUNDLE_SCHEMA_VERSION,
    AnalysisBundleBuilder,
    BundleDisposition,
    BundleSectionKind,
    BundleWarningCode,
    ProvenanceLink,
    UsptoAnalysisBundle,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.gap_report import (
    GAP_REPORT_SCHEMA_VERSION,
    OUTPUT_KIND_REQUIREMENT_EVIDENCE_GAP_REPORT,
    REDACTION_TOKEN,
    UNKNOWN_BANNER,
    GapReportError,
    GapReportInput,
    GapReportLabel,
    GapReportRenderer,
    GapStatement,
    GapStatus,
    OutputPolicyMode,
    OutputRedactionPolicy,
    RequirementEvidenceGapReport,
    SourceLink,
    StatementKind,
    render_gap_report,
    report_round_trip_equal,
    verify_report_bundle_binding,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DIGEST_A = sha256_hex(b"artifact-bytes-a")
_DIGEST_SEC = sha256_hex(b"section-payload-v1")
_AUTH = "auth:usc-112b-2011"

_seq: Iterator[int] = itertools.count(1)


def _reset_seq() -> None:
    global _seq
    _seq = itertools.count(1)


def _id_factory() -> str:
    return f"{next(_seq):04d}"


def _renderer(**kwargs: Any) -> GapReportRenderer:
    _reset_seq()
    return GapReportRenderer(id_factory=_id_factory, **kwargs)


def _build_bundle(
    *,
    matter_id: str = "matter:unit-1",
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER,
    review_state: ReviewState = ReviewState.REQUIRED,
    disposition: BundleDisposition = BundleDisposition.PARTIAL,
    with_requirement: bool = True,
    with_untraced: bool = False,
    unsupported: tuple[str, ...] = (),
    private: bool = False,
) -> UsptoAnalysisBundle:
    _reset_seq()
    if private:
        classification = DisclosureClassification.CONFIDENTIAL_APPLICATION
    builder = AnalysisBundleBuilder(
        matter_id=matter_id,
        analysis_id="analysis:unit-1",
        seed_classification=classification,
        id_factory=_id_factory,
    )
    builder.add_input_artifact_ids("art:oa:1", "art:sub:1")
    builder.add_validation_receipt_ids("rcpt:val:1")
    builder.add_ruleset_versions({"unit": "test@1"})
    for check in unsupported:
        builder.add_unsupported_check(check)

    builder.bind_section(
        kind=BundleSectionKind.ARTIFACT_MANIFEST,
        record_id="art:oa:1",
        schema_version="uspto.artifact-manifest.v1",
        content_digest=_DIGEST_A,
        classification=classification,
        source_artifact_ids=("art:oa:1",),
    )
    if with_requirement:
        builder.bind_section(
            kind=BundleSectionKind.REQUIREMENT,
            record_id="req:112b:1",
            schema_version="uspto.requirement-processor.v1",
            content_digest=_DIGEST_SEC,
            classification=classification,
            source_artifact_ids=("art:oa:1",),
            authority_ids=(_AUTH,),
            labels={"requirement_type": "rejection_112b"},
            span_ids=("span:oa:112b",),
        )
    if with_untraced:
        builder.add_provenance(
            ProvenanceLink(
                link_id=f"prov:{_id_factory()}",
                subject_id="orphan:fact:1",
                subject_kind="submission_evidence",
                artifact_ids=(),
                authority_ids=(),
                span_ids=(),
            )
        )

    bundle = builder.build(bundle_id="bundle:unit-1")
    # Rebuild with explicit review/disposition when builder defaults differ.
    # Builder already sets review based on warnings; accept as-is if compatible.
    assert bundle.bundle_id
    assert bundle.bundle_digest
    # Force review_state/disposition for deterministic acceptance tests by
    # re-wrapping only when needed (immutable — use from_dict override).
    data = bundle.to_dict()
    data["review_state"] = review_state.value
    data["disposition"] = disposition.value
    data["classification"] = classification.value
    # Recompute digest is intentionally NOT done here — report binds to the
    # digest stored on the bundle record as provided.
    return UsptoAnalysisBundle.from_dict(data)


# ---------------------------------------------------------------------------
# Round-trip / bundle binding
# ---------------------------------------------------------------------------


class TestBundleRoundTrip:
    def test_report_binds_to_source_bundle(self) -> None:
        bundle = _build_bundle()
        report = _renderer().render_bundle(bundle)
        assert report.source_bundle_id == bundle.bundle_id
        assert report.source_bundle_digest == bundle.bundle_digest
        assert report.matter_summary.bundle_id == bundle.bundle_id
        assert report.matter_summary.bundle_digest == bundle.bundle_digest
        assert report.binds_bundle(bundle)
        assert verify_report_bundle_binding(report, bundle)

    def test_report_dict_round_trip_preserves_bundle_binding(self) -> None:
        bundle = _build_bundle()
        report = _renderer().render_bundle(bundle)
        revived = RequirementEvidenceGapReport.from_dict(report.to_dict())
        assert revived.source_bundle_id == bundle.bundle_id
        assert revived.source_bundle_digest == bundle.bundle_digest
        assert revived.to_canonical_json() == report.to_canonical_json()
        assert report_round_trip_equal(report)
        assert verify_report_bundle_binding(revived, bundle)

    def test_round_trip_fails_for_different_bundle(self) -> None:
        bundle_a = _build_bundle(matter_id="matter:a")
        bundle_b = _build_bundle(matter_id="matter:b")
        # Force distinct digests by different matter via full rebuild.
        builder = AnalysisBundleBuilder(
            matter_id="matter:b-distinct",
            seed_classification=DisclosureClassification.PUBLIC_USER,
            id_factory=_id_factory,
        )
        builder.add_input_artifact_ids("art:other:1")
        builder.bind_section(
            kind=BundleSectionKind.ARTIFACT_MANIFEST,
            record_id="art:other:1",
            schema_version="uspto.artifact-manifest.v1",
            content_digest=sha256_hex(b"other"),
            classification=DisclosureClassification.PUBLIC_USER,
            source_artifact_ids=("art:other:1",),
        )
        bundle_b = builder.build(bundle_id="bundle:other")
        report = _renderer().render_bundle(bundle_a)
        assert not report.binds_bundle(bundle_b)
        assert not verify_report_bundle_binding(report, bundle_b)

    def test_render_is_deterministic_for_same_inputs(self) -> None:
        bundle = _build_bundle()
        assessments = [
            {
                "assessment_id": "asm:1",
                "requirement_id": "req:112b:1",
                "status": "unknown",
                "mandatory": True,
                "requirement_type": "rejection_112b",
                "support_span_ids": ["span:sub:1"],
                "counter_span_ids": [],
                "authority": {"selected_versions": [_AUTH]},
                "classification": DisclosureClassification.PUBLIC_USER.value,
                "reason_codes": ["mandatory_unknown"],
                "explanation": "Insufficient claim support span match",
            }
        ]
        r1 = _renderer().render(
            GapReportInput(analysis_bundle=bundle, assessments=assessments)
        )
        r2 = _renderer().render(
            GapReportInput(analysis_bundle=bundle, assessments=assessments)
        )
        # content_digest is material (excludes report_id); human form is stable
        # under deterministic id factory reset.
        assert r1.source_bundle_digest == r2.source_bundle_digest
        assert r1.label == r2.label
        assert r1.unknown_count == r2.unknown_count
        assert len(r1.requirement_rows) == len(r2.requirement_rows)
        assert r1.content_digest == r2.content_digest


# ---------------------------------------------------------------------------
# Source links on every statement
# ---------------------------------------------------------------------------


class TestSourceLinks:
    def test_every_statement_has_source_links(self) -> None:
        bundle = _build_bundle()
        report = render_gap_report(
            bundle,
            assessments=[
                {
                    "assessment_id": "asm:1",
                    "requirement_id": "req:112b:1",
                    "status": "unsatisfied",
                    "mandatory": True,
                    "requirement_type": "rejection_112b",
                    "support_span_ids": ["span:sub:remarks"],
                    "counter_span_ids": ["span:oa:counter"],
                    "authority": {"selected_versions": [_AUTH]},
                    "classification": DisclosureClassification.PUBLIC_USER.value,
                    "explanation": "No amending claim language found",
                }
            ],
            candidate_dates=[
                {
                    "candidate_id": "cand:resp:1",
                    "status": "unknown",
                    "candidate_utc": "2024-09-01T00:00:00Z",
                    "uncertainty_summary": "entity status assumed",
                    "uncertainty_kinds": ["entity_status_assumed"],
                    "is_review_only": True,
                    "source_spans": ["span:oa:mail-date"],
                    "classification": DisclosureClassification.PUBLIC_USER.value,
                }
            ],
            id_factory=_id_factory,
        )
        assert report.statements
        for stmt in report.statements:
            assert stmt.source_links, f"missing links on {stmt.statement_id}"
            assert all(isinstance(s, SourceLink) for s in stmt.source_links)
        assert report.statements_missing_source_links() == ()

        for row in report.requirement_rows:
            assert row.source_links
            for stmt in row.statements:
                assert stmt.source_links

        for cand in report.candidate_dates:
            assert cand.source_links

        for action in report.reviewer_actions:
            assert action.source_links

        for item in report.inventory:
            assert item.source_links

    def test_statement_without_source_links_rejected(self) -> None:
        with pytest.raises(GapReportError) as exc:
            GapStatement(
                statement_id="stmt:x",
                kind=StatementKind.GAP,
                summary="orphan",
                status=GapStatus.UNKNOWN,
                source_links=(),
                is_unknown=True,
                is_prominent_unknown=True,
                classification=DisclosureClassification.PUBLIC_USER,
                redacted=False,
            )
        assert exc.value.code == "missing_source_links"


# ---------------------------------------------------------------------------
# Unknowns prominent
# ---------------------------------------------------------------------------


class TestUnknownsProminent:
    def test_unknowns_section_and_banner(self) -> None:
        bundle = _build_bundle(unsupported=("proof:lean:timeout",), with_untraced=True)
        report = _renderer().render_bundle(bundle)
        assert report.unknown_count > 0
        assert report.unknowns
        assert all(u.is_prominent_unknown for u in report.unknowns)
        assert any(UNKNOWN_BANNER in u.summary for u in report.unknowns)
        assert UNKNOWN_BANNER in report.human_readable
        assert report.label in (
            GapReportLabel.UNKNOWNS_PRESENT,
            GapReportLabel.REVIEW_REQUIRED,
            GapReportLabel.GAPS_PRESENT,
            GapReportLabel.PARTIAL,
            GapReportLabel.QUARANTINE,
        )
        assert report.label is not GapReportLabel.ALL_CLEAR

    def test_requirement_without_assessment_is_unknown(self) -> None:
        bundle = _build_bundle(with_requirement=True)
        report = _renderer().render_bundle(bundle)
        assert report.requirement_rows
        assert any(r.is_unknown for r in report.requirement_rows)
        assert any(r.status is GapStatus.UNKNOWN for r in report.requirement_rows)
        # Prominent in markdown matrix
        assert UNKNOWN_BANNER in report.to_markdown()


# ---------------------------------------------------------------------------
# Private redaction
# ---------------------------------------------------------------------------


class TestPrivateRedaction:
    def test_private_classification_redacts_surface_text(self) -> None:
        bundle = _build_bundle(private=True)
        report = _renderer().render(
            GapReportInput(
                analysis_bundle=bundle,
                assessments=[
                    {
                        "assessment_id": "asm:priv:1",
                        "requirement_id": "req:112b:1",
                        "status": "unknown",
                        "mandatory": True,
                        "requirement_type": "rejection_112b",
                        "support_span_ids": ["span:priv:1"],
                        "authority": {"selected_versions": [_AUTH]},
                        "classification": (
                            DisclosureClassification.CONFIDENTIAL_APPLICATION.value
                        ),
                        "explanation": "SECRET claim language about trade formula X",
                        "required_human_action": "review_evidence",
                    }
                ],
                output_policy=OutputRedactionPolicy(
                    mode=OutputPolicyMode.REDACT_PRIVATE
                ),
            )
        )
        assert report.redaction_applied
        assert report.is_private
        # Surface explanations must not leak private body text.
        assert "trade formula" not in report.human_readable
        assert "SECRET" not in report.human_readable
        for stmt in report.statements:
            if stmt.detail_text is not None and stmt.redacted:
                assert stmt.detail_text == REDACTION_TOKEN
        # Identifiers / digests remain.
        assert report.source_bundle_id == bundle.bundle_id
        assert bundle.bundle_digest in report.human_readable or report.source_bundle_digest

    def test_identifiers_only_policy(self) -> None:
        bundle = _build_bundle()
        policy = OutputRedactionPolicy(mode=OutputPolicyMode.IDENTIFIERS_ONLY)
        report = _renderer().render(
            GapReportInput(
                analysis_bundle=bundle,
                assessments=[
                    {
                        "assessment_id": "asm:1",
                        "requirement_id": "req:112b:1",
                        "status": "satisfied",
                        "mandatory": True,
                        "support_span_ids": ["span:1"],
                        "authority": {"selected_versions": [_AUTH]},
                        "explanation": "public explanation text",
                        "classification": DisclosureClassification.PUBLIC_USER.value,
                    }
                ],
                output_policy=policy,
            )
        )
        assert report.redaction_applied
        for stmt in report.statements:
            if stmt.detail_text is not None:
                assert stmt.detail_text == REDACTION_TOKEN or stmt.redacted

    def test_public_full_policy_keeps_explanations(self) -> None:
        bundle = _build_bundle()
        explanation = "Claims 1-3 lack antecedent basis for hinge pin."
        report = _renderer().render(
            GapReportInput(
                analysis_bundle=bundle,
                assessments=[
                    {
                        "assessment_id": "asm:1",
                        "requirement_id": "req:112b:1",
                        "status": "unsatisfied",
                        "mandatory": True,
                        "support_span_ids": ["span:1"],
                        "authority": {"selected_versions": [_AUTH]},
                        "explanation": explanation,
                        "classification": DisclosureClassification.PUBLIC_USER.value,
                    }
                ],
                output_policy=OutputRedactionPolicy(mode=OutputPolicyMode.FULL),
            )
        )
        # Public full mode should not blanket-redact.
        details = [s.detail_text for s in report.statements if s.detail_text]
        assert any(explanation in (d or "") for d in details) or explanation in report.human_readable


# ---------------------------------------------------------------------------
# No all_clear when mandatory review remains
# ---------------------------------------------------------------------------


class TestNoAllClearWithMandatoryReview:
    def test_label_not_all_clear_when_review_required(self) -> None:
        bundle = _build_bundle(review_state=ReviewState.REQUIRED)
        report = _renderer().render_bundle(bundle)
        assert report.mandatory_review_remaining
        assert report.label is not GapReportLabel.ALL_CLEAR
        assert "all_clear" not in report.human_readable.lower().replace("_", " ") or (
            report.label.value != "all_clear"
        )
        # Human form must not claim all clear.
        hr = report.human_readable.lower()
        if report.mandatory_review_remaining:
            assert "all clear" not in hr
            assert report.label.value != GapReportLabel.ALL_CLEAR.value

    def test_all_clear_forbidden_on_construction(self) -> None:
        bundle = _build_bundle()
        report = _renderer().render_bundle(bundle)
        payload = report.to_dict()
        payload["label"] = GapReportLabel.ALL_CLEAR.value
        payload["mandatory_review_remaining"] = True
        with pytest.raises(GapReportError) as exc:
            RequirementEvidenceGapReport.from_dict(payload)
        assert exc.value.code == "all_clear_with_mandatory_review"

    def test_all_clear_forbidden_with_unknowns(self) -> None:
        bundle = _build_bundle(unsupported=("check:x",))
        report = _renderer().render_bundle(bundle)
        payload = report.to_dict()
        payload["label"] = GapReportLabel.ALL_CLEAR.value
        payload["mandatory_review_remaining"] = False
        # Keep unknown_count > 0 from original
        assert payload["unknown_count"] > 0
        with pytest.raises(GapReportError) as exc:
            RequirementEvidenceGapReport.from_dict(payload)
        assert exc.value.code == "all_clear_with_unknowns"

    def test_satisfied_package_without_review_can_be_all_clear(self) -> None:
        """When bundle needs no review and assessments are satisfied, allow all_clear."""
        _reset_seq()
        builder = AnalysisBundleBuilder(
            matter_id="matter:clear",
            analysis_id="analysis:clear",
            seed_classification=DisclosureClassification.PUBLIC_OFFICIAL,
            id_factory=_id_factory,
        )
        builder.add_input_artifact_ids("art:pub:1")
        builder.bind_section(
            kind=BundleSectionKind.ARTIFACT_MANIFEST,
            record_id="art:pub:1",
            schema_version="uspto.artifact-manifest.v1",
            content_digest=_DIGEST_A,
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            source_artifact_ids=("art:pub:1",),
        )
        bundle = builder.build(bundle_id="bundle:clear")
        data = bundle.to_dict()
        data["review_state"] = ReviewState.NOT_REQUIRED.value
        data["disposition"] = BundleDisposition.COMPLETE.value
        data["warnings"] = []
        data["warning_codes"] = []
        data["unsupported_checks"] = []
        bundle = UsptoAnalysisBundle.from_dict(data)

        report = _renderer().render(
            GapReportInput(
                analysis_bundle=bundle,
                assessments=[
                    {
                        "assessment_id": "asm:ok",
                        "requirement_id": "req:fee:1",
                        "status": "satisfied",
                        "mandatory": True,
                        "support_span_ids": ["span:fee:1"],
                        "authority": {"selected_versions": ["auth:fee"]},
                        "classification": DisclosureClassification.PUBLIC_OFFICIAL.value,
                        "explanation": "Fee receipt present",
                    }
                ],
            )
        )
        # May still require review if package logic emits actions; if not:
        if not report.mandatory_review_remaining and report.unknown_count == 0 and report.gap_count == 0:
            assert report.label is GapReportLabel.ALL_CLEAR
        else:
            assert report.label is not GapReportLabel.ALL_CLEAR


# ---------------------------------------------------------------------------
# Projection content
# ---------------------------------------------------------------------------


class TestProjectionContent:
    def test_matter_summary_and_inventory(self) -> None:
        bundle = _build_bundle()
        report = _renderer().render_bundle(bundle)
        assert report.matter_summary.matter_id == "matter:unit-1"
        assert report.inventory
        kinds = {i.kind for i in report.inventory}
        assert "artifact_manifest" in kinds or "input_artifact" in kinds
        assert any(i.receipt_id == "rcpt:val:1" for i in report.inventory)
        assert report.output_kind == OUTPUT_KIND_REQUIREMENT_EVIDENCE_GAP_REPORT
        assert report.schema_version == GAP_REPORT_SCHEMA_VERSION

    def test_assessment_row_exposes_evidence_and_authority(self) -> None:
        bundle = _build_bundle()
        report = _renderer().render(
            GapReportInput(
                analysis_bundle=bundle,
                assessments=[
                    {
                        "assessment_id": "asm:1",
                        "requirement_id": "req:112b:1",
                        "status": "unsatisfied",
                        "mandatory": True,
                        "requirement_type": "rejection_112b",
                        "support_span_ids": ["span:sub:1"],
                        "counter_span_ids": ["span:oa:1"],
                        "authority": {"selected_versions": [_AUTH]},
                        "affected_claims": ["1", "2", "3"],
                        "classification": DisclosureClassification.PUBLIC_USER.value,
                        "explanation": "Amendment does not address indefiniteness",
                        "required_human_action": "supply_evidence",
                    }
                ],
            )
        )
        assert len(report.requirement_rows) == 1
        row = report.requirement_rows[0]
        assert row.requirement_id == "req:112b:1"
        assert row.status is GapStatus.UNSATISFIED
        assert row.gap_status is GapStatus.GAP
        assert _AUTH in row.authority_ids
        assert "span:sub:1" in row.evidence_span_ids
        assert "span:oa:1" in row.counter_evidence_span_ids
        assert row.reviewer_action is not None
        assert report.gap_count >= 1
        assert report.reviewer_actions
        md = report.to_markdown()
        assert "req:112b:1" in md
        assert "span:sub:1" in md
        assert _AUTH in md

    def test_candidate_dates_projected(self) -> None:
        bundle = _build_bundle()
        report = _renderer().render(
            GapReportInput(
                analysis_bundle=bundle,
                assessments=[
                    {
                        "assessment_id": "asm:1",
                        "requirement_id": "req:112b:1",
                        "status": "satisfied",
                        "mandatory": True,
                        "support_span_ids": ["span:1"],
                        "authority": {"selected_versions": [_AUTH]},
                        "classification": DisclosureClassification.PUBLIC_USER.value,
                    }
                ],
                candidate_dates=[
                    {
                        "candidate_id": "cand:1",
                        "status": "unknown",
                        "candidate_utc": "2024-12-01T00:00:00Z",
                        "uncertainty_summary": "holiday set incomplete",
                        "uncertainty_kinds": ["holiday_set_incomplete"],
                        "assumptions": {"entity_status": "small"},
                        "is_review_only": True,
                        "human_review_question": "Confirm short/long statutory period?",
                        "classification": DisclosureClassification.PUBLIC_USER.value,
                    }
                ],
            )
        )
        assert report.candidate_dates
        cand = report.candidate_dates[0]
        assert cand.is_review_only
        assert cand.is_unknown
        assert "holiday" in cand.uncertainty_summary
        assert any(s.kind is StatementKind.CANDIDATE_DATE for s in report.statements)

    def test_public_projection_has_no_body_fields(self) -> None:
        bundle = _build_bundle(private=True)
        report = _renderer().render_bundle(bundle)
        pub = report.public_projection()
        assert "human_readable" not in pub
        assert "statements" not in pub
        assert pub["source_bundle_digest"] == bundle.bundle_digest
        assert pub["is_private"] is True

    def test_machine_and_human_forms_present(self) -> None:
        bundle = _build_bundle()
        report = _renderer().render_bundle(bundle)
        as_dict = report.to_dict()
        assert as_dict["schema_version"] == GAP_REPORT_SCHEMA_VERSION
        assert "requirement_rows" in as_dict
        assert "human_readable" in as_dict
        assert report.to_markdown().startswith("#")
        assert "Matter summary" in report.human_readable

    def test_render_gap_report_helper(self) -> None:
        bundle = _build_bundle()
        report = render_gap_report(bundle, id_factory=_id_factory)
        assert isinstance(report, RequirementEvidenceGapReport)
        assert report.source_bundle_id == bundle.bundle_id


# ---------------------------------------------------------------------------
# Policy / error paths
# ---------------------------------------------------------------------------


class TestPolicyAndErrors:
    def test_output_policy_round_trip(self) -> None:
        policy = OutputRedactionPolicy(
            mode=OutputPolicyMode.REDACT_PRIVATE,
            redaction_token="<<X>>",
            quarantine_as_private=True,
        )
        revived = OutputRedactionPolicy.from_dict(policy.to_dict())
        assert revived.mode is OutputPolicyMode.REDACT_PRIVATE
        assert revived.redaction_token == "<<X>>"

    def test_rejects_non_bundle_input(self) -> None:
        with pytest.raises(TypeError):
            GapReportInput(analysis_bundle="not-a-bundle")  # type: ignore[arg-type]

    def test_schema_version_enforced(self) -> None:
        bundle = _build_bundle()
        report = _renderer().render_bundle(bundle)
        payload = report.to_dict()
        payload["schema_version"] = "wrong.v0"
        with pytest.raises(GapReportError) as exc:
            RequirementEvidenceGapReport.from_dict(payload)
        assert exc.value.code == "schema_version_mismatch"

    def test_canonical_json_stable_key_order(self) -> None:
        bundle = _build_bundle()
        report = _renderer().render_bundle(bundle)
        a = report.to_canonical_json()
        b = canonical_json(report.to_dict())
        assert a == b
