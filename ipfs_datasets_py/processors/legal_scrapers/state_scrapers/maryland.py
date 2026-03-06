"""Scraper for Maryland state laws.

This module contains the scraper for Maryland statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class MarylandScraper(BaseStateScraper):
    """Scraper for Maryland state laws from http://mgaleg.maryland.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Maryland's legislative website."""
        return "https://mgaleg.maryland.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Maryland."""
        return [{
            "name": "Maryland Code",
            "url": f"{self.get_base_url()}/mgawebsite/Laws/StatuteText",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Maryland's legislative website.
        
        Maryland uses JavaScript for statute search, so we use Playwright.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/mgawebsite/Laws/StatuteText",
            f"{self.get_base_url()}/mgawebsite/Laws/Code",
            "https://law.justia.com/codes/maryland/",
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

            try:
                statutes = await self._playwright_scrape(
                    code_name,
                    candidate,
                    "Md. Code Ann.",
                    wait_for_selector="a[href*='statute'], a[href*='laws'], .article-link",
                    timeout=45000,
                    max_sections=260,
                )
            except Exception:
                statutes = []

            _merge(statutes)
            if len(merged) >= 30:
                return merged

            try:
                generic = await self._generic_scrape(code_name, candidate, "Md. Code Ann.", max_sections=260)
            except Exception:
                generic = []

            _merge(generic)
            if len(merged) >= 30:
                return merged

        return merged


# Register this scraper with the registry
StateScraperRegistry.register("MD", MarylandScraper)
