"""
Medical Research Data Scrapers for Medicine Dashboard.

This module provides scrapers for collecting medical, biochemical, and population health
data from various research databases and repositories to support the medicine dashboard's
temporal deontic logic reasoning system.

Available scrapers:
- PubMed medical literature
- ClinicalTrials.gov trial data
- NIH research databases
- arXiv medical papers
- CDC population health data
- WHO health statistics
"""

from typing import List, Dict, Any, Optional

__all__ = [
    'PubMedScraper',
    'ClinicalTrialsScraper',
    'NIHDataScraper',
    'ArXivMedicalScraper',
    'CDCHealthDataScraper',
    'WHOStatsScraper',
]

# Import individual scrapers (will be created)
try:
    from .pubmed_scraper import PubMedScraper
except ImportError:
    PubMedScraper = None

try:
    from .clinical_trials_scraper import ClinicalTrialsScraper
except ImportError:
    ClinicalTrialsScraper = None

try:
    from .nih_data_scraper import NIHDataScraper
except ImportError:
    NIHDataScraper = None

try:
    from .arxiv_medical_scraper import ArXivMedicalScraper
except ImportError:
    ArXivMedicalScraper = None

try:
    from .cdc_health_data_scraper import CDCHealthDataScraper
except ImportError:
    CDCHealthDataScraper = None

try:
    from .who_stats_scraper import WHOStatsScraper
except ImportError:
    WHOStatsScraper = None
