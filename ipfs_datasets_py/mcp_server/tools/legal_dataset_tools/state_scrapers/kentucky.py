"""Scraper for Kentucky state laws.

This module contains the scraper for Kentucky statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class KentuckyScraper(BaseStateScraper):
    """Scraper for Kentucky state laws from https://legislature.ky.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Kentucky's legislative website."""
        return "https://legislature.ky.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Kentucky."""
        return [{
            "name": "Kentucky Revised Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Kentucky's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "Ky. Rev. Stat.")


# Register this scraper with the registry
StateScraperRegistry.register("KY", KentuckyScraper)
