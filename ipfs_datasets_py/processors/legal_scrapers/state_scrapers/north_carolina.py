"""Scraper for North Carolina state laws.

This module contains the scraper for North Carolina statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class NorthCarolinaScraper(BaseStateScraper):
    """Scraper for North Carolina state laws from https://www.ncleg.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for North Carolina's legislative website."""
        return "https://www.ncleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for North Carolina."""
        return [{
            "name": "North Carolina General Statutes",
            "url": f"{self.get_base_url()}/Laws/GeneralStatutes",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from North Carolina's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/Laws/GeneralStatutes",
            f"{self.get_base_url()}/Laws",
            # Archive fallback candidate when live endpoints fluctuate.
            "https://web.archive.org/web/20251017000000/https://www.ncleg.gov/Laws/GeneralStatutes",
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
                        "N.C. Gen. Stat.",
                        max_sections=160,
                        wait_for_selector="a[href*='GeneralStatutes'], a[href*='Chapter'], a[href*='Statute'], a[href*='Laws']",
                        timeout=45000,
                    )
                    if statutes:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "N.C. Gen. Stat.", max_sections=160)
            if statutes:
                return statutes

        return []


# Register this scraper with the registry
StateScraperRegistry.register("NC", NorthCarolinaScraper)
