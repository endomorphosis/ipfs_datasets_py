"""Scraper for Massachusetts state laws.

This module contains the scraper for Massachusetts statutes from the official state
legislative website.
"""

from typing import List, Dict, Optional, Tuple
import urllib.request
import re
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class MassachusettsScraper(BaseStateScraper):
    """Scraper for Massachusetts state laws from https://malegislature.gov"""

    _MA_TITLE_LOAD_RE = re.compile(
        r"accordionAjaxLoad\(\s*'(?P<part>\d+)'\s*,\s*'(?P<title>\d+)'\s*,\s*'(?P<code>[^']*)'\s*\)",
        re.IGNORECASE,
    )
    _MA_CHAPTER_NUMBER_RE = re.compile(r"/chapter(?P<chapter>[a-z0-9.]+)$", re.IGNORECASE)
    _MA_SECTION_NUMBER_RE = re.compile(r"/section(?P<section>[a-z0-9.]+)$", re.IGNORECASE)
    _MA_SECTION_URL_RE = re.compile(
        r"/laws/generallaws/(?:part[a-z0-9-]*|title[a-z0-9-]*|chapter[a-z0-9-]*|section[a-z0-9-]*)(?:/|$)",
        re.IGNORECASE,
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Massachusetts's legislative website."""
        return "https://malegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Massachusetts."""
        return [{
            "name": "Massachusetts General Laws",
            "url": f"{self.get_base_url()}/Laws/GeneralLaws",
            "type": "Code"
        }]

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MA_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Massachusetts's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/Laws/GeneralLaws/PartI",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartII",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartIII",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartIV",
        ]

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        return_threshold = self._bounded_return_threshold(160)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct_sections = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
            if direct_sections:
                _merge(direct_sections)

        official_statutes = await self._scrape_official_general_laws_tree(
            code_name,
            max_statutes=max(10, return_threshold),
        )
        if official_statutes:
            return official_statutes[:return_threshold]

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "Mass. Gen. Laws",
                max_sections=max(10, return_threshold),
            )
            statutes = self._filter_section_level(statutes)
            _merge(statutes)
            if len(merged) >= return_threshold:
                return merged

        return merged

    async def _scrape_official_general_laws_tree(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        root_html = await self._request_text_direct(f"{self.get_base_url()}/Laws/GeneralLaws", timeout=20)
        if not root_html:
            return []

        root_soup = BeautifulSoup(root_html, "html.parser")
        part_links: List[str] = []
        seen_parts = set()
        for link in root_soup.find_all("a", href=True):
            href = str(link.get("href", "")).strip()
            if "/Laws/GeneralLaws/Part" not in href:
                continue
            abs_url = urljoin(self.get_base_url(), href)
            if abs_url in seen_parts:
                continue
            seen_parts.add(abs_url)
            part_links.append(abs_url)

        statutes: List[NormalizedStatute] = []
        seen_sections = set()
        for part_url in part_links:
            if len(statutes) >= max_statutes:
                break
            section_links = await self._discover_section_links_from_part(part_url, max_sections=max_statutes * 4)
            for section_url in section_links:
                if len(statutes) >= max_statutes:
                    break
                if section_url in seen_sections:
                    continue
                seen_sections.add(section_url)
                statute = await self._build_section_statute(code_name, section_url)
                if statute is not None:
                    statutes.append(statute)
        return statutes

    async def _discover_section_links_from_part(self, part_url: str, max_sections: int) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        part_html = await self._request_text_direct(part_url, timeout=20)
        if not part_html:
            return []

        title_specs = self._extract_title_specs(part_html)
        section_links: List[str] = []
        seen_chapters = set()
        seen_sections = set()
        for part_id, title_id, title_code in title_specs:
            if len(section_links) >= max_sections:
                break
            chapter_fragment = await self._request_text_direct(
                f"{self.get_base_url()}/Laws/GeneralLaws/GetChaptersForTitle?partId={part_id}&titleId={title_id}&code={title_code}",
                timeout=20,
            )
            if not chapter_fragment:
                continue
            chapter_soup = BeautifulSoup(chapter_fragment, "html.parser")
            for link in chapter_soup.find_all("a", href=True):
                href = str(link.get("href", "")).strip()
                if "/Laws/GeneralLaws/" not in href or "/Chapter" not in href:
                    continue
                chapter_url = urljoin(self.get_base_url(), href)
                if chapter_url in seen_chapters:
                    continue
                seen_chapters.add(chapter_url)
                chapter_html = await self._request_text_direct(chapter_url, timeout=20)
                if not chapter_html:
                    continue
                chapter_page = BeautifulSoup(chapter_html, "html.parser")
                for section_link in chapter_page.find_all("a", href=True):
                    raw_section_href = str(section_link.get("href", "")).strip()
                    if "/Laws/GeneralLaws/" not in raw_section_href or "/Section" not in raw_section_href:
                        continue
                    abs_section = urljoin(self.get_base_url(), raw_section_href)
                    if abs_section in seen_sections:
                        continue
                    seen_sections.add(abs_section)
                    section_links.append(abs_section)
                    if len(section_links) >= max_sections:
                        break
                if len(section_links) >= max_sections:
                    break
        return section_links

    def _extract_title_specs(self, html: str) -> List[Tuple[str, str, str]]:
        specs: List[Tuple[str, str, str]] = []
        seen = set()
        for match in self._MA_TITLE_LOAD_RE.finditer(html):
            item = (
                str(match.group("part") or "").strip(),
                str(match.group("title") or "").strip(),
                str(match.group("code") or "").strip(),
            )
            if not all(item) or item in seen:
                continue
            seen.add(item)
            specs.append(item)
        return specs

    async def _build_section_statute(self, code_name: str, section_url: str) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._request_text_direct(section_url, timeout=20)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")

        heading = soup.select_one("h2.genLawHeading")
        section_name = self._normalize_legal_text(heading.get_text(" ", strip=True)) if heading else ""
        body_chunks: List[str] = []
        for para in soup.find_all("p"):
            text = self._normalize_legal_text(para.get_text(" ", strip=True))
            if text:
                body_chunks.append(text)
        if not body_chunks:
            main = soup.select_one("main") or soup
            text = self._normalize_legal_text(main.get_text(" ", strip=True))
            if text:
                body_chunks.append(text)
        body = "\n".join(chunk for chunk in body_chunks if chunk)
        if len(body) < 80:
            return None

        chapter_match = self._MA_CHAPTER_NUMBER_RE.search(section_url)
        section_match = self._MA_SECTION_NUMBER_RE.search(section_url)
        chapter_number = chapter_match.group("chapter") if chapter_match else ""
        section_number = section_match.group("section") if section_match else ""
        statute_id = f"{code_name} ch. {chapter_number} § {section_number}".strip()
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=statute_id,
            code_name=code_name,
            chapter_number=chapter_number,
            section_number=section_number,
            section_name=section_name[:200] if section_name else f"Section {section_number}",
            full_text=body,
            legal_area=self._identify_legal_area(section_name or body),
            source_url=section_url,
            official_cite=f"Mass. Gen. Laws ch. {chapter_number}, § {section_number}",
            structured_data={
                "source_kind": "official_massachusetts_general_laws_html",
                "discovery_method": "official_part_title_chapter_section",
                "skip_hydrate": True,
            },
        )

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 2) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("1", "Citizens of commonwealth defined", f"{self.get_base_url()}/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section1"),
            ("2", "Jurisdiction", f"{self.get_base_url()}/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section2"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, fallback_name, source_url in seeds[: max(1, int(max_statutes or 1))]:
            html = await self._request_text_direct(source_url, timeout=18)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            heading = soup.select_one("h2.genLawHeading")
            section_name = self._normalize_legal_text(heading.get_text(" ", strip=True)) if heading else fallback_name
            body = ""
            for para in soup.find_all("p"):
                text = self._normalize_legal_text(para.get_text(" ", strip=True))
                if text.lower().startswith(f"section {section_number.lower()}."):
                    body = text
                    break
            if not body:
                main = soup.select_one("main") or soup
                body = self._normalize_legal_text(main.get_text(" ", strip=True))
            if len(body) < 60:
                continue
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} ch. 1 § {section_number}",
                    code_name=code_name,
                    chapter_number="1",
                    chapter_name="JURISDICTION OF THE COMMONWEALTH AND OF THE UNITED STATES",
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=body,
                    legal_area=self._identify_legal_area(section_name or body),
                    source_url=source_url,
                    official_cite=f"Mass. Gen. Laws ch. 1, § {section_number}",
                    structured_data={
                        "source_kind": "official_massachusetts_general_laws_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        def _request() -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            import asyncio

            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""


# Register this scraper with the registry
StateScraperRegistry.register("MA", MassachusettsScraper)
