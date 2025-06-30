from datetime import datetime
from pathlib import Path

def generate_validation_report(
    error_summary: dict[str, int], 
    accuracy_stats: dict[str, float],
    estimates: dict[str, float],
    error_report_db
) -> Path:
    """
    Generate a comprehensive validation report for municipal bluebook citations.

    Args:
        error_summary (dict[str, int]): Error type counts.
        accuracy_stats (dict[str, float]): Accuracy metrics.
        estimates (dict[str, float]): Projected statistics.
        error_report_db (DatabaseConnection): DB connection for saving the report.

    Returns:
        Path: Path to the generated validation report file.
    """

    # Validate input types
    if not isinstance(error_summary, dict) or not isinstance(accuracy_stats, dict) or not isinstance(estimates, dict):
        raise ValueError("Input arguments must be dictionaries.")

    report_dir = Path("validation_reports")
    report_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"bluebook_validation_report_{timestamp}.txt"

    # Compose report content
    lines = []
    lines.append("Municipal Bluebook Citation Validation Report")
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("=" * 60)
    lines.append("\nError Summary:")
    for err, count in error_summary.items():
        lines.append(f"  {err}: {count}")
    lines.append("\nAccuracy Statistics:")
    for k, v in accuracy_stats.items():
        lines.append(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    lines.append("\nEstimates (Extrapolated):")
    for k, v in estimates.items():
        lines.append(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    lines.append("=" * 60)
    lines.append("End of Report\n")

    # Write to file
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        raise IOError(f"Failed to write report: {e}")

    # Save to database (duckdb or similar)
    try:
        # Assume error_report_db is a duckdb.Connection or similar
        error_report_db.execute("""
            CREATE TABLE IF NOT EXISTS validation_reports (
                timestamp VARCHAR,
                report_path VARCHAR,
                error_summary VARCHAR,
                accuracy_stats VARCHAR,
                estimates VARCHAR
            )
        """)
        error_report_db.execute(
            "INSERT INTO validation_reports VALUES (?, ?, ?, ?, ?)",
            [
                timestamp,
                str(report_path),
                str(error_summary),
                str(accuracy_stats),
                str(estimates)
            ]
        )
    except Exception as e:
        raise RuntimeError(f"Failed to save report to database: {e}") from e

    return report_path