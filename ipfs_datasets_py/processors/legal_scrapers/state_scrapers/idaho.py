"""Scraper for Idaho state laws.

This module contains the scraper for Idaho statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class IdahoScraper(BaseStateScraper):
    """Scraper for Idaho state laws from https://legislature.idaho.gov"""

    _ID_SECTION_URL_RE = re.compile(r"/statutesrules/idstat/title\d+/t\d+ch\d+/sect\d+[\-\.0-9A-Za-z]*$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._ID_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Idaho's legislative website."""
        return "https://legislature.idaho.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Idaho."""
        return [{
            "name": "Idaho Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Idaho's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            "https://legislature.idaho.gov/statutesrules/idstat/Title1/T1CH1",
            "https://legislature.idaho.gov/statutesrules/idstat/Title18/T18CH1",
            "https://legislature.idaho.gov/statutesrules/idstat/",
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
                        "Idaho Code",
                        max_sections=220,
                        wait_for_selector="a[href*='/SECT'], a[href*='/T1CH'], a[href*='/T18CH']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= 30:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Idaho Code", max_sections=220)
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 30:
                return statutes

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("ID", IdahoScraper)
