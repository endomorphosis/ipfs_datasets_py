"""Scraper for District of Columbia state laws.

This module contains the scraper for District of Columbia statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class DistrictOfColumbiaScraper(BaseStateScraper):
    """Scraper for District of Columbia state laws from https://code.dccouncil.us"""
    
    def get_base_url(self) -> str:
        """Return the base URL for District of Columbia's legislative website."""
        return "https://code.dccouncil.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for District of Columbia."""
        return [{
            "name": "District of Columbia Official Code",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from District of Columbia's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "D.C. Code")


# Register this scraper with the registry
StateScraperRegistry.register("DC", DistrictOfColumbiaScraper)
