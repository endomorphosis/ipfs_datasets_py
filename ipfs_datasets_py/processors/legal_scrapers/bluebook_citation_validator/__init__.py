"""Public API for the Bluebook citation validator package.

New canonical location::

    ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator

Migrate from::

    ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator
"""

from .config import ValidatorConfig
from .constants import BLUEBOOK_STATE_ABBREVS, MIN_CITATION_YEAR, MAX_CITATION_YEAR, MUNICIPAL_CLASS_CODES, COUNTY_CLASS_CODES, CONSOLIDATED_CLASS_CODES
from .validator import CitationValidator
from .sampling import StratifiedSampler
from .analysis import ResultsAnalyzer, ConfusionMatrixStats
from .report import generate_validation_report
from .cli import main as validate_citations_cli
from .database import make_cid, setup_reference_database, setup_error_database, setup_report_database
from .checkers import (
    check_geography,
    check_code_type,
    check_section,
    check_date,
    check_format,
)

__all__ = [
    # Primary classes
    "ValidatorConfig",
    "CitationValidator",
    "StratifiedSampler",
    "ResultsAnalyzer",
    "ConfusionMatrixStats",
    # Top-level functions
    "generate_validation_report",
    "validate_citations_cli",
    # Database helpers
    "make_cid",
    "setup_reference_database",
    "setup_error_database",
    "setup_report_database",
    # Individual checkers
    "check_geography",
    "check_code_type",
    "check_section",
    "check_date",
    "check_format",
    # Constants
    "BLUEBOOK_STATE_ABBREVS",
    "MIN_CITATION_YEAR",
    "MAX_CITATION_YEAR",
    "MUNICIPAL_CLASS_CODES",
    "COUNTY_CLASS_CODES",
    "CONSOLIDATED_CLASS_CODES",
]
