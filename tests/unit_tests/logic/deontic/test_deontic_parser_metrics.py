"""Tests for deterministic legal parser metrics."""

from ipfs_datasets_py.logic.deontic import summarize_parser_elements
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


def test_summarize_parser_elements_handles_empty_input() -> None:
    summary = summarize_parser_elements([])

    assert summary["element_count"] == 0
    assert summary["schema_valid_rate"] == 0.0
    assert summary["warning_distribution"] == {}

