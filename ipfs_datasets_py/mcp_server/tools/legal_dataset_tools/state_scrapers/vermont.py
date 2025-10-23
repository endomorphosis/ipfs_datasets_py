"""Scraper for Vermont state laws.

This module contains the scraper for Vermont statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class VermontScraper(BaseStateScraper):
    """Scraper for Vermont state laws from https://legislature.vermont.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Vermont's legislative website."""
        return "https://legislature.vermont.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Vermont."""
        return [{
            "name": "Vermont Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Vermont's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "Vt. Stat. Ann.")


# Register this scraper with the registry
StateScraperRegistry.register("VT", VermontScraper)
