"""Scraper for District of Columbia Official Code.

Primary path: official hierarchy on https://code.dccouncil.gov
(title → chapter → section). Playwright/generic remain fallbacks only.
"""

from typing import List, Dict, Optional, Tuple
import re
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class DistrictOfColumbiaScraper(BaseStateScraper):
    """Scraper for District of Columbia state laws from https://code.dccouncil.gov"""

    _DC_SECTION_URL_RE = re.compile(
        r"/us/dc/council/code/sections/([0-9A-Za-z.\-]+)/?$",
        re.IGNORECASE,
    )
    _DC_TITLE_URL_RE = re.compile(
        r"/us/dc/council/code/titles/(\d+)/?$",
        re.IGNORECASE,
    )
    _DC_CHAPTER_URL_RE = re.compile(
        r"/us/dc/council/code/titles/\d+/chapters/(\d+)/?$",
        re.IGNORECASE,
    )
    # Legacy filter also accepted chapter/subchapter index pages from generic scrape.
    _DC_LEGACY_LEVEL_URL_RE = re.compile(
        r"/us/dc/council/code/(?:sections/[0-9A-Za-z.\-]+|titles/\d+/chapters/\d+(?:/subchapters/[IVXLC]+)?)/?$",
        re.IGNORECASE,
    )

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._DC_LEGACY_LEVEL_URL_RE.search(source):
                filtered.append(statute)
        return filtered

    def get_base_url(self) -> str:
        """Return the base URL for District of Columbia's legislative website."""
        return "https://code.dccouncil.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for District of Columbia."""
        return [{
            "name": "District of Columbia Official Code",
            "url": f"{self.get_base_url()}/us/dc/council/code",
            "type": "Code",
        }]

    def _probe_timeout_seconds(self) -> int:
        """Bounded probes use a short timeout so offline unit tests fail closed fast.

        Full-corpus runs keep a longer recovery budget for official pages.
        """
        return 25 if self._full_corpus_enabled() else 4

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from District of Columbia's legislative website.

        Prefers the official title/chapter/section HTML hierarchy. Playwright and
        generic scrapers remain offline/fallback paths only.
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        seed_statutes: List[NormalizedStatute] = []

        # Bounded probes may gather direct seeds; full-corpus never sole-admits seeds.
        # Prefer the official hierarchy when available; seeds are a recovery path only.
        if not self._full_corpus_enabled() or max_statutes is not None:
            seed_limit = limit if limit is not None else 160
            seed_statutes = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=seed_limit,
            )

        official = await self._scrape_official_index(code_name, max_statutes=limit)
        if official:
            return official if limit is None else official[: int(limit)]

        if seed_statutes:
            return seed_statutes if limit is None else seed_statutes[: int(limit)]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/us/dc/council/code/titles/1",
            f"{self.get_base_url()}/us/dc/council/code/titles/2",
            f"{self.get_base_url()}/us/dc/council/code/titles/1/chapters/1",
            f"{self.get_base_url()}/us/dc/council/code/sections/1-101",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        return_threshold = limit if limit is not None else 1000000
        scan_limit = return_threshold if limit is not None else 1000
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "D.C. Code",
                        max_sections=scan_limit,
                        wait_for_selector="a[href*='/sections/'], a[href*='/chapters/'], a[href*='/titles/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes[:return_threshold]
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "D.C. Code",
                max_sections=scan_limit,
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes[:return_threshold]

        if limit is None:
            return best_statutes
        return best_statutes[: int(limit)]

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        seeds = [
            ("1-101", f"{self.get_base_url()}/us/dc/council/code/sections/1-101"),
            ("1-102", f"{self.get_base_url()}/us/dc/council/code/sections/1-102"),
        ]
        return await self._scrape_section_urls(
            code_name,
            seeds,
            max_statutes=max_statutes,
            discovery_method="official_seed_section",
        )

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        title_links = await self._discover_title_links()
        self.logger.info(
            "District of Columbia official index: discovered %s title links",
            len(title_links),
        )
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            if title_index == 1 or title_index % 10 == 0 or title_index == len(title_links):
                self.logger.info(
                    "District of Columbia official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                    title_label or title_url,
                    title_index,
                    len(title_links),
                    len(chapter_links),
                    len(statutes),
                )
            for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                section_links = await self._discover_section_links(chapter_url)
                if (
                    chapter_index == 1
                    or chapter_index % 10 == 0
                    or chapter_index == len(chapter_links)
                ):
                    self.logger.info(
                        "District of Columbia official index: title=%s chapter=%s/%s sections=%s statutes_so_far=%s",
                        title_label or title_url,
                        chapter_index,
                        len(chapter_links),
                        len(section_links),
                        len(statutes),
                    )
                parsed = await self._scrape_section_urls(
                    code_name,
                    section_links,
                    max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                    discovery_method="official_title_chapter_section_index",
                )
                statutes.extend(parsed)
        return statutes[:limit] if limit is not None else statutes

    async def _discover_title_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/us/dc/council/code"
        payload = await self._fetch_page_content_with_archival_fallback(
            index_url,
            timeout_seconds=self._probe_timeout_seconds(),
        )
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not self._DC_TITLE_URL_RE.search(href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(
            title_url,
            timeout_seconds=self._probe_timeout_seconds(),
        )
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(title_url, str(anchor.get("href") or "").strip())
            if not self._DC_CHAPTER_URL_RE.search(href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(
            chapter_url,
            timeout_seconds=self._probe_timeout_seconds(),
        )
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            match = self._DC_SECTION_URL_RE.search(href)
            if not match:
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            section_number = match.group(1)
            out.append((section_number, normalized))
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
        discovery_method: str = "official_seed_section",
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        statutes: List[NormalizedStatute] = []
        for first, second in section_urls:
            if limit is not None and len(statutes) >= limit:
                break
            # Accept either (section_number, url) or (url, section_number).
            if str(first).startswith("http"):
                source_url, section_number = first, second
            else:
                section_number, source_url = first, second
            match = self._DC_SECTION_URL_RE.search(str(source_url))
            if match:
                section_number = match.group(1)
            section_number = str(section_number or "").strip()
            if not section_number:
                continue

            payload = await self._fetch_page_content_with_archival_fallback(
                str(source_url),
                timeout_seconds=self._probe_timeout_seconds(),
            )
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
                tag.decompose()

            heading = (
                soup.select_one("h1")
                or soup.select_one(".section-title")
                or soup.select_one("title")
            )
            section_name = self._normalize_legal_text(
                heading.get_text(" ", strip=True) if heading else f"Section {section_number}"
            )
            main = (
                soup.select_one("main")
                or soup.select_one("article")
                or soup.select_one("#content")
                or soup.select_one(".content")
                or soup.find("body")
                or soup
            )
            text = self._normalize_legal_text(main.get_text(" ", strip=True))
            if len(text) < 180:
                continue

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:220] or f"Section {section_number}",
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=str(source_url),
                    official_cite=f"D.C. Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_dc_council_code_html",
                        "discovery_method": discovery_method,
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("DC", DistrictOfColumbiaScraper)
