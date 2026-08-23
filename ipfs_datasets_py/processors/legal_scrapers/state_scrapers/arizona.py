"""Scraper for Arizona state laws.

This module contains the scraper for Arizona statutes from the official state legislative website.
"""

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import json
import re
import ssl
import urllib.request
from urllib.parse import parse_qs, urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class ArizonaScraper(BaseStateScraper):
    """Scraper for Arizona state laws from https://www.azleg.gov"""

    OFFICIAL_DOMAIN = "www.azleg.gov"
    OFFICIAL_ENTRY_PATH = "/arsOverview/"
    OFFICIAL_ENTRY_URL = "https://www.azleg.gov/arsOverview/"
    _AZ_TITLE_DETAIL_RE = re.compile(r"/arsDetail/\?title=\d+$", re.IGNORECASE)
    _AZ_SECTION_DOC_RE = re.compile(r"/ars/(\d+)/([0-9A-Za-z-]+)\.htm$", re.IGNORECASE)
    _AZ_SECTION_HEAD_RE = re.compile(r"^\s*(\d+-\d+(?:\.\d+)?)\s*[-–]\s*(.+)$")
    _AZ_DETAIL_SECTION_LINK_RE = re.compile(
        r'<a[^>]+class=["\'][^"\']*\bstat\b[^"\']*["\'][^>]+href=["\'](?P<href>[^"\']+)["\'][^>]*>\s*(?P<section>\d+-\d+(?:\.\d+)?)\s*</a>'
        r"\s*</li>\s*<li[^>]+class=[\"'][^\"']*\bcolright\b[^\"']*[\"'][^>]*>\s*(?P<title>.*?)\s*</li>",
        re.IGNORECASE | re.DOTALL,
    )
    _AZ_TITLE_QUERY_RE = re.compile(r"[?&]title=(\d{1,2})\b", re.IGNORECASE)
    _AZ_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(\d{1,2})\b", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Aeronautics"),
        ("3", "Agriculture"),
        ("4", "Alcoholic Beverages"),
        ("5", "Amusements and Sports"),
        ("6", "Banks and Financial Institutions"),
        ("7", "Bonds"),
        ("8", "Child Safety"),
        ("9", "Cities and Towns"),
        ("10", "Corporations and Associations"),
        ("11", "Counties"),
        ("12", "Courts and Civil Proceedings"),
        ("13", "Criminal Code"),
        ("14", "Trusts, Estates and Protective Proceedings"),
        ("15", "Education"),
        ("16", "Elections and Electors"),
        ("17", "Game and Fish"),
        ("18", "Information Technology"),
        ("19", "Initiative, Referendum and Recall"),
        ("20", "Insurance"),
        ("21", "Juries"),
        ("22", "Justice and Municipal Courts"),
        ("23", "Labor"),
        ("24", "Livestock"),
        ("25", "Marital and Domestic Relations"),
        ("26", "Military Affairs and Emergency Management"),
        ("27", "Minerals, Oil and Gas"),
        ("28", "Transportation"),
        ("29", "Partnership"),
        ("30", "Power"),
        ("31", "Prisons and Prisoners"),
        ("32", "Professions and Occupations"),
        ("33", "Property"),
        ("34", "Public Buildings and Improvements"),
        ("35", "Public Finances"),
        ("36", "Public Health and Safety"),
        ("37", "Public Lands"),
        ("38", "Public Officers and Employees"),
        ("39", "Public Records, Printing and Notices"),
        ("40", "Public Utilities and Carriers"),
        ("41", "State Government"),
        ("42", "Taxation"),
        ("43", "Taxation of Income"),
        ("44", "Trade and Commerce"),
        ("45", "Waters"),
        ("46", "Welfare"),
        ("47", "Uniform Commercial Code"),
        ("48", "Special Taxing Districts"),
        ("49", "The Environment"),
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Arizona's legislative website."""
        return "https://www.azleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Arizona."""
        # Arizona publishes titles behind a consistent static endpoint. Return
        # every likely title so full-corpus runs can walk the whole ARS, while
        # bounded runs stop after the first successful title via scrape_all().
        return [
            {
                "name": f"Arizona Revised Statutes Title {title}",
                "url": f"{self.get_base_url()}/arsDetail/?title={title}",
                "type": "Code",
            }
            for title in range(1, 50)
        ]
    
    async def _fetch_official_az_html(self, url: str, timeout_seconds: int = 8) -> str:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached.decode("utf-8", errors="replace")
        timeout = max(1, int(timeout_seconds or 8))

        def _request() -> str:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-arizona-ars-scraper/2.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                    timeout=timeout,
                )
                if int(response.status_code or 0) != 200:
                    return ""
                return bytes(response.content or b"").decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            html = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 1)
        except asyncio.TimeoutError:
            html = ""
        self._record_fetch_event(provider="requests_direct", success=bool(html))
        if html:
            await self._cache_successful_page_fetch(
                url=url,
                payload=html.encode("utf-8", errors="replace"),
                provider="requests_direct",
            )
        return html

    def _raw_doc_url_from_href(self, href: str, base_url: str) -> str:
        value = urljoin(base_url, str(href or "").strip())
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        doc_name = (query.get("docName") or query.get("docname") or [""])[0]
        return doc_name.strip() if doc_name else value

    async def _discover_section_links(self, title_url: str) -> List[Tuple[str, str, str]]:
        html = await self._fetch_official_az_html(title_url)
        if not html:
            return []

        out: List[Tuple[str, str, str]] = []
        seen: set[str] = set()
        for match in self._AZ_DETAIL_SECTION_LINK_RE.finditer(html):
            label = re.sub(r"\s+", " ", match.group("section") or "").strip()
            raw_url = self._raw_doc_url_from_href(str(match.group("href") or ""), title_url)
            if not self._AZ_SECTION_DOC_RE.search(raw_url):
                continue
            if raw_url in seen:
                continue
            seen.add(raw_url)
            title = re.sub(r"<[^>]+>", " ", str(match.group("title") or ""))
            title = re.sub(r"\s+", " ", title).strip()
            out.append((raw_url, label, title))
        return out

    async def _build_statute_from_section_page(
        self,
        *,
        code_name: str,
        section_url: str,
        section_number: str,
        section_title: str = "",
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._fetch_official_az_html(section_url)
        if not html:
            return None
        from .arizona_section import parse_arizona_section_html

        parsed = parse_arizona_section_html(
            html, source_url=section_url, code_name=code_name
        )
        if parsed is not None:
            return parsed
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body") or soup
        full_text = self._normalize_legal_text(body.get_text(" ", strip=True))
        if "Page not found" in full_text or len(full_text) < 120:
            return None

        heading = ""
        first_p = body.find("p") if hasattr(body, "find") else None
        if first_p is not None:
            heading = self._normalize_legal_text(first_p.get_text(" ", strip=True))
        match = self._AZ_SECTION_HEAD_RE.match(heading)
        if match:
            section_number = match.group(1)
            section_title = match.group(2).strip()

        url_match = self._AZ_SECTION_DOC_RE.search(section_url)
        title_number = url_match.group(1) if url_match else section_number.split("-", 1)[0]
        chapter_number = section_number.split("-", 1)[1].split(".", 1)[0][:2] if "-" in section_number else None

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"AZ-{section_number}",
            code_name=code_name,
            title_number=title_number,
            chapter_number=chapter_number,
            section_number=section_number,
            section_name=(section_title or heading or section_number)[:200],
            short_title=(section_title or heading or section_number)[:200],
            full_text=full_text,
            legal_area=self._identify_legal_area(section_title or heading),
            source_url=section_url,
            official_cite=f"Ariz. Rev. Stat. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_arizona_ars_html",
                "discovery_method": "official_title_detail_index",
                "skip_hydrate": True,
            },
        )

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Arizona's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=240)
        from .arizona_section import configured_section_html_path, parse_arizona_section_html

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_arizona_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://www.azleg.gov/ars/13/01101.htm",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        statutes: List[NormalizedStatute] = []
        for section_url, section_number, section_title in await self._discover_section_links(code_url):
            if limit is not None and len(statutes) >= limit:
                break
            statute = await self._build_statute_from_section_page(
                code_name=code_name,
                section_url=section_url,
                section_number=section_number,
                section_title=section_title,
            )
            if statute is not None:
                statutes.append(statute)
        return statutes[:limit] if limit is not None else statutes

    def official_title_url(self, title_number: object) -> str:
        return f"{self.get_base_url()}/arsDetail/?title={title_number}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Arizona Revised Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"az:title-{number}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Arizona Revised Statutes Title {number} ({name}) official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def is_official_azleg_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == "azleg.gov" or host.endswith(".azleg.gov")

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-arizona-official-catalog/1.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                )
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    if int(getattr(response, "status", 200) or 200) != 200:
                        return b""
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "ipfs-datasets-arizona-official-catalog/1.0",
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

    def _parse_official_title_links(self, html: bytes, page_url: str = "") -> Dict[str, str]:
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
            if not href:
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            match = self._AZ_TITLE_QUERY_RE.search(absolute) or self._AZ_TITLE_LABEL_RE.search(
                link.get_text(" ", strip=True) or ""
            )
            if not match:
                continue
            number = match.group(1).lstrip("0") or match.group(1)
            if number not in known:
                continue
            if number not in found and self.is_official_azleg_url(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Arizona Revised Statutes title."""

        discovered = self._parse_official_title_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        rows: List[Dict[str, Any]] = []
        for item in self.official_title_catalog():
            number = str(item["title_number"])
            official_url = str(item["source_url"])
            live_url = discovered.get(number)
            source_url = live_url or official_url
            disposition = "official" if live_url else "repaired_official_azleg"
            rows.append(
                {
                    **item,
                    "source_url": source_url,
                    "source_link_disposition": disposition,
                    "text": (
                        f"Arizona Revised Statutes Title {number} ({item['name']}) "
                        f"official catalog unit at {source_url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "AZ"):
        """Acquire the exhaustive official Arizona Revised Statutes title catalog.

        Live HTTPS retains the official ARS overview page. Every published
        Arizona title is enumerated with an official azleg.gov URL. This hook
        never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "AZ").strip().upper() or "AZ"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("arizona official catalog enumeration is incomplete")
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
StateScraperRegistry.register("AZ", ArizonaScraper)
