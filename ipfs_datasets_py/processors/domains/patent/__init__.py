"""
Patent domain processors for patent data collection and analysis.
"""

# Try to import patent modules, make them optional for missing dependencies
try:
    from .patent_scraper import *
except ImportError as e:
    import warnings
    warnings.warn(f"PatentScraper unavailable due to missing dependencies: {e}")

try:
    from .patent_dataset_api import *
except ImportError as e:
    import warnings
    warnings.warn(f"PatentDatasetAPI unavailable due to missing dependencies: {e}")

__all__ = ['PatentScraper', 'PatentDatasetAPI']
