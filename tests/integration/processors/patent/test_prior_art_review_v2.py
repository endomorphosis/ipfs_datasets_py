"""Integration: source-quoted claim charts + IDS review queue (PATLAW-151).

Acceptance coverage
-------------------
* Every chart cell links claim and evidence spans or says not_found/unknown.
* Coverage gaps remain prominent.
* Reviewer changes are versioned.
* No reference enters an IDS-ready state without natural-person
  relevance/materiality review.
* No output claims an exhaustive search.
"""

from __future__ import annotations

from typing import Sequence

import pytest

from ipfs_datasets_py.processors.domains.patent.claim_chart_v2 import (
    CLAIM_CHART_V2_DISCLAIMER,
    CLAIM_CHART_V2_SCHEMA_VERSION,
    CellSpanError,
    CellStatus,
    ClaimChartCellV2,
    ClaimChartV2,
    CoverageAcknowledgementError,
    CoverageGapAcknowledgement,
    CoverageGapProminenceError,
    EvidenceHitInput,
    ExhaustiveSearchClaimError,
    LimitationChartInput,
    PassagePolarity,
    ReviewerDisposition,
    ReviewerVersionError,
    apply_reviewer_disposition,
    assert_cells_link_spans_or_status,
    assert_coverage_gaps_prominent,
    assert_no_exhaustive_search_claim,
    assert_reviewer_changes_versioned,
    attach_coverage_acknowledgement,
    build_claim_chart_v2,
    canonical_json,
    content_digest,
    make_evidence_link,
    sign_coverage_acknowledgement,
)
from ipfs_datasets_py.processors.domains.patent.ids_review_queue import (
    IDS_REVIEW_QUEUE_SCHEMA_VERSION,
    IdsAutoFileError,
    IdsCandidateState,
    IdsNaturalPersonError,
    IdsReadyGateError,
    IdsReferenceCandidate,
    MaterialityDisposition,
    RelevanceDisposition,
    assert_auto_file_blocked,
    assert_not_ids_ready_without_review,
    attach_queue_coverage_acknowledgement,
    build_ids_review_queue,
    build_prior_art_review_package,
    enqueue_flagged_from_chart,
    enqueue_from_chart_cell,
    promote_to_ids_ready,
    record_materiality_review,
    record_relevance_review,
    reject_candidate,
)
from ipfs_datasets_py.processors.domains.patent.prior_art import (
    CoverageGapKind,
    default_coverage_gaps,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import SourceSpan

SUBJECT = "subject:app-16-123456"
FILING = "2022-03-15"
PRIORITY = "2021-03-15"
SEARCH = "2024-06-01T12:00:00Z"
REVIEW_TIME = "2024-06-02T15:30:00Z"
REVIEW_TIME_2 = "2024-06-02T16:00:00Z"
REVIEW_TIME_3 = "2024-06-02T16:30:00Z"
REVIEWER = "reviewer:natasha-chen"
CID_A = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"
CID_B = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _limitations() -> tuple[LimitationChartInput, ...]:
    return (
        LimitationChartInput(
            limitation_id="lim:1:encoding",
            claim_number=1,
            text="encoding claim text for retrieval",
            claim_span=SourceSpan(start=20, end=54, unit="char"),
            claim_version_id="claim-ver:1",
            claim_version_digest="a" * 64,
        ),
        LimitationChartInput(
            limitation_id="lim:1:indexing",
            claim_number=1,
            text="indexes CPC G06F16/00 documents",
            claim_span=SourceSpan(start=70, end=102, unit="char"),
            claim_version_id="claim-ver:1",
            claim_version_digest="a" * 64,
        ),
        LimitationChartInput(
            limitation_id="lim:1:network",
            claim_number=1,
            text="applying wireless network processor analysis",
            claim_span=SourceSpan(start=110, end=154, unit="char"),
            claim_version_id="claim-ver:1",
            claim_version_digest="a" * 64,
        ),
    )


def _hit(
    doc_id: str,
    *,
    rank: int = 1,
    related: Sequence[str] | None = None,
    polarity: PassagePolarity = PassagePolarity.SUPPORTING,
    query_id: str = "q:1",
    cid: str = CID_A,
    excerpt: str = "prior art discloses encoding claim text",
) -> EvidenceHitInput:
    return EvidenceHitInput(
        document_id=doc_id,
        rank=rank,
        score=float(10 - rank),
        source_links=(
            make_evidence_link(
                source_cid=cid,
                artifact_id=f"artifact:{doc_id}",
                start=0,
                end=max(len(excerpt), 1),
            ),
        ),
        related_limitation_ids=tuple(related or ()),
        passage_excerpt=excerpt,
        query_id=query_id,
        polarity=polarity,
    )


def _build_chart(
    *,
    hits: Sequence[EvidenceHitInput] | None = None,
    limitations: Sequence[LimitationChartInput] | None = None,
) -> ClaimChartV2:
    return build_claim_chart_v2(
        subject_id=SUBJECT,
        filing_date=FILING,
        priority_date=PRIORITY,
        search_date_utc=SEARCH,
        limitations=limitations or _limitations(),
        evidence_hits=hits
        if hits is not None
        else (
            _hit(
                "US10123456B2",
                related=("lim:1:encoding",),
                excerpt="encoding claim text for hybrid retrieval",
            ),
            _hit(
                "US9000001A",
                rank=2,
                related=("lim:1:indexing",),
                polarity=PassagePolarity.CONTRADICTORY,
                excerpt="indexes CPC G06F16/00 without documents",
                cid=CID_B,
            ),
        ),
        plan_id="plan:prior-art-1",
        claim_version_id="claim-ver:1",
        claim_version_digest="a" * 64,
    )


def _round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)


