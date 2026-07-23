"""Scraper for Arizona state laws.

This module contains the scraper for Arizona statutes from the official state legislative website.
"""

from typing import List, Dict, Optional, Tuple
import re
from urllib.parse import parse_qs, urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class ArizonaScraper(BaseStateScraper):
    """Scraper for Arizona state laws from https://www.azleg.gov"""

    _AZ_TITLE_DETAIL_RE = re.compile(r"/arsDetail/\?title=\d+$", re.IGNORECASE)
    _AZ_SECTION_DOC_RE = re.compile(r"/ars/(\d+)/([0-9A-Za-z-]+)\.htm$", re.IGNORECASE)
    _AZ_SECTION_HEAD_RE = re.compile(r"^\s*(\d+-\d+(?:\.\d+)?)\s*[-–]\s*(.+)$")
    _AZ_DETAIL_SECTION_LINK_RE = re.compile(
        r'<a[^>]+class=["\'][^"\']*\bstat\b[^"\']*["\'][^>]+href=["\'](?P<href>[^"\']+)["\'][^>]*>\s*(?P<section>\d+-\d+(?:\.\d+)?)\s*</a>'
        r"\s*</li>\s*<li[^>]+class=[\"'][^\"']*\bcolright\b[^\"']*[\"'][^>]*>\s*(?P<title>.*?)\s*</li>",
        re.IGNORECASE | re.DOTALL,
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Arizona's legislative website."""
        return "https://www.azleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Arizona."""
        # Arizona publishes titles behind a consistent static endpoint. Return
        # every likely title so full-corpus runs can walk the whole ARS, while
        # bounded runs stop after the first successful title via scrape_all().
        return [
            {
                "name": f"Arizona Revised Statutes Title {title}",
                "url": f"{self.get_base_url()}/arsDetail/?title={title}",
                "type": "Code",
            }
            for title in range(1, 50)
        ]
    
    async def _fetch_official_az_html(self, url: str, timeout_seconds: int = 8) -> str:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached.decode("utf-8", errors="replace")
        timeout = max(1, int(timeout_seconds or 8))

        def _request() -> str:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-arizona-ars-scraper/2.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                    timeout=timeout,
                )
                if int(response.status_code or 0) != 200:
                    return ""
                return bytes(response.content or b"").decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            html = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 1)
        except asyncio.TimeoutError:
            html = ""
        self._record_fetch_event(provider="requests_direct", success=bool(html))
        if html:
            await self._cache_successful_page_fetch(
                url=url,
                payload=html.encode("utf-8", errors="replace"),
                provider="requests_direct",
            )
        return html

    def _raw_doc_url_from_href(self, href: str, base_url: str) -> str:
        value = urljoin(base_url, str(href or "").strip())
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        doc_name = (query.get("docName") or query.get("docname") or [""])[0]
        return doc_name.strip() if doc_name else value

    async def _discover_section_links(self, title_url: str) -> List[Tuple[str, str, str]]:
        html = await self._fetch_official_az_html(title_url)
        if not html:
            return []

        out: List[Tuple[str, str, str]] = []
        seen: set[str] = set()
        for match in self._AZ_DETAIL_SECTION_LINK_RE.finditer(html):
            label = re.sub(r"\s+", " ", match.group("section") or "").strip()
            raw_url = self._raw_doc_url_from_href(str(match.group("href") or ""), title_url)
            if not self._AZ_SECTION_DOC_RE.search(raw_url):
                continue
            if raw_url in seen:
                continue
            seen.add(raw_url)
            title = re.sub(r"<[^>]+>", " ", str(match.group("title") or ""))
            title = re.sub(r"\s+", " ", title).strip()
            out.append((raw_url, label, title))
        return out

    async def _build_statute_from_section_page(
        self,
        *,
        code_name: str,
        section_url: str,
        section_number: str,
        section_title: str = "",
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._fetch_official_az_html(section_url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body") or soup
        full_text = self._normalize_legal_text(body.get_text(" ", strip=True))
        if "Page not found" in full_text or len(full_text) < 120:
            return None

        heading = ""
        first_p = body.find("p") if hasattr(body, "find") else None
        if first_p is not None:
            heading = self._normalize_legal_text(first_p.get_text(" ", strip=True))
        match = self._AZ_SECTION_HEAD_RE.match(heading)
        if match:
            section_number = match.group(1)
            section_title = match.group(2).strip()

        url_match = self._AZ_SECTION_DOC_RE.search(section_url)
        title_number = url_match.group(1) if url_match else section_number.split("-", 1)[0]
        chapter_number = section_number.split("-", 1)[1].split(".", 1)[0][:2] if "-" in section_number else None

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"AZ-{section_number}",
            code_name=code_name,
            title_number=title_number,
            chapter_number=chapter_number,
            section_number=section_number,
            section_name=(section_title or heading or section_number)[:200],
            short_title=(section_title or heading or section_number)[:200],
            full_text=full_text,
            legal_area=self._identify_legal_area(section_title or heading),
            source_url=section_url,
            official_cite=f"Ariz. Rev. Stat. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_arizona_ars_html",
                "discovery_method": "official_title_detail_index",
                "skip_hydrate": True,
            },
        )

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Arizona's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=240)
        statutes: List[NormalizedStatute] = []
        for section_url, section_number, section_title in await self._discover_section_links(code_url):
            if limit is not None and len(statutes) >= limit:
                break
            statute = await self._build_statute_from_section_page(
                code_name=code_name,
                section_url=section_url,
                section_number=section_number,
                section_title=section_title,
            )
            if statute is not None:
                statutes.append(statute)
        return statutes[:limit] if limit is not None else statutes


# Register this scraper with the registry
StateScraperRegistry.register("AZ", ArizonaScraper)
