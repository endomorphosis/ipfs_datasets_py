"""Scraper for Arkansas state laws.

This module contains the scraper for Arkansas statutes from the official state legislative website.
"""

import asyncio
import re
import time
from typing import List, Dict, Optional
from urllib.parse import urljoin

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class ArkansasScraper(BaseStateScraper):
    """Scraper for Arkansas state laws from https://www.arkleg.state.ar.us"""

    _AR_JUSTIA_TITLE_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/?$", re.IGNORECASE)
    _AR_JUSTIA_VERSION_RE = re.compile(r"/codes/arkansas/\d{4}/?$", re.IGNORECASE)
    _AR_JUSTIA_INTERMEDIATE_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/(?!.*section-)[^?#]+/?$", re.IGNORECASE)
    _AR_JUSTIA_SECTION_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/.*/section-[^/]+/?$", re.IGNORECASE)
    _AR_SECTION_NUMBER_RE = re.compile(r"/section-([^/]+)/?$", re.IGNORECASE)
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
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
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
        justia_statutes = await self._scrape_justia_titles(code_name, max_statutes=limit)
        justia_statutes = self._filter_non_code_results(justia_statutes)
        if limit is None and justia_statutes:
            return justia_statutes
        if limit is not None and len(justia_statutes) >= limit:
            return justia_statutes[:limit] if limit is not None else justia_statutes

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

            statutes = await self._generic_scrape(code_name, candidate, "Ark. Code Ann.", max_sections=limit or 1000000)
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
        )


# Register this scraper with the registry
StateScraperRegistry.register("AR", ArkansasScraper)
