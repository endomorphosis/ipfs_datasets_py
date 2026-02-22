"""AutoScraper web scraping tools — thin MCP wrapper.

All domain logic lives at:
  ipfs_datasets_py.web_archiving.autoscraper_engine
"""
from ipfs_datasets_py.web_archiving.autoscraper_engine import (  # noqa: F401
    batch_scrape_with_autoscraper,
    create_autoscraper_model,
    list_autoscraper_models,
    optimize_autoscraper_model,
    scrape_with_autoscraper,
)

__all__ = [
    "create_autoscraper_model",
    "scrape_with_autoscraper",
    "optimize_autoscraper_model",
    "batch_scrape_with_autoscraper",
    "list_autoscraper_models",
]
