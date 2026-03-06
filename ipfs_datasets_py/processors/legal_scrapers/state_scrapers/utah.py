"""Scraper for Utah state laws.

This module contains the scraper for Utah statutes from the official state legislative website.
"""

from typing import List, Dict
from urllib.parse import quote
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
            "https://web.archive.org/web/20250101000000/https://law.justia.com/codes/utah/",
        ]
        for archived in await self._discover_archived_title_urls(limit=220):
            if archived not in candidate_urls:
                candidate_urls.append(archived)

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

            statutes = await self._generic_scrape(code_name, candidate, "Utah Code Ann.", max_sections=260)
            _merge(statutes)
            if len(merged) >= 40:
                return merged

        return merged

    async def _discover_archived_title_urls(self, limit: int = 180) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=le.utah.gov/xcode/Title*"
            "&output=json&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._fetch_page_content_with_archival_fallback(cdx_url, timeout_seconds=35)
            rows = self._parse_json_rows(payload)
        except Exception:
            return []

        out: List[str] = []
        seen = set()
        for row in rows:
            if len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue
            lower_original = original.lower()
            if "/xcode/title" not in lower_original:
                continue
            replay = f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}"
            if replay in seen:
                continue
            seen.add(replay)
            out.append(replay)
            if len(out) >= limit:
                break

        return out


# Register this scraper with the registry
StateScraperRegistry.register("UT", UtahScraper)
