"""Tests for BM25-guided legal ontology frame selection."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    BM25FrameSelector,
    DEFAULT_LEGAL_FRAME_FIXTURE,
    FrameCandidate,
    frame_ontology_feature_keys,
    frame_ontology_terms_from_feature_keys,
    frame_ontology_terms_from_triples,
    frame_ontology_terms,
    is_frame_ontology_feature_key,
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


def test_frame_ontology_terms_from_triples_support_contextual_flogic_predicates() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "condition",
                "object": "unless written notice is provided",
            },
            {
                "subject": "doc-1",
                "predicate": "exception",
                "object": "except as provided in subsection (b)",
            },
            {
                "subject": "doc-1",
                "predicate": "predicate_argument",
                "object": "actor:agency",
            },
            {
                "subject": "doc-1",
                "predicate": "predicate_token",
                "object": "authority",
            },
            {
                "subject": "doc-1",
                "predicate": "modal_operator_label",
                "object": "permission",
            },
            {
                "subject": "doc-1",
                "predicate": "modal_cue",
                "object": "may",
            },
            {
                "subject": "doc-1",
                "predicate": "source_id",
                "object": "us-code-5-552-deadbeefdeadbeef",
            },
        ]
    )

    assert terms == [
        "unless_written_notice_provided",
        "except_provided_subsection",
        "actor_agency",
        "authority",
        "permission",
        "may",
    ]


def test_frame_ontology_terms_from_feature_keys_support_selected_candidate_aliases() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "selected-frame:administrative_notice_hearing",
            "candidate-frame:criminal_penalty_enforcement",
            "frame-candidate-term:hearing rights",
            "slot:candidate-frame-term:final order",
        ]
    )

    assert terms == [
        "administrative_notice_hearing",
        "criminal_penalty_enforcement",
        "hearing_rights",
        "final_order",
    ]


def test_frame_ontology_terms_from_feature_keys_are_case_insensitive_for_prefixes() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "FRAME:administrative_notice_hearing",
            "SLOT:SELECTED_FRAME_TERM:final order",
            "FLOGIC:SELECTED-TERM:hearing rights",
        ]
    )

    assert terms == [
        "administrative_notice_hearing",
        "final_order",
        "hearing_rights",
    ]


def test_frame_ontology_terms_from_feature_keys_support_direct_ontology_predicates() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "selected_ontology_frame:administrative_notice_hearing",
            "candidate-ontology-term:agency notice",
            "slot:selected_ontology_term:final order",
            "flogic:interpreted-in-frame-term:hearing rights",
        ]
    )

    assert terms == [
        "administrative_notice_hearing",
        "agency_notice",
        "final_order",
        "hearing_rights",
    ]


def test_frame_ontology_terms_from_feature_keys_support_frame_cue_features() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "cue:frame:Frame:authority",
            "cue:frame:Frame:part of",
            "cue:deontic:O:must",
        ]
    )

    assert terms == [
        "authority",
        "part",
    ]


def test_frame_ontology_terms_from_feature_keys_ignore_unrelated_namespaces() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "cue:frame:transferred",
            "family:selected_frame:deontic",
            "slot:modal_family:frame",
            "selected_ontology_frame:administrative_notice_hearing",
        ]
    )

    assert terms == ["administrative_notice_hearing"]


def test_frame_ontology_terms_from_feature_keys_support_contextual_flogic_features() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:modal_family:conditional_normative",
            "flogic:modal_family:temporal",
            "flogic:modal_system:LTL",
            "flogic:predicate_role:temporal_scope",
            "flogic:predicate:Pub",
            "flogic:modal_operator:O",
            "slot:modal_family:frame",
        ]
    )

    assert terms == [
        "conditional_normative",
        "temporal",
        "ltl",
        "temporal_scope",
        "pub",
    ]


def test_frame_ontology_terms_from_feature_keys_support_plain_contextual_flogic_predicates() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:condition:unless written notice is provided",
            "flogic:exception:except as provided in subsection (b)",
            "flogic:predicate_argument:actor:agency",
            "flogic:predicate_token:authority",
            "flogic:modal_operator_label:permission",
            "flogic:modal_cue:may",
            "flogic:source_id:us-code-5-552-deadbeefdeadbeef",
        ]
    )

    assert terms == [
        "unless_written_notice_provided",
        "except_provided_subsection",
        "actor_agency",
        "authority",
        "permission",
        "may",
    ]


def test_frame_ontology_terms_from_feature_keys_support_typed_flogic_citation_and_scope_features() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:citation_section_component:430f",
            "flogic:citation_section_suffix:f",
            "flogic:citation_title:16",
            "flogic:statutory_scope_target:552(a)(1)",
            "flogic:predicate_argument_scope:pursuant_to_subsection_(b)",
            "flogic:predicate_token_suffix:notice",
            "flogic:condition_prefix:if",
            "flogic:exception_prefix:except",
        ]
    )

    assert terms == [
        "430f",
        "pursuant_subsection",
        "notice",
        "if",
        "except",
    ]


def test_frame_ontology_terms_from_feature_keys_support_frame_family_signals() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "family:frame:1",
            "modal-family:frame:3",
            "modal_family:frame",
            "family:deontic:2",
        ]
    )

    assert terms == ["frame"]


def test_is_frame_ontology_feature_key_distinguishes_frame_linked_signals() -> None:
    assert is_frame_ontology_feature_key("family:frame:1") is True
    assert is_frame_ontology_feature_key("modal-family:frame") is True
    assert is_frame_ontology_feature_key("cue:frame:Frame:authority") is True
    assert is_frame_ontology_feature_key(
        "slot:selected_ontology_term:final order"
    ) is True
    assert is_frame_ontology_feature_key("token:agency") is False
    assert is_frame_ontology_feature_key("cue:deontic:O:must") is False
    assert is_frame_ontology_feature_key("flogic:condition:unless written notice is provided") is True
    assert is_frame_ontology_feature_key("flogic:source_id:us-code-5-552-deadbeefdeadbeef") is False
    assert is_frame_ontology_feature_key("") is False


def test_frame_ontology_feature_keys_filter_non_frame_and_preserve_order() -> None:
    keys = frame_ontology_feature_keys(
        [
            "token:agency",
            "family:frame:1",
            "modal_family:frame:3",
            "cue:frame:Frame:authority",
            "slot:selected_frame:administrative_notice_hearing",
            "family:frame:1",
            "",
        ]
    )

    assert keys == [
        "family:frame:1",
        "modal_family:frame:3",
        "cue:frame:Frame:authority",
        "slot:selected_frame:administrative_notice_hearing",
    ]
