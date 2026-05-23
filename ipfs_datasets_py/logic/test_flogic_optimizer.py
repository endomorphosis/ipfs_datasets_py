"""Tests for frame-ontology audit metadata emitted by the F-logic optimizer."""

from ipfs_datasets_py.logic.flogic_optimizer import (
    FLogicOptimizerConfig,
    FLogicSemanticOptimizer,
)


def _optimizer() -> FLogicSemanticOptimizer:
    return FLogicSemanticOptimizer(
        config=FLogicOptimizerConfig(check_ontology_consistency=False)
    )


def test_frame_ontology_terms_include_contextualized_suffix_count_features() -> None:
    result = _optimizer().evaluate(
        source_text="s",
        decoded_text="d",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:citation_section_primary_suffix_consonant_count:1",
            "flogic:citation_section_suffix_consonant_count:1",
            "flogic:citation_section_suffix_consonant_count_positioned:1:1",
            "flogic:source_id_section_primary_suffix_consonant_count:1",
            "flogic:source_id_section_suffix_consonant_count:1",
            "flogic:source_id_section_suffix_consonant_count_positioned:1:1",
            "slot:citation_section_primary_suffix_consonant_count:1",
            "slot:citation_section_suffix_consonant_count:1",
        ],
    )

    metadata = result.metadata
    assert "citation_section_suffix_consonant_count_1" in metadata["frame_ontology_terms"]
    assert (
        "source_id_section_suffix_consonant_count_positioned_1"
        in metadata["frame_ontology_terms"]
    )
    assert "citation_section_suffix_consonant_count_1" in metadata[
        "frame_ontology_high_signal_terms"
    ]


def test_frame_ontology_terms_include_contextualized_parity_audit_features() -> None:
    result = _optimizer().evaluate(
        source_text="s",
        decoded_text="d",
        source_embedding=[0.0, 1.0],
        decoded_embedding=[0.0, 1.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:citation_source_id_title_number_signature_parity_pair:even|even",
            "flogic:citation_title_number_parity:even",
            "flogic:source_id_title_number_parity:even",
            "slot:citation_source_id_title_number_signature_parity_pair:even_even",
            "slot:citation_title_number_parity:even",
            "slot:source_id_title_number_parity:even",
            "flogic:status_keyword:codification",
        ],
    )

    metadata = result.metadata
    assert "citation_title_number_parity_even" in metadata["frame_ontology_terms"]
    assert "source_id_title_number_parity_even" in metadata["frame_ontology_terms"]
    assert "codification" in metadata["frame_ontology_high_signal_terms"]
    assert "citation_title_number_parity_even" in metadata[
        "frame_ontology_high_signal_terms"
    ]


def test_frame_ontology_terms_contextualize_condition_modal_family_and_operator() -> None:
    result = _optimizer().evaluate(
        source_text="s",
        decoded_text="d",
        source_embedding=[0.0, 1.0],
        decoded_embedding=[0.0, 1.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:citation_title_section_primary_number_span_thousands_block:2",
            "slot:citation_title_section_primary_number_span_thousands_block:2",
            "flogic:condition_modal_family:frame",
            "slot:condition_modal_operator:frame",
            "flogic:condition_scope_token:thereof",
        ],
    )

    metadata = result.metadata
    assert "condition_modal_family_frame" in metadata["frame_ontology_terms"]
    assert "condition_modal_operator_frame" in metadata["frame_ontology_terms"]
    assert (
        "citation_title_section_primary_number_span_thousands_block_2"
        in metadata["frame_ontology_terms"]
    )
    assert "condition_modal_family_frame" in metadata[
        "frame_ontology_contextualized_terms"
    ]
    assert "condition_modal_operator_frame" in metadata[
        "frame_ontology_contextualized_terms"
    ]
