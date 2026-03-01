"""Scraper for Arizona state laws.

This module contains the scraper for Arizona statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class ArizonaScraper(BaseStateScraper):
    """Scraper for Arizona state laws from https://www.azleg.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Arizona's legislative website."""
        return "https://www.azleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Arizona."""
        return [{
            "name": "Arizona Revised Statutes",
            "url": f"{self.get_base_url()}/arsDetail/?title=13",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Arizona's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/arsDetail/?title=13",
            f"{self.get_base_url()}/arsDetail/?title=1",
            f"{self.get_base_url()}/arsDetail/?title=28",
            # Archive fallback candidate when live endpoints are template-heavy.
            "https://web.archive.org/web/20251017000000/https://www.azleg.gov/arsDetail/?title=13",
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
                        "Ariz. Rev. Stat.",
                        max_sections=180,
                        wait_for_selector="a[href*='ars'], a[href*='statute'], a[href*='title'], a[href*='chapter']",
                        timeout=45000,
                    )
                    if statutes:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Ariz. Rev. Stat.", max_sections=180)
            if statutes:
                return statutes

        return []


# Register this scraper with the registry
StateScraperRegistry.register("AZ", ArizonaScraper)
