"""Tests for BM25-guided legal ontology frame selection."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    BM25FrameSelector,
    DEFAULT_LEGAL_FRAME_FIXTURE,
    FrameCandidate,
)


def test_bm25_selector_ranks_housing_frame_for_voucher_text() -> None:
    selector = BM25FrameSelector(DEFAULT_LEGAL_FRAME_FIXTURE)

    results = selector.rank("The tenant may request a housing voucher accommodation from the agency.")

    assert results[0].frame.frame_id == "housing_voucher_benefits"
    assert {"housing", "voucher", "agency"}.issubset(set(results[0].matched_terms))
    assert "BM25 score" in results[0].explanation


def test_bm25_selector_ranks_administrative_notice_frame() -> None:
    selector = BM25FrameSelector(DEFAULT_LEGAL_FRAME_FIXTURE)

    results = selector.rank("The agency must provide notice and a hearing before a final order.")

    assert results[0].frame.frame_id == "administrative_notice_hearing"
    assert {"agency", "notice", "hearing", "order"}.issubset(set(results[0].matched_terms))


def test_bm25_selector_supports_domain_filter() -> None:
    selector = BM25FrameSelector(DEFAULT_LEGAL_FRAME_FIXTURE)

    results = selector.rank("agency notice hearing", domain="housing")

    assert len(results) == 1
    assert results[0].frame.domain == "housing"


def test_bm25_selector_tie_breaks_by_frame_id() -> None:
    selector = BM25FrameSelector(
        [
            FrameCandidate(frame_id="b_frame", label="Shared", terms=("alpha",)),
            FrameCandidate(frame_id="a_frame", label="Shared", terms=("alpha",)),
        ]
    )

    results = selector.rank("alpha", top_k=2)

    assert [result.frame.frame_id for result in results] == ["a_frame", "b_frame"]


def test_bm25_selector_top_k_zero_returns_empty_list() -> None:
    selector = BM25FrameSelector(DEFAULT_LEGAL_FRAME_FIXTURE)

    assert selector.rank("agency notice", top_k=0) == []
