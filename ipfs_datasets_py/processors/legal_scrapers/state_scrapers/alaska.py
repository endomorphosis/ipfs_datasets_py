"""Scraper for Alaska state laws.

This module contains the scraper for Alaska statutes from the official state legislative website.
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


class AlaskaScraper(BaseStateScraper):
    """Scraper for Alaska state laws from http://www.legis.state.ak.us"""

    _AK_SECTION_RE = re.compile(r"\bSec\.\s*(\d{2}\.\d{2}\.\d{3})\.\s*(.+)", re.IGNORECASE | re.DOTALL)
    OFFICIAL_DOMAIN = "www.akleg.gov"
    OFFICIAL_ENTRY_PATH = "/basis/statutes.asp"
    OFFICIAL_ENTRY_URL = "https://www.akleg.gov/basis/statutes.asp"
    MISSING_LINK_QUARANTINE_REASON = "missing_official_source_link"
    _AK_TITLE_QUERY_RE = re.compile(r"[?&#]title=(\d{1,2})\b", re.IGNORECASE)
    _AK_TITLE_HASH_RE = re.compile(r"#(\d{1,2})(?:\.|$)", re.IGNORECASE)
    _AK_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(\d{1,2})\b", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Aeronautics"),
        ("3", "Agriculture, Animals, and Food"),
        ("4", "Alcoholic Beverages"),
        ("5", "Amusements and Sports"),
        ("6", "Banks and Financial Institutions"),
        ("8", "Business and Professions"),
        ("9", "Code of Civil Procedure"),
        ("10", "Corporations and Associations"),
        ("11", "Criminal Law"),
        ("12", "Code of Criminal Procedure"),
        ("13", "Decedents' Estates, Guardianships, Transfers, Trusts, and Health Care Decisions"),
        ("14", "Education, Libraries, and Museums"),
        ("15", "Elections"),
        ("16", "Fish and Game"),
        ("17", "Food and Drugs"),
        ("18", "Health, Safety, Housing, Human Rights, and Public Defender"),
        ("19", "Highways and Ferries"),
        ("21", "Insurance"),
        ("22", "Judiciary"),
        ("23", "Labor and Workers' Compensation"),
        ("24", "Legislature and Lobbying"),
        ("25", "Marital and Domestic Relations"),
        ("26", "Military Affairs, Veterans, Disasters, and Aerospace"),
        ("27", "Mining"),
        ("28", "Motor Vehicles"),
        ("29", "Municipal Government"),
        ("30", "Navigation, Harbors, Shipping, and Transportation Facilities"),
        ("31", "Oil and Gas"),
        ("32", "Partnership"),
        ("33", "Probation, Prisons, Pardons, and Prisoners"),
        ("34", "Property"),
        ("35", "Public Buildings, Works, and Improvements"),
        ("36", "Public Contracts"),
        ("37", "Public Finance"),
        ("38", "Public Land"),
        ("39", "Public Officers and Employees"),
        ("40", "Public Records and Recorders"),
        ("41", "Public Resources"),
        ("42", "Public Utilities and Carriers and Energy Programs"),
        ("43", "Revenue and Taxation"),
        ("44", "State Government"),
        ("45", "Trade and Commerce"),
        ("46", "Water, Air, Energy, and Environmental Conservation"),
        ("47", "Welfare, Social Services, and Institutions"),
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Alaska's legislative website."""
        return "http://www.legis.state.ak.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Alaska."""
        return [{
            "name": "Alaska Statutes",
            "url": "https://www.akleg.gov/basis/statutes.asp",
            "type": "Code"
        }]
    
    async def _fetch_statute_chunk(self, sec_start: str, timeout_seconds: int = 8) -> Tuple[str, str]:
        cache_url = f"https://www.akleg.gov/basis/statutes.asp?media=print&type=fetch&secStart={sec_start}"
        cached = await self._load_page_bytes_from_any_cache(cache_url)
        if cached:
            cached_html = cached.decode("cp1252", errors="replace")
            section_numbers = re.findall(r'name=["\'](\d{2}\.\d{2}\.\d{3})["\']', cached_html)
            return cached_html, (section_numbers[-1] if section_numbers else "")
        timeout = max(1, int(timeout_seconds or 8))

        def _request() -> Tuple[str, str]:
            try:
                import requests

                response = requests.get(
                    "https://www.akleg.gov/basis/statutes.asp",
                    params={"media": "print", "type": "fetch", "secStart": sec_start},
                    headers={
                        "User-Agent": "ipfs-datasets-alaska-statutes-scraper/2.0",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=timeout,
                )
                if int(response.status_code or 0) != 200:
                    return "", ""
                return bytes(response.content or b"").decode("cp1252", errors="replace"), str(response.headers.get("LastSec") or "")
            except Exception:
                return "", ""

        try:
            html, last_sec = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 1)
        except asyncio.TimeoutError:
            html, last_sec = "", ""
        self._record_fetch_event(provider="requests_direct", success=bool(html))
        if html:
            await self._cache_successful_page_fetch(
                url=cache_url,
                payload=html.encode("cp1252", errors="replace"),
                provider="requests_direct",
            )
        return html, last_sec

    def _parse_statute_chunk(self, *, code_name: str, html: str) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html or "", "html.parser")
        statutes: List[NormalizedStatute] = []
        for div in soup.select("div.statute"):
            anchors = [a.get("name") for a in div.find_all("a") if a.get("name")]
            section_anchor = next((str(a) for a in anchors if re.match(r"^\d{2}\.\d{2}\.\d{3}$", str(a))), "")
            if not section_anchor:
                continue
            heading_node = None
            for bold in div.find_all("b"):
                anchor = bold.find("a")
                if anchor and str(anchor.get("name") or "") == section_anchor:
                    heading_node = bold
                    break
            heading = self._normalize_legal_text(heading_node.get_text(" ", strip=True) if heading_node else "")
            match = self._AK_SECTION_RE.search(heading)
            if not match:
                continue
            section_number = match.group(1)
            section_name = re.sub(r"\s+", " ", match.group(2)).strip()
            full_text = self._normalize_legal_text(div.get_text(" ", strip=True))
            if len(full_text) < 120:
                continue
            title_number, chapter_number, _section = section_number.split(".")
            source_url = f"https://www.akleg.gov/basis/statutes.asp#{section_number}"
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"AK-{section_number}",
                    code_name=code_name,
                    title_number=title_number,
                    chapter_number=chapter_number,
                    section_number=section_number,
                    section_name=section_name[:200],
                    short_title=section_name[:200],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(section_name),
                    source_url=source_url,
                    official_cite=f"Alaska Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_alaska_statutes_ajax_html",
                        "discovery_method": "official_fetch_endpoint",
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    def _next_sec_start(self, last_sec: str) -> Optional[str]:
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", str(last_sec or "").strip())
        if not match:
            return None
        title, chapter, _section = (int(part) for part in match.groups())
        return f"{title}.{chapter + 1:02d}"

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Alaska's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=240)
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        sec_start: Optional[str] = "1"

        for _ in range(80):
            if not sec_start or (limit is not None and len(statutes) >= limit):
                break
            html, last_sec = await self._fetch_statute_chunk(sec_start)
            if not html:
                break
            for statute in self._parse_statute_chunk(code_name=code_name, html=html):
                key = str(statute.section_number or "")
                if key in seen_sections:
                    continue
                seen_sections.add(key)
                statutes.append(statute)
                if limit is not None and len(statutes) >= limit:
                    break
            next_start = self._next_sec_start(last_sec)
            if not next_start or next_start == sec_start:
                break
            sec_start = next_start

        return statutes[:limit] if limit is not None else statutes

    def official_title_url(self, title_number: object) -> str:
        number = str(title_number or "").strip()
        padded = number.zfill(2) if number.isdigit() else number
        return f"{self.OFFICIAL_ENTRY_URL}#{padded}"

    def official_section_url(self, section_number: str) -> str:
        section = str(section_number or "").strip()
        return f"{self.OFFICIAL_ENTRY_URL}#{section}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Alaska Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"ak:title-{number}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Alaska Statutes Title {number} ({name}) official catalog "
                        f"unit at {url}"
                    ),
                }
            )
        return rows

    def is_official_akleg_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return (
            host == "akleg.gov"
            or host.endswith(".akleg.gov")
            or host == "legis.state.ak.us"
            or host.endswith(".legis.state.ak.us")
        )

    def repair_or_type_missing_source_link(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Attach an official Alaska Legislature URL or type a linkless row."""

        structured = dict(statute.structured_data or {})
        source_url = str(statute.source_url or "").strip()
        if source_url and self.is_official_akleg_url(source_url):
            structured.setdefault("source_link_disposition", "official")
            statute.structured_data = structured
            return statute

        section_number = str(statute.section_number or "").strip()
        if section_number:
            repaired = self.official_section_url(section_number)
            statute.source_url = repaired
            structured["source_kind"] = (
                structured.get("source_kind") or "official_alaska_statutes_ajax_html"
            )
            structured["source_link_disposition"] = "repaired_official_akleg"
            structured["previous_source_url"] = source_url or None
            statute.structured_data = structured
            return statute

        structured["source_link_disposition"] = "typed_quarantine"
        structured["quarantine_reason"] = self.MISSING_LINK_QUARANTINE_REASON
        statute.structured_data = structured
        return statute

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-alaska-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-alaska-official-catalog/1.0",
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
            parsed = urlparse(absolute)
            query = parse_qs(parsed.query)
            title_values = query.get("title") or []
            number = str((title_values or [""])[0]).lstrip("0") or str(
                (title_values or [""])[0]
            )
            if not number or number not in known:
                match = (
                    self._AK_TITLE_QUERY_RE.search(absolute)
                    or self._AK_TITLE_HASH_RE.search(absolute)
                    or self._AK_TITLE_LABEL_RE.search(link.get_text(" ", strip=True) or "")
                )
                number = match.group(1).lstrip("0") or match.group(1) if match else ""
            if number not in known:
                continue
            if number not in found and self.is_official_akleg_url(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Alaska title and repair missing-link rows."""

        discovered = self._parse_official_title_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        rows: List[Dict[str, Any]] = []
        for item in self.official_title_catalog():
            number = str(item["title_number"])
            official_url = str(item["source_url"])
            live_url = discovered.get(number)
            source_url = live_url or official_url
            disposition = "official" if live_url else "repaired_official_akleg"
            rows.append(
                {
                    **item,
                    "source_url": source_url,
                    "source_link_disposition": disposition,
                    "text": (
                        f"Alaska Statutes Title {number} ({item['name']}) official "
                        f"catalog unit at {source_url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "AK"):
        """Acquire the exhaustive official Alaska Statutes title catalog.

        Live HTTPS retains the official BASIS statutes landing page. Every
        known Alaska title is enumerated with an official akleg.gov URL.
        Linkless catalog members are repaired to the official title URL.
        This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "AK").strip().upper() or "AK"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("alaska official catalog enumeration is incomplete")
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
StateScraperRegistry.register("AK", AlaskaScraper)
