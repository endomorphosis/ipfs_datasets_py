"""Scraper for Tennessee state laws.

This module contains the scraper for Tennessee statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
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
        
        Tennessee uses JavaScript for statute rendering, so we try Playwright first.
        Falls back to HTTP scraping if Playwright is unavailable.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Try Playwright first
        if self.has_playwright():
            try:
                return await self._playwright_scrape(
                    code_name, 
                    code_url, 
                    "Tenn. Code Ann.",
                    wait_for_selector="a[href*='title'], .code-link, a[href*='tca']",
                    timeout=45000
                )
            except Exception as e:
                self.logger.warning(f"Tennessee Playwright scraping failed: {e}, falling back to HTTP")
        
        # Fallback to generic scraper
        self.logger.info("Tennessee: Using fallback HTTP scraper")
        return await self._generic_scrape(code_name, code_url, "Tenn. Code Ann.")


# Register this scraper with the registry
StateScraperRegistry.register("TN", TennesseeScraper)
