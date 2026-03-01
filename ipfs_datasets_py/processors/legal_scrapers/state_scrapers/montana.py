"""Scraper for Montana state laws.

This module contains the scraper for Montana statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class MontanaScraper(BaseStateScraper):
    """Scraper for Montana state laws from https://leg.mt.gov"""

    _MT_SECTION_URL_RE = re.compile(r"/\d{4}-\d{4}-\d{4}-\d{4}\.html$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MT_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Montana's legislative website."""
        return "https://leg.mt.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Montana."""
        return [{
            "name": "Montana Code Annotated",
            "url": f"{self.get_base_url()}/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Montana's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/bills/mca/",
            f"{self.get_base_url()}/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html",
            "https://archive.legmt.gov/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html",
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
                        "Mont. Code Ann.",
                        max_sections=220,
                        wait_for_selector="a[href*='/bills/mca/'], a[href*='/section_'], a[href*='chapters_index']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= 20:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Mont. Code Ann.", max_sections=220)
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 20:
                return statutes

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("MT", MontanaScraper)
