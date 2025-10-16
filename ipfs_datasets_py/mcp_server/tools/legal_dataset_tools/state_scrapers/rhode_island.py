"""Scraper for Rhode Island state laws.

This module contains the scraper for Rhode Island statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class RhodeIslandScraper(BaseStateScraper):
    """Scraper for Rhode Island state laws from http://webserver.rilin.state.ri.us"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Rhode Island's legislative website."""
        return "http://webserver.rilin.state.ri.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Rhode Island."""
        return [{
            "name": "Rhode Island General Laws",
            "url": f"{self.get_base_url()}/Statutes/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Rhode Island's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._generic_scrape(code_name, code_url, "R.I. Gen. Laws")


# Register this scraper with the registry
StateScraperRegistry.register("RI", RhodeIslandScraper)
