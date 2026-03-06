"""Scraper for Minnesota state laws.

This module contains the scraper for Minnesota statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class MinnesotaScraper(BaseStateScraper):
    """Scraper for Minnesota state laws from https://www.revisor.mn.gov"""

    _MN_SECTION_URL_RE = re.compile(r"/statutes/cite/[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MN_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Minnesota's legislative website."""
        return "https://www.revisor.mn.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Minnesota."""
        return [{
            "name": "Minnesota Statutes",
            "url": f"{self.get_base_url()}/statutes/cite/609.02",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Minnesota's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/cite/609.02",
            f"{self.get_base_url()}/statutes/",
            f"{self.get_base_url()}/statutes/cite/645.44",
            "https://law.justia.com/codes/minnesota/",
        ]

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Minn. Stat.",
                        max_sections=220,
                        wait_for_selector="a[href*='/statutes/cite/'], a[href*='/statutes/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    _merge(statutes)
                    if len(merged) >= 40:
                        return merged
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Minn. Stat.", max_sections=220)
            statutes = self._filter_section_level(statutes)
            _merge(statutes)
            if len(merged) >= 40:
                return merged

        return merged


# Register this scraper with the registry
StateScraperRegistry.register("MN", MinnesotaScraper)
