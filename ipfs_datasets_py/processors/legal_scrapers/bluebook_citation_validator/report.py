"""Report generator: produces a human-readable validation summary."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def generate_validation_report(
    error_summary: dict[str, Any],
    accuracy_stats,
    extrapolated_results: dict[str, Any],
    output_dir: Optional[Path] = None,
    report_db=None,
) -> dict[str, Any]:
    """Generate and optionally persist a validation report.

    Args:
        error_summary: Output of :func:`~analysis.analyze_error_patterns`.
        accuracy_stats: A :class:`~analysis.ConfusionMatrixStats` instance.
        extrapolated_results: Output of :meth:`~analysis.ExtrapolateToFullDataset.extrapolate`.
        output_dir: When provided, the JSON report is written to this directory.
        report_db: When provided, the JSON report is inserted into the
            ``error_reports`` table.

    Returns:
        The report as a plain dict.
    """
    report: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "error_summary": error_summary,
        "accuracy_stats": {
            "accuracy": accuracy_stats.accuracy,
            "precision": accuracy_stats.precision,
            "recall": accuracy_stats.true_positive_rate,
            "f1_score": accuracy_stats.f1_score,
            "total_citations": accuracy_stats.total,
            "total_errors": accuracy_stats.true_positives,
        },
        "extrapolated_results": extrapolated_results,
    }

    report_json = json.dumps(report, indent=2, default=str)

    # Write to file.
    if output_dir is not None:
        out_path = Path(output_dir) / f"validation_report_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_json, encoding="utf-8")
        logger.info("Report written to %s.", out_path)

    # Persist to DB.
    if report_db is not None:
        try:
            report_db.execute(
                "INSERT INTO error_reports (report_json, created_at) VALUES (?, ?)",
                [report_json, datetime.utcnow().isoformat()],
            )
        except Exception as exc:
            logger.error("Failed to persist report to database: %s", exc)

    return report
