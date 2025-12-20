"""
Municipal code scrapers.

Provides scrapers for major municipal code providers:
- Municode (library.municode.com)
- eCode360 (ecode360.com)
- American Legal Publishing (codelibrary.amlegal.com)
"""

from pathlib import Path
import sys

# Import main scrapers
try:
    from . import municode_scraper
    from . import ecode360_scraper  
    from . import american_legal_scraper
except ImportError as e:
    import logging
    logging.warning(f"Could not import all municipal scrapers: {e}")
    municode_scraper = None
    ecode360_scraper = None
    american_legal_scraper = None


__all__ = [
    "municode_scraper",
    "ecode360_scraper",
    "american_legal_scraper",
]
