"""Scraper for Washington state laws.

This module contains the scraper for Washington statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class WashingtonScraper(BaseStateScraper):
    """Scraper for Washington state laws from https://app.leg.wa.gov"""

    _SECTION_CITE_RE = re.compile(r"^\d+[A-Za-z]?\.\d+\.\d+[A-Za-z]?$")

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            section_number = str(statute.section_number or "")
            if "default.aspx?cite=" not in source.lower():
                continue
            if self._SECTION_CITE_RE.match(section_number):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Washington's legislative website."""
        return "https://app.leg.wa.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Washington."""
        return [{
            "name": "Revised Code of Washington",
            "url": f"{self.get_base_url()}/RCW/default.aspx?cite=9A.32.030",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Washington's legislative website.
        
        Washington RCW database uses JavaScript navigation, so we use Playwright.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/RCW/default.aspx?cite=9A.32.030",
            f"{self.get_base_url()}/RCW/default.aspx?cite=9A.04",
            f"{self.get_base_url()}/RCW/default.aspx",
            f"{self.get_base_url()}/RCW/",
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
                        "Wash. Rev. Code",
                        max_sections=220,
                        wait_for_selector="a[href*='default.aspx?cite='], a[href*='/RCW/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= 20:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Wash. Rev. Code", max_sections=220)
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 20:
                return statutes

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("WA", WashingtonScraper)