def _signed_ack(chart: ClaimChartV2) -> CoverageGapAcknowledgement:
    gap_ids = tuple(g.gap_id for g in chart.coverage_gaps) + tuple(
        g.gap_id for g in chart.named_coverage_gaps
    )
    ack = CoverageGapAcknowledgement(
        acknowledgement_id=f"ack:{chart.chart_id}",
        subject_id=chart.subject_id,
        chart_id=chart.chart_id,
        acknowledger_id=REVIEWER,
        acknowledged_at_utc=REVIEW_TIME,
        searched_sources=("us_patents", "local_public_snapshot"),
        gap_ids_acknowledged=gap_ids,
        acknowledges_gaps_remain_visible=True,
        acknowledges_search_not_exhaustive=True,
        is_natural_person=True,
    )
    return sign_coverage_acknowledgement(
        ack, signature=f"sig:{REVIEWER}:{chart.chart_id}"
    )


# ---------------------------------------------------------------------------
# Cell span contract: claim + evidence OR not_found/unknown
# ---------------------------------------------------------------------------


def test_every_cell_links_claim_and_evidence_spans_or_status() -> None:
    chart = _build_chart()
    assert chart.cells
    assert_cells_link_spans_or_status(chart)

    found = chart.found_cells()
    assert found
    for cell in found:
        assert cell.status is CellStatus.FOUND
        assert cell.claim_span is not None
        assert cell.claim_span.end > cell.claim_span.start
        assert cell.evidence_links
        assert all(link.source_cid and link.span is not None for link in cell.evidence_links)

    # Unmatched limitation "lim:1:network" must surface as not_found.
    not_found = chart.not_found_cells()
    assert any(c.limitation_id == "lim:1:network" for c in not_found)
    for cell in not_found:
        assert cell.status is CellStatus.NOT_FOUND
        assert cell.claim_span is not None  # claim span still bound


def test_found_cell_without_evidence_raises() -> None:
    with pytest.raises(CellSpanError, match="evidence"):
        ClaimChartCellV2(
            cell_id="cell:bad",
            limitation_id="lim:1:encoding",
            claim_number=1,
            claim_span=SourceSpan(start=0, end=10),
            status=CellStatus.FOUND,
            document_id="US10123456B2",
            evidence_links=(),
        )


def test_unknown_cell_allowed_without_evidence() -> None:
    cell = ClaimChartCellV2(
        cell_id="cell:unknown",
        limitation_id="lim:1:encoding",
        claim_number=1,
        claim_span=SourceSpan(start=0, end=10),
        status=CellStatus.UNKNOWN,
    )
    assert cell.status is CellStatus.UNKNOWN
    chart = build_claim_chart_v2(
        subject_id=SUBJECT,
        filing_date=FILING,
        priority_date=PRIORITY,
        search_date_utc=SEARCH,
        limitations=_limitations()[:1],
        evidence_hits=(),
        emit_not_found_for_unmatched=False,
    )
    # Manually inject unknown via disposition path after building a not_found.
    chart = _build_chart(hits=())
    nf = chart.not_found_cells()[0]
    chart2 = apply_reviewer_disposition(
        chart,
        cell_id=nf.cell_id,
        reviewer_id=REVIEWER,
        disposition=ReviewerDisposition.MARK_UNKNOWN,
        changed_at_utc=REVIEW_TIME,
        notes="insufficient corpus to decide",
    )
    updated = next(c for c in chart2.cells if c.cell_id == nf.cell_id)
    assert updated.status is CellStatus.UNKNOWN
    assert_cells_link_spans_or_status(chart2)


