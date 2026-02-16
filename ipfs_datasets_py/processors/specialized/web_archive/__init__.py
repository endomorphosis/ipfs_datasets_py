"""Advanced web archiving package.

This package provides comprehensive web archiving capabilities including
Common Crawl integration, WARC file handling, and distributed web scraping.
"""

from .advanced_archiving import (
    AdvancedWebArchiver,
    ArchivingConfig,
    WebResource,
    ArchiveCollection,
)

__all__ = [
    'AdvancedWebArchiver',
    'ArchivingConfig',
    'WebResource',
    'ArchiveCollection',
]
