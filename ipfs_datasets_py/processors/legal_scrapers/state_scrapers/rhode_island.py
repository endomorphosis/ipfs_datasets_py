"""Scraper for Rhode Island state laws."""

from __future__ import annotations

import re
from typing import List, Dict, Optional
from urllib.parse import urljoin

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

_TITLE_INDEX_URL_TEMPLATE = "https://webserver.rilegislature.gov/Statutes/TITLE{title}/INDEX.HTM"
_TITLE_LINK_RE = re.compile(r"/Statutes/TITLE(\d+)/(\d+(?:-\d+)+)/INDEX\.htm$", re.IGNORECASE)
_SECTION_LINK_RE = re.compile(r"/Statutes/TITLE(\d+)/(\d+(?:-\d+)+)/([\dA-Za-z._-]+)\.htm$", re.IGNORECASE)
_SECTION_NUMBER_RE = re.compile(r"§\s*([0-9A-Za-z.-]+)")


class RhodeIslandScraper(BaseStateScraper):
    """Scraper for Rhode Island state laws from http://webserver.rilin.state.ri.us"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Rhode Island's legislative website."""
        return "https://webserver.rilegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Rhode Island."""
        return [{
            "name": "Rhode Island General Laws",
            "url": _TITLE_INDEX_URL_TEMPLATE.format(title=1),
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Rhode Island's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=100)
        max_sections = limit if limit is not None else 1000000
        return await self._custom_scrape_rhode_island(
            code_name,
            code_url,
            "R.I. Gen. Laws",
            max_sections=max_sections,
        )
    
    async def _custom_scrape_rhode_island(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Rhode Island's legislative website."""
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        statutes: List[NormalizedStatute] = []
        seen_urls = set()

        try:
            max_title = 60
            consecutive_missing_titles = 0
            for title_num in range(1, max_title + 1):
                if len(statutes) >= max_sections:
                    break

                title_url = _TITLE_INDEX_URL_TEMPLATE.format(title=title_num)
                title_bytes = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=30)
                title_html = title_bytes.decode("utf-8", errors="replace") if title_bytes else ""
                if not title_html or "Document Moved" in title_html or "404" in title_html[:200]:
                    consecutive_missing_titles += 1
                    if consecutive_missing_titles >= 5 and title_num > 47:
                        break
                    continue
                consecutive_missing_titles = 0

                title_soup = BeautifulSoup(title_html, "html.parser")
                chapter_links = []
                for link in title_soup.find_all("a", href=True):
                    full_url = urljoin(title_url, str(link.get("href") or ""))
                    if _TITLE_LINK_RE.search(full_url):
                        chapter_links.append((link, full_url))

                for link, chapter_url in chapter_links:
                    if len(statutes) >= max_sections:
                        break

                    chapter_bytes = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=30)
                    if not chapter_bytes:
                        continue
                    chapter_soup = BeautifulSoup(chapter_bytes, "html.parser")
                    chapter_name = link.get_text(" ", strip=True) or ""
                    legal_area = self._identify_legal_area(chapter_name or code_name)

                    for section_link in chapter_soup.find_all("a", href=True):
                        if len(statutes) >= max_sections:
                            break
                        section_url = urljoin(chapter_url, str(section_link.get("href") or ""))
                        if section_url in seen_urls:
                            continue
                        if not _SECTION_LINK_RE.search(section_url):
                            continue

                        section_label = section_link.get_text(" ", strip=True)
                        section_number = self._extract_ri_section_number(section_label, section_url)
                        if not section_number:
                            continue

                        statute = NormalizedStatute(
                            state_code=self.state_code,
                            state_name=self.state_name,
                            statute_id=f"{code_name} § {section_number}",
                            code_name=code_name,
                            title_number=str(title_num),
                            chapter_number=self._extract_ri_chapter_number(chapter_url),
                            chapter_name=chapter_name[:200] or None,
                            section_number=section_number,
                            section_name=section_label[:200],
                            full_text=f"Section {section_number}: {section_label}",
                            legal_area=legal_area,
                            source_url=section_url,
                            official_cite=f"{citation_format} § {section_number}",
                            metadata=StatuteMetadata(),
                        )
                        statutes.append(statute)
                        seen_urls.add(section_url)

            self.logger.info("Rhode Island custom scraper: Scraped %s sections", len(statutes))
            if not statutes:
                self.logger.info("Rhode Island custom scraper found no data, falling back to generic scraper")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            return statutes
        except Exception as e:
            self.logger.error(f"Rhode Island custom scraper failed: {e}")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)

    def _extract_ri_section_number(self, link_text: str, url: str) -> str:
        match = _SECTION_NUMBER_RE.search(str(link_text or ""))
        if match:
            return match.group(1).strip().rstrip(".")
        return (
            self._extract_section_number(link_text)
            or self._derive_section_number_from_url(url)
            or ""
        )

    @staticmethod
    def _extract_ri_chapter_number(url: str) -> str | None:
        match = _TITLE_LINK_RE.search(str(url or ""))
        if not match:
            return None
        return match.group(2)


# Register this scraper with the registry
StateScraperRegistry.register("RI", RhodeIslandScraper)
