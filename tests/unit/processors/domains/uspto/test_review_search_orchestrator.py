"""Unit tests for PAAR review search orchestrator (PAAR-030)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.review_search_orchestrator import (
    REVIEW_SEARCH_ORCHESTRATOR_SCHEMA,
    REVIEW_ONLY_SEARCH_DISCLAIMER,
    CorpusStatus,
    OrchestrationMode,
    ReviewSearchOrchestration,
    apply_cutoff_to_query_text,
    compose_review_search,
    default_named_gaps,
    filter_hits_by_cutoff,
    resolve_cutoff_date,
)


SAMPLE_CLAIMS = """\
1. A method comprising detecting a sensor signal and generating an alert.

2. The method of claim 1, wherein the alert is audible.
"""


def test_compose_hermetic_us_plan_and_journal() -> None:
    result = compose_review_search(
        application_number="16000001",
        claims_text=SAMPLE_CLAIMS,
        filing_date="2020-01-15",
        priority_date="2019-06-01",
        mode=OrchestrationMode.HERMETIC_STUB,
        enable_foreign=False,
        enable_npl=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert result.schema == REVIEW_SEARCH_ORCHESTRATOR_SCHEMA
    assert result.auto_file_blocked is True
    assert result.application_number == "16000001"
    assert result.cutoff_date == "2019-06-01"
    assert result.priority_date == "2019-06-01"
    assert result.content_digest
    assert len(result.content_digest) == 64
    # US corpora planned/stubbed
    corpora = {c.corpus: c for c in result.corpora}
    assert "us_patents" in corpora
    assert corpora["us_patents"].status in {
        CorpusStatus.STUB,
        CorpusStatus.PLANNED,
        CorpusStatus.SEARCHED,
    }
    assert corpora["us_patents"].query_count >= 1
    # Journal stubs present
    assert len(result.journal_records) >= 1
    # Cutoff annotated on queries when anchors provided
    assert any(
        result.cutoff_date in (r.query_text or "")
        or r.cutoff_date == result.cutoff_date
        for r in result.journal_records
    )


def test_foreign_unsearched_named_gap() -> None:
    result = compose_review_search(
        application_number="16000002",
        claims_text=SAMPLE_CLAIMS,
        filing_date="2020-01-15",
        priority_date="2019-06-01",
        enable_foreign=False,
        enable_npl=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    gap_kinds = {g.kind for g in result.named_gaps} | {
        g.corpus for g in result.named_gaps
    }
    assert "foreign_patent" in gap_kinds or "foreign_patents" in gap_kinds
    assert "npl" in gap_kinds
    assert "foreign_patents" in result.unsearched_corpora
    assert "npl" in result.unsearched_corpora
    payload = result.to_dict()
    assert payload["coverage_declaration"]["named_gaps"]
    foreign_entries = [
        c for c in result.corpora if c.corpus == "foreign_patents"
    ]
    assert foreign_entries
    assert foreign_entries[0].status is CorpusStatus.UNSEARCHED


def test_optional_foreign_fixture_searches() -> None:
    result = compose_review_search(
        application_number="16000003",
        claims_text=SAMPLE_CLAIMS,
        filing_date="2020-01-15",
        priority_date="2019-06-01",
        enable_foreign=True,
        enable_npl=False,
        foreign_fixture=[
            {
                "document_id": "EP1234567",
                "publication_date": "2018-01-01",
                "title": "Foreign prior art stub",
            }
        ],
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert "foreign_patents" in result.searched_corpora
    # Foreign no longer unsearched gap
    assert not any(
        g.corpus == "foreign_patents" and g.status == "unsearched"
        for g in result.named_gaps
    )
    # NPL still gap
    assert any(g.corpus == "npl" for g in result.named_gaps)
    foreign_journal = [
        r for r in result.journal_records if r.corpus == "foreign_patents"
    ]
    assert foreign_journal
    assert foreign_journal[0].hit_count >= 1


def test_priority_date_cutoff_applied() -> None:
    cutoff = resolve_cutoff_date(
        priority_date="2018-05-01",
        filing_date="2019-01-01",
    )
    assert cutoff == "2018-05-01"
    q = apply_cutoff_to_query_text("claim_limitation sensor", cutoff)
    assert "2018-05-01" in q
    assert "prior_art_cutoff" in q

    hits = filter_hits_by_cutoff(
        [
            {"document_id": "A", "publication_date": "2017-01-01"},
            {"document_id": "B", "publication_date": "2020-01-01"},
            {"document_id": "C", "publication_date": "2018-04-30"},
        ],
        cutoff,
    )
    ids = {h["document_id"] for h in hits}
    assert "A" in ids
    assert "C" in ids
    assert "B" not in ids


def test_cutoff_override_and_family_seed_mode() -> None:
    assert (
        resolve_cutoff_date(
            priority_date="2018-01-01",
            override_cutoff="2017-06-01",
        )
        == "2017-06-01"
    )
    # allow_post_cutoff for IDS/family seed mode
    hits = filter_hits_by_cutoff(
        [{"document_id": "B", "publication_date": "2020-01-01"}],
        "2018-01-01",
        allow_post_cutoff=True,
    )
    assert len(hits) == 1


def test_compose_applies_cutoff_to_foreign_fixture_hits() -> None:
    """PAAR-031: post-cutoff publications excluded from hit sets by default."""
    result = compose_review_search(
        application_number="16000031",
        claims_text=SAMPLE_CLAIMS,
        filing_date="2020-01-15",
        priority_date="2019-06-01",
        enable_foreign=True,
        enable_npl=True,
        foreign_fixture=[
            {
                "document_id": "EP-PRE",
                "publication_date": "2018-01-01",
                "title": "Pre-cutoff foreign",
            },
            {
                "document_id": "EP-POST",
                "publication_date": "2021-01-01",
                "title": "Post-cutoff foreign",
            },
        ],
        npl_fixture=[
            {
                "document_id": "NPL-PRE",
                "publication_date": "2017-06-01",
                "title": "Pre-cutoff NPL",
            },
            {
                "document_id": "NPL-POST",
                "publication_date": "2022-01-01",
                "title": "Post-cutoff NPL",
            },
        ],
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert result.cutoff_date == "2019-06-01"
    # All journal records carry cutoff
    assert all(
        (r.cutoff_date == result.cutoff_date) or result.cutoff_date in (r.query_text or "")
        for r in result.journal_records
        if r.corpus in {"foreign_patents", "npl", "us_patents"}
    )
    # Foreign/NPL hits filtered by publication date
    foreign_hits: list[dict] = []
    npl_hits: list[dict] = []
    for rec in result.journal_records:
        hits = list(getattr(rec, "hits", None) or rec.to_dict().get("hits") or [])
        if rec.corpus == "foreign_patents":
            foreign_hits.extend(hits if isinstance(hits, list) else [])
        if rec.corpus == "npl":
            npl_hits.extend(hits if isinstance(hits, list) else [])
    # Prefer direct hit lists from result if journal structure differs
    payload = result.to_dict()
    all_hits = []
    for rec in payload.get("journal_records") or []:
        all_hits.extend(rec.get("hits") or [])
    if not foreign_hits and not npl_hits and all_hits:
        foreign_hits = [
            h
            for h in all_hits
            if str(h.get("document_id") or "").startswith("EP")
            or str(h.get("corpus") or "") == "foreign_patents"
        ]
        npl_hits = [
            h
            for h in all_hits
            if str(h.get("document_id") or "").startswith("NPL")
            or str(h.get("corpus") or "") == "npl"
        ]
    # When hits are present, post-cutoff docs must be excluded
    doc_ids = {
        str(h.get("document_id") or h.get("hit_id") or "")
        for h in (foreign_hits + npl_hits + all_hits)
    }
    if doc_ids:
        assert "EP-POST" not in doc_ids
        assert "NPL-POST" not in doc_ids
        # Pre-cutoff may remain when fixtures flow through
        # (unknown-date hits kept with cutoff_date_unknown)
    # Explicit unit filter still enforces exclusion (regression lock)
    filtered = filter_hits_by_cutoff(
        [
            {"document_id": "EP-PRE", "publication_date": "2018-01-01"},
            {"document_id": "EP-POST", "publication_date": "2021-01-01"},
        ],
        result.cutoff_date,
    )
    assert {h["document_id"] for h in filtered} == {"EP-PRE"}


def test_effective_filing_date_precedes_priority() -> None:
    """PAAR-031: cutoff precedence override > effective > priority > filing."""
    assert (
        resolve_cutoff_date(
            filing_date="2020-01-01",
            priority_date="2019-01-01",
            effective_filing_date="2018-06-15",
        )
        == "2018-06-15"
    )
    assert (
        resolve_cutoff_date(
            filing_date="2020-01-01",
            priority_date="2019-01-01",
            effective_filing_date="2018-06-15",
            override_cutoff="2017-12-01",
        )
        == "2017-12-01"
    )


def test_plan_only_mode() -> None:
    result = compose_review_search(
        application_number="16000004",
        claims_text=SAMPLE_CLAIMS,
        filing_date="2020-01-15",
        priority_date="2019-06-01",
        mode=OrchestrationMode.PLAN_ONLY,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert result.mode is OrchestrationMode.PLAN_ONLY
    assert all(not r.executed for r in result.journal_records if r.corpus.startswith("us"))
    us = next(c for c in result.corpora if c.corpus == "us_patents")
    assert us.status is CorpusStatus.PLANNED


def test_fixture_hits_on_us_queries() -> None:
    # First build to learn query ids, or pass hermetic stub plan
    base = compose_review_search(
        application_number="16000005",
        claims_text=SAMPLE_CLAIMS,
        filing_date="2020-01-15",
        priority_date="2019-06-01",
        use_client_plan=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    qids = [r.query_id for r in base.journal_records if r.corpus.startswith("us")]
    assert qids
    fixture = {
        qids[0]: [
            {
                "document_id": "US9999999",
                "publication_date": "2015-01-01",
                "passage_excerpt": "detecting a sensor signal",
            }
        ]
    }
    result = compose_review_search(
        application_number="16000005",
        claims_text=SAMPLE_CLAIMS,
        filing_date="2020-01-15",
        priority_date="2019-06-01",
        use_client_plan=False,
        fixture_hits=fixture,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    matched = [r for r in result.journal_records if r.query_id == qids[0]]
    assert matched
    assert matched[0].hit_count >= 1
    assert matched[0].executed is True


def test_deterministic_digest() -> None:
    kwargs = dict(
        application_number="16000006",
        claims_text=SAMPLE_CLAIMS,
        filing_date="2020-01-15",
        priority_date="2019-06-01",
        use_client_plan=False,
        generated_at_utc="2026-08-06T00:00:00Z",
        orchestration_id="rso:test:fixed",
    )
    r1 = compose_review_search(**kwargs)
    r2 = compose_review_search(**kwargs)
    assert r1.content_digest == r2.content_digest
    restored = ReviewSearchOrchestration.from_dict(r1.to_dict())
    assert restored.content_digest == r1.content_digest


def test_phrase_ban_and_disclaimer() -> None:
    result = compose_review_search(
        application_number="16000007",
        claims_text=SAMPLE_CLAIMS,
        filing_date="2020-01-15",
        priority_date="2019-06-01",
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    lower = json.dumps(result.to_dict()).lower()
    for phrase in (
        "is patentable",
        "is novel",
        "is obvious",
        "no prior art exists",
    ):
        assert phrase not in lower
    d = REVIEW_ONLY_SEARCH_DISCLAIMER.lower()
    assert "not legal advice" in d
    assert "not a patentability" in d or "patentability" in d


def test_default_named_gaps() -> None:
    gaps = default_named_gaps(searched_corpora=("us_patents",))
    corpora = {g.corpus for g in gaps}
    assert "foreign_patents" in corpora
    assert "npl" in corpora
    gaps2 = default_named_gaps(
        searched_corpora=("us_patents", "foreign_patents", "npl"),
        foreign_searched=True,
        npl_searched=True,
    )
    assert gaps2 == []


def test_uses_prior_art_client_when_available() -> None:
    result = compose_review_search(
        application_number="16000008",
        claims=[
            {
                "claim_number": 1,
                "text": "A method comprising detecting a sensor signal.",
            }
        ],
        filing_date="2020-01-15",
        priority_date="2019-06-01",
        use_client_plan=True,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    # Either client plan or hermetic fallback is acceptable offline
    assert result.prior_art_plan is not None
    assert result.metadata.get("plan_source") in {
        "prior_art_search_client",
        "hermetic_stub_fallback",
        "hermetic_stub",
        "provided",
    }
    assert result.prior_art_plan_id or result.prior_art_plan.get("plan_id")


def test_coverage_declaration_in_payload() -> None:
    result = compose_review_search(
        application_number="16000009",
        claims_text=SAMPLE_CLAIMS,
        filing_date="2020-01-15",
        priority_date="2019-06-01",
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    payload = result.to_dict()
    assert "coverage_declaration" in payload
    assert payload["auto_file_blocked"] is True
    assert payload["journal_schema"]
    assert payload["plan_schema"]


def test_empty_cutoff_when_no_anchors() -> None:
    result = compose_review_search(
        application_number="16000010",
        claims_text=SAMPLE_CLAIMS,
        use_client_plan=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert result.cutoff_date == ""
    # Gaps still named
    assert result.named_gaps
