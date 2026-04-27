"""Scraper for Connecticut state laws.

This module contains the scraper for Connecticut statutes from the official state legislative website.
"""

from ipfs_datasets_py.utils import anyio_compat as asyncio
import json
import re
import ssl
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup, Tag
from typing import List, Dict, Optional
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class ConnecticutScraper(BaseStateScraper):
    """Scraper for Connecticut state laws from https://www.cga.ct.gov"""

    _CHAPTER_LINK_RE = re.compile(r"chap_[0-9a-z]+\.htm$", re.IGNORECASE)
    _TITLE_LINK_RE = re.compile(r"title_[0-9a-z]+\.htm$", re.IGNORECASE)
    
    def get_base_url(self) -> str:
        """Return the base URL for Connecticut's legislative website."""
        return "https://www.cga.ct.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Connecticut."""
        return [{
            "name": "Connecticut General Statutes",
            # Live endpoint currently fails SSL verification in several runtime
            # environments; seed from a stable archive snapshot instead.
            "url": "http://web.archive.org/web/20250101000000/http://www.cga.ct.gov/current/pub/titles.htm",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Connecticut's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=30)
        return_threshold = limit if limit is not None else 1000000
        direct_sections: List[NormalizedStatute] = []

        live_stubs = await self._scrape_live_title_stubs(code_name, max_statutes=max(10, return_threshold))

        archival_stubs = await self._scrape_archived_chapter_stubs(code_name, max_statutes=max(10, return_threshold))

        candidate_urls = [
            code_url,
            "https://www.cga.ct.gov/current/pub/titles.htm",
            "https://law.justia.com/codes/connecticut/",
            "http://web.archive.org/web/20250101000000/https://law.justia.com/codes/connecticut/",
        ]

        best: List[NormalizedStatute] = []
        seen = set()
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._custom_scrape_connecticut(
                code_name,
                candidate,
                "Conn. Gen. Stat.",
                max_sections=return_threshold,
            )
            if len(statutes) > len(best):
                best = statutes
            if len(statutes) >= return_threshold:
                return statutes

            generic = await self._generic_scrape(
                code_name,
                candidate,
                "Conn. Gen. Stat.",
                max_sections=return_threshold if limit is not None else 260,
            )
            if len(generic) > len(best):
                best = generic
            if len(generic) >= return_threshold:
                return generic

        if not self._full_corpus_enabled():
            direct_sections = await self._scrape_direct_chapters(code_name, max_statutes=return_threshold)

        if len(live_stubs) > len(best):
            best = live_stubs

        if len(archival_stubs) > len(best):
            best = archival_stubs

        if direct_sections and len(direct_sections) > len(best):
            best = direct_sections

        return best

    async def _scrape_direct_chapters(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        """Fetch official CGA chapter pages directly, tolerating their TLS chain."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        chapter_urls = [
            "https://www.cga.ct.gov/current/pub/chap_001.htm",
            "https://www.cga.ct.gov/current/pub/chap_002.htm",
        ]
        out: List[NormalizedStatute] = []
        context = ssl._create_unverified_context()
        for source_url in chapter_urls[: max(1, int(max_statutes or 1))]:
            try:
                req = urllib.request.Request(source_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=12, context=context) as resp:
                    payload = resp.read()
            except Exception:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 280:
                continue
            title = text.split(" Table of Contents", 1)[0][:200] or "Connecticut General Statutes"
            chapter_match = re.search(r"\bChapter\s+([0-9A-Za-z]+)\b", text, re.IGNORECASE)
            chapter = chapter_match.group(1) if chapter_match else str(len(out) + 1)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § Chapter {chapter}",
                    code_name=code_name,
                    section_number=f"Chapter {chapter}",
                    section_name=title,
                    full_text=text[:14000],
                    source_url=source_url,
                    legal_area=self._identify_legal_area(title),
                    official_cite=f"Conn. Gen. Stat. ch. {chapter}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_direct_chapter", "skip_hydrate": True},
                )
            )
        return out

    async def _scrape_live_title_stubs(self, code_name: str, max_statutes: int = 120) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError:
            return []

        url = "https://www.cga.ct.gov/current/pub/titles.htm"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=35)
            if not payload:
                return []
        except Exception:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        out: List[NormalizedStatute] = []
        seen = set()
        for a in soup.find_all("a", href=True):
            if len(out) >= max_statutes:
                break
            href = str(a.get("href") or "").strip()
            text = str(a.get_text(" ", strip=True) or "").strip()
            if not href or not text:
                continue
            if "chap" not in href.lower() and "title" not in text.lower() and "chapter" not in text.lower():
                continue
            full_url = urljoin(url, href)
            section_number = self._extract_section_number(text) or str(len(out) + 1)
            key = section_number.lower()
            if key in seen:
                continue
            seen.add(key)

            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=text[:200],
                    full_text=f"Connecticut General Statutes {text}: {full_url}",
                    source_url=full_url,
                    legal_area=self._identify_legal_area(text),
                    official_cite=f"Conn. Gen. Stat. {section_number}",
                    metadata=StatuteMetadata(),
                )
            )
        return out

    async def _scrape_archived_chapter_stubs(self, code_name: str, max_statutes: int = 120) -> List[NormalizedStatute]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx?url=www.cga.ct.gov/current/pub/*"
            "&output=json&filter=statuscode:200&collapse=digest"
            f"&limit={max(1, int(max_statutes) * 6)}"
        )
        try:
            req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                rows = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception:
            return []

        if not isinstance(rows, list) or len(rows) < 2:
            return []

        out: List[NormalizedStatute] = []
        seen = set()
        for row in rows[1:]:
            if len(out) >= max_statutes:
                break
            if not isinstance(row, list) or len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue

            m = re.search(r"/(?:chap|chapter)([0-9A-Za-z]+)\.(?:htm|html)$", original, flags=re.IGNORECASE)
            chapter = m.group(1) if m else ""
            if not chapter:
                continue
            key = chapter.lower()
            if key in seen:
                continue
            seen.add(key)

            encoded = urllib.parse.quote(original, safe=':/?=&%.-_')
            source_url = f"https://web.archive.org/web/{ts}/{encoded}"
            title = f"Chapter {chapter}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {chapter}",
                    code_name=code_name,
                    section_number=chapter,
                    section_name=title,
                    full_text=f"Connecticut General Statutes {title}: {source_url}",
                    source_url=source_url,
                    legal_area=self._identify_legal_area(title),
                    official_cite=f"Conn. Gen. Stat. ch. {chapter}",
                    metadata=StatuteMetadata(),
                )
            )

        return out
    
    async def _custom_scrape_connecticut(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Connecticut's legislative website.
        
        Connecticut organizes statutes by titles with chapters underneath.
        """
        try:
            chapter_urls = await self._discover_chapter_urls(code_url, limit=max(max_sections * 3, 20))
            statutes: List[NormalizedStatute] = []
            seen_sections: set[str] = set()
            for chapter_url in chapter_urls:
                if len(statutes) >= max_sections:
                    break
                chapter_statutes = await self._extract_chapter_sections(
                    code_name=code_name,
                    chapter_url=chapter_url,
                    citation_format=citation_format,
                )
                for statute in chapter_statutes:
                    section_number = str(statute.section_number or "").strip().lower()
                    if not section_number or section_number in seen_sections:
                        continue
                    seen_sections.add(section_number)
                    statutes.append(statute)
                    if len(statutes) >= max_sections:
                        break

            self.logger.info(f"Connecticut custom scraper: Scraped {len(statutes)} sections")
            
            # Fallback to generic scraper if no data found
            if not statutes:
                self.logger.info("Connecticut custom scraper found no data, falling back to generic scraper")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            
        except Exception as e:
            self.logger.error(f"Connecticut custom scraper failed: {e}")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        return statutes

    async def _discover_chapter_urls(self, code_url: str, limit: int = 120) -> List[str]:
        payload = await self._fetch_connecticut_page(code_url, timeout_seconds=35)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        seen: set[str] = set()
        title_urls: List[str] = []
        out: List[str] = []

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urllib.parse.urljoin(code_url, href)
            parsed = urllib.parse.urlparse(absolute)
            if self._CHAPTER_LINK_RE.search(parsed.path):
                if absolute in seen:
                    continue
                seen.add(absolute)
                out.append(absolute)
                if len(out) >= limit:
                    break
            elif self._TITLE_LINK_RE.search(parsed.path):
                if absolute not in title_urls:
                    title_urls.append(absolute)

        for title_url in title_urls:
            if len(out) >= limit:
                break
            title_payload = await self._fetch_connecticut_page(title_url, timeout_seconds=35)
            if not title_payload:
                continue
            title_soup = BeautifulSoup(title_payload, "html.parser")
            for link in title_soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                if not href:
                    continue
                absolute = urllib.parse.urljoin(title_url, href)
                parsed = urllib.parse.urlparse(absolute)
                if not self._CHAPTER_LINK_RE.search(parsed.path):
                    continue
                if absolute in seen:
                    continue
                seen.add(absolute)
                out.append(absolute)
                if len(out) >= limit:
                    break
        return out

    async def _extract_chapter_sections(
        self,
        code_name: str,
        chapter_url: str,
        citation_format: str,
    ) -> List[NormalizedStatute]:
        payload = await self._fetch_connecticut_page(chapter_url, timeout_seconds=35)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        chapter_title = ""
        title_node = soup.find("title")
        if title_node:
            chapter_title = re.sub(r"\s+", " ", title_node.get_text(" ", strip=True)).strip()

        sections: List[NormalizedStatute] = []
        for catchln in soup.select("span.catchln[id^='sec_']"):
            section_number = self._extract_section_number(catchln.get_text(" ", strip=True))
            if not section_number:
                continue
            section_name = self._extract_connecticut_section_name(catchln.get_text(" ", strip=True), section_number)
            full_text = self._collect_connecticut_section_text(catchln)
            normalized = self._normalize_legal_text(full_text)
            if len(normalized) < 120:
                continue
            sections.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=(section_name or chapter_title or f"Section {section_number}")[:240],
                    full_text=normalized[:24000],
                    legal_area=self._identify_legal_area(f"{chapter_title} {section_name}"),
                    source_url=f"{chapter_url}#sec_{section_number.lower()}",
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_connecticut_chapter_html",
                        "discovery_method": "official_title_chapter_section_html",
                        "chapter_url": chapter_url,
                    },
                )
            )
        return sections

    def _extract_connecticut_section_name(self, heading: str, section_number: str) -> str:
        heading_text = re.sub(r"\s+", " ", str(heading or "").strip())
        match = re.match(
            rf"Sec\.\s*{re.escape(section_number)}\.\s*(.+)$",
            heading_text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(" .")
        return heading_text[:240]

    def _collect_connecticut_section_text(self, catchln: Tag) -> str:
        parent = catchln.parent
        if parent is None:
            return catchln.get_text(" ", strip=True)

        pieces: List[str] = []
        node = parent
        while isinstance(node, Tag):
            if node.name == "table" and "nav_tbl" in (node.get("class") or []):
                break
            if node.name == "hr":
                break
            text = node.get_text(" ", strip=True)
            if text:
                pieces.append(text)
            node = node.find_next_sibling()
        return "\n".join(pieces)

    async def _fetch_connecticut_page(self, url: str, timeout_seconds: int = 35) -> bytes:
        def _direct_fetch() -> bytes:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(req, timeout=timeout_seconds, context=context) as resp:
                    return bytes(resp.read() or b"")
            except Exception:
                return b""

        try:
            direct = await asyncio.wait_for(asyncio.to_thread(_direct_fetch), timeout=timeout_seconds + 2)
        except Exception:
            direct = b""
        if direct:
            return direct
        return await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=timeout_seconds)


# Register this scraper with the registry
StateScraperRegistry.register("CT", ConnecticutScraper)
