"""Scraper for Tennessee state laws."""

import asyncio
import os
import re
import time
import warnings
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

# Suppress SSL warnings for tn.gov
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


class TennesseeScraper(BaseStateScraper):
    """Scraper for Tennessee state laws from official TGA / capitol hosts."""

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
    _TN_OFFICIAL_HOST_SUFFIXES = (
        "tn.gov",
        "capitol.tn.gov",
    )
    _TN_OFFICIAL_SECTION_RE = re.compile(
        r"(?:/tca/|/statutes?/|/code/)[^?#]*section[/_-]?([0-9]+(?:-[0-9A-Za-z.]+)+)",
        re.IGNORECASE,
    )
    _TN_OFFICIAL_TITLE_RE = re.compile(
        r"(?:title[/_-]|/tca/)(\d{1,3})(?:[/?#]|$)",
        re.IGNORECASE,
    )
    _TN_SECTION_LABEL_RE = re.compile(
        r"(?:§|Section)\s*([0-9]+(?:-[0-9A-Za-z.]+)+)",
        re.IGNORECASE,
    )

    def get_base_url(self) -> str:
        """Return the base URL for Tennessee's legislative website."""
        return "https://www.capitol.tn.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Tennessee."""
        return [
            {
                "name": "Tennessee Code Annotated",
                "url": "https://www.tn.gov/tga/statutes.html",
                "type": "Code",
            }
        ]

    def _justia_fallback_allowed(self) -> bool:
        return str(
            os.getenv("STATE_SCRAPER_TN_ALLOW_JUSTIA_FALLBACK", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}

    def _is_justia_url(self, url: str) -> bool:
        return "justia.com" in str(url or "").lower()

    def _is_official_host(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return any(host == s or host.endswith("." + s) for s in self._TN_OFFICIAL_HOST_SUFFIXES)

    def _filter_official_only(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        """Drop secondary/Justia rows when full-corpus admission is sealed."""
        if not self._full_corpus_enabled() or self._justia_fallback_allowed():
            return statutes
        return [
            s
            for s in statutes
            if self._is_official_host(str(s.source_url or ""))
            and "justia" not in str((s.structured_data or {}).get("source_kind") or "").lower()
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Tennessee statutes preferring official TGA/capitol sources.

        Justia TCA mirrors are secondary and cannot authorize full-corpus
        admission unless ``STATE_SCRAPER_TN_ALLOW_JUSTIA_FALLBACK`` is set.
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        allow_justia = self._justia_fallback_allowed()
        # Bounded probes that explicitly target Justia keep that recovery path
        # offline-friendly; full-corpus always prefers official hosts first.
        prefer_official = (not self._is_justia_url(code_url)) or self._full_corpus_enabled()
        merged: List[NormalizedStatute] = []
        seen: Set[str] = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(statute)

        if prefer_official:
            # Official hierarchy first (catalog path: tn.gov / capitol.tn.gov).
            official = await self._scrape_official_tga_tree(
                code_name=code_name,
                code_url=code_url,
                max_statutes=limit,
            )
            _merge(self._filter_official_only(official))
            if limit is not None and len(merged) >= int(limit):
                return merged[: int(limit)]
            if limit is None and merged:
                return merged

            # Bounded probes may use official seed sections.
            if not self._full_corpus_enabled() or max_statutes is not None:
                seed_budget = limit if limit is not None else 2
                direct = await self._scrape_official_seed_sections(
                    code_name,
                    max_statutes=max(1, int(seed_budget)),
                )
                _merge(self._filter_official_only(direct))
                if limit is not None and len(merged) >= int(limit):
                    return merged[: int(limit)]

            if merged and (not self._full_corpus_enabled() or max_statutes is not None):
                return merged[: int(limit)] if limit is not None else merged

        # Secondary Justia is never sole full-corpus admission unless re-enabled.
        if self._full_corpus_enabled() and max_statutes is None and not allow_justia:
            if merged:
                return merged
            self.logger.warning(
                "Tennessee full-corpus run found zero official statutes; "
                "refusing secondary Justia sole-admission fallback"
            )
            return []

        justia_limit = limit
        if self._is_justia_url(code_url) or allow_justia or not self._full_corpus_enabled():
            justia_statutes = await self._scrape_justia_code_tree(
                code_name=code_name,
                max_statutes=justia_limit,
            )
            _merge(justia_statutes)
            if limit is not None and len(merged) >= int(limit):
                return merged[: int(limit)]

        if not merged and not self._full_corpus_enabled():
            legacy = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=max(1, int(limit or 1)),
            )
            _merge(legacy)

        return merged[: int(limit)] if limit is not None else merged

    async def _scrape_official_tga_tree(
        self,
        *,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Walk official Tennessee portal pages for section-level statute rows."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        entry_urls = [
            code_url if self._is_official_host(code_url) else "",
            "https://www.tn.gov/tga/statutes.html",
            "https://www.tn.gov/tga",
            "https://www.capitol.tn.gov/legislation/",
            "https://www.capitol.tn.gov/",
        ]
        queue: List[str] = []
        seen_pages: Set[str] = set()
        for url in entry_urls:
            value = str(url or "").strip()
            if value and value not in seen_pages and self._is_official_host(value):
                queue.append(value)
                seen_pages.add(value)

        section_urls: List[str] = []
        seen_sections: Set[str] = set()
        page_budget = None if limit is None else max(24, int(limit) * 8)
        pages_scanned = 0

        while queue:
            if limit is not None and len(section_urls) >= max(24, int(limit) * 4):
                break
            if page_budget is not None and pages_scanned >= page_budget:
                break
            page_url = queue.pop(0)
            pages_scanned += 1
            payload = await self._fetch_page_content_with_archival_fallback(
                page_url,
                timeout_seconds=30,
            )
            if not payload:
                continue
            html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                if not href or href.startswith("#") or href.lower().startswith("javascript:"):
                    continue
                abs_url = urljoin(page_url, href)
                if not self._is_official_host(abs_url):
                    continue
                canonical = abs_url.split("#", 1)[0]
                label = self._normalize_legal_text(anchor.get_text(" ", strip=True))
                if self._looks_like_section_url(canonical, label):
                    if canonical not in seen_sections:
                        seen_sections.add(canonical)
                        section_urls.append(canonical)
                    continue
                if self._looks_like_index_url(canonical, label) and canonical not in seen_pages:
                    seen_pages.add(canonical)
                    queue.append(canonical)

        out: List[NormalizedStatute] = []
        for index, section_url in enumerate(section_urls, start=1):
            if limit is not None and len(out) >= int(limit):
                break
            statute = await self._build_official_section_statute(
                code_name=code_name,
                section_url=section_url,
                fallback_number=str(index),
            )
            if statute is not None:
                out.append(statute)
        return out

    def _looks_like_section_url(self, url: str, label: str = "") -> bool:
        value = str(url or "").lower()
        if self._TN_OFFICIAL_SECTION_RE.search(value):
            return True
        if self._TN_SECTION_LABEL_RE.search(label or "") and any(
            token in value for token in ("/statute", "/section", "/tca/", "code")
        ):
            return True
        return bool(re.search(r"section[/_-][0-9]+-[0-9]+", value))

    def _looks_like_index_url(self, url: str, label: str = "") -> bool:
        value = str(url or "").lower()
        label_l = str(label or "").lower()
        if any(token in value for token in ("/tga", "/statute", "/tca", "/code", "/title", "/chapter", "/legislation")):
            return True
        return any(token in label_l for token in ("title", "chapter", "statute", "code", "tca"))

    async def _build_official_section_statute(
        self,
        *,
        code_name: str,
        section_url: str,
        fallback_number: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        payload = await self._fetch_page_content_with_archival_fallback(
            section_url,
            timeout_seconds=30,
        )
        if not payload:
            return None
        html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        soup = BeautifulSoup(html, "html.parser")
        content = (
            soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one("#content")
            or soup.find("body")
            or soup
        )
        text = self._normalize_legal_text(content.get_text(" ", strip=True))
        if len(text) < 220:
            return None

        section_number = ""
        section_match = self._TN_OFFICIAL_SECTION_RE.search(section_url)
        if section_match:
            section_number = section_match.group(1)
        if not section_number:
            label_match = self._TN_SECTION_LABEL_RE.search(text[:400])
            if label_match:
                section_number = label_match.group(1)
        if not section_number:
            section_number = str(fallback_number)

        heading = soup.find(["h1", "h2", "h3"])
        section_name = self._normalize_legal_text(heading.get_text(" ", strip=True) if heading else "")
        if not section_name:
            section_name = f"Section {section_number}"
        title_number = section_number.split("-", 1)[0] if "-" in section_number else None

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=title_number,
            section_number=section_number,
            section_name=section_name[:200],
            full_text=text[:14000],
            legal_area=self._identify_legal_area(text[:1200]),
            source_url=section_url,
            official_cite=f"Tenn. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_tennessee_code_html",
                "discovery_method": "official_tga_capitol_hierarchy",
                "skip_hydrate": True,
            },
        )

    async def _scrape_official_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        seeds = [
            (
                "1-1-101",
                "Designation and citation",
                "https://www.tn.gov/tga/statutes/title-1/chapter-1/section-1-1-101.html",
            ),
            (
                "1-1-102",
                "Construction of code",
                "https://www.tn.gov/tga/statutes/title-1/chapter-1/section-1-1-102.html",
            ),
            (
                "39-13-202",
                "First degree murder",
                "https://www.capitol.tn.gov/legislation/statutes/title-39/chapter-13/section-39-13-202.html",
            ),
        ]
        out: List[NormalizedStatute] = []
        for section_number, section_name, source_url in seeds[: max(1, int(max_statutes or 1))]:
            statute = await self._build_official_section_statute(
                code_name=code_name,
                section_url=source_url,
                fallback_number=section_number,
            )
            if statute is None:
                # Offline/bounded fixtures may supply page HTML without live body
                # extraction succeeding; still admit labeled official seeds only
                # when the page fetch returns substantive text via generic path.
                payload = await self._fetch_page_content_with_archival_fallback(
                    source_url,
                    timeout_seconds=25,
                )
                if not payload:
                    continue
                text = self._normalize_legal_text(
                    payload.decode("utf-8", errors="replace")
                    if isinstance(payload, bytes)
                    else str(payload)
                )
                text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
                text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
                text = re.sub(r"(?is)<[^>]+>", " ", text)
                text = self._normalize_legal_text(text)
                if len(text) < 220:
                    continue
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name,
                    full_text=text[:14000],
                    legal_area=self._identify_legal_area(text[:1200]),
                    source_url=source_url,
                    official_cite=f"Tenn. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_tennessee_code_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            else:
                # Prefer known seed metadata when the page body is present.
                statute.section_number = section_number
                statute.section_name = section_name
                statute.statute_id = f"{code_name} § {section_number}"
                statute.official_cite = f"Tenn. Code Ann. § {section_number}"
                if statute.structured_data is None:
                    statute.structured_data = {}
                statute.structured_data["discovery_method"] = "official_seed_section"
            out.append(statute)
        return out

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
