"""Scraper for Indiana state laws.

This module contains the scraper for Indiana statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class IndianaScraper(BaseStateScraper):
    """Scraper for Indiana state laws from http://iga.in.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Indiana's legislative website."""
        return "http://iga.in.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Indiana."""
        return [{
            "name": "Indiana Code",
            "url": f"{self.get_base_url()}/legislative/laws/2024/ic/titles/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Indiana's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "Ind. Code")


# Register this scraper with the registry
StateScraperRegistry.register("IN", IndianaScraper)
