"""Scraper for Virginia state laws.

This module contains the scraper for Virginia statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class VirginiaScraper(BaseStateScraper):
    """Scraper for Virginia state laws from https://law.lis.virginia.gov"""

    _VA_SECTION_URL_RE = re.compile(r"/vacode/title[0-9A-Za-z\.]+/chapter[0-9A-Za-z\.]+/section[0-9A-Za-z\-\.]+/?$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._VA_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Virginia's legislative website."""
        return "https://law.lis.virginia.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Virginia."""
        return [{
            "name": "Code of Virginia",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Virginia's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            "https://law.lis.virginia.gov/vacode/title1/chapter1/",
            "https://law.lis.virginia.gov/vacode/title18.2/chapter7/",
            "https://law.lis.virginia.gov/vacode/",
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
                        "Va. Code Ann.",
                        max_sections=220,
                        wait_for_selector="a[href*='/section'], a[href*='/chapter']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= 30:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Va. Code Ann.", max_sections=220)
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 30:
                return statutes

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("VA", VirginiaScraper)
