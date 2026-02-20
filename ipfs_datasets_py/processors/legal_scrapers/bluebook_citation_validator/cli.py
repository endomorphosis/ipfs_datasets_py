"""Command-line entry point for the Bluebook citation validator.

Usage::

    python -m ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator
    # or via installed console script:
    ipfs-datasets validate-citations --citation-dir ./citations ...
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="validate-citations",
        description="Validate municipal Bluebook citations against GNIS reference data.",
    )
    parser.add_argument(
        "--citation-dir",
        default="./citations",
        help="Directory containing *_citation.parquet files.",
    )
    parser.add_argument(
        "--document-dir",
        default="./documents",
        help="Directory containing *_html.parquet files.",
    )
    parser.add_argument(
        "--error-db",
        default="bluebook_errors.duckdb",
        help="Path for the DuckDB error database.",
    )
    parser.add_argument(
        "--report-db",
        default="bluebook_reports.duckdb",
        help="Path for the DuckDB report database.",
    )
    parser.add_argument(
        "--output-dir",
        default="./reports",
        help="Directory for JSON report output.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=385,
        help="Stratified sample size (default: 385).",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=8,
        help="Thread-pool size for parallel validation.",
    )
    parser.add_argument(
        "--mysql-host", default="localhost", help="MySQL hostname."
    )
    parser.add_argument("--mysql-port", type=int, default=3306, help="MySQL port.")
    parser.add_argument("--mysql-user", default="", help="MySQL username.")
    parser.add_argument("--mysql-password", default="", help="MySQL password.")
    parser.add_argument("--mysql-database", default="", help="MySQL database name.")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """Entry point for ``ipfs-datasets validate-citations``."""
    args = _parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from .config import ValidatorConfig
    from .database import (
        setup_reference_database,
        setup_error_database,
        setup_report_database,
    )
    from .sampling import StratifiedSampler
    from .validator import CitationValidator
    from .analysis import ResultsAnalyzer
    from .report import generate_validation_report

    config = ValidatorConfig(
        citation_dir=Path(args.citation_dir),
        document_dir=Path(args.document_dir),
        error_db_path=Path(args.error_db),
        error_report_db_path=Path(args.report_db),
        output_dir=Path(args.output_dir),
        sample_size=args.sample_size,
        max_concurrency=args.max_concurrency,
        mysql_host=args.mysql_host,
        mysql_port=args.mysql_port,
        mysql_user=args.mysql_user,
        mysql_password=args.mysql_password,
        mysql_database=args.mysql_database,
    )

    try:
        reference_db = setup_reference_database(config)
        error_db = setup_error_database(config)
        report_db = setup_report_database(config)
    except RuntimeError as exc:
        logger.error("Database setup failed: %s", exc)
        return 1

    try:
        citation_files = list(Path(config.citation_dir).glob("*_citation.parquet"))
        logger.info("Found %d citation files.", len(citation_files))

        sampler = StratifiedSampler(config)
        gnis_counts_by_state, sampled_gnis = sampler.get_stratified_sample(
            citation_files, reference_db
        )

        validator = CitationValidator(config, reference_db, error_db)
        total_errors = validator.validate_citations_against_html_and_references(sampled_gnis)

        total_citations = len(sampled_gnis)  # approximate
        analyzer = ResultsAnalyzer(config)
        error_summary, accuracy_stats, extrapolated = analyzer.analyze(
            error_db, gnis_counts_by_state, total_citations, total_errors
        )

        generate_validation_report(
            error_summary,
            accuracy_stats,
            extrapolated,
            output_dir=config.output_dir,
            report_db=report_db,
        )

        logger.info("Validation complete. %d errors found.", total_errors)
    finally:
        for conn in (reference_db, error_db, report_db):
            try:
                conn.close()
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
