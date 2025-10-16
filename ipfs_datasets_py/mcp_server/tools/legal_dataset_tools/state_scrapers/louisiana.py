"""Scraper for Louisiana state laws.

This module contains the scraper for Louisiana statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class LouisianaScraper(BaseStateScraper):
    """Scraper for Louisiana state laws from http://www.legis.la.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Louisiana's legislative website."""
        return "http://www.legis.la.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Louisiana."""
        return [{
            "name": "Louisiana Revised Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Louisiana's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "La. Rev. Stat.")


# Register this scraper with the registry
StateScraperRegistry.register("LA", LouisianaScraper)
