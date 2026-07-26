"""Run-scoped paths and immutability guards for HSSL reassessments.

``reassessment-v2`` is a published evidence identity, not a mutable execution
slot.  Read-only validators continue to default to that identity, while every
new source reconciliation, capability probe, and matrix execution must select
a distinct run id.  This module keeps that rule and all derived artifact/cache
paths in one dependency-light boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterable

from . import BENCHMARK_ID, DEFAULT_BENCHMARK_ROOT, RunPaths


PUBLISHED_REASSESSMENT_RUN_ID: Final = "reassessment-v2"
PUBLISHED_CAPABILITY_SNAPSHOT: Final = (
    Path("docs")
    / "performance_snapshots"
    / "2026-07-24_hssl_reassessment_capability_inventory.json"
)
PUBLISHED_MATRIX_SNAPSHOT: Final = (
    Path("docs")
    / "performance_snapshots"
    / "2026-07-24_hssl_reassessment_matrix.json"
)
PUBLISHED_PILOT_SNAPSHOT: Final = (
    Path("docs")
    / "performance_snapshots"
    / "2026-07-24_hssl_reassessment_pilot_shortlist.json"
)
PUBLISHED_HOLDOUT_SNAPSHOT: Final = (
    Path("docs")
    / "performance_snapshots"
    / "2026-07-24_hssl_reassessment_holdout.json"
)
PUBLISHED_REPORTS_SNAPSHOT: Final = (
    Path("docs")
    / "performance_snapshots"
    / "2026-07-24_hssl_reassessment_reports.json"
)
PUBLISHED_FINAL_DECISION: Final = (
    Path("docs")
    / "performance_snapshots"
    / "2026-07-24_hammer_symai_spacy_leanstral_final_decision_v2.json"
)
PUBLISHED_RUNBOOK: Final = (
    Path("docs")
    / "implementation"
    / "runbooks"
    / "hammer_symai_spacy_leanstral_benchmark.md"
)
PUBLISHED_RUNTIME_LOCKS: Final = (
    Path("benchmarks") / "logic_pipeline" / "runtime_env" / "spacy.lock",
    Path("benchmarks")
    / "logic_pipeline"
    / "runtime_env"
    / "symai-router.lock",
    Path("benchmarks")
    / "logic_pipeline"
    / "runtime_env"
    / "leanstral.lock",
)
PUBLISHED_PREDECESSOR_ARTIFACTS: Final = (
    Path("workspace")
    / "benchmarks"
    / BENCHMARK_ID
    / "a0-baseline-v1"
    / "state"
    / "baseline-manifest.json",
    *(
        Path("workspace") / "benchmarks" / BENCHMARK_ID / "results" / name
        for name in (
            "frontend-overlap-v1.json",
            "proof-overlap-ordering-v1.json",
            "pilot-shortlist-v1.json",
            "holdout-evaluation-v1.json",
        )
    ),
    Path("docs")
    / "performance_snapshots"
    / "2026-07-24_hammer_symai_spacy_leanstral_final_decision.json",
)


class ReassessmentNamespaceError(ValueError):
    """Raised when a mutable run could collide with published evidence."""


@dataclass(frozen=True, slots=True)
class ReassessmentRunLayout:
    """All source, execution, analysis, and decision paths for one run id."""

    run_id: str
    run_paths: RunPaths
    baseline_manifest: Path
    receipt_directory: Path
    capability_snapshot: Path
    matrix_root: Path
    matrix_index: Path
    matrix_snapshot: Path
    frontend_report: Path
    frontend_receipt_directory: Path
    frontend_receipt_index: Path
    pilot_report: Path
    pilot_snapshot: Path
    holdout_report: Path
    holdout_snapshot: Path
    holdout_execution_root: Path
    replay_root: Path
    replay_index: Path
    statistics_report: Path
    reports_snapshot: Path
    final_decision: Path
    cache_namespace: str

    @classmethod
    def for_run(
        cls,
        run_id: str,
        *,
        benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    ) -> "ReassessmentRunLayout":
        """Derive paths without creating files or directories."""

        run_paths = RunPaths.for_run(run_id, benchmark_root=benchmark_root)
        if (
            run_id == PUBLISHED_REASSESSMENT_RUN_ID
            and Path(benchmark_root) == DEFAULT_BENCHMARK_ROOT
        ):
            capability_snapshot = PUBLISHED_CAPABILITY_SNAPSHOT
            matrix_snapshot = PUBLISHED_MATRIX_SNAPSHOT
            pilot_snapshot = PUBLISHED_PILOT_SNAPSHOT
            holdout_snapshot = PUBLISHED_HOLDOUT_SNAPSHOT
            reports_snapshot = PUBLISHED_REPORTS_SNAPSHOT
            final_decision = PUBLISHED_FINAL_DECISION
        else:
            # Fresh snapshots are run artifacts. Publication into docs is a
            # separate reviewed action, so a retry cannot replace a public
            # decision artifact merely by choosing a new run id.
            capability_snapshot = (
                run_paths.results / "capability-reassessment-snapshot.json"
            )
            matrix_snapshot = (
                run_paths.results / "matrix-reassessment-snapshot.json"
            )
            pilot_snapshot = (
                run_paths.results / "pilot-shortlist-snapshot.json"
            )
            holdout_snapshot = (
                run_paths.results / "holdout-evaluation-snapshot.json"
            )
            reports_snapshot = (
                run_paths.results / "reassessment-reports-snapshot.json"
            )
            final_decision = (
                run_paths.results / "final-decision.json"
            )
        return cls(
            run_id=run_id,
            run_paths=run_paths,
            baseline_manifest=run_paths.state / "baseline-manifest.json",
            receipt_directory=run_paths.receipts,
            capability_snapshot=capability_snapshot,
            matrix_root=run_paths.results / "matrix",
            matrix_index=run_paths.results / "matrix-execution-v2.json",
            matrix_snapshot=matrix_snapshot,
            frontend_report=run_paths.results / "frontend-semantic-report.json",
            frontend_receipt_directory=(
                run_paths.receipts / "semantic-validation"
            ),
            frontend_receipt_index=(
                run_paths.results / "frontend-semantic-receipts.json"
            ),
            pilot_report=run_paths.results / "pilot-shortlist-v2.json",
            pilot_snapshot=pilot_snapshot,
            holdout_report=run_paths.results / "holdout-evaluation-v2.json",
            holdout_snapshot=holdout_snapshot,
            holdout_execution_root=run_paths.run_root / "holdout",
            replay_root=run_paths.run_root / "replay",
            replay_index=run_paths.run_root / "replay" / "replay-index.json",
            statistics_report=run_paths.results / "statistics.json",
            reports_snapshot=reports_snapshot,
            final_decision=final_decision,
            cache_namespace=f"{BENCHMARK_ID}/{run_id}",
        )


def require_fresh_reassessment_run(
    run_id: str,
    *,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> ReassessmentRunLayout:
    """Return a validated layout, rejecting the published read-only run."""

    try:
        layout = ReassessmentRunLayout.for_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ValueError as exc:
        raise ReassessmentNamespaceError(str(exc)) from exc
    if run_id == PUBLISHED_REASSESSMENT_RUN_ID:
        raise ReassessmentNamespaceError(
            f"{PUBLISHED_REASSESSMENT_RUN_ID!r} is published immutable evidence "
            "and may only be validated; choose a distinct fresh run_id"
        )
    return layout


def reject_published_write_targets(
    *,
    repository_root: str | Path,
    run_id: str,
    targets: Iterable[str | Path],
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> ReassessmentRunLayout:
    """Reject fresh writes that resolve into any published v2 artifact root."""

    layout = require_fresh_reassessment_run(
        run_id,
        benchmark_root=benchmark_root,
    )
    repository = Path(repository_root).resolve()
    canonical_published = ReassessmentRunLayout.for_run(
        PUBLISHED_REASSESSMENT_RUN_ID
    )
    selected_published = ReassessmentRunLayout.for_run(
        PUBLISHED_REASSESSMENT_RUN_ID,
        benchmark_root=benchmark_root,
    )
    published_layouts = (canonical_published, selected_published)
    published_roots = {
        (
            item.run_paths.run_root
            if item.run_paths.run_root.is_absolute()
            else repository / item.run_paths.run_root
        ).resolve()
        for item in published_layouts
    }
    published_files = {
        (
            path
            if path.is_absolute()
            else repository / path
        ).resolve()
        for item in published_layouts
        for path in (
            item.capability_snapshot,
            item.matrix_snapshot,
            item.pilot_snapshot,
            item.holdout_snapshot,
            item.reports_snapshot,
            item.final_decision,
        )
    }
    published_files.add((repository / PUBLISHED_RUNBOOK).resolve())
    published_files.update(
        (repository / path).resolve() for path in PUBLISHED_RUNTIME_LOCKS
    )
    published_files.update(
        (repository / path).resolve()
        for path in PUBLISHED_PREDECESSOR_ARTIFACTS
    )
    for raw_target in targets:
        target = Path(raw_target)
        if not target.is_absolute():
            target = repository / target
        resolved = target.resolve()
        if (
            any(resolved.is_relative_to(root) for root in published_roots)
            or resolved in published_files
        ):
            raise ReassessmentNamespaceError(
                "fresh reassessment target reuses published immutable "
                f"{PUBLISHED_REASSESSMENT_RUN_ID} evidence: {target}"
            )
    return layout


__all__ = [
    "PUBLISHED_CAPABILITY_SNAPSHOT",
    "PUBLISHED_FINAL_DECISION",
    "PUBLISHED_HOLDOUT_SNAPSHOT",
    "PUBLISHED_MATRIX_SNAPSHOT",
    "PUBLISHED_PILOT_SNAPSHOT",
    "PUBLISHED_PREDECESSOR_ARTIFACTS",
    "PUBLISHED_REASSESSMENT_RUN_ID",
    "PUBLISHED_REPORTS_SNAPSHOT",
    "PUBLISHED_RUNBOOK",
    "PUBLISHED_RUNTIME_LOCKS",
    "ReassessmentNamespaceError",
    "ReassessmentRunLayout",
    "reject_published_write_targets",
    "require_fresh_reassessment_run",
]