def test_supporting_and_contradictory_passages_recorded() -> None:
    chart = _build_chart()
    supporting_cells = [
        c for c in chart.found_cells() if c.supporting_passages
    ]
    contradictory_cells = [
        c for c in chart.found_cells() if c.contradictory_passages
    ]
    assert supporting_cells
    assert contradictory_cells
    for cell in supporting_cells:
        for p in cell.supporting_passages:
            assert p.quoted_text
            assert p.source_links
            assert p.polarity is PassagePolarity.SUPPORTING
    for cell in contradictory_cells:
        for p in cell.contradictory_passages:
            assert p.polarity is PassagePolarity.CONTRADICTORY


# ---------------------------------------------------------------------------
# Coverage gaps remain prominent
# ---------------------------------------------------------------------------


def test_coverage_gaps_remain_prominent() -> None:
    chart = _build_chart()
    assert chart.coverage_gaps_prominent is True
    assert_coverage_gaps_prominent(chart)
    kinds = {g.kind for g in chart.coverage_gaps}
    assert CoverageGapKind.FOREIGN_PATENT in kinds
    assert CoverageGapKind.NPL in kinds
    for gap in chart.coverage_gaps:
        assert gap.remains_visible is True


def test_chart_rejects_missing_coverage_gaps() -> None:
    with pytest.raises(CoverageGapProminenceError):
        ClaimChartV2(
            schema_version=CLAIM_CHART_V2_SCHEMA_VERSION,
            chart_id="chart:no-gaps",
            subject_id=SUBJECT,
            filing_date=FILING,
            priority_date=PRIORITY,
            search_date_utc=SEARCH,
            cells=(
                ClaimChartCellV2(
                    cell_id="cell:x",
                    limitation_id="lim:1:encoding",
                    claim_number=1,
                    claim_span=SourceSpan(start=0, end=5),
                    status=CellStatus.NOT_FOUND,
                ),
            ),
            coverage_gaps=(),  # missing foreign + NPL
            coverage_gaps_prominent=True,
        )


def test_claims_exhaustive_search_rejected() -> None:
    chart = _build_chart()
    payload = chart.to_dict()
    assert payload["claims_exhaustive_search"] is False
    assert_no_exhaustive_search_claim(payload)

    with pytest.raises(ExhaustiveSearchClaimError):
        ClaimChartV2(
            schema_version=CLAIM_CHART_V2_SCHEMA_VERSION,
            chart_id="chart:exhaustive",
            subject_id=SUBJECT,
            filing_date=FILING,
            priority_date=PRIORITY,
            search_date_utc=SEARCH,
            cells=chart.cells,
            coverage_gaps=default_coverage_gaps(),
            claims_exhaustive_search=True,
        )

    with pytest.raises(ExhaustiveSearchClaimError):
        assert_no_exhaustive_search_claim(
            {**payload, "notes": "This is an exhaustive search of all prior art."}
        )


# ---------------------------------------------------------------------------
# Reviewer changes are versioned
# ---------------------------------------------------------------------------


def test_reviewer_changes_are_versioned() -> None:
    chart = _build_chart()
    found = chart.found_cells()[0]

    chart = apply_reviewer_disposition(
        chart,
        cell_id=found.cell_id,
        reviewer_id=REVIEWER,
        disposition=ReviewerDisposition.ACCEPTED,
        changed_at_utc=REVIEW_TIME,
        notes="maps to claim limitation",
    )
    cell_v1 = next(c for c in chart.cells if c.cell_id == found.cell_id)
    assert cell_v1.disposition is ReviewerDisposition.ACCEPTED
    assert len(cell_v1.reviewer_history) == 1
    assert cell_v1.reviewer_history[0].version == 1
    assert cell_v1.reviewer_history[0].previous_version_digest is None
    assert cell_v1.reviewer_history[0].content_digest
    assert cell_v1.reviewer_history[0].is_natural_person is True

    chart = apply_reviewer_disposition(
        chart,
        cell_id=found.cell_id,
        reviewer_id=REVIEWER,
        disposition=ReviewerDisposition.FLAG_FOR_IDS,
        changed_at_utc=REVIEW_TIME_2,
        notes="possible IDS candidate",
    )
    cell_v2 = next(c for c in chart.cells if c.cell_id == found.cell_id)
    assert len(cell_v2.reviewer_history) == 2
    assert cell_v2.reviewer_history[1].version == 2
    assert (
        cell_v2.reviewer_history[1].previous_version_digest
        == cell_v2.reviewer_history[0].content_digest
    )
    assert cell_v2.disposition is ReviewerDisposition.FLAG_FOR_IDS
    assert_reviewer_changes_versioned(chart)
    _round_trip(chart)


