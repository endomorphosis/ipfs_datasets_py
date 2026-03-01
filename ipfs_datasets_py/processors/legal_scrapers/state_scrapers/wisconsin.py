"""Scraper for Wisconsin state laws.

This module contains the scraper for Wisconsin statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class WisconsinScraper(BaseStateScraper):
    """Scraper for Wisconsin state laws from https://docs.legis.wisconsin.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Wisconsin's legislative website."""
        return "https://docs.legis.wisconsin.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Wisconsin."""
        return [{
            "name": "Wisconsin Statutes",
            "url": f"{self.get_base_url()}/statutes/statutes",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Wisconsin's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/statutes",
            f"{self.get_base_url()}/document/statutes/940",
            f"{self.get_base_url()}/document/statutes/939.50",
        ]

        seen = set()
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Wis. Stat.",
                        max_sections=250,
                        wait_for_selector="a[href*='/document/statutes/'], a[href*='/statutes/statutes']",
                        timeout=45000,
                    )
                    if statutes:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Wis. Stat.", max_sections=250)
            if statutes:
                return statutes

        return []


# Register this scraper with the registry
StateScraperRegistry.register("WI", WisconsinScraper)
