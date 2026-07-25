"""Unit evidence for immutable published and isolated fresh reassessments."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.logic_pipeline import capability_reprobe
from benchmarks.logic_pipeline import holdout_reassessment
from benchmarks.logic_pipeline import matrix_reassessment
from benchmarks.logic_pipeline import pilot_reassessment
from benchmarks.logic_pipeline import reassessment_reports
from benchmarks.logic_pipeline import report
from benchmarks.logic_pipeline.reassessment_namespace import (
    PUBLISHED_PREDECESSOR_ARTIFACTS,
    PUBLISHED_REASSESSMENT_RUN_ID,
    PUBLISHED_RUNBOOK,
    PUBLISHED_RUNTIME_LOCKS,
    ReassessmentNamespaceError,
    ReassessmentRunLayout,
    reject_published_write_targets,
)


FRESH_RUN_ID = "post-repair-reassessment-test"


def test_fresh_layout_has_distinct_artifact_cache_and_snapshot_paths(
    tmp_path: Path,
) -> None:
    published = ReassessmentRunLayout.for_run(PUBLISHED_REASSESSMENT_RUN_ID)
    fresh = ReassessmentRunLayout.for_run(FRESH_RUN_ID)
    custom = ReassessmentRunLayout.for_run(
        FRESH_RUN_ID,
        benchmark_root=tmp_path / "isolated-benchmark",
    )

    assert fresh.run_id == FRESH_RUN_ID
    assert fresh.run_paths.run_root != published.run_paths.run_root
    assert fresh.receipt_directory != published.receipt_directory
    assert fresh.matrix_root != published.matrix_root
    assert fresh.matrix_index != published.matrix_index
    assert fresh.capability_snapshot != published.capability_snapshot
    assert fresh.matrix_snapshot != published.matrix_snapshot
    assert fresh.frontend_report != published.frontend_report
    assert fresh.frontend_receipt_directory != (
        published.frontend_receipt_directory
    )
    assert fresh.frontend_receipt_index != published.frontend_receipt_index
    assert fresh.pilot_report != published.pilot_report
    assert fresh.pilot_snapshot != published.pilot_snapshot
    assert fresh.holdout_report != published.holdout_report
    assert fresh.holdout_snapshot != published.holdout_snapshot
    assert fresh.holdout_execution_root != published.holdout_execution_root
    assert fresh.replay_index != published.replay_index
    assert fresh.statistics_report != published.statistics_report
    assert fresh.reports_snapshot != published.reports_snapshot
    assert fresh.final_decision != published.final_decision
    assert fresh.run_paths.cache != published.run_paths.cache
    assert fresh.cache_namespace.endswith(f"/{FRESH_RUN_ID}")
    assert custom.run_paths.run_root == (
        tmp_path / "isolated-benchmark" / FRESH_RUN_ID
    )
    assert custom.run_paths.cache.is_relative_to(custom.run_paths.run_root)
    assert custom.matrix_root.is_relative_to(custom.run_paths.run_root)
    assert all(
        FRESH_RUN_ID in path.parts
        for path in (
            fresh.baseline_manifest,
            fresh.receipt_directory,
            fresh.capability_snapshot,
            fresh.matrix_root,
            fresh.matrix_index,
            fresh.matrix_snapshot,
            fresh.frontend_report,
            fresh.frontend_receipt_directory,
            fresh.frontend_receipt_index,
            fresh.pilot_report,
            fresh.pilot_snapshot,
            fresh.holdout_report,
            fresh.holdout_snapshot,
            fresh.holdout_execution_root,
            fresh.replay_index,
            fresh.statistics_report,
            fresh.reports_snapshot,
            fresh.final_decision,
            fresh.run_paths.cache,
        )
    )


def test_published_run_and_paths_are_rejected_before_live_work(
    tmp_path: Path,
) -> None:
    legacy_probe_called = False

    def forbidden_probe(*_args: object, **_kwargs: object) -> object:
        nonlocal legacy_probe_called
        legacy_probe_called = True
        raise AssertionError("live probe must not start")

    with pytest.raises(
        capability_reprobe.CapabilityFreezeError,
        match="published immutable evidence",
    ):
        capability_reprobe.run_live_capability_reprobe(
            repository_root=tmp_path,
            run_id=PUBLISHED_REASSESSMENT_RUN_ID,
            legacy_probe=forbidden_probe,
        )
    assert legacy_probe_called is False

    with pytest.raises(
        matrix_reassessment.MatrixReassessmentError,
        match="published immutable evidence",
    ):
        matrix_reassessment.execute_reassessment_matrix(
            repository_root=tmp_path,
            run_id=PUBLISHED_REASSESSMENT_RUN_ID,
        )

    with pytest.raises(
        ReassessmentNamespaceError,
        match="reuses published immutable",
    ):
        reject_published_write_targets(
            repository_root=tmp_path,
            run_id=FRESH_RUN_ID,
            targets=(
                ReassessmentRunLayout.for_run(
                    PUBLISHED_REASSESSMENT_RUN_ID
                ).matrix_root,
            ),
        )


def test_fresh_matrix_rejects_explicit_published_output_before_loading_receipts(
    tmp_path: Path,
) -> None:
    published = ReassessmentRunLayout.for_run(PUBLISHED_REASSESSMENT_RUN_ID)

    with pytest.raises(
        matrix_reassessment.MatrixReassessmentError,
        match="reuses published immutable",
    ):
        matrix_reassessment.execute_reassessment_matrix(
            repository_root=tmp_path,
            run_id=FRESH_RUN_ID,
            output_root=published.matrix_root,
        )


def test_custom_benchmark_root_protects_its_published_namespace(
    tmp_path: Path,
) -> None:
    benchmark_root = tmp_path / "isolated-benchmark"
    published = ReassessmentRunLayout.for_run(
        PUBLISHED_REASSESSMENT_RUN_ID,
        benchmark_root=benchmark_root,
    )
    fresh = ReassessmentRunLayout.for_run(
        FRESH_RUN_ID,
        benchmark_root=benchmark_root,
    )

    with pytest.raises(
        ReassessmentNamespaceError,
        match="reuses published immutable",
    ):
        reject_published_write_targets(
            repository_root=tmp_path,
            run_id=FRESH_RUN_ID,
            targets=(published.matrix_root,),
            benchmark_root=benchmark_root,
        )

    assert (
        reject_published_write_targets(
            repository_root=tmp_path,
            run_id=FRESH_RUN_ID,
            targets=(fresh.matrix_root,),
            benchmark_root=benchmark_root,
        )
        == fresh
    )


@pytest.mark.parametrize(
    "protected_path",
    (
        PUBLISHED_RUNBOOK,
        *PUBLISHED_RUNTIME_LOCKS,
        *PUBLISHED_PREDECESSOR_ARTIFACTS,
    ),
)
def test_fresh_writers_cannot_target_published_supporting_evidence(
    tmp_path: Path,
    protected_path: Path,
) -> None:
    with pytest.raises(
        ReassessmentNamespaceError,
        match="reuses published immutable",
    ):
        reject_published_write_targets(
            repository_root=tmp_path,
            run_id=FRESH_RUN_ID,
            targets=(protected_path,),
        )


def test_all_downstream_writers_reject_published_run_before_source_loading(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        pilot_reassessment.PilotReassessmentError,
        match="published immutable evidence",
    ):
        pilot_reassessment.write_pilot_reassessment_report(
            repository_root=tmp_path,
            run_id=PUBLISHED_REASSESSMENT_RUN_ID,
        )
    with pytest.raises(
        holdout_reassessment.HoldoutReassessmentError,
        match="published immutable evidence",
    ):
        holdout_reassessment.write_holdout_reassessment_report(
            repository_root=tmp_path,
            run_id=PUBLISHED_REASSESSMENT_RUN_ID,
        )
    with pytest.raises(
        reassessment_reports.ReassessmentReportsError,
        match="published immutable evidence",
    ):
        reassessment_reports.write_reassessment_reports(
            repository_root=tmp_path,
            run_id=PUBLISHED_REASSESSMENT_RUN_ID,
        )
    with pytest.raises(
        report.FinalDecisionValidationError,
        match="published immutable evidence",
    ):
        report.write_reassessment_final_decision(
            repository_root=tmp_path,
            run_id=PUBLISHED_REASSESSMENT_RUN_ID,
        )
