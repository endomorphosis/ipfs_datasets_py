import re
from typing import List, Dict, Optional
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class OhioScraper(BaseStateScraper):
    """Scraper for Ohio state laws from https://codes.ohio.gov"""
    _OH_TITLE_URL_RE = re.compile(r"/ohio-revised-code/title-(\d+)$", re.IGNORECASE)
    _OH_CHAPTER_URL_RE = re.compile(r"/ohio-revised-code/chapter-([0-9.]+)$", re.IGNORECASE)
    _OH_SECTION_URL_RE = re.compile(r"/ohio-revised-code/section-([0-9A-Za-z.]+)$", re.IGNORECASE)
    
    def get_base_url(self) -> str:
        """Return the base URL for Ohio's legislative website."""
        return "https://codes.ohio.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Ohio."""
        return [{
            "name": "Ohio Revised Code",
            "url": f"{self.get_base_url()}/ohio-revised-code",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Ohio's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        merged: List[NormalizedStatute] = []
        seen_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for row in items:
                key = str(row.statute_id or row.source_url or "").strip().lower()
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                merged.append(row)

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
            if direct:
                _merge(direct)

        official = await self._scrape_official_title_chapter_section_tree(
            code_name,
            max_statutes=max(10, int(limit or 10)),
        )
        if official:
            return official[: int(limit or len(official))]

        if merged:
            return merged[: int(limit or len(merged))]
        max_sections = limit if limit is not None else 1000000
        return await self._generic_scrape(
            code_name,
            code_url,
            "Ohio Rev. Code Ann.",
            max_sections=max_sections,
        )

    async def _scrape_official_title_chapter_section_tree(
        self,
        code_name: str,
        max_statutes: int,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        root_payload = await self._fetch_page_content_with_archival_fallback(
            f"{self.get_base_url()}/ohio-revised-code",
            timeout_seconds=20,
        )
        if not root_payload:
            return []
        root_soup = BeautifulSoup(root_payload, "html.parser")

        title_urls: List[str] = []
        seen_titles = set()
        for link in root_soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            abs_url = urljoin(f"{self.get_base_url()}/", href)
            if not self._OH_TITLE_URL_RE.search(abs_url):
                continue
            if abs_url in seen_titles:
                continue
            seen_titles.add(abs_url)
            title_urls.append(abs_url)

        statutes: List[NormalizedStatute] = []
        seen_sections = set()
        max_section_links = max_statutes * 5
        for title_url in title_urls:
            if len(statutes) >= max_statutes:
                break
            title_payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=20)
            if not title_payload:
                continue
            title_soup = BeautifulSoup(title_payload, "html.parser")
            chapter_urls: List[str] = []
            seen_chapters = set()
            for link in title_soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                abs_url = urljoin(title_url, href)
                if not self._OH_CHAPTER_URL_RE.search(abs_url):
                    continue
                if abs_url in seen_chapters:
                    continue
                seen_chapters.add(abs_url)
                chapter_urls.append(abs_url)

            for chapter_url in chapter_urls:
                if len(statutes) >= max_statutes or len(seen_sections) >= max_section_links:
                    break
                chapter_payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
                if not chapter_payload:
                    continue
                chapter_soup = BeautifulSoup(chapter_payload, "html.parser")
                for link in chapter_soup.find_all("a", href=True):
                    href = str(link.get("href") or "").strip()
                    abs_url = urljoin(chapter_url, href)
                    if not self._OH_SECTION_URL_RE.search(abs_url):
                        continue
                    if abs_url in seen_sections:
                        continue
                    seen_sections.add(abs_url)
                    statute = await self._build_official_section_statute(code_name, abs_url)
                    if statute is not None:
                        statutes.append(statute)
                        if len(statutes) >= max_statutes:
                            break
        return statutes

    async def _build_official_section_statute(
        self,
        code_name: str,
        source_url: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=20)
        if not payload:
            return None
        soup = BeautifulSoup(payload, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()
        heading = soup.find("h1")
        section_name = self._normalize_legal_text(heading.get_text(" ", strip=True) if heading else "")
        main = soup.find("main") or soup.find("body") or soup
        text = self._normalize_legal_text(main.get_text(" ", strip=True))
        match = self._OH_SECTION_URL_RE.search(source_url)
        section_number = match.group(1) if match else source_url.rsplit("section-", 1)[-1]
        start_idx = text.lower().find(f"section {section_number.lower()}")
        body = self._normalize_legal_text(text[start_idx:] if start_idx >= 0 else text)
        if len(body) < 180:
            return None
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name[:200] or f"Section {section_number}",
            full_text=body,
            legal_area=self._identify_legal_area(section_name or body),
            source_url=source_url,
            official_cite=f"Ohio Rev. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_ohio_revised_code_html",
                "discovery_method": "official_title_chapter_section",
                "skip_hydrate": True,
            },
        )

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
            f"{self.get_base_url()}/ohio-revised-code/section-1.01",
            f"{self.get_base_url()}/ohio-revised-code/section-2903.01",
        ]
        statutes: List[NormalizedStatute] = []
        limit = max_statutes if max_statutes is not None else len(section_urls)
        for source_url in section_urls[: max(1, int(limit))]:
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=12)
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            title = soup.find(["h1", "h2"])
            section_name = title.get_text(" ", strip=True) if title else ""
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            match = re.search(r"\bSection\s+(\d+[A-Za-z]?(?:\.\d+[A-Za-z]*)*)\b", text, re.IGNORECASE)
            section_number = match.group(1) if match else source_url.rsplit("section-", 1)[-1]
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
                    official_cite=f"Ohio Rev. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_direct_section", "skip_hydrate": True},
                )
            )
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("OH", OhioScraper)
