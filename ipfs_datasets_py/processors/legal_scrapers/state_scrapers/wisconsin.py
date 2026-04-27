"""Scraper for Wisconsin state laws.

This module contains the scraper for Wisconsin statutes from the official state legislative website.
"""

from typing import List, Dict, Optional, Tuple
import re
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class WisconsinScraper(BaseStateScraper):
    """Scraper for Wisconsin state laws from https://docs.legis.wisconsin.gov"""

    _WI_SECTION_URL_RE = re.compile(r"/document/statutes/[0-9]+(?:\.[0-9A-Za-z]+)+$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._WI_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Wisconsin's legislative website."""
        return "https://docs.legis.wisconsin.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Wisconsin."""
        return [{
            "name": "Wisconsin Statutes",
            "url": f"{self.get_base_url()}/statutes/statutes",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Wisconsin's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=40)
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        if official:
            return official[:limit] if limit is not None else official

        if limit is not None and max_statutes is None:
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
            if direct:
                return direct[:limit]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/statutes",
            f"{self.get_base_url()}/document/statutes/940",
            f"{self.get_base_url()}/document/statutes/939.50",
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
                        "Wis. Stat.",
                        max_sections=scan_limit,
                        wait_for_selector="a[href*='/document/statutes/'], a[href*='/statutes/statutes']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "Wis. Stat.",
                max_sections=scan_limit,
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes[:return_threshold]

        return best_statutes

    async def _scrape_direct_sections(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        section_urls = [
            ("939.50", f"{self.get_base_url()}/document/statutes/939.50"),
            ("940.01", f"{self.get_base_url()}/document/statutes/940.01"),
        ]
        return await self._scrape_section_urls(code_name, [(url, section_number) for section_number, url in section_urls], max_statutes=max_statutes)

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        chapter_links = await self._discover_chapter_links()
        self.logger.info("Wisconsin official index: discovered %s chapter links", len(chapter_links))
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            section_links = await self._discover_section_links(chapter_url)
            if chapter_index == 1 or chapter_index % 25 == 0 or chapter_index == len(chapter_links):
                self.logger.info(
                    "Wisconsin official index: chapter=%s index=%s/%s sections=%s statutes_so_far=%s",
                    chapter_label or chapter_url,
                    chapter_index,
                    len(chapter_links),
                    len(section_links),
                    len(statutes),
                )
            parsed = await self._scrape_section_urls(
                code_name,
                section_links,
                max_statutes=(None if limit is None else max(0, limit - len(statutes))),
            )
            statutes.extend(parsed)
        return statutes[:limit] if limit is not None else statutes

    async def _discover_chapter_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/statutes/statutes"
        payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not re.search(r"/document/statutes/[0-9]+/?$", href, re.IGNORECASE):
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

        chapter_match = re.search(r"/document/statutes/([0-9]+)/?$", chapter_url, re.IGNORECASE)
        chapter_number = chapter_match.group(1) if chapter_match else ""
        payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            if not self._WI_SECTION_URL_RE.search(href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            label = self._normalize_legal_text(anchor.get_text(" ", strip=True))
            section_number = normalized.rsplit("/", 1)[-1]
            if chapter_number and section_number.split(".", 1)[0] != chapter_number:
                continue
            out.append((normalized, label or section_number))
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        statutes: List[NormalizedStatute] = []
        for source_url, section_number in section_urls:
            if limit is not None and len(statutes) >= limit:
                break
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=15)
            if not payload:
                continue
            section_number = str(section_number or source_url.rsplit("/", 1)[-1]).strip()
            soup = BeautifulSoup(payload, "html.parser")
            section_nodes = soup.select(f'[data-section="{section_number}"]')
            if not section_nodes:
                section_nodes = soup.select(".box-content, #contentFrame")

            text_parts: List[str] = []
            section_name = ""
            for node in section_nodes:
                if not section_name:
                    title_node = node.select_one(".qstitle_sect") or node.find("title")
                    if title_node:
                        section_name = title_node.get_text(" ", strip=True)
                text_value = self._normalize_legal_text(node.get_text(" ", strip=True))
                if text_value:
                    text_parts.append(text_value)

            text = self._normalize_legal_text(" ".join(text_parts))
            if not section_name:
                title = soup.find("title")
                section_name = title.get_text(" ", strip=True) if title else f"Section {section_number}"
            if len(text) < 240:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=source_url,
                    official_cite=f"Wis. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_wisconsin_statutes_html", "skip_hydrate": True},
                )
            )
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("WI", WisconsinScraper)