def test_non_natural_person_reviewer_change_rejected() -> None:
    chart = _build_chart()
    cell = chart.found_cells()[0]
    with pytest.raises(ReviewerVersionError, match="natural person"):
        apply_reviewer_disposition(
            chart,
            cell_id=cell.cell_id,
            reviewer_id="bot:auto-reviewer",
            disposition=ReviewerDisposition.ACCEPTED,
            changed_at_utc=REVIEW_TIME,
            is_natural_person=False,
        )


# ---------------------------------------------------------------------------
# Coverage acknowledgement (signed searched/gap)
# ---------------------------------------------------------------------------


def test_signed_coverage_acknowledgement_required_fields() -> None:
    chart = _build_chart()
    ack = _signed_ack(chart)
    assert ack.is_signed
    assert ack.acknowledges_search_not_exhaustive is True
    assert ack.acknowledges_gaps_remain_visible is True
    chart2 = attach_coverage_acknowledgement(chart, ack)
    assert chart2.coverage_acknowledgement is not None
    assert chart2.coverage_acknowledgement.signature
    _round_trip(chart2)


def test_unsigned_acknowledgement_cannot_attach() -> None:
    chart = _build_chart()
    gap_ids = tuple(g.gap_id for g in chart.coverage_gaps)
    ack = CoverageGapAcknowledgement(
        acknowledgement_id="ack:unsigned",
        subject_id=SUBJECT,
        chart_id=chart.chart_id,
        acknowledger_id=REVIEWER,
        acknowledged_at_utc=REVIEW_TIME,
        searched_sources=("us_patents",),
        gap_ids_acknowledged=gap_ids,
    )
    assert not ack.is_signed
    with pytest.raises(CoverageAcknowledgementError, match="signed"):
        attach_coverage_acknowledgement(chart, ack)


def test_acknowledgement_cannot_claim_exhaustive() -> None:
    chart = _build_chart()
    gap_ids = tuple(g.gap_id for g in chart.coverage_gaps)
    with pytest.raises(CoverageAcknowledgementError, match="not_exhaustive"):
        CoverageGapAcknowledgement(
            acknowledgement_id="ack:bad",
            subject_id=SUBJECT,
            chart_id=chart.chart_id,
            acknowledger_id=REVIEWER,
            acknowledged_at_utc=REVIEW_TIME,
            searched_sources=("us_patents",),
            gap_ids_acknowledged=gap_ids,
            acknowledges_search_not_exhaustive=False,
        )


# ---------------------------------------------------------------------------
# IDS review queue: natural-person relevance + materiality gate
# ---------------------------------------------------------------------------


