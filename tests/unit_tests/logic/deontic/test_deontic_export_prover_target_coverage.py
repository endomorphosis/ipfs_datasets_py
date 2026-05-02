"""Tests for Phase 8 prover-syntax target coverage reporting."""

from ipfs_datasets_py.logic.deontic.exports import (
    LOCAL_PROVER_SYNTAX_TARGETS,
    summarize_prover_syntax_target_coverage,
)
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_prover_syntax_target_coverage_requires_all_local_targets():
    records = [
        {"target": "frame_logic", "syntax_valid": True},
        {"target": "deontic_cec", "status": "passed"},
        {"target": "fol", "parse_status": "valid"},
    ]

    summary = summarize_prover_syntax_target_coverage(records)

    assert summary["required_targets"] == list(LOCAL_PROVER_SYNTAX_TARGETS)
    assert summary["record_count"] == 3
    assert summary["present_required_target_count"] == 3
    assert summary["passed_targets"] == ["deontic_cec", "fol", "frame_logic"]
    assert summary["failed_targets"] == []
    assert summary["skipped_targets"] == []
    assert summary["missing_targets"] == [
        "deontic_fol",
        "deontic_temporal_fol",
    ]
    assert summary["all_required_passed"] is False
    assert summary["syntax_valid_rate"] == 0.6


def test_prover_syntax_target_coverage_reports_failed_and_skipped_targets():
    records = [
        {"target_name": "frame_logic", "syntax_valid": True},
        {"target_name": "deontic_cec", "syntax_valid": False},
        {"target_name": "fol", "status": "skipped"},
        {"target_name": "deontic_fol", "parse_status": "valid"},
        {"target_name": "deontic_temporal_fol", "status": "passed"},
    ]

    summary = summarize_prover_syntax_target_coverage(records)

    assert summary["passed_targets"] == [
        "deontic_fol",
        "deontic_temporal_fol",
        "frame_logic",
    ]
    assert summary["failed_targets"] == ["deontic_cec"]
    assert summary["skipped_targets"] == ["fol"]
    assert summary["missing_targets"] == []
    assert summary["all_required_passed"] is False
    assert summary["syntax_valid_rate"] == 0.6


def test_prover_syntax_target_coverage_passes_when_all_required_targets_pass():
    records = [
        {"prover_target": target, "syntax_valid": True}
        for target in LOCAL_PROVER_SYNTAX_TARGETS
    ]

    summary = summarize_prover_syntax_target_coverage(records)

    assert summary["passed_targets"] == sorted(LOCAL_PROVER_SYNTAX_TARGETS)
    assert summary["failed_targets"] == []
    assert summary["skipped_targets"] == []
    assert summary["missing_targets"] == []
    assert summary["all_required_passed"] is True
    assert summary["syntax_valid_rate"] == 1.0


def test_prover_target_coverage_slice_preserves_numbered_exception_repair_blocker():
    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
