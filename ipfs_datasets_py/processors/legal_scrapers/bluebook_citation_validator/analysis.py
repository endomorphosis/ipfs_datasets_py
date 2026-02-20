"""Results analysis: error-pattern counting, accuracy statistics, and
extrapolation to the full dataset.

Bugs fixed:
- Bug #11: ``ResultsAnalyzer`` had double-indented methods (parse error).
- Bug #11: ``analyze`` method was missing its ``return`` statement.
- Bug #12: ``_apply_geographic_weighting`` call passed ``cv`` (undefined) instead
  of ``gnis_counts_by_state``.
- Bug #13: ``accuracy_stats.recall`` → ``.true_positive_rate``; ``.total_population`` → ``.total``.
- Bug #24: ``row[2:6]`` unpacking skipped ``type_error`` — fixed to ``row[2:7]``
  and now unpacks all 5 error flags.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from functools import cached_property, cache
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Accuracy / confusion-matrix statistics
# ---------------------------------------------------------------------------

@dataclass
class ConfusionMatrixStats:
    """Accuracy statistics derived from a binary confusion matrix.

    Attributes:
        true_positives: Correctly flagged invalid citations.
        false_positives: Valid citations incorrectly flagged.
        true_negatives: Correctly passed valid citations.
        false_negatives: Invalid citations that were missed.
    """

    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int

    @property
    def total(self) -> int:
        """Total number of evaluated citations."""
        return (
            self.true_positives
            + self.false_positives
            + self.true_negatives
            + self.false_negatives
        )

    @property
    def accuracy(self) -> float:
        n = self.total
        return (self.true_positives + self.true_negatives) / n if n else 0.0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 0.0

    @property
    def true_positive_rate(self) -> float:
        """Also known as recall / sensitivity."""
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 0.0

    # Alias for callers that expect .recall
    @property
    def recall(self) -> float:
        return self.true_positive_rate

    @property
    def f1_score(self) -> float:
        p, r = self.precision, self.true_positive_rate
        return 2 * p * r / (p + r) if (p + r) else 0.0


def calculate_accuracy_statistics(
    total_citations: int, total_errors: int
) -> ConfusionMatrixStats:
    """Build a :class:`ConfusionMatrixStats` from raw totals.

    Assumes the validator has perfect recall (no missed errors), so
    ``true_negatives = total_citations - total_errors`` and
    ``false_negatives = 0``.
    """
    valid = max(0, total_citations - total_errors)
    return ConfusionMatrixStats(
        true_positives=total_errors,
        false_positives=0,
        true_negatives=valid,
        false_negatives=0,
    )


# ---------------------------------------------------------------------------
# Error-pattern analysis
# ---------------------------------------------------------------------------

def analyze_error_patterns(error_db, logger_=None) -> dict[str, int]:
    """Count errors in the database by type.

    Bug #24 fix: ``row[2:7]`` now correctly unpacks 5 boolean columns:
    ``geography_error, type_error, section_error, date_error, format_error``
    (original code used ``row[2:6]`` which silently dropped ``type_error``).
    """
    _log = logger_ or logger
    summary: dict[str, int] = {
        "total_errors": 0,
        "geography_errors": 0,
        "type_errors": 0,
        "section_errors": 0,
        "date_errors": 0,
        "format_errors": 0,
        "critical_errors": 0,
        "minor_errors": 0,
    }

    try:
        rows = error_db.execute("SELECT * FROM errors").fetchall()
    except Exception as exc:
        _log.error("Failed to query error database: %s", exc)
        return summary

    if not rows:
        return summary

    for row in rows:
        summary["total_errors"] += 1
        # Columns: cid(0), citation_cid(1), gnis(2), geography_error(3),
        #          type_error(4), section_error(5), date_error(6), format_error(7),
        #          severity(8), error_message(9), created_at(10)
        # Bug #24 fix: unpack 5 flags from indices 3-7.
        geography_error = bool(row[3])
        type_error = bool(row[4])
        section_error = bool(row[5])
        date_error = bool(row[6])
        format_error = bool(row[7])

        if geography_error:
            summary["geography_errors"] += 1
            summary["critical_errors"] += 1
        if type_error:
            summary["type_errors"] += 1
            summary["critical_errors"] += 1
        if section_error:
            summary["section_errors"] += 1
            summary["minor_errors"] += 1
        if date_error:
            summary["date_errors"] += 1
            summary["minor_errors"] += 1
        if format_error:
            summary["format_errors"] += 1
            summary["minor_errors"] += 1

    return summary


# ---------------------------------------------------------------------------
# Extrapolation
# ---------------------------------------------------------------------------

class ExtrapolateToFullDataset:
    """Extrapolates sample accuracy statistics to the full dataset."""

    _Z_SCORE = 1.96

    def __init__(self, logger_=None) -> None:
        self._logger = logger_ or logger
        self._gnis_counts_by_state: Optional[dict[str, int]] = None

    @cached_property
    def _total_estimated_records(self) -> int:
        if self._gnis_counts_by_state is None:
            return 0
        return sum(self._gnis_counts_by_state.values())

    @staticmethod
    def _apply_geographic_weighting(gnis_counts_by_state: dict[str, int]) -> float:
        """Return the coefficient of variation (CV) for state counts.

        Bug #12 fix: method is called as
        ``_apply_geographic_weighting(gnis_counts_by_state)``, not
        ``_apply_geographic_weighting(cv, scaling_factor)``.
        """
        counts = list(gnis_counts_by_state.values())
        mean = sum(counts) / len(counts) if counts else 0.0
        if mean == 0:
            return 0.0
        variance = sum((c - mean) ** 2 for c in counts) / len(counts)
        return math.sqrt(variance) / mean

    def extrapolate(
        self,
        accuracy_stats: ConfusionMatrixStats,
        gnis_counts_by_state: dict[str, int],
        sample_size: int,
    ) -> dict[str, Any]:
        """Extrapolate validation metrics from a sample to the full dataset.

        Bug #12 fix: ``cv`` is computed BEFORE being used.
        Bug #13 fix: uses ``.true_positive_rate`` and ``.total``.

        Args:
            accuracy_stats: Confusion-matrix stats for the sample.
            gnis_counts_by_state: Mapping of state → GNIS count.
            sample_size: Number of citations in the sample.

        Returns:
            Dict of extrapolated metrics.
        """
        if sample_size <= 0:
            raise ValueError("sample_size must be positive")
        if not gnis_counts_by_state:
            raise ValueError("gnis_counts_by_state cannot be empty")

        self._gnis_counts_by_state = gnis_counts_by_state

        # Bug #13 fix: use .true_positive_rate (not .recall), .total (not .total_population)
        sample_accuracy = accuracy_stats.accuracy
        sample_precision = accuracy_stats.precision
        sample_recall = accuracy_stats.true_positive_rate  # Bug #13 fix
        actual_sample_size = accuracy_stats.total  # Bug #13 fix

        if actual_sample_size != sample_size:
            self._logger.warning(
                "Sample size mismatch: provided %d, matrix shows %d; using matrix value.",
                sample_size,
                actual_sample_size,
            )
            sample_size = actual_sample_size

        total_estimated_records = self._total_estimated_records

        # Wilson score interval
        z = self._Z_SCORE
        n = sample_size
        p = sample_accuracy
        denom = 1 + z ** 2 / n
        center = (p + z ** 2 / (2 * n)) / denom
        margin = (z / denom) * math.sqrt((p * (1 - p) / n) + (z ** 2 / (4 * n ** 2)))

        confidence_lower = max(0.0, center - margin)
        confidence_upper = min(1.0, center + margin)

        # Bug #12 fix: cv is computed from gnis_counts_by_state, not from
        # an undefined variable.
        cv = self._apply_geographic_weighting(gnis_counts_by_state)

        # Geographic adjustment to confidence interval.
        confidence_lower = max(0.0, confidence_lower - cv * 0.05)
        confidence_upper = min(1.0, confidence_upper + cv * 0.05)

        scaling_factor = total_estimated_records / max(sample_size, 1)
        estimated_total_errors = int(total_estimated_records * (1 - sample_accuracy))
        estimated_valid_citations = total_estimated_records - estimated_total_errors

        # Finite population correction.
        fpc = 1.0
        if total_estimated_records > 0 and sample_size / total_estimated_records > 0.05:
            fpc = math.sqrt(
                (total_estimated_records - sample_size) / (total_estimated_records - 1)
            )
            confidence_lower = max(0.0, center - margin * fpc)
            confidence_upper = min(1.0, center + margin * fpc)

        reliability = (
            "high" if sample_size >= 385 else "medium" if sample_size >= 100 else "low"
        )

        return {
            "estimated_accuracy": sample_accuracy,
            "estimated_accuracy_percent": sample_accuracy * 100,
            "estimated_precision": sample_precision,
            "estimated_recall": sample_recall,
            "estimated_f1_score": accuracy_stats.f1_score,
            "confidence_interval_lower": confidence_lower,
            "confidence_interval_upper": confidence_upper,
            "confidence_level": 95.0,
            "margin_of_error": margin,
            "total_estimated_records": total_estimated_records,
            "sample_size": sample_size,
            "scaling_factor": scaling_factor,
            "estimated_total_errors": estimated_total_errors,
            "estimated_valid_citations": estimated_valid_citations,
            "estimated_error_rate": 1 - sample_accuracy,
            "geographic_cv": cv,
            "finite_population_correction": fpc,
            "extrapolation_reliability": reliability,
            "number_of_states": len(gnis_counts_by_state),
        }


# ---------------------------------------------------------------------------
# Top-level ResultsAnalyzer
# ---------------------------------------------------------------------------

class ResultsAnalyzer:
    """Orchestrates error-pattern analysis, accuracy stats, and extrapolation.

    Bug #11 fix: methods are no longer doubly-indented, and ``analyze`` now
    includes the required ``return`` statement.
    """

    def __init__(self, config) -> None:
        self._config = config
        self._extrapolator = ExtrapolateToFullDataset()

    def analyze(
        self,
        error_db,
        gnis_counts_by_state: dict[str, int],
        total_citations: int,
        total_errors: int,
    ) -> tuple[dict[str, Any], ConfusionMatrixStats, dict[str, Any]]:
        """Run the full analysis pipeline.

        Args:
            error_db: Open DuckDB connection to the errors database.
            gnis_counts_by_state: Mapping of state → GNIS place count.
            total_citations: Total citations validated.
            total_errors: Total error rows produced.

        Returns:
            ``(error_summary, accuracy_stats, extrapolated_results)``
        """
        error_summary = analyze_error_patterns(error_db)
        accuracy_stats = calculate_accuracy_statistics(total_citations, total_errors)
        extrapolated_results = self._extrapolator.extrapolate(
            accuracy_stats,
            gnis_counts_by_state,
            sample_size=self._config.sample_size,
        )
        # Bug #11 fix: was missing the return statement.
        return error_summary, accuracy_stats, extrapolated_results
