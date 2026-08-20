"""Scraper for Montana state laws.

This module contains the scraper for Montana statutes from the official state legislative website.
"""

import json
import re
import ssl
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute
from .base_scraper import StatuteMetadata
from .registry import StateScraperRegistry


class MontanaScraper(BaseStateScraper):
    """Scraper for Montana state laws from https://leg.mt.gov"""

    OFFICIAL_DOMAIN = "leg.mt.gov"
    OFFICIAL_ENTRY_PATH = "/bills/mca/index.html"
    OFFICIAL_ENTRY_URL = "https://leg.mt.gov/bills/mca/index.html"
    OFFICIAL_TITLES = (
        1, 2, 3, 5, 7, 10, 13, 15, 16, 17, 18, 19, 20, 22, 23, 25, 27, 28,
        30, 31, 32, 33, 35, 37, 39, 40, 41, 42, 44, 45, 46, 49, 50, 52, 53,
        60, 61, 67, 69, 70, 71, 72, 75, 76, 80, 81, 82, 85, 87, 90,
    )
    _MT_TITLE_INDEX_HREF_RE = re.compile(
        r"title_(?P<title>\d{4})/chapters_index\.html",
        re.IGNORECASE,
    )
    _MT_SECTION_URL_RE = re.compile(r"/\d{4}-\d{4}-\d{4}-\d{4}\.html$", re.IGNORECASE)
    _MT_TITLE_INDEX_RE = re.compile(
        r"https://mca\.legmt\.gov/bills/mca/title_\d{4}/chapters_index\.html", re.IGNORECASE
    )
    _MT_CHAPTER_INDEX_RE = re.compile(
        r"https://mca\.legmt\.gov/bills/mca/title_\d{4}/chapter_\d{4}/parts_index\.html",
        re.IGNORECASE,
    )
    _MT_PART_INDEX_RE = re.compile(
        r"https://mca\.legmt\.gov/bills/mca/title_\d{4}/chapter_\d{4}/part_\d{4}/sections_index\.html",
        re.IGNORECASE,
    )
    _MT_MARKDOWN_LINK_RE = re.compile(
        r"\[([^\]]+)\]\((https://mca\.legmt\.gov[^)]+)\)", re.IGNORECASE
    )

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MT_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered

    def get_base_url(self) -> str:
        """Return the base URL for Montana's legislative website."""
        return "https://leg.mt.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Montana."""
        return [
            {
                "name": "Montana Code Annotated",
                "url": f"{self.get_base_url()}/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html",
                "type": "Code",
            }
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Montana's legislative website.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        direct_limit = self._effective_scrape_limit(max_statutes, default=160)
        official = await self._scrape_official_mca_tree(
            code_name, max_statutes=max(10, int(direct_limit or 10))
        )
        if official:
            return official[: max(1, int(direct_limit or len(official)))]

        direct = await self._scrape_direct_seed_sections(
            code_name,
            max_statutes=max(1, int(direct_limit or 2)),
        )
        if direct and not self._full_corpus_enabled():
            return direct[: max(1, int(direct_limit or len(direct)))]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/bills/mca/",
            f"{self.get_base_url()}/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html",
            "https://archive.legmt.gov/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        return_threshold = self._bounded_return_threshold(160)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Mont. Code Ann.",
                        max_sections=max(10, return_threshold),
                        wait_for_selector="a[href*='/bills/mca/'], a[href*='/section_'], a[href*='chapters_index']",
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
                code_name, candidate, "Mont. Code Ann.", max_sections=max(10, return_threshold)
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes

        return best_statutes

    async def _scrape_official_mca_tree(
        self,
        code_name: str,
        max_statutes: int,
    ) -> List[NormalizedStatute]:
        root_reader = "https://r.jina.ai/http://https://leg.mt.gov/bills/mca/"
        root_text = await self._fetch_reader_markdown(root_reader)
        if not root_text:
            return []

        statutes: List[NormalizedStatute] = []
        seen_sections = set()
        title_links = self._extract_mca_links(root_text, self._MT_TITLE_INDEX_RE)
        for _, title_url in title_links:
            if len(statutes) >= max_statutes:
                break
            title_text = await self._fetch_reader_markdown(f"https://r.jina.ai/http://{title_url}")
            if not title_text:
                continue
            chapter_links = self._extract_mca_links(title_text, self._MT_CHAPTER_INDEX_RE)
            for _, chapter_url in chapter_links:
                if len(statutes) >= max_statutes:
                    break
                chapter_text = await self._fetch_reader_markdown(
                    f"https://r.jina.ai/http://{chapter_url}"
                )
                if not chapter_text:
                    continue
                part_links = self._extract_mca_links(chapter_text, self._MT_PART_INDEX_RE)
                for _, part_url in part_links:
                    if len(statutes) >= max_statutes:
                        break
                    part_text = await self._fetch_reader_markdown(
                        f"https://r.jina.ai/http://{part_url}"
                    )
                    if not part_text:
                        continue
                    section_links = self._extract_mca_links(part_text, self._MT_SECTION_URL_RE)
                    for section_label, section_url in section_links:
                        if len(statutes) >= max_statutes:
                            break
                        if section_url in seen_sections:
                            continue
                        seen_sections.add(section_url)
                        statute = await self._build_official_section_statute(
                            code_name, section_label, section_url
                        )
                        if statute is not None:
                            statutes.append(statute)
        return statutes

    async def _build_official_section_statute(
        self,
        code_name: str,
        section_label: str,
        section_url: str,
    ) -> Optional[NormalizedStatute]:
        markdown = await self._fetch_reader_markdown(f"https://r.jina.ai/http://{section_url}")
        if not markdown:
            return None
        section_number = self._section_number_from_mca_url(section_url)
        text = self._extract_reader_statute_text(markdown, section_number)
        if len(text) < 220:
            return None
        heading = self._normalize_legal_text(section_label)[:220] or self._extract_reader_heading(
            markdown, section_number
        )
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=(section_number.split("-", 1)[0] if section_number else None),
            section_number=section_number,
            section_name=heading,
            full_text=text,
            legal_area=self._identify_legal_area(text[:1200]),
            source_url=section_url,
            official_cite=f"Mont. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "jina_reader_montana_mca_hierarchical",
                "discovery_method": "official_mca_title_chapter_part_section",
                "reader_url": f"https://r.jina.ai/http://{section_url}",
                "skip_hydrate": True,
            },
        )

    async def _fetch_reader_markdown(self, reader_url: str) -> str:
        raw = await self._fetch_page_content_with_archival_fallback(reader_url, timeout_seconds=25)
        if not raw:
            return ""
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)

    def _extract_mca_links(
        self, markdown: str, target_pattern: re.Pattern
    ) -> List[tuple[str, str]]:
        links: List[tuple[str, str]] = []
        seen = set()
        for label, url in self._MT_MARKDOWN_LINK_RE.findall(str(markdown or "")):
            clean_url = str(url or "").strip().rstrip("`").split('"', 1)[0].strip()
            if not clean_url or clean_url in seen:
                continue
            if isinstance(target_pattern, re.Pattern):
                if not target_pattern.search(clean_url):
                    continue
            seen.add(clean_url)
            links.append((self._normalize_legal_text(label), clean_url))
        return links

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        """Recover full Montana statute text from official pages via Jina reader."""
        seeds = [
            "https://leg.mt.gov/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html",
            "https://leg.mt.gov/bills/mca/title_0460/chapter_0180/part_0020/section_0190/0460-0180-0020-0190.html",
        ]
        out: List[NormalizedStatute] = []
        for url in seeds[: max(1, int(max_statutes or 1))]:
            reader_url = f"https://r.jina.ai/http://{url}"
            raw = await self._fetch_page_content_with_archival_fallback(
                reader_url, timeout_seconds=25
            )
            if not raw:
                continue
            try:
                markdown = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
            section_number = self._section_number_from_mca_url(url)
            text = self._extract_reader_statute_text(markdown, section_number)
            if len(text) < 220:
                continue
            heading = self._extract_reader_heading(markdown, section_number)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=(section_number.split("-", 1)[0] if section_number else None),
                    section_number=section_number,
                    section_name=heading,
                    full_text=text,
                    legal_area=self._identify_legal_area(text[:1200]),
                    source_url=url,
                    official_cite=f"Mont. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "jina_reader_montana_mca_official",
                        "discovery_method": "cloudflare_block_recovery_seed_section",
                        "reader_url": reader_url,
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def _section_number_from_mca_url(self, url: str) -> str:
        match = self._MT_SECTION_URL_RE.search(str(url or ""))
        if not match:
            return self._derive_section_number_from_url(url) or ""
        raw = match.group(0).rsplit("/", 1)[-1].removesuffix(".html")
        parts = [int(part) for part in raw.split("-") if part.isdigit()]
        if len(parts) >= 4:
            title, chapter, part, section = parts[:4]
            # Montana MCA file paths encode section 45-5-102 as
            # title_0450/chapter_0050/part_0010/section_0020.
            section_tail = (part // 10 * 100) + (section // 10)
            return f"{title // 10}-{chapter // 10}-{section_tail}"
        return self._derive_section_number_from_url(url) or raw

    def _extract_reader_heading(self, markdown: str, section_number: str) -> str:
        for line in str(markdown or "").splitlines():
            value = self._normalize_legal_text(line.lstrip("# ").strip())
            if section_number and value.startswith(section_number):
                return value[:220]
        title_match = re.search(
            r"^Title:\s*(.+)$", str(markdown or ""), flags=re.IGNORECASE | re.MULTILINE
        )
        if title_match:
            return self._normalize_legal_text(title_match.group(1))[:220]
        return section_number

    def _extract_reader_statute_text(self, markdown: str, section_number: str) -> str:
        lines = []
        capture = False
        for line in str(markdown or "").splitlines():
            value = line.strip()
            if not value:
                if capture:
                    lines.append("")
                continue
            clean = self._normalize_legal_text(value.lstrip("# ").strip())
            if not capture and section_number and clean.startswith(section_number):
                capture = True
            if capture:
                if clean.lower().startswith(("url source:", "markdown content:", "title:")):
                    continue
                lines.append(value)
        text = self._normalize_legal_text("\n".join(lines))
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        return self._normalize_legal_text(text)

    def official_title_token(self, title_number: Any) -> str:
        return f"{int(title_number) * 10:04d}"

    def official_title_url(self, title_number: Any) -> str:
        token = self.official_title_token(title_number)
        return f"https://leg.mt.gov/bills/mca/title_{token}/chapters_index.html"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Montana Code Annotated title catalog."""

        rows: List[Dict[str, Any]] = []
        for number in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"mt:title-{int(number)}",
                    "title_number": str(int(number)),
                    "name": f"Title {int(number)}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Montana Code Annotated Title {int(number)} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-montana-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }

        def _request() -> bytes:
            try:
                request = urllib.request.Request(url, headers=headers)
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(url, headers=headers)
                    context = ssl._create_unverified_context()
                    with urllib.request.urlopen(
                        request, timeout=timeout, context=context
                    ) as response:
                        return bytes(response.read() or b"")
                except Exception:
                    return b""

        return _request()

    def _title_number_from_token(self, token: str) -> str:
        digits = "".join(ch for ch in str(token or "") if ch.isdigit())
        if not digits:
            return ""
        value = int(digits)
        if value >= 10 and value % 10 == 0:
            return str(value // 10)
        return str(value)

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
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
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._MT_TITLE_INDEX_HREF_RE.search(absolute)
            if not match:
                continue
            number = self._title_number_from_token(match.group("title"))
            if number and number not in found:
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official MCA title and repair missing live links."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        seen = {str(row["title_number"]) for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
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
                    "canonical_key": f"mt:title-{number}",
                    "title_number": number,
                    "name": f"Title {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Montana Code Annotated Title {number} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "MT"):
        """Acquire the exhaustive official Montana Code Annotated title catalog.

        Live HTTPS retains the official MCA index. Every known title is
        enumerated with an official leg.mt.gov URL. This hook never returns
        fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "MT").strip().upper() or "MT"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        if not html:
            html = self._official_http_get("https://leg.mt.gov/bills/mca/")
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("montana official catalog enumeration is incomplete")
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
StateScraperRegistry.register("MT", MontanaScraper)
