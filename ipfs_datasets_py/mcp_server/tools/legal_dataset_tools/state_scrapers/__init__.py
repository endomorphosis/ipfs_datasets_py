"""Individual state law scrapers.

This package contains dedicated scrapers for each US state's official
legislative website, with state-specific parsing logic.
"""

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry, get_scraper_for_state

# Import state-specific scrapers to register them
from . import california
from . import new_york
from . import texas
from .generic import GenericStateScraper

__all__ = [
    'BaseStateScraper',
    'NormalizedStatute',
    'StatuteMetadata',
    'StateScraperRegistry',
    'get_scraper_for_state',
    'GenericStateScraper',
]
