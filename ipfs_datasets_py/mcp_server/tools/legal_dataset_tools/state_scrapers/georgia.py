"""Scraper for Georgia state laws.

This module contains the scraper for Georgia statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class GeorgiaScraper(BaseStateScraper):
    """Scraper for Georgia state laws from http://www.legis.ga.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Georgia's legislative website."""
        return "http://www.legis.ga.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Georgia."""
        return [{
            "name": "Official Code of Georgia",
            "url": f"{self.get_base_url()}/legislation/laws.html",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Georgia's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "Ga. Code Ann.")


# Register this scraper with the registry
StateScraperRegistry.register("GA", GeorgiaScraper)
