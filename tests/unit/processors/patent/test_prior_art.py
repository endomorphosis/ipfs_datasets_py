"""Unit tests for reproducible prior-art plans and claim charts (PATLAW-094)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.prior_art import (
    PRIOR_ART_DISCLAIMER,
    PRIOR_ART_SCHEMA_VERSION,
    ChartSourceCitationError,
    ClaimChart,
    ClaimChartEntry,
    ClaimLimitationCandidate,
    CoverageGap,
    CoverageGapKind,
    CoverageGapVisibilityError,
    DatedQueryLog,
    KeywordCandidate,
    MaterialRole,
    MissingTemporalAnchorError,
    PatentabilityConclusionError,
    PriorArtReport,
    PriorArtSearchPlan,
    QueryFamily,
    RankedPassageHit,
    SearchCorpus,
    SearchQuerySpec,
    assert_chart_entries_cite_sources,
    assert_no_patentability_conclusions,
    build_claim_chart,
    build_prior_art_search_plan,
    build_search_queries,
    canonical_json,
    content_digest,
    default_coverage_gaps,
    default_golden_claim_chart_path,
    decompose_claim_limitations,
    execute_prior_art_plan,
    extract_keyword_candidates,
    load_golden_claim_chart,
    parse_golden_claim_chart,
    record_dated_query_log,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    AuthorityClaim,
    DisclosureClass,
    EdgeProvenance,
    PreRankingFilters,
    RankedHit,
    RetrievalFamily,
    SourceLink,
    SourceSpan,
)

CID_SOURCE = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"
CID_SOURCE_B = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"

FILING = "2022-03-15"
PRIORITY = "2021-03-15"
SEARCH = "2024-06-01T12:00:00Z"

CLAIM_TEXT = (
    "1. A method comprising encoding claim text for retrieval; "
    "wherein the system indexes CPC G06F16/00 documents; "
    "and applying 35 U.S.C. section 102 prior art analysis."
)


def _link(
    cid: str = CID_SOURCE,
    artifact_id: str = "artifact:patent-11222333",
    start: int = 0,
    end: int = 40,
) -> SourceLink:
    return SourceLink(
        source_cid=cid,
        artifact_id=artifact_id,
        span=SourceSpan(start=start, end=end, unit="char"),
        authority_tier="official-base",
    )


def _filters(*, applied: bool = True) -> PreRankingFilters:
    return PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id="tenant-public",
        as_of_utc=SEARCH,
        allowed_disclosures=(
            DisclosureClass.PUBLIC_OFFICIAL,
            DisclosureClass.PUBLIC_USER,
        ),
        applied=applied,
        denied_provider_call_count=0,
        filter_receipt_id="filter:prior-art",
    )


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert restored == record


def _sample_plan(**overrides: object) -> PriorArtSearchPlan:
    kwargs: dict[str, object] = dict(
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
        rank_cutoff=5,
        filters=_filters(),
        citation_seed_document_ids=("doc:patent-encode",),
        family_seed_document_ids=("doc:patent-encode",),
    )
    kwargs.update(overrides)
    return build_prior_art_search_plan(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Schema / disclaimer
# ---------------------------------------------------------------------------


def test_schema_version_pinned() -> None:
    assert PRIOR_ART_SCHEMA_VERSION == "patent.prior_art.v1"
    assert "patentability" in PRIOR_ART_DISCLAIMER.lower()
    assert "candidates" in PRIOR_ART_DISCLAIMER.lower()
    assert "foreign" in PRIOR_ART_DISCLAIMER.lower()
    assert "npl" in PRIOR_ART_DISCLAIMER.lower()


# ---------------------------------------------------------------------------
# Limitation / keyword candidates
# ---------------------------------------------------------------------------


def test_decompose_claim_limitations_are_candidates() -> None:
    limitations = decompose_claim_limitations(CLAIM_TEXT, claim_number=1)
    assert len(limitations) >= 2
    for lim in limitations:
        assert lim.is_candidate is True
        assert lim.role is MaterialRole.CANDIDATE
        assert lim.authority_claim is not AuthorityClaim.SOURCE_BOUND
        assert lim.provenance is EdgeProvenance.CANDIDATE
        assert lim.claim_number == 1
    _assert_round_trip(limitations[0])


def test_keyword_candidates_are_candidates() -> None:
    keywords = extract_keyword_candidates(
        [CLAIM_TEXT],
        classifications=("G06F16/00",),
        related_limitation_ids=("lim:c1-1",),
    )
    assert keywords
    assert any(k.kind == "classification" for k in keywords)
    for kw in keywords:
        assert kw.is_candidate is True
        assert kw.role is MaterialRole.CANDIDATE
        assert kw.authority_claim is not AuthorityClaim.SOURCE_BOUND
    _assert_round_trip(keywords[0])


def test_limitation_candidate_rejects_source_bound_authority() -> None:
    with pytest.raises((PatentabilityConclusionError, ValueError, Exception)):
        ClaimLimitationCandidate(
            limitation_id="lim:bad",
            claim_number=1,
            text="encoding text",
            is_candidate=True,
            authority_claim=AuthorityClaim.SOURCE_BOUND,
            provenance=EdgeProvenance.CANDIDATE,
        )


def test_limitation_candidate_requires_is_candidate_true() -> None:
    with pytest.raises(ValueError, match="is_candidate"):
        ClaimLimitationCandidate(
            limitation_id="lim:bad",
            claim_number=1,
            text="encoding text",
            is_candidate=False,
        )


# ---------------------------------------------------------------------------
# Plan: explicit dates, gaps, no patentability
# ---------------------------------------------------------------------------


def test_build_plan_requires_explicit_dates() -> None:
    plan = _sample_plan()
    assert plan.filing_date == FILING
    assert plan.priority_date == PRIORITY
    assert plan.search_date_utc == SEARCH
    assert plan.limitations
    assert all(lim.is_candidate for lim in plan.limitations)
    assert plan.keywords
    assert all(kw.is_candidate for kw in plan.keywords)
    assert plan.queries
    _assert_round_trip(plan)


def test_plan_rejects_missing_filing_date() -> None:
    with pytest.raises((MissingTemporalAnchorError, ValueError)):
        build_prior_art_search_plan(
            subject_id="subject:x",
            filing_date="",
            priority_date=PRIORITY,
            search_date_utc=SEARCH,
            claims=({"claim_number": 1, "claim_text": CLAIM_TEXT},),
        )


def test_plan_rejects_invalid_search_timestamp() -> None:
    with pytest.raises(ValueError, match="ISO-8601"):
        build_prior_art_search_plan(
            subject_id="subject:x",
            filing_date=FILING,
            priority_date=PRIORITY,
            search_date_utc="2024-06-01",  # date only — not UTC timestamp
            claims=({"claim_number": 1, "claim_text": CLAIM_TEXT},),
        )


def test_foreign_patent_and_npl_gaps_always_visible_on_plan() -> None:
    plan = _sample_plan()
    kinds = {g.kind for g in plan.coverage_gaps}
    assert CoverageGapKind.FOREIGN_PATENT in kinds
    assert CoverageGapKind.NPL in kinds
    for gap in plan.coverage_gaps:
        if gap.kind in (CoverageGapKind.FOREIGN_PATENT, CoverageGapKind.NPL):
            assert gap.remains_visible is True
            # Default U.S.-only plan does not mark these as fully searched.
            assert gap.searched is False


def test_plan_without_required_gaps_fails() -> None:
    lim = decompose_claim_limitations(CLAIM_TEXT)[0]
    kw = extract_keyword_candidates([CLAIM_TEXT])[0]
    query = SearchQuerySpec(
        query_id="q1",
        query_text="encoding",
        family=QueryFamily.KEYWORD,
        intended_corpora=(SearchCorpus.US_PATENTS,),
    )
    with pytest.raises(CoverageGapVisibilityError):
        PriorArtSearchPlan(
            schema_version=PRIOR_ART_SCHEMA_VERSION,
            plan_id="plan:test",
            subject_id="subject:x",
            filing_date=FILING,
            priority_date=PRIORITY,
            search_date_utc=SEARCH,
            claims=({"claim_number": 1, "claim_text": CLAIM_TEXT},),
            limitations=(lim,),
            keywords=(kw,),
            queries=(query,),
            intended_corpora=(SearchCorpus.US_PATENTS,),
            coverage_gaps=(),  # missing foreign + NPL
        )


def test_plan_rejects_patentability_metadata() -> None:
    with pytest.raises(PatentabilityConclusionError):
        build_prior_art_search_plan(
            subject_id="subject:x",
            filing_date=FILING,
            priority_date=PRIORITY,
            search_date_utc=SEARCH,
            claims=({"claim_number": 1, "claim_text": CLAIM_TEXT},),
            metadata={"patentability_conclusion": "novel"},
        )


def test_build_search_queries_us_corpora_only_by_default() -> None:
    lims = decompose_claim_limitations(CLAIM_TEXT)
    kws = extract_keyword_candidates([CLAIM_TEXT], classifications=("G06F16/00",))
    queries = build_search_queries(limitations=lims, keywords=kws, classifications=("G06F16/00",))
    assert queries
    for q in queries:
        for corpus in q.intended_corpora:
            assert corpus in (
                SearchCorpus.US_PATENTS,
                SearchCorpus.US_PUBLICATIONS,
            )


# ---------------------------------------------------------------------------
# Chart: source CID/span required
# ---------------------------------------------------------------------------


def test_chart_entry_requires_source_cid_and_span() -> None:
    entry = ClaimChartEntry(
        entry_id="entry:1",
        claim_number=1,
        limitation_id="lim:c1-1",
        document_id="doc:patent-encode",
        rank=1,
        score=10.0,
        source_links=(_link(),),
    )
    _assert_round_trip(entry)

    with pytest.raises(ChartSourceCitationError):
        ClaimChartEntry(
            entry_id="entry:bad",
            claim_number=1,
            limitation_id="lim:c1-1",
            document_id="doc:x",
            rank=1,
            score=1.0,
            source_links=(),
        )

    with pytest.raises(ChartSourceCitationError):
        ClaimChartEntry(
            entry_id="entry:bad-span",
            claim_number=1,
            limitation_id="lim:c1-1",
            document_id="doc:x",
            rank=1,
            score=1.0,
            source_links=(
                SourceLink(
                    source_cid=CID_SOURCE,
                    artifact_id="artifact:x",
                    span=None,
                ),
            ),
        )


def test_claim_chart_explicit_dates_and_gaps() -> None:
    lim = decompose_claim_limitations(CLAIM_TEXT)[0]
    entry = ClaimChartEntry(
        entry_id="entry:1",
        claim_number=1,
        limitation_id=lim.limitation_id,
        document_id="doc:patent-encode",
        rank=1,
        score=9.5,
        source_links=(_link(end=80),),
        query_id="q-lim-1",
        passage_excerpt="encoding claim text for retrieval",
    )
    chart = build_claim_chart(
        subject_id="subject:app-16-123456",
        filing_date=FILING,
        priority_date=PRIORITY,
        search_date_utc=SEARCH,
        entries=(entry,),
        limitations=(lim,),
        plan_id="plan:test",
    )
    assert chart.filing_date == FILING
    assert chart.priority_date == PRIORITY
    assert chart.search_date_utc == SEARCH
    assert_chart_entries_cite_sources(chart)
    kinds = {g.kind for g in chart.coverage_gaps}
    assert CoverageGapKind.FOREIGN_PATENT in kinds
    assert CoverageGapKind.NPL in kinds
    assert "patentability" in chart.disclaimer.lower()
    _assert_round_trip(chart)


def test_assert_no_patentability_conclusions_on_chart() -> None:
    chart = build_claim_chart(
        subject_id="subject:x",
        filing_date=FILING,
        priority_date=PRIORITY,
        search_date_utc=SEARCH,
        entries=(
            ClaimChartEntry(
                entry_id="entry:1",
                claim_number=1,
                limitation_id="lim:c1-1",
                document_id="doc:a",
                rank=1,
                score=1.0,
                source_links=(_link(),),
            ),
        ),
    )
    assert_no_patentability_conclusions(chart)
    assert_no_patentability_conclusions(chart.to_dict())

    bad = chart.to_dict()
    bad["metadata"] = {"novelty": "claim is novel over art"}
    with pytest.raises(PatentabilityConclusionError):
        assert_no_patentability_conclusions(bad)


# ---------------------------------------------------------------------------
# Dated query logs + execution
# ---------------------------------------------------------------------------


def test_dated_query_log_records_search_date_ranks_cutoff() -> None:
    query = SearchQuerySpec(
        query_id="q-kw-1",
        query_text="encoding retrieval G06F16/00",
        family=QueryFamily.KEYWORD,
        intended_corpora=(SearchCorpus.US_PATENTS,),
        rank_cutoff=3,
        related_limitation_ids=("lim:c1-1",),
    )
    hits = (
        RankedHit(
            document_id="doc:patent-encode",
            score=10.0,
            rank=1,
            family=RetrievalFamily.FUSION,
            source_links=(_link(),),
        ),
        RankedHit(
            document_id="doc:patent-network",
            score=4.0,
            rank=2,
            family=RetrievalFamily.FUSION,
            source_links=(_link(CID_SOURCE_B, "artifact:patent-10123456"),),
        ),
        RankedHit(
            document_id="doc:past-cutoff",
            score=1.0,
            rank=5,
            family=RetrievalFamily.FUSION,
            source_links=(_link(),),
        ),
    )
    log = record_dated_query_log(
        query,
        hits,
        search_date_utc=SEARCH,
        corpus=SearchCorpus.US_PATENTS,
        filters=_filters(),
    )
    assert log.search_date_utc == SEARCH
    assert log.rank_cutoff == 3
    assert log.query_text == query.query_text
    assert all(h.rank <= 3 for h in log.hits)
    assert {h.document_id for h in log.hits} == {
        "doc:patent-encode",
        "doc:patent-network",
    }
    for hit in log.hits:
        assert hit.source_links
        assert any(link.span is not None for link in hit.source_links)
    _assert_round_trip(log)


def test_execute_plan_with_search_fn_builds_report() -> None:
    plan = _sample_plan()

    def fake_search(
        query: SearchQuerySpec, filters: PreRankingFilters
    ):
        from ipfs_datasets_py.processors.domains.patent.hybrid_retrieval import (
            HybridSearchResult,
        )
        from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
            FusionResult,
            FusionWeights,
        )

        hit = RankedHit(
            document_id="doc:patent-encode",
            score=8.0,
            rank=1,
            family=RetrievalFamily.FUSION,
            source_links=(_link(end=60),),
        )
        fusion = FusionResult(
            schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
            query_id=query.query_id,
            filters=filters if filters.applied else filters.mark_applied(),
            fusion_weights=FusionWeights(),
            bm25_hits=(),
            vector_hits=(),
            graph_hits=(),
            fused_hits=(hit,),
            corpus_cid=CID_SOURCE,
            config_cid=CID_SOURCE_B,
        )
        return HybridSearchResult(
            fusion=fusion,
            bm25_backend="python",
            vector_embedding={"provider": "local"},
            denied_provider_call_count=0,
            remote_embedding_calls=0,
        )

    report = execute_prior_art_plan(plan, search_fn=fake_search, filters=_filters())
    assert isinstance(report, PriorArtReport)
    assert report.filing_date == FILING
    assert report.priority_date == PRIORITY
    assert report.search_date_utc == SEARCH
    assert report.query_logs
    for log in report.query_logs:
        assert log.search_date_utc == SEARCH
        assert log.rank_cutoff >= 1
    assert report.chart.entries
    assert_chart_entries_cite_sources(report.chart)
    kinds = {g.kind for g in report.coverage_gaps}
    assert CoverageGapKind.FOREIGN_PATENT in kinds
    assert CoverageGapKind.NPL in kinds
    assert_no_patentability_conclusions(report)
    _assert_round_trip(report)


# ---------------------------------------------------------------------------
# Golden fixture
# ---------------------------------------------------------------------------


def test_golden_claim_chart_fixture_exists_and_validates() -> None:
    path = default_golden_claim_chart_path()
    assert path.is_file(), f"missing golden fixture at {path}"
    payload = load_golden_claim_chart(path)
    assert payload["schema_version"] == PRIOR_ART_SCHEMA_VERSION
    plan, chart, report = parse_golden_claim_chart(payload)

    # Explicit dates
    assert plan.filing_date
    assert plan.priority_date
    assert plan.search_date_utc
    assert chart.filing_date == plan.filing_date
    assert chart.priority_date == plan.priority_date
    assert chart.search_date_utc == plan.search_date_utc

    # Chart entries cite source CID/span
    assert chart.entries
    for entry in chart.entries:
        assert entry.source_links
        assert any(link.source_cid for link in entry.source_links)
        assert any(link.span is not None for link in entry.source_links)

    # Limitations / keywords are candidates
    assert plan.limitations
    assert all(lim.is_candidate for lim in plan.limitations)
    assert plan.keywords
    assert all(kw.is_candidate for kw in plan.keywords)

    # Foreign-patent and NPL gaps visible
    for obj_gaps in (plan.coverage_gaps, chart.coverage_gaps):
        kinds = {g.kind for g in obj_gaps}
        assert CoverageGapKind.FOREIGN_PATENT in kinds
        assert CoverageGapKind.NPL in kinds

    # No patentability conclusion
    assert_no_patentability_conclusions(payload)
    assert_no_patentability_conclusions(plan)
    assert_no_patentability_conclusions(chart)
    if report is not None:
        assert_no_patentability_conclusions(report)

    # Deterministic round-trip of golden payload components
    _assert_round_trip(plan)
    _assert_round_trip(chart)


def test_default_coverage_gaps_pair() -> None:
    gaps = default_coverage_gaps()
    assert len(gaps) == 2
    assert {g.kind for g in gaps} == {
        CoverageGapKind.FOREIGN_PATENT,
        CoverageGapKind.NPL,
    }
    for g in gaps:
        assert g.remains_visible is True


def test_content_digest_stable() -> None:
    a = content_digest({"a": 1, "b": [2, 3]})
    b = content_digest({"b": [2, 3], "a": 1})
    assert a == b
    assert len(a) == 64
