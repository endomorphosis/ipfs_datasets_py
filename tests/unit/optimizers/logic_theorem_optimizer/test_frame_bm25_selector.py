"""Tests for BM25-guided legal ontology frame selection."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    BM25FrameSelector,
    DEFAULT_LEGAL_FRAME_FIXTURE,
    FrameCandidate,
    frame_ontology_contextualized_terms,
    frame_ontology_feature_value,
    frame_ontology_feature_keys,
    frame_ontology_feature_keys_from_values,
    frame_ontology_high_signal_terms,
    frame_ontology_terms_from_feature_keys,
    frame_ontology_terms_from_triples,
    frame_ontology_terms,
    is_high_signal_frame_ontology_term,
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
        "5_552",
    ]


def test_frame_ontology_terms_from_triples_preserve_modal_cue_stopwords_for_audits() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "modal_cue",
                "object": "by",
            },
            {
                "subject": "doc-1",
                "predicate": "modal_cue",
                "object": "shall",
            },
        ]
    )

    assert terms == [
        "by",
        "shall",
    ]


def test_frame_ontology_terms_from_triples_support_procedural_keyword_predicates() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "procedural_keyword",
                "object": "review",
            },
            {
                "subject": "doc-1",
                "predicate": "procedural_keyword_stem",
                "object": "adjudicatory_review",
            },
            {
                "subject": "doc-1",
                "predicate": "procedural_keyword_token_count",
                "object": "2",
            },
        ]
    )

    assert terms == [
        "review",
        "adjudicatory_review",
    ]


def test_frame_ontology_terms_from_triples_support_predicate_alnum_segment_predicates() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "predicate_alnum_segment",
                "object": "391",
            },
            {
                "subject": "doc-1",
                "predicate": "predicate_alnum_segment_positioned",
                "object": "1:391",
            },
            {
                "subject": "doc-1",
                "predicate": "predicate_alnum_segment",
                "object": "a",
            },
            {
                "subject": "doc-1",
                "predicate": "predicate_alnum_segment_positioned",
                "object": "2:a",
            },
            {
                "subject": "doc-1",
                "predicate": "predicate_alnum_segment_kind",
                "object": "alpha",
            },
        ]
    )

    assert terms == [
        "391",
        "a",
    ]


def test_frame_ontology_terms_from_triples_preserve_condition_stopword_segments_for_audits() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "condition_alnum_segment",
                "object": "if",
            },
            {
                "subject": "doc-1",
                "predicate": "condition_alnum_segment",
                "object": "of",
            },
            {
                "subject": "doc-1",
                "predicate": "condition_alnum_segment",
                "object": "the",
            },
        ]
    )

    assert terms == [
        "if",
        "of",
        "the",
    ]


def test_frame_ontology_terms_from_triples_keep_single_letter_modal_symbols() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "modal_operator",
                "object": "P",
            },
            {
                "subject": "doc-1",
                "predicate": "modal_operator",
                "object": "O|",
            },
            {
                "subject": "doc-1",
                "predicate": "modal_system",
                "object": "D",
            },
            {
                "subject": "doc-1",
                "predicate": "modal_system",
                "object": "LTL",
            },
        ]
    )

    assert terms == [
        "p",
        "o",
        "d",
        "ltl",
    ]


def test_frame_ontology_terms_from_triples_support_fallback_surface_text_predicates() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "fallback_surface_text",
                "object": "Housing voucher benefits and utility allowances",
            },
            {
                "subject": "doc-1",
                "predicate": "fallback_surface_text_token_suffix",
                "object": "allowances",
            },
        ]
    )

    assert terms == [
        "housing_voucher_benefits_utility_allowances",
        "allowances",
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


def test_frame_ontology_feature_value_extracts_normalized_raw_values() -> None:
    assert (
        frame_ontology_feature_value("selected-frame-term:42 U.S.C. 6932.")
        == "42 U.S.C. 6932."
    )
    assert (
        frame_ontology_feature_value(
            "flogic:source_id:us-code-5-552-deadbeefdeadbeef"
        )
        == "5 552"
    )
    assert (
        frame_ontology_feature_value(
            "flogic:belongs_to_document:us-code-46-30525.-99a6422ab828fa0c"
        )
        == "46 30525"
    )
    assert frame_ontology_feature_value("token:agency") == ""


def test_frame_ontology_terms_from_feature_keys_preserve_tail_frame_features_for_dense_inputs() -> None:
    labels = [
        f"{left}{right}"
        for left in "abcdefghijklmnopqrstuvwxyz"
        for right in "abcdefghijklmnopqrstuvwxyz"
    ]
    dense_features = [
        f"flogic:selected_ontology_term:term {label}"
        for label in labels[:140]
    ]
    terms = frame_ontology_terms_from_feature_keys(
        dense_features
        + [
            "cue:frame:transferred",
            "family:selected_frame:deontic",
        ]
    )

    assert "transferred" in terms
    assert "deontic" in terms
    assert "term_fj" in terms
    assert len(terms) > 64


def test_frame_ontology_terms_from_feature_keys_prioritize_direct_terms_when_term_cap_is_exceeded() -> None:
    contextual_features = [
        f"flogic:citation_section_component:{1000 + index}"
        for index in range(12)
    ]
    terms = frame_ontology_terms_from_feature_keys(
        contextual_features
        + ["selected-frame-term:final order"],
        max_terms=4,
    )

    assert terms == [
        "final_order",
        "1000",
        "1001",
        "1002",
    ]


def test_frame_ontology_terms_from_feature_keys_deprioritize_structural_contextual_terms_when_term_cap_is_exceeded() -> None:
    structural_features = [
        f"flogic:citation_section_component_count:{index}"
        for index in range(12)
    ]
    terms = frame_ontology_terms_from_feature_keys(
        structural_features
        + [
            "flogic:citation_section_component_kind:alphanumeric",
            "flogic:citation_section_shape:NA-NA",
            "flogic:status_keyword:transferred",
            "flogic:statement_hint:purpose_clause",
        ],
        max_terms=3,
    )

    assert terms == [
        "transferred",
        "purpose_clause",
        "alphanumeric",
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
            "cue:frame:Frame:is a",
            "cue:frame:Frame:part of",
            "cue:deontic:O:must",
        ]
    )

    assert terms == [
        "authority",
        "isa",
        "part",
    ]


def test_frame_ontology_terms_from_feature_keys_support_legal_ir_view_features() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "legal-ir-view:modal.frame_logic",
            "legal_ir_view:deontic.ir",
            "token:agency",
        ]
    )

    assert terms == [
        "modal_frame_logic",
        "deontic_ir",
    ]


def test_frame_ontology_terms_from_feature_keys_extract_predicate_argument_role_shape_and_role_pairs() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "predicate-argument:source-action-role:appropriations:clause",
            "predicate-argument:source-object-family:repealed:frame",
            "predicate-argument:role-shape:conditional_normative:clause:c1:e1",
        ]
    )

    assert "source_action_role_appropriations_clause" in terms
    assert "appropriations" in terms
    assert "appropriations_clause" in terms
    assert "source_object_family_repealed_frame" in terms
    assert "repealed" in terms
    assert "repealed_frame" in terms
    assert "role_shape_conditional_normative_clause_c1_e1" in terms
    assert "conditional_normative" in terms
    assert "conditional_normative_clause" in terms


def test_frame_ontology_terms_from_feature_keys_support_legacy_frame_cues() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "cue:frame:transferred",
            "cue:frame:is a",
            "cue:frame:",
        ]
    )

    assert terms == [
        "transferred",
        "isa",
    ]


def test_frame_ontology_terms_from_feature_keys_support_slot_contextual_features() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "cue:frame:transferred",
            "family:selected_frame:deontic",
            "slot:modal_family:frame",
            "slot:condition:unless written notice is provided",
            "slot:citation_section_number:5406",
            "slot:source_id:us-code-5-552-deadbeefdeadbeef",
            "selected_ontology_frame:administrative_notice_hearing",
        ]
    )

    assert terms == [
        "transferred",
        "deontic",
        "frame",
        "unless_written_notice_provided",
        "5406",
        "5_552",
        "administrative_notice_hearing",
    ]


def test_frame_ontology_terms_from_feature_keys_keep_single_letter_modal_symbols() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:modal_operator:P",
            "flogic:modal_operator:O|",
            "flogic:modal_system:D",
            "slot:modal_system:LTL",
        ]
    )

    assert terms == [
        "p",
        "o",
        "d",
        "ltl",
    ]


def test_frame_ontology_terms_from_feature_keys_support_frame_semantic_slot_features() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:operator:framed_as",
            "slot:role:frame",
            "slot:operator:obligatory",
            "slot:role:clause",
        ]
    )

    assert terms == [
        "frame",
    ]


def test_frame_ontology_terms_from_feature_keys_support_selected_frame_slot_derivatives() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:selected_frame:administrative_notice_hearing",
            "slot:selected_frame_stem:administrative_notice_hearing",
            "slot:selected_frame_token:administrative",
            "slot:selected_frame_token_count:3",
        ]
    )

    assert terms == [
        "administrative_notice_hearing",
        "administrative",
    ]


def test_frame_ontology_terms_from_feature_keys_support_ranked_frame_candidate_slots() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:frame_candidate_ranked:1:criminal_penalty_enforcement",
            "slot:frame_candidate_token:penalty",
            "slot:frame_candidate_rank:1",
        ]
    )

    assert terms == [
        "criminal_penalty_enforcement",
        "penalty",
    ]


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
        "o",
        "frame",
    ]


def test_frame_ontology_terms_from_feature_keys_support_modal_family_count_features() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:modal_family_count:deontic:2",
            "flogic:modal_family_count_ranked:1:frame:3",
            "flogic:modal_family_count_family:temporal",
            "flogic:modal_family_count_dynamic:4",
            "flogic:modal_family_count_value:9",
        ]
    )

    assert terms == [
        "deontic",
        "frame",
        "temporal",
        "dynamic",
    ]


def test_frame_ontology_terms_from_triples_support_modal_family_count_features() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "modal_family_count",
                "object": "deontic:2",
            },
            {
                "subject": "doc-1",
                "predicate": "modal_family_count_ranked",
                "object": "1:frame:3",
            },
            {
                "subject": "doc-1",
                "predicate": "modal_family_count_family",
                "object": "temporal",
            },
            {
                "subject": "doc-1",
                "predicate": "modal_family_count_dynamic",
                "object": "4",
            },
            {
                "subject": "doc-1",
                "predicate": "modal_family_count_value",
                "object": "9",
            },
        ]
    )

    assert terms == [
        "deontic",
        "frame",
        "temporal",
        "dynamic",
    ]


def test_frame_ontology_terms_from_feature_keys_support_selected_frame_modal_family_count_features() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:selected_frame_modal_family:deontic",
            "flogic:selected_frame_modal_family_ranked:1:frame",
            "flogic:selected_frame_modal_family_count:temporal:2",
            "flogic:selected_frame_modal_family_count_ranked:2:dynamic:3",
            "flogic:selected_frame_modal_family_count_value:9",
            "flogic:selected_frame_modal_family_epistemic:4",
        ]
    )

    assert terms == [
        "deontic",
        "frame",
        "temporal",
        "dynamic",
        "epistemic",
    ]


def test_frame_ontology_terms_from_triples_support_selected_frame_modal_family_count_features() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "selected_frame_modal_family",
                "object": "deontic",
            },
            {
                "subject": "doc-1",
                "predicate": "selected_frame_modal_family_ranked",
                "object": "1:frame",
            },
            {
                "subject": "doc-1",
                "predicate": "selected_frame_modal_family_count",
                "object": "temporal:2",
            },
            {
                "subject": "doc-1",
                "predicate": "selected_frame_modal_family_count_ranked",
                "object": "2:dynamic:3",
            },
            {
                "subject": "doc-1",
                "predicate": "selected_frame_modal_family_count_value",
                "object": "9",
            },
            {
                "subject": "doc-1",
                "predicate": "selected_frame_modal_family_epistemic",
                "object": "4",
            },
        ]
    )

    assert terms == [
        "deontic",
        "frame",
        "temporal",
        "dynamic",
        "epistemic",
    ]


def test_frame_ontology_terms_from_triples_preserve_tail_contextual_terms_for_dense_inputs() -> None:
    labels = [
        f"{left}{right}"
        for left in "abcdefghijklmnopqrstuvwxyz"
        for right in "abcdefghijklmnopqrstuvwxyz"
    ]
    dense_triples = [
        {
            "subject": "doc-1",
            "predicate": "selected_ontology_term",
            "object": f"term {label}",
        }
        for label in labels[:140]
    ]
    dense_triples.append(
        {
            "subject": "doc-1",
            "predicate": "condition",
            "object": "unless written notice is provided",
        }
    )

    terms = frame_ontology_terms_from_triples(dense_triples)

    assert "unless_written_notice_provided" in terms
    assert "term_fj" in terms
    assert len(terms) > 64


def test_frame_ontology_terms_from_triples_prioritize_direct_terms_when_term_cap_is_exceeded() -> None:
    contextual_triples = [
        {
            "subject": "doc-1",
            "predicate": "citation_section_component",
            "object": str(1000 + index),
        }
        for index in range(12)
    ]
    terms = frame_ontology_terms_from_triples(
        contextual_triples
        + [
            {
                "subject": "doc-1",
                "predicate": "selected_ontology_term",
                "object": "final order",
            }
        ],
        max_terms=4,
    )

    assert terms == [
        "final_order",
        "1000",
        "1001",
        "1002",
    ]


def test_frame_ontology_terms_from_triples_deprioritize_structural_contextual_terms_when_term_cap_is_exceeded() -> None:
    structural_triples = [
        {
            "subject": "doc-1",
            "predicate": "citation_section_component_count",
            "object": str(index),
        }
        for index in range(12)
    ]
    terms = frame_ontology_terms_from_triples(
        structural_triples
        + [
            {
                "subject": "doc-1",
                "predicate": "citation_section_component_kind",
                "object": "alphanumeric",
            },
            {
                "subject": "doc-1",
                "predicate": "citation_section_shape",
                "object": "NA-NA",
            },
            {
                "subject": "doc-1",
                "predicate": "status_keyword",
                "object": "transferred",
            },
            {
                "subject": "doc-1",
                "predicate": "statement_hint",
                "object": "purpose_clause",
            },
        ],
        max_terms=3,
    )

    assert terms == [
        "transferred",
        "purpose_clause",
        "alphanumeric",
    ]


def test_frame_ontology_terms_from_triples_support_source_id_citation_canonical_terms() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "source_id_citation_canonical",
                "object": "50 U.S.C. 2675",
            },
            {
                "subject": "doc-1",
                "predicate": "source_id_digest",
                "object": "8dbd5e2eb6c364c8",
            },
        ]
    )

    assert terms == ["50_2675"]


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
        "5_552",
    ]


def test_frame_ontology_terms_from_feature_keys_preserve_modal_cue_stopwords_for_audits() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:modal_cue:by",
            "flogic:modal_cue:shall",
            "token:agency",
        ]
    )

    assert terms == [
        "by",
        "shall",
    ]


def test_frame_ontology_terms_from_feature_keys_support_procedural_keyword_features() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:procedural_keyword:review",
            "slot:procedural_keyword_stem:adjudicatory_review",
            "slot:procedural_keyword_token_count:2",
        ]
    )

    assert terms == [
        "review",
        "adjudicatory_review",
    ]


def test_frame_ontology_terms_from_feature_keys_support_predicate_alnum_segment_features() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:predicate_alnum_segment:1790",
            "flogic:predicate_alnum_segment_positioned:1:1790",
            "slot:predicate_alnum_segment:b",
            "slot:predicate_alnum_segment_positioned:2:b",
            "slot:predicate_alnum_segment_kind:alpha",
        ]
    )

    assert terms == [
        "1790",
        "b",
    ]


def test_frame_ontology_terms_from_feature_keys_preserve_condition_stopword_segments_for_audits() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:condition_alnum_segment:if",
            "flogic:condition_alnum_segment:of",
            "flogic:condition_alnum_segment:the",
        ]
    )

    assert terms == [
        "if",
        "of",
        "the",
    ]


def test_frame_ontology_terms_from_feature_keys_preserve_condition_scope_token_stopwords_for_audits() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:condition_token:is",
            "flogic:condition_scope_token:an",
            "slot:condition_scope_token:to",
            "slot:exception_scope_token:with",
        ]
    )

    assert terms == [
        "is",
        "an",
        "to",
        "with",
    ]
    assert frame_ontology_high_signal_terms(terms) == []


def test_frame_ontology_terms_from_triples_keep_single_letter_conditional_modal_operators() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "condition_modal_operator",
                "object": "P",
            },
            {
                "subject": "doc-1",
                "predicate": "exception_modal_operator",
                "object": "O|",
            },
        ]
    )

    assert terms == [
        "p",
        "o",
    ]


def test_frame_ontology_terms_from_feature_keys_keep_single_letter_conditional_modal_operators() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:condition_modal_operator:P",
            "slot:exception_modal_operator:O|",
        ]
    )

    assert terms == [
        "p",
        "o",
    ]


def test_frame_ontology_terms_from_feature_keys_preserve_conditional_normative_relation_terms() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:condition_conditional_normative:O|:subject_to",
        ]
    )

    assert terms == [
        "subject_to",
    ]


def test_frame_ontology_contextualized_terms_explicitly_contextualize_distance_profile_and_terminal_bucket_values() -> None:
    terms = frame_ontology_contextualized_terms(
        feature_keys=[
            "flogic:citation_title_section_primary_number_distance_profile_token:1k",
            "flogic:citation_title_section_terminal_number_distance_profile:ascending_lt_1k",
            "flogic:citation_title_section_terminal_number_distance_profile_stem:ascending_lt_1k",
            "flogic:citation_section_terminal_number_digit_count_bucket:3_digit",
            "flogic:condition_conditional_normative:O|:subject_to",
        ],
    )

    assert "citation_title_section_primary_number_distance_profile_token_1k" in terms
    assert (
        "citation_title_section_terminal_number_distance_profile_ascending_lt_1k"
        in terms
    )
    assert (
        "citation_title_section_terminal_number_distance_profile_stem_ascending_lt_1k"
        in terms
    )
    assert "citation_section_terminal_number_digit_count_bucket_3_digit" in terms
    assert "condition_conditional_normative_subject_to" in terms


def test_frame_ontology_contextualized_terms_contextualize_predicate_token_and_magnitude_bucket_values() -> None:
    terms = frame_ontology_contextualized_terms(
        feature_keys=[
            "flogic:predicate_alnum_segment:pub",
            "flogic:predicate_token:pub",
            "flogic:predicate_token_suffix:pub",
            "flogic:citation_section_number_magnitude_bucket:lt_1k",
            "flogic:citation_section_primary_number_magnitude_bucket:lt_1k",
        ]
    )

    assert "predicate_alnum_segment_pub" in terms
    assert "predicate_token_pub" in terms
    assert "predicate_token_suffix_pub" in terms
    assert "citation_section_number_magnitude_bucket_lt_1k" in terms
    assert "citation_section_primary_number_magnitude_bucket_lt_1k" in terms


def test_frame_ontology_contextualized_terms_contextualize_modal_cues_and_low_signal_digit_signatures() -> None:
    terms = frame_ontology_contextualized_terms(
        feature_keys=[
            "flogic:citation_section_number_parity_positioned:2:even",
            "flogic:source_id_section_number_parity_positioned:2:even",
            "slot:citation_section_number_parity_positioned:2_even",
            "slot:source_id_section_number_parity_positioned:2_even",
            "flogic:citation_source_id_title_number_signature_leading_digit_pair:2|2",
            "flogic:citation_title_number_leading_digit:2",
            "flogic:source_id_title_number_leading_digit:2",
            "slot:citation_source_id_title_number_signature_leading_digit_pair:2_2",
            "flogic:modal_cue:after",
        ]
    )

    assert "citation_section_number_parity_positioned_even" in terms
    assert "source_id_section_number_parity_positioned_even" in terms
    assert "citation_source_id_title_number_signature_leading_digit_pair_2" in terms
    assert "citation_title_number_leading_digit_2" in terms
    assert "source_id_title_number_leading_digit_2" in terms
    assert "modal_cue_after" in terms


def test_frame_ontology_terms_from_feature_keys_support_legacy_bare_contextual_predicates() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "condition:unless written notice is provided",
            "citation_section_component:430f",
            "source_id_section_suffix:e",
            "modal_family_count_ranked:1:frame:3",
            "source_id:us-code-5-552-deadbeefdeadbeef",
        ]
    )

    assert terms == [
        "unless_written_notice_provided",
        "430f",
        "e",
        "frame",
        "5_552",
    ]


def test_frame_ontology_terms_from_feature_keys_support_source_id_citation_canonical_terms() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:source_id_citation_canonical:50 U.S.C. 2675",
            "slot:source_id_citation_canonical:16 U.S.C. 460ff-1",
            "flogic:source_id_digest:8dbd5e2eb6c364c8",
        ]
    )

    assert terms == [
        "50_2675",
        "16_460ff_1",
    ]


def test_frame_ontology_terms_from_feature_keys_normalize_truncated_slot_canonical_pair_values() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:citation_source_id_canonical_pair:49_u_s_c_1101_49_u_s",
            "slot:citation_source_id_canonical_pair:34_u_s_c_10406_34_u_s",
        ]
    )

    assert terms == [
        "49_1101",
        "34_10406",
    ]


def test_frame_ontology_terms_from_feature_keys_canonicalize_usc_citations_for_direct_frame_terms() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "selected-frame-term:42 U.S.C. 1437q.",
            "candidate-frame-term:20 U.S.C. 1087j",
            "flogic:selected_ontology_term:16 U.S.C. 460l-11",
            "slot:candidate_ontology_term:42 U.S.C. 2981 to 2981c.",
            "flogic:interpreted_in_frame_term:22 U.S.C. 2349aa-4",
        ]
    )

    assert terms == [
        "42_1437q",
        "20_1087j",
        "16_460l_11",
        "42_2981_2981c",
        "22_2349aa_4",
    ]


def test_frame_ontology_terms_from_feature_keys_support_slot_normalized_source_ids() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:source_id:us_code_54_102701_171f636b98d4b36b",
            "slot:source_id:us_code_2_31a_2b_119e8839f18f02be",
            "slot:source_id:us_code_invalid_value",
        ]
    )

    assert terms == [
        "54_102701",
        "2_31a_2b",
    ]


def test_frame_ontology_terms_from_feature_keys_support_digestless_source_ids() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:source_id:us-code-42-2624 to 2628.",
            "slot:source_id:us_code_44_1305",
            "slot:source_id:us_code_invalid_value",
        ]
    )

    assert terms == [
        "42_2624_2628",
        "44_1305",
    ]


def test_frame_ontology_terms_from_feature_keys_support_belongs_to_document_source_ids() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:belongs_to_document:us-code-46-30525.-99a6422ab828fa0c",
            "flogic:belongs_to_document:us-code-48-1422b.-1024d577005506f9",
            "flogic:belongs_to_document:not-a-us-code-source-id",
        ]
    )

    assert terms == [
        "46_30525",
        "48_1422b",
    ]


def test_frame_ontology_terms_from_feature_keys_support_bare_usc_and_source_id_coordinates() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "54 U.S.C. 308103.",
            "us-code-25-4104-60f38eda8457e605",
            "49 U.S.C. 44919.",
            "us-code-16-460l-2-d5a72237fcd0f550",
            "token:agency",
            "25 U.S.C. 1041d",
            "us-code-42-8013.-3827148a37e8f294",
            "54 U.S.C. 100507.",
        ]
    )

    assert terms == [
        "54_308103",
        "25_4104",
        "49_44919",
        "16_460l_2",
        "25_1041d",
        "42_8013",
        "54_100507",
    ]


def test_frame_ontology_terms_from_triples_support_digestless_source_ids() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "source_id",
                "object": "us-code-42-2624 to 2628.",
            },
            {
                "subject": "doc-1",
                "predicate": "source_id",
                "object": "us_code_44_1305",
            },
            {
                "subject": "doc-1",
                "predicate": "source_id",
                "object": "us_code_invalid_value",
            },
        ]
    )

    assert terms == [
        "42_2624_2628",
        "44_1305",
    ]


def test_frame_ontology_terms_from_feature_keys_support_section_trailing_punctuation() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:citation_section_trailing_punct:.",
            "slot:source_id_section_trailing_punct:).",
        ]
    )

    assert terms == [
        "period",
        "right_paren_period",
    ]


def test_frame_ontology_terms_from_triples_support_section_trailing_punctuation() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "citation_section_trailing_punct",
                "object": ".",
            },
            {
                "subject": "doc-1",
                "predicate": "source_id_section_trailing_punct",
                "object": ").",
            },
        ]
    )

    assert terms == [
        "period",
        "right_paren_period",
    ]


def test_frame_ontology_terms_from_triples_canonicalize_usc_citations_for_direct_frame_terms() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "selected_ontology_term",
                "object": "42 U.S.C. 1437q.",
            },
            {
                "subject": "doc-1",
                "predicate": "candidate_ontology_term",
                "object": "20 U.S.C. 1087j",
            },
            {
                "subject": "doc-1",
                "predicate": "interpreted_in_frame_term",
                "object": "16 U.S.C. 460l-11",
            },
            {
                "subject": "doc-1",
                "predicate": "selected_ontology_term",
                "object": "42 U.S.C. 2981 to 2981c.",
            },
            {
                "subject": "doc-1",
                "predicate": "candidate_ontology_term",
                "object": "22 U.S.C. 2349aa-4",
            },
        ]
    )

    assert terms == [
        "42_1437q",
        "20_1087j",
        "16_460l_11",
        "42_2981_2981c",
        "22_2349aa_4",
    ]


def test_frame_ontology_terms_from_feature_keys_support_fallback_surface_text_features() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:fallback_surface_text:Housing voucher benefits and utility allowances",
            "flogic:fallback_surface_text_token_suffix:allowances",
        ]
    )

    assert terms == [
        "housing_voucher_benefits_utility_allowances",
        "allowances",
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
        "f",
        "16",
        "552",
        "pursuant_subsection",
        "notice",
        "if",
        "except",
    ]


def test_frame_ontology_terms_from_feature_keys_keep_single_letter_citation_suffixes() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:citation_section_suffix:i",
            "flogic:source_id_section_suffix:e",
            "slot:citation_section_suffix:a",
        ]
    )

    assert terms == [
        "i",
        "e",
        "a",
    ]


def test_frame_ontology_terms_from_triples_keep_single_letter_citation_suffixes() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "citation_section_suffix",
                "object": "i",
            },
            {
                "subject": "doc-1",
                "predicate": "source_id_section_suffix",
                "object": "e",
            },
            {
                "subject": "doc-1",
                "predicate": "citation_section_suffix",
                "object": "a",
            },
        ]
    )

    assert terms == [
        "i",
        "e",
        "a",
    ]


def test_frame_ontology_terms_from_feature_keys_normalize_positioned_citation_values() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:citation_section_component_positioned:1:360bbb",
            "slot:citation_section_number_positioned:1:360",
            "slot:citation_section_number_positioned:2:0",
            "flogic:source_id_section_component_positioned:1:360bbb",
            "flogic:source_id_section_number_positioned:2:0",
            "flogic:source_id_section_component_kind_positioned:1:alphanumeric",
        ]
    )

    assert terms == [
        "360bbb",
        "360",
        "0",
        "alphanumeric",
    ]


def test_frame_ontology_terms_from_feature_keys_normalize_legacy_slot_positioned_values() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:citation_section_component_positioned:1_360bbb",
            "slot:citation_section_number_positioned:1_360",
            "slot:citation_section_number_digit_count_positioned:1_3",
            "slot:citation_section_component_kind_positioned:1_alphanumeric",
        ]
    )

    assert terms == [
        "360bbb",
        "360",
        "3",
        "alphanumeric",
    ]


def test_frame_ontology_terms_from_triples_normalize_positioned_citation_values() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "citation_section_component_positioned",
                "object": "1:360bbb",
            },
            {
                "subject": "doc-1",
                "predicate": "citation_section_number_positioned",
                "object": "1:360",
            },
            {
                "subject": "doc-1",
                "predicate": "citation_section_number_positioned",
                "object": "2:0",
            },
            {
                "subject": "doc-1",
                "predicate": "source_id_section_component_positioned",
                "object": "1:360bbb",
            },
            {
                "subject": "doc-1",
                "predicate": "source_id_section_number_positioned",
                "object": "2:0",
            },
            {
                "subject": "doc-1",
                "predicate": "source_id_section_component_kind_positioned",
                "object": "1:alphanumeric",
            },
        ]
    )

    assert terms == [
        "360bbb",
        "360",
        "0",
        "alphanumeric",
    ]


def test_frame_ontology_terms_from_feature_keys_keep_zero_digit_count_values() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:citation_title_number_zero_digit_count:0",
            "flogic:citation_title_number_trailing_zero_count:0",
            "slot:source_id_section_primary_number_zero_digit_count:1",
            "slot:source_id_section_primary_number_trailing_zero_count:1",
            "flogic:citation_section_component_count:3",
        ]
    )

    assert terms == [
        "0",
        "1",
    ]


def test_frame_ontology_terms_from_triples_keep_zero_digit_count_values() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {
                "subject": "doc-1",
                "predicate": "citation_title_number_zero_digit_count",
                "object": "0",
            },
            {
                "subject": "doc-1",
                "predicate": "citation_title_number_trailing_zero_count",
                "object": "0",
            },
            {
                "subject": "doc-1",
                "predicate": "source_id_section_primary_number_zero_digit_count",
                "object": "1",
            },
            {
                "subject": "doc-1",
                "predicate": "source_id_section_primary_number_trailing_zero_count",
                "object": "1",
            },
            {
                "subject": "doc-1",
                "predicate": "citation_section_component_count",
                "object": "3",
            },
        ]
    )

    assert terms == [
        "0",
        "1",
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

    assert terms == [
        "frame",
        "deontic",
    ]


def test_frame_ontology_terms_from_feature_keys_support_selected_frame_family_signals() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "family:selected_frame:deontic",
            "modal-family:selected-frame:temporal",
            "modal_family:selected_frame:frame",
            "family:selected_frame:2",
        ]
    )

    assert terms == [
        "deontic",
        "temporal",
        "frame",
    ]


def test_is_frame_ontology_feature_key_distinguishes_frame_linked_signals() -> None:
    assert is_frame_ontology_feature_key("family:frame:1") is True
    assert is_frame_ontology_feature_key("modal-family:frame") is True
    assert is_frame_ontology_feature_key("family:deontic:2") is True
    assert is_frame_ontology_feature_key("cue:frame:transferred") is True
    assert is_frame_ontology_feature_key("cue:frame:Frame:authority") is True
    assert is_frame_ontology_feature_key("family:selected_frame:deontic") is True
    assert is_frame_ontology_feature_key("flogic:modal_family_count:deontic:2") is True
    assert is_frame_ontology_feature_key("flogic:modal_family_count_dynamic:4") is True
    assert is_frame_ontology_feature_key("flogic:modal_family_count_value:9") is False
    assert is_frame_ontology_feature_key("slot:modal_family:frame") is True
    assert is_frame_ontology_feature_key("slot:operator:framed_as") is True
    assert is_frame_ontology_feature_key("slot:role:frame") is True
    assert is_frame_ontology_feature_key("slot:operator:obligatory") is False
    assert is_frame_ontology_feature_key("slot:role:clause") is False
    assert is_frame_ontology_feature_key("slot:selected_frame_stem:administrative_notice_hearing") is True
    assert is_frame_ontology_feature_key("slot:frame_candidate_ranked:1:criminal_penalty_enforcement") is True
    assert is_frame_ontology_feature_key(
        "slot:selected_ontology_term:final order"
    ) is True
    assert is_frame_ontology_feature_key(
        "citation_section_component:430f"
    ) is True
    assert is_frame_ontology_feature_key(
        "condition:unless written notice is provided"
    ) is True
    assert is_frame_ontology_feature_key(
        "flogic:source_id_citation_canonical:50 U.S.C. 2675"
    ) is True
    assert is_frame_ontology_feature_key(
        "slot:source_id_citation_canonical:16 U.S.C. 460ff-1"
    ) is True
    assert is_frame_ontology_feature_key(
        "flogic:source_id_digest:8dbd5e2eb6c364c8"
    ) is False
    assert is_frame_ontology_feature_key("token:agency") is False
    assert is_frame_ontology_feature_key("cue:deontic:O:must") is False
    assert is_frame_ontology_feature_key("flogic:condition:unless written notice is provided") is True
    assert is_frame_ontology_feature_key("slot:source_id:us-code-5-552-deadbeefdeadbeef") is True
    assert is_frame_ontology_feature_key(
        "slot:source_id:us_code_5_552_deadbeefdeadbeef"
    ) is True
    assert is_frame_ontology_feature_key("flogic:source_id:us-code-5-552-deadbeefdeadbeef") is True
    assert is_frame_ontology_feature_key("slot:source_id:us_code_44_1305") is True
    assert is_frame_ontology_feature_key("flogic:source_id:us-code-42-2624 to 2628.") is True
    assert is_frame_ontology_feature_key(
        "flogic:belongs_to_document:us-code-46-30525.-99a6422ab828fa0c"
    ) is True
    assert is_frame_ontology_feature_key("54 U.S.C. 308103.") is True
    assert is_frame_ontology_feature_key("us-code-16-460l-2-d5a72237fcd0f550") is True
    assert is_frame_ontology_feature_key("slot:source_id:not-a-us-code-source-id") is False
    assert is_frame_ontology_feature_key("transferred") is False
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


def test_frame_ontology_feature_keys_prioritize_direct_signals_when_key_cap_is_exceeded() -> None:
    contextual_features = [
        f"flogic:citation_section_component:{1000 + index}"
        for index in range(12)
    ]
    keys = frame_ontology_feature_keys(
        contextual_features
        + ["selected-frame-term:final_order"],
        max_keys=4,
    )

    assert keys == [
        "selected-frame-term:final_order",
        "flogic:citation_section_component:1000",
        "flogic:citation_section_component:1001",
        "flogic:citation_section_component:1002",
    ]


def test_frame_ontology_feature_keys_from_values_extracts_nested_hint_evidence() -> None:
    keys = frame_ontology_feature_keys_from_values(
        {
            "hint_evidence": [
                {
                    "hint_id": "modal-synthesis-248e6f537d1662f7",
                    "priority": 0.795075535022,
                    "sample_id": "us-code-26-307-c04b9c0813def639",
                    "frame_features": [
                        "selected-frame-term:26 U.S.C. 307",
                        "token:agency",
                    ],
                }
            ],
            "metadata": {
                "sample_ids": [
                    "us-code-42-300i-0102d16fb9d986ee",
                    "sample-without-source-shape",
                ]
            },
        }
    )

    assert keys == [
        "us-code-26-307-c04b9c0813def639",
        "selected-frame-term:26 U.S.C. 307",
        "us-code-42-300i-0102d16fb9d986ee",
    ]


def test_frame_ontology_feature_keys_from_values_extracts_belongs_to_document_features() -> None:
    keys = frame_ontology_feature_keys_from_values(
        {
            "hint_evidence": [
                {
                    "top_embedding_features": [
                        "flogic:belongs_to_document:us-code-46-30525.-99a6422ab828fa0c",
                        "token:agency",
                    ]
                }
            ]
        }
    )

    assert keys == [
        "flogic:belongs_to_document:us-code-46-30525.-99a6422ab828fa0c",
    ]


def test_frame_ontology_feature_keys_from_values_synthesizes_semantic_frame_fields() -> None:
    keys = frame_ontology_feature_keys_from_values(
        {
            "hint_evidence": [
                {
                    "selected_frame": "administrative_notice_hearing",
                    "predicted_family": "deontic",
                    "target_family": "frame",
                    "top_family_features": ["token:agency"],
                }
            ]
        }
    )

    assert keys == [
        "frame:administrative_notice_hearing",
        "family:selected_frame:deontic",
        "family:selected_frame:frame",
    ]
    assert frame_ontology_terms_from_feature_keys(keys) == [
        "administrative_notice_hearing",
        "deontic",
        "frame",
    ]


def test_frame_ontology_feature_keys_from_values_synthesizes_family_alias_fields() -> None:
    keys = frame_ontology_feature_keys_from_values(
        {
            "hint_evidence": [
                {
                    "family": "deontic",
                    "selected_family": "temporal",
                    "candidate_family": "epistemic",
                    "family_name": "dynamic",
                    "modal_family_name": "frame",
                    "top_family_features": ["token:agency"],
                }
            ]
        }
    )

    assert keys == [
        "family:selected_frame:deontic",
        "family:selected_frame:temporal",
        "family:selected_frame:epistemic",
        "family:selected_frame:dynamic",
        "family:selected_frame:frame",
    ]
    assert frame_ontology_terms_from_feature_keys(keys) == [
        "deontic",
        "temporal",
        "epistemic",
        "dynamic",
        "frame",
    ]


def test_is_high_signal_frame_ontology_term_filters_structural_noise() -> None:
    assert is_high_signal_frame_ontology_term("final_order") is True
    assert is_high_signal_frame_ontology_term("42_291") is True
    assert is_high_signal_frame_ontology_term("291") is True
    assert is_high_signal_frame_ontology_term("42") is False
    assert is_high_signal_frame_ontology_term("1") is False
    assert is_high_signal_frame_ontology_term("false") is False
    assert is_high_signal_frame_ontology_term("odd") is False


def test_frame_ontology_high_signal_terms_preserve_order_and_filter_noise() -> None:
    terms = frame_ontology_high_signal_terms(
        [
            "0",
            "false",
            "291",
            "42_291",
            "final_order",
            "odd",
            "42_291",
            "2",
        ]
    )

    assert terms == [
        "291",
        "42_291",
        "final_order",
    ]


def test_frame_ontology_high_signal_terms_filter_stopword_noise() -> None:
    terms = frame_ontology_high_signal_terms(
        [
            "if",
            "of",
            "the",
            "final_order",
        ]
    )

    assert terms == [
        "if",
        "final_order",
    ]
