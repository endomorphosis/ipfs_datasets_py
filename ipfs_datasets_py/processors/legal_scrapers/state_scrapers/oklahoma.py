"""Scraper for Oklahoma state laws.

This module contains the scraper for Oklahoma statutes using OSCN's
DeliverDocument statute pages.
"""

import json
import asyncio
import re
import time
from typing import Dict, List, Set
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry
from .state_archival_fetch import ArchivalFetchClient


class OklahomaScraper(BaseStateScraper):
    """Scraper for Oklahoma state laws from http://www.oklegislature.gov"""

    _SEED_INDEX_URLS = [
        "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=69782&Title=74",
        "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=438588",
        "https://www.oscn.net/applications/oscn/Index.asp?ftdb=STOKST74",
        "https://www.oscn.net/applications/oscn/index.asp?level=1&ftdb=STOKST",
    ]
    _CDX_DISCOVERY_URL = (
        "https://web.archive.org/cdx/search/cdx"
        "?url=www.oscn.net/applications/oscn/DeliverDocument.asp*"
        "&output=json&filter=statuscode:200&limit=350"
    )
    _ANTI_BOT_RE = re.compile(
        r"why am i seeing this\?|verify (?:you are|you're) human|automated traffic|cloudflare",
        re.IGNORECASE,
    )
    _CASELAW_RE = re.compile(
        r"court of (?:criminal|civil) appeals cases|oklahoma (?:supreme|court of criminal appeals|court of civil appeals)|case number:\s*[A-Z0-9\-]+|v\.\s+state",
        re.IGNORECASE,
    )
    _NON_STATUTE_RE = re.compile(
        r"oklahoma attorney general'?s opinions|oklahoma jury instructions|uniform jury instructions|ag\s+\d{2,4}\s*[- ]\s*\d+|question submitted by:|previous case\s+top of index\s+this point in index",
        re.IGNORECASE,
    )

    @staticmethod
    def _normalize_wayback_url(url: str) -> str:
        value = str(url or "").strip()
        if value.startswith("https://web.archive.org/"):
            return "http://" + value[len("https://"):]
        return value
    
    def get_base_url(self) -> str:
        """Return the base URL for Oklahoma's legislative website."""
        return "http://www.oklegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Oklahoma."""
        return [{
            "name": "Oklahoma Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Oklahoma's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        best_archival: List[NormalizedStatute] = []
        for attempt in range(3):
            archival = await self._scrape_oscn_documents(code_name=code_name, max_statutes=30)
            if len(archival) > len(best_archival):
                best_archival = archival
            if best_archival:
                self.logger.info(
                    "Oklahoma OSCN archival fallback: scraped %s sections on attempt %s",
                    len(best_archival),
                    attempt + 1,
                )
                return best_archival
            await asyncio.sleep(0.4 * (attempt + 1))

        # If OSCN blocks automated access, use a broader fallback index to avoid zero-state output.
        fallback_urls = [
            code_url,
            "https://law.justia.com/codes/oklahoma/",
        ]
        best: List[NormalizedStatute] = []
        for candidate in fallback_urls:
            try:
                statutes = await self._generic_scrape(code_name, candidate, "Okla. Stat.")
            except Exception:
                statutes = []
            if len(statutes) > len(best):
                best = statutes

        return best

    async def _scrape_oscn_documents(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen: Set[str] = set()

        candidate_urls = await self._collect_candidate_document_urls(headers=headers)
        for link in candidate_urls:
            if len(statutes) >= max_statutes:
                break
            dedupe_key = str(link or "").strip().lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            statute = await self._build_statute_from_document_url(code_name=code_name, document_url=link, headers=headers)
            if statute is None:
                continue
            statutes.append(statute)

        return statutes

    async def _collect_candidate_document_urls(self, headers: Dict[str, str]) -> List[str]:
        candidates: List[str] = []
        seen: Set[str] = set()

        def _add(url_value: str) -> None:
            normalized = str(url_value or "").strip()
            if not normalized:
                return
            if "deliverdocument.asp?citeid=" not in normalized.lower():
                return
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(normalized)

        for seed_url in self._SEED_INDEX_URLS:
            _add(seed_url)
            html = await self._request_text(seed_url, headers=headers, timeout=45)
            if not html:
                for archived_link in await self._discover_links_from_archived_seed(seed_url=seed_url, headers=headers):
                    _add(archived_link)
                continue
            for live_link in self._extract_deliver_document_links(seed_url=seed_url, html=html):
                _add(live_link)

        # Archive-driven URL discovery helps when live index pages are sparse.
        for archive_url in self._discover_oscn_document_urls_via_cdx(headers=headers):
            _add(archive_url)

        return candidates

    def _extract_deliver_document_links(self, *, seed_url: str, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: List[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            full_url = urljoin(seed_url, href)
            if "deliverdocument.asp?citeid=" not in full_url.lower():
                continue
            links.append(full_url)
        return links

    async def _discover_links_from_archived_seed(self, *, seed_url: str, headers: Dict[str, str]) -> List[str]:
        seed_citeid = self._extract_cite_id(seed_url)
        if not seed_citeid:
            return []

        cdx_url = (
            "http://web.archive.org/cdx/search/cdx"
            "?url=www.oscn.net/applications/oscn/DeliverDocument.asp"
            f"?CiteID={seed_citeid}&output=json"
            "&fl=timestamp,original,statuscode&filter=statuscode:200&limit=8"
        )
        try:
            response = requests.get(cdx_url, headers=headers, timeout=30)
            response.raise_for_status()
            rows = json.loads(response.text)
        except Exception:
            return []

        if not isinstance(rows, list) or len(rows) <= 1:
            return []

        discovered: List[str] = []
        # Prefer latest captures first.
        for row in reversed(rows[1:]):
            if not isinstance(row, list) or len(row) < 2:
                continue
            ts = str(row[0] or "").strip()
            original = str(row[1] or "").strip()
            if not ts or not original:
                continue
            replay_url = self._normalize_wayback_url(f"http://web.archive.org/web/{ts}id_/{original}")
            html = await self._request_text(replay_url, headers=headers, timeout=35)
            if not html:
                continue
            for link in self._extract_deliver_document_links(seed_url=replay_url, html=html):
                discovered.append(link)
            if len(discovered) >= 120:
                break

        return discovered

    def _discover_oscn_document_urls_via_cdx(self, headers: Dict[str, str]) -> List[str]:
        try:
            response = requests.get(self._CDX_DISCOVERY_URL, headers=headers, timeout=35)
            response.raise_for_status()
            payload = json.loads(response.text)
        except Exception:
            return []

        urls: List[str] = []
        if not isinstance(payload, list) or len(payload) <= 1:
            return urls

        for row in payload[1:]:
            if not isinstance(row, list) or len(row) < 3:
                continue
            timestamp = str(row[1] or "").strip() if len(row) > 1 else ""
            original = str(row[2] or "").strip()
            if "deliverdocument.asp?citeid=" not in original.lower():
                continue
            if timestamp:
                replay = self._normalize_wayback_url(f"https://web.archive.org/web/{timestamp}id_/{original}")
                urls.append(replay)
            urls.append(original)
        return urls

    def _extract_document_body_text(self, soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        selectors = [
            "#oscn-content",
            "#content",
            "#body",
            "main",
            "article",
            "div.document",
            "div#doc",
        ]

        candidates: List[str] = []
        for selector in selectors:
            for node in soup.select(selector):
                text = self._normalize_legal_text(node.get_text(" ", strip=True))
                if len(text) >= 300:
                    candidates.append(text)

        if not candidates:
            body = soup.find("body")
            if body is not None:
                text = self._normalize_legal_text(body.get_text(" ", strip=True))
                if text:
                    candidates.append(text)

        if not candidates:
            return ""

        text = max(candidates, key=len)
        # Drop OSCN global navigation noise that often prefixes archived pages.
        text = re.sub(r"^\s*OSCN\s+navigation\s+.*?\bHelp\b\s*", "", text, flags=re.IGNORECASE)
        return self._normalize_legal_text(text)

    async def _build_statute_from_document_url(
        self,
        code_name: str,
        document_url: str,
        headers: Dict[str, str],
    ) -> NormalizedStatute | None:
        html = await self._request_text(document_url, headers=headers, timeout=45)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        text = self._extract_document_body_text(soup)
        if len(text) < 280:
            return None

        if self._ANTI_BOT_RE.search(text):
            return None

        if self._CASELAW_RE.search(text):
            return None

        if self._NON_STATUTE_RE.search(text):
            return None

        # Ignore obvious navigation/event pages that happen to be long.
        if self._looks_like_navigation_text(text) and not self._contains_statute_signals(text):
            return None

        section_number = self._extract_section_number(text) or self._extract_cite_id(document_url)
        if not section_number:
            section_number = "unknown"

        section_name_match = re.search(r"Section\s+[0-9A-Za-z.\-]+\s*-\s*([^\n\r]+)", text, flags=re.IGNORECASE)
        section_name = section_name_match.group(1).strip()[:180] if section_name_match else f"Section {section_number}"

        official_cite_match = re.search(r"\b\d+\s+O\.S\.\s*[0-9A-Za-z.\-]+\b", text)
        official_cite = official_cite_match.group(0) if official_cite_match else f"Okla. Stat. {section_number}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name,
            full_text=text[:14000],
            legal_area=self._identify_legal_area(text),
            source_url=document_url,
            official_cite=official_cite,
        )

    def _extract_cite_id(self, url: str) -> str:
        match = re.search(r"[?&]CiteID=(\d+)", str(url or ""), flags=re.IGNORECASE)
        return match.group(1) if match else ""

    def _request_text_direct(self, url: str, headers: Dict[str, str], timeout: int) -> str:
        request_url = self._normalize_wayback_url(url)
        for _ in range(3):
            try:
                response = requests.get(request_url, headers=headers, timeout=timeout)
                response.raise_for_status()
                text = response.text
                if self._ANTI_BOT_RE.search(str(text or "")):
                    return ""
                return text
            except Exception:
                time.sleep(0.6)
                continue
        return ""

    async def _request_text(self, url: str, headers: Dict[str, str], timeout: int) -> str:
        text = await asyncio.to_thread(self._request_text_direct, url, headers, timeout)
        if text:
            return text

        try:
            fetch_client = ArchivalFetchClient(request_timeout_seconds=max(20, int(timeout)))
            fetched = await fetch_client.fetch_with_fallback(url)
            content = bytes(getattr(fetched, "content", b"") or b"")
            if not content:
                return ""
            text = content.decode("utf-8", errors="replace")
            if self._ANTI_BOT_RE.search(str(text or "")):
                return ""
            return text
        except Exception:
            return ""


# Register this scraper with the registry
StateScraperRegistry.register("OK", OklahomaScraper)
