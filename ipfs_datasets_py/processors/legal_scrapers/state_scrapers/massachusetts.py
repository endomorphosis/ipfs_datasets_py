"""Scraper for Massachusetts state laws.

This module contains the scraper for Massachusetts statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class MassachusettsScraper(BaseStateScraper):
    """Scraper for Massachusetts state laws from https://malegislature.gov"""

    _MA_SECTION_URL_RE = re.compile(
        r"/laws/generallaws/(?:part[a-z0-9-]*|title[a-z0-9-]*|chapter[a-z0-9-]*|section[a-z0-9-]*)(?:/|$)",
        re.IGNORECASE,
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Massachusetts's legislative website."""
        return "https://malegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Massachusetts."""
        return [{
            "name": "Massachusetts General Laws",
            "url": f"{self.get_base_url()}/Laws/GeneralLaws",
            "type": "Code"
        }]

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MA_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Massachusetts's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/Laws/GeneralLaws/PartI",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartII",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartIII",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartIV",
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

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "Mass. Gen. Laws",
                max_sections=260,
            )
            statutes = self._filter_section_level(statutes)
            _merge(statutes)
            if len(merged) >= 40:
                return merged

        return merged


# Register this scraper with the registry
StateScraperRegistry.register("MA", MassachusettsScraper)
