"""Scraper for Vermont state laws.

This module contains the scraper for Vermont statutes from the official state legislative website.
"""

import json
import os
import re
import ssl
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class VermontScraper(BaseStateScraper):
    """Scraper for Vermont state laws from https://legislature.vermont.gov"""

    OFFICIAL_DOMAIN = "legislature.vermont.gov"
    OFFICIAL_ENTRY_PATH = "/statutes/"
    OFFICIAL_ENTRY_URL = "https://legislature.vermont.gov/statutes/"
    _VT_TITLE_HREF_RE = re.compile(
        r"/statutes/title/(?P<title>[0-9]{1,2}[A-Za-z]?)/?$",
        re.IGNORECASE,
    )
    _VT_TITLE_LABEL_RE = re.compile(
        r"\bTitle\s+(?P<title>\d{1,2}[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    _VT_CONTINUATION_RE = re.compile(
        r"\b(next|continue|more titles|page\s+\d+)\b",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Legislature"),
        ("3", "Executive"),
        ("4", "Judiciary"),
        ("5", "Aeronautics and Surface Transportation"),
        ("6", "Agriculture"),
        ("7", "Alcoholic Beverages, Cannabis, and Tobacco"),
        ("8", "Banking and Insurance"),
        ("9", "Commerce and Trade"),
        ("9A", "Uniform Commercial Code"),
        ("10", "Conservation and Development"),
        ("10A", "National Forest Lands"),
        ("11", "Corporations, Partnerships and Associations"),
        ("11A", "Vermont Business Corporations"),
        ("11B", "Nonprofit Corporations"),
        ("11C", "Mutual Benefit Enterprises"),
        ("12", "Court Procedure"),
        ("13", "Crimes and Criminal Procedure"),
        ("14", "Decedents' Estates and Fiduciary Relations"),
        ("14A", "Trusts"),
        ("15", "Domestic Relations"),
        ("15A", "Adoption Act"),
        ("15B", "Uniform Interstate Family Support Act"),
        ("15C", "Parentage Proceedings"),
        ("16", "Education"),
        ("16A", "The Vermont State Colleges"),
        ("17", "Elections"),
        ("18", "Health"),
        ("19", "Highways"),
        ("20", "Internal Security and Public Safety"),
        ("21", "Labor"),
        ("22", "Libraries, History, and Information Technology"),
        ("23", "Motor Vehicles"),
        ("24", "Municipal and County Government"),
        ("24A", "Municipal Charters"),
        ("25", "Navigation and Waters"),
        ("26", "Professions and Occupations"),
        ("27", "Property"),
        ("27A", "Uniform Common Interest Ownership Act"),
        ("28", "Public Institutions and Corrections"),
        ("29", "Public Property and Supplies"),
        ("30", "Public Service"),
        ("31", "Recreation and Sports"),
        ("32", "Taxation and Finance"),
        ("33", "Human Services"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)
    
    def get_base_url(self) -> str:
        """Return the base URL for Vermont's legislative website."""
        return "https://legislature.vermont.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Vermont."""
        return [{
            "name": "Vermont Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Vermont's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        if official:
            return official[:limit] if limit is not None else official

        if limit is not None:
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
            if direct:
                return direct[:limit]

        max_sections = limit if limit is not None else 1000000
        return await self._generic_scrape(
            code_name,
            code_url,
            "Vt. Stat. Ann.",
            max_sections=max_sections,
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
            f"{self.get_base_url()}/statutes/section/01/001/00001",
            f"{self.get_base_url()}/statutes/section/13/053/02301",
        ]
        return await self._scrape_section_urls(code_name, [(url, "") for url in section_urls], max_statutes=max_statutes)

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        title_links = await self._discover_title_links()
        self.logger.info("Vermont official index: discovered %s title links", len(title_links))
        statutes: List[NormalizedStatute] = []
        checkpoint = _VermontCheckpoint(self.state_code)
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "Vermont official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
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
                        "Vermont official index: title=%s chapter=%s/%s sections=%s statutes_so_far=%s",
                        title_label or title_url,
                        chapter_index,
                        len(chapter_links),
                        len(section_links),
                        len(statutes),
                    )
                parsed = await self._scrape_section_urls(
                    code_name,
                    section_links,
                    max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                )
                statutes.extend(parsed)
                checkpoint.maybe_write(statutes, title_label=title_label or title_url, chapter_label=chapter_label or chapter_url)
        checkpoint.write(statutes, title_label="complete", chapter_label="complete")
        return statutes[:limit] if limit is not None else statutes

    async def _discover_title_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/statutes/"
        payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            if not re.search(r"/statutes/title/[0-9A-Za-z]+/?$", href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=20)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            if not re.search(r"/statutes/chapter/[0-9A-Za-z]+/[0-9A-Za-z]+/?$", href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            if not re.search(r"/statutes/section/[0-9A-Za-z]+/[0-9A-Za-z]+/[0-9A-Za-z]+/?$", href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for source_url, section_label in section_urls:
            if limit is not None and len(statutes) >= limit:
                break
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=15)
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            main = soup.find(id="main-content") or soup
            for tag in main(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            text = self._normalize_legal_text(main.get_text(" ", strip=True))
            match = re.search(r"\bCite as:\s*([0-9A-Za-z.]+)\s+V\.S\.A\.\s+§\s*([0-9A-Za-z.-]+)", text)
            title_number = match.group(1) if match else ""
            section_number = match.group(2) if match else self._derive_section_number_from_url(source_url)
            heading = main.find(["h1", "h2", "h3"]) or soup.find(["h1", "h2", "h3"])
            section_name = heading.get_text(" ", strip=True) if heading else (section_label or f"Section {section_number}")
            bold = main.find("b")
            if bold:
                section_name = bold.get_text(" ", strip=True)
            if len(text) < 240 or not section_number:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=title_number or None,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=source_url,
                    official_cite=f"{title_number} V.S.A. § {section_number}" if title_number else f"Vt. Stat. Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_vermont_statutes_html", "skip_hydrate": True},
                )
            )
        return statutes

    def official_title_slug(self, title_number: Any) -> str:
        text = str(title_number or "").strip()
        match = re.match(r"^0*(\d{1,2})([A-Za-z]?)$", text)
        if not match:
            return text
        number, suffix = match.group(1), match.group(2).upper()
        return f"{int(number):02d}{suffix}"

    def official_title_url(self, title_number: Any) -> str:
        slug = self.official_title_slug(title_number)
        return f"{self.get_base_url()}/statutes/title/{slug}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Vermont Statutes Annotated title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"vt:title-{str(number).lower()}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Vermont Statutes Annotated Title {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith("." + self.OFFICIAL_DOMAIN)

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-vermont-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
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

    def _normalize_title_number(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        match = re.match(r"^0*(\d{1,2}[A-Z]?)$", text)
        return match.group(1) if match else ""

    def _parse_continuation_links(self, html: bytes, page_url: str) -> List[str]:
        found: List[str] = []
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            rel = " ".join(link.get("rel") or []).lower()
            if not href:
                continue
            if "next" not in rel and not self._VT_CONTINUATION_RE.search(label):
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            if absolute in seen or not self._host_is_official(absolute):
                continue
            if absolute.rstrip("/") == str(page_url or "").rstrip("/"):
                continue
            seen.add(absolute)
            found.append(absolute)
        return found

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
            match = self._VT_TITLE_HREF_RE.search(absolute) or self._VT_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = self._normalize_title_number(match.group("title"))
            if not number or number in found:
                continue
            if number not in known:
                known.add(number)
            if self._host_is_official(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Vermont Statutes Annotated title."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        known = {str(row["title_number"]) for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_vtleg"
        for number, url in discovered.items():
            if number in known:
                continue
            rows.append(
                {
                    "canonical_key": f"vt:title-{number.lower()}",
                    "title_number": number,
                    "name": f"Title {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Vermont Statutes Annotated Title {number} "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        rows.sort(key=lambda item: self._title_sort_key(str(item.get("title_number") or "")))
        return rows

    def _title_sort_key(self, number: str) -> Tuple[int, int, str]:
        match = re.match(r"^(\d+)(?:\.(\d+))?([A-Za-z]+)?$", str(number or "").strip())
        if not match:
            return (9999, 0, str(number or ""))
        return (int(match.group(1)), int(match.group(2) or 0), (match.group(3) or "").upper())

    def _collect_official_index_pages(self) -> Tuple[bytes, List[str]]:
        visited: List[str] = []
        seen: set[str] = set()
        pending = [self.OFFICIAL_ENTRY_URL]
        combined = b""
        while pending:
            url = pending.pop(0)
            if url in seen:
                continue
            seen.add(url)
            visited.append(url)
            html = self._official_http_get(url)
            if html:
                combined = html if not combined else combined + b"\n" + html
            for continuation in self._parse_continuation_links(html, url):
                if continuation not in seen:
                    pending.append(continuation)
            if len(visited) >= 32:
                break
        return combined, [item for item in pending if item not in seen]

    def fetch_official(self, code: str = "VT"):
        """Acquire the exhaustive official Vermont Statutes Annotated catalog.

        Live HTTPS retains the official legislature.vermont.gov statute index.
        Every known title is enumerated with an official URL. Continuation
        pages are exhausted. This hook never returns fixture bytes, never
        promotes a partial scrape checkpoint, and never uses secondary hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "VT").strip().upper() or "VT"
        if normalized != "VT":
            raise ValueError(f"VermontScraper cannot acquire {normalized}")
        html, remaining = self._collect_official_index_pages()
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "vermont official catalog enumeration rejected incomplete "
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
            "unvisited_continuation_links": list(remaining),
            "visited_index_units": len(rows),
        }
        if remaining:
            frontier["closed"] = False
            frontier["pagination_closed"] = False
            frontier["toc_exhausted"] = False
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        self.last_official_checkpoint = {
            "partial": False,
            "promoted_success": False,
            "completion_basis": "source_frontier",
        }
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
StateScraperRegistry.register("VT", VermontScraper)


class _VermontCheckpoint:
    """Best-effort partial progress checkpoint for Vermont's long corpus crawl."""

    def __init__(self, state_code: str) -> None:
        raw_dir = str(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR") or "").strip()
        if not raw_dir:
            self.path: Optional[Path] = None
        else:
            self.path = Path(raw_dir).expanduser().resolve() / f"STATE-{state_code.upper()}-partial.json"
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_code = state_code.upper()
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
        if not self.path or not statutes:
            return
        payload = {
            "state_code": self.state_code,
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
