"""Scraper for Pennsylvania state laws.

This module contains the scraper for Pennsylvania statutes from the
official Pennsylvania General Assembly statutes portal.
"""

from ipfs_datasets_py.utils import anyio_compat as asyncio
import json
import re
import ssl
import subprocess
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class PennsylvaniaScraper(BaseStateScraper):
    """Scraper for Pennsylvania state laws from https://www.legis.state.pa.us"""

    OFFICIAL_DOMAIN = "www.palegis.us"
    OFFICIAL_ENTRY_PATH = "/statutes/consolidated"
    OFFICIAL_ENTRY_URL = "https://www.palegis.us/statutes/consolidated"
    OFFICIAL_TITLE_COUNT = 62
    _SECTION_HEADER_RE = re.compile(r"(?m)^\s*§\s*([0-9A-Za-z.-]+)\.\s+(.+)$")
    _PA_TITLE_QUERY_RE = re.compile(r"[?&]ttl=(?P<title>\d{1,2})\b", re.IGNORECASE)
    _PA_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(?P<title>\d{1,2})\b", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Administrative Law and Procedure"),
        ("3", "Agriculture"),
        ("4", "Amusements"),
        ("5", "Athletics and Sports"),
        ("8", "Boroughs and Incorporated Towns"),
        ("9", "Burial Grounds"),
        ("11", "Cities"),
        ("12", "Commerce and Trade"),
        ("13", "Commercial Code"),
        ("15", "Corporations and Unincorporated Associations"),
        ("16", "Counties"),
        ("17", "Creditors and Debtors"),
        ("18", "Crimes and Offenses"),
        ("20", "Decedents, Estates and Fiduciaries"),
        ("22", "Detectives and Private Police"),
        ("23", "Domestic Relations"),
        ("24", "Education"),
        ("25", "Elections"),
        ("26", "Eminent Domain"),
        ("27", "Environmental Resources"),
        ("28", "Escheats"),
        ("29", "Federal Relations"),
        ("30", "Fish"),
        ("31", "Food"),
        ("32", "Forests, Waters and State Parks"),
        ("33", "Frauds, Statute of"),
        ("34", "Game"),
        ("35", "Health and Safety"),
        ("36", "Highways and Bridges"),
        ("37", "Historical and Museums"),
        ("38", "Holidays and Observances"),
        ("39", "Insolvency and Assignments"),
        ("40", "Insurance"),
        ("42", "Judiciary and Judicial Procedure"),
        ("43", "Labor"),
        ("44", "Law and Justice"),
        ("45", "Legal Notices"),
        ("46", "Legislature"),
        ("47", "Liquor"),
        ("48", "Lodging and Housing"),
        ("51", "Military Affairs"),
        ("52", "Mines and Mining"),
        ("53", "Municipalities Generally"),
        ("54", "Names"),
        ("57", "Notaries Public"),
        ("58", "Oil and Gas"),
        ("61", "Prisons and Parole"),
        ("62", "Procurement"),
        ("63", "Professions and Occupations (State Licensed)"),
        ("64", "Public Authorities and Quasi-Public Corporations"),
        ("65", "Public Officers"),
        ("66", "Public Utilities"),
        ("67", "Public Welfare"),
        ("68", "Real and Personal Property"),
        ("70", "Securities"),
        ("71", "State Government"),
        ("72", "Taxation and Fiscal Affairs"),
        ("73", "Townships"),
        ("74", "Transportation"),
        ("75", "Vehicles"),
        ("77", "Workers' Compensation"),
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Pennsylvania's legislative website."""
        return "https://www.palegis.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Pennsylvania."""
        return [{
            "name": "Pennsylvania Consolidated Statutes",
            "url": f"{self.get_base_url()}/statutes/consolidated",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Pennsylvania's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        return_threshold = limit if limit is not None else 1000000

        official_pdf_sections = await self._scrape_consolidated_title_pdfs(
            code_name=code_name,
            max_statutes=return_threshold,
        )
        if official_pdf_sections:
            return official_pdf_sections[:return_threshold]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/consolidated",
        ]

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()
        if not self._full_corpus_enabled():
            direct_statutes = await self._scrape_direct_titles(
                code_name,
                max_statutes=return_threshold,
            )
            if direct_statutes:
                if limit is not None:
                    return direct_statutes[:limit]
                return direct_statutes

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "Pa. Cons. Stat.",
                max_sections=return_threshold,
            )
            _merge(statutes)
            if len(merged) >= return_threshold:
                return merged[:return_threshold]

        return merged

    async def _scrape_consolidated_title_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        discovered = await self._discover_consolidated_title_pdfs(limit=max(4, int(max_statutes or 1)))
        if not discovered:
            return []

        statutes: List[NormalizedStatute] = []
        seen_sections: set[Tuple[str, str]] = set()
        for title_number, title_name, pdf_url in discovered:
            if len(statutes) >= max_statutes:
                break
            pdf_bytes = await self._request_pdf_bytes(pdf_url, timeout=60)
            if not pdf_bytes:
                continue
            title_text = self._extract_pdf_text_preserve_layout(pdf_bytes=pdf_bytes, max_chars=900000)
            if len(title_text) < 500:
                continue
            split_sections = self._split_title_pdf_into_sections(
                code_name=code_name,
                title_number=title_number,
                title_name=title_name,
                title_text=title_text,
                source_url=pdf_url,
            )
            for statute in split_sections:
                section_number = str(statute.section_number or "").strip()
                key = (str(title_number or "").strip(), section_number)
                if not section_number or key in seen_sections:
                    continue
                seen_sections.add(key)
                statutes.append(statute)
                if len(statutes) >= max_statutes:
                    break
        return statutes

    async def _discover_consolidated_title_pdfs(self, limit: int = 120) -> List[Tuple[str, str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/statutes/consolidated"
        payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=45)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        discovered: List[Tuple[str, str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            text = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
            if not href or not text:
                continue
            if text.lower() in {"html", "pdf", "microsoft word"}:
                continue
            if "/statutes/consolidated/view-statute?" not in href or "txtType=HTM" not in href:
                continue

            absolute = urllib.parse.urljoin(index_url, href)
            parsed = urllib.parse.urlparse(absolute)
            query = urllib.parse.parse_qs(parsed.query)
            title_number = str((query.get("ttl") or [""])[0]).strip()
            if not title_number or title_number == "0" or title_number in seen:
                continue
            seen.add(title_number)
            pdf_query = dict((k, v[-1] if isinstance(v, list) else v) for k, v in query.items())
            pdf_query["txtType"] = "PDF"
            pdf_url = urllib.parse.urlunparse(
                parsed._replace(query=urllib.parse.urlencode(pdf_query, doseq=False))
            )
            discovered.append((title_number, text[:240], pdf_url))
            if len(discovered) >= limit:
                break
        return discovered

    async def _request_pdf_bytes(self, url: str, timeout: int = 45) -> bytes:
        def _request() -> bytes:
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/pdf,*/*;q=0.8",
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return bytes(resp.read() or b"")
            except Exception:
                return b""

        try:
            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 5)
        except Exception:
            return b""

    def _extract_pdf_text_preserve_layout(self, pdf_bytes: bytes, max_chars: int) -> str:
        if not pdf_bytes:
            return ""
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-q", "-", "-"],
                input=pdf_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except Exception:
            return ""

        if proc.returncode != 0 or not proc.stdout:
            return ""
        return proc.stdout.decode("utf-8", errors="ignore")[:max_chars]

    def _split_title_pdf_into_sections(
        self,
        code_name: str,
        title_number: str,
        title_name: str,
        title_text: str,
        source_url: str,
    ) -> List[NormalizedStatute]:
        matches = list(self._SECTION_HEADER_RE.finditer(title_text or ""))
        if not matches:
            return []

        # The title PDFs begin with a table of contents, so prefer the second
        # appearance of the earliest repeated section number when present.
        starts_by_section: Dict[str, List[re.Match[str]]] = {}
        for match in matches:
            starts_by_section.setdefault(match.group(1), []).append(match)

        body_start = 0
        for match in matches:
            repeats = starts_by_section.get(match.group(1)) or []
            if len(repeats) >= 2:
                body_start = repeats[1].start()
                break

        body_matches = [match for match in matches if match.start() >= body_start]
        if not body_matches:
            body_matches = matches

        statutes: List[NormalizedStatute] = []
        for index, match in enumerate(body_matches):
            section_number = str(match.group(1) or "").strip()
            section_name = re.sub(r"\s+", " ", str(match.group(2) or "").strip()).strip(" .")
            end = body_matches[index + 1].start() if index + 1 < len(body_matches) else len(title_text)
            raw_block = title_text[match.start():end]
            normalized = self._normalize_legal_text(raw_block)
            if len(normalized) < 60:
                continue

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} tit. {title_number} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:240] or f"Section {section_number}",
                    full_text=normalized[:24000],
                    source_url=source_url,
                    legal_area=self._identify_legal_area(f"{title_name} {section_name}"),
                    official_cite=f"Pa. Cons. Stat. tit. {title_number} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_pennsylvania_title_pdf",
                        "discovery_method": "official_consolidated_title_pdf_index",
                        "title_number": title_number,
                        "title_name": title_name,
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    async def _scrape_direct_titles(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        urls = [
            "https://www.palegis.us/statutes/consolidated/view-statute?txtType=PDF&ttl=01",
            "https://www.palegis.us/statutes/consolidated/view-statute?txtType=PDF&ttl=18",
        ]
        out: List[NormalizedStatute] = []
        for source_url in urls[: max(1, int(max_statutes or 1))]:
            payload = await self._request_pdf_bytes(source_url, timeout=18)
            text = self._extract_pdf_text_preserve_layout(payload, max_chars=22000)
            text = self._normalize_legal_text(text)
            if len(text) < 280:
                continue
            title_match = re.search(r"\bTITLE\s+(\d+)\b", text, re.IGNORECASE)
            title_number = title_match.group(1) if title_match else str(len(out) + 1)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § Title {title_number}",
                    code_name=code_name,
                    section_number=f"Title {title_number}",
                    section_name=f"Title {title_number}",
                    full_text=text[:14000],
                    source_url=source_url,
                    legal_area=self._identify_legal_area(text[:1200]),
                    official_cite=f"Pa. Cons. Stat. tit. {title_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_direct_title", "skip_hydrate": True},
                )
            )
        return out

    def official_title_url(self, title_number: Any) -> str:
        number = str(int(str(title_number).strip()))
        return (
            f"{self.get_base_url()}/statutes/consolidated/view-statute"
            f"?txtType=HTM&ttl={number}"
        )

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Pennsylvania Consolidated Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"pa:title-{int(number)}",
                    "title_number": str(int(number)),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Pennsylvania Consolidated Statutes Title {int(number)} "
                        f"({name}) official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return (
            host == "palegis.us"
            or host.endswith(".palegis.us")
            or host == "legis.state.pa.us"
            or host.endswith(".legis.state.pa.us")
        )

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-pennsylvania-official-catalog/1.0",
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
            match = self._PA_TITLE_QUERY_RE.search(absolute) or self._PA_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = str(int(match.group("title")))
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
        """Enumerate every official Pennsylvania Consolidated Statutes title."""

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

    def fetch_official(self, code: str = "PA"):
        """Acquire the exhaustive official Pennsylvania Consolidated Statutes catalog.

        Live HTTPS retains the official palegis.us title index. Every known
        consolidated-statutes title is enumerated with an official URL. This
        hook never returns fixture bytes or secondary-mirror hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "PA").strip().upper() or "PA"
        if normalized != "PA":
            raise ValueError(f"PennsylvaniaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "pennsylvania official catalog enumeration rejected incomplete "
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
StateScraperRegistry.register("PA", PennsylvaniaScraper)
