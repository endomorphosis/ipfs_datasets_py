"""Scraper for Arkansas state laws.

This module contains the scraper for Arkansas statutes from the official state legislative website.
"""

import asyncio
import hashlib
import json
import re
import ssl
import time
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class ArkansasScraper(BaseStateScraper):
    """Scraper for Arkansas state laws from https://www.arkleg.state.ar.us"""

    OFFICIAL_CODE_INDEX = "https://www.arkleg.state.ar.us/ArkansasCode/"
    OFFICIAL_DOMAIN = "www.arkleg.state.ar.us"
    OFFICIAL_ENTRY_PATH = "/ArkansasCode/"
    OFFICIAL_ENTRY_URL = "https://www.arkleg.state.ar.us/ArkansasCode/"
    BUCKET_SEED_QUARANTINE_REASON = "bucket_seed_pending_official_replacement"
    _AR_TITLE_QUERY_RE = re.compile(r"[?&](?:title|codeTitle)=(\d{1,2})\b", re.IGNORECASE)
    _AR_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(\d{1,2})\b", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Agriculture"),
        ("3", "Alcoholic Beverages"),
        ("4", "Business and Commercial Law"),
        ("5", "Criminal Offenses"),
        ("6", "Education"),
        ("7", "Elections"),
        ("8", "Environmental Law"),
        ("9", "Family Law"),
        ("10", "General Assembly"),
        ("11", "Labor and Industrial Relations"),
        ("12", "Law Enforcement, Emergency Management, and Military Affairs"),
        ("13", "Libraries, Archives, and Cultural Resources"),
        ("14", "Local Government"),
        ("15", "Natural Resources and Economic Development"),
        ("16", "Practice, Procedure, and Courts"),
        ("17", "Professions, Occupations, and Businesses"),
        ("18", "Property"),
        ("19", "Public Finance"),
        ("20", "Public Health and Welfare"),
        ("21", "Public Officers and Employees"),
        ("22", "Public Property"),
        ("23", "Public Utilities and Regulated Industries"),
        ("24", "Retirement and Pensions"),
        ("25", "State Government"),
        ("26", "Taxation"),
        ("27", "Transportation"),
        ("28", "Wills, Estates, and Fiduciary Relationships"),
    )
    DEFAULT_BUCKET_SEED_ROWS = (
        {
            "canonical_key": "ar:bucket-title-1",
            "label": "Arkansas Code Title 1 General Provisions",
            "source_url": "https://law.justia.com/codes/arkansas/title-1/",
            "title_number": "1",
        },
        {
            "canonical_key": "ar:bucket-seed-untitled",
            "label": "open-us-law-bucket Arkansas seed row without an official host",
            "source_url": "",
        },
        {
            "canonical_key": "ar:bucket-seed-phantom",
            "label": "Arkansas Code phantom bucket seed without a recoverable title",
            "source_url": "https://law.justia.com/codes/arkansas/",
        },
    )

    _AR_JUSTIA_TITLE_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/?$", re.IGNORECASE)
    _AR_JUSTIA_VERSION_RE = re.compile(r"/codes/arkansas/\d{4}/?$", re.IGNORECASE)
    _AR_JUSTIA_INTERMEDIATE_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/(?!.*section-)[^?#]+/?$", re.IGNORECASE)
    _AR_JUSTIA_SECTION_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/.*/section-[^/]+/?$", re.IGNORECASE)
    _AR_SECTION_NUMBER_RE = re.compile(r"/section-([^/]+)/?$", re.IGNORECASE)
    _AR_OFFICIAL_SECTION_HREF_RE = re.compile(
        r"/ArkansasCode/(?P<section>\d+-\d+(?:-\d+)?(?:\.\d+)?)/?$",
        re.IGNORECASE,
    )
    _AR_OFFICIAL_SECTION_QUERY_RE = re.compile(
        r"[?&](?:section|sec|codeSection)=(?P<section>\d+-\d+(?:-\d+)?(?:\.\d+)?)",
        re.IGNORECASE,
    )
    _AR_SECTION_HEAD_RE = re.compile(
        r"^\s*(?:§\s*)?(?P<section>\d+-\d+(?:-\d+)?(?:\.\d+)?)\s*[.–—-]\s*(?P<title>.+)$",
        re.IGNORECASE,
    )
    _AR_CLOUDFLARE_CHALLENGE_RE = re.compile(
        r"(cf-mitigated|challenge-platform|enable javascript and cookies|just a moment)",
        re.IGNORECASE,
    )

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

    def _looks_like_challenge_page(self, payload: bytes) -> bool:
        if not payload:
            return False
        sample = payload[:12000].decode("utf-8", errors="ignore")
        return bool(self._AR_CLOUDFLARE_CHALLENGE_RE.search(sample))

    async def _fetch_direct_html(self, url: str, timeout_seconds: int = 8) -> bytes:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached
        timeout = max(1, int(timeout_seconds or 8))

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-arkansas-code-scraper/2.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                    timeout=timeout,
                )
                if int(response.status_code or 0) != 200:
                    return b""
                return bytes(response.content or b"")
            except Exception:
                return b""

        try:
            payload = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 1)
        except asyncio.TimeoutError:
            payload = b""
        if self._looks_like_challenge_page(payload):
            self._record_fetch_event(provider="requests_direct", success=False, error="cloudflare_challenge")
            return b""
        self._record_fetch_event(provider="requests_direct", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(url=url, payload=payload, provider="requests_direct")
        return payload

    async def _fetch_justia_html(self, url: str, timeout_seconds: int = 18) -> bytes:
        payload = await self._fetch_direct_html(url, timeout_seconds=min(8, max(1, int(timeout_seconds or 18))))
        if payload:
            return payload

        timeout = max(5, int(timeout_seconds or 18))
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            self._record_fetch_event(provider="playwright_justia", success=False, error=f"playwright_unavailable: {exc}")
            return b""

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(
                        user_agent=(
                            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "Chrome/122.0.0.0 Safari/537.36"
                        )
                    )
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                    content = await page.content()
                finally:
                    await browser.close()
        except Exception as exc:
            self._record_fetch_event(provider="playwright_justia", success=False, error=str(exc))
            return b""

        payload = content.encode("utf-8", errors="ignore")
        if self._looks_like_challenge_page(payload):
            self._record_fetch_event(provider="playwright_justia", success=False, error="cloudflare_challenge")
            return b""
        self._record_fetch_event(provider="playwright_justia", success=bool(payload))
        return payload
    
    def get_base_url(self) -> str:
        """Return the base URL for Arkansas's legislative website."""
        return "https://www.arkleg.state.ar.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Arkansas."""
        return [{
            "name": "Arkansas Code",
            "url": self.OFFICIAL_CODE_INDEX,
            "type": "Code"
        }]

    def _official_section_number_from_url(self, url: str) -> str:
        text = str(url or "").strip()
        match = self._AR_OFFICIAL_SECTION_HREF_RE.search(text)
        if match:
            return match.group("section")
        match = self._AR_OFFICIAL_SECTION_QUERY_RE.search(text)
        if match:
            return match.group("section")
        return ""

    async def _discover_official_section_links(
        self, index_url: str
    ) -> List[Tuple[str, str, str]]:
        """Discover official Arkansas Code section links from an index page."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_direct_html(index_url)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            section_number = self._official_section_number_from_url(href)
            if not section_number:
                continue
            if href in seen:
                continue
            seen.add(href)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((href, section_number, label))
        return out

    async def _build_official_statute(
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

        payload = await self._fetch_direct_html(section_url)
        if not payload:
            return None
        html = payload.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        content_node = (
            soup.select_one("div#content")
            or soup.select_one("div.content")
            or soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one("body")
        )
        if content_node is None:
            return None
        full_text = self._normalize_legal_text(content_node.get_text(" ", strip=True))
        if len(full_text) < 120:
            return None

        heading = ""
        heading_node = (
            content_node.find(["h1", "h2", "h3"])
            if hasattr(content_node, "find")
            else None
        )
        if heading_node is not None:
            heading = self._normalize_legal_text(heading_node.get_text(" ", strip=True))
        if not heading:
            first_p = content_node.find("p") if hasattr(content_node, "find") else None
            if first_p is not None:
                heading = self._normalize_legal_text(first_p.get_text(" ", strip=True))
        match = self._AR_SECTION_HEAD_RE.match(heading)
        if match:
            section_number = match.group("section")
            section_title = match.group("title").strip()
        title = (section_title or heading or section_number)[:200]
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"AR-{section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=title,
            short_title=title,
            full_text=full_text[:14000],
            legal_area=self._identify_legal_area(title),
            source_url=section_url,
            official_cite=f"Ark. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_arkansas_code_html",
                "discovery_method": "official_arkansas_code_index",
                "skip_hydrate": True,
            },
        )

    async def _scrape_official_arkansas_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Scrape Arkansas Code from official arkleg.state.ar.us HTML."""
        index_candidates = []
        for candidate in (
            code_url,
            self.OFFICIAL_CODE_INDEX,
            f"{self.get_base_url()}/ArkansasCode/",
            f"{self.get_base_url()}/",
        ):
            value = str(candidate or "").strip()
            if value and value not in index_candidates:
                index_candidates.append(value)

        section_links: List[Tuple[str, str, str]] = []
        seen_urls: set[str] = set()
        for index_url in index_candidates:
            for section_url, section_number, label in await self._discover_official_section_links(
                index_url
            ):
                if section_url in seen_urls:
                    continue
                seen_urls.add(section_url)
                section_links.append((section_url, section_number, label))
            if section_links:
                break

        statutes: List[NormalizedStatute] = []
        for section_url, section_number, label in section_links:
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            statute = await self._build_official_statute(
                code_name=code_name,
                section_url=section_url,
                section_number=section_number,
                section_title=label,
            )
            if statute is not None:
                statutes.append(statute)
        return statutes[:max_statutes] if max_statutes is not None else statutes
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Arkansas's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=180)
        official = await self._scrape_official_arkansas_code(
            code_name, code_url or self.OFFICIAL_CODE_INDEX, max_statutes=limit
        )
        official = self._filter_non_code_results(official)
        if official and (limit is None or len(official) >= limit):
            return official[:limit] if limit is not None else official

        # Full-corpus mode must not sole-admit secondary Justia mirrors.
        if limit is None and self._full_corpus_enabled():
            if official:
                return official
            self.logger.warning(
                "Arkansas full-corpus: official arkleg path empty; refusing Justia sole admission"
            )
            return []

        justia_statutes = await self._scrape_justia_titles(code_name, max_statutes=limit)
        justia_statutes = self._filter_non_code_results(justia_statutes)
        if limit is not None and len(justia_statutes) >= limit:
            return justia_statutes[:limit]

        candidate_urls = [
            code_url,
            "https://www.arkleg.state.ar.us/",
            "https://www.arkleg.state.ar.us/ArkansasCode/",
            "https://web.archive.org/web/20240101000000/https://www.arkleg.state.ar.us/ArkansasCode/",
            "https://law.justia.com/codes/arkansas/",
            "https://web.archive.org/web/20231201000000/https://law.justia.com/codes/arkansas/",
        ]

        seen = set()
        merged: List[NormalizedStatute] = list(official) + list(justia_statutes)
        merged_keys = set()
        for statute in merged:
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

            statutes = await self._generic_scrape(
                code_name, candidate, "Ark. Code Ann.", max_sections=limit or 1000000
            )
            statutes = self._filter_non_code_results(statutes)
            _merge(statutes)
            if limit is not None and len(merged) >= limit:
                return merged[:limit]

        return merged[:limit] if limit is not None else merged

    async def _scrape_justia_titles(self, code_name: str, max_statutes: Optional[int]) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = "https://law.justia.com/codes/arkansas/"
        try:
            payload = await self._fetch_justia_html(index_url, timeout_seconds=18)
        except Exception:
            return []
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        candidate_title_indexes = [index_url]
        seen_title_indexes = {index_url}
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not self._AR_JUSTIA_VERSION_RE.search(href):
                continue
            if href in seen_title_indexes:
                continue
            seen_title_indexes.add(href)
            candidate_title_indexes.append(href)
            break

        title_limit = max_statutes if max_statutes is not None else None
        section_limit = max_statutes if max_statutes is not None else None
        title_urls: List[str] = []
        seen_titles = set()
        for title_index_url in candidate_title_indexes:
            if title_index_url == index_url:
                title_soup = soup
            else:
                title_index_payload = await self._fetch_justia_html(title_index_url, timeout_seconds=18)
                if not title_index_payload:
                    continue
                title_soup = BeautifulSoup(title_index_payload, "html.parser")

            for anchor in title_soup.find_all("a", href=True):
                href = urljoin(title_index_url, str(anchor.get("href") or "").strip())
                if not self._AR_JUSTIA_TITLE_RE.search(href):
                    continue
                if href in seen_titles:
                    continue
                seen_titles.add(href)
                title_urls.append(href)
                if title_limit is not None and len(title_urls) >= title_limit:
                    break
            if title_urls:
                break
        self.logger.info("Arkansas Justia: discovered %d title indexes", len(title_urls))

        section_urls: List[str] = []
        intermediate_urls: List[str] = []
        seen_intermediate = set()
        seen_sections = set()
        for title_url in title_urls:
            try:
                title_payload = await self._fetch_justia_html(title_url, timeout_seconds=18)
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
                if section_limit is not None and len(section_urls) >= max(1, int(section_limit * 4)):
                    break
            if section_limit is not None and len(intermediate_urls) >= max(1, int(section_limit * 2)):
                break
            if section_limit is not None and len(section_urls) >= max(1, int(section_limit * 4)):
                break

        intermediate_scan = intermediate_urls[: max(1, int(section_limit * 2))] if section_limit is not None else intermediate_urls
        self.logger.info(
            "Arkansas Justia: discovered %d direct section urls and %d intermediate urls",
            len(section_urls),
            len(intermediate_urls),
        )
        heartbeat_seconds = max(15.0, float(self._env_int("STATE_SCRAPER_HEARTBEAT_SECONDS", default=60)))
        last_heartbeat = time.monotonic()
        for idx, page_url in enumerate(intermediate_scan, start=1):
            try:
                page_payload = await self._fetch_justia_html(page_url, timeout_seconds=18)
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
                if section_limit is not None and len(section_urls) >= max(1, int(section_limit * 4)):
                    break
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                self.logger.info(
                    "Arkansas Justia: scanned_intermediate=%d/%d section_urls=%d",
                    idx,
                    len(intermediate_scan),
                    len(section_urls),
                )
                last_heartbeat = now
            if section_limit is not None and len(section_urls) >= max(1, int(section_limit * 4)):
                break
        self.logger.info("Arkansas Justia: total section urls queued=%d", len(section_urls))

        sem = asyncio.Semaphore(2)

        async def _fetch_one(section_url: str, index: int) -> NormalizedStatute | None:
            async with sem:
                return await self._build_justia_statute(code_name=code_name, section_url=section_url, fallback_number=str(index))

        statutes: List[NormalizedStatute] = []
        urls_to_fetch = section_urls[: max(1, int(section_limit * 4))] if section_limit is not None else section_urls
        batch_size = 24
        last_heartbeat = time.monotonic()
        for offset in range(0, len(urls_to_fetch), batch_size):
            batch = urls_to_fetch[offset : offset + batch_size]
            jobs = [_fetch_one(section_url, offset + idx) for idx, section_url in enumerate(batch, start=1)]
            for result in await asyncio.gather(*jobs, return_exceptions=True):
                if isinstance(result, Exception) or result is None:
                    continue
                statutes.append(result)
                if max_statutes is not None and len(statutes) >= max_statutes:
                    return statutes
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                self.logger.info(
                    "Arkansas Justia: fetched_sections=%d/%d statutes=%d",
                    min(offset + len(batch), len(urls_to_fetch)),
                    len(urls_to_fetch),
                    len(statutes),
                )
                last_heartbeat = now

        return statutes

    async def _build_justia_statute(self, *, code_name: str, section_url: str, fallback_number: str) -> NormalizedStatute | None:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        try:
            payload = await self._fetch_justia_html(section_url, timeout_seconds=18)
        except Exception:
            return None
        if not payload:
            return None

        html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        soup = BeautifulSoup(html, "html.parser")
        content_node = (
            soup.select_one("div.wrapper")
            or soup.select_one(".primary-content")
            or soup.select_one("#main-content")
            or soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one("body")
        )
        if content_node is None:
            return None

        full_text = self._extract_best_content_text(str(content_node))
        full_text = re.split(r"\bDisclaimer\s*:", full_text, maxsplit=1)[0].strip()
        full_text = re.split(r"\bAsk a Lawyer\b", full_text, maxsplit=1)[0].strip()
        full_text = re.sub(
            r"^Go to Previous Versions\b.*?\bUniversal Citation:\s*AR Code\s*§\s*[^.]+?"
            r"\s*Learn more\s*This media-neutral citation.*?official citation\.\s*(?:Previous\s+)?Next\s*",
            "",
            full_text,
            flags=re.IGNORECASE,
        )
        full_text = re.sub(r"\s*(?:Previous\s+)?Next\s*$", "", full_text, flags=re.IGNORECASE)
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
            structured_data={
                "source_kind": "secondary_justia_arkansas_html",
                "discovery_method": "justia_title_section_crawl",
                "skip_hydrate": True,
            },
        )

    def official_title_url(self, title_number: object) -> str:
        return f"{self.OFFICIAL_CODE_INDEX}?title={title_number}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Arkansas Code title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"ar:title-{number}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Arkansas Code Title {number} ({name}) official arkleg "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def is_official_arkleg_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == "arkleg.state.ar.us" or host.endswith(".arkleg.state.ar.us")

    def _looks_like_bucket_seed_url(self, url: str) -> bool:
        text = str(url or "").strip().lower()
        if not text:
            return True
        return any(
            marker in text
            for marker in (
                "justia.com",
                "findlaw.com",
                "law.cornell.edu",
                "open-us-law-bucket",
                "huggingface.co",
                "unicourt",
            )
        )

    def _recover_title_number(self, *parts: object) -> str:
        blob = " ".join(str(item or "") for item in parts)
        query_match = self._AR_TITLE_QUERY_RE.search(blob)
        if query_match:
            return query_match.group(1).lstrip("0") or query_match.group(1)
        label_match = self._AR_TITLE_LABEL_RE.search(blob)
        if label_match:
            return label_match.group(1).lstrip("0") or label_match.group(1)
        official_section = self._official_section_number_from_url(blob)
        if official_section:
            return official_section.split("-", 1)[0].lstrip("0") or official_section.split("-", 1)[0]
        return ""

    def classify_bucket_seed_rows(
        self,
        seeds: object,
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Admit official arkleg replacements or keep bucket seed rows quarantined.

        Recoverable title numbers are rewritten to the official Arkansas Code
        title URL. Remaining Hugging Face bucket / secondary-mirror rows stay
        quarantined with ``bucket_seed_pending_official_replacement`` until an
        official replacement is proven.
        """

        repaired: List[Dict[str, Any]] = []
        quarantines: List[Dict[str, Any]] = []
        seen_titles: set[str] = set()
        seen_quarantine: set[str] = set()
        known = {number for number, _name in self.OFFICIAL_TITLES}

        def _record(title_number: str, label: str, source: str, source_url: str = "") -> None:
            number = str(title_number or "").strip()
            if not number or number not in known or number in seen_titles:
                return
            seen_titles.add(number)
            official_url = source_url if source_url and self.is_official_arkleg_url(source_url) else self.official_title_url(number)
            name = dict(self.OFFICIAL_TITLES).get(number, f"Title {number}")
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip() or name
            repaired.append(
                {
                    "canonical_key": f"ar:title-{number}",
                    "title_number": number,
                    "name": name,
                    "source_url": official_url,
                    "source_link_disposition": source,
                    "repair_source": source,
                    "text": (
                        f"Arkansas Code Title {number} ({name}) official arkleg "
                        f"catalog unit at {official_url}"
                    ),
                }
            )

        def _quarantine(label: str, evidence: str, unit_id: str = "") -> None:
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
            if not cleaned:
                return
            key = unit_id or (
                "ar:bucket-"
                + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            )
            if key in seen_quarantine:
                return
            seen_quarantine.add(key)
            quarantines.append(
                {
                    "unit_id": key,
                    "reason": self.BUCKET_SEED_QUARANTINE_REASON,
                    "label": cleaned[:240],
                    "page_url": page_url,
                    "evidence_sha256": hashlib.sha256(
                        str(evidence or cleaned).encode("utf-8")
                    ).hexdigest(),
                }
            )

        items: Sequence[Any]
        if isinstance(seeds, (bytes, bytearray, str)):
            html = seeds.decode("utf-8", errors="replace") if isinstance(seeds, (bytes, bytearray)) else seeds
            try:
                from bs4 import BeautifulSoup
            except ImportError as exc:
                raise RuntimeError(
                    "BeautifulSoup is required for official Arkansas discovery"
                ) from exc
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
                absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
                title_number = self._recover_title_number(absolute, href, label)
                if title_number and self.is_official_arkleg_url(absolute):
                    _record(title_number, label, "official", self.official_title_url(title_number))
                    continue
                if title_number and not self._looks_like_bucket_seed_url(absolute):
                    _record(title_number, label, "official_replacement")
                    continue
                if title_number:
                    _record(title_number, label, "official_replacement")
                    continue
                if label and self._looks_like_bucket_seed_url(absolute):
                    _quarantine(label, str(link))
            for node in soup.find_all(["span", "td", "li", "div"]):
                if node.find("a", href=True):
                    continue
                label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
                if not label:
                    continue
                title_number = self._recover_title_number(
                    node.get("data-title"),
                    node.get("id"),
                    label,
                    str(node),
                )
                if title_number:
                    _record(title_number, label, "official_replacement")
                    continue
                if re.search(r"\b(bucket seed|phantom|without a recoverable)\b", label, re.IGNORECASE):
                    _quarantine(label, str(node))
            return {"repaired": repaired, "quarantines": quarantines}

        items = seeds or ()
        for item in items:
            if not isinstance(item, Mapping):
                continue
            label = str(
                item.get("label")
                or item.get("name")
                or item.get("text")
                or item.get("section_name")
                or ""
            ).strip()
            source_url = str(item.get("source_url") or item.get("href") or "").strip()
            title_number = self._recover_title_number(
                item.get("title_number"),
                item.get("section_number"),
                source_url,
                label,
            )
            if title_number and source_url and self.is_official_arkleg_url(source_url):
                _record(title_number, label, "official", source_url)
                continue
            if title_number:
                _record(title_number, label, "official_replacement")
                continue
            _quarantine(
                label or source_url or "arkansas bucket seed",
                json.dumps(dict(item), sort_keys=True),
                unit_id=str(item.get("canonical_key") or ""),
            )
        return {"repaired": repaired, "quarantines": quarantines}

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-arkansas-official-catalog/1.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                )
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    if int(getattr(response, "status", 200) or 200) != 200:
                        return b""
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "ipfs-datasets-arkansas-official-catalog/1.0",
                            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                        },
                    )
                    context = ssl._create_unverified_context()
                    with urllib.request.urlopen(
                        request, timeout=timeout, context=context
                    ) as response:
                        return bytes(response.read() or b"")
                except Exception:
                    return b""

        return _request()

    def _parse_official_title_links(self, html: bytes, page_url: str = "") -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {number for number, _name in self.OFFICIAL_TITLES}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            if not self.is_official_arkleg_url(absolute):
                continue
            number = self._recover_title_number(
                absolute, href, link.get_text(" ", strip=True) or ""
            )
            if number not in known:
                continue
            if number not in found:
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate official Arkansas titles and quarantine leftover bucket seeds."""

        discovered = self._parse_official_title_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        classified = self.classify_bucket_seed_rows(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        seed_classified = self.classify_bucket_seed_rows(
            list(seed_rows) if seed_rows is not None else list(self.DEFAULT_BUCKET_SEED_ROWS),
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        classified["repaired"].extend(seed_classified["repaired"])
        classified["quarantines"].extend(seed_classified["quarantines"])
        self.last_official_quarantines = list(classified["quarantines"])

        rows = self.official_title_catalog()
        by_title = {str(row["title_number"]): row for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_arkleg"
        for unit in classified["repaired"]:
            number = str(unit.get("title_number") or "")
            if number in by_title:
                if unit.get("source_link_disposition") in {"official", "official_replacement"}:
                    by_title[number]["source_url"] = unit["source_url"]
                    if unit.get("source_link_disposition") == "official":
                        by_title[number]["source_link_disposition"] = "official"
                continue
        return rows

    def fetch_official(self, code: str = "AR"):
        """Acquire the exhaustive official Arkansas Code title catalog.

        Official arkleg titles are admitted. Hugging Face bucket seed rows
        remain quarantined unless an official title replacement is proven.
        This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "AR").strip().upper() or "AR"
        if normalized != "AR":
            raise ValueError(f"ArkansasScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        quarantines = list(getattr(self, "last_official_quarantines", []) or [])
        if len(rows) < 3:
            raise RuntimeError("arkansas official catalog enumeration is incomplete")
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "units": rows,
            "quarantines": quarantines,
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = html if html else (b"HTTP/1.1 200 OK\n\n" + body)
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows),
            "method": "pagination",
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(rows),
            "ar_bucket_seed_quarantines": quarantines,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code=normalized,
            request_bytes=request,
            response_bytes=response,
            body_bytes=body,
            source_domain=self.OFFICIAL_DOMAIN,
            source_path=self.OFFICIAL_ENTRY_PATH,
            frontier=frontier,
            rows=tuple(rows),
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=str(rows[0]["canonical_key"]),
            last_hierarchy_unit=str(rows[-1]["canonical_key"]),
        )


# Register this scraper with the registry
StateScraperRegistry.register("AR", ArkansasScraper)
