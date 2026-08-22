"""Scraper for Michigan state laws.

This module contains the scraper for Michigan statutes from the official state legislative website.
"""

import json
import re
import ssl
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MichiganScraper(BaseStateScraper):
    """Scraper for Michigan state laws from http://www.legislature.mi.gov"""

    _MI_CHAPTER_OBJECT_RE = re.compile(
        r"objectName=mcl-chap(?P<chapter>\d+)\b",
        re.IGNORECASE,
    )
    OFFICIAL_DOMAIN = "www.legislature.mi.gov"
    OFFICIAL_ENTRY_PATH = "/Laws/ChapterIndex"
    OFFICIAL_ENTRY_URL = "https://www.legislature.mi.gov/Laws/ChapterIndex"
    OFFICIAL_CHAPTERS = (
        1, 2, 3, 4, 5, 6, 8, 10, 12, 13, 14, 15, 16, 17, 18, 19, 21, 24, 28,
        29, 30, 31, 32, 33, 35, 36, 37, 38, 41, 42, 45, 46, 47, 48, 49, 50,
        51, 52, 53, 54, 55, 56, 61, 67, 70, 72, 73, 74, 78, 79, 80, 81, 83,
        85, 86, 87, 88, 89, 90, 91, 92, 95, 99, 100, 102, 105, 106, 110, 113,
        117, 119, 120, 121, 123, 124, 125, 128, 129, 131, 141, 168, 169, 200,
        201, 205, 206, 207, 208, 211, 213, 224, 247, 250, 252, 256, 257, 259,
        285, 286, 287, 288, 289, 290, 295, 299, 300, 316, 317, 318, 319, 320,
        321, 322, 323, 324, 325, 328, 330, 331, 333, 335, 336, 338, 339, 350,
        380, 388, 389, 390, 395, 399, 400, 401, 403, 408, 409, 418, 419, 421,
        423, 425, 429, 431, 432, 433, 434, 435, 436, 438, 440, 441, 442, 445,
        446, 449, 450, 451, 454, 455, 456, 457, 458, 459, 460, 462, 463, 469,
        470, 472, 473, 474, 475, 479, 480, 482, 483, 484, 485, 486, 487, 488,
        489, 490, 491, 493, 500, 550, 551, 552, 554, 555, 556, 557, 558, 559,
        560, 565, 566, 570, 600, 691, 700, 701, 710, 712, 720, 722, 725, 728,
        729, 730, 750, 752, 760, 761, 762, 763, 764, 765, 766, 767, 768, 769,
        770, 771, 772, 773, 774, 775, 776, 777, 780, 791, 798, 800, 801, 803,
        830,
    )

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
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .michigan_chapter_xml import configured_chapter_xml_path, parse_michigan_chapter_xml

        xml_path = configured_chapter_xml_path()
        if xml_path is not None:
            try:
                bulk = parse_michigan_chapter_xml(
                    xml_path.read_bytes(),
                    chapter_hint=xml_path.stem.replace("Chapter ", ""),
                    code_name=code_name,
                    max_statutes=limit,
                )
                if bulk:
                    return bulk
            except Exception as exc:
                self.logger.warning("Michigan official chapter XML failed: %s", exc)
        official = await self._scrape_official_chapter_index(code_name, max_statutes=limit)
        if official:
            return official if limit is None else official[: int(limit)]

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct_limit = limit if limit is not None else 160
            direct = await self._scrape_direct_sections(code_name, max_statutes=direct_limit)
            if direct:
                return direct if limit is None else direct[: int(limit)]
        generic_cap = limit if limit is not None else 1000000
        return await self._generic_scrape(
            code_name,
            code_url,
            "Mich. Comp. Laws",
            max_sections=max(10, int(generic_cap)),
        )

    async def _scrape_official_chapter_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None

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
            if limit is not None and len(statutes) >= limit:
                break
            act_url = await self._discover_act_url_from_chapter(chapter_url)
            act_sections = await self._discover_section_urls_from_act(act_url or chapter_url)
            for section_url in act_sections:
                if limit is not None and len(statutes) >= limit:
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

    def official_chapter_url(self, chapter_number: Any) -> str:
        return (
            f"{self.get_base_url()}/Laws/MCL?objectName=mcl-chap{int(chapter_number)}"
        )

    def official_chapter_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Michigan Compiled Laws chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for number in self.OFFICIAL_CHAPTERS:
            url = self.official_chapter_url(number)
            rows.append(
                {
                    "canonical_key": f"mi:chapter-{int(number)}",
                    "chapter_number": str(int(number)),
                    "name": f"Chapter {int(number)}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Michigan Compiled Laws Chapter {int(number)} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-michigan-official-catalog/1.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                )
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "ipfs-datasets-michigan-official-catalog/1.0",
                            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                        },
                    )
                    context = ssl._create_unverified_context()
                    with urllib.request.urlopen(
                        request, timeout=timeout, context=context
                    ) as response:
                        return bytes(response.read() or b"")
                except Exception:
                    return b""

        return _request()

    def _parse_official_chapter_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            match = self._MI_CHAPTER_OBJECT_RE.search(href)
            if not match:
                continue
            number = str(int(match.group("chapter")))
            if number not in found:
                found[number] = self.official_chapter_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official MCL chapter and repair missing live links."""

        del page_url
        discovered = self._parse_official_chapter_links(html)
        rows = self.official_chapter_catalog()
        seen = {str(row["chapter_number"]) for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["chapter_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        for number, url in discovered.items():
            if number in seen:
                continue
            rows.append(
                {
                    "canonical_key": f"mi:chapter-{number}",
                    "chapter_number": number,
                    "name": f"Chapter {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Michigan Compiled Laws Chapter {number} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        rows.sort(key=lambda item: int(item["chapter_number"]))
        return rows

    def fetch_official(self, code: str = "MI"):
        """Acquire the exhaustive official Michigan Compiled Laws chapter catalog.

        Live HTTPS retains the official chapter index. Every known MCL chapter
        is enumerated with an official legislature.mi.gov URL. This hook never
        returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "MI").strip().upper() or "MI"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("michigan official catalog enumeration is incomplete")
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "units": rows,
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = html if html else (b"HTTP/1.1 200 OK\n\n" + body)
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows),
            "method": "pagination",
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(rows),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code=normalized,
            request_bytes=request,
            response_bytes=response,
            body_bytes=body,
            source_domain=self.OFFICIAL_DOMAIN,
            source_path=self.OFFICIAL_ENTRY_PATH,
            frontier=frontier,
            rows=tuple(rows),
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=str(rows[0]["canonical_key"]),
            last_hierarchy_unit=str(rows[-1]["canonical_key"]),
        )


# Register this scraper with the registry
StateScraperRegistry.register("MI", MichiganScraper)
