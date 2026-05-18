"""Tests for frame ontology feature/term extraction helpers."""

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    frame_ontology_feature_keys_from_values,
    frame_ontology_high_signal_terms,
    frame_ontology_terms_from_feature_keys,
    frame_ontology_terms_from_triples,
    normalize_frame_ontology_term,
)


def test_normalize_frame_ontology_term_drops_generic_numeric_tokens() -> None:
    assert normalize_frame_ontology_term("5406") == ""


def test_frame_ontology_terms_from_triples_keeps_citation_numbers() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {"predicate": "citation_section_number", "object": "5406"},
            {"predicate": "source_id_section_number", "object": "1472"},
            {"predicate": "citation_section_component_count", "object": "3"},
            {"predicate": "modal_family", "object": "frame"},
        ]
    )

    assert "5406" in terms
    assert "1472" in terms
    assert "frame" in terms
    assert "3" not in terms


def test_frame_ontology_terms_from_feature_keys_keeps_flogic_citation_numbers() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:citation_section_number:1472",
            "flogic:source_id_section_number:5406",
            "flogic:citation_section_component_count:2",
            "flogic:modal_family:frame",
        ]
    )

    assert "1472" in terms
    assert "5406" in terms
    assert "frame" in terms
    assert "2" not in terms


def test_frame_ontology_terms_from_triples_keeps_single_digit_citation_suffixes() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {"predicate": "citation_section", "object": "78u-3"},
            {"predicate": "source_id_section", "object": "410r-1"},
        ]
    )

    assert "78u_3" in terms
    assert "410r_1" in terms


def test_frame_ontology_terms_from_feature_keys_keeps_single_digit_citation_suffixes() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:citation_section:78u-3",
            "flogic:source_id_section:410r-1",
        ]
    )

    assert "78u_3" in terms
    assert "410r_1" in terms


def test_frame_ontology_terms_from_triples_keeps_single_letter_citation_suffixes() -> None:
    terms = frame_ontology_terms_from_triples(
        [
            {"predicate": "citation_section_suffix", "object": "i"},
            {"predicate": "source_id_section_suffix", "object": "e"},
        ]
    )

    assert "i" in terms
    assert "e" in terms


def test_frame_ontology_terms_from_feature_keys_keeps_single_letter_citation_suffixes() -> None:
    terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:citation_section_suffix:i",
            "flogic:source_id_section_suffix:e",
        ]
    )

    assert "i" in terms
    assert "e" in terms


def test_frame_ontology_terms_support_modal_family_count_predicates() -> None:
    triple_terms = frame_ontology_terms_from_triples(
        [
            {"predicate": "modal_family_count", "object": "deontic:2"},
            {"predicate": "modal_family_count_ranked", "object": "1:frame:3"},
            {"predicate": "modal_family_count_family", "object": "temporal"},
            {"predicate": "modal_family_count_dynamic", "object": "4"},
            {"predicate": "modal_family_count_value", "object": "9"},
        ]
    )
    feature_terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:modal_family_count:deontic:2",
            "flogic:modal_family_count_ranked:1:frame:3",
            "flogic:modal_family_count_family:temporal",
            "flogic:modal_family_count_dynamic:4",
            "flogic:modal_family_count_value:9",
        ]
    )

    assert triple_terms == ["deontic", "frame", "temporal", "dynamic"]
    assert feature_terms == ["deontic", "frame", "temporal", "dynamic"]


def test_frame_ontology_terms_support_source_id_citation_canonical_predicates() -> None:
    triple_terms = frame_ontology_terms_from_triples(
        [
            {"predicate": "source_id_citation_canonical", "object": "50 U.S.C. 2675"},
            {"predicate": "source_id_digest", "object": "8dbd5e2eb6c364c8"},
        ]
    )
    feature_terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:source_id_citation_canonical:50 U.S.C. 2675",
            "slot:source_id_citation_canonical:16 U.S.C. 460ff-1",
            "flogic:source_id_digest:8dbd5e2eb6c364c8",
        ]
    )

    assert triple_terms == ["50_2675"]
    assert feature_terms == ["50_2675", "16_460ff_1"]


def test_frame_ontology_terms_normalize_truncated_slot_canonical_pair_values() -> None:
    feature_terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:citation_source_id_canonical_pair:49_u_s_c_1101_49_u_s",
            "slot:citation_source_id_canonical_pair:34_u_s_c_10406_34_u_s",
        ]
    )

    assert feature_terms == ["49_1101", "34_10406"]


def test_frame_ontology_terms_normalize_range_connector_predicates() -> None:
    triple_terms = frame_ontology_terms_from_triples(
        [
            {"predicate": "citation_section_range_connector", "object": "to"},
            {"predicate": "source_id_section_range_connector", "object": "through"},
            {"predicate": "citation_section_range_connector", "object": "thru"},
        ]
    )
    feature_terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:citation_section_range_connector:to",
            "slot:source_id_section_range_connector:through",
            "flogic:citation_section_range_connector:thru",
        ]
    )

    assert triple_terms == ["through"]
    assert feature_terms == ["through"]


def test_frame_ontology_terms_extract_source_id_coordinate_terms() -> None:
    triple_terms = frame_ontology_terms_from_triples(
        [
            {"predicate": "source_id", "object": "us-code-43-945a.-deadbeefdeadbeef"},
            {"predicate": "source_id", "object": "not-a-uscode-source-id"},
        ]
    )
    feature_terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:source_id:us-code-43-945a.-deadbeefdeadbeef",
            "slot:source_id:not-a-uscode-source-id",
        ]
    )

    assert triple_terms == ["43_945a"]
    assert feature_terms == ["43_945a"]


