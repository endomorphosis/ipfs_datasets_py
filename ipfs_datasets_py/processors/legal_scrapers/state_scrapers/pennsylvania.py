"""Scraper for Pennsylvania state laws.

This module contains the scraper for Pennsylvania statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class PennsylvaniaScraper(BaseStateScraper):
    """Scraper for Pennsylvania state laws from https://www.legis.state.pa.us"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Pennsylvania's legislative website."""
        return "https://www.legis.state.pa.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Pennsylvania."""
        return [{
            "name": "Pennsylvania Consolidated Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Pennsylvania's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/cfdocs/legis/LI/Public/li_index.cfm",
            f"{self.get_base_url()}/WU01/LI/LI/CT/HTM/",
            "https://law.justia.com/codes/pennsylvania/",
            "https://web.archive.org/web/20250201000000/https://law.justia.com/codes/pennsylvania/",
            "https://web.archive.org/web/20250201000000/https://www.legis.state.pa.us/cfdocs/legis/LI/Public/li_index.cfm",
        ]

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()
        return_threshold = self._bounded_return_threshold(80)

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

            statutes = await self._generic_scrape(code_name, candidate, "Pa. Cons. Stat.", max_sections=900)
            _merge(statutes)
            if len(merged) >= return_threshold:
                return merged

        return merged


# Register this scraper with the registry
StateScraperRegistry.register("PA", PennsylvaniaScraper)
