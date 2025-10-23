"""Scraper for Hawaii state laws.

This module contains the scraper for Hawaii statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
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
            "url": f"{self.get_base_url()}/hrscurrent/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Hawaii's legislative website.
        
        Hawaii uses JavaScript for statute navigation, so we try Playwright first.
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
                    "Haw. Rev. Stat.",
                    wait_for_selector="a[href*='Vol'], .statute-link, a[href*='hrs']",
                    timeout=45000
                )
            except Exception as e:
                self.logger.warning(f"Hawaii Playwright scraping failed: {e}, falling back to HTTP")
        
        # Fallback to generic scraper
        self.logger.info("Hawaii: Using fallback HTTP scraper")
        return await self._generic_scrape(code_name, code_url, "Haw. Rev. Stat.")


# Register this scraper with the registry
StateScraperRegistry.register("HI", HawaiiScraper)
