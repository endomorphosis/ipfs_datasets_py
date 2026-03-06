"""Scraper for New Hampshire state laws.

This module contains the scraper for New Hampshire statutes from the official state legislative website.
"""

from typing import List, Dict
import json
import re
from urllib.parse import quote
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class NewHampshireScraper(BaseStateScraper):
    """Scraper for New Hampshire state laws from http://www.gencourt.state.nh.us"""

    _NH_STATUTE_URL_RE = re.compile(
        r"/rsa/html/(?:NHTOC/[^/?#]+\.htm|(?:[^/?#]+/)+[^/?#]+\.htm)$",
        re.IGNORECASE,
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for New Hampshire's legislative website."""
        return "http://www.gencourt.state.nh.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for New Hampshire."""
        return [{
            "name": "New Hampshire Revised Statutes",
            "url": f"{self.get_base_url()}/rsa/html/NHTOC.htm",
            "type": "Code"
        }]

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._NH_STATUTE_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from New Hampshire's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/rsa/html/NHTOC.htm",
            f"{self.get_base_url()}/rsa/html/",
            "http://web.archive.org/web/20250101000000/http://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
            "https://web.archive.org/web/20250101000000/http://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
        ]
        for archived in await self._discover_archived_rsa_urls(limit=220):
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

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "N.H. Rev. Stat.",
                max_sections=320,
            )
            statutes = self._filter_section_level(statutes)
            _merge(statutes)
            if len(merged) >= 40:
                return merged

        return merged

    async def _discover_archived_rsa_urls(self, limit: int = 180) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=www.gencourt.state.nh.us/rsa/html/*"
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
            if "/rsa/html/" not in lower_original:
                continue
            replay = f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}"
            if replay in seen:
                continue
            seen.add(replay)
            out.append(replay)
            if len(out) >= limit:
                break

        return out

    def _parse_json_rows(self, payload: bytes) -> List[List[object]]:
        if not payload:
            return []
        try:
            parsed = json.loads(payload.decode("utf-8", errors="ignore"))
        except Exception:
            return []
        if not isinstance(parsed, list):
            return []
        return [row for row in parsed[1:] if isinstance(row, list)]


# Register this scraper with the registry
StateScraperRegistry.register("NH", NewHampshireScraper)
