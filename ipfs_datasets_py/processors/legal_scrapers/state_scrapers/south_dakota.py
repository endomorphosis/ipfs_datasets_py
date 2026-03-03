"""Scraper for South Dakota state laws.

This module contains the scraper for South Dakota statutes from the official
JSON statute endpoint.
"""

import re
import time
from html import unescape
from typing import Dict, List

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class SouthDakotaScraper(BaseStateScraper):
    """Scraper for South Dakota state laws from https://sdlegislature.gov"""

    _SEED_SECTIONS = [
        "1-1-1",
        "1-1-1.1",
        "1-1-2",
        "1-1-3",
        "1-1-4",
        "1-1-5",
        "1-1-6",
        "1-1-7",
    ]
    
    def get_base_url(self) -> str:
        """Return the base URL for South Dakota's legislative website."""
        return "https://sdlegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for South Dakota."""
        return [{
            "name": "South Dakota Codified Laws",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from South Dakota's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        api_statutes = await self._scrape_statutes_api(code_name=code_name, max_statutes=20)
        if api_statutes:
            self.logger.info(f"South Dakota API fallback: Scraped {len(api_statutes)} sections")
            return api_statutes

        return await self._generic_scrape(code_name, code_url, "S.D. Codified Laws")

    async def _scrape_statutes_api(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        statutes: List[NormalizedStatute] = []
        seen = set()

        for section in self._SEED_SECTIONS:
            if len(statutes) >= max_statutes:
                break
            if section in seen:
                continue

            data = await self._request_json(
                f"https://sdlegislature.gov/api/Statutes/Statute/{section}",
                headers=headers,
                timeout=35,
            )
            if not data:
                continue

            html = str(data.get("Html") or "")
            full_text = self._clean_html_text(html)
            if len(full_text) < 280:
                continue

            section_number = str(data.get("Statute") or section)
            section_name = str(data.get("CatchLine") or f"Section {section_number}").strip()

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:180],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(full_text),
                    source_url=f"https://sdlegislature.gov/api/Statutes/Statute/{section_number}",
                    official_cite=f"S.D. Codified Laws {section_number}",
                )
            )
            seen.add(section)

        return statutes

    async def _request_json(self, url: str, headers: Dict[str, str], timeout: int) -> Dict:
        for _ in range(3):
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    url,
                    timeout_seconds=timeout,
                )
                if not payload:
                    raise ValueError("empty response")
                data = self._parse_json_payload(payload)
                if isinstance(data, dict):
                    return data
            except Exception:
                time.sleep(0.5)
                continue
        return {}

    def _parse_json_payload(self, payload: bytes) -> Dict:
        try:
            import json

            parsed = json.loads(payload.decode("utf-8", errors="replace"))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
        return {}

    def _clean_html_text(self, html: str, max_chars: int = 14000) -> str:
        value = str(html or "")
        value = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", value)
        value = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", value)
        value = re.sub(r"(?is)<br\s*/?>", "\n", value)
        value = re.sub(r"(?is)</p>", "\n", value)
        value = re.sub(r"(?is)<[^>]+>", " ", value)
        value = unescape(value)
        value = value.replace("\xa0", " ")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\s*\n\s*", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()[:max_chars]


# Register this scraper with the registry
StateScraperRegistry.register("SD", SouthDakotaScraper)
