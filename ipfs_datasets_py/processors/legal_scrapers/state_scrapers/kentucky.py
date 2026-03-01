"""Scraper for Kentucky state laws.

This module contains the scraper for Kentucky statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class KentuckyScraper(BaseStateScraper):
    """Scraper for Kentucky state laws from https://legislature.ky.gov"""

    _KY_SECTION_URL_RE = re.compile(r"/law/statutes/statute\.aspx\?id=\d+$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._KY_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Kentucky's legislative website."""
        return "https://legislature.ky.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Kentucky."""
        return [{
            "name": "Kentucky Revised Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Kentucky's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            "https://apps.legislature.ky.gov/law/statutes/",
            "https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=37024",
            "https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=37025",
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
                        "Ky. Rev. Stat.",
                        max_sections=200,
                        wait_for_selector="a[href*='statute.aspx?id='], a[href*='chapter.aspx?id=']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= 30:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Ky. Rev. Stat.", max_sections=200)
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 30:
                return statutes

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("KY", KentuckyScraper)
