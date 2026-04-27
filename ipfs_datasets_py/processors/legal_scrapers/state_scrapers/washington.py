"""Scraper for Washington state laws.

This module contains the scraper for Washington statutes from the official state legislative website.
"""

from typing import List, Dict, Optional, Tuple
import re
from urllib.parse import parse_qs, urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class WashingtonScraper(BaseStateScraper):
    """Scraper for Washington state laws from https://app.leg.wa.gov"""

    _SECTION_CITE_RE = re.compile(r"^\d+[A-Za-z]?\.\d+(?:\.\d+)?[A-Za-z]?$")

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            section_number = str(statute.section_number or "")
            if "default.aspx?cite=" not in source.lower():
                continue
            if self._SECTION_CITE_RE.match(section_number):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Washington's legislative website."""
        return "https://app.leg.wa.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Washington."""
        return [{
            "name": "Revised Code of Washington",
            "url": f"{self.get_base_url()}/RCW/default.aspx?cite=9A.32.030",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str, max_statutes: int | None = None) -> List[NormalizedStatute]:
        """Scrape a specific code from Washington's legislative website.
        
        Washington RCW database uses JavaScript navigation, so we use Playwright.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._effective_scrape_limit(max_statutes, default=160) or 1000000
        if not self._full_corpus_enabled() and max_statutes is None:
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=int(return_threshold))
            if direct:
                return direct[: int(return_threshold)]

        official = await self._scrape_official_index(
            code_name,
            max_statutes=None if return_threshold == 1000000 else int(return_threshold),
        )
        if official:
            return official[: int(return_threshold)]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/RCW/default.aspx",
            f"{self.get_base_url()}/RCW/",
            f"{self.get_base_url()}/RCW/default.aspx?cite=1",
            f"{self.get_base_url()}/RCW/default.aspx?cite=9A.32.030",
            f"{self.get_base_url()}/RCW/default.aspx?cite=9A.04",
            f"{self.get_base_url()}/RCW/default.aspx?cite=4.24",
            f"{self.get_base_url()}/RCW/default.aspx?cite=7.28",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        fallback_scan_limit = int(return_threshold)
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Wash. Rev. Code",
                        max_sections=fallback_scan_limit,
                        wait_for_selector="a[href*='default.aspx?cite='], a[href*='/RCW/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes[:return_threshold]
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Wash. Rev. Code", max_sections=fallback_scan_limit)
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes[:return_threshold]

        return best_statutes[:return_threshold]

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
            ("9A.32.030", "https://app.leg.wa.gov/RCW/default.aspx?cite=9A.32.030"),
        ]
        return await self._scrape_section_urls(
            code_name,
            [(url, section_number) for section_number, url in seeds],
            max_statutes=max_statutes,
            discovery_method="official_seed_section",
        )

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        title_links = await self._discover_title_links()
        self.logger.info("Washington official index: discovered %s title links", len(title_links))
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "Washington official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
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
                if chapter_index == 1 or chapter_index % 10 == 0 or chapter_index == len(chapter_links):
                    self.logger.info(
                        "Washington official index: title=%s chapter=%s/%s sections=%s statutes_so_far=%s",
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

        index_url = f"{self.get_base_url()}/RCW/default.aspx"
        raw = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            cite = self._extract_cite_from_url(href)
            if not cite or "." in cite or not re.match(r"^\d+[A-Za-z]?$", cite):
                continue
            normalized = f"{self.get_base_url()}/RCW/default.aspx?cite={cite}"
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

        title_cite = self._extract_cite_from_url(title_url)
        raw = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(title_url, str(anchor.get("href") or "").strip())
            cite = self._extract_cite_from_url(href)
            if not cite or not title_cite or not cite.startswith(f"{title_cite}."):
                continue
            if cite.count(".") != 1:
                continue
            normalized = f"{self.get_base_url()}/RCW/default.aspx?cite={cite}"
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

        chapter_cite = self._extract_cite_from_url(chapter_url)
        raw = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            cite = self._extract_cite_from_url(href)
            if not cite or not chapter_cite or not cite.startswith(f"{chapter_cite}."):
                continue
            if not self._SECTION_CITE_RE.match(cite):
                continue
            normalized = f"{self.get_base_url()}/RCW/default.aspx?cite={cite}"
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, cite))
        return out

    def _extract_cite_from_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            values = parse_qs(parsed.query).get("cite") or parse_qs(parsed.query).get("Cite") or []
            return str(values[0] if values else "").strip()
        except Exception:
            return ""

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

        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for url, section_number in section_urls:
            if limit is not None and len(out) >= limit:
                break
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            soup = BeautifulSoup(raw, "html.parser")
            citation_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h1")
            caption_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h2")
            content_node = soup.select_one("#contentWrapper")
            citation_text = self._normalize_legal_text(citation_node.get_text(" ", strip=True) if citation_node else "")
            caption = self._normalize_legal_text(caption_node.get_text(" ", strip=True) if caption_node else "")
            body = self._normalize_legal_text(content_node.get_text(" ", strip=True) if content_node else "")
            if len(body) < 220:
                continue
            full_text = self._normalize_legal_text(f"{citation_text} {caption} {body}")
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split(".", 1)[0],
                    section_number=section_number,
                    section_name=caption or section_number,
                    full_text=full_text,
                    legal_area=self._identify_legal_area(full_text[:1200]),
                    source_url=url,
                    official_cite=f"Wash. Rev. Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_washington_rcw_html",
                        "discovery_method": discovery_method,
                        "skip_hydrate": True,
                    },
                )
            )
        return out


# Register this scraper with the registry
StateScraperRegistry.register("WA", WashingtonScraper)
