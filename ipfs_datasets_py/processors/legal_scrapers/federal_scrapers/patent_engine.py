"""DEPRECATED compatibility re-export of the USPTO patent scraper engine.

Canonical implementation lives under::

    ipfs_datasets_py.processors.domains.patent.patent_scraper

This federal_scrapers path is retained for historical package imports. Classes
re-exported here are the *same objects* as the canonical domain module and
``legal_scrapers.patent_engine``.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.patent_engine "
    "is deprecated; use ipfs_datasets_py.processors.domains.patent.patent_scraper "
    "instead.",
    DeprecationWarning,
    stacklevel=2,
)

import requests  # re-exported for legacy patch paths  # noqa: E402

# Import via the package-level compatibility module so both legacy paths share
# one installation of offline guards and requests aliases.
from ipfs_datasets_py.processors.legal_scrapers.patent_engine import (  # noqa: E402,F401
    Patent,
    PatentDatasetBuilder,
    PatentSearchCriteria,
    USPTOPatentScraper,
    search_patents_by_assignee,
    search_patents_by_inventor,
    search_patents_by_keyword,
)

__all__ = [
    "Patent",
    "PatentDatasetBuilder",
    "PatentSearchCriteria",
    "USPTOPatentScraper",
    "requests",
    "search_patents_by_assignee",
    "search_patents_by_inventor",
    "search_patents_by_keyword",
]
