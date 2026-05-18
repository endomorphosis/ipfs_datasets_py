"""Tests for BM25-guided legal ontology frame selection."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    BM25FrameSelector,
    DEFAULT_LEGAL_FRAME_FIXTURE,
    FrameCandidate,
    frame_ontology_terms_from_feature_keys,
    frame_ontology_terms_from_triples,
    frame_ontology_terms,
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


def test_frame_ontology_terms_are_canonical_and_include_matched_terms() -> None:
    frame = FrameCandidate(
        frame_id="administrative_notice_hearing",
        label="Administrative Notice and Hearing",
        terms=("agency", "final order"),
        domain="administrative",
    )

    terms = frame_ontology_terms(frame, matched_terms=("notice", "hearing rights"))

    assert "administrative_notice_hearing" in terms
    assert "administrative" in terms
    assert "notice" in terms
    assert "hearing_rights" in terms


def test_frame_ontology_terms_filter_stopwords_and_numeric_tokens() -> None:
    frame = FrameCandidate(
        frame_id="administrative_notice_hearing",
        label="The Administrative Notice and Hearing",
        terms=("agency", "final order", "and", "42"),
        domain="general",
    )

    terms = frame_ontology_terms(
        frame,
        matched_terms=("and", "the", "42", "hearing rights"),
    )

    assert "and" not in terms
    assert "the" not in terms
    assert "42" not in terms
    assert "hearing_rights" in terms


def test_frame_ontology_terms_prioritize_matched_terms_with_term_cap() -> None:
    frame = FrameCandidate(
        frame_id="administrative_notice_hearing",
        label="Administrative notice and hearing",
        terms=("agency", "final order", "appeal deadline"),
        domain="administrative",
    )

    terms = frame_ontology_terms(
        frame,
        matched_terms=("hearing rights", "appeal"),
        max_terms=4,
    )

    assert terms == [
        "administrative_notice_hearing",
        "hearing_rights",
        "hearing",
        "rights",
    ]


def test_frame_ontology_terms_from_triples_include_frame_predicates() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "candidate_ontology_frame",
                "object": "administrative_notice_hearing",
            },
            {
                "subject": "doc-1",
                "predicate": "selected_ontology_term",
                "object": "final order",
            },
        ]
    )

    assert terms == ["administrative_notice_hearing", "final_order"]


def test_frame_ontology_terms_from_feature_keys_extract_frame_linked_values() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "frame:administrative_notice_hearing",
            "frame-candidate:housing_voucher_benefits",
            "selected-frame-term:final_order",
            "flogic:selected_ontology_frame:administrative_notice_hearing",
            "flogic:candidate_ontology_term:agency notice",
            "token:agency",
        ]
    )

    assert terms == [
        "administrative_notice_hearing",
        "housing_voucher_benefits",
        "final_order",
        "agency_notice",
    ]


def test_frame_ontology_terms_from_feature_keys_support_slot_and_legacy_aliases() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:selected_frame:administrative_notice_hearing",
            "frame_candidate:criminal_penalty_enforcement",
            "frame_term:agency notice",
            "selected_frame_term:final order",
            "flogic:selected-frame-term:hearing rights",
            "flogic:candidate-frame:housing_voucher_benefits",
        ]
    )

    assert terms == [
        "administrative_notice_hearing",
        "criminal_penalty_enforcement",
        "agency_notice",
        "final_order",
        "hearing_rights",
        "housing_voucher_benefits",
    ]


def test_frame_ontology_terms_from_triples_support_legacy_frame_predicates() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "candidate-frame",
                "object": "administrative_notice_hearing",
            },
            {
                "subject": "doc-1",
                "predicate": "selected_frame_term",
                "object": "Final Order",
            },
            {
                "subject": "doc-1",
                "predicate": "interpreted-frame-term",
                "object": "and",
            },
        ]
    )

    assert terms == ["administrative_notice_hearing", "final_order"]
