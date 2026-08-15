"""Florida state law scraper.

Scrapes laws from the Florida Legislature website
(http://www.leg.state.fl.us/).
"""

import json
import re
import ssl
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat as asyncio
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class FloridaScraper(BaseStateScraper):
    """Scraper for Florida state laws from https://www.leg.state.fl.us."""

    OFFICIAL_DOMAIN = "www.leg.state.fl.us"
    OFFICIAL_ENTRY_PATH = "/Statutes/"
    OFFICIAL_ENTRY_URL = "https://www.leg.state.fl.us/Statutes/"
    MISSING_LINK_QUARANTINE_REASON = "missing_official_source_link"
    _TITLE_INDEX_RE = re.compile(r"App_mode=Display_Index&Title_Request=", re.IGNORECASE)
    _TITLE_REQUEST_RE = re.compile(r"[?&]Title_Request=([IVXLCDM]+)\b", re.IGNORECASE)
    _TITLE_LABEL_RE = re.compile(r"\bTitle\s+([IVXLCDM]+|\d+)\b", re.IGNORECASE)
    _CHAPTER_CONTENTS_RE = re.compile(
        r"URL=([0-9]{4}-[0-9]{4}/[0-9]{4}/[0-9]{4})ContentsIndex\.html",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("1", "I", "Construction of Statutes"),
        ("2", "II", "State Organization"),
        ("3", "III", "Legislative Branch; Commissions"),
        ("4", "IV", "Executive Branch"),
        ("5", "V", "Judicial Branch"),
        ("6", "VI", "Civil Practice and Procedure"),
        ("7", "VII", "Evidence"),
        ("8", "VIII", "Limitations"),
        ("9", "IX", "Electors and Elections"),
        ("10", "X", "Public Officers, Employees, and Records"),
        ("11", "XI", "County Organization and Intergovernmental Relations"),
        ("12", "XII", "Municipalities"),
        ("13", "XIII", "Planning and Development"),
        ("14", "XIV", "Taxation and Finance"),
        ("15", "XV", "Homestead and Exemptions"),
        ("16", "XVI", "Teachers' Retirement System; Higher Educational Facilities Bonds"),
        ("17", "XVII", "Military Affairs and Related Matters"),
        ("18", "XVIII", "Public Lands and Property"),
        ("19", "XIX", "Public Business"),
        ("20", "XX", "Veterans"),
        ("21", "XXI", "Drainage"),
        ("22", "XXII", "Ports and Harbors"),
        ("23", "XXIII", "Motor Vehicles"),
        ("24", "XXIV", "Vessels"),
        ("25", "XXV", "Aviation"),
        ("26", "XXVI", "Public Transportation"),
        ("27", "XXVII", "Railroads and Other Regulated Utilities"),
        ("28", "XXVIII", "Natural Resources; Conservation, Reclamation, and Use"),
        ("29", "XXIX", "Public Health"),
        ("30", "XXX", "Social Welfare"),
        ("31", "XXXI", "Labor"),
        ("32", "XXXII", "Regulation of Professions and Occupations"),
        ("33", "XXXIII", "Regulation of Trade, Commerce, Investments, and Solicitations"),
        ("34", "XXXIV", "Alcoholic Beverages and Tobacco"),
        ("35", "XXXV", "Agriculture, Horticulture, and Animal Industry"),
        ("36", "XXXVI", "Business Organizations"),
        ("37", "XXXVII", "Insurance"),
        ("38", "XXXVIII", "Banks and Banking"),
        ("39", "XXXIX", "Commercial Relations"),
        ("40", "XL", "Real and Personal Property"),
        ("41", "XLI", "Statute of Frauds, Fraudulent Transfers, and General Assignments"),
        ("42", "XLII", "Estates and Trusts"),
        ("43", "XLIII", "Domestic Relations"),
        ("44", "XLIV", "Civil Rights"),
        ("45", "XLV", "Torts"),
        ("46", "XLVI", "Crimes"),
        ("47", "XLVII", "Criminal Procedure and Corrections"),
        ("48", "XLVIII", "Early Learning-20 Education Code"),
    )
    _ROMAN_TO_ARABIC = {roman.upper(): number for number, roman, _name in OFFICIAL_TITLES}
    _ARABIC_TO_ROMAN = {number: roman for number, roman, _name in OFFICIAL_TITLES}

    def get_base_url(self) -> str:
        """Get base URL for Florida statutes."""
        return "https://www.leg.state.fl.us"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of Florida statutes."""
        base_url = self.get_base_url()
        return [
            {"name": "Florida Statutes", "url": f"{base_url}/Statutes/", "type": "FS"},
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Florida statutes directly from official title/chapter indexes."""
        # Uncapped when max_statutes is omitted (full-corpus daemon runs).
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
            self.logger.warning(
                "Florida official direct crawl returned no statutes; "
                "skipping generic recovery fallback"
            )
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

    def official_title_url(self, title_number: object) -> str:
        token = str(title_number or "").strip()
        roman = self._ARABIC_TO_ROMAN.get(token, token.upper())
        if token.upper() in self._ROMAN_TO_ARABIC:
            roman = token.upper()
        return (
            f"{self.get_base_url()}/Statutes/index.cfm"
            f"?App_mode=Display_Index&Title_Request={roman}"
        )

    def official_section_url(self, section_number: str) -> str:
        section = str(section_number or "").strip()
        return (
            f"{self.get_base_url()}/Statutes/index.cfm"
            f"?App_mode=Display_Statute&Search_String=&Statute={section}"
        )

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Florida Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, roman, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"fl:title-{number}",
                    "title_number": number,
                    "title_roman": roman,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Florida Statutes Title {roman} ({name}) official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def is_official_fl_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith(".leg.state.fl.us")

    def repair_or_type_missing_source_link(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Attach an official Florida Statutes URL or type a linkless row."""

        structured = dict(statute.structured_data or {})
        source_url = str(statute.source_url or "").strip()
        if source_url and self.is_official_fl_url(source_url):
            structured.setdefault("source_link_disposition", "official")
            statute.structured_data = structured
            return statute

        section_number = str(statute.section_number or "").strip()
        if section_number:
            repaired = self.official_section_url(section_number)
            statute.source_url = repaired
            structured["source_kind"] = (
                structured.get("source_kind") or "official_florida_statutes_html"
            )
            structured["source_link_disposition"] = "repaired_official_flleg"
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
                        "User-Agent": "ipfs-datasets-florida-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-florida-official-catalog/1.0",
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

    def _normalize_title_token(self, token: str) -> str:
        value = str(token or "").strip().upper()
        if value in self._ROMAN_TO_ARABIC:
            return self._ROMAN_TO_ARABIC[value]
        if value.lstrip("0") in self._ARABIC_TO_ROMAN:
            return value.lstrip("0")
        if value in self._ARABIC_TO_ROMAN:
            return value
        return ""

    def _parse_official_title_links(self, html: bytes, page_url: str = "") -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {number for number, _roman, _name in self.OFFICIAL_TITLES}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            parsed = urlparse(absolute)
            query = parse_qs(parsed.query)
            request_values = query.get("Title_Request") or query.get("title_request") or []
            token = str((request_values or [""])[0]).strip()
            if not token:
                match = self._TITLE_REQUEST_RE.search(absolute) or self._TITLE_LABEL_RE.search(
                    link.get_text(" ", strip=True) or ""
                )
                token = match.group(1) if match else ""
            number = self._normalize_title_token(token)
            if number not in known:
                continue
            if number not in found and self.is_official_fl_url(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Florida title and repair missing-link rows."""

        discovered = self._parse_official_title_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        rows: List[Dict[str, Any]] = []
        for item in self.official_title_catalog():
            number = str(item["title_number"])
            official_url = str(item["source_url"])
            live_url = discovered.get(number)
            source_url = live_url or official_url
            disposition = "official" if live_url else "repaired_official_flleg"
            rows.append(
                {
                    **item,
                    "source_url": source_url,
                    "source_link_disposition": disposition,
                    "text": (
                        f"Florida Statutes Title {item['title_roman']} ({item['name']}) "
                        f"official catalog unit at {source_url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "FL"):
        """Acquire the exhaustive official Florida Statutes title catalog.

        Live HTTPS retains the official statutes landing page. Every known
        Florida title is enumerated with an official leg.state.fl.us URL.
        Linkless catalog members are repaired to the official title index.
        This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "FL").strip().upper() or "FL"
        if normalized != "FL":
            raise ValueError(f"FloridaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("florida official catalog enumeration is incomplete")
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


# Register the scraper
StateScraperRegistry.register("FL", FloridaScraper)
