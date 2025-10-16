"""Individual state law scrapers.

This package contains dedicated scrapers for each US state's official
legislative website, with state-specific parsing logic.

All 51 US jurisdictions (50 states + DC) have individual scraper files.
"""

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry, get_scraper_for_state
from .generic import GenericStateScraper

# Import all 51 state-specific scrapers (alphabetically)
from . import alabama
from . import alaska
from . import arizona
from . import arkansas
from . import california
from . import colorado
from . import connecticut
from . import delaware
from . import district_of_columbia
from . import florida
from . import georgia
from . import hawaii
from . import idaho
from . import illinois
from . import indiana
from . import iowa
from . import kansas
from . import kentucky
from . import louisiana
from . import maine
from . import maryland
from . import massachusetts
from . import michigan
from . import minnesota
from . import mississippi
from . import missouri
from . import montana
from . import nebraska
from . import nevada
from . import new_hampshire
from . import new_jersey
from . import new_mexico
from . import new_york
from . import north_carolina
from . import north_dakota
from . import ohio
from . import oklahoma
from . import oregon
from . import pennsylvania
from . import rhode_island
from . import south_carolina
from . import south_dakota
from . import tennessee
from . import texas
from . import utah
from . import vermont
from . import virginia
from . import washington
from . import west_virginia
from . import wisconsin
from . import wyoming

__all__ = [
    'BaseStateScraper',
    'NormalizedStatute',
    'StatuteMetadata',
    'StateScraperRegistry',
    'get_scraper_for_state',
    'GenericStateScraper',
]
