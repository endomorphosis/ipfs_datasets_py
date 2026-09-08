"""Municipal collectors shipped in ``endomorphosis/american_municipal_law``.

These sit beside the older HTML scrapers in this package. They talk to the
publisher JSON APIs (American Legal, eCode360, Municode).
"""

from .amlegal import PUBLISHER as AMLEGAL_PUBLISHER
from .amlegal import scrape_jurisdiction as scrape_amlegal_jurisdiction
from .amlegal import scrape_rows as scrape_amlegal_rows

__all__ = [
    "AMLEGAL_PUBLISHER",
    "scrape_amlegal_jurisdiction",
    "scrape_amlegal_rows",
]
