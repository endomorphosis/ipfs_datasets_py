"""Scraper for Arizona state laws.

This module contains the scraper for Arizona statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class ArizonaScraper(BaseStateScraper):
    """Scraper for Arizona state laws from https://www.azleg.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Arizona's legislative website."""
        return "https://www.azleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Arizona."""
        return [{
            "name": "Arizona Revised Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Arizona's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "Ariz. Rev. Stat.")


# Register this scraper with the registry
StateScraperRegistry.register("AZ", ArizonaScraper)
