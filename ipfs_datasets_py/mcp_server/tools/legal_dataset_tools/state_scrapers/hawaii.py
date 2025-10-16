"""Scraper for Hawaii state laws.

This module contains the scraper for Hawaii statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class HawaiiScraper(BaseStateScraper):
    """Scraper for Hawaii state laws from https://www.capitol.hawaii.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Hawaii's legislative website."""
        return "https://www.capitol.hawaii.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Hawaii."""
        return [{
            "name": "Hawaii Revised Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Hawaii's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "Haw. Rev. Stat.")


# Register this scraper with the registry
StateScraperRegistry.register("HI", HawaiiScraper)
