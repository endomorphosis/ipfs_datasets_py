"""Florida state law scraper.

Scrapes laws from the Florida Legislature website
(http://www.leg.state.fl.us/).
"""

from typing import List, Dict, Optional, Tuple
import re
from urllib.parse import urljoin

from ipfs_datasets_py.utils import anyio_compat as asyncio
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class FloridaScraper(BaseStateScraper):
    """Scraper for Florida state laws."""

    _TITLE_INDEX_RE = re.compile(r"App_mode=Display_Index&Title_Request=", re.IGNORECASE)
    _CHAPTER_CONTENTS_RE = re.compile(r"URL=([0-9]{4}-[0-9]{4}/[0-9]{4}/[0-9]{4})ContentsIndex\.html", re.IGNORECASE)
    
    def get_base_url(self) -> str:
        """Get base URL for Florida statutes."""
        return "http://www.leg.state.fl.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of Florida statutes."""
        base_url = self.get_base_url()
        
        codes = [
            {"name": "Florida Statutes", "url": f"{base_url}/Statutes/", "type": "FS"},
        ]
        
        return codes
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Florida statutes directly from official title/chapter indexes."""
        limit = max(1, int(max_statutes)) if max_statutes else None
        statutes: List[NormalizedStatute] = []
        title_links = await self._discover_title_links(code_url)
        self.logger.info("Florida official index: discovered %s title links", len(title_links))

        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "Florida official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                title_label or title_url,
                title_index,
                len(title_links),
                len(chapter_links),
                len(statutes),
            )
            for chapter_url, chapter_label in chapter_links:
                if limit is not None and len(statutes) >= limit:
                    break
                remaining = None if limit is None else max(0, limit - len(statutes))
                statutes.extend(
                    await self._parse_chapter_sections(
                        code_name=code_name,
                        chapter_url=chapter_url,
                        chapter_label=chapter_label,
                        max_statutes=remaining,
                    )
                )

        if not statutes:
            self.logger.warning("Florida official direct crawl returned no statutes; skipping generic recovery fallback")
        return statutes[:limit] if limit is not None else statutes

    async def _fetch_official_fl_html(self, url: str, timeout_seconds: int = 12) -> str:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached.decode("utf-8", errors="replace")

        timeout = max(1, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-florida-statutes-scraper/2.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                    timeout=(min(5, timeout), timeout),
                )
                if int(response.status_code or 0) != 200:
                    return b""
                return bytes(response.content or b"")
            except Exception:
                return b""

        try:
            payload = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except TimeoutError:
            payload = b""

        self._record_fetch_event(provider="requests_direct", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(url=url, payload=payload, provider="requests_direct")
            return payload.decode("utf-8", errors="replace")
        return ""

    async def _discover_title_links(self, code_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = code_url or f"{self.get_base_url()}/Statutes/"
        html = await self._fetch_official_fl_html(index_url)
        if not html and index_url.startswith("http://"):
            index_url = index_url.replace("http://", "https://", 1)
            html = await self._fetch_official_fl_html(index_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if not self._TITLE_INDEX_RE.search(href):
                continue
            full_url = urljoin(index_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((full_url, label or full_url.rsplit("Title_Request=", 1)[-1]))
        return out

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_fl_html(title_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            match = self._CHAPTER_CONTENTS_RE.search(href)
            if not match:
                continue
            chapter_path = f"{match.group(1)}.html"
            chapter_url = urljoin(title_url, f"index.cfm?App_mode=Display_Statute&URL={chapter_path}")
            if chapter_url in seen:
                continue
            seen.add(chapter_url)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((chapter_url, label or chapter_path))
        return out

    async def _parse_chapter_sections(
        self,
        *,
        code_name: str,
        chapter_url: str,
        chapter_label: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_fl_html(chapter_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        title_number = self._text_or_empty(soup.select_one(".TitleNumber"))
        title_name = self._text_or_empty(soup.select_one(".TitleName"))
        chapter_number = self._text_or_empty(soup.select_one(".ChapterNumber")) or self._chapter_number_from_url(chapter_url)
        chapter_name = self._text_or_empty(soup.select_one(".ChapterName")) or chapter_label

        statutes: List[NormalizedStatute] = []
        for section in soup.select(".Section"):
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            section_number = self._text_or_empty(section.select_one(".SectionNumber"))
            section_name = self._text_or_empty(section.select_one(".Catchline"))
            if not section_number:
                head_text = self._normalize_legal_text(section.get_text(" ", strip=True))
                match = re.match(r"([0-9]+\.[0-9A-Za-z]+)\s+(.+?)\s+[—-]\s+", head_text)
                if match:
                    section_number = match.group(1)
                    section_name = match.group(2)
            full_text = self._normalize_legal_text(section.get_text(" ", strip=True))
            if not section_number or len(full_text) < 80:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"FL-{section_number}",
                    code_name=code_name,
                    title_number=title_number or None,
                    title_name=title_name or None,
                    chapter_number=chapter_number or None,
                    chapter_name=chapter_name or None,
                    section_number=section_number,
                    section_name=section_name[:200] if section_name else f"Section {section_number}",
                    short_title=section_name[:200] if section_name else None,
                    full_text=full_text,
                    legal_area=self._identify_legal_area(section_name or chapter_name or code_name),
                    source_url=self._section_url(chapter_url, section_number),
                    official_cite=f"Fla. Stat. § {section_number}",
                    structured_data={
                        "source_kind": "official_florida_statutes_html",
                        "discovery_method": "official_title_chapter_index",
                        "chapter_url": chapter_url,
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    @staticmethod
    def _text_or_empty(node: object) -> str:
        if node is None:
            return ""
        try:
            return re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _chapter_number_from_url(url: str) -> str:
        match = re.search(r"/([0-9]{4})/\\1\.html", str(url or ""))
        return match.group(1).lstrip("0") if match else ""

    @staticmethod
    def _section_url(chapter_url: str, section_number: str) -> str:
        padded = section_number
        if re.match(r"^\d+\.", padded):
            chapter = padded.split(".", 1)[0].zfill(4)
            padded_section = f"{chapter}.{padded.split('.', 1)[1]}"
            base = re.sub(r"/[0-9]{4}\.html.*$", f"/Sections/{padded_section}.html", chapter_url)
            if base != chapter_url:
                return base
        return chapter_url


# Register the scraper
StateScraperRegistry.register("FL", FloridaScraper)
