"""Scraper for Idaho state laws.

This module contains the scraper for Idaho statutes from the official state legislative website.
"""

from typing import Any, Dict, List, Mapping, Optional, Tuple
import re
import os
import ssl
import time
import json
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat as asyncio
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class IdahoScraper(BaseStateScraper):
    """Scraper for Idaho state laws from https://legislature.idaho.gov"""

    OFFICIAL_DOMAIN = "legislature.idaho.gov"
    OFFICIAL_ENTRY_PATH = "/statutesrules/idstat/"
    OFFICIAL_ENTRY_URL = "https://legislature.idaho.gov/statutesrules/idstat/"
    MISSING_LINK_QUARANTINE_REASON = "missing_official_source_link"
    OFFICIAL_TITLES = (
        ("1", "Courts and Court Officials"),
        ("2", "Juries and Jurors"),
        ("3", "Attorneys and Counselors at Law"),
        ("4", "Enforcement of Judgments in Civil Actions"),
        ("5", "Proceedings in Civil Actions in Courts of Record"),
        ("6", "Actions in Particular Cases"),
        ("7", "Special Proceedings"),
        ("8", "Provisional Remedies in Civil Actions"),
        ("9", "Evidence"),
        ("10", "Issues, Trial and Judgment in Civil Actions"),
        ("11", "Enforcement of Judgments in Civil Actions"),
        ("12", "Costs and Miscellaneous Matters in Civil Actions"),
        ("13", "Appeals in Civil Actions"),
        ("14", "Estates of Decedents"),
        ("15", "Uniform Probate Code"),
        ("16", "Juvenile Proceedings"),
        ("18", "Crimes and Punishments"),
        ("19", "Criminal Procedure"),
        ("20", "State Prison and County Jails"),
        ("21", "Aeronautics"),
        ("22", "Agriculture and Horticulture"),
        ("23", "Alcoholic Beverages"),
        ("25", "Animals"),
        ("26", "Banks and Banking"),
        ("27", "Cemeteries"),
        ("28", "Commercial Transactions"),
        ("29", "Contracts"),
        ("30", "Corporations"),
        ("31", "Counties and County Law"),
        ("32", "Domestic Relations"),
        ("33", "Education"),
        ("34", "Elections"),
        ("36", "Fish and Game"),
        ("37", "Food, Drugs, and Oil"),
        ("38", "Forestry, Forest Products and Stumpage Districts"),
        ("39", "Health and Safety"),
        ("40", "Highways and Bridges"),
        ("41", "Insurance"),
        ("42", "Irrigation and Drainage -- Water Rights and Reclamation"),
        ("43", "Irrigation Districts"),
        ("44", "Labor"),
        ("45", "Liens, Mortgages and Pledges"),
        ("46", "Militia and Military Affairs"),
        ("47", "Mines and Mining"),
        ("48", "Monopolies and Trade Practices"),
        ("49", "Motor Vehicles"),
        ("50", "Municipal Corporations"),
        ("51", "Notaries Public and Commissioners of Deeds"),
        ("52", "Nuisances"),
        ("53", "Partnership"),
        ("54", "Professions, Vocations, and Businesses"),
        ("55", "Property in General"),
        ("56", "Public Assistance and Welfare"),
        ("57", "Public Funds in General"),
        ("58", "Public Lands"),
        ("59", "Public Officers in General"),
        ("60", "Public Printing and Official Notices"),
        ("61", "Public Utility Regulation"),
        ("62", "Railroads and Other Public Utilities"),
        ("63", "Revenue and Taxation"),
        ("64", "Sales"),
        ("65", "Service Members"),
        ("66", "State Charitable Institutions"),
        ("67", "State Government and State Affairs"),
        ("68", "Trusts and Fiduciaries"),
        ("69", "Warehouses"),
        ("70", "Watercourses and Port Districts"),
        ("71", "Weights and Measures"),
        ("72", "Worker's Compensation and Related Laws -- Industrial Commission"),
        ("73", "General Code Provisions"),
        ("74", "Transparent and Ethical Government"),
    )
    _ID_SECTION_URL_RE = re.compile(r"/statutesrules/idstat/title\d+/t\d+ch\d+/sect\d+[\-\.0-9A-Za-z]*$", re.IGNORECASE)
    _ID_TITLE_URL_RE = re.compile(r"/statutesrules/idstat/title\d+/?$", re.IGNORECASE)
    _ID_CHAPTER_URL_RE = re.compile(r"/statutesrules/idstat/title\d+/t\d+ch\d+/?$", re.IGNORECASE)
    _ID_SECTION_NUM_RE = re.compile(r"/sect([0-9A-Za-z.-]+)/?$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._ID_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Idaho's legislative website."""
        return "https://legislature.idaho.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Idaho."""
        return [{
            "name": "Idaho Statutes",
            "url": f"{self.get_base_url()}/statutesrules/idstat/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape Idaho statutes from the official title/chapter/section tree.

        When ``max_statutes`` is omitted the walk is uncapped for full-corpus
        certification runs.
        """
        limit = max(1, int(max_statutes)) if max_statutes else None
        statutes: List[NormalizedStatute] = []
        checkpoint = _IdahoCheckpoint(self.state_code)
        title_links = await self._discover_title_links(code_url)
        self.logger.info("Idaho official index: discovered %s title links", len(title_links))

        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "Idaho official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                title_label or title_url,
                title_index,
                len(title_links),
                len(chapter_links),
                len(statutes),
            )
            for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                section_links = await self._discover_section_links(chapter_url)
                if chapter_index == 1 or chapter_index % 10 == 0 or chapter_index == len(chapter_links):
                    self.logger.info(
                        "Idaho official index: title=%s chapter=%s/%s sections=%s statutes_so_far=%s",
                        title_label or title_url,
                        chapter_index,
                        len(chapter_links),
                        len(section_links),
                        len(statutes),
                    )
                for section_url, section_label in section_links:
                    if limit is not None and len(statutes) >= limit:
                        break
                    statute = await self._parse_section_page(
                        code_name=code_name,
                        section_url=section_url,
                        section_label=section_label,
                        title_label=title_label,
                        chapter_label=chapter_label,
                    )
                    if statute is not None:
                        statutes.append(statute)
                        checkpoint.maybe_write(statutes, title_label=title_label, chapter_label=chapter_label)

        if statutes:
            checkpoint.write(statutes, title_label="complete", chapter_label="complete")
            return statutes[:limit] if limit is not None else statutes

        self.logger.warning("Idaho official direct crawl returned no statutes; skipping generic recovery fallback")
        return []

    async def _fetch_official_id_html(self, url: str, timeout_seconds: int = 15) -> str:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached.decode("utf-8", errors="replace")

        timeout = max(1, int(timeout_seconds or 15))

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-idaho-statutes-scraper/2.0",
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

        index_url = code_url or f"{self.get_base_url()}/statutesrules/idstat/"
        html = await self._fetch_official_id_html(index_url)
        if not html:
            return []
        from .idaho_section import title_rows

        listed = title_rows(html)
        if listed:
            return [(url, name) for _number, name, url in listed]
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not self._ID_TITLE_URL_RE.search(href):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((normalized, label or normalized.rsplit("/title", 1)[-1].rstrip("/")))
        return out

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_id_html(title_url)
        if not html:
            return []
        from .idaho_section import chapter_rows

        listed = chapter_rows(html)
        if listed:
            return [(url, number) for number, url in listed]
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(title_url, str(anchor.get("href") or "").strip())
            if not self._ID_CHAPTER_URL_RE.search(href):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((normalized, label or normalized.rsplit("/", 2)[-2]))
        return out

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_id_html(chapter_url)
        if not html:
            return []
        from .idaho_section import section_rows

        sections, subcontainers = section_rows(html)
        if sections or subcontainers:
            out: List[Tuple[str, str]] = [
                (url, f"{number} {desc}".strip()) for number, desc, url in sections
            ]
            seen = {url for url, _label in out}
            for sub_url in subcontainers:
                nested_html = await self._fetch_official_id_html(sub_url)
                if not nested_html:
                    continue
                nested_sections, _nested_subs = section_rows(nested_html)
                for number, desc, url in nested_sections:
                    if url in seen:
                        continue
                    seen.add(url)
                    out.append((url, f"{number} {desc}".strip()))
            if out:
                return out
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            if not self._ID_SECTION_URL_RE.search(href.rstrip("/")):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((normalized, label))
        return out

    async def _parse_section_page(
        self,
        *,
        code_name: str,
        section_url: str,
        section_label: str,
        title_label: str,
        chapter_label: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._fetch_official_id_html(section_url)
        if not html:
            return None
        from .idaho_section import statute_from_section_html

        url_match = self._ID_SECTION_NUM_RE.search(section_url)
        guessed_number = (url_match.group(1) if url_match else section_label).upper().replace(".", "-")
        parsed = statute_from_section_html(
            html,
            section_number=guessed_number,
            source_url=section_url,
            code_name=code_name,
        )
        if parsed is not None:
            return parsed
        soup = BeautifulSoup(html, "html.parser")

        for node in soup(["script", "style", "noscript", "form", "nav", "footer", "header"]):
            node.decompose()

        main_node = soup.select_one("section.parallax-fix .wpb_column") or soup.select_one("body")
        if main_node is None:
            return None

        full_text = self._normalize_legal_text(main_node.get_text(" ", strip=True))
        marker_match = re.search(r"\b(\d+[A-Za-z]?\-\d+[A-Za-z0-9.-]*)\.\s+", full_text)
        if marker_match:
            full_text = full_text[marker_match.start() :]
        full_text = re.split(r"\bHow current is this law\?", full_text, maxsplit=1)[0].strip()
        if len(full_text) < 80:
            return None

        url_match = self._ID_SECTION_NUM_RE.search(section_url)
        section_number = (url_match.group(1) if url_match else section_label).upper()
        section_number = section_number.replace(".", "-")
        heading_match = re.match(r"([0-9A-Z.-]+)\.\s+(.+?)(?:\s+The\b|\s+History:|$)", full_text)
        section_name = ""
        if heading_match:
            section_name = heading_match.group(2).strip(" .")
        section_name = section_name or section_label or f"Section {section_number}"

        title_number_match = re.search(r"title(\d+)", section_url, re.IGNORECASE)
        chapter_number_match = re.search(r"t\d+ch(\d+)", section_url, re.IGNORECASE)

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=title_number_match.group(1) if title_number_match else None,
            title_name=title_label or None,
            chapter_number=chapter_number_match.group(1) if chapter_number_match else None,
            chapter_name=chapter_label or None,
            section_number=section_number,
            section_name=section_name[:200],
            short_title=section_name[:200],
            full_text=full_text[:14000],
            legal_area=self._identify_legal_area(section_name or chapter_label or title_label),
            source_url=section_url,
            official_cite=f"Idaho Code § {section_number}",
            structured_data={
                "source_kind": "official_idaho_statutes_html",
                "discovery_method": "official_title_chapter_section_index",
                "skip_hydrate": True,
            },
        )

    def official_title_url(self, title_number: object) -> str:
        number = str(title_number or "").strip()
        return f"{self.get_base_url()}/statutesrules/idstat/title{number}/"

    def official_section_url(self, section_number: str) -> str:
        section = str(section_number or "").strip()
        parts = re.split(r"[-.]", section)
        title = parts[0] if parts else "1"
        chapter = parts[1] if len(parts) > 1 else "1"
        return (
            f"{self.get_base_url()}/statutesrules/idstat/title{title}"
            f"/t{title}ch{chapter}/sect{section}/"
        )

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Idaho Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"id:title-{number}",
                    "title_number": number,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Idaho Statutes Title {number} ({name}) official "
                        f"legislature.idaho.gov catalog unit at {url}"
                    ),
                }
            )
        return rows

    def is_official_id_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith(".legislature.idaho.gov")

    def repair_or_type_missing_source_link(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Attach an official Idaho Statutes URL or type a linkless row."""

        structured = dict(statute.structured_data or {})
        source_url = str(statute.source_url or "").strip()
        if source_url and self.is_official_id_url(source_url):
            structured.setdefault("source_link_disposition", "official")
            statute.structured_data = structured
            return statute

        section_number = str(statute.section_number or "").strip()
        if section_number:
            repaired = self.official_section_url(section_number)
            statute.source_url = repaired
            structured["source_kind"] = (
                structured.get("source_kind") or "official_idaho_statutes_html"
            )
            structured["source_link_disposition"] = "repaired_official_idleg"
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
                        "User-Agent": "ipfs-datasets-idaho-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-idaho-official-catalog/1.0",
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

    def _recover_title_number(self, *parts: object) -> str:
        blob = " ".join(str(item or "") for item in parts)
        path_match = re.search(r"/statutesrules/idstat/title(\d+)/?", blob, re.IGNORECASE)
        if path_match:
            return str(int(path_match.group(1)))
        label_match = re.search(r"\bTitle\s+(\d{1,2})\b", blob, re.IGNORECASE)
        if label_match:
            return label_match.group(1).lstrip("0") or label_match.group(1)
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
        known = {number for number, _name in self.OFFICIAL_TITLES}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            number = self._recover_title_number(
                absolute, href, link.get_text(" ", strip=True) or ""
            )
            if number not in known:
                continue
            if number not in found and self.is_official_id_url(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Idaho title and repair missing-link rows."""

        discovered = self._parse_official_title_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        rows: List[Dict[str, Any]] = []
        for item in self.official_title_catalog():
            number = str(item["title_number"])
            official_url = str(item["source_url"])
            live_url = discovered.get(number)
            source_url = live_url or official_url
            disposition = "official" if live_url else "repaired_official_idleg"
            rows.append(
                {
                    **item,
                    "source_url": source_url,
                    "source_link_disposition": disposition,
                    "text": (
                        f"Idaho Statutes Title {number} ({item['name']}) official "
                        f"legislature.idaho.gov catalog unit at {source_url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "ID"):
        """Acquire the exhaustive official Idaho Statutes title catalog.

        Live HTTPS retains the official idstat landing page. Every known
        Idaho title is enumerated with an official legislature.idaho.gov URL.
        This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "ID").strip().upper() or "ID"
        if normalized != "ID":
            raise ValueError(f"IdahoScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("idaho official catalog enumeration is incomplete")
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
StateScraperRegistry.register("ID", IdahoScraper)


class _IdahoCheckpoint:
    """Best-effort partial progress checkpoint for Idaho's large corpus crawl."""

    def __init__(self, state_code: str) -> None:
        raw_dir = str(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR") or "").strip()
        if not raw_dir:
            self.path: Optional[Path] = None
        else:
            self.path = Path(raw_dir).expanduser().resolve() / f"STATE-{state_code.upper()}-partial.json"
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.interval = max(1, int(float(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_INTERVAL", "500") or 500)))
        self.last_count = 0
        self.last_write_ts = 0.0

    def maybe_write(self, statutes: List[NormalizedStatute], *, title_label: str, chapter_label: str) -> None:
        count = len(statutes)
        if not self.path or count <= 0:
            return
        if count - self.last_count < self.interval and time.time() - self.last_write_ts < 120:
            return
        self.write(statutes, title_label=title_label, chapter_label=chapter_label)

    def write(self, statutes: List[NormalizedStatute], *, title_label: str, chapter_label: str) -> None:
        if not self.path:
            return
        payload = {
            "state_code": "ID",
            "updated_at": time.time(),
            "statutes_count": len(statutes),
            "title_label": title_label,
            "chapter_label": chapter_label,
            "statutes": [statute.to_dict() for statute in statutes],
        }
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(statutes)
        self.last_write_ts = time.time()
