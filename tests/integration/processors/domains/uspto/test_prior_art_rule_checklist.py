"""Integration: prior-art report + authority sources → preflight checklist (PATLAW-095).

Uses compact synthetic fixtures (PATLAW-094 prior-art report + current-rule
source inputs) rather than bulk golden dumps. Verifies fail-closed readiness,
citation completeness, separate forms/fees/guidance labels, and the prior-art
search-complete gate.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.patent.prior_art import (
    PRIOR_ART_SCHEMA_VERSION,
    ClaimChartEntry,
    PriorArtReport,
    build_claim_chart,
    build_prior_art_search_plan,
    record_dated_query_log,
    SearchCorpus,
    SearchQuerySpec,
    QueryFamily,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    DisclosureClass,
    PreRankingFilters,
    RankedHit,
    RetrievalFamily,
    SourceLink,
    SourceSpan,
)
from ipfs_datasets_py.processors.domains.patent.rules import (
    RULES_DISCLAIMER,
    RULES_SCHEMA_VERSION,
    AuthorityLabel,
    AuthorityViewKind,
    ChecklistStatus,
    CurrentRuleSourceInput,
    PriorArtSearchCompleteError,
    REASON_CONFLICTING_SOURCES,
    REASON_MISSING_HUMAN_COVERAGE_ACK,
    REASON_MISSING_PRIOR_ART_REPORT,
    REASON_MISSING_SOURCE,
    REASON_STALE_SOURCE,
    ReadinessDisposition,
    SourceHealth,
    assert_checklist_items_cite_sources,
    assert_no_advice_content,
    build_human_coverage_acknowledgment,
    build_prior_art_rule_checklist,
    content_digest,
    prior_art_search_complete_allowed,
    project_filing_preflight_readiness,
)

# ---------------------------------------------------------------------------
# Compact fixtures
# ---------------------------------------------------------------------------

CID_USC = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CID_CFR = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"
CID_FORM = "bafybeiformsb080000000000000000000000000000000000000000001"
CID_FEE = "bafybeifeeschedule000000000000000000000000000000000000001"
CID_MPEP = "bafybeimpepguidance00000000000000000000000000000000000001"
CID_PATENT = "bafybeipatentencode00000000000000000000000000000000000001"
CID_REPORT = "bafybeipriorartreportint00000000000000000000000000000001"
CID_CONFLICT_B = "bafybeiconflictalt000000000000000000000000000000000000001"

AS_OF = "2024-06-15T12:00:00Z"
FILING = "2022-03-15"
PRIORITY = "2021-03-15"
SEARCH = "2024-06-01T12:00:00Z"
SUBJECT = "subject:app-16-999001"

CLAIM_TEXT = (
    "1. A method comprising encoding claim text for hybrid retrieval; "
    "wherein documents are ranked by CPC G06F16/00; and applying temporal "
    "as-of filters before fusion."
)


def _span(start: int = 0, end: int = 48) -> SourceSpan:
    return SourceSpan(start=start, end=end, unit="char")


def _link(
    cid: str = CID_PATENT,
    artifact_id: str = "artifact:patent-encode",
    start: int = 0,
    end: int = 60,
) -> SourceLink:
    return SourceLink(
        source_cid=cid,
        artifact_id=artifact_id,
        span=_span(start, end),
        authority_tier="official-base",
    )


def _filters() -> PreRankingFilters:
    return PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id="tenant-public",
        as_of_utc=SEARCH,
        allowed_disclosures=(
            DisclosureClass.PUBLIC_OFFICIAL,
            DisclosureClass.PUBLIC_USER,
        ),
        applied=True,
        denied_provider_call_count=0,
        filter_receipt_id="filter:int-prior-art-rules",
    )


def _build_dated_prior_art_report() -> PriorArtReport:
    """Build a real PATLAW-094 prior-art report with dated query log + chart."""
    plan = build_prior_art_search_plan(
        subject_id=SUBJECT,
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
        rank_cutoff=5,
        filters=_filters(),
    )
    query = plan.queries[0] if plan.queries else SearchQuerySpec(
        query_id="q-int-1",
        query_text="encoding hybrid retrieval G06F16/00",
        family=QueryFamily.KEYWORD,
        intended_corpora=(SearchCorpus.US_PATENTS,),
        rank_cutoff=5,
    )
    hit = RankedHit(
        document_id="doc:patent-encode",
        score=11.0,
        rank=1,
        family=RetrievalFamily.FUSION,
        source_links=(_link(),),
    )
    log = record_dated_query_log(
        query,
        (hit,),
        search_date_utc=SEARCH,
        corpus=SearchCorpus.US_PATENTS,
        filters=_filters(),
    )
    lim = plan.limitations[0]
    entry = ClaimChartEntry(
        entry_id="entry:int-1",
        claim_number=1,
        limitation_id=lim.limitation_id,
        document_id="doc:patent-encode",
        rank=1,
        score=11.0,
        source_links=(_link(end=80),),
        query_id=query.query_id,
        log_id=log.log_id,
        passage_excerpt="encoding claim text for hybrid retrieval",
    )
    chart = build_claim_chart(
        subject_id=SUBJECT,
        filing_date=FILING,
        priority_date=PRIORITY,
        search_date_utc=SEARCH,
        entries=(entry,),
        limitations=plan.limitations,
        plan_id=plan.plan_id,
        coverage_gaps=plan.coverage_gaps,
    )
    return PriorArtReport(
        schema_version=PRIOR_ART_SCHEMA_VERSION,
        report_id="report:prior-art-int-1",
        plan=plan,
        query_logs=(log,),
        chart=chart,
        coverage_gaps=plan.coverage_gaps,
    )


def _source(
    *,
    source_id: str,
    cid: str,
    version: str,
    label: AuthorityLabel,
    title: str,
    health: SourceHealth = SourceHealth.OK,
    effective_start: str | None = "2011-09-16",
    effective_end: str | None = None,
    retrieved_at_utc: str | None = "2024-06-10T00:00:00Z",
    conflict_group: str | None = None,
    tier: str = "official-base",
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
        authority_tier=tier,
        effective_start=effective_start,
        effective_end=effective_end,
        retrieved_at_utc=retrieved_at_utc,
        citation_key=source_id,
        title=title,
        health=health,
        conflict_group=conflict_group,
    )


def _healthy_authority_set() -> tuple[CurrentRuleSourceInput, ...]:
    return (
        _source(
            source_id="src:usc-112b",
            cid=CID_USC,
            version="aia-2011",
            label=AuthorityLabel.OFFICIAL,
            title="35 U.S.C. § 112(b)",
            tier="official-base",
        ),
        _source(
            source_id="src:cfr-1-56",
            cid=CID_CFR,
            version="37-cfr-1.56-2024",
            label=AuthorityLabel.OFFICIAL,
            title="37 C.F.R. § 1.56",
            tier="official-base",
        ),
        _source(
            source_id="src:form-sb08",
            cid=CID_FORM,
            version="form-sb08-2023-07",
            label=AuthorityLabel.FORMS,
            title="PTO/SB/08",
            tier="guidance",
        ),
        _source(
            source_id="src:fee-schedule",
            cid=CID_FEE,
            version="fee-schedule-2024-01-16",
            label=AuthorityLabel.FEES,
            title="USPTO fee schedule",
            tier="guidance",
        ),
        _source(
            source_id="src:mpep-700",
            cid=CID_MPEP,
            version="mpep-e9r10-2024",
            label=AuthorityLabel.GUIDANCE,
            title="MPEP Chapter 700",
            tier="guidance",
        ),
    )


def _every_item_cites_source_span_version_time(checklist: Any) -> None:
    assert_checklist_items_cite_sources(checklist.items)
    for item in checklist.items:
        assert item.status in {
            ChecklistStatus.PASS,
            ChecklistStatus.FAIL,
            ChecklistStatus.REVIEW,
            ChecklistStatus.UNKNOWN,
        }
        for citation in item.citations:
            assert citation.source_cid
            assert citation.span is not None
            assert citation.span.end >= citation.span.start
            assert citation.version
            assert citation.version.lower() != "latest"
            assert citation.as_of_utc
            # Time anchor present (as-of and/or retrieved).
            assert citation.as_of_utc or citation.retrieved_at_utc


# ---------------------------------------------------------------------------
# Happy path: dated report + human coverage ack + healthy sources
# ---------------------------------------------------------------------------


def test_integration_preflight_ready_with_dated_report_and_human_ack() -> None:
    report = _build_dated_prior_art_report()
    assert report.search_date_utc == SEARCH
    assert report.query_logs  # dated query log present
    assert report.coverage_gaps  # foreign/NPL gaps visible

    ack = build_human_coverage_acknowledgment(
        acknowledger_name="Casey Responsible-Human",
        acknowledged_at_utc="2024-06-14T20:00:00Z",
        report=report,
        coverage_scope_text=(
            "Reviewed US patent/publication search plan and dated query logs. "
            "Foreign-patent and NPL corpora were not searched; those coverage "
            "gaps remain visible for practitioner review."
        ),
    )

    checklist = build_prior_art_rule_checklist(
        subject_id=SUBJECT,
        as_of_utc=AS_OF,
        authority_sources=_healthy_authority_set(),
        prior_art_report=report,
        human_coverage_acknowledgment=ack,
        authority_view=AuthorityViewKind.OFFICIAL,
        report_source_cid=CID_REPORT,
        report_artifact_id="artifact:prior-art-report:int-1",
    )

    assert checklist.schema_version == RULES_SCHEMA_VERSION
    assert checklist.prior_art_search_complete is True
    assert checklist.prior_art_search_date_utc == SEARCH
    assert checklist.prior_art_report_id == report.report_id
    assert checklist.prior_art_report_digest == content_digest(report.to_dict())
    assert checklist.readiness is ReadinessDisposition.READY
    assert checklist.blocking_reason_codes == ()
    assert checklist.is_ready is True

    # Separately labelled surfaces present.
    by_label = {item.authority_label for item in checklist.items}
    assert AuthorityLabel.OFFICIAL in by_label
    assert AuthorityLabel.FORMS in by_label
    assert AuthorityLabel.FEES in by_label
    assert AuthorityLabel.GUIDANCE in by_label
    assert AuthorityLabel.PRIOR_ART in by_label

    _every_item_cites_source_span_version_time(checklist)
    assert_no_advice_content(checklist)
    assert "decision support" in checklist.disclaimer.lower() or (
        "decision-support" in checklist.disclaimer.lower()
    )
    assert "not legal advice" in checklist.disclaimer.lower()

    # Round-trip stability.
    restored = type(checklist).from_dict(checklist.to_dict())
    assert restored.to_dict() == checklist.to_dict()

    readiness = project_filing_preflight_readiness(checklist)
    assert readiness.readiness is ReadinessDisposition.READY
    assert readiness.prior_art_search_complete is True
    assert readiness.blocking_item_ids == ()
    assert readiness.checklist_digest == content_digest(checklist.to_dict())
    assert_no_advice_content(readiness)


# ---------------------------------------------------------------------------
# Fail-closed: missing / stale / conflict sources block readiness
# ---------------------------------------------------------------------------


def test_integration_missing_stale_conflict_block_readiness() -> None:
    report = _build_dated_prior_art_report()
    ack = build_human_coverage_acknowledgment(
        acknowledger_name="Casey Responsible-Human",
        acknowledged_at_utc="2024-06-14T20:00:00Z",
        report=report,
        coverage_scope_text="US search; foreign/NPL gaps visible.",
    )

    sources = list(_healthy_authority_set())
    sources.append(
        _source(
            source_id="src:missing-rule",
            cid=CID_USC,
            version="absent",
            label=AuthorityLabel.OFFICIAL,
            title="Missing rule node",
            health=SourceHealth.MISSING,
        )
    )
    sources.append(
        _source(
            source_id="src:stale-rule",
            cid=CID_CFR,
            version="37-cfr-old",
            label=AuthorityLabel.OFFICIAL,
            title="Stale retrieval",
            retrieved_at_utc="2018-01-01T00:00:00Z",
        )
    )
    sources.append(
        _source(
            source_id="src:conflict-a",
            cid=CID_USC,
            version="v-alpha",
            label=AuthorityLabel.OFFICIAL,
            title="Conflict A",
            conflict_group="37-cfr-1.56",
        )
    )
    sources.append(
        _source(
            source_id="src:conflict-b",
            cid=CID_CONFLICT_B,
            version="v-beta",
            label=AuthorityLabel.OFFICIAL,
            title="Conflict B",
            conflict_group="37-cfr-1.56",
        )
    )

    checklist = build_prior_art_rule_checklist(
        subject_id=SUBJECT,
        as_of_utc=AS_OF,
        authority_sources=sources,
        prior_art_report=report,
        human_coverage_acknowledgment=ack,
        stale_max_age_seconds=14 * 86400,
        report_source_cid=CID_REPORT,
    )

    # Prior-art search may still be "complete" (report + ack) but readiness blocked.
    assert checklist.prior_art_search_complete is True
    assert checklist.readiness is ReadinessDisposition.NOT_READY
    codes = set(checklist.blocking_reason_codes)
    assert REASON_MISSING_SOURCE in codes
    assert REASON_STALE_SOURCE in codes
    assert REASON_CONFLICTING_SOURCES in codes
    assert checklist.blocking_items
    _every_item_cites_source_span_version_time(checklist)

    readiness = project_filing_preflight_readiness(checklist)
    assert readiness.readiness is ReadinessDisposition.NOT_READY
    assert readiness.prior_art_search_complete is True
    assert set(readiness.blocking_reason_codes) >= {
        REASON_MISSING_SOURCE,
        REASON_STALE_SOURCE,
        REASON_CONFLICTING_SOURCES,
    }


# ---------------------------------------------------------------------------
# Prior-art search complete gate
# ---------------------------------------------------------------------------


def test_integration_cannot_claim_complete_without_report_or_ack() -> None:
    # No report, no ack.
    checklist = build_prior_art_rule_checklist(
        subject_id=SUBJECT,
        as_of_utc=AS_OF,
        authority_sources=_healthy_authority_set(),
        prior_art_report=None,
        human_coverage_acknowledgment=None,
    )
    assert checklist.prior_art_search_complete is False
    assert checklist.readiness is ReadinessDisposition.NOT_READY
    assert REASON_MISSING_PRIOR_ART_REPORT in checklist.blocking_reason_codes
    assert REASON_MISSING_HUMAN_COVERAGE_ACK in checklist.blocking_reason_codes
    _every_item_cites_source_span_version_time(checklist)
    assert_no_advice_content(checklist)

    # Dated report without human ack.
    report = _build_dated_prior_art_report()
    checklist2 = build_prior_art_rule_checklist(
        subject_id=SUBJECT,
        as_of_utc=AS_OF,
        authority_sources=_healthy_authority_set(),
        prior_art_report=report,
        human_coverage_acknowledgment=None,
        report_source_cid=CID_REPORT,
    )
    assert checklist2.prior_art_search_complete is False
    assert checklist2.prior_art_search_date_utc == SEARCH
    assert REASON_MISSING_HUMAN_COVERAGE_ACK in checklist2.blocking_reason_codes
    assert prior_art_search_complete_allowed(
        report=report, report_digest=None, human_ack=None
    ) is False

    with pytest.raises(PriorArtSearchCompleteError):
        build_prior_art_rule_checklist(
            subject_id=SUBJECT,
            as_of_utc=AS_OF,
            authority_sources=_healthy_authority_set(),
            prior_art_report=report,
            human_coverage_acknowledgment=None,
            claim_prior_art_search_complete=True,
            report_source_cid=CID_REPORT,
        )


def test_integration_ack_bound_to_report_digest_invalidates_on_mismatch() -> None:
    report = _build_dated_prior_art_report()
    wrong_ack = build_human_coverage_acknowledgment(
        acknowledger_name="Casey Responsible-Human",
        acknowledged_at_utc="2024-06-14T20:00:00Z",
        report=report,
        coverage_scope_text="US search; gaps visible.",
        report_digest="a" * 64,  # deliberately wrong
    )
    checklist = build_prior_art_rule_checklist(
        subject_id=SUBJECT,
        as_of_utc=AS_OF,
        authority_sources=_healthy_authority_set(),
        prior_art_report=report,
        human_coverage_acknowledgment=wrong_ack,
        report_source_cid=CID_REPORT,
    )
    assert checklist.prior_art_search_complete is False
    assert checklist.readiness is ReadinessDisposition.NOT_READY
    # Human ack item should fail / block.
    ack_items = [
        i
        for i in checklist.items
        if i.kind.value == "human_coverage_acknowledgment"
    ]
    assert ack_items
    assert any(i.blocks_readiness for i in ack_items)


def test_integration_disclaimer_is_decision_support_not_advice() -> None:
    report = _build_dated_prior_art_report()
    ack = build_human_coverage_acknowledgment(
        acknowledger_name="Casey Responsible-Human",
        acknowledged_at_utc="2024-06-14T20:00:00Z",
        report=report,
        coverage_scope_text="US search; gaps visible.",
    )
    checklist = build_prior_art_rule_checklist(
        subject_id=SUBJECT,
        as_of_utc=AS_OF,
        authority_sources=_healthy_authority_set(),
        prior_art_report=report,
        human_coverage_acknowledgment=ack,
        report_source_cid=CID_REPORT,
    )
    lower = RULES_DISCLAIMER.lower()
    assert "not legal advice" in lower
    assert "decision support" in lower or "decision-support" in lower
    # Must not authorize filing / IDS / strategy.
    for phrase in (
        "you should file",
        "sign and file",
        "submit an ids",
        "is patentable",
    ):
        assert phrase not in lower
    assert_no_advice_content(checklist.to_dict())
