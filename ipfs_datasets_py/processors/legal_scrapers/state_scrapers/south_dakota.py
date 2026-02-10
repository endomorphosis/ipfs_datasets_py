"""Scraper for South Dakota state laws.

This module contains the scraper for South Dakota statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class SouthDakotaScraper(BaseStateScraper):
    """Scraper for South Dakota state laws from https://sdlegislature.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for South Dakota's legislative website."""
        return "https://sdlegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for South Dakota."""
        return [{
            "name": "South Dakota Codified Laws",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from South Dakota's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "S.D. Codified Laws")


# Register this scraper with the registry
StateScraperRegistry.register("SD", SouthDakotaScraper)
