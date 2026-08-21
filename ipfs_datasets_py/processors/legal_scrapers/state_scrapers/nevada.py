"""Scraper for Nevada state laws.

This module contains the scraper for Nevada statutes from the official state legislative website.
"""

import hashlib
import json
import re
import ssl
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class NevadaScraper(BaseStateScraper):
    """Scraper for Nevada state laws from https://www.leg.state.nv.us"""

    OFFICIAL_DOMAIN = "www.leg.state.nv.us"
    OFFICIAL_ENTRY_PATH = "/NRS/"
    OFFICIAL_ENTRY_URL = "https://www.leg.state.nv.us/NRS/"
    OFFICIAL_TITLE_COUNT = 59
    MISSING_LINK_DISPOSITION = "missing_official_source_link"
    LINKLESS_BUCKET_DISPOSITION = "linkless_bucket_row"
    last_official_quarantines: List[Dict[str, str]] = []
    _NRS_CHAPTER_HREF_RE = re.compile(r"^NRS-\d{3}[A-Z]?\.html$", re.IGNORECASE)
    _NRS_CHAPTER_ABS_RE = re.compile(
        r"/NRS/NRS-(?P<chapter>\d{1,4}[A-Z]?)\.html",
        re.IGNORECASE,
    )
    _NRS_SECTION_NUMBER_RE = re.compile(r"^\d+[A-Z]?\.\d+(?:\.\d+)?[A-Z]?$")
    _NRS_REF_RE = re.compile(
        r"\b(?:NRS[-\s]*)?(?P<chapter>\d{1,4}[A-Z]?)(?:\.(?P<section>\d+(?:\.\d+)*[A-Z]?))?\b",
        re.IGNORECASE,
    )
    _NRS_LINKLESS_LABEL_RE = re.compile(
        r"\b(?:NRS|Title\s+\d+|Chapter\s+\d+)",
        re.IGNORECASE,
    )
    _SECONDARY_HOST_MARKERS = (
        "justia.com",
        "findlaw.com",
        "unicourt.github.io",
        "law.cornell.edu",
    )
    OFFICIAL_TITLE_FIRST_CHAPTER = {
        1: "1", 2: "7", 3: "28", 4: "47", 5: "62A", 6: "63", 7: "75", 8: "97",
        9: "106", 10: "123", 11: "132", 12: "159", 13: "169", 14: "193",
        15: "209", 16: "217", 17: "231", 18: "240", 19: "244", 20: "277",
        21: "281", 22: "293", 23: "313", 24: "328", 25: "332", 26: "341",
        27: "353", 28: "361", 29: "378", 30: "381", 31: "386", 32: "389",
        33: "403", 34: "412", 35: "422", 36: "439", 37: "463", 38: "469",
        39: "475", 40: "481", 41: "488", 42: "493", 43: "497", 44: "512",
        45: "527", 46: "532", 47: "552", 48: "563", 49: "573", 50: "590",
        51: "598", 52: "607", 53: "623", 54: "657", 55: "679A", 56: "701",
        57: "706", 58: "714", 59: "722",
    }
    OFFICIAL_TITLE_NAMES = {
        1: "State Judicial Department",
        2: "Civil Practice",
        3: "Remedies; Special Actions and Proceedings",
        4: "Witnesses and Evidence",
        5: "Juvenile Justice",
        6: "Children",
        7: "Business Associations; Securities; Commodities",
        8: "Commercial Instruments and Transactions",
        9: "Security Instruments of Public Utilities; Mortgages; Deeds of Trust; Other Liens",
        10: "Property Rights and Transactions",
        11: "Domestic Relations",
        12: "Wills and Estates of Deceased Persons",
        13: "Guardianships; Conservatorships; Trusts",
        14: "Procedure in Criminal Cases",
        15: "Crimes and Punishments",
        16: "Correctional Institutions; Aid to Victims of Crime",
        17: "State Legislative Department",
        18: "State Executive Department",
        19: "Miscellaneous Matters Related to Government and Public Affairs",
        20: "Counties and Townships: Formation, Government and Officers",
        21: "Cities and Towns",
        22: "Cooperative Agreements by Public Agencies; Planning and Zoning",
        23: "Public Officers and Employees",
        24: "Elections",
        25: "Public Organizations for Community Service",
        26: "Public Lands",
        27: "Public Property and Purchasing",
        28: "Public Financial Administration",
        29: "Revenue and Taxation",
        30: "Public Borrowing and Obligations",
        31: "Public Financial Administration",
        32: "Education",
        33: "Highways; Roads; Bridges; Parks; Outdoor Recreation",
        34: "Military Affairs and Civil Emergencies",
        35: "Highways; Vehicles; Watercraft; Aviation",
        36: "Public Health and Safety",
        37: "Veterans; Privileges; Benefits",
        38: "Public Welfare",
        39: "Mental Health",
        40: "Public Health and Safety",
        41: "Gaming; Horse Racing; Sporting Events",
        42: "Agriculture",
        43: "Public Safety; Vehicles; Watercraft",
        44: "Aeronautics",
        45: "Wildlife",
        46: "Mines and Minerals",
        47: "Forestry; Fire Protection",
        48: "Water",
        49: "Agriculture",
        50: "Animals",
        51: "Food and Other Commodities",
        52: "Trade Regulations and Practices",
        53: "Labor and Industrial Relations",
        54: "Professions, Occupations and Businesses",
        55: "Banks and Related Organizations",
        56: "Insurance",
        57: "Other Financial Institutions",
        58: "Energy; Public Utilities and Similar Entities",
        59: "Electronic Records and Transactions",
    }
    
    def get_base_url(self) -> str:
        """Return the base URL for Nevada's legislative website."""
        return "https://www.leg.state.nv.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Nevada."""
        return [{
            "name": "Nevada Revised Statutes",
            "url": f"{self.get_base_url()}/NRS/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Nevada's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        official = self._filter_official_host_statutes(official)
        if official:
            return official if limit is None else official[: int(limit)]

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=max(1, int(limit or 2)),
            )
            direct = self._filter_official_host_statutes(direct)
            if direct:
                return direct if limit is None else direct[: int(limit)]

        if self._full_corpus_enabled() and max_statutes is None:
            return []
        if any(marker in str(code_url).lower() for marker in self._SECONDARY_HOST_MARKERS):
            return []
        fallback_limit = max(10, int(limit or 40))
        generic = await self._generic_scrape(
            code_name, code_url, "Nev. Rev. Stat.", max_sections=fallback_limit
        )
        return self._filter_official_host_statutes(generic)

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 2) -> List[NormalizedStatute]:
        seeds = [
            ("1.010", f"{self.get_base_url()}/NRS/NRS-001.html"),
            ("200.010", f"{self.get_base_url()}/NRS/NRS-200.html"),
        ]
        chapter_rows = await self._scrape_chapter_pages(
            code_name,
            [url for _, url in seeds[: max(1, int(max_statutes or 1))]],
            max_statutes=max_statutes,
            discovery_method="official_seed_chapter_inline_sections",
        )
        return chapter_rows[: max(1, int(max_statutes or 1))]

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        chapter_pages = await self._discover_chapter_pages()
        self.logger.info("Nevada official index: discovered %s chapter pages", len(chapter_pages))
        return await self._scrape_chapter_pages(
            code_name,
            chapter_pages,
            max_statutes=max_statutes,
            discovery_method="official_title_chapter_inline_sections",
        )

    async def _discover_chapter_pages(self) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/NRS/"
        html = await self._request_text_direct(index_url, timeout=30)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not self._NRS_CHAPTER_HREF_RE.match(href):
                continue
            chapter_url = f"{self.get_base_url()}/NRS/{href.lstrip('/')}"
            if chapter_url in seen:
                continue
            seen.add(chapter_url)
            out.append(chapter_url)
        return out

    async def _scrape_chapter_pages(
        self,
        code_name: str,
        chapter_pages: List[str],
        *,
        max_statutes: Optional[int],
        discovery_method: str,
    ) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for chapter_index, chapter_url in enumerate(chapter_pages, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            remaining = None if limit is None else max(0, limit - len(statutes))
            if remaining is not None and remaining <= 0:
                break
            chapter_rows = await self._extract_sections_from_chapter_page(
                code_name,
                chapter_url,
                discovery_method=discovery_method,
                max_statutes=remaining,
            )
            statutes.extend(chapter_rows)
            if chapter_index == 1 or chapter_index % 25 == 0 or chapter_index == len(chapter_pages):
                self.logger.info(
                    "Nevada official index: chapter=%s/%s yielded=%s statutes_so_far=%s",
                    chapter_index,
                    len(chapter_pages),
                    len(chapter_rows),
                    len(statutes),
                )
        return statutes[:limit] if limit is not None else statutes

    async def _extract_sections_from_chapter_page(
        self,
        code_name: str,
        chapter_url: str,
        *,
        discovery_method: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        if max_statutes is not None and int(max_statutes) <= 0:
            return []
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._request_text_direct(chapter_url, timeout=35)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        paragraphs = soup.find_all("p")
        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        current: Dict[str, object] | None = None

        def _flush_current() -> None:
            nonlocal current
            if not current:
                return
            section_number = str(current.get("section_number") or "").strip()
            section_name = str(current.get("section_name") or "").strip()
            body_parts = [str(item).strip() for item in current.get("body_parts") or [] if str(item).strip()]
            if not section_number or not body_parts:
                current = None
                return
            full_text = self._normalize_legal_text(" ".join(body_parts))
            if len(full_text) < 120:
                current = None
                return
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=(section_name or f"NRS {section_number}")[:200],
                    full_text=full_text[:14000],
                    legal_area=self._identify_legal_area(section_name or full_text[:800]),
                    source_url=f"{chapter_url}#{current.get('anchor')}" if current.get("anchor") else chapter_url,
                    official_cite=f"Nev. Rev. Stat. § {section_number}",
                    structured_data={
                        "source_kind": "official_nevada_revised_statutes_html",
                        "discovery_method": discovery_method,
                        "chapter_url": chapter_url,
                        "skip_hydrate": True,
                    },
                )
            )
            current = None

        for paragraph in paragraphs:
            if limit is not None and len(out) >= limit:
                break
            anchor = paragraph.find("a", attrs={"name": True})
            section_span = paragraph.find("span", class_="Section")
            if anchor is not None and section_span is not None:
                _flush_current()
                section_number = self._normalize_legal_text(section_span.get_text(" ", strip=True))
                if not self._NRS_SECTION_NUMBER_RE.match(section_number):
                    continue
                leadline = paragraph.find("span", class_="Leadline")
                section_name = self._normalize_legal_text(leadline.get_text(" ", strip=True)) if leadline else ""
                text = self._normalize_legal_text(paragraph.get_text(" ", strip=True))
                current = {
                    "anchor": str(anchor.get("name") or "").strip(),
                    "section_number": section_number,
                    "section_name": section_name,
                    "body_parts": [text] if text else [],
                }
                continue
            if current is None:
                continue
            css_classes = {str(value) for value in (paragraph.get("class") or [])}
            if "SectBody" not in css_classes:
                continue
            text = self._normalize_legal_text(paragraph.get_text(" ", strip=True))
            if text:
                cast_parts = current.setdefault("body_parts", [])
                if isinstance(cast_parts, list):
                    cast_parts.append(text)

        _flush_current()
        return out[:limit] if limit is not None else out

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        def _request() -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("windows-1252", errors="replace")
            except Exception:
                return ""

        try:
            import asyncio

            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""

    def official_chapter_url(self, chapter: Any) -> str:
        token = str(chapter or "").strip().upper()
        if not token:
            return self.OFFICIAL_ENTRY_URL
        if token.isdigit():
            filename = f"NRS-{int(token):03d}.html"
        else:
            match = re.match(r"(\d+)([A-Z]+)$", token)
            if match:
                filename = f"NRS-{int(match.group(1)):03d}{match.group(2)}.html"
            else:
                filename = f"NRS-{token}.html"
        return f"{self.get_base_url()}/NRS/{filename}"

    def official_title_url(self, title_number: Any) -> str:
        first = self.OFFICIAL_TITLE_FIRST_CHAPTER.get(int(title_number), str(title_number))
        return self.official_chapter_url(first)

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Nevada Revised Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number in range(1, self.OFFICIAL_TITLE_COUNT + 1):
            url = self.official_title_url(number)
            name = self.OFFICIAL_TITLE_NAMES.get(number, f"Title {number}")
            rows.append(
                {
                    "canonical_key": f"nv:title-{number}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Nevada Revised Statutes Title {number} ({name}) official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-nevada-official-catalog/1.0",
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

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        if any(marker in host for marker in self._SECONDARY_HOST_MARKERS):
            return False
        return host == "leg.state.nv.us" or host.endswith(".leg.state.nv.us")

    def _filter_official_host_statutes(
        self, statutes: List[NormalizedStatute]
    ) -> List[NormalizedStatute]:
        return [
            statute
            for statute in statutes
            if self._host_is_official(str(statute.source_url or ""))
        ]

    def _chapter_from_text(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        href_match = self._NRS_CHAPTER_ABS_RE.search(text)
        if href_match:
            return href_match.group("chapter").upper().lstrip("0") or "0"
        ref = self._NRS_REF_RE.search(text)
        if not ref:
            return ""
        chapter = str(ref.group("chapter") or "").upper().lstrip("0")
        return chapter or ""

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        current_title = ""
        for node in soup.find_all(["a", "b", "strong", "h2", "h3", "h4", "p"]):
            label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
            title_match = re.search(r"\bTitle\s+(\d{1,2})\b", label, flags=re.IGNORECASE)
            if title_match:
                current_title = str(int(title_match.group(1)))
            href = str(node.get("href") or "").strip() if node.name == "a" else ""
            if not href or not current_title or current_title in found:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            if self._NRS_CHAPTER_ABS_RE.search(absolute) or self._NRS_CHAPTER_HREF_RE.match(href):
                found[current_title] = self.official_title_url(current_title)
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._NRS_CHAPTER_ABS_RE.search(absolute)
            if not match:
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            title_match = re.search(r"\bTitle\s+(\d{1,2})\b", label, flags=re.IGNORECASE)
            if title_match:
                number = str(int(title_match.group(1)))
                if number not in found:
                    found[number] = self.official_title_url(number)
        return found

    def classify_linkless_bucket_rows(
        self,
        material: Union[bytes, str, Sequence[Mapping[str, Any]]],
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, str]]]:
        """Replace NV linkless bucket rows with official NRS URLs or quarantine them.

        Accepts either a live/index HTML fragment or a sequence of bucket-style
        row mappings. Recoverable chapter identifiers are rewritten to
        ``https://www.leg.state.nv.us/NRS/NRS-XXX.html``. Remaining linkless
        material is quarantined with a typed disposition and evidence hash.
        """

        if isinstance(material, (bytes, bytearray, str)):
            return self._classify_linkless_html(material, page_url=page_url)
        repaired: List[Dict[str, str]] = []
        quarantines: List[Dict[str, str]] = []
        seen: set[str] = set()
        for index, raw in enumerate(list(material or []), start=1):
            if not isinstance(raw, Mapping):
                continue
            source_url = str(
                raw.get("source_url") or raw.get("url") or raw.get("href") or ""
            ).strip()
            label = str(
                raw.get("section_number")
                or raw.get("statute_id")
                or raw.get("citation")
                or raw.get("name")
                or raw.get("text")
                or raw.get("label")
                or ""
            ).strip()
            blob = " ".join(
                str(raw.get(key) or "")
                for key in (
                    "source_url",
                    "url",
                    "href",
                    "section_number",
                    "statute_id",
                    "citation",
                    "name",
                    "text",
                    "label",
                    "chapter",
                    "title",
                )
            )
            chapter = self._chapter_from_text(blob) or self._chapter_from_text(label)
            official_url = self.official_chapter_url(chapter) if chapter else ""
            official_already = bool(source_url) and self._host_is_official(source_url)
            if official_already and chapter:
                unit_id = f"nv:chapter-{chapter.lower()}"
                if unit_id in seen:
                    continue
                seen.add(unit_id)
                repaired.append(
                    {
                        "canonical_key": unit_id,
                        "chapter": chapter,
                        "source_url": source_url,
                        "label": label or f"NRS {chapter}",
                        "repair_source": "official_href",
                        "source_link_disposition": "official",
                        "text": (
                            f"Nevada Revised Statutes Chapter {chapter} official "
                            f"catalog unit at {source_url}"
                        ),
                    }
                )
                continue
            if chapter and official_url:
                unit_id = f"nv:chapter-{chapter.lower()}"
                if unit_id in seen:
                    continue
                seen.add(unit_id)
                repaired.append(
                    {
                        "canonical_key": unit_id,
                        "chapter": chapter,
                        "source_url": official_url,
                        "label": label or f"NRS {chapter}",
                        "repair_source": "repaired_from_linkless_row",
                        "source_link_disposition": "repaired_official_leginfo",
                        "text": (
                            f"Nevada Revised Statutes Chapter {chapter} official "
                            f"catalog unit at {official_url}"
                        ),
                    }
                )
                continue
            evidence_src = json.dumps(dict(raw), sort_keys=True, default=str)
            unit_id = f"nv:missing-{hashlib.sha256(evidence_src.encode('utf-8')).hexdigest()[:16]}"
            if unit_id in seen:
                continue
            seen.add(unit_id)
            quarantines.append(
                {
                    "unit_id": unit_id,
                    "reason": self.LINKLESS_BUCKET_DISPOSITION,
                    "label": (label or f"linkless bucket row {index}")[:240],
                    "page_url": page_url or source_url,
                    "evidence_sha256": hashlib.sha256(evidence_src.encode("utf-8")).hexdigest(),
                }
            )
        return {"repaired": repaired, "quarantines": quarantines}

    def _classify_linkless_html(
        self,
        html: Union[bytes, str],
        *,
        page_url: str,
    ) -> Dict[str, List[Dict[str, str]]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for official Nevada discovery") from exc

        payload = html.decode("utf-8", errors="replace") if isinstance(html, (bytes, bytearray)) else str(html or "")
        soup = BeautifulSoup(payload, "html.parser")
        repaired: List[Dict[str, str]] = []
        quarantines: List[Dict[str, str]] = []
        seen: set[str] = set()
        seen_quarantine: set[str] = set()

        def _record(chapter: str, label: str, source: str) -> None:
            chapter = str(chapter or "").strip().upper().lstrip("0") or ""
            if not chapter:
                return
            unit_id = f"nv:chapter-{chapter.lower()}"
            if unit_id in seen:
                return
            seen.add(unit_id)
            official_url = self.official_chapter_url(chapter)
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip() or f"NRS {chapter}"
            repaired.append(
                {
                    "canonical_key": unit_id,
                    "chapter": chapter,
                    "source_url": official_url,
                    "label": cleaned,
                    "repair_source": source,
                    "source_link_disposition": (
                        "official" if source == "official_href" else "repaired_official_leginfo"
                    ),
                    "text": (
                        f"Nevada Revised Statutes Chapter {chapter} official "
                        f"catalog unit at {official_url}"
                    ),
                }
            )

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            match = self._NRS_CHAPTER_ABS_RE.search(absolute) or self._NRS_CHAPTER_HREF_RE.match(href)
            if match:
                chapter = match.group("chapter") if hasattr(match, "lastindex") and match.lastindex else (
                    href[4:-5] if href.upper().startswith("NRS-") else self._chapter_from_text(absolute)
                )
                if hasattr(match, "groupdict") and match.groupdict().get("chapter"):
                    chapter = match.group("chapter")
                _record(chapter, label, "official_href")
                continue
            nearby = " ".join(
                str(item or "")
                for item in (href, link.get("onclick"), link.get("id"), label)
            )
            chapter = self._chapter_from_text(nearby)
            if chapter:
                _record(chapter, label, "repaired_from_attributes")

        for node in soup.find_all(["span", "td", "li", "div", "p"]):
            label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
            if not label or not self._NRS_LINKLESS_LABEL_RE.search(label):
                continue
            if node.find("a", href=True):
                continue
            chapter = self._chapter_from_text(
                " ".join(str(item or "") for item in (node.get("data-chapter"), node.get("id"), label))
            )
            if chapter:
                _record(chapter, label, "repaired_from_linkless_row")
                continue
            unit_id = f"nv:missing-{hashlib.sha256(label.encode('utf-8')).hexdigest()[:16]}"
            if unit_id in seen_quarantine:
                continue
            seen_quarantine.add(unit_id)
            quarantines.append(
                {
                    "unit_id": unit_id,
                    "reason": self.MISSING_LINK_DISPOSITION,
                    "label": label[:240],
                    "page_url": page_url or self.OFFICIAL_ENTRY_URL,
                    "evidence_sha256": hashlib.sha256(str(node).encode("utf-8")).hexdigest(),
                }
            )
        return {"repaired": repaired, "quarantines": quarantines}

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official NRS title and repair missing live links."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        return rows

    def fetch_official(self, code: str = "NV"):
        """Acquire the exhaustive official Nevada Revised Statutes title catalog.

        Live HTTPS retains the official NRS index. Every NRS title is
        enumerated with an official leg.state.nv.us URL. Linkless bucket
        rows are repaired to official chapter URLs or quarantined with a
        typed disposition. This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "NV").strip().upper() or "NV"
        self.last_official_quarantines = []
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("nevada official catalog enumeration is incomplete")
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "nevada official catalog enumeration rejected incomplete "
                "title reacquisition"
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
            "quarantines": list(self.last_official_quarantines),
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
            "nv_linkless_quarantines": list(self.last_official_quarantines),
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
StateScraperRegistry.register("NV", NevadaScraper)
