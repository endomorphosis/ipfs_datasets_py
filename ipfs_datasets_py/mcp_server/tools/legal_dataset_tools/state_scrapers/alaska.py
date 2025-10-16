"""Scraper for Alaska state laws.

This module contains the scraper for Alaska statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class AlaskaScraper(BaseStateScraper):
    """Scraper for Alaska state laws from http://www.legis.state.ak.us"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Alaska's legislative website."""
        return "http://www.legis.state.ak.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Alaska."""
        return [{
            "name": "Alaska Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Alaska's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "Alaska Stat.")


# Register this scraper with the registry
StateScraperRegistry.register("AK", AlaskaScraper)
