"""Tests for deterministic legal parser metrics."""

from ipfs_datasets_py.logic.deontic import (
    summarize_parser_elements,
    summarize_phase8_parser_metrics,
)
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_summarize_parser_elements_reports_quality_and_warning_rates() -> None:
    elements = extract_normative_elements(
        """5.01.010 General.
The tenant must pay rent.
The Secretary shall publish the notice except as provided in section 9.99.999."""
    )

    summary = summarize_parser_elements(elements)

    assert summary["element_count"] == 2
    assert summary["schema_valid_count"] == 2
    assert summary["schema_valid_rate"] == 1.0
    assert summary["source_span_valid_count"] == 2
    assert summary["source_span_valid_rate"] == 1.0
    assert summary["proof_ready_count"] == 1
    assert summary["proof_ready_rate"] == 0.5
    assert summary["repair_required_count"] == 1
    assert summary["repair_required_rate"] == 0.5
    assert summary["average_scaffold_quality"] > 0.0
    assert summary["warning_distribution"]["cross_reference_requires_resolution"] == 1
    assert summary["warning_distribution"]["exception_requires_scope_review"] == 1
    assert summary["norm_type_distribution"] == {"obligation": 2}
    assert summary["modality_distribution"] == {"O": 2}
    assert summary["cross_reference_resolution_rate"] == 0.0


