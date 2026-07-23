"""Scraper for Michigan state laws.

This module contains the scraper for Michigan statutes from the official state legislative website.
"""

import re
from typing import List, Dict, Optional
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MichiganScraper(BaseStateScraper):
    """Scraper for Michigan state laws from http://www.legislature.mi.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Michigan's legislative website."""
        return "https://www.legislature.mi.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Michigan."""
        return [{
            "name": "Michigan Compiled Laws",
            "url": f"{self.get_base_url()}/Laws/ChapterIndex",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Michigan's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = max(1, int(max_statutes)) if max_statutes is not None else self._bounded_return_threshold(160)
        official = await self._scrape_official_chapter_index(code_name, max_statutes=limit)
        if official:
            return official[:limit]

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
            if direct:
                return direct
        return await self._generic_scrape(code_name, code_url, "Mich. Comp. Laws", max_sections=max(10, limit))

    async def _scrape_official_chapter_index(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/Laws/ChapterIndex"
        payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=18)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        chapter_links: list[tuple[str, str]] = []
        seen_chapters: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if "objectName=mcl-chap" not in href:
                continue
            chapter_url = self._normalize_object_url(urljoin(index_url, href))
            if not chapter_url or chapter_url in seen_chapters:
                continue
            seen_chapters.add(chapter_url)
            chapter_links.append((self._text_or_empty(anchor), chapter_url))

        statutes: list[NormalizedStatute] = []
        seen_sections: set[str] = set()
        for chapter_label, chapter_url in chapter_links:
            if len(statutes) >= max_statutes:
                break
            act_url = await self._discover_act_url_from_chapter(chapter_url)
            act_sections = await self._discover_section_urls_from_act(act_url or chapter_url)
            for section_url in act_sections:
                if len(statutes) >= max_statutes:
                    break
                statute = await self._build_statute_from_section_page(
                    code_name=code_name,
                    section_url=section_url,
                    chapter_label=chapter_label,
                )
                if statute is None:
                    continue
                section_number = str(statute.section_number or "").strip()
                if not section_number or section_number in seen_sections:
                    continue
                seen_sections.add(section_number)
                statutes.append(statute)
        return statutes

    async def _discover_act_url_from_chapter(self, chapter_url: str) -> Optional[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=18)
        if not payload:
            return None
        soup = BeautifulSoup(payload, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if "objectName=mcl-Act-" not in href:
                continue
            return self._normalize_object_url(urljoin(chapter_url, href))
        return None

    async def _discover_section_urls_from_act(self, act_url: str) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(act_url, timeout_seconds=18)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not re.search(r"objectName=mcl-\d+(?:-\d+)+", href, flags=re.IGNORECASE):
                continue
            section_url = self._normalize_object_url(urljoin(act_url, href))
            if not section_url or section_url in seen:
                continue
            seen.add(section_url)
            out.append(section_url)
        return out

    async def _build_statute_from_section_page(
        self,
        *,
        code_name: str,
        section_url: str,
        chapter_label: str = "",
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=18)
        if not payload:
            return None
        soup = BeautifulSoup(payload, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        main = soup.select_one("main") or soup.select_one("#main") or soup.body
        if main is None:
            return None
        title = self._text_or_empty(main.find(["h1", "h2", "h3"]))
        text = self._normalize_legal_text(main.get_text(" ", strip=True))
        if len(text) < 160:
            return None
        object_section_number = self._section_number_from_object_name(section_url)
        match = re.search(r"\b(\d+(?:\.\d+)+(?:[a-z])?)\b", title or text, flags=re.IGNORECASE)
        section_number = object_section_number or (match.group(1) if match else section_url.rsplit("mcl-", 1)[-1])
        chapter_number = self._extract_section_number(chapter_label) or ""
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            chapter_number=chapter_number or None,
            chapter_name=chapter_label or None,
            section_number=section_number,
            section_name=title[:200] or f"Section {section_number}",
            full_text=text,
            legal_area=self._identify_legal_area(title or text),
            source_url=section_url,
            official_cite=f"Mich. Comp. Laws § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_michigan_compiled_laws_html",
                "discovery_method": "official_chapter_index_act_section",
                "skip_hydrate": True,
            },
        )

    async def _scrape_direct_sections(self, code_name: str, max_statutes: int | None = None) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        section_urls = [
            f"{self.get_base_url()}/Laws/MCL?objectName=mcl-750-316",
            f"{self.get_base_url()}/Laws/MCL?objectName=mcl-600-101",
        ]
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else self._bounded_return_threshold(160)
        for source_url in section_urls[:limit]:
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=12)
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            title = soup.find(["h1", "h2"])
            section_name = title.get_text(" ", strip=True) if title else ""
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            match = re.search(r"\b(\d+[A-Za-z]?(?:\.\d+[A-Za-z]*)+)\b", text)
            section_number = match.group(1) if match else source_url.rsplit("mcl-", 1)[-1]
            if len(text) < 160:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200] or f"Section {section_number}",
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=source_url,
                    official_cite=f"Mich. Comp. Laws § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_direct_section", "skip_hydrate": True},
                )
            )
        return statutes

    def _normalize_object_url(self, url: str) -> str:
        normalized = str(url or "").strip()
        if "/Home/GetObject?" in normalized:
            normalized = normalized.replace("/Home/GetObject?", "/Laws/MCL?")
        return normalized

    @staticmethod
    def _section_number_from_object_name(url: str) -> str:
        match = re.search(r"objectName=mcl-(\d+)-(\d+[a-z]?)\b", str(url or ""), flags=re.IGNORECASE)
        if not match:
            return ""
        return f"{match.group(1)}.{match.group(2)}"

    @staticmethod
    def _text_or_empty(node: object) -> str:
        if node is None:
            return ""
        try:
            return re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
        except Exception:
            return ""


# Register this scraper with the registry
StateScraperRegistry.register("MI", MichiganScraper)
