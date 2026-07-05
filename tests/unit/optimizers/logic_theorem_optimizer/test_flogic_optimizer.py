"""Tests for F-logic frame-ontology audit metadata."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic.flogic_optimizer import (
    FLogicOptimizerConfig,
    FLogicSemanticOptimizer,
)


def test_flogic_optimizer_reports_frame_feature_keys_and_context_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:modal_family:temporal",
            "flogic:predicate_role:temporal_scope",
            "family:frame:1",
            "token:agency",
            "",
        ],
    )

    assert result.metadata["frame_feature_key_count"] == 4
    assert result.metadata["frame_feature_keys"] == [
        "family:frame:1",
        "flogic:modal_family:temporal",
        "flogic:predicate_role:temporal_scope",
        "token:agency",
    ]
    assert result.metadata["frame_audit_feature_key_count"] == 3
    assert result.metadata["frame_audit_feature_keys"] == [
        "family:frame:1",
        "flogic:modal_family:temporal",
        "flogic:predicate_role:temporal_scope",
    ]
    assert result.metadata["frame_ontology_terms"] == [
        "frame",
        "temporal",
        "temporal_scope",
    ]


def test_flogic_optimizer_tracks_fallback_surface_text_frame_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:fallback_surface_text:Housing voucher benefits and utility allowances",
            "flogic:fallback_surface_text_token_suffix:allowances",
        ],
    )

    assert result.metadata["frame_audit_feature_key_count"] == 2
    assert result.metadata["frame_ontology_term_count"] == 2
    assert result.metadata["frame_ontology_terms"] == [
        "allowances",
        "housing_voucher_benefits_utility_allowances",
    ]


def test_flogic_optimizer_tracks_slot_contextual_frame_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "slot:modal_family:frame",
            "slot:condition:unless written notice is provided",
            "slot:citation_section_number:5406",
            "slot:source_id:us-code-5-552-deadbeefdeadbeef",
        ],
    )

    assert result.metadata["frame_feature_key_count"] == 4
    assert result.metadata["frame_audit_feature_key_count"] == 4
    assert result.metadata["frame_audit_feature_keys"] == [
        "slot:citation_section_number:5406",
        "slot:condition:unless written notice is provided",
        "slot:modal_family:frame",
        "slot:source_id:us-code-5-552-deadbeefdeadbeef",
    ]
    assert result.metadata["frame_ontology_term_count"] == 4
    assert result.metadata["frame_ontology_terms"] == [
        "5406",
        "5_552",
        "frame",
        "unless_written_notice_provided",
    ]


def test_flogic_optimizer_tracks_frame_semantic_slot_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "slot:operator:framed_as",
            "slot:role:frame",
            "slot:operator:obligatory",
            "slot:role:clause",
        ],
    )

    assert result.metadata["frame_audit_feature_keys"] == [
        "slot:operator:framed_as",
        "slot:role:frame",
    ]
    assert result.metadata["frame_ontology_terms"] == [
        "frame",
    ]


def test_flogic_optimizer_tracks_selected_frame_family_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "family:selected_frame:deontic",
            "modal-family:selected-frame:temporal",
            "family:selected_frame:2",
        ],
    )

    assert result.metadata["frame_audit_feature_key_count"] == 3
    assert result.metadata["frame_ontology_term_count"] == 2
    assert result.metadata["frame_ontology_terms"] == [
        "deontic",
        "temporal",
    ]


def test_flogic_optimizer_tracks_modal_family_count_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:modal_family_count:deontic:2",
            "flogic:modal_family_count_ranked:1:frame:3",
            "flogic:modal_family_count_family:temporal",
            "flogic:modal_family_count_dynamic:4",
            "flogic:modal_family_count_value:9",
        ],
    )

    assert result.metadata["frame_audit_feature_keys"] == [
        "flogic:modal_family_count:deontic:2",
        "flogic:modal_family_count_dynamic:4",
        "flogic:modal_family_count_family:temporal",
        "flogic:modal_family_count_ranked:1:frame:3",
    ]
    assert result.metadata["frame_ontology_terms"] == [
        "deontic",
        "dynamic",
        "frame",
        "temporal",
    ]


def test_flogic_optimizer_tracks_source_id_citation_canonical_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:source_id_citation_canonical:50 U.S.C. 2675",
            "slot:source_id_citation_canonical:16 U.S.C. 460ff-1",
            "flogic:source_id_digest:8dbd5e2eb6c364c8",
        ],
    )

    assert result.metadata["frame_audit_feature_keys"] == [
        "flogic:source_id_citation_canonical:50 U.S.C. 2675",
        "slot:source_id_citation_canonical:16 U.S.C. 460ff-1",
    ]
    assert result.metadata["frame_ontology_terms"] == [
        "16_460ff_1",
        "50_2675",
    ]


def test_flogic_optimizer_tracks_digestless_source_id_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "slot:source_id:us-code-42-2624 to 2628.",
            "flogic:source_id:us_code_44_1305",
            "slot:source_id:us_code_invalid_value",
        ],
    )

    assert result.metadata["frame_audit_feature_keys"] == [
        "flogic:source_id:us_code_44_1305",
        "slot:source_id:us-code-42-2624 to 2628.",
    ]
    assert result.metadata["frame_ontology_terms"] == [
        "42_2624_2628",
        "44_1305",
    ]


def test_flogic_optimizer_normalizes_truncated_slot_canonical_pair_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "slot:citation_source_id_canonical_pair:49_u_s_c_1101_49_u_s",
            "slot:citation_source_id_canonical_pair:34_u_s_c_10406_34_u_s",
        ],
    )

    assert result.metadata["frame_ontology_terms"] == [
        "34_10406",
        "49_1101",
    ]


def test_flogic_optimizer_canonicalizes_alphanumeric_usc_frame_term_features() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "selected-frame-term:42 U.S.C. 1437q.",
            "candidate-frame-term:20 U.S.C. 1087j",
            "slot:candidate_ontology_term:16 U.S.C. 460l-11",
            "flogic:selected_ontology_term:42 U.S.C. 2981 to 2981c.",
            "flogic:interpreted_in_frame_term:22 U.S.C. 2349aa-4",
        ],
    )

    assert result.metadata["frame_ontology_terms"] == [
        "16_460l_11",
        "20_1087j",
        "22_2349aa_4",
        "42_1437q",
        "42_2981_2981c",
    ]


def test_flogic_optimizer_normalizes_range_connector_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "slot:citation_section_range_connector:to",
            "flogic:source_id_section_range_connector:thru",
        ],
    )

    assert result.metadata["frame_ontology_terms"] == [
        "through",
    ]


def test_flogic_optimizer_tracks_legacy_bare_contextual_feature_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "condition:unless written notice is provided",
            "citation_section_component:430f",
            "source_id_section_suffix:e",
            "source_id:us-code-5-552-deadbeefdeadbeef",
        ],
    )

    assert result.metadata["frame_audit_feature_keys"] == [
        "citation_section_component:430f",
        "condition:unless written notice is provided",
        "source_id:us-code-5-552-deadbeefdeadbeef",
        "source_id_section_suffix:e",
    ]
    assert result.metadata["frame_ontology_terms"] == [
        "430f",
        "5_552",
        "e",
        "unless_written_notice_provided",
    ]


def test_flogic_optimizer_tracks_single_letter_modal_symbol_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:modal_operator:P",
            "flogic:modal_operator:O|",
            "flogic:modal_system:D",
            "flogic:modal_system:LTL",
        ],
    )

    assert result.metadata["frame_ontology_terms"] == [
        "d",
        "ltl",
        "o",
        "p",
    ]


def test_flogic_optimizer_keeps_direct_frame_terms_when_audit_key_cap_is_exceeded() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    dense_contextual_features = [
        f"flogic:citation_section_component:{1000 + index}"
        for index in range(1200)
    ]
    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=dense_contextual_features + ["selected-frame-term:final_order"],
    )

    assert "selected-frame-term:final_order" in result.metadata["frame_audit_feature_keys"]
    assert "final_order" in result.metadata["frame_ontology_terms"]


def test_flogic_optimizer_reports_high_signal_frame_ontology_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "selected-frame-term:final_order",
            "flogic:citation_section_number:291",
            "flogic:citation_title:42",
            "flogic:citation_section_has_suffix:false",
        ],
    )

    assert result.metadata["frame_ontology_terms"] == [
        "291",
        "42",
        "false",
        "final_order",
    ]
    assert result.metadata["frame_ontology_high_signal_term_count"] == 2
    assert result.metadata["frame_ontology_high_signal_terms"] == [
        "291",
        "final_order",
    ]
    assert result.metadata["frame_ontology_high_signal_terms_from_feature_keys_count"] == 2
    assert result.metadata["frame_ontology_high_signal_terms_from_feature_keys"] == [
        "291",
        "final_order",
    ]
    assert result.metadata["frame_ontology_high_signal_terms_from_triples_count"] == 0
    assert result.metadata["frame_ontology_high_signal_terms_from_triples"] == []


def test_flogic_optimizer_tracks_zero_digit_count_frame_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:citation_title_number_zero_digit_count:0",
            "slot:source_id_title_section_primary_number_span_trailing_zero_count:1",
            "flogic:citation_section_component_count:3",
        ],
    )

    assert result.metadata["frame_ontology_terms"] == [
        "0",
        "1",
    ]


def test_flogic_optimizer_tracks_contextualized_modal_cue_terms() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            "flogic:modal_cue:after",
            "flogic:modal_cue:by",
            "flogic:citation_title_number_leading_digit:2",
        ],
    )

    assert "modal_cue_after" in result.metadata["frame_ontology_contextualized_terms"]
    assert "modal_cue_by" in result.metadata["frame_ontology_contextualized_terms"]
    assert (
        "citation_title_number_leading_digit_2"
        in result.metadata["frame_ontology_contextualized_terms"]
    )


def test_flogic_optimizer_extracts_frame_features_from_structured_hint_evidence() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            {
                "hint_id": "modal-synthesis-248e6f537d1662f7",
                "priority": 0.795075535022,
                "sample_id": "us-code-26-307-c04b9c0813def639",
                "frame_features": [
                    "selected-frame-term:26 U.S.C. 307",
                    "token:agency",
                ],
            },
            "token:agency",
        ],
    )

    assert result.metadata["frame_feature_keys"] == [
        "flogic:statement_hint:modal-synthesis",
        "selected-frame-term:26 U.S.C. 307",
        "token:agency",
        "us-code-26-307-c04b9c0813def639",
    ]
    assert result.metadata["frame_audit_feature_keys"] == [
        "flogic:statement_hint:modal-synthesis",
        "selected-frame-term:26 U.S.C. 307",
        "us-code-26-307-c04b9c0813def639",
    ]
    assert result.metadata["frame_ontology_terms"] == [
        "26_307",
        "modal_synthesis",
    ]


def test_flogic_optimizer_audits_packet_view_quality_frame_features() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            {
                "hint_id": "modal-synthesis-0597720f6c8ff3bb",
                "frame_features": [
                    "legal-ir-view:deontic.ir",
                    "legal-ir-view:CEC.native",
                    "legal-ir-view:knowledge_graphs.neo4j_compat",
                    "quality:bias",
                    "quality:symbolic:has-formula",
                    "legal-ir-view:TDFOL.prover",
                ],
                "top_family_features": [
                    "legal-ir-view:deontic.ir",
                    "legal-ir-view:CEC.native",
                    "legal-ir-view:knowledge_graphs.neo4j_compat",
                    "quality:bias",
                    "quality:symbolic:has-formula",
                    "legal-ir-view:TDFOL.prover",
                ],
            }
        ],
    )

    assert "quality:bias" in result.metadata["frame_audit_feature_keys"]
    assert "quality:symbolic:has-formula" in result.metadata["frame_audit_feature_keys"]
    assert "bias" in result.metadata["frame_ontology_terms"]
    assert "symbolic_has_formula" in result.metadata["frame_ontology_terms"]
    assert (
        "quality_symbolic_has_formula"
        in result.metadata["frame_ontology_contextualized_terms"]
    )


def test_flogic_optimizer_extracts_semantic_frame_fields_from_structured_features() -> None:
    optimizer = FLogicSemanticOptimizer(
        FLogicOptimizerConfig(
            similarity_threshold=0.0,
            check_ontology_consistency=False,
        )
    )

    result = optimizer.evaluate(
        source_text="source",
        decoded_text="decoded",
        source_embedding=[1.0, 0.0],
        decoded_embedding=[1.0, 0.0],
        kg_triples=[],
        frame_feature_keys=[
            {
                "hint_id": "modal-synthesis-meaningful-frame-fields",
                "selected_frame": "administrative_notice_hearing",
                "predicted_family": "deontic",
                "target_family": "frame",
            },
        ],
    )

    assert result.metadata["frame_audit_feature_keys"] == [
        "family:selected_frame:deontic",
        "family:selected_frame:frame",
        "frame:administrative_notice_hearing",
    ]
    assert result.metadata["frame_ontology_terms"] == [
        "administrative_notice_hearing",
        "deontic",
        "frame",
    ]
