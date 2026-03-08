"""Scraper for Minnesota state laws.

This module contains the scraper for Minnesota statutes from the official state legislative website.
"""

import asyncio
from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MinnesotaScraper(BaseStateScraper):
    """Scraper for Minnesota state laws from https://www.revisor.mn.gov"""

    _MN_SECTION_URL_RE = re.compile(r"/statutes/cite/[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*$", re.IGNORECASE)
    _MN_SECTION_NUMBER_RE = re.compile(r"/statutes/cite/([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MN_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Minnesota's legislative website."""
        return "https://www.revisor.mn.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Minnesota."""
        return [{
            "name": "Minnesota Statutes",
            "url": f"{self.get_base_url()}/statutes/cite/609.02",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Minnesota's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/cite/609.02",
            f"{self.get_base_url()}/statutes/",
            f"{self.get_base_url()}/statutes/cite/645.44",
            "https://law.justia.com/codes/minnesota/",
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

        chapter_statutes = await self._scrape_chapter_sections(code_name, max_statutes=260)
        _merge(chapter_statutes)
        if len(merged) >= 40:
            return merged

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Minn. Stat.",
                        max_sections=420,
                        wait_for_selector="a[href*='/statutes/cite/'], a[href*='/statutes/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    _merge(statutes)
                    if len(merged) >= 40:
                        return merged
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Minn. Stat.", max_sections=420)
            statutes = self._filter_section_level(statutes)
            _merge(statutes)
            if len(merged) >= 40:
                return merged

        return merged

    async def _scrape_chapter_sections(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        chapter_urls = [
            f"{self.get_base_url()}/statutes/cite/609",
            f"{self.get_base_url()}/statutes/cite/645",
            f"{self.get_base_url()}/statutes/cite/518B",
            f"{self.get_base_url()}/statutes/cite/169A",
            f"{self.get_base_url()}/statutes/cite/8",
            f"{self.get_base_url()}/statutes/cite/13",
            f"{self.get_base_url()}/statutes/cite/144",
            f"{self.get_base_url()}/statutes/cite/325F",
        ]

        section_urls: List[str] = []
        seen_urls = set()
        for chapter_url in chapter_urls:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=35)
            except Exception:
                continue
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                if not href.startswith("/statutes/cite/"):
                    continue
                full_url = href if href.startswith("http") else f"{self.get_base_url()}{href}"
                if not self._MN_SECTION_URL_RE.search(full_url):
                    continue
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                section_urls.append(full_url)
                if len(section_urls) >= max_statutes * 4:
                    break
            if len(section_urls) >= max_statutes * 4:
                break

        if not section_urls:
            return []

        sem = asyncio.Semaphore(10)

        async def _fetch_one(section_url: str) -> NormalizedStatute | None:
            async with sem:
                return await self._build_statute_from_section_page(code_name, section_url)

        statutes: List[NormalizedStatute] = []
        for result in await asyncio.gather(*[_fetch_one(url) for url in section_urls[: max_statutes * 4]], return_exceptions=True):
            if isinstance(result, Exception) or result is None:
                continue
            statutes.append(result)
            if len(statutes) >= max_statutes:
                break

        return statutes

    async def _build_statute_from_section_page(self, code_name: str, section_url: str) -> NormalizedStatute | None:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        try:
            payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=35)
        except Exception:
            return None
        if not payload:
            return None

        soup = BeautifulSoup(payload, "html.parser")
        text = " ".join(soup.get_text(" ", strip=True).split())
        if len(text) < 160:
            return None

        match = self._MN_SECTION_NUMBER_RE.search(section_url)
        section_number = match.group(1) if match else section_url.rsplit("/", 1)[-1]
        heading = ""
        for selector in ("h1", "h2", "title"):
            node = soup.select_one(selector)
            if node:
                heading = " ".join(node.get_text(" ", strip=True).split())
                if heading:
                    break
        if not heading:
            heading = f"Minnesota Statutes {section_number}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=heading[:200],
            full_text=text[:14000],
            source_url=section_url,
            legal_area=self._identify_legal_area(heading),
            official_cite=f"Minn. Stat. § {section_number}",
            metadata=StatuteMetadata(),
        )


# Register this scraper with the registry
StateScraperRegistry.register("MN", MinnesotaScraper)
