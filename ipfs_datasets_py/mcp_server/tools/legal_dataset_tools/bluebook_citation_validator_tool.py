"""Thin MCP wrapper for the Bluebook citation validator.

Core implementation lives at:
``ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator``

This module exposes a single async function ``validate_bluebook_citations``
that can be registered as an MCP tool.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def validate_bluebook_citations(
    citation_dir: str,
    document_dir: str,
    mysql_host: str = "localhost",
    mysql_port: int = 3306,
    mysql_user: str = "",
    mysql_password: str = "",
    mysql_database: str = "",
    error_db_path: str = "validation_errors.duckdb",
    error_report_db_path: str = "validation_reports.duckdb",
    output_dir: str = "./reports",
    sample_size: int = 385,
    max_concurrency: int = 8,
    random_seed: int = 420,
) -> dict[str, Any]:
    """Validate municipal Bluebook citations against source HTML and a GNIS reference DB.

    This is a thin async wrapper around the synchronous core implementation in
    :mod:`ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator`.

    Args:
        citation_dir: Path to directory containing ``*_citation.parquet`` files.
        document_dir: Path to directory containing ``*_html.parquet`` files.
        mysql_host: MySQL server hostname (reference database).
        mysql_port: MySQL server port.
        mysql_user: MySQL username.
        mysql_password: MySQL password.
        mysql_database: MySQL schema/database name.
        error_db_path: Path for the output DuckDB error database.
        error_report_db_path: Path for the output DuckDB report database.
        output_dir: Directory for JSON report files.
        sample_size: Target stratified sample size (95 % CI ±5 % ≈ 385).
        max_concurrency: Thread-pool size for parallel place validation.
        random_seed: RNG seed for reproducible sampling.

    Returns:
        A dict containing:
        - ``total_errors``: number of error rows found.
        - ``error_summary``: per-type error counts.
        - ``accuracy_stats``: accuracy/precision/recall/f1.
        - ``extrapolated_results``: full-dataset projections.
        - ``status``: ``"ok"`` or ``"error"``.
        - ``message``: human-readable summary or error description.
    """
    from ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator import (
        ValidatorConfig,
        CitationValidator,
        StratifiedSampler,
        ResultsAnalyzer,
        generate_validation_report,
        setup_reference_database,
        setup_error_database,
        setup_report_database,
    )

    config = ValidatorConfig(
        citation_dir=Path(citation_dir),
        document_dir=Path(document_dir),
        error_db_path=Path(error_db_path),
        error_report_db_path=Path(error_report_db_path),
        output_dir=Path(output_dir),
        sample_size=sample_size,
        max_concurrency=max_concurrency,
        random_seed=random_seed,
        mysql_host=mysql_host,
        mysql_port=mysql_port,
        mysql_user=mysql_user,
        mysql_password=mysql_password,
        mysql_database=mysql_database,
    )

    loop = asyncio.get_event_loop()

    def _run_sync() -> dict[str, Any]:
        reference_db = error_db = report_db = None
        try:
            reference_db = setup_reference_database(config)
            error_db = setup_error_database(config)
            report_db = setup_report_database(config)

            citation_files = list(Path(citation_dir).glob("*_citation.parquet"))
            logger.info("Found %d citation files for MCP validation.", len(citation_files))

            sampler = StratifiedSampler(config)
            gnis_counts_by_state, sampled_gnis = sampler.get_stratified_sample(
                citation_files, reference_db
            )

            validator = CitationValidator(config, reference_db, error_db)
            total_errors = validator.validate_citations_against_html_and_references(
                sampled_gnis
            )

            analyzer = ResultsAnalyzer(config)
            error_summary, accuracy_stats, extrapolated = analyzer.analyze(
                error_db,
                gnis_counts_by_state,
                total_citations=len(sampled_gnis),
                total_errors=total_errors,
            )

            report = generate_validation_report(
                error_summary,
                accuracy_stats,
                extrapolated,
                output_dir=config.output_dir,
                report_db=report_db,
            )

            return {
                "status": "ok",
                "message": f"Validated {len(sampled_gnis)} places; found {total_errors} errors.",
                "total_errors": total_errors,
                "error_summary": error_summary,
                "accuracy_stats": report["accuracy_stats"],
                "extrapolated_results": extrapolated,
            }
        except Exception as exc:
            logger.exception("MCP validate_bluebook_citations failed: %s", exc)
            return {"status": "error", "message": str(exc)}
        finally:
            for conn in (reference_db, error_db, report_db):
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    return await loop.run_in_executor(None, _run_sync)
