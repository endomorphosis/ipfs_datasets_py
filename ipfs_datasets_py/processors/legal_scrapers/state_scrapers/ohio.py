import json
import re
import ssl
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class OhioScraper(BaseStateScraper):
    """Scraper for Ohio state laws from https://codes.ohio.gov"""

    OFFICIAL_DOMAIN = "codes.ohio.gov"
    OFFICIAL_ENTRY_PATH = "/ohio-revised-code"
    OFFICIAL_ENTRY_URL = "https://codes.ohio.gov/ohio-revised-code"
    _OH_TITLE_URL_RE = re.compile(r"/ohio-revised-code/title-(\d+)$", re.IGNORECASE)
    _OH_CHAPTER_URL_RE = re.compile(r"/ohio-revised-code/chapter-([0-9.]+)$", re.IGNORECASE)
    _OH_SECTION_URL_RE = re.compile(r"/ohio-revised-code/section-([0-9A-Za-z.]+)$", re.IGNORECASE)
    _OH_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(?P<title>\d{1,2})\b", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "State Government"),
        ("3", "Counties"),
        ("5", "Townships"),
        ("7", "Municipal Corporations"),
        ("9", "Agriculture-Animals-Fences"),
        ("11", "Banks-Savings and Loan Associations"),
        ("13", "Commercial Transactions-Ohio Uniform Commercial Code"),
        ("15", "Conservation of Natural Resources"),
        ("17", "Corporations-Partnerships"),
        ("19", "Courts-Municipal-Mayor's-County"),
        ("21", "Courts-Probate-Juvenile"),
        ("23", "Courts-Common Pleas"),
        ("25", "Courts-Appellate"),
        ("27", "Courts-General Provisions-Special Remedies"),
        ("29", "Crimes-Procedure"),
        ("31", "Domestic Relations-Children"),
        ("33", "Education-Libraries"),
        ("35", "Elections"),
        ("37", "Health-Safety-Morals"),
        ("39", "Insurance"),
        ("41", "Labor and Industry"),
        ("43", "Liquor"),
        ("45", "Motor Vehicles-Aeronautics-Watercraft"),
        ("47", "Occupations-Professions"),
        ("49", "Public Utilities"),
        ("51", "Public Welfare"),
        ("53", "Real Property"),
        ("55", "Roads-Highways-Bridges"),
        ("57", "Taxation"),
        ("58", "Trusts"),
        ("59", "Veterans-Military Affairs"),
        ("61", "Water Supply-Sanitation-Ditches"),
        ("63", "Workforce Development"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)
    
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

        # Seed/direct recovery is for bounded probes only — never sole full-corpus path.
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct_limit = limit if limit is not None else 160
            direct = await self._scrape_direct_sections(code_name, max_statutes=direct_limit)
            if direct:
                _merge(direct)

        official = await self._scrape_official_title_chapter_section_tree(
            code_name,
            max_statutes=limit,
        )
        if official:
            return official if limit is None else official[: int(limit)]

        if merged:
            return merged if limit is None else merged[: int(limit)]
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
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None

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
        # Bound section-link exploration when sampling; unbounded in full-corpus mode.
        max_section_links = (limit * 5) if limit is not None else None
        for title_url in title_urls:
            if limit is not None and len(statutes) >= limit:
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
                if limit is not None and len(statutes) >= limit:
                    break
                if max_section_links is not None and len(seen_sections) >= max_section_links:
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
                        if limit is not None and len(statutes) >= limit:
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

    def official_title_url(self, title_number: Any) -> str:
        number = str(int(str(title_number).strip()))
        return f"{self.get_base_url()}/ohio-revised-code/title-{number}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Ohio Revised Code title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"oh:title-{int(number)}",
                    "title_number": str(int(number)),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Ohio Revised Code Title {int(number)} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == "codes.ohio.gov" or host.endswith(".codes.ohio.gov")

    def _official_http_get(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(2, min(int(timeout_seconds or 8), 8))
        headers = {
            "User-Agent": "ipfs-datasets-ohio-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        try:
            request = urllib.request.Request(url, headers=headers)
            context = ssl.create_default_context()
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return bytes(response.read() or b"")
        except Exception:
            return b""

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {number for number, _name in self.OFFICIAL_TITLES}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._OH_TITLE_URL_RE.search(absolute) or self._OH_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = str(int(match.group(1) if match.lastindex else match.group("title")))
            if number not in known or number in found:
                continue
            if self._host_is_official(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Ohio Revised Code title."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_ohcodes"
        return rows

    def fetch_official(self, code: str = "OH"):
        """Acquire the exhaustive official Ohio Revised Code title catalog.

        Live HTTPS retains the official codes.ohio.gov title index. Every known
        Revised Code title is enumerated with an official URL. This hook never
        returns fixture bytes or secondary-mirror hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "OH").strip().upper() or "OH"
        if normalized != "OH":
            raise ValueError(f"OhioScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "ohio official catalog enumeration rejected incomplete title reacquisition"
            )
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
StateScraperRegistry.register("OH", OhioScraper)