def test_frame_ontology_terms_canonicalize_usc_citations_for_direct_frame_terms() -> None:
    triple_terms = frame_ontology_terms_from_triples(
        [
            {"predicate": "selected_ontology_term", "object": "42 U.S.C. 1437q."},
            {"predicate": "candidate_ontology_term", "object": "20 U.S.C. 1087j"},
            {"predicate": "interpreted_in_frame_term", "object": "16 U.S.C. 460l-11"},
            {"predicate": "selected_ontology_term", "object": "42 U.S.C. 2981 to 2981c."},
            {"predicate": "candidate_ontology_term", "object": "22 U.S.C. 2349aa-4"},
        ]
    )
    feature_terms = frame_ontology_terms_from_feature_keys(
        [
            "selected-frame-term:42 U.S.C. 1437q.",
            "candidate-frame-term:20 U.S.C. 1087j",
            "flogic:selected_ontology_term:16 U.S.C. 460l-11",
            "slot:candidate_ontology_term:42 U.S.C. 2981 to 2981c.",
            "flogic:interpreted_in_frame_term:22 U.S.C. 2349aa-4",
        ]
    )

    expected = [
        "42_1437q",
        "20_1087j",
        "16_460l_11",
        "42_2981_2981c",
        "22_2349aa_4",
    ]
    assert triple_terms == expected
    assert feature_terms == expected


def test_frame_ontology_terms_support_slot_normalized_source_id_coordinate_terms() -> None:
    feature_terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:source_id:us_code_54_102701_171f636b98d4b36b",
            "slot:source_id:us_code_2_31a_2b_119e8839f18f02be",
        ]
    )

    assert feature_terms == ["54_102701", "2_31a_2b"]


def test_frame_ontology_terms_support_procedural_keyword_predicates() -> None:
    triple_terms = frame_ontology_terms_from_triples(
        [
            {"predicate": "procedural_keyword", "object": "review"},
            {
                "predicate": "procedural_keyword_stem",
                "object": "adjudicatory_review",
            },
            {"predicate": "procedural_keyword_token_count", "object": "2"},
        ]
    )
    feature_terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:procedural_keyword:review",
            "slot:procedural_keyword_stem:adjudicatory_review",
            "slot:procedural_keyword_token_count:2",
        ]
    )

    assert triple_terms == ["review", "adjudicatory_review"]
    assert feature_terms == ["review", "adjudicatory_review"]


def test_frame_ontology_terms_support_predicate_alnum_segment_predicates() -> None:
    triple_terms = frame_ontology_terms_from_triples(
        [
            {"predicate": "predicate_alnum_segment", "object": "391"},
            {"predicate": "predicate_alnum_segment_positioned", "object": "1:391"},
            {"predicate": "predicate_alnum_segment", "object": "a"},
            {"predicate": "predicate_alnum_segment_positioned", "object": "2:a"},
            {"predicate": "predicate_alnum_segment_kind", "object": "alpha"},
        ]
    )
    feature_terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:predicate_alnum_segment:1790",
            "flogic:predicate_alnum_segment_positioned:1:1790",
            "slot:predicate_alnum_segment:b",
            "slot:predicate_alnum_segment_positioned:2:b",
            "slot:predicate_alnum_segment_kind:alpha",
        ]
    )

    assert triple_terms == ["391", "a"]
    assert feature_terms == ["1790", "b"]


def test_frame_ontology_terms_preserve_condition_stopword_segments_for_audits() -> None:
    triple_terms = frame_ontology_terms_from_triples(
        [
            {"predicate": "condition_alnum_segment", "object": "if"},
            {"predicate": "condition_alnum_segment", "object": "of"},
            {"predicate": "condition_alnum_segment", "object": "the"},
        ]
    )
    feature_terms = frame_ontology_terms_from_feature_keys(
        [
            "flogic:condition_alnum_segment:if",
            "flogic:condition_alnum_segment:of",
            "flogic:condition_alnum_segment:the",
        ]
    )

    assert triple_terms == ["if", "of", "the"]
    assert feature_terms == ["if", "of", "the"]
    assert frame_ontology_high_signal_terms(feature_terms) == ["if"]


def test_frame_ontology_terms_canonicalize_repeated_pair_values() -> None:
    triple_terms = frame_ontology_terms_from_triples(
        [
            {
                "predicate": "citation_source_id_title_section_key_pair",
                "object": "22:10006|22:10006",
            },
            {"predicate": "citation_source_id_title_pair", "object": "22|22"},
            {"predicate": "citation_source_id_section_pair", "object": "10006|10006"},
        ]
    )
    feature_terms = frame_ontology_terms_from_feature_keys(
        [
            "slot:citation_source_id_title_section_key_pair:22_10006_22_10006",
            "slot:citation_source_id_title_pair:22_22",
            "slot:citation_source_id_section_pair:10006_10006",
        ]
    )

    assert triple_terms == ["22_10006", "22", "10006"]
    assert feature_terms == ["22_10006", "22", "10006"]


def test_frame_ontology_feature_keys_from_values_parses_serialized_json_payloads() -> None:
    feature_keys = frame_ontology_feature_keys_from_values(
        {
            "dedupe_signature": (
                '{"action":"audit_frame_logic_terms",'
                '"sample_ids":["us-code-51-60604.-82ff42829bbdeb0f",'
                '"us-code-3-4-a7eca1aa946379a7"]}'
            ),
            "citations": ["42 U.S.C. 1437q."],
        }
    )

    assert feature_keys == [
        "us-code-51-60604.-82ff42829bbdeb0f",
        "us-code-3-4-a7eca1aa946379a7",
        "42 U.S.C. 1437q.",
    ]
    assert frame_ontology_terms_from_feature_keys(feature_keys) == [
        "51_60604",
        "3_4",
        "42_1437q",
    ]
