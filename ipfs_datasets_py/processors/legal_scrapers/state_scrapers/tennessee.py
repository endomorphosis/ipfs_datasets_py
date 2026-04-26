"""Scraper for Tennessee state laws."""

import asyncio
import re
import time
import warnings
from typing import Dict, List, Optional
from urllib.parse import urljoin

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

# Suppress SSL warnings for tn.gov
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


class TennesseeScraper(BaseStateScraper):
    """Scraper for Tennessee state laws."""

    _TN_JUSTIA_VERSION_RE = re.compile(r"/codes/tennessee/\d{4}/?$", re.IGNORECASE)
    _TN_JUSTIA_TITLE_RE = re.compile(r"/codes/tennessee/(?:\d{4}/)?title-\d+/?$", re.IGNORECASE)
    _TN_JUSTIA_INTERMEDIATE_RE = re.compile(
        r"/codes/tennessee/(?:\d{4}/)?title-\d+/(?!.*section-)[^?#]+/?$",
        re.IGNORECASE,
    )
    _TN_JUSTIA_SECTION_RE = re.compile(
        r"/codes/tennessee/(?:\d{4}/)?title-\d+/.*/section-[^/]+/?$",
        re.IGNORECASE,
    )
    _TN_SECTION_NUMBER_RE = re.compile(r"/section-([^/]+)/?$", re.IGNORECASE)
    _TN_CLOUDFLARE_CHALLENGE_RE = re.compile(
        r"(cf-mitigated|challenge-platform|enable javascript and cookies|just a moment)",
        re.IGNORECASE,
    )

    def get_base_url(self) -> str:
        """Return the base URL for Tennessee's legislative website."""
        return "https://www.tn.gov/tga"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Tennessee."""
        return [
            {
                "name": "Tennessee Code Annotated",
                "url": "https://law.justia.com/codes/tennessee/2024/",
                "type": "Code",
            }
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Tennessee statutes from the public Justia code tree."""
        limit = self._effective_scrape_limit(max_statutes, default=160)
        justia_statutes = await self._scrape_justia_code_tree(code_name=code_name, max_statutes=limit)
        if limit is None and justia_statutes:
            return justia_statutes
        if (limit is not None and len(justia_statutes) >= limit) or max_statutes:
            return justia_statutes[:limit] if limit is not None else justia_statutes

        direct = await self._scrape_direct_seed_sections(code_name, max_statutes=max(1, limit or 1))
        merged = list(justia_statutes)
        seen = {
            str(statute.statute_id or statute.source_url or "").strip().lower()
            for statute in merged
            if str(statute.statute_id or statute.source_url or "").strip()
        }
        for statute in direct:
            key = str(statute.statute_id or statute.source_url or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(statute)

        return merged[:limit] if limit is not None else merged

    async def _scrape_justia_code_tree(
        self,
        *,
        code_name: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = "https://law.justia.com/codes/tennessee/"
        payload = await self._fetch_justia_listing_html(index_url, timeout_seconds=30)
        if not payload:
            payload = await self._fetch_justia_listing_html(
                "https://law.justia.com/codes/tennessee/2024/",
                timeout_seconds=30,
            )
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        candidate_indexes = ["https://law.justia.com/codes/tennessee/2024/"]
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not self._TN_JUSTIA_VERSION_RE.search(href):
                continue
            if href not in candidate_indexes:
                candidate_indexes.append(href)

        title_urls: List[str] = []
        seen_titles = set()
        title_limit = None if max_statutes is None else max(1, int(max_statutes))
        for title_index_url in candidate_indexes:
            title_payload = await self._fetch_justia_listing_html(title_index_url, timeout_seconds=30)
            if not title_payload:
                continue
            title_soup = BeautifulSoup(title_payload, "html.parser")
            for anchor in title_soup.find_all("a", href=True):
                href = urljoin(title_index_url, str(anchor.get("href") or "").strip())
                if not self._TN_JUSTIA_TITLE_RE.search(href):
                    continue
                canonical = self._canonicalize_tn_justia_url(href)
                if canonical in seen_titles:
                    continue
                seen_titles.add(canonical)
                title_urls.append(canonical)
                if title_limit is not None and len(title_urls) >= title_limit:
                    break
            if title_urls:
                break

        self.logger.info("Tennessee Justia: discovered_titles=%d", len(title_urls))
        if not title_urls:
            return []

        section_url_limit = None if max_statutes is None else max(24, int(max_statutes) * 5)
        intermediate_limit = None if max_statutes is None else max(16, int(max_statutes) * 3)
        section_urls: List[str] = []
        intermediate_urls: List[str] = []
        seen_sections = set()
        seen_intermediate = set()
        heartbeat_seconds = max(15.0, float(self._env_int("STATE_SCRAPER_HEARTBEAT_SECONDS", default=60)))
        last_heartbeat = time.monotonic()

        for title_url in title_urls:
            title_payload = await self._fetch_justia_listing_html(title_url, timeout_seconds=30)
            if not title_payload:
                continue
            title_soup = BeautifulSoup(title_payload, "html.parser")
            for anchor in title_soup.find_all("a", href=True):
                href = urljoin(title_url, str(anchor.get("href") or "").strip())
                canonical = self._canonicalize_tn_justia_url(href)
                if self._TN_JUSTIA_SECTION_RE.search(canonical):
                    if canonical not in seen_sections:
                        seen_sections.add(canonical)
                        section_urls.append(canonical)
                elif self._TN_JUSTIA_INTERMEDIATE_RE.search(canonical) and canonical != title_url:
                    if canonical not in seen_intermediate:
                        seen_intermediate.add(canonical)
                        intermediate_urls.append(canonical)
                if section_url_limit is not None and len(section_urls) >= section_url_limit:
                    break
                if intermediate_limit is not None and len(intermediate_urls) >= intermediate_limit:
                    break
            if section_url_limit is not None and len(section_urls) >= section_url_limit:
                break
            if intermediate_limit is not None and len(intermediate_urls) >= intermediate_limit:
                break

        self.logger.info(
            "Tennessee Justia: discovered_direct_sections=%d intermediate_pages=%d",
            len(section_urls),
            len(intermediate_urls),
        )

        pages_to_scan = intermediate_urls if intermediate_limit is None else intermediate_urls[:intermediate_limit]
        for idx, page_url in enumerate(pages_to_scan, start=1):
            page_payload = await self._fetch_justia_listing_html(page_url, timeout_seconds=30)
            if not page_payload:
                continue
            page_soup = BeautifulSoup(page_payload, "html.parser")
            for anchor in page_soup.find_all("a", href=True):
                href = urljoin(page_url, str(anchor.get("href") or "").strip())
                canonical = self._canonicalize_tn_justia_url(href)
                if not self._TN_JUSTIA_SECTION_RE.search(canonical):
                    continue
                if canonical in seen_sections:
                    continue
                seen_sections.add(canonical)
                section_urls.append(canonical)
                if section_url_limit is not None and len(section_urls) >= section_url_limit:
                    break
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                self.logger.info(
                    "Tennessee Justia: scanned_intermediate=%d/%d section_urls=%d",
                    idx,
                    len(pages_to_scan),
                    len(section_urls),
                )
                last_heartbeat = now
            if section_url_limit is not None and len(section_urls) >= section_url_limit:
                break

        self.logger.info("Tennessee Justia: total_section_urls=%d", len(section_urls))
        if not section_urls:
            return []

        sem = asyncio.Semaphore(4)

        async def _fetch_one(section_url: str, index: int) -> NormalizedStatute | None:
            async with sem:
                return await self._build_justia_statute(
                    code_name=code_name,
                    section_url=section_url,
                    fallback_number=str(index),
                )

        out: List[NormalizedStatute] = []
        urls_to_fetch = section_urls if max_statutes is None else section_urls[: max(24, int(max_statutes) * 4)]
        batch_size = 24
        last_heartbeat = time.monotonic()
        for offset in range(0, len(urls_to_fetch), batch_size):
            batch = urls_to_fetch[offset : offset + batch_size]
            jobs = [_fetch_one(section_url, offset + idx) for idx, section_url in enumerate(batch, start=1)]
            for result in await asyncio.gather(*jobs, return_exceptions=True):
                if isinstance(result, Exception) or result is None:
                    continue
                out.append(result)
                if max_statutes is not None and len(out) >= max_statutes:
                    return out[:max_statutes]
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                self.logger.info(
                    "Tennessee Justia: fetched_sections=%d/%d statutes=%d",
                    min(offset + len(batch), len(urls_to_fetch)),
                    len(urls_to_fetch),
                    len(out),
                )
                last_heartbeat = now

        return out[:max_statutes] if max_statutes is not None else out

    async def _custom_scrape_tennessee(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 280,
    ) -> List[NormalizedStatute]:
        """Compatibility fallback used by older tests and recovery paths."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(code_url, timeout_seconds=45)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        statutes: List[NormalizedStatute] = []
        seen = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            label = self._normalize_legal_text(anchor.get_text(" ", strip=True))
            if not href or not label:
                continue
            full_url = urljoin(code_url, href)
            section_number = self._extract_section_number(label)
            if not section_number:
                section_number = f"TN-{len(statutes) + 1}"
            key = f"{section_number}|{full_url}".lower()
            if key in seen:
                continue
            seen.add(key)
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=label[:200],
                    full_text=f"Section {section_number}: {label}",
                    legal_area=self._identify_legal_area(label),
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "tennessee_compatibility_link_listing",
                        "discovery_method": "archival_link_listing",
                    },
                )
            )
            if len(statutes) >= max_sections:
                break
        return statutes

    async def _fetch_justia_listing_html(self, url: str, timeout_seconds: int = 30) -> bytes:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached

        timeout = max(5, int(timeout_seconds or 30))
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            self._record_fetch_event(provider="playwright_tn_justia", success=False, error=f"playwright_unavailable: {exc}")
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
                    await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
                    content = await page.content()
                finally:
                    await browser.close()
        except Exception as exc:
            self._record_fetch_event(provider="playwright_tn_justia", success=False, error=str(exc))
            return b""

        payload = content.encode("utf-8", errors="ignore")
        sample = payload[:12000].decode("utf-8", errors="ignore")
        if self._TN_CLOUDFLARE_CHALLENGE_RE.search(sample):
            self._record_fetch_event(provider="playwright_tn_justia", success=False, error="cloudflare_challenge")
            return b""

        self._record_fetch_event(provider="playwright_tn_justia", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(url=url, payload=payload, provider="playwright_tn_justia")
        return payload

    async def _fetch_justia_section_markdown(self, url: str, timeout_seconds: int = 25) -> str:
        reader_url = f"https://r.jina.ai/http://{url}"
        cached = await self._load_page_bytes_from_any_cache(reader_url)
        if cached:
            try:
                return cached.decode("utf-8", errors="replace")
            except Exception:
                return ""

        timeout = max(5, int(timeout_seconds or 25))

        def _request() -> str:
            try:
                import requests

                response = requests.get(
                    reader_url,
                    headers={
                        "User-Agent": "ipfs-datasets-tennessee-code-scraper/2.0",
                        "Accept": "text/plain,text/markdown;q=0.9,*/*;q=0.8",
                    },
                    timeout=timeout,
                )
                if int(response.status_code or 0) != 200:
                    return ""
                return str(response.text or "")
            except Exception:
                return ""

        try:
            text = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 1)
        except asyncio.TimeoutError:
            text = ""

        self._record_fetch_event(provider="requests_direct_rjina", success=bool(text))
        if text:
            await self._cache_successful_page_fetch(
                url=reader_url,
                payload=text.encode("utf-8", errors="ignore"),
                provider="requests_direct_rjina",
            )
        return text

    async def _build_justia_statute(
        self,
        *,
        code_name: str,
        section_url: str,
        fallback_number: str,
    ) -> NormalizedStatute | None:
        markdown = await self._fetch_justia_section_markdown(section_url, timeout_seconds=25)
        if not markdown:
            return None

        match = self._TN_SECTION_NUMBER_RE.search(section_url)
        section_number = match.group(1) if match else fallback_number
        section_name = self._extract_justia_section_name(markdown, section_number)
        body = self._extract_justia_reader_section(markdown, section_number)
        if len(body) < 220:
            return None

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=section_number.split("-", 1)[0],
            section_number=section_number,
            section_name=section_name[:200],
            full_text=body[:14000],
            legal_area=self._identify_legal_area(body[:1200]),
            source_url=section_url,
            official_cite=f"Tenn. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "jina_reader_justia_tennessee_code",
                "discovery_method": "justia_tennessee_code_tree",
                "reader_url": f"https://r.jina.ai/http://{section_url}",
                "skip_hydrate": True,
            },
        )

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 1,
    ) -> List[NormalizedStatute]:
        seeds = [
            (
                "39-13-202",
                "First degree murder",
                "https://law.justia.com/codes/tennessee/title-39/chapter-13/part-2/section-39-13-202/",
            ),
        ]
        out: List[NormalizedStatute] = []
        for section_number, section_name, source_url in seeds[: max(1, int(max_statutes or 1))]:
            markdown = await self._fetch_justia_section_markdown(source_url, timeout_seconds=25)
            if not markdown:
                continue
            body = self._extract_justia_reader_section(markdown, section_number)
            if len(body) < 220:
                continue
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name,
                    full_text=body[:14000],
                    legal_area=self._identify_legal_area(body[:1200]),
                    source_url=source_url,
                    official_cite=f"Tenn. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "jina_reader_justia_tennessee_code",
                        "discovery_method": "cloudflare_block_recovery_seed_section",
                        "reader_url": f"https://r.jina.ai/http://{source_url}",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def _canonicalize_tn_justia_url(self, url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return value
        value = re.sub(r"/codes/tennessee/\d{4}/", "/codes/tennessee/", value, flags=re.IGNORECASE)
        if value.endswith("/") and "section-" not in value:
            return value
        return value.rstrip("/") + "/"

    def _extract_justia_section_name(self, markdown: str, section_number: str) -> str:
        text = str(markdown or "")
        patterns = [
            rf"#\s*Tennessee Code §\s*{re.escape(section_number)}\s*\(\d{{4}}\)\s*-\s*(.+?)\s*::",
            rf"Section\s+{re.escape(section_number)}\s*-\s*(.+)",
            rf"TN Code §\s*{re.escape(section_number)}\s*\(\d{{4}}\)\s*-\s*(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return self._normalize_legal_text(match.group(1))[:200]
        return f"Section {section_number}"

    def _extract_justia_reader_section(self, markdown: str, section_number: str) -> str:
        text = str(markdown or "")
        start = text.find(f"Section {section_number}")
        cite_start = text.find(f"TN Code § {section_number}")
        if cite_start >= 0:
            start = cite_start
        if start < 0:
            start = text.find(f"§ {section_number}")
        if start < 0:
            return ""
        tail = text[start:]
        end_markers = ["Disclaimer:", "Justia Free Databases", "Newsletter", "Want to receive"]
        end = len(tail)
        for marker in end_markers:
            idx = tail.find(marker)
            if idx >= 0:
                end = min(end, idx)
        body = tail[:end]
        body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
        body = re.sub(r"\*\*([^*]+)\*\*", r"\1", body)
        return self._normalize_legal_text(body)


StateScraperRegistry.register("TN", TennesseeScraper)
