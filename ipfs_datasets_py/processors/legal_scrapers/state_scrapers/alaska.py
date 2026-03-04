"""Scraper for Alaska state laws.

This module contains the scraper for Alaska statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class AlaskaScraper(BaseStateScraper):
    """Scraper for Alaska state laws from http://www.legis.state.ak.us"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Alaska's legislative website."""
        return "http://www.legis.state.ak.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Alaska."""
        return [{
            "name": "Alaska Statutes",
            "url": "https://www.akleg.gov/basis/statutes.asp",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Alaska's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            "https://www.akleg.gov/basis/statutes.asp",
            "https://law.justia.com/codes/alaska/",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(code_name, candidate, "Alaska Stat.", max_sections=240)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 30:
                return statutes

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("AK", AlaskaScraper)
