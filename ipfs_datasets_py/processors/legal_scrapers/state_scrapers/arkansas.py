"""Scraper for Arkansas state laws.

This module contains the scraper for Arkansas statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class ArkansasScraper(BaseStateScraper):
    """Scraper for Arkansas state laws from https://www.arkleg.state.ar.us"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Arkansas's legislative website."""
        return "https://www.arkleg.state.ar.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Arkansas."""
        return [{
            "name": "Arkansas Code",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Arkansas's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            "https://law.justia.com/codes/arkansas/",
            "https://web.archive.org/web/20231201000000/https://law.justia.com/codes/arkansas/",
            "https://www.arkleg.state.ar.us/",
            "https://www.arkleg.state.ar.us/ArkansasCode/",
            "https://web.archive.org/web/20240101000000/https://www.arkleg.state.ar.us/ArkansasCode/",
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

            statutes = await self._generic_scrape(code_name, candidate, "Ark. Code Ann.", max_sections=260)
            _merge(statutes)
            if len(merged) >= 30:
                return merged

        return merged


# Register this scraper with the registry
StateScraperRegistry.register("AR", ArkansasScraper)
