"""Scraper for Utah state laws.

This module contains the scraper for Utah statutes from the official state legislative website.
"""

import re
from typing import List, Dict, Optional
from urllib.parse import urljoin
from urllib.parse import quote
from urllib.parse import urlparse, parse_qs
from xml.etree import ElementTree as ET
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class UtahScraper(BaseStateScraper):
    """Scraper for Utah state laws from https://le.utah.gov"""
    _UT_VERSION_DEFAULT_RE = re.compile(r"var\s+versionDefault\s*=\s*['\"]([^'\"]*)['\"]", re.IGNORECASE)
    _UT_TITLE_WRAPPER_RE = re.compile(r"/xcode/title[0-9a-z]+/[0-9a-z]+\.html$", re.IGNORECASE)
    _UT_SECTION_LINK_RE = re.compile(r"/xcode/title[0-9a-z]+/chapter[0-9a-z]+/[0-9a-z-]+-s[0-9a-z.]+\.html", re.IGNORECASE)
    _UT_PART_LINK_RE = re.compile(r"/xcode/title[0-9a-z]+/chapter[0-9a-z]+/[0-9a-z-]+-p[0-9a-z.]+\.html", re.IGNORECASE)
    _UT_CHAPTER_LINK_RE = re.compile(r"/xcode/title[0-9a-z]+/chapter[0-9a-z]+/[0-9a-z-]+\.html", re.IGNORECASE)
    _UT_CHAPTER_RE = re.compile(
        r"Chapter\s+([0-9]+[A-Za-z]?)\s+(.+?)(?=\s+Chapter\s+[0-9]+[A-Za-z]?\s+|\s+<< Previous Title|\s+Download Options|$)",
        re.IGNORECASE,
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Utah's legislative website."""
        return "https://le.utah.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Utah."""
        return [{
            "name": "Utah Code",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Utah's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._bounded_return_threshold(40)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))

        xml_sections = await self._scrape_official_xml_code_tree(
            code_name,
            max_statutes=max(10, return_threshold),
        )
        if xml_sections:
            return xml_sections[:return_threshold]

        official_sections = await self._scrape_official_versioned_tree(
            code_name,
            max_statutes=max(10, return_threshold),
        )
        if official_sections:
            return official_sections[:return_threshold]

        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
            if direct:
                return direct[:return_threshold]

        live_title_stubs = await self._scrape_live_title_stubs(code_name, max_statutes=max(10, return_threshold))
        live_chapter_stubs = await self._scrape_live_chapter_stubs(
            code_name,
            title_limit=max(1, min(12, return_threshold)),
            per_title_limit=max(1, min(10, return_threshold)),
        )

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/xcode/code.html",
            f"{self.get_base_url()}/xcode/",
            f"{self.get_base_url()}/xcode/Title01/",
            "https://law.justia.com/codes/utah/",
            "https://web.archive.org/web/20250101000000/https://law.justia.com/codes/utah/",
        ]
        for archived in await self._discover_archived_title_urls(limit=max(10, return_threshold)):
            if archived not in candidate_urls:
                candidate_urls.append(archived)

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

        _merge(live_title_stubs)
        _merge(live_chapter_stubs)
        if len(merged) >= return_threshold:
            return merged

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(code_name, candidate, "Utah Code Ann.", max_sections=return_threshold)
            _merge(statutes)
            if len(merged) >= return_threshold:
                return merged

        return merged

    async def _scrape_official_xml_code_tree(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        root_xml_url = await self._resolve_root_versioned_xml_url()
        if not root_xml_url:
            return []

        xml_text = await self._fetch_text_with_archival(root_xml_url, timeout=35)
        if not xml_text:
            return []

        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return []

        statutes: List[NormalizedStatute] = []
        title_nodes = root.findall(".//title") if root.tag != "title" else [root]
        for title_node in title_nodes:
            title_number = str(title_node.attrib.get("number") or "").strip()
            title_name = self._normalize_legal_text(title_node.findtext("catchline", default=""))
            for chapter_node in title_node.findall(".//chapter"):
                chapter_number = str(chapter_node.attrib.get("number") or "").strip()
                chapter_name = self._normalize_legal_text(chapter_node.findtext("catchline", default=""))
                for section_node in chapter_node.findall(".//section"):
                    if len(statutes) >= max_statutes:
                        return statutes
                    statute = self._build_official_section_from_xml_node(
                        code_name=code_name,
                        root_xml_url=root_xml_url,
                        title_number=title_number,
                        title_name=title_name,
                        chapter_number=chapter_number,
                        chapter_name=chapter_name,
                        section_node=section_node,
                    )
                    if statute is not None:
                        statutes.append(statute)
        return statutes

    async def _resolve_root_versioned_xml_url(self) -> Optional[str]:
        wrapper_url = f"{self.get_base_url()}/xcode/code.html"
        wrapper_html = await self._fetch_text_with_archival(wrapper_url, timeout=25)
        if not wrapper_html:
            return None
        versioned_html_url = self._resolve_versioned_content_url(wrapper_url, wrapper_html)
        if not versioned_html_url:
            return None
        if versioned_html_url.lower().endswith(".html"):
            return versioned_html_url[:-5] + ".xml"
        return None

    def _build_official_section_from_xml_node(
        self,
        *,
        code_name: str,
        root_xml_url: str,
        title_number: str,
        title_name: str,
        chapter_number: str,
        chapter_name: str,
        section_node: ET.Element,
    ) -> Optional[NormalizedStatute]:
        section_number = str(section_node.attrib.get("number") or "").strip()
        if not section_number:
            return None

        section_name = self._normalize_legal_text(section_node.findtext("catchline", default=""))
        body = self._normalize_legal_text(" ".join(text.strip() for text in section_node.itertext() if str(text or "").strip()))
        if len(body) < 120:
            return None

        source_url = root_xml_url
        version_hint = urlparse(root_xml_url).path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if title_number and version_hint:
            source_url = f"{self.get_base_url()}/xcode/Title{title_number}/{version_hint}.xml"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=title_number or None,
            title_name=title_name or None,
            chapter_number=chapter_number or None,
            chapter_name=chapter_name or None,
            section_number=section_number,
            section_name=section_name[:220] or f"Section {section_number}",
            full_text=body[:20000],
            source_url=source_url,
            legal_area=self._identify_legal_area(f"{title_name} {chapter_name} {section_name} {body[:1200]}"),
            official_cite=f"Utah Code § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_utah_code_xml",
                "discovery_method": "official_root_xml_title_chapter_section",
                "skip_hydrate": True,
            },
        )

    async def _scrape_official_versioned_tree(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        statutes: List[NormalizedStatute] = []
        seen_titles = set()
        seen_sections = set()
        title_queue = [f"{self.get_base_url()}/xcode/Title1/1.html"]

        while title_queue and len(statutes) < max_statutes:
            title_wrapper_url = title_queue.pop(0)
            if title_wrapper_url in seen_titles:
                continue
            seen_titles.add(title_wrapper_url)

            title_wrapper_html = await self._fetch_text_with_archival(title_wrapper_url, timeout=25)
            if not title_wrapper_html:
                continue
            title_versioned_url = self._resolve_versioned_content_url(title_wrapper_url, title_wrapper_html)
            if not title_versioned_url:
                continue
            title_content_html = await self._fetch_text_with_archival(title_versioned_url, timeout=25)
            if not title_content_html:
                continue
            title_soup = BeautifulSoup(title_content_html, "html.parser")

            for link in title_soup.find_all("a", href=True):
                if len(statutes) >= max_statutes:
                    break
                href = str(link.get("href") or "").strip()
                abs_url = urljoin(title_versioned_url, href)
                lower = abs_url.lower()

                if self._UT_TITLE_WRAPPER_RE.search(lower):
                    if abs_url not in seen_titles and abs_url not in title_queue:
                        title_queue.append(abs_url)
                    continue

                if not self._UT_CHAPTER_LINK_RE.search(lower):
                    continue

                chapter_versioned_url = self._resolve_versioned_link(abs_url)
                if not chapter_versioned_url:
                    chapter_wrapper_html = await self._fetch_text_with_archival(abs_url, timeout=25)
                    chapter_versioned_url = self._resolve_versioned_content_url(abs_url, chapter_wrapper_html)
                if not chapter_versioned_url:
                    continue
                section_urls = await self._discover_section_urls_from_versioned_container(chapter_versioned_url)
                for section_url in section_urls:
                    if len(statutes) >= max_statutes:
                        break
                    if section_url in seen_sections:
                        continue
                    seen_sections.add(section_url)
                    statute = await self._build_official_section_from_versioned_url(code_name, section_url)
                    if statute is not None:
                        statutes.append(statute)

        if statutes:
            return statutes

        # Utah's live title wrappers are inconsistent: some titles publish a versioned
        # container tree, while others leave the wrapper empty. When the global title
        # crawl cannot bootstrap, fall back to known current official containers that
        # still produce real section-level rows.
        seed_containers = [
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5-P2_1800010118000101.html",
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5-P1_1800010118000101.html",
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5_2022050420220504.html",
        ]
        for container_url in seed_containers:
            if len(statutes) >= max_statutes:
                break
            section_urls = await self._discover_section_urls_from_versioned_container(container_url)
            for section_url in section_urls:
                if len(statutes) >= max_statutes:
                    break
                if section_url in seen_sections:
                    continue
                seen_sections.add(section_url)
                statute = await self._build_official_section_from_versioned_url(code_name, section_url)
                if statute is not None:
                    statutes.append(statute)

        return statutes

    async def _discover_section_urls_from_versioned_container(self, versioned_url: str) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_text_with_archival(versioned_url, timeout=25)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        urls: List[str] = []
        seen = set()

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            abs_url = urljoin(versioned_url, href)
            lower = abs_url.lower()
            candidate = self._resolve_versioned_link(abs_url)

            if self._UT_SECTION_LINK_RE.search(lower):
                if candidate and candidate not in seen:
                    seen.add(candidate)
                    urls.append(candidate)
                continue

            if self._UT_PART_LINK_RE.search(lower):
                part_versioned_url = candidate
                if not part_versioned_url:
                    part_wrapper_html = await self._fetch_text_with_archival(abs_url, timeout=25)
                    part_versioned_url = self._resolve_versioned_content_url(abs_url, part_wrapper_html)
                if not part_versioned_url:
                    continue
                part_html = await self._fetch_text_with_archival(part_versioned_url, timeout=25)
                if not part_html:
                    continue
                part_soup = BeautifulSoup(part_html, "html.parser")
                for part_link in part_soup.find_all("a", href=True):
                    part_href = str(part_link.get("href") or "").strip()
                    abs_part_href = urljoin(part_versioned_url, part_href)
                    if not self._UT_SECTION_LINK_RE.search(abs_part_href.lower()):
                        continue
                    section_versioned_url = self._resolve_versioned_link(abs_part_href)
                    if section_versioned_url and section_versioned_url not in seen:
                        seen.add(section_versioned_url)
                        urls.append(section_versioned_url)

        return urls

    def _resolve_versioned_link(self, href: str) -> Optional[str]:
        parsed = urlparse(str(href or ""))
        query = parse_qs(parsed.query or "")
        version = str((query.get("v") or [""])[0] or "").strip()
        if not version:
            return None
        base_path = parsed.path.rsplit("/", 1)[0]
        return urljoin(f"{parsed.scheme}://{parsed.netloc}", f"{base_path}/{version}.html")

    def _resolve_versioned_content_url(self, wrapper_url: str, wrapper_html: str) -> Optional[str]:
        if not wrapper_html:
            return None
        match = self._UT_VERSION_DEFAULT_RE.search(wrapper_html)
        if not match:
            return None
        version = str(match.group(1) or "").strip()
        if not version:
            return None
        parsed = urlparse(wrapper_url)
        base_path = parsed.path.rsplit("/", 1)[0]
        return urljoin(f"{parsed.scheme}://{parsed.netloc}", f"{base_path}/{version}.html")

    async def _build_official_section_from_versioned_url(
        self,
        code_name: str,
        versioned_url: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._fetch_text_with_archival(versioned_url, timeout=25)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        content = soup.select_one("#content") or soup.find("body") or soup
        text = self._normalize_legal_text(content.get_text(" ", strip=True))
        match = re.search(r"\b(\d{1,3}-\d{1,3}-\d+[A-Za-z0-9.-]*)\b", text)
        if not match or len(text) < 240:
            return None
        section_number = match.group(1)
        heading = soup.select_one("h3.heading")
        heading_text = self._normalize_legal_text(heading.get_text(" ", strip=True) if heading else "")
        section_name = heading_text
        if "Section " in heading_text:
            section_name = heading_text.split("Section ", 1)[-1]
        start_idx = text.find(f"{section_number}.")
        body = self._normalize_legal_text(text[start_idx:] if start_idx >= 0 else text)
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=section_number.split("-", 1)[0],
            section_number=section_number,
            section_name=section_name[:220] or f"Section {section_number}",
            full_text=body[:14000],
            source_url=versioned_url,
            legal_area=self._identify_legal_area(body[:1200]),
            official_cite=f"Utah Code § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_utah_code_versioned_html",
                "discovery_method": "official_title_chapter_part_section",
                "skip_hydrate": True,
            },
        )

    async def _fetch_text_with_archival(self, url: str, timeout: int = 25) -> str:
        try:
            payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=timeout)
        except Exception:
            payload = b""
        if not payload:
            return ""
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return str(payload)

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5-S203_2025050720250507.html",
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5-S202_2025050720250507.html",
        ]
        out: List[NormalizedStatute] = []
        for url in seeds[: max(1, int(max_statutes or 1))]:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            except Exception:
                payload = b""
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            content = soup.select_one("#content") or soup.find("body")
            text = self._normalize_legal_text(content.get_text(" ", strip=True) if content else "")
            match = re.search(r"\b(\d{1,3}-\d{1,3}-\d+[A-Za-z-]*)\.\s+(.+)", text)
            if not match or len(text) < 280:
                continue
            section_number = match.group(1)
            section_name = self._normalize_legal_text(match.group(2))[:220]
            # Drop the global breadcrumb/nav prefix so records start at the section.
            start_idx = text.find(f"{section_number}.")
            body = self._normalize_legal_text(text[start_idx:] if start_idx >= 0 else text)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name,
                    full_text=body[:14000],
                    source_url=url,
                    legal_area=self._identify_legal_area(body[:1200]),
                    official_cite=f"Utah Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_utah_code_section_html",
                        "discovery_method": "official_seed_current_version",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _scrape_live_chapter_stubs(
        self,
        code_name: str,
        title_limit: int = 10,
        per_title_limit: int = 8,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        title_rows = await self._scrape_live_title_stubs(code_name, max_statutes=max(1, int(title_limit)))
        out: List[NormalizedStatute] = []
        seen = set()
        for title_row in title_rows[:title_limit]:
            title_url = str(title_row.source_url or "").strip()
            if not title_url:
                continue
            try:
                payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=35)
                if not payload:
                    continue
            except Exception:
                continue

            soup = BeautifulSoup(payload, "html.parser")
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if not text:
                continue

            title_number = self._extract_title_number(str(title_row.section_number or ""))
            count = 0
            for match in self._UT_CHAPTER_RE.finditer(text):
                if count >= per_title_limit:
                    break
                chapter_no = match.group(1).strip()
                chapter_name = self._normalize_legal_text(match.group(2))[:220]
                if not chapter_name:
                    continue
                key = f"{title_number}:{chapter_no}:{chapter_name}".lower()
                if key in seen:
                    continue
                seen.add(key)
                count += 1
                out.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § Title {title_number} Chapter {chapter_no}",
                        code_name=code_name,
                        section_number=f"Title {title_number} Chapter {chapter_no}",
                        section_name=f"Chapter {chapter_no} {chapter_name}"[:220],
                        full_text=f"Utah Code Title {title_number} Chapter {chapter_no} {chapter_name}",
                        source_url=title_url,
                        legal_area=self._identify_legal_area(chapter_name),
                        official_cite=f"Utah Code Title {title_number} Chapter {chapter_no}",
                        metadata=StatuteMetadata(),
                    )
                )
        return out

    def _extract_title_number(self, value: str) -> str:
        match = re.search(r"title\s+([0-9]+[A-Z]?)", str(value or ""), re.IGNORECASE)
        if match:
            return match.group(1).upper()
        return self._normalize_legal_text(value) or "UNKNOWN"

    async def _scrape_live_title_stubs(self, code_name: str, max_statutes: int = 60) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        url = f"{self.get_base_url()}/xcode/code.html"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=35)
            if not payload:
                return []
        except Exception:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        out: List[NormalizedStatute] = []
        seen = set()
        title_re = re.compile(r"title\s+([0-9]+[A-Z]?)", re.IGNORECASE)

        for a in soup.find_all("a", href=True):
            if len(out) >= max_statutes:
                break
            href = str(a.get("href") or "").strip()
            text = str(a.get_text(" ", strip=True) or "").strip()
            full_url = urljoin(url, href)
            if "/xcode/title" not in full_url.lower():
                continue

            match = title_re.search(text) or title_re.search(full_url)
            if not match:
                continue
            title_number = match.group(1).upper()
            key = title_number.lower()
            if key in seen:
                continue
            seen.add(key)

            title_name = text[:200] if text else f"Title {title_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § Title {title_number}",
                    code_name=code_name,
                    section_number=f"Title {title_number}",
                    section_name=title_name,
                    full_text=f"Utah Code {title_name}: {full_url}",
                    source_url=full_url,
                    legal_area=self._identify_legal_area(title_name),
                    official_cite=f"Utah Code Title {title_number}",
                    metadata=StatuteMetadata(),
                )
            )

        return out

    async def _discover_archived_title_urls(self, limit: int = 180) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=le.utah.gov/xcode/Title*"
            "&output=json&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._fetch_page_content_with_archival_fallback(cdx_url, timeout_seconds=35)
            rows = self._parse_json_rows(payload)
        except Exception:
            return []

        out: List[str] = []
        seen = set()
        for row in rows:
            if len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue
            lower_original = original.lower()
            if "/xcode/title" not in lower_original:
                continue
            replay = f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}"
            if replay in seen:
                continue
            seen.add(replay)
            out.append(replay)
            if len(out) >= limit:
                break

        return out


# Register this scraper with the registry
StateScraperRegistry.register("UT", UtahScraper)
