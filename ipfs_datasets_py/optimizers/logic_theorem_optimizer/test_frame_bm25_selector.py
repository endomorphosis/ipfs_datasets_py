"""Tests for frame ontology feature/term extraction helpers."""

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
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
