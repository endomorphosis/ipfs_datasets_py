"""Tests for Phase 8 prover-syntax target coverage reporting."""

from ipfs_datasets_py.logic.deontic.exports import (
    LOCAL_PROVER_SYNTAX_TARGETS,
    build_prover_syntax_target_coverage_record,
    summarize_prover_syntax_target_corpus_coverage,
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
    assert summary["target_status_by_target"] == {
        "frame_logic": "passed",
        "deontic_cec": "passed",
        "fol": "passed",
        "deontic_fol": "missing",
        "deontic_temporal_fol": "missing",
    }
    assert summary["target_status_matrix_complete"] is False
    assert summary["target_status_matrix_requires_validation"] is True
    assert summary["target_status_matrix_blockers"] == [
        "missing_prover_syntax_target:deontic_fol",
        "missing_prover_syntax_target:deontic_temporal_fol",
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
    assert summary["target_status_by_target"] == {
        "frame_logic": "passed",
        "deontic_cec": "failed",
        "fol": "skipped",
        "deontic_fol": "passed",
        "deontic_temporal_fol": "passed",
    }
    assert summary["target_status_matrix_blockers"] == [
        "failed_prover_syntax_target:deontic_cec",
        "skipped_prover_syntax_target:fol",
    ]
    assert summary["target_status_matrix"][1]["failed"] is True
    assert summary["target_status_matrix"][2]["skipped"] is True
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
    assert summary["target_status_matrix_complete"] is True
    assert summary["target_status_matrix_requires_validation"] is False
    assert summary["target_status_matrix_blockers"] == []
    assert summary["target_record_count_by_target"] == {
        target: 1 for target in LOCAL_PROVER_SYNTAX_TARGETS
    }
    assert summary["all_required_passed"] is True
    assert summary["syntax_valid_rate"] == 1.0


def test_prover_syntax_target_coverage_matrix_reports_duplicate_records():
    records = [
        {"prover_target": target, "syntax_valid": True}
        for target in LOCAL_PROVER_SYNTAX_TARGETS
    ]
    records.append({"prover_target": "fol", "syntax_valid": True})

    summary = summarize_prover_syntax_target_coverage(records)
    fol_row = next(row for row in summary["target_status_matrix"] if row["target"] == "fol")

    assert summary["all_required_passed"] is True
    assert summary["target_status_matrix_complete"] is False
    assert summary["target_status_matrix_requires_validation"] is True
    assert summary["target_duplicate_record_count"] == 1
    assert summary["target_duplicate_targets"] == ["fol"]
    assert summary["target_record_count_by_target"]["fol"] == 2
    assert fol_row["status"] == "passed"
    assert fol_row["duplicate"] is True
    assert fol_row["statuses"] == ["passed", "passed"]
    assert fol_row["blockers"] == ["duplicate_prover_syntax_target_record:fol:2"]
    assert summary["target_status_matrix_blockers"] == [
        "duplicate_prover_syntax_target_record:fol:2"
    ]


def test_prover_syntax_target_corpus_coverage_groups_raw_rows_by_source():
    records = [
        {
            "source_id": "deontic:complete",
            "prover_target": target,
            "syntax_valid": True,
        }
        for target in LOCAL_PROVER_SYNTAX_TARGETS
    ]
    records.extend(
        [
            {
                "source_id": "deontic:partial",
                "prover_target": "frame_logic",
                "syntax_valid": True,
            },
            {
                "source_id": "deontic:partial",
                "prover_target": "deontic_cec",
                "syntax_valid": False,
            },
            {
                "source_id": "deontic:partial",
                "prover_target": "fol",
                "status": "skipped",
            },
        ]
    )

    summary = summarize_prover_syntax_target_corpus_coverage(records)

    assert summary["source_count"] == 2
    assert summary["complete_source_count"] == 1
    assert summary["incomplete_source_count"] == 1
    assert summary["sources_with_complete_required_targets"] == ["deontic:complete"]
    assert summary["sources_requiring_validation"] == ["deontic:partial"]
    assert summary["source_complete_rate"] == 0.5
    assert summary["formal_syntax_valid_source_rate"] == 0.5
    assert summary["source_status_by_source"]["deontic:partial"] == {
        "frame_logic": "passed",
        "deontic_cec": "failed",
        "fol": "skipped",
        "deontic_fol": "missing",
        "deontic_temporal_fol": "missing",
    }
    assert summary["source_missing_targets_by_source"]["deontic:partial"] == [
        "deontic_fol",
        "deontic_temporal_fol",
    ]
    assert summary["coverage_blocker_distribution"] == {
        "failed_prover_syntax_target:deontic_cec": 1,
        "missing_prover_syntax_target:deontic_fol": 1,
        "missing_prover_syntax_target:deontic_temporal_fol": 1,
        "skipped_prover_syntax_target:fol": 1,
    }


def test_prover_syntax_target_corpus_coverage_accepts_persisted_coverage_rows():
    complete = build_prover_syntax_target_coverage_record(
        "deontic:complete",
        [
            {"target": target, "syntax_valid": True}
            for target in LOCAL_PROVER_SYNTAX_TARGETS
        ],
    )
    duplicate = build_prover_syntax_target_coverage_record(
        "deontic:duplicate",
        [
            {"target": target, "syntax_valid": True}
            for target in LOCAL_PROVER_SYNTAX_TARGETS
        ]
        + [{"target": "fol", "syntax_valid": True}],
    )

    summary = summarize_prover_syntax_target_corpus_coverage([complete, duplicate])

    assert summary["record_count"] == 2
    assert summary["source_count"] == 2
    assert summary["complete_source_count"] == 1
    assert summary["sources_requiring_validation"] == ["deontic:duplicate"]
    assert summary["target_duplicate_record_count"] == 1
    assert summary["target_presence_distribution"] == {
        target: 2 for target in sorted(LOCAL_PROVER_SYNTAX_TARGETS)
    }
    assert summary["target_pass_distribution"] == {
        target: 2 for target in sorted(LOCAL_PROVER_SYNTAX_TARGETS)
    }
    assert summary["coverage_blocker_distribution"] == {
        "duplicate_prover_syntax_target_record:fol:2": 1
    }
    assert summary["all_sources_complete"] is False
    assert summary["all_sources_required_targets_passed"] is True


def test_prover_syntax_target_corpus_coverage_marks_missing_source_ids_incomplete():
    records = [
        {
            "prover_target": target,
            "syntax_valid": True,
        }
        for target in LOCAL_PROVER_SYNTAX_TARGETS
    ]

    summary = summarize_prover_syntax_target_corpus_coverage(records)

    assert summary["record_count"] == 5
    assert summary["source_count"] == 1
    assert summary["source_id_missing_record_count"] == 5
    assert summary["sources_with_missing_source_id"] == ["unknown"]
    assert summary["source_identity_complete"] is False
    assert summary["complete_source_count"] == 0
    assert summary["sources_requiring_validation"] == ["unknown"]
    assert summary["source_blockers_by_source"]["unknown"] == [
        "missing_prover_syntax_source_id"
    ]
    assert summary["coverage_blocker_distribution"] == {
        "missing_prover_syntax_source_id": 1
    }
    assert summary["all_sources_complete"] is False
    assert summary["all_sources_required_targets_passed"] is True


def test_prover_syntax_target_corpus_coverage_marks_persisted_row_missing_source_id():
    coverage = build_prover_syntax_target_coverage_record(
        "",
        [
            {"target": target, "syntax_valid": True}
            for target in LOCAL_PROVER_SYNTAX_TARGETS
        ],
    )

    summary = summarize_prover_syntax_target_corpus_coverage([coverage])

    assert summary["source_count"] == 1
    assert summary["source_id_missing_record_count"] == 1
    assert summary["sources_with_missing_source_id"] == ["unknown"]
    assert summary["source_status_by_source"]["unknown"] == {
        target: "passed" for target in LOCAL_PROVER_SYNTAX_TARGETS
    }
    assert summary["source_missing_targets_by_source"]["unknown"] == []
    assert summary["source_blockers_by_source"]["unknown"] == [
        "missing_prover_syntax_source_id"
    ]
    assert summary["complete_source_count"] == 0
    assert summary["formal_syntax_valid_source_rate"] == 1.0


def test_prover_target_coverage_slice_preserves_numbered_exception_repair_blocker():
    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
