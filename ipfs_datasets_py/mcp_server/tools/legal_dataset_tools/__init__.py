"""Legal dataset scraping tools for the MCP server.

These tools allow AI assistants to scrape legal datasets including:
- US Code
- Federal Register
- State Laws
- Municipal Laws
- RECAP Archive (Court Documents)
"""

from .us_code_scraper import scrape_us_code, get_us_code_titles
from .federal_register_scraper import scrape_federal_register, search_federal_register
from .state_laws_scraper import scrape_state_laws, list_state_jurisdictions
from .municipal_laws_scraper import scrape_municipal_laws, search_municipal_codes
from .recap_archive_scraper import scrape_recap_archive, search_recap_documents, get_recap_document
from .export_utils import export_dataset, export_to_json, export_to_parquet, export_to_csv

__all__ = [
    # US Code tools
    "scrape_us_code",
    "get_us_code_titles",
    
    # Federal Register tools
    "scrape_federal_register",
    "search_federal_register",
    
    # State Laws tools
    "scrape_state_laws",
    "list_state_jurisdictions",
    
    # Municipal Laws tools
    "scrape_municipal_laws",
    "search_municipal_codes",
    
    # RECAP Archive tools
    "scrape_recap_archive",
    "search_recap_documents",
    "get_recap_document",
    
    # Export utilities
    "export_dataset",
    "export_to_json",
    "export_to_parquet",
    "export_to_csv",
]
