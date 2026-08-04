"""Unit tests for prior-art / current-rule filing preflight checklist (PATLAW-095)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.domains.patent.prior_art import (
    PRIOR_ART_SCHEMA_VERSION,
    ClaimChartEntry,
    PriorArtReport,
    build_claim_chart,
    build_prior_art_search_plan,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    SourceLink,
    SourceSpan,
)
from ipfs_datasets_py.processors.domains.patent.rules import (
    RULES_DISCLAIMER,
    RULES_SCHEMA_VERSION,
    AdviceContentError,
    AuthorityLabel,
    AuthorityViewKind,
    ChecklistCitationError,
    ChecklistItemKind,
    ChecklistStatus,
    CurrentRuleSourceInput,
    HardCodedLatestError,
    HumanCoverageAcknowledgment,
    PriorArtRuleChecklist,
    PriorArtSearchCompleteError,
    REASON_CONFLICTING_SOURCES,
    REASON_MISSING_HUMAN_COVERAGE_ACK,
    REASON_MISSING_PRIOR_ART_REPORT,
    REASON_MISSING_SOURCE,
    REASON_STALE_SOURCE,
    ReadinessBlockError,
    ReadinessDisposition,
    RuleChecklistItem,
    SourceCitation,
    SourceHealth,
    assert_checklist_items_cite_sources,
    assert_no_advice_content,
    assert_prior_art_search_complete_allowed,
    build_human_coverage_acknowledgment,
    build_prior_art_rule_checklist,
    build_rule_checklist_item_from_source,
    canonical_json,
    compute_readiness,
    content_digest,
    evaluate_source_health,
    prior_art_search_complete_allowed,
    project_filing_preflight_readiness,
)

CID_A = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CID_B = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"
CID_REPORT = "bafybeipriorartreportfixture000000000001"

AS_OF = "2024-06-15T12:00:00Z"
FILING = "2022-03-15"
PRIORITY = "2021-03-15"
SEARCH = "2024-06-01T12:00:00Z"

CLAIM_TEXT = (
    "1. A method comprising encoding claim text for retrieval; "
    "wherein the system indexes CPC G06F16/00 documents."
)


def _span(start: int = 0, end: int = 40) -> SourceSpan:
    return SourceSpan(start=start, end=end, unit="char")


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert restored == record


def _official_source(
    *,
    source_id: str = "src:usc-112b",
    cid: str = CID_A,
    version: str = "aia-2011",
    health: SourceHealth = SourceHealth.OK,
    label: AuthorityLabel = AuthorityLabel.OFFICIAL,
    effective_start: str | None = "2011-09-16",
    effective_end: str | None = None,
    retrieved_at_utc: str | None = "2024-06-10T00:00:00Z",
    conflict_group: str | None = None,
    title: str | None = "35 U.S.C. § 112(b)",
) -> CurrentRuleSourceInput:
    return CurrentRuleSourceInput(
        source_id=source_id,
        source_cid=cid,
        artifact_id=f"artifact:{source_id}",
        span=_span(),
        version=version,
        authority_label=label,
        as_of_utc=AS_OF,
        authority_view=AuthorityViewKind.OFFICIAL,
        authority_tier="official-base",
        effective_start=effective_start,
        effective_end=effective_end,
        retrieved_at_utc=retrieved_at_utc,
        citation_key="35-usc-112(b)",
        title=title,
        health=health,
        conflict_group=conflict_group,
    )


def _sample_report() -> PriorArtReport:
    plan = build_prior_art_search_plan(
        subject_id="subject:app-16-123456",
        filing_date=FILING,
        priority_date=PRIORITY,
        search_date_utc=SEARCH,
        claims=(
            {
                "claim_number": 1,
                "claim_text": CLAIM_TEXT,
                "claim_kind": "independent",
            },
        ),
        classifications=("G06F16/00",),
    )
    lim = plan.limitations[0]
    entry = ClaimChartEntry(
        entry_id="entry:1",
        claim_number=1,
        limitation_id=lim.limitation_id,
        document_id="doc:patent-encode",
        rank=1,
        score=9.0,
        source_links=(
            SourceLink(
                source_cid=CID_A,
                artifact_id="artifact:patent-encode",
                span=_span(0, 80),
            ),
        ),
    )
    chart = build_claim_chart(
        subject_id=plan.subject_id,
        filing_date=FILING,
        priority_date=PRIORITY,
        search_date_utc=SEARCH,
        entries=(entry,),
        limitations=plan.limitations,
        plan_id=plan.plan_id,
    )
    return PriorArtReport(
        schema_version=PRIOR_ART_SCHEMA_VERSION,
        report_id="report:prior-art-unit-1",
        plan=plan,
        query_logs=(),
        chart=chart,
        coverage_gaps=plan.coverage_gaps,
    )


# ---------------------------------------------------------------------------
# Schema / disclaimer
# ---------------------------------------------------------------------------


def test_schema_version_and_disclaimer() -> None:
    assert RULES_SCHEMA_VERSION == "patent.rules.v1"
    lower = RULES_DISCLAIMER.lower()
    assert "decision support" in lower or "decision-support" in lower
    assert "not legal advice" in lower
    assert "prior-art" in lower or "prior art" in lower


# ---------------------------------------------------------------------------
# Citations: source / span / version / time
# ---------------------------------------------------------------------------


def test_source_citation_requires_source_span_version_time() -> None:
    citation = SourceCitation(
        source_cid=CID_A,
        artifact_id="artifact:usc-112b",
        span=_span(),
        version="aia-2011",
        as_of_utc=AS_OF,
        effective_start="2011-09-16",
        authority_label=AuthorityLabel.OFFICIAL,
    )
    assert citation.source_cid == CID_A
    assert citation.span is not None
    assert citation.version == "aia-2011"
    assert citation.as_of_utc == AS_OF
    _assert_round_trip(citation)


def test_source_citation_rejects_hard_coded_latest() -> None:
    with pytest.raises(HardCodedLatestError):
        SourceCitation(
            source_cid=CID_A,
            artifact_id="artifact:x",
            span=_span(),
            version="latest",
            as_of_utc=AS_OF,
        )


def test_checklist_item_requires_citations() -> None:
    with pytest.raises(ChecklistCitationError):
        RuleChecklistItem(
            item_id="item:bare",
            kind=ChecklistItemKind.OFFICIAL_AUTHORITY,
            status=ChecklistStatus.PASS,
            authority_label=AuthorityLabel.OFFICIAL,
            title="Bare item",
            summary="No citations provided.",
            citations=(),
        )


def test_checklist_item_round_trip() -> None:
    citation = SourceCitation(
        source_cid=CID_A,
        artifact_id="artifact:x",
        span=_span(),
        version="2024-ed",
        as_of_utc=AS_OF,
        retrieved_at_utc="2024-06-01T00:00:00Z",
    )
    item = RuleChecklistItem(
        item_id="item:ok",
        kind=ChecklistItemKind.OFFICIAL_AUTHORITY,
        status=ChecklistStatus.PASS,
        authority_label=AuthorityLabel.OFFICIAL,
        title="Official base rule",
        summary="Source is present, current, and non-conflicting.",
        citations=(citation,),
        blocks_readiness=False,
        source_health=SourceHealth.OK,
    )
    _assert_round_trip(item)


# ---------------------------------------------------------------------------
# Forms / fees / guidance separately labelled
# ---------------------------------------------------------------------------


def test_forms_fees_guidance_separately_labelled() -> None:
    forms = build_rule_checklist_item_from_source(
        _official_source(
            source_id="src:form-sb08",
            label=AuthorityLabel.FORMS,
            version="form-sb08-2023-07",
            title="SB/08 form",
        ),
        as_of_utc=AS_OF,
    )
    fees = build_rule_checklist_item_from_source(
        _official_source(
            source_id="src:fee-schedule",
            label=AuthorityLabel.FEES,
            version="fee-schedule-2024-01",
            title="Fee schedule",
        ),
        as_of_utc=AS_OF,
    )
    guidance = build_rule_checklist_item_from_source(
        _official_source(
            source_id="src:mpep-2100",
            label=AuthorityLabel.GUIDANCE,
            version="mpep-e9r10-2024",
            title="MPEP 2100",
            health=SourceHealth.OK,
        ),
        as_of_utc=AS_OF,
    )
    assert forms.authority_label is AuthorityLabel.FORMS
    assert forms.kind is ChecklistItemKind.FORMS
    assert fees.authority_label is AuthorityLabel.FEES
    assert fees.kind is ChecklistItemKind.FEES
    assert guidance.authority_label is AuthorityLabel.GUIDANCE
    assert guidance.kind is ChecklistItemKind.GUIDANCE
    assert forms.status is ChecklistStatus.PASS
    assert fees.status is ChecklistStatus.PASS
    assert guidance.status is ChecklistStatus.PASS


# ---------------------------------------------------------------------------
# Source health → readiness blockers
# ---------------------------------------------------------------------------


def test_missing_source_blocks_readiness() -> None:
    src = _official_source(source_id="src:missing", health=SourceHealth.MISSING)
    assert evaluate_source_health(src, as_of_utc=AS_OF) is SourceHealth.MISSING
    item = build_rule_checklist_item_from_source(src, as_of_utc=AS_OF)
    assert item.status is ChecklistStatus.FAIL
    assert item.blocks_readiness is True
    assert REASON_MISSING_SOURCE in item.reason_codes
    readiness, codes = compute_readiness((item,))
    assert readiness is ReadinessDisposition.NOT_READY
    assert REASON_MISSING_SOURCE in codes


def test_stale_source_blocks_readiness() -> None:
    # Retrieval far older than as-of → stale.
    src = _official_source(
        source_id="src:stale",
        retrieved_at_utc="2020-01-01T00:00:00Z",
        health=SourceHealth.OK,
    )
    health = evaluate_source_health(src, as_of_utc=AS_OF, stale_max_age_seconds=7 * 86400)
    assert health is SourceHealth.STALE
    item = build_rule_checklist_item_from_source(
        src, as_of_utc=AS_OF, stale_max_age_seconds=7 * 86400
    )
    assert item.source_health is SourceHealth.STALE
    assert item.blocks_readiness is True
    assert REASON_STALE_SOURCE in item.reason_codes


def test_stale_by_effective_end_blocks() -> None:
    src = _official_source(
        source_id="src:expired",
        effective_start="2010-01-01",
        effective_end="2020-12-31",
        retrieved_at_utc="2024-06-01T00:00:00Z",
    )
    health = evaluate_source_health(src, as_of_utc=AS_OF)
    assert health is SourceHealth.STALE


def test_conflicting_sources_block_readiness() -> None:
    a = _official_source(
        source_id="src:a",
        cid=CID_A,
        version="v1",
        conflict_group="usc-112b",
    )
    b = _official_source(
        source_id="src:b",
        cid=CID_B,
        version="v2",
        conflict_group="usc-112b",
    )
    members = [f"{a.source_cid}|{a.version}", f"{b.source_cid}|{b.version}"]
    item_a = build_rule_checklist_item_from_source(
        a, as_of_utc=AS_OF, conflict_members=members
    )
    item_b = build_rule_checklist_item_from_source(
        b, as_of_utc=AS_OF, conflict_members=members
    )
    assert item_a.source_health is SourceHealth.CONFLICT
    assert item_b.source_health is SourceHealth.CONFLICT
    assert item_a.blocks_readiness and item_b.blocks_readiness
    readiness, codes = compute_readiness((item_a, item_b))
    assert readiness is ReadinessDisposition.NOT_READY
    assert REASON_CONFLICTING_SOURCES in codes


def test_ready_checklist_rejects_blocking_items() -> None:
    citation = SourceCitation(
        source_cid=CID_A,
        artifact_id="artifact:x",
        span=_span(),
        version="v1",
        as_of_utc=AS_OF,
    )
    bad_item = RuleChecklistItem(
        item_id="item:missing",
        kind=ChecklistItemKind.SOURCE_PRESENCE,
        status=ChecklistStatus.FAIL,
        authority_label=AuthorityLabel.OFFICIAL,
        title="Missing",
        summary="Source missing.",
        citations=(citation,),
        blocks_readiness=True,
        reason_codes=(REASON_MISSING_SOURCE,),
        source_health=SourceHealth.MISSING,
    )
    with pytest.raises(ReadinessBlockError):
        PriorArtRuleChecklist(
            schema_version=RULES_SCHEMA_VERSION,
            checklist_id="checklist:bad-ready",
            subject_id="subject:x",
            as_of_utc=AS_OF,
            authority_view=AuthorityViewKind.OFFICIAL,
            items=(bad_item,),
            readiness=ReadinessDisposition.READY,
            prior_art_search_complete=False,
            blocking_reason_codes=(),
        )


# ---------------------------------------------------------------------------
# Prior-art search complete gate
# ---------------------------------------------------------------------------


def test_cannot_claim_search_complete_without_dated_report() -> None:
    with pytest.raises(PriorArtSearchCompleteError):
        assert_prior_art_search_complete_allowed(
            report=None,
            report_digest=None,
            human_ack=None,
        )
    assert prior_art_search_complete_allowed(
        report=None, report_digest=None, human_ack=None
    ) is False


def test_cannot_claim_search_complete_without_human_ack() -> None:
    report = _sample_report()
    digest = content_digest(report.to_dict())
    with pytest.raises(PriorArtSearchCompleteError, match="human coverage"):
        assert_prior_art_search_complete_allowed(
            report=report,
            report_digest=digest,
            human_ack=None,
        )


def test_human_ack_must_match_report_digest() -> None:
    report = _sample_report()
    digest = content_digest(report.to_dict())
    ack = HumanCoverageAcknowledgment(
        acknowledger_name="Alex Examiner-Reviewer",
        acknowledged_at_utc="2024-06-14T18:00:00Z",
        report_id=report.report_id,
        report_digest="0" * 64,  # wrong digest
        coverage_scope_text="US patents and publications only; NPL/foreign gaps visible.",
        acknowledges_gaps_visible=True,
        statement=(
            "I reviewed search scope for decision support only, not legal advice. "
            "Coverage gaps remain visible."
        ),
    )
    with pytest.raises(PriorArtSearchCompleteError, match="digest"):
        assert_prior_art_search_complete_allowed(
            report=report,
            report_digest=digest,
            human_ack=ack,
        )


def test_build_checklist_without_report_not_complete_and_not_ready() -> None:
    checklist = build_prior_art_rule_checklist(
        subject_id="subject:app-16-123456",
        as_of_utc=AS_OF,
        authority_sources=(_official_source(),),
        prior_art_report=None,
        human_coverage_acknowledgment=None,
    )
    assert checklist.prior_art_search_complete is False
    assert checklist.readiness is ReadinessDisposition.NOT_READY
    assert REASON_MISSING_PRIOR_ART_REPORT in checklist.blocking_reason_codes
    assert REASON_MISSING_HUMAN_COVERAGE_ACK in checklist.blocking_reason_codes
    # Every item cites source/span/version/time
    assert_checklist_items_cite_sources(checklist.items)
    for item in checklist.items:
        assert item.citations
        for c in item.citations:
            assert c.source_cid
            assert c.span is not None
            assert c.version
            assert c.as_of_utc
    _assert_round_trip(checklist)


def test_build_checklist_complete_when_report_and_human_ack() -> None:
    report = _sample_report()
    ack = build_human_coverage_acknowledgment(
        acknowledger_name="Jordan Practitioner",
        acknowledged_at_utc="2024-06-14T18:00:00Z",
        report=report,
        coverage_scope_text=(
            "Searched US patents and publications; foreign patents and NPL "
            "remain unsearched and visible as coverage gaps."
        ),
    )
    checklist = build_prior_art_rule_checklist(
        subject_id="subject:app-16-123456",
        as_of_utc=AS_OF,
        authority_sources=(
            _official_source(),
            _official_source(
                source_id="src:form-sb08",
                label=AuthorityLabel.FORMS,
                version="form-sb08-2023-07",
                title="SB/08",
            ),
            _official_source(
                source_id="src:fee-schedule",
                label=AuthorityLabel.FEES,
                version="fee-2024-01",
                title="Fees",
            ),
            _official_source(
                source_id="src:mpep",
                label=AuthorityLabel.GUIDANCE,
                version="mpep-e9r10",
                title="MPEP",
            ),
        ),
        prior_art_report=report,
        human_coverage_acknowledgment=ack,
        report_source_cid=CID_REPORT,
        report_artifact_id="artifact:prior-art-report:unit-1",
    )
    assert checklist.prior_art_search_complete is True
    assert checklist.prior_art_search_date_utc == SEARCH
    assert checklist.prior_art_report_id == report.report_id
    assert checklist.readiness is ReadinessDisposition.READY
    assert checklist.blocking_reason_codes == ()
    labels = {i.authority_label for i in checklist.items}
    assert AuthorityLabel.OFFICIAL in labels
    assert AuthorityLabel.FORMS in labels
    assert AuthorityLabel.FEES in labels
    assert AuthorityLabel.GUIDANCE in labels
    assert AuthorityLabel.PRIOR_ART in labels
    assert_no_advice_content(checklist)
    _assert_round_trip(checklist)

    readiness = project_filing_preflight_readiness(checklist)
    assert readiness.readiness is ReadinessDisposition.READY
    assert readiness.prior_art_search_complete is True
    assert readiness.blocking_item_ids == ()
    _assert_round_trip(readiness)


def test_claim_complete_true_fails_without_prerequisites() -> None:
    with pytest.raises(PriorArtSearchCompleteError):
        build_prior_art_rule_checklist(
            subject_id="subject:x",
            as_of_utc=AS_OF,
            authority_sources=(_official_source(),),
            prior_art_report=None,
            claim_prior_art_search_complete=True,
        )


def test_human_ack_requires_gaps_visible_true() -> None:
    report = _sample_report()
    digest = content_digest(report.to_dict())
    with pytest.raises(ValueError, match="acknowledges_gaps_visible"):
        HumanCoverageAcknowledgment(
            acknowledger_name="Pat",
            acknowledged_at_utc="2024-06-14T18:00:00Z",
            report_id=report.report_id,
            report_digest=digest,
            coverage_scope_text="US only.",
            acknowledges_gaps_visible=False,
            statement="Acknowledged without gaps — invalid.",
        )


# ---------------------------------------------------------------------------
# Decision support, not advice
# ---------------------------------------------------------------------------


def test_advice_content_rejected() -> None:
    with pytest.raises(AdviceContentError):
        assert_no_advice_content(
            {"summary": "You should file this application immediately."}
        )
    with pytest.raises(AdviceContentError):
        RuleChecklistItem(
            item_id="item:advice",
            kind=ChecklistItemKind.OTHER,
            status=ChecklistStatus.PASS,
            authority_label=AuthorityLabel.OTHER,
            title="Advice",
            summary="This is legal advice to submit an IDS now.",
            citations=(
                SourceCitation(
                    source_cid=CID_A,
                    artifact_id="artifact:x",
                    span=_span(),
                    version="v1",
                    as_of_utc=AS_OF,
                ),
            ),
        )


def test_statuses_are_pass_fail_review_unknown() -> None:
    assert {s.value for s in ChecklistStatus} == {
        "pass",
        "fail",
        "review",
        "unknown",
    }


def test_missing_and_stale_in_full_checklist_block() -> None:
    report = _sample_report()
    ack = build_human_coverage_acknowledgment(
        acknowledger_name="Jordan Practitioner",
        acknowledged_at_utc="2024-06-14T18:00:00Z",
        report=report,
        coverage_scope_text="US patents only; foreign/NPL gaps visible.",
    )
    checklist = build_prior_art_rule_checklist(
        subject_id="subject:app-16-123456",
        as_of_utc=AS_OF,
        authority_sources=(
            _official_source(source_id="src:ok"),
            _official_source(
                source_id="src:missing",
                health=SourceHealth.MISSING,
            ),
            _official_source(
                source_id="src:stale",
                retrieved_at_utc="2019-01-01T00:00:00Z",
            ),
        ),
        prior_art_report=report,
        human_coverage_acknowledgment=ack,
        stale_max_age_seconds=7 * 86400,
        report_source_cid=CID_REPORT,
    )
    assert checklist.prior_art_search_complete is True
    assert checklist.readiness is ReadinessDisposition.NOT_READY
    codes = set(checklist.blocking_reason_codes)
    assert REASON_MISSING_SOURCE in codes
    assert REASON_STALE_SOURCE in codes
    readiness = project_filing_preflight_readiness(checklist)
    assert readiness.readiness is ReadinessDisposition.NOT_READY
    assert readiness.prior_art_search_complete is True
    assert readiness.blocking_item_ids
