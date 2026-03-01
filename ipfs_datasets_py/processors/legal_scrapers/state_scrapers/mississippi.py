"""Scraper for Mississippi state laws.

This module contains the scraper for Mississippi statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class MississippiScraper(BaseStateScraper):
    """Scraper for Mississippi state laws from http://www.legislature.ms.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Mississippi's legislative website."""
        return "http://www.legislature.ms.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Mississippi."""
        return [{
            "name": "Mississippi Code",
            "url": "https://www.legislature.ms.gov/legislation/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Mississippi's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            "https://www.legislature.ms.gov/legislation/",
            "http://www.legislature.ms.gov/legislation/",
            # Archive fallback candidate when live pathing changes.
            "https://web.archive.org/web/20251017000000/https://www.legislature.ms.gov/legislation/",
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
                        "Miss. Code Ann.",
                        max_sections=150,
                        wait_for_selector="a[href*='statute'], a[href*='code'], a[href*='title'], a[href*='chapter']",
                        timeout=45000,
                    )
                    if statutes:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Miss. Code Ann.", max_sections=150)
            if statutes:
                return statutes

        return []


# Register this scraper with the registry
StateScraperRegistry.register("MS", MississippiScraper)
