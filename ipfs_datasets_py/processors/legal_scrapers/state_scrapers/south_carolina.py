"""Scraper for South Carolina state laws.

This module contains the scraper for South Carolina statutes from the official state legislative website.
"""

import re
from typing import List, Dict, Optional
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class SouthCarolinaScraper(BaseStateScraper):
    """Scraper for South Carolina state laws from https://www.scstatehouse.gov"""
    _TITLE_URL_RE = re.compile(r"/code/title(\d+)\.php$", re.IGNORECASE)
    _CHAPTER_URL_RE = re.compile(r"/code/t(\d{2})c(\d{3})\.php$", re.IGNORECASE)
    _SECTION_START_RE = re.compile(r"\bSECTION\s+([0-9A-Za-z.-]+)\.\s*", re.IGNORECASE)
    
    def get_base_url(self) -> str:
        """Return the base URL for South Carolina's legislative website."""
        return "https://www.scstatehouse.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for South Carolina."""
        return [{
            "name": "South Carolina Code of Laws",
            # Use the statute master page directly; home page navigation is noisy
            # and often yields zero probable statute links.
            "url": f"{self.get_base_url()}/code/statmast.php",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from South Carolina's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._bounded_return_threshold(160)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))
        official = await self._scrape_official_code_tree(
            code_name,
            max_statutes=None if self._full_corpus_enabled() and max_statutes is None else return_threshold,
        )
        if official:
            return official if self._full_corpus_enabled() and max_statutes is None else official[:return_threshold]
        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
            if direct:
                return direct[:return_threshold]
        return await self._generic_scrape(code_name, code_url, "S.C. Code Ann.", max_sections=max(10, return_threshold))

    async def _scrape_official_code_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        title_links = await self._discover_title_links()
        self.logger.info("South Carolina official index: discovered %s title links", len(title_links))
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None

        for title_index, (title_number, title_name, title_url) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "South Carolina official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                title_number,
                title_index,
                len(title_links),
                len(chapter_links),
                len(statutes),
            )
            for chapter_index, (chapter_number, chapter_url) in enumerate(chapter_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                parsed = await self._parse_chapter_sections(
                    code_name=code_name,
                    title_number=title_number,
                    title_name=title_name,
                    chapter_number=chapter_number,
                    chapter_url=chapter_url,
                    max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                )
                statutes.extend(parsed)
                if chapter_index == 1 or chapter_index % 10 == 0 or chapter_index == len(chapter_links):
                    self.logger.info(
                        "South Carolina official index: title=%s chapter=%s/%s statutes_so_far=%s",
                        title_number,
                        chapter_index,
                        len(chapter_links),
                        len(statutes),
                    )

        return statutes[:limit] if limit is not None else statutes

    async def _discover_title_links(self) -> List[tuple[str, str, str]]:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(
            f"{self.get_base_url()}/code/statmast.php",
            timeout_seconds=35,
        )
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[tuple[str, str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            match = self._TITLE_URL_RE.search(href)
            if not match:
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            title_number = match.group(1)
            title_name = self._normalize_legal_text(anchor.get_text(" ", strip=True))
            out.append((title_number, title_name, normalized))
        return out

    async def _discover_chapter_links(self, title_url: str) -> List[tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=35)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            match = self._CHAPTER_URL_RE.search(href)
            if not match:
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((str(int(match.group(2))), normalized))
        return out

    async def _parse_chapter_sections(
        self,
        *,
        code_name: str,
        title_number: str,
        title_name: str,
        chapter_number: str,
        chapter_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=35)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        text = self._normalize_legal_text(soup.get_text("\n", strip=True))
        matches = list(self._SECTION_START_RE.finditer(text))
        if not matches:
            return []

        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for index, match in enumerate(matches):
            if limit is not None and len(statutes) >= limit:
                break
            section_number = match.group(1).strip()
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            segment = self._normalize_legal_text(text[start:end])
            if len(segment) < 120:
                continue
            title_match = re.match(
                rf"SECTION\s+{re.escape(section_number)}\.\s*([^\.]{{3,220}})",
                segment,
                flags=re.IGNORECASE,
            )
            section_name = title_match.group(1).strip() if title_match else f"Section {section_number}"
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=title_number,
                    title_name=title_name[:200] if title_name else None,
                    chapter_number=chapter_number,
                    section_number=section_number,
                    section_name=section_name[:220],
                    full_text=segment[:14000],
                    legal_area=self._identify_legal_area(section_name or segment[:1000]),
                    source_url=f"{chapter_url}#{section_number}",
                    official_cite=f"S.C. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_south_carolina_code_html",
                        "discovery_method": "official_title_chapter_index",
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 1,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("16-3-10", "https://www.scstatehouse.gov/code/t16c003.php"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, url in seeds[: max(1, int(max_statutes or 1))]:
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            soup = BeautifulSoup(raw, "html.parser")
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            match = re.search(
                rf"\bSECTION\s+{re.escape(section_number)}\.\s*(.+?)(?=\bSECTION\s+\d+-\d+-\d+\.)",
                text,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            body = self._normalize_legal_text(f"SECTION {section_number}. {match.group(1)}")
            if len(body) < 120:
                continue
            name_match = re.match(rf"SECTION\s+{re.escape(section_number)}\.\s*([^\.]+)\.", body, flags=re.IGNORECASE)
            section_name = name_match.group(1).strip() if name_match else section_number
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name[:220],
                    full_text=body,
                    legal_area=self._identify_legal_area(body[:1200]),
                    source_url=f"{url}#{section_number}",
                    official_cite=f"S.C. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_south_carolina_code_html",
                        "discovery_method": "official_seed_chapter_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out


# Register this scraper with the registry
StateScraperRegistry.register("SC", SouthCarolinaScraper)
