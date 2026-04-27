"""Scraper for West Virginia state laws.

This module contains the scraper for West Virginia statutes from the official state legislative website.
"""

from typing import List, Dict, Optional, Tuple
import re
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class WestVirginiaScraper(BaseStateScraper):
    """Scraper for West Virginia state laws from http://www.wvlegislature.gov"""

    _WV_SECTION_URL_RE = re.compile(r"/\d+[A-Za-z]?(?:-\d+[A-Za-z]?){1,2}/?$")

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._WV_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for West Virginia's legislative website."""
        return "https://code.wvlegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for West Virginia."""
        return [{
            "name": "West Virginia Code",
            "url": f"{self.get_base_url()}/11-8-12/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str, max_statutes: int | None = None) -> List[NormalizedStatute]:
        """Scrape a specific code from West Virginia's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._effective_scrape_limit(max_statutes, default=15) or 1000000
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
            f"{self.get_base_url()}/1/",
            f"{self.get_base_url()}/11/",
            f"{self.get_base_url()}/11-8-12/",
            f"{self.get_base_url()}/1-1/",
            f"{self.get_base_url()}/",
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
                        "W. Va. Code",
                        max_sections=fallback_scan_limit,
                        wait_for_selector="a[href*='wvlegislature.gov/'][href*='-'], a[href*='/code/'], a[href*='/article/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes[:return_threshold]
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "W. Va. Code", max_sections=fallback_scan_limit)
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
            ("61-2-1", "https://code.wvlegislature.gov/61-2-1/"),
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
        chapter_links = await self._discover_chapter_links()
        self.logger.info("West Virginia official index: discovered %s chapter links", len(chapter_links))
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            article_links = await self._discover_article_links(chapter_url)
            self.logger.info(
                "West Virginia official index: chapter=%s index=%s/%s articles=%s statutes_so_far=%s",
                chapter_label or chapter_url,
                chapter_index,
                len(chapter_links),
                len(article_links),
                len(statutes),
            )
            for article_index, (article_url, article_label) in enumerate(article_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                section_links = await self._discover_section_links(article_url)
                if article_index == 1 or article_index % 10 == 0 or article_index == len(article_links):
                    self.logger.info(
                        "West Virginia official index: chapter=%s article=%s/%s sections=%s statutes_so_far=%s",
                        chapter_label or chapter_url,
                        article_index,
                        len(article_links),
                        len(section_links),
                        len(statutes),
                    )
                parsed = await self._scrape_section_urls(
                    code_name,
                    section_links,
                    max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                    discovery_method="official_chapter_article_section_index",
                )
                statutes.extend(parsed)
        return statutes[:limit] if limit is not None else statutes

    async def _discover_chapter_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/"
        raw = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for option in soup.select("select#sel-chapter option[value]"):
            chapter = str(option.get("value") or "").strip()
            if not re.match(r"^\d+[A-Za-z]?$", chapter):
                continue
            normalized = f"{self.get_base_url()}/{chapter}/"
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(option.get_text(" ", strip=True))))
        return out

    async def _discover_article_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        raw = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("div.art-head a[href]"):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            if not re.search(r"/\d+[A-Za-z]?-\d+[A-Za-z]?/?$", href):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_section_links(self, article_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        raw = await self._fetch_page_content_with_archival_fallback(article_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("div.sec-head a[href]"):
            href = urljoin(article_url, str(anchor.get("href") or "").strip())
            if not self._WV_SECTION_URL_RE.search(href):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            section_number = normalized.rstrip("/").rsplit("/", 1)[-1]
            out.append((normalized, section_number))
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

        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for url, section_number in section_urls:
            if limit is not None and len(out) >= limit:
                break
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            soup = BeautifulSoup(raw, "html.parser")
            node = soup.select_one("div.sectiontext")
            if node is None:
                continue
            heading = self._normalize_legal_text((node.find("h4") or node).get_text(" ", strip=True))
            body_parts = [
                self._normalize_legal_text(p.get_text(" ", strip=True))
                for p in node.find_all("p")
            ]
            body = self._normalize_legal_text(" ".join([heading, *body_parts]))
            if len(body) < 180:
                continue
            section_name = re.sub(r"^§\s*[\w\-]+\.?\s*", "", heading).strip() or heading
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
                    source_url=url,
                    official_cite=f"W. Va. Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_west_virginia_code_html",
                        "discovery_method": discovery_method,
                        "skip_hydrate": True,
                    },
                )
            )
        return out


# Register this scraper with the registry
StateScraperRegistry.register("WV", WestVirginiaScraper)
