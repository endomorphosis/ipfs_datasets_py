"""Scraper for Maine state laws.

This module contains the scraper for Maine statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class MaineScraper(BaseStateScraper):
    """Scraper for Maine state laws from http://legislature.maine.gov"""

    _ME_SECTION_URL_RE = re.compile(r"/statutes/[0-9A-Za-z\-]+/title[0-9A-Za-z\-]+sec[0-9A-Za-z\-]+\.html$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._ME_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Maine's legislative website."""
        return "http://legislature.maine.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Maine."""
        return [{
            "name": "Maine Revised Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Maine's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            "https://legislature.maine.gov/statutes/1/title1ch1sec0.html",
            "https://legislature.maine.gov/statutes/17-A/title17-Ach1sec0.html",
            "https://legislature.maine.gov/statutes/",
            code_url,
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Me. Rev. Stat.",
                        max_sections=220,
                        wait_for_selector="a[href*='sec'][href$='.html'], a[href*='ch'][href$='sec0.html']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= 30:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Me. Rev. Stat.", max_sections=220)
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 30:
                return statutes

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("ME", MaineScraper)
