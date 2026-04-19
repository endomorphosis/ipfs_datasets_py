"""Scraper for Alaska state laws.

This module contains the scraper for Alaska statutes from the official state legislative website.
"""

from typing import List, Dict, Optional, Tuple
import re

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class AlaskaScraper(BaseStateScraper):
    """Scraper for Alaska state laws from http://www.legis.state.ak.us"""

    _AK_SECTION_RE = re.compile(r"\bSec\.\s*(\d{2}\.\d{2}\.\d{3})\.\s*(.+)", re.IGNORECASE | re.DOTALL)
    
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
    
    async def _fetch_statute_chunk(self, sec_start: str, timeout_seconds: int = 8) -> Tuple[str, str]:
        timeout = max(1, int(timeout_seconds or 8))

        def _request() -> Tuple[str, str]:
            try:
                import requests

                response = requests.get(
                    "https://www.akleg.gov/basis/statutes.asp",
                    params={"media": "print", "type": "fetch", "secStart": sec_start},
                    headers={
                        "User-Agent": "ipfs-datasets-alaska-statutes-scraper/2.0",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=timeout,
                )
                if int(response.status_code or 0) != 200:
                    return "", ""
                return bytes(response.content or b"").decode("cp1252", errors="replace"), str(response.headers.get("LastSec") or "")
            except Exception:
                return "", ""

        try:
            html, last_sec = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 1)
        except asyncio.TimeoutError:
            html, last_sec = "", ""
        self._record_fetch_event(provider="requests_direct", success=bool(html))
        return html, last_sec

    def _parse_statute_chunk(self, *, code_name: str, html: str) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html or "", "html.parser")
        statutes: List[NormalizedStatute] = []
        for div in soup.select("div.statute"):
            anchors = [a.get("name") for a in div.find_all("a") if a.get("name")]
            section_anchor = next((str(a) for a in anchors if re.match(r"^\d{2}\.\d{2}\.\d{3}$", str(a))), "")
            if not section_anchor:
                continue
            heading_node = None
            for bold in div.find_all("b"):
                anchor = bold.find("a")
                if anchor and str(anchor.get("name") or "") == section_anchor:
                    heading_node = bold
                    break
            heading = self._normalize_legal_text(heading_node.get_text(" ", strip=True) if heading_node else "")
            match = self._AK_SECTION_RE.search(heading)
            if not match:
                continue
            section_number = match.group(1)
            section_name = re.sub(r"\s+", " ", match.group(2)).strip()
            full_text = self._normalize_legal_text(div.get_text(" ", strip=True))
            if len(full_text) < 120:
                continue
            title_number, chapter_number, _section = section_number.split(".")
            source_url = f"https://www.akleg.gov/basis/statutes.asp#{section_number}"
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"AK-{section_number}",
                    code_name=code_name,
                    title_number=title_number,
                    chapter_number=chapter_number,
                    section_number=section_number,
                    section_name=section_name[:200],
                    short_title=section_name[:200],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(section_name),
                    source_url=source_url,
                    official_cite=f"Alaska Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_alaska_statutes_ajax_html",
                        "discovery_method": "official_fetch_endpoint",
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    def _next_sec_start(self, last_sec: str) -> Optional[str]:
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", str(last_sec or "").strip())
        if not match:
            return None
        title, chapter, _section = (int(part) for part in match.groups())
        return f"{title}.{chapter + 1:02d}"

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Alaska's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=240)
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        sec_start: Optional[str] = "1"

        for _ in range(80):
            if not sec_start or (limit is not None and len(statutes) >= limit):
                break
            html, last_sec = await self._fetch_statute_chunk(sec_start)
            if not html:
                break
            for statute in self._parse_statute_chunk(code_name=code_name, html=html):
                key = str(statute.section_number or "")
                if key in seen_sections:
                    continue
                seen_sections.add(key)
                statutes.append(statute)
                if limit is not None and len(statutes) >= limit:
                    break
            next_start = self._next_sec_start(last_sec)
            if not next_start or next_start == sec_start:
                break
            sec_start = next_start

        return statutes[:limit] if limit is not None else statutes


# Register this scraper with the registry
StateScraperRegistry.register("AK", AlaskaScraper)
