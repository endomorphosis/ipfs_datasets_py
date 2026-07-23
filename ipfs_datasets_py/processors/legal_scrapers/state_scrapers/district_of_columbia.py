"""Scraper for District of Columbia state laws.

This module contains the scraper for District of Columbia statutes from the official state legislative website.
"""

from typing import List, Dict, Optional
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class DistrictOfColumbiaScraper(BaseStateScraper):
    """Scraper for District of Columbia state laws from https://code.dccouncil.us"""

    _DC_SECTION_URL_RE = re.compile(
        r"/us/dc/council/code/(?:sections/[0-9A-Za-z\-]+|titles/\d+/chapters/\d+(?:/subchapters/[IVXLC]+)?)$",
        re.IGNORECASE,
    )

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._DC_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for District of Columbia's legislative website."""
        return "https://code.dccouncil.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for District of Columbia."""
        return [{
            "name": "District of Columbia Official Code",
            "url": f"{self.get_base_url()}/us/dc/council/code",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from District of Columbia's legislative website.
        
        DC Code uses JavaScript rendering, so we use Playwright.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/us/dc/council/code/titles/1",
            f"{self.get_base_url()}/us/dc/council/code/titles/2",
            f"{self.get_base_url()}/us/dc/council/code/titles/3",
            f"{self.get_base_url()}/us/dc/council/code/titles/4",
            f"{self.get_base_url()}/us/dc/council/code/titles/5",
            f"{self.get_base_url()}/us/dc/council/code/titles/1/chapters/1",
            f"{self.get_base_url()}/us/dc/council/code/titles/2/chapters/1",
            f"{self.get_base_url()}/us/dc/council/code/titles/1/chapters/1/subchapters/I",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        limit = self._effective_scrape_limit(max_statutes, default=160)
        return_threshold = limit if limit is not None else 1000000
        scan_limit = return_threshold if limit is not None else 1000
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "D.C. Code",
                        max_sections=scan_limit,
                        wait_for_selector="a[href*='/sections/'], a[href*='/subchapters/'], a[href*='/chapters/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes[:return_threshold]
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "D.C. Code",
                max_sections=scan_limit,
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes[:return_threshold]

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("DC", DistrictOfColumbiaScraper)
