"""Scraper for Wyoming state laws.

This module contains the scraper for Wyoming statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class WyomingScraper(BaseStateScraper):
    """Scraper for Wyoming state laws from https://www.wyoleg.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Wyoming's legislative website."""
        return "https://www.wyoleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Wyoming."""
        return [{
            "name": "Wyoming Statutes",
            "url": f"{self.get_base_url()}/statutes/statutesintro.aspx",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Wyoming's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "Wyo. Stat.")


# Register this scraper with the registry
StateScraperRegistry.register("WY", WyomingScraper)
