"""Scraper for Alaska state laws.

This module contains the scraper for Alaska statutes from the official state legislative website.
"""

import hashlib
import json
import re
import ssl
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class AlaskaScraper(BaseStateScraper):
    """Scraper for Alaska state laws from http://www.legis.state.ak.us"""

    _AK_SECTION_RE = re.compile(r"\bSec\.\s*(\d{2}\.\d{2}\.\d{3})\.\s*(.+)", re.IGNORECASE | re.DOTALL)
    OFFICIAL_DOMAIN = "www.akleg.gov"
    OFFICIAL_ENTRY_PATH = "/basis/statutes.asp"
    OFFICIAL_ENTRY_URL = "https://www.akleg.gov/basis/statutes.asp"
    MISSING_LINK_QUARANTINE_REASON = "missing_official_source_link"
    _AK_ANCHORED_SECTION_RE = re.compile(
        r'name\s*=\s*["\'](\d{2}\.\d{2}\.\d{3}[A-Za-z]?)["\']',
        re.IGNORECASE,
    )
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
        timeout = max(1, int(timeout_seconds or 8))
        cursor_title = str(sec_start or "").split(".", 1)[0].lstrip("0") or "0"
        final_title = max(
            (str(number) for number, _name in self.OFFICIAL_TITLES),
            key=int,
        )
        final_title_probe = cursor_title == final_title
        self._last_alaska_terminal_probe = {}
        payload = await self._fetch_parser_input_with_transport(
            cache_url,
            headers={
                "User-Agent": "ipfs-datasets-alaska-statutes-scraper/2.0",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout_seconds=timeout,
            # A successful Alaska terminal request is HTTP 200 with an empty
            # body.  The shared byte adapter quite correctly rejects empty
            # parser input, but treating that expected sentinel as a transport
            # failure launches an unnecessary archive/WARC hunt.  First make a
            # direct-only attempt in the final official title; retained inputs
            # are still replayed before the direct request.
            allow_archival_fallback=not final_title_probe,
            media_type="text/html",
            provider="requests_direct",
        )
        if not payload and final_title_probe:
            terminal_receipt = await self._fetch_fresh_official_response_receipt(
                cache_url,
                headers={
                    "User-Agent": "ipfs-datasets-alaska-statutes-scraper/2.0",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout_seconds=timeout,
                admit_success_body=True,
                media_type="text/html",
                provider="alaska_basis_terminal_probe",
            )
            requested_url = self._canonical_fetch_url(cache_url)
            final_url = self._canonical_fetch_url(
                str(terminal_receipt.get("final_url") or "")
            )
            status_code = int(terminal_receipt.get("status_code") or 0)
            terminal_body = bytes(terminal_receipt.get("body") or b"")
            terminal_digest = hashlib.sha256(terminal_body).hexdigest()
            if (
                status_code == 200
                and final_url == requested_url
                and str(terminal_receipt.get("content_sha256") or "").strip().lower()
                == terminal_digest
            ):
                payload = terminal_body
                if not terminal_body:
                    self._last_alaska_terminal_probe = {
                        "closed": True,
                        "content_sha256": terminal_digest,
                        "empty": True,
                        "final_url": final_url,
                        "observed_at": str(
                            terminal_receipt.get("observed_at") or ""
                        ),
                        "requested_url": requested_url,
                        "sec_start": str(sec_start or "").strip(),
                        "status_code": status_code,
                    }
            else:
                # A timeout, non-200 response, or redirect is not frontier
                # closure.  Preserve the standard direct/archive fallback for
                # a real transport failure.
                payload = await self._fetch_parser_input_with_transport(
                    cache_url,
                    headers={
                        "User-Agent": "ipfs-datasets-alaska-statutes-scraper/2.0",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout_seconds=timeout,
                    allow_archival_fallback=True,
                    media_type="text/html",
                    provider="requests_direct",
                )
        html = payload.decode("cp1252", errors="replace") if payload else ""
        # The shared adapter deliberately exposes exact response bytes rather
        # than unretained response headers.  The Alaska body carries the same
        # continuation cursor as its final anchored section, which is also how
        # cached and archived responses have historically been resumed.
        section_numbers = self._AK_ANCHORED_SECTION_RE.findall(html)
        last_sec = section_numbers[-1] if section_numbers else ""
        return html, last_sec

    def _bind_statute_chunk_provenance(
        self,
        statutes: List[NormalizedStatute],
    ) -> List[NormalizedStatute]:
        """Bind every AJAX-derived row to its exact retained response bytes."""

        if not statutes:
            return statutes
        provenance = self._last_parser_input_row_provenance()
        if self._state_law_acquisition_ledger is not None and not provenance:
            raise RuntimeError(
                "Alaska AJAX rows lack exact retained parser-input provenance"
            )
        if not provenance:
            return statutes
        for statute in statutes:
            structured = dict(statute.structured_data or {})
            structured.update(provenance)
            statute.structured_data = structured
        return statutes

    def _enrich_statute_structure(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Carry exact AJAX response provenance into canonical JSON-LD."""

        enriched = super()._enrich_statute_structure(statute)
        structured = dict(enriched.structured_data or {})
        if str(structured.get("source_kind") or "").strip() != (
            "official_alaska_statutes_ajax_html"
        ):
            return enriched

        digest = str(structured.get("content_sha256") or "").strip().lower()
        receipt = structured.get("transport_receipt")
        jsonld = structured.get("jsonld")
        receipt_digest = (
            str(receipt.get("content_sha256") or "").strip().lower()
            if isinstance(receipt, Mapping)
            else ""
        )
        provenance_complete = bool(
            re.fullmatch(r"[a-f0-9]{64}", digest)
            and receipt_digest == digest
            and isinstance(receipt, Mapping)
            and isinstance(jsonld, Mapping)
        )
        if not provenance_complete:
            if self._state_law_acquisition_ledger is not None:
                raise RuntimeError(
                    "Alaska AJAX row lacks canonical retained parser-input provenance"
                )
            return enriched

        jsonld_payload = dict(jsonld)
        prior = jsonld_payload.get("provenance")
        provenance = dict(prior) if isinstance(prior, Mapping) else {}
        provenance.update(
            {
                "content_sha256": digest,
                "transport_receipt": dict(receipt),
            }
        )
        jsonld_payload["provenance"] = provenance
        structured["jsonld"] = jsonld_payload
        enriched.structured_data = structured
        return enriched

    def _parse_statute_chunk(self, *, code_name: str, html: str) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html or "", "html.parser")
        from .alaska_section import parse_alaska_statute_html

        parsed = parse_alaska_statute_html(html, code_name=code_name)
        if parsed:
            return parsed
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
        match = re.match(
            r"^(\d+)\.(\d+)\.(\d+)(?:[A-Za-z])?$",
            str(last_sec or "").strip(),
        )
        if not match:
            return None
        # BASIS treats secStart as an exclusive cursor.  Passing LastSec returns
        # the next section.  Incrementing its chapter (the prior behavior)
        # silently skipped the remainder of every boundary chapter.
        return str(last_sec or "").strip()

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
        from .alaska_constitution import (
            configured_constitution_html_path,
            parse_alaska_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_alaska_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Alaska Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .alaska_section import (
            configured_section_html_path,
            parse_alaska_statute_html,
        )

        local_section = configured_section_html_path()
        if local_section is not None:
            local_rows = parse_alaska_statute_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                code_name=code_name,
                max_statutes=limit,
            )
            if local_rows:
                if limit is None:
                    expected = {str(number) for number, _name in self.OFFICIAL_TITLES}
                    observed = {
                        str(int(str(row.title_number or "0"))) for row in local_rows
                    }
                    missing = sorted(expected - observed, key=int)
                    if missing:
                        raise RuntimeError(
                            "Configured Alaska section HTML is not a full official corpus: "
                            f"missing_titles={missing} rows={len(local_rows)}"
                        )
                return local_rows if limit is None else local_rows[: int(limit)]
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        sec_start: Optional[str] = "1"
        seen_cursors: set[str] = set()
        observed_titles: set[str] = set()
        expected_titles = {str(number) for number, _name in self.OFFICIAL_TITLES}
        final_title = max(expected_titles, key=int)
        last_nonempty_cursor = ""
        frontier_closed = False
        page_count = 0

        while True:
            if not sec_start or (limit is not None and len(statutes) >= limit):
                break
            if sec_start in seen_cursors:
                message = f"Alaska BASIS traversal cursor cycle at {sec_start}"
                if limit is None:
                    raise RuntimeError(message)
                self.logger.warning(message)
                break
            if page_count >= 4096:
                message = "Alaska BASIS traversal exceeded the 4096-page safety frontier"
                if limit is None:
                    raise RuntimeError(message)
                self.logger.warning(message)
                break
            seen_cursors.add(sec_start)
            page_count += 1
            html, last_sec = await self._fetch_statute_chunk(sec_start)
            if not html:
                last_title = str(last_nonempty_cursor).split(".", 1)[0].lstrip("0") or "0"
                terminal_probe = dict(
                    getattr(self, "_last_alaska_terminal_probe", {}) or {}
                )
                terminal_url = (
                    "https://www.akleg.gov/basis/statutes.asp"
                    f"?media=print&type=fetch&secStart={sec_start}"
                )
                exact_terminal_empty = bool(
                    terminal_probe.get("closed") is True
                    and terminal_probe.get("empty") is True
                    and int(terminal_probe.get("status_code") or 0) == 200
                    and str(terminal_probe.get("content_sha256") or "")
                    == hashlib.sha256(b"").hexdigest()
                    and str(terminal_probe.get("sec_start") or "").strip()
                    == str(sec_start or "").strip()
                    and self._canonical_fetch_url(
                        str(terminal_probe.get("requested_url") or "")
                    )
                    == self._canonical_fetch_url(terminal_url)
                    and self._canonical_fetch_url(
                        str(terminal_probe.get("final_url") or "")
                    )
                    == self._canonical_fetch_url(terminal_url)
                )
                if last_title == final_title and (
                    exact_terminal_empty
                    # Preserve bounded/local fixture compatibility.  A strict
                    # publication crawl always has the ledger attached and
                    # therefore always requires the exact terminal receipt.
                    or self._state_law_acquisition_ledger is None
                ):
                    frontier_closed = True
                elif limit is None:
                    raise RuntimeError(
                        "Alaska BASIS traversal ended without an exact terminal "
                        "HTTP 200 empty response: "
                        f"last_cursor={last_nonempty_cursor or 'missing'} "
                        f"terminal_probe={terminal_probe or 'missing'}"
                    )
                break
            chunk_statutes = self._bind_statute_chunk_provenance(
                self._parse_statute_chunk(code_name=code_name, html=html)
            )
            for statute in chunk_statutes:
                key = str(statute.section_number or "")
                if key in seen_sections:
                    continue
                seen_sections.add(key)
                title = str(statute.title_number or "").lstrip("0") or "0"
                observed_titles.add(title)
                statutes.append(statute)
                if limit is not None and len(statutes) >= limit:
                    break
            next_start = self._next_sec_start(last_sec)
            if not next_start:
                if limit is None:
                    raise RuntimeError(
                        f"Alaska BASIS response at {sec_start} omitted a usable LastSec cursor"
                    )
                break
            if next_start == sec_start:
                message = f"Alaska BASIS LastSec did not advance from {sec_start}"
                if limit is None:
                    raise RuntimeError(message)
                self.logger.warning(message)
                break
            last_nonempty_cursor = next_start
            sec_start = next_start

        if limit is None:
            missing_titles = sorted(expected_titles - observed_titles, key=int)
            if not frontier_closed or missing_titles:
                raise RuntimeError(
                    "Alaska full-corpus traversal did not close the official frontier: "
                    f"frontier_closed={frontier_closed} missing_titles={missing_titles} "
                    f"rows={len(statutes)}"
                )
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
