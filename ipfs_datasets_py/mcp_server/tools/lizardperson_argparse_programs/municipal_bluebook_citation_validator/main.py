#!/usr/bin/env python3
"""
Bluebook Citation Validator - Main Implementation
Based on the Second SAD architecture
"""
import argparse
import functools
import logging
import random
import sys
from pathlib import Path
from queue import Queue
import re
from threading import RLock
from typing import Any, Dict, Generator, List, Optional, Tuple, TypeVar, Union


from configs import configs
from types_ import DatabaseConnection


logger = logging.getLogger(__name__)


from _setup_databases_and_files import make_setup_database_and_files
from stratified_sampler import make_stratified_sampler
from citation_validator import make_citation_validator
from results_analyzer import make_results_analyzer
from generate_reports import generate_validation_report # TODO Turn into factory function
from datetime import datetime


def main() -> int:
    """
    Main function implementing the 4-step process from Second SAD:
    1. Setup - connect to databases and load files
    2. Smart Sampling - select 385 places to check  
    3. Validation Loop - run all 5 checkers on each citation
    4. Analysis and Reporting - count errors and generate reports
    """
    try:
        # Step 1: Setup
        print("Step 1: Setting up databases and loading files...")
        setup = make_setup_database_and_files()
        reference_db, error_db, error_report_db = setup.get_databases() # -> DatabaseConnection, DatabaseConnection, DatabaseConnection
        citations, html =  setup.get_files() # -> List[Path], List[Path]

        print(f"Found {len(citations)} citation files and {len(html)} document files")

        # Step 2: Smart Sampling
        stratified_sampler = make_stratified_sampler()
        gnis_counts_by_state, gnis_for_sampled_places = stratified_sampler.get_stratified_sample(citations, reference_db)

        # Step 3: Validation Loop
        validator = make_citation_validator()
        number_of_errors = validator.validate_citations_against_html_and_references(
                            citations, html, gnis_for_sampled_places, 
                            reference_db, error_db
                        )
        if number_of_errors == 0:
            print("No errors found during validation. Exiting.")
            return 0

        # Step 4: Analysis
        # NOTE Rather than pass the list from the last function, we re-query the error_db.
        # This ensures we have a clean state and decouples validation from analysis.
        results_analyzer = make_results_analyzer() 
        error_summary, accuracy_stats, estimates = results_analyzer.analyze(error_db, gnis_counts_by_state, len(citations), len(gnis_for_sampled_places))

        # Step 5: Generate reports
        report_path: Path = generate_validation_report(error_summary, accuracy_stats, estimates, error_report_db)

        print(f"Validation complete! Report saved to: {report_path}")
        print(f"Sample accuracy: {accuracy_stats['accuracy_percent']:.2f}%")
        print(f"Estimated full dataset accuracy: {estimates['estimated_accuracy']:.2f}%")
        print(f"Total errors found: {error_summary['total_errors']}")
        print(f"See validation report for detailed error patterns and statistics.")

        return 0
        
    except Exception as e:
        logger.exception(f"{type(e).__name__} occurred during validation: {e}")
        print(f"Error during validation: {e}", file=sys.stderr)
        return 1
    finally:
        # Cleanup connections
        cleanup_database_connections(error_db, error_report_db)





# Cleanup Function
def cleanup_database_connections(*connections) -> None:
    """Close all database connections properly."""
    for conn in connections:
        if conn is not None:
            try:
                conn.close()
                logger.info(f"Closed database connection: {conn}")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}")


# utils.py
if __name__ == "__main__":
    try:
        exit_code: int = main()
    except KeyboardInterrupt:
        print("Validation interrupted by user")
        exit_code = 0
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"Unexpected error: {e}")
        exit_code = 1
    finally:
        sys.exit(exit_code)
