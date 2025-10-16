"""Scraper for Tennessee state laws.

This module contains the scraper for Tennessee statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class TennesseeScraper(BaseStateScraper):
    """Scraper for Tennessee state laws from https://www.tn.gov/tga"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Tennessee's legislative website."""
        return "https://www.tn.gov/tga"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Tennessee."""
        return [{
            "name": "Tennessee Code Annotated",
            "url": f"{self.get_base_url()}/statutes.html",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Tennessee's legislative website.
        
        Tennessee uses JavaScript for statute rendering, so we use Playwright.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._playwright_scrape(
            code_name, 
            code_url, 
            "Tenn. Code Ann.",
            wait_for_selector="a[href*='title'], .code-link",
            timeout=45000
        )


# Register this scraper with the registry
StateScraperRegistry.register("TN", TennesseeScraper)