def test_ids_ready_requires_natural_person_relevance_and_materiality() -> None:
    chart = _build_chart()
    found = chart.found_cells()[0]
    chart = apply_reviewer_disposition(
        chart,
        cell_id=found.cell_id,
        reviewer_id=REVIEWER,
        disposition=ReviewerDisposition.FLAG_FOR_IDS,
        changed_at_utc=REVIEW_TIME,
    )
    queue = build_ids_review_queue(
        subject_id=SUBJECT, chart_id=chart.chart_id
    )
    queue = enqueue_flagged_from_chart(
        queue, chart, reviewer_id=REVIEWER, acted_at_utc=REVIEW_TIME
    )
    assert len(queue.candidates) >= 1
    cand = queue.candidates[0]
    assert cand.is_ids_ready is False
    assert cand.state is IdsCandidateState.CANDIDATE
    assert cand.auto_file_blocked is True

    # Cannot promote without reviews.
    with pytest.raises(IdsReadyGateError):
        promote_to_ids_ready(
            queue,
            candidate_id=cand.candidate_id,
            reviewer_id=REVIEWER,
            acted_at_utc=REVIEW_TIME_2,
        )

    # Relevance alone is insufficient.
    queue = record_relevance_review(
        queue,
        candidate_id=cand.candidate_id,
        reviewer_id=REVIEWER,
        disposition=RelevanceDisposition.RELEVANT,
        acted_at_utc=REVIEW_TIME_2,
        notes="appears relevant to claim 1",
    )
    with pytest.raises(IdsReadyGateError, match="materiality"):
        promote_to_ids_ready(
            queue,
            candidate_id=cand.candidate_id,
            reviewer_id=REVIEWER,
            acted_at_utc=REVIEW_TIME_3,
        )

    # Materiality not_material still cannot promote to IDS-ready.
    queue_nm = record_materiality_review(
        queue,
        candidate_id=cand.candidate_id,
        reviewer_id=REVIEWER,
        disposition=MaterialityDisposition.NOT_MATERIAL,
        acted_at_utc=REVIEW_TIME_3,
    )
    with pytest.raises(IdsReadyGateError, match="material"):
        promote_to_ids_ready(
            queue_nm,
            candidate_id=cand.candidate_id,
            reviewer_id=REVIEWER,
            acted_at_utc=REVIEW_TIME_3,
        )

    # Affirmative dual review allows promotion.
    queue = record_materiality_review(
        queue,
        candidate_id=cand.candidate_id,
        reviewer_id=REVIEWER,
        disposition=MaterialityDisposition.MATERIAL,
        acted_at_utc=REVIEW_TIME_3,
        notes="material to pending claims",
    )
    queue = promote_to_ids_ready(
        queue,
        candidate_id=cand.candidate_id,
        reviewer_id=REVIEWER,
        acted_at_utc=REVIEW_TIME_3,
    )
    ready = queue.ids_ready_candidates()
    assert len(ready) == 1
    assert ready[0].is_ids_ready is True
    assert ready[0].state is IdsCandidateState.IDS_READY
    assert ready[0].relevance is RelevanceDisposition.RELEVANT
    assert ready[0].materiality is MaterialityDisposition.MATERIAL
    assert ready[0].relevance_reviewer_id == REVIEWER
    assert ready[0].materiality_reviewer_id == REVIEWER
    # Versioned history: enqueue + relevance + materiality + promote
    assert len(ready[0].review_history) >= 4
    versions = [a.version for a in ready[0].review_history]
    assert versions == sorted(versions)
    assert_not_ids_ready_without_review(queue)
    assert_auto_file_blocked(queue)
    _round_trip(queue)


def test_cannot_construct_ids_ready_without_review_history() -> None:
    with pytest.raises(IdsReadyGateError):
        IdsReferenceCandidate(
            candidate_id="ids-cand:bare",
            document_id="US10123456B2",
            subject_id=SUBJECT,
            state=IdsCandidateState.IDS_READY,
            relevance=RelevanceDisposition.RELEVANT,
            materiality=MaterialityDisposition.MATERIAL,
            relevance_reviewer_id=REVIEWER,
            materiality_reviewer_id=REVIEWER,
            relevance_reviewed_at_utc=REVIEW_TIME,
            materiality_reviewed_at_utc=REVIEW_TIME,
            review_history=(),  # missing versioned actions
            is_ids_ready=True,
        )


def test_non_natural_person_cannot_review_or_promote() -> None:
    chart = _build_chart()
    cell = chart.found_cells()[0]
    queue = build_ids_review_queue(subject_id=SUBJECT, chart_id=chart.chart_id)
    queue = enqueue_from_chart_cell(
        queue, cell, reviewer_id=REVIEWER, acted_at_utc=REVIEW_TIME
    )
    cand_id = queue.candidates[0].candidate_id
    with pytest.raises(IdsNaturalPersonError):
        record_relevance_review(
            queue,
            candidate_id=cand_id,
            reviewer_id="bot:classifier",
            disposition=RelevanceDisposition.RELEVANT,
            acted_at_utc=REVIEW_TIME_2,
            is_natural_person=False,
        )
    with pytest.raises(IdsNaturalPersonError):
        record_materiality_review(
            queue,
            candidate_id=cand_id,
            reviewer_id="bot:classifier",
            disposition=MaterialityDisposition.MATERIAL,
            acted_at_utc=REVIEW_TIME_2,
            is_natural_person=False,
        )


