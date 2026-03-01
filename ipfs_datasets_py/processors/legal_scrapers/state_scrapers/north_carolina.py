"""Scraper for North Carolina state laws.

This module contains the scraper for North Carolina statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class NorthCarolinaScraper(BaseStateScraper):
    """Scraper for North Carolina state laws from https://www.ncleg.gov"""

    _NC_SECTION_URL_RE = re.compile(r"/enactedlegislation/statutes/html/bysection/chapter_[0-9A-Za-z]+/gs_[0-9A-Za-z\-\.]+\.html$", re.IGNORECASE)
    _NC_CHAPTER_URL_RE = re.compile(r"/laws/generalstatutesections/chapter[0-9A-Za-z]+$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._NC_SECTION_URL_RE.search(source) or self._NC_CHAPTER_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
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
            f"{self.get_base_url()}/Laws/GeneralStatuteSections/Chapter1",
            f"{self.get_base_url()}/Laws/GeneralStatutesTOC",
            code_url,
            f"{self.get_base_url()}/Laws/GeneralStatutes",
            f"{self.get_base_url()}/Laws",
            # Archive fallback candidate when live endpoints fluctuate.
            "https://web.archive.org/web/20251017000000/https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter1",
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
                        "N.C. Gen. Stat.",
                        max_sections=240,
                        wait_for_selector="a[href*='/BySection/'][href*='GS_'], a[href*='/GeneralStatuteSections/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= 30:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "N.C. Gen. Stat.", max_sections=240)
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 30:
                return statutes

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("NC", NorthCarolinaScraper)