def test_summarize_parser_elements_uses_ir_formula_repair_clearance() -> None:
    elements = [
        extract_normative_elements("This section applies to food carts.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]

    assert [element["promotable_to_theorem"] for element in elements] == [
        False,
        False,
        False,
        False,
    ]
    assert [element["llm_repair"]["required"] for element in elements] == [
        False,
        False,
        False,
        True,
    ]

    summary = summarize_parser_elements(elements)

    assert summary["element_count"] == 4
    assert summary["proof_ready_count"] == 3
    assert summary["proof_ready_rate"] == 0.75
    assert summary["repair_required_count"] == 1
    assert summary["repair_required_rate"] == 0.25
    assert summary["warning_distribution"]["cross_reference_requires_resolution"] == 3
    assert summary["warning_distribution"]["exception_requires_scope_review"] == 2
    assert summary["warning_distribution"]["override_clause_requires_precedence_review"] == 1
    assert summary["cross_reference_resolution_rate"] == 0.666667


def test_summarize_parser_elements_handles_empty_input() -> None:
    summary = summarize_parser_elements([])

    assert summary["element_count"] == 0
    assert summary["schema_valid_rate"] == 0.0
    assert summary["warning_distribution"] == {}
    assert summary["phase8_source_count"] == 0
    assert summary["phase8_parser_capability_profile_count"] == 0
    assert summary["phase8_parser_capability_family_distribution"] == {}
    assert summary["phase8_parser_capability_formula_ready_rate"] == 0.0
    assert summary["phase8_quality_record_count"] == 0
    assert summary["phase8_decoder_grounded_phrase_rate"] == 0.0
    assert summary["phase8_prover_syntax_valid_rate"] == 0.0


def test_summarize_parser_elements_includes_phase8_quality_metrics() -> None:
    elements = [
        extract_normative_elements("The tenant must pay rent monthly.")[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]

    summary = summarize_parser_elements(elements)

    assert summary["element_count"] == 2
    assert summary["proof_ready_count"] == 1
    assert summary["phase8_source_count"] == 2
    assert summary["phase8_record_build_error_count"] == 0
    assert summary["phase8_decoder_reconstruction_record_count"] == 2
    assert summary["phase8_decoder_grounded_phrase_rate"] == 1.0
    assert summary["phase8_decoder_ungrounded_phrase_rate"] == 0.0
    assert summary["phase8_decoder_records_with_missing_slots"] == 0
    assert summary["phase8_parser_capability_profile_count"] == 2
    assert summary["phase8_parser_capability_family_distribution"] == {
        "ordinary_duty": 1,
        "procedural_event_duty": 1,
    }
    assert summary["phase8_parser_capability_formula_ready_rate"] == 0.5
    assert summary["phase8_parser_capability_source_grounding_rate"] == 1.0
    assert summary["phase8_parser_capability_decoder_grounding_rate"] == 1.0
    assert summary["phase8_parser_capability_requires_validation_count"] == 1
    assert summary["phase8_parser_capability_repair_required_count"] == 1
    assert summary["phase8_prover_required_target_count"] == 5
    assert summary["phase8_prover_present_required_target_count"] == 5
    assert summary["phase8_prover_syntax_valid_rate"] == 1.0
    assert summary["phase8_prover_corpus_source_count"] == 2
    assert summary["phase8_prover_corpus_complete_source_count"] == 2
    assert summary["phase8_prover_corpus_source_complete_rate"] == 1.0
    assert summary["phase8_prover_corpus_formal_syntax_valid_source_rate"] == 1.0
    assert summary["phase8_prover_corpus_source_identity_complete"] is True
    assert summary["phase8_quality_record_count"] == 2
    assert summary["phase8_quality_complete_count"] == 0
    assert summary["phase8_quality_complete_rate"] == 0.0
    assert summary["phase8_quality_requires_validation_count"] == 2
    assert summary["phase8_quality_requires_validation_rate"] == 1.0
    assert summary["decoder_reconstruction_metrics"]["proof_ready_count"] == 1
    assert summary["prover_syntax_target_coverage"]["all_required_passed"] is True
    assert summary["prover_syntax_corpus_coverage"]["all_sources_complete"] is True
    assert summary["prover_syntax_corpus_coverage"][
        "all_sources_required_targets_passed"
    ] is True
    assert summary["phase8_quality_summary"]["requires_validation"] is True
    assert summary["phase8_quality_summary"]["prover_syntax_corpus_coverage"][
        "source_complete_rate"
    ] == 1.0
    assert summary["parser_capability_profile_metrics"]["requires_validation"] is True
    assert summary["parser_capability_profile_metrics"][
        "coverage_blocker_distribution"
    ] == {
        "cross_reference_requires_resolution": 1,
        "exception_requires_scope_review": 1,
        "llm_repair_required": 1,
    }
    assert "missing_reconstruction_slot:cross_references" in summary[
        "phase8_coverage_blocker_distribution"
    ]


def test_summarize_phase8_parser_metrics_exposes_dedicated_surface() -> None:
    elements = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )

    summary = summarize_phase8_parser_metrics(elements)

    assert summary["phase8_source_count"] == 1
    assert summary["phase8_decoder_reconstruction_record_count"] == 1
    assert summary["phase8_prover_required_target_count"] == 5
    assert summary["phase8_prover_syntax_valid_rate"] == 1.0
    assert summary["phase8_prover_corpus_source_count"] == 1
    assert summary["phase8_prover_corpus_source_complete_rate"] == 1.0
    assert summary["phase8_ir_grounded_slot_rate"] > 0.0
    assert summary["phase8_quality_record_count"] == 1
    assert summary["phase8_quality_summary"]["prover_syntax_target_coverage"][
        "all_required_passed"
    ] is True


def test_phase8_metrics_summarize_parser_capability_families() -> None:
    elements = [
        extract_normative_elements("The tenant must pay rent monthly.")[0],
        extract_normative_elements(
            "The Director is delegated authority to approve permits."
        )[0],
        extract_normative_elements(
            "The Director shall issue a permit within 10 days after application."
        )[0],
        extract_normative_elements(
            "A violation is punishable by a civil fine of not less than $100 and not more than $500 per violation."
        )[0],
        *extract_normative_elements(
            "The Secretary shall (1) establish procedures; (2) submit a report; and (3) maintain records.",
            expand_enumerations=True,
        ),
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]

    summary = summarize_phase8_parser_metrics(elements)
    capability = summary["parser_capability_profile_metrics"]

    assert summary["phase8_source_count"] == 8
    assert summary["phase8_parser_capability_profile_count"] == 8
    assert summary["phase8_parser_capability_family_distribution"] == {
        "authority_grant": 1,
        "enumerated_child_duty": 3,
        "ordinary_duty": 1,
        "procedural_event_duty": 1,
        "sanction_clause": 1,
        "temporal_deadline_duty": 1,
    }
    assert capability["record_count"] == 8
    assert capability["capability_family_distribution"] == summary[
        "phase8_parser_capability_family_distribution"
    ]
    assert capability["formula_proof_ready_count"] == 7
    assert capability["formula_proof_ready_rate"] == 0.875
    assert capability["repair_required_count"] == 1
    assert capability["requires_validation_count"] == 1
    assert capability["source_grounding_complete_count"] == 8
    assert capability["decoder_slot_grounding_complete_count"] == 8
    assert capability["mean_source_grounded_slot_rate"] == 1.0
    assert capability["mean_decoder_grounded_slot_rate"] == 1.0
    assert capability["all_profiles_formula_proof_ready"] is False
    assert capability["all_profiles_source_grounded"] is True
    assert capability["all_profiles_decoder_grounded"] is True
    assert capability["coverage_blocker_distribution"] == {
        "cross_reference_requires_resolution": 1,
        "exception_requires_scope_review": 1,
        "llm_repair_required": 1,
    }

    blocked = elements[-1]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
