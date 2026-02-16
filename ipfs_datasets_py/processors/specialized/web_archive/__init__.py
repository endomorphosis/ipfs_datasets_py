"""Advanced web archiving package.

This package provides comprehensive web archiving capabilities including
Common Crawl integration, WARC file handling, and distributed web scraping.
"""

from .advanced_archiving import (
    AdvancedWebArchiver,
    ArchiveConfig,
    ArchiveResult,
)

__all__ = [
    'AdvancedWebArchiver',
    'ArchiveConfig',
    'ArchiveResult',
]
