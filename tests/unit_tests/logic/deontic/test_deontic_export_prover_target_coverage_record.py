"""Tests for prover-syntax target coverage export records."""

from ipfs_datasets_py.logic.deontic.exports import (
    LOCAL_PROVER_SYNTAX_TARGETS,
    build_prover_syntax_target_coverage_record,
)
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def _record(target, status="passed"):
    return {
        "target": target,
        "status": status,
        "syntax_valid": status == "passed",
    }


def test_prover_target_coverage_record_marks_complete_local_report_valid():
    records = [_record(target) for target in LOCAL_PROVER_SYNTAX_TARGETS]

    coverage = build_prover_syntax_target_coverage_record("deontic:proof-ready", records)

    assert coverage["prover_syntax_summary_id"].startswith("prover-syntax-coverage:")
    assert coverage["source_id"] == "deontic:proof-ready"
    assert coverage["target_logic"] == "local_prover_syntax"
    assert coverage["required_targets"] == list(LOCAL_PROVER_SYNTAX_TARGETS)
    assert coverage["present_required_target_count"] == len(LOCAL_PROVER_SYNTAX_TARGETS)
    assert coverage["record_count"] == len(LOCAL_PROVER_SYNTAX_TARGETS)
    assert coverage["syntax_valid_rate"] == 1.0
    assert coverage["formal_syntax_valid"] is True
    assert coverage["requires_validation"] is False
    assert coverage["coverage_blockers"] == []
    assert coverage["coverage_summary"]["all_required_passed"] is True


def test_prover_target_coverage_record_blocks_missing_required_targets():
    records = [
        _record("frame_logic"),
        _record("deontic_cec"),
        _record("fol"),
    ]

    coverage = build_prover_syntax_target_coverage_record("deontic:partial", records)

    assert coverage["formal_syntax_valid"] is False
    assert coverage["requires_validation"] is True
    assert coverage["present_required_target_count"] == 3
    assert coverage["syntax_valid_rate"] == 0.6
    assert coverage["coverage_summary"]["missing_targets"] == [
        "deontic_fol",
        "deontic_temporal_fol",
    ]
    assert coverage["coverage_blockers"] == [
        "missing_prover_syntax_target:deontic_fol",
        "missing_prover_syntax_target:deontic_temporal_fol",
    ]


def test_prover_target_coverage_record_blocks_failed_and_skipped_targets():
    records = [
        _record("frame_logic"),
        _record("deontic_cec", "failed"),
        _record("fol"),
        _record("deontic_fol", "skipped"),
        _record("deontic_temporal_fol"),
    ]

    coverage = build_prover_syntax_target_coverage_record("deontic:mixed", records)

    assert coverage["formal_syntax_valid"] is False
    assert coverage["requires_validation"] is True
    assert coverage["coverage_summary"]["failed_targets"] == ["deontic_cec"]
    assert coverage["coverage_summary"]["skipped_targets"] == ["deontic_fol"]
    assert "failed_prover_syntax_target:deontic_cec" in coverage["coverage_blockers"]
    assert "skipped_prover_syntax_target:deontic_fol" in coverage["coverage_blockers"]


def test_prover_target_coverage_record_slice_preserves_numbered_exception_repair_blocker():
    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
