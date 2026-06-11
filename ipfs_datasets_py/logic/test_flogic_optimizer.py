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


def test_frame_ontology_terms_audit_zero_digit_predicates_as_contextual_terms() -> None:
    result = _optimizer().evaluate(
        source_text="s",
        decoded_text="d",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:citation_title_section_primary_number_span_has_zero_digit:false",
            "flogic:citation_title_section_primary_number_span_zero_digit_count:0",
            "flogic:citation_title_section_terminal_number_span_has_zero_digit:false",
            "flogic:citation_section_primary_number_trailing_zero_count:100",
        ],
    )

    metadata = result.metadata
    expected_terms = {
        "citation_title_section_primary_number_span_has_zero_digit_false",
        "citation_title_section_primary_number_span_zero_digit_count_0",
        "citation_title_section_terminal_number_span_has_zero_digit_false",
        "citation_section_primary_number_trailing_zero_count_100",
    }
    assert expected_terms.issubset(set(metadata["frame_ontology_terms"]))
    assert expected_terms.issubset(set(metadata["frame_ontology_high_signal_terms"]))
    assert expected_terms.issubset(
        set(metadata["frame_ontology_high_signal_terms_from_contextualized"])
    )


def test_frame_ontology_terms_include_predicate_argument_anchor_terms() -> None:
    result = _optimizer().evaluate(
        source_text="s",
        decoded_text="d",
        source_embedding=[0.0, 1.0],
        decoded_embedding=[0.0, 1.0],
        kg_triples=[],
        frame_feature_keys=[
            "predicate-argument:source-object-role:education:clause",
            "predicate-argument:source-object-family:education:frame",
            "predicate-argument:operator:deontic:d:o",
            "predicate-argument:source-object-family:conservation:frame",
        ],
    )

    metadata = result.metadata
    assert "source_object_role_education_clause" in metadata["frame_ontology_terms"]
    assert "source_object_family_conservation_frame" in metadata["frame_ontology_terms"]
    assert "education" in metadata["frame_ontology_terms"]
    assert "education_frame" in metadata["frame_ontology_terms"]
    assert "conservation" in metadata["frame_ontology_terms"]
    assert "conservation_frame" in metadata["frame_ontology_terms"]
    assert "deontic" in metadata["frame_ontology_terms"]
    assert "deontic_d_o" in metadata["frame_ontology_terms"]


def test_frame_ontology_terms_contextualize_legal_ir_view_family_features() -> None:
    result = _optimizer().evaluate(
        source_text="s",
        decoded_text="d",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            {
                "frame_features": [
                    "legal-ir-view:deontic.ir",
                    "legal-ir-view:modal.frame_logic",
                    "legal-ir-view:TDFOL.prover",
                    "legal-ir-view:knowledge_graphs.neo4j_compat",
                    "legal-ir-view:CEC.native",
                    "flogic:fallback_surface_text_alnum_segment_kind_positioned:4:numeric",
                    "slot:fallback_surface_text_alnum_segment_kind_positioned:4_numeric",
                ],
                "top_family_features": [
                    "legal-ir-view:deontic.ir",
                    "legal-ir-view:modal.frame_logic",
                    "legal-ir-view:TDFOL.prover",
                    "legal-ir-view:knowledge_graphs.neo4j_compat",
                    "quality:bias",
                    "quality:symbolic:has-formula",
                    "legal-ir-view:CEC.native",
                ],
            }
        ],
    )

    metadata = result.metadata
    assert "modal_frame_logic" in metadata["frame_ontology_terms"]
    assert "legal_ir_view_modal_frame_logic" in metadata["frame_ontology_terms"]
    assert "legal_ir_view_tdfol_prover" in metadata["frame_ontology_high_signal_terms"]
    assert (
        "fallback_surface_text_alnum_segment_kind_positioned_numeric"
        in metadata["frame_ontology_high_signal_terms_from_contextualized"]
    )


def test_frame_ontology_terms_promote_compiler_guidance_view_gaps() -> None:
    result = _optimizer().evaluate(
        source_text="s",
        decoded_text="d",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "legal-ir-view-gap:underrepresented:modal.frame_logic",
            "legal-ir-target-view:knowledge_graphs.neo4j_compat",
            "legal-ir-predicted-view:TDFOL.prover",
        ],
    )

    metadata = result.metadata
    assert "modal_frame_logic" in metadata["frame_ontology_terms"]
    assert "knowledge_graphs_neo4j_compat" in metadata["frame_ontology_terms"]
    assert "tdfol_prover" in metadata["frame_ontology_terms"]
    assert (
        "legal_ir_view_modal_frame_logic"
        in metadata["frame_ontology_high_signal_terms_from_contextualized"]
    )


def test_frame_ontology_terms_extract_compiler_guidance_view_evidence_fields() -> None:
    result = _optimizer().evaluate(
        source_text="s",
        decoded_text="d",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            {
                "bridge_failure_name": "flogic_similarity_loss",
                "legal_ir_underrepresented_components": [
                    "modal.frame_logic",
                    "knowledge_graphs.neo4j_compat",
                ],
                "predicted_view": "modal.frame_logic",
                "target_view": "modal.frame_logic",
            }
        ],
    )

    metadata = result.metadata
    assert "legal-ir-view:modal.frame_logic" in metadata["frame_audit_feature_keys"]
    assert (
        "legal-ir-view:knowledge_graphs.neo4j_compat"
        in metadata["frame_audit_feature_keys"]
    )
    assert "modal_frame_logic" in metadata["frame_ontology_terms"]
    assert "legal_ir_view_modal_frame_logic" in metadata["frame_ontology_terms"]
    assert "knowledge_graphs_neo4j_compat" in metadata["frame_ontology_terms"]


def test_frame_ontology_terms_skip_low_signal_positioned_alnum_segments() -> None:
    result = _optimizer().evaluate(
        source_text="s",
        decoded_text="d",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:condition_alnum_segment_positioned:15:in",
            "flogic:condition_scope_alnum_segment_positioned:14:in",
            "slot:condition_alnum_segment_positioned:15_in",
            "slot:condition_scope_alnum_segment_positioned:14_in",
            "flogic:fallback_surface_text_alnum_segment_positioned:3:91",
            "slot:fallback_surface_text_alnum_segment_positioned:3_91",
            "flogic:fallback_surface_text_alnum_segment_kind_positioned:4:numeric",
            "flogic:fallback_surface_text_alnum_segment_positioned:4:voucher",
        ],
    )

    metadata = result.metadata
    assert "in" not in metadata["frame_ontology_terms"]
    assert "91" not in metadata["frame_ontology_terms"]
    assert "condition_alnum_segment_positioned_in" not in metadata[
        "frame_ontology_contextualized_terms"
    ]
    assert "fallback_surface_text_alnum_segment_positioned_91" not in metadata[
        "frame_ontology_high_signal_terms_from_contextualized"
    ]
    assert "voucher" in metadata["frame_ontology_terms"]
    assert (
        "fallback_surface_text_alnum_segment_kind_positioned_numeric"
        in metadata["frame_ontology_high_signal_terms_from_contextualized"]
    )
