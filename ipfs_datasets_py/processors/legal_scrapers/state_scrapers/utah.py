"""Scraper for Utah state laws.

This module contains the scraper for Utah statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class UtahScraper(BaseStateScraper):
    """Scraper for Utah state laws from https://le.utah.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Utah's legislative website."""
        return "https://le.utah.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Utah."""
        return [{
            "name": "Utah Code",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Utah's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/xcode/",
            f"{self.get_base_url()}/xcode/Title01/",
            "https://law.justia.com/codes/utah/",
            "https://web.archive.org/web/20250301000000/https://le.utah.gov/xcode/",
            "https://web.archive.org/web/20250301000000/https://le.utah.gov/xcode/Title01/",
            "https://web.archive.org/web/20250301000000/https://le.utah.gov/xcode/Title10/",
            "https://web.archive.org/web/20250301000000/https://le.utah.gov/xcode/Title17/",
            "https://web.archive.org/web/20250301000000/https://le.utah.gov/xcode/Title76/",
            "https://web.archive.org/web/20250301000000/https://le.utah.gov/xcode/Title78B/",
        ]

        for title in range(1, 33):
            candidate_urls.append(f"https://web.archive.org/web/20250301000000/https://le.utah.gov/xcode/Title{title:02d}/")

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(code_name, candidate, "Utah Code Ann.", max_sections=360)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 40:
                return statutes

        return best_statutes


# Register this scraper with the registry
StateScraperRegistry.register("UT", UtahScraper)
