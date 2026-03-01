"""Scraper for West Virginia state laws.

This module contains the scraper for West Virginia statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class WestVirginiaScraper(BaseStateScraper):
    """Scraper for West Virginia state laws from http://www.wvlegislature.gov"""

    _WV_SECTION_URL_RE = re.compile(r"/\d+[A-Za-z]?(?:-\d+[A-Za-z]?){2,}/?$")

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._WV_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for West Virginia's legislative website."""
        return "https://code.wvlegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for West Virginia."""
        return [{
            "name": "West Virginia Code",
            "url": f"{self.get_base_url()}/11-8-12/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from West Virginia's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/11-8-12/",
            f"{self.get_base_url()}/1-1/",
            f"{self.get_base_url()}/",
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
                        "W. Va. Code",
                        max_sections=220,
                        wait_for_selector="a[href*='wvlegislature.gov/'][href*='-'], a[href*='/code/'], a[href*='/article/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= 15:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "W. Va. Code", max_sections=220)
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 15:
                return statutes

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("WV", WestVirginiaScraper)
