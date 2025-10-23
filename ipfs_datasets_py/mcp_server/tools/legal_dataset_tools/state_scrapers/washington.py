"""Scraper for Washington state laws.

This module contains the scraper for Washington statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class WashingtonScraper(BaseStateScraper):
    """Scraper for Washington state laws from https://app.leg.wa.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Washington's legislative website."""
        return "https://app.leg.wa.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Washington."""
        return [{
            "name": "Revised Code of Washington",
            "url": f"{self.get_base_url()}/RCW/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Washington's legislative website.
        
        Washington RCW database uses JavaScript navigation, so we use Playwright.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._playwright_scrape(
            code_name, 
            code_url, 
            "Wash. Rev. Code",
            wait_for_selector="a[href*='RCW'], .rcw-link",
            timeout=45000
        )


# Register this scraper with the registry
StateScraperRegistry.register("WA", WashingtonScraper)
