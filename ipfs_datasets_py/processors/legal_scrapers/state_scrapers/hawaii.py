"""Scraper for Hawaii state laws.

This module contains the scraper for Hawaii statutes from the official state legislative website.
"""

import asyncio
import re
from typing import Dict, List
from urllib.parse import unquote, urljoin
from html import unescape

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class HawaiiScraper(BaseStateScraper):
    """Scraper for Hawaii state laws from https://www.capitol.hawaii.gov"""

    _WAYBACK_ROOTS = [
        "http://web.archive.org/web/20060407224843/http://www.capitol.hawaii.gov/hrscurrent/",
        "http://web.archive.org/web/20060407230101/http://www.capitol.hawaii.gov/hrscurrent/",
    ]
    _SECTION_FILE_RE = re.compile(r"HRS_(\d{4})-(\d{4}(?:_\d{4})?)\.HTM$", re.IGNORECASE)
    _SEED_SECTION_URLS = [
        "http://web.archive.org/web/20060408115923/http://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0001.HTM",
        "http://web.archive.org/web/20060408115923/http://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0002.HTM",
        "http://web.archive.org/web/20060408115923/http://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0003.HTM",
        "http://web.archive.org/web/20060408115923/http://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0004.HTM",
    ]

    def get_base_url(self) -> str:
        """Return the base URL for Hawaii's legislative website."""
        return "https://www.capitol.hawaii.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Hawaii."""
        return [
            {
                "name": "Hawaii Revised Statutes",
                "url": f"{self.get_base_url()}/hrscurrent/",
                "type": "Code",
            }
        ]

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Hawaii's legislative website.

        Hawaii live endpoints are frequently blocked in automation contexts,
        so we first try a Wayback snapshot of the official HRS site.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        archival = await self._scrape_archived_hrscurrent(code_name, max_statutes=20)
        if archival:
            self.logger.info(f"Hawaii archival fallback: Scraped {len(archival)} sections")
            return archival

        # Try Playwright against the live site.
        if self.has_playwright():
            try:
                return await self._playwright_scrape(
                    code_name,
                    code_url,
                    "Haw. Rev. Stat.",
                    wait_for_selector="a[href*='Vol'], .statute-link, a[href*='hrs']",
                    timeout=45000,
                )
            except Exception as e:
                self.logger.warning(f"Hawaii Playwright scraping failed: {e}, falling back to HTTP")

        self.logger.info("Hawaii: Using fallback HTTP scraper")
        return await self._generic_scrape(code_name, code_url, "Haw. Rev. Stat.")

    async def _scrape_archived_hrscurrent(self, code_name: str, max_statutes: int = 20) -> List[NormalizedStatute]:
        """Scrape archived HRS section pages from Wayback when live site is blocked."""
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_dirs = set()
        seen_sections = set()

        for section_url in self._SEED_SECTION_URLS:
            statute = await self._build_statute_from_section_url(code_name, section_url, headers)
            if statute is None:
                continue
            statutes.append(statute)
            if len(statutes) >= max_statutes:
                return statutes

        if statutes:
            return statutes

        for root_url in self._WAYBACK_ROOTS:
            root_html = await self._request_text(root_url, headers=headers, timeout=45)
            if not root_html:
                self.logger.debug(f"Hawaii archive root failed {root_url}")
                continue

            volume_dirs: List[str] = []
            for href in self._extract_hrefs(root_html):
                if not href:
                    continue
                full_url = urljoin(root_url, href)
                decoded = unquote(full_url)
                if "/hrscurrent/Vol" not in decoded or "_Ch" not in decoded:
                    continue
                if full_url in seen_dirs:
                    continue
                seen_dirs.add(full_url)
                volume_dirs.append(full_url)

            chapter_dirs: List[str] = []
            for volume_url in volume_dirs:
                volume_html = await self._request_text(volume_url, headers=headers, timeout=45)
                if not volume_html:
                    self.logger.debug(f"Hawaii archive volume failed {volume_url}")
                    continue

                for href in self._extract_hrefs(volume_html):
                    if not href:
                        continue
                    full_url = urljoin(volume_url, href)
                    decoded = unquote(full_url)
                    if not re.search(r"/HRS\d{4}[A-Z]?/", decoded):
                        continue
                    if full_url in seen_dirs:
                        continue
                    seen_dirs.add(full_url)
                    chapter_dirs.append(full_url)

            for chapter_url in chapter_dirs:
                if len(statutes) >= max_statutes:
                    break

                chapter_html = await self._request_text(chapter_url, headers=headers, timeout=45)
                if not chapter_html:
                    self.logger.debug(f"Hawaii archive chapter failed {chapter_url}")
                    continue

                section_urls: List[str] = []
                for href in self._extract_hrefs(chapter_html):
                    if not href:
                        continue
                    full_url = urljoin(chapter_url, href)
                    if full_url in seen_sections:
                        continue
                    if not self._SECTION_FILE_RE.search(unquote(full_url)):
                        continue
                    seen_sections.add(full_url)
                    section_urls.append(full_url)

                for section_url in section_urls:
                    if len(statutes) >= max_statutes:
                        break
                    statute = await self._build_statute_from_section_url(code_name, section_url, headers)
                    if statute is None:
                        continue
                    statutes.append(statute)

            if statutes:
                break

        return statutes

    def _extract_section_number_from_wayback_url(self, url: str) -> str:
        match = self._SECTION_FILE_RE.search(unquote(str(url or "")))
        if not match:
            return ""

        chapter = str(int(match.group(1)))
        raw_section = match.group(2)
        if "_" in raw_section:
            primary, secondary = raw_section.split("_", 1)
            section = f"{int(primary)}.{int(secondary)}"
        else:
            section = str(int(raw_section))
        return f"{chapter}-{section}"

    def _extract_wayback_statute_text(self, html: str, max_chars: int = 12000) -> str:
        value = str(html or "")
        value = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", value)
        value = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", value)
        value = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", value)
        value = re.sub(r"(?is)<[^>]+>", " ", value)

        text = unescape(value)
        text = re.sub(r"\s+", " ", text).strip()

        archive_idx = text.find("FILE ARCHIVED ON")
        if archive_idx > 0:
            text = text[:archive_idx].strip()

        return text[:max_chars]

    def _extract_hrefs(self, html: str) -> List[str]:
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', str(html or ""), flags=re.IGNORECASE)
        out: List[str] = []
        for href in hrefs:
            value = str(href or "").strip()
            value = re.sub(r"\s+", "", value)
            if not value or value.startswith("#"):
                continue
            out.append(value)
        return out

    async def _request_text(self, url: str, headers: Dict[str, str], timeout: int) -> str:
        candidates = [str(url or "")]
        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        for candidate in candidates:
            for _ in range(4):
                try:
                    payload = await self._fetch_page_content_with_archival_fallback(
                        candidate,
                        timeout_seconds=timeout,
                    )
                    if payload:
                        return payload.decode("utf-8", errors="replace")
                except Exception:
                    await asyncio.sleep(0.6)
                    continue
        return ""

    async def _build_statute_from_section_url(
        self,
        code_name: str,
        section_url: str,
        headers: Dict[str, str],
    ) -> NormalizedStatute | None:
        section_number = self._extract_section_number_from_wayback_url(section_url)
        if not section_number:
            return None

        section_html = await self._request_text(section_url, headers=headers, timeout=45)
        if not section_html:
            return None

        full_text = self._extract_wayback_statute_text(section_html)
        if len(full_text) < 280:
            return None

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=f"Section {section_number}",
            full_text=full_text,
            legal_area=self._identify_legal_area(full_text),
            source_url=section_url,
            official_cite=f"Haw. Rev. Stat. § {section_number}",
            metadata=StatuteMetadata(),
        )


# Register this scraper with the registry
StateScraperRegistry.register("HI", HawaiiScraper)
