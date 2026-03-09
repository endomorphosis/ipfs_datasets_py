"""Scraper for Arkansas state laws.

This module contains the scraper for Arkansas statutes from the official state legislative website.
"""

import asyncio
import re
from typing import List, Dict
from urllib.parse import urljoin

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class ArkansasScraper(BaseStateScraper):
    """Scraper for Arkansas state laws from https://www.arkleg.state.ar.us"""

    _AR_JUSTIA_TITLE_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/?$", re.IGNORECASE)
    _AR_JUSTIA_INTERMEDIATE_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/(?!.*section-)[^?#]+/?$", re.IGNORECASE)
    _AR_JUSTIA_SECTION_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/.*/section-[^/]+/?$", re.IGNORECASE)
    _AR_SECTION_NUMBER_RE = re.compile(r"/section-([^/]+)/?$", re.IGNORECASE)

    def _filter_non_code_results(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        for statute in statutes:
            url = str(statute.source_url or "").lower()
            text = str(statute.full_text or "").lower()
            allow_justia_section = bool(self._AR_JUSTIA_SECTION_RE.search(url))
            if "/acts/codesectionsamended" in url:
                continue
            if "codeofarrules.arkansas.gov" in url:
                continue
            if "code sections amended" in text or "state government directory" in text:
                continue
            if "law.justia.com" in url and not allow_justia_section:
                continue
            out.append(statute)
        return out
    
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
        justia_statutes = await self._scrape_justia_titles(code_name, max_statutes=180)
        justia_statutes = self._filter_non_code_results(justia_statutes)
        if len(justia_statutes) >= 60:
            return justia_statutes

        candidate_urls = [
            code_url,
            "https://law.justia.com/codes/arkansas/",
            "https://web.archive.org/web/20231201000000/https://law.justia.com/codes/arkansas/",
            "https://www.arkleg.state.ar.us/",
            "https://www.arkleg.state.ar.us/ArkansasCode/",
            "https://web.archive.org/web/20240101000000/https://www.arkleg.state.ar.us/ArkansasCode/",
        ]

        seen = set()
        merged: List[NormalizedStatute] = list(justia_statutes)
        merged_keys = set()
        for statute in justia_statutes:
            key = str(statute.statute_id or statute.source_url or "").strip().lower()
            if key:
                merged_keys.add(key)

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

            statutes = await self._generic_scrape(code_name, candidate, "Ark. Code Ann.", max_sections=720)
            statutes = self._filter_non_code_results(statutes)
            _merge(statutes)
            if len(merged) >= 80:
                return merged

        return merged

    async def _scrape_justia_titles(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = "https://law.justia.com/codes/arkansas/"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=40)
        except Exception:
            return []
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        title_urls: List[str] = []
        seen_titles = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not self._AR_JUSTIA_TITLE_RE.search(href):
                continue
            if href in seen_titles:
                continue
            seen_titles.add(href)
            title_urls.append(href)
            if len(title_urls) >= 40:
                break

        section_urls: List[str] = []
        intermediate_urls: List[str] = []
        seen_intermediate = set()
        seen_sections = set()
        for title_url in title_urls:
            try:
                title_payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=35)
            except Exception:
                continue
            if not title_payload:
                continue
            title_soup = BeautifulSoup(title_payload, "html.parser")
            for anchor in title_soup.find_all("a", href=True):
                href = urljoin(title_url, str(anchor.get("href") or "").strip())
                if not self._AR_JUSTIA_SECTION_RE.search(href):
                    if self._AR_JUSTIA_INTERMEDIATE_RE.search(href) and href not in seen_intermediate and href != title_url:
                        seen_intermediate.add(href)
                        intermediate_urls.append(href)
                    continue
                if href not in seen_sections:
                    seen_sections.add(href)
                    section_urls.append(href)
                if len(section_urls) >= max(1, int(max_statutes * 4)):
                    break
            if len(section_urls) >= max(1, int(max_statutes * 4)):
                break

        for page_url in intermediate_urls[: max(1, int(max_statutes * 2))]:
            try:
                page_payload = await self._fetch_page_content_with_archival_fallback(page_url, timeout_seconds=35)
            except Exception:
                continue
            if not page_payload:
                continue
            page_soup = BeautifulSoup(page_payload, "html.parser")
            for anchor in page_soup.find_all("a", href=True):
                href = urljoin(page_url, str(anchor.get("href") or "").strip())
                if not self._AR_JUSTIA_SECTION_RE.search(href):
                    continue
                if href in seen_sections:
                    continue
                seen_sections.add(href)
                section_urls.append(href)
                if len(section_urls) >= max(1, int(max_statutes * 4)):
                    break
            if len(section_urls) >= max(1, int(max_statutes * 4)):
                break

        sem = asyncio.Semaphore(12)

        async def _fetch_one(section_url: str, index: int) -> NormalizedStatute | None:
            async with sem:
                return await self._build_justia_statute(code_name=code_name, section_url=section_url, fallback_number=str(index))

        statutes: List[NormalizedStatute] = []
        jobs = [_fetch_one(section_url, idx) for idx, section_url in enumerate(section_urls[: max(1, int(max_statutes * 4))], start=1)]
        for result in await asyncio.gather(*jobs, return_exceptions=True):
            if isinstance(result, Exception) or result is None:
                continue
            statutes.append(result)
            if len(statutes) >= max_statutes:
                break

        return statutes

    async def _build_justia_statute(self, *, code_name: str, section_url: str, fallback_number: str) -> NormalizedStatute | None:
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

        html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        soup = BeautifulSoup(html, "html.parser")
        content_node = soup.select_one("main") or soup.select_one("article") or soup.select_one("body")
        if content_node is None:
            return None

        full_text = self._extract_best_content_text(str(content_node))
        full_text = re.split(r"\bDisclaimer:\b", full_text, maxsplit=1)[0].strip()
        full_text = re.split(r"\bAsk a Lawyer\b", full_text, maxsplit=1)[0].strip()
        full_text = re.sub(r"\s+", " ", full_text).strip()
        if len(full_text) < 280:
            return None

        heading_node = soup.select_one("h1") or soup.select_one("title")
        heading = " ".join((heading_node.get_text(" ", strip=True) if heading_node else "").split())
        match = self._AR_SECTION_NUMBER_RE.search(section_url)
        section_number = match.group(1) if match else fallback_number

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=(heading or f"Arkansas Code {section_number}")[:200],
            full_text=full_text[:14000],
            source_url=section_url,
            legal_area=self._identify_legal_area(heading),
            official_cite=f"Ark. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
        )


# Register this scraper with the registry
StateScraperRegistry.register("AR", ArkansasScraper)