def test_reject_candidate_never_ids_ready() -> None:
    chart = _build_chart()
    cell = chart.found_cells()[0]
    queue = build_ids_review_queue(subject_id=SUBJECT)
    queue = enqueue_from_chart_cell(
        queue, cell, reviewer_id=REVIEWER, acted_at_utc=REVIEW_TIME
    )
    cand_id = queue.candidates[0].candidate_id
    queue = reject_candidate(
        queue,
        candidate_id=cand_id,
        reviewer_id=REVIEWER,
        acted_at_utc=REVIEW_TIME_2,
        notes="cumulative of already cited art",
    )
    cand = queue.candidate(cand_id)
    assert cand.state is IdsCandidateState.REJECTED
    assert cand.is_ids_ready is False


def test_queue_blocks_auto_file_and_exhaustive_claim() -> None:
    queue = build_ids_review_queue(subject_id=SUBJECT)
    assert queue.auto_file_blocked is True
    assert queue.claims_exhaustive_search is False
    assert_auto_file_blocked(queue)
    assert_no_exhaustive_search_claim(queue.to_dict())

    with pytest.raises(IdsAutoFileError):
        # Constructing with auto_file_blocked=False must fail.
        from ipfs_datasets_py.processors.domains.patent.ids_review_queue import (
            IdsReviewQueue,
        )

        IdsReviewQueue(
            schema_version=IDS_REVIEW_QUEUE_SCHEMA_VERSION,
            queue_id="ids-queue:bad",
            subject_id=SUBJECT,
            candidates=(),
            auto_file_blocked=False,
        )


# ---------------------------------------------------------------------------
# End-to-end prior-art review package
# ---------------------------------------------------------------------------


def test_prior_art_review_package_end_to_end() -> None:
    chart = _build_chart()
    # Versioned reviewer dispositions on found cells.
    for cell in chart.found_cells():
        chart = apply_reviewer_disposition(
            chart,
            cell_id=cell.cell_id,
            reviewer_id=REVIEWER,
            disposition=ReviewerDisposition.FLAG_FOR_IDS,
            changed_at_utc=REVIEW_TIME,
        )

    ack = _signed_ack(chart)
    chart = attach_coverage_acknowledgement(chart, ack)

    queue = build_ids_review_queue(subject_id=SUBJECT, chart_id=chart.chart_id)
    queue = attach_queue_coverage_acknowledgement(queue, ack)
    queue = enqueue_flagged_from_chart(
        queue, chart, reviewer_id=REVIEWER, acted_at_utc=REVIEW_TIME
    )
    assert queue.candidates

    for cand in list(queue.candidates):
        queue = record_relevance_review(
            queue,
            candidate_id=cand.candidate_id,
            reviewer_id=REVIEWER,
            disposition=RelevanceDisposition.RELEVANT,
            acted_at_utc=REVIEW_TIME_2,
        )
        queue = record_materiality_review(
            queue,
            candidate_id=cand.candidate_id,
            reviewer_id=REVIEWER,
            disposition=MaterialityDisposition.MATERIAL,
            acted_at_utc=REVIEW_TIME_3,
        )
        queue = promote_to_ids_ready(
            queue,
            candidate_id=cand.candidate_id,
            reviewer_id=REVIEWER,
            acted_at_utc=REVIEW_TIME_3,
            require_coverage_acknowledgement=True,
        )

    package = build_prior_art_review_package(chart=chart, queue=queue)
    assert package["claims_exhaustive_search"] is False
    assert package["coverage_acknowledgement"]["signature"]
    assert package["chart"]["coverage_gaps_prominent"] is True
    assert package["ids_queue"]["auto_file_blocked"] is True
    assert any(c["is_ids_ready"] for c in package["ids_queue"]["candidates"])
    # Every chart cell still satisfies the span/status contract.
    restored = ClaimChartV2.from_dict(package["chart"])
    assert_cells_link_spans_or_status(restored)
    assert_coverage_gaps_prominent(restored)
    assert_reviewer_changes_versioned(restored)
    assert_no_exhaustive_search_claim(package)
    # Deterministic serialization
    assert content_digest(package) == content_digest(
        build_prior_art_review_package(chart=chart, queue=queue)
    )


def test_disclaimer_denies_exhaustive_search_and_patentability() -> None:
    lower = CLAIM_CHART_V2_DISCLAIMER.lower()
    assert "not an exhaustive search" in lower
    assert "patentability" in lower
    assert "ids" in lower


def test_chart_and_queue_schema_pins() -> None:
    chart = _build_chart()
    assert chart.schema_version == CLAIM_CHART_V2_SCHEMA_VERSION
    queue = build_ids_review_queue(subject_id=SUBJECT)
    assert queue.schema_version == IDS_REVIEW_QUEUE_SCHEMA_VERSION
