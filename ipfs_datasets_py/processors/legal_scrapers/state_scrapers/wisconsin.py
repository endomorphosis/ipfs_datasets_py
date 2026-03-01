"""Scraper for Wisconsin state laws.

This module contains the scraper for Wisconsin statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class WisconsinScraper(BaseStateScraper):
    """Scraper for Wisconsin state laws from https://docs.legis.wisconsin.gov"""

    _WI_SECTION_URL_RE = re.compile(r"/document/statutes/[0-9]+(?:\.[0-9A-Za-z]+)+$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._WI_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
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
                        "Wis. Stat.",
                        max_sections=250,
                        wait_for_selector="a[href*='/document/statutes/'], a[href*='/statutes/statutes']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= 40:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Wis. Stat.", max_sections=250)
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 40:
                return statutes

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("WI", WisconsinScraper)
