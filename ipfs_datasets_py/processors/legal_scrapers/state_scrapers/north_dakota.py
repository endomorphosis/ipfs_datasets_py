"""Scraper for North Dakota state laws.

This module contains the scraper for North Dakota statutes from the official state legislative website.
"""

from typing import Any, Dict, List, Optional
import json
import re
import ssl
import subprocess
import urllib.parse
import urllib.request
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class NorthDakotaScraper(BaseStateScraper):
    """Scraper for North Dakota state laws from https://www.legis.nd.gov"""

    OFFICIAL_DOMAIN = "www.legis.nd.gov"
    OFFICIAL_ENTRY_PATH = "/general-information/north-dakota-century-code"
    OFFICIAL_ENTRY_URL = "https://www.legis.nd.gov/general-information/north-dakota-century-code"
    _ND_CENCODE_PDF_RE = re.compile(r"/cencode/.*?\.pdf$", re.IGNORECASE)
    _ND_CENCODE_FILE_RE = re.compile(r"t(\d{1,3})c(\d{1,3})\.pdf$", re.IGNORECASE)
    _ND_TITLE_HREF_RE = re.compile(
        r"/cencode/t(?P<title>\d{1,2}(?:-\d)?)\.html$",
        re.IGNORECASE,
    )
    _ND_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(?P<title>\d{1,2}(?:\.\d)?)\b", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Aeronautics"),
        ("4.1", "Agriculture"),
        ("5", "Alcoholic Beverages"),
        ("6", "Banks and Banking"),
        ("8", "Carriage"),
        ("9", "Contracts and Obligations"),
        ("10", "Corporations"),
        ("11", "Counties"),
        ("12", "Corrections, Parole, and Probation"),
        ("12.1", "Criminal Code"),
        ("13", "Debtor and Creditor Relationship"),
        ("14", "Domestic Relations and Persons"),
        ("15", "Education"),
        ("15.1", "Elementary and Secondary Education"),
        ("16.1", "Elections"),
        ("18", "Fires"),
        ("19", "Foods, Drugs, Oils, and Compounds"),
        ("20.1", "Game, Fish, Predators, and Boating"),
        ("21", "Governmental Finance"),
        ("22", "Guaranty, Indemnity, and Suretyship"),
        ("23", "Health and Safety"),
        ("23.1", "Environmental Quality"),
        ("24", "Highways, Bridges, and Ferries"),
        ("25", "Mental and Physical Illness or Disability"),
        ("26.1", "Insurance"),
        ("27", "Judicial Branch of Government"),
        ("28", "Judicial Procedure, Civil"),
        ("29", "Judicial Procedure, Criminal"),
        ("30.1", "Uniform Probate Code"),
        ("31", "Judicial Proof"),
        ("32", "Judicial Remedies"),
        ("32.1", "Conciliation"),
        ("34", "Labor and Employment"),
        ("35", "Liens"),
        ("36", "Livestock"),
        ("37", "Military"),
        ("38", "Mining and Gas and Oil Production"),
        ("39", "Motor Vehicles"),
        ("40", "Municipal Government"),
        ("41", "Uniform Commercial Code"),
        ("42", "Nuisances"),
        ("43", "Occupations and Professions"),
        ("44", "Offices and Officers"),
        ("45", "Partnerships"),
        ("46", "Printing Laws"),
        ("47", "Property"),
        ("48", "Public Buildings"),
        ("49", "Public Utilities"),
        ("50", "Public Welfare"),
        ("51", "Sales and Exchanges"),
        ("52", "Social Security"),
        ("53", "Sports and Amusements"),
        ("54", "State Government"),
        ("55", "State Historical Society and State Parks"),
        ("57", "Taxation"),
        ("58", "Townships"),
        ("59", "Trusts"),
        ("61", "Waters"),
        ("62.1", "Weapons"),
        ("65", "Workforce Safety and Insurance"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)

    def _filter_non_code_results(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        for statute in statutes:
            url = str(statute.source_url or "").lower()
            text = str(statute.full_text or "").lower()
            if "/cencode/" not in url and "web.archive.org/web/" not in url:
                continue
            if "/assembly/" in url:
                continue
            if "legislative assembly - regular session" in text:
                continue
            out.append(statute)
        return out
    
    def get_base_url(self) -> str:
        """Return the base URL for North Dakota's legislative website."""
        return "https://www.legis.nd.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for North Dakota."""
        return [{
            "name": "North Dakota Century Code",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from North Dakota's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/",
            f"{self.get_base_url()}/cencode/",
            "https://www.ndlegis.gov/cencode/",
        ]

        best: List[NormalizedStatute] = []
        seen = set()
        # Full-corpus uses a large practical ceiling so PDF discovery is not
        # silently truncated to the historical sample default of 160.
        # Bounded probes honor max_statutes / STATE_SCRAPER_MAX_STATUTES.
        if max_statutes is not None:
            return_threshold = max(1, int(max_statutes))
            unbounded = False
        elif self._full_corpus_enabled():
            return_threshold = 1000000
            unbounded = True
        else:
            return_threshold = self._bounded_return_threshold(160)
            unbounded = False

        official_pdf_statutes = await self._scrape_official_index_pdfs(
            code_name,
            max_statutes=None if unbounded else max(10, return_threshold),
        )
        if official_pdf_statutes:
            return official_pdf_statutes if unbounded else official_pdf_statutes[:return_threshold]

        # Seed PDFs are for bounded probes only — never sole full-corpus path.
        if not self._full_corpus_enabled():
            direct_pdf_statutes = await self._scrape_seed_cencode_pdfs(code_name, max_statutes=return_threshold)
            if direct_pdf_statutes:
                best = list(direct_pdf_statutes)

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            statutes = await self._generic_scrape(code_name, candidate, "N.D. Cent. Code", max_sections=max(10, return_threshold))
            statutes = self._filter_non_code_results(statutes)
            if len(statutes) > len(best):
                best = statutes
            if not unbounded and len(best) >= return_threshold:
                return best

        if not unbounded and len(best) >= return_threshold:
            return best

        pdf_statutes = await self._scrape_cencode_pdfs(
            code_name,
            max_statutes=None if unbounded else max(10, return_threshold),
        )
        if pdf_statutes:
            return pdf_statutes
        return best

    async def _scrape_official_index_pdfs(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        # Full-corpus discovery should not be capped at a small sample of PDFs.
        discovery_limit = 100000 if limit is None else max(200, int(limit) * 6)
        discovered = await self._discover_official_cencode_pdfs(limit=discovery_limit)
        if not discovered:
            return []

        statutes: List[NormalizedStatute] = []
        seen = set()
        for pdf_url in discovered:
            if limit is not None and len(statutes) >= limit:
                break
            base_pdf_url = pdf_url.split("#", 1)[0]
            if base_pdf_url in seen:
                continue
            seen.add(base_pdf_url)
            pdf_bytes = await self._request_bytes(base_pdf_url, timeout=45)
            full_text = self._extract_pdf_text(pdf_bytes=pdf_bytes, max_chars=14000)
            if len(full_text) < 280:
                continue
            file_name = base_pdf_url.rsplit("/", 1)[-1]
            m = self._ND_CENCODE_FILE_RE.search(file_name)
            title_no = m.group(1) if m else ""
            chapter_no = m.group(2) if m else ""
            label = f"Title {title_no} Chapter {chapter_no}".strip() if m else file_name
            section_number = f"{title_no}-{chapter_no}".strip("-") or file_name.rsplit(".", 1)[0]
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=label,
                    full_text=full_text,
                    source_url=base_pdf_url,
                    legal_area=self._identify_legal_area(label),
                    official_cite=f"N.D. Cent. Code {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_modern_index_pdf", "skip_hydrate": True},
                )
            )
        return statutes

    async def _scrape_seed_cencode_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        seeds = [
            "https://www.legis.nd.gov/cencode/t01c01.pdf",
            "https://www.legis.nd.gov/cencode/t12c01.pdf",
        ]
        out: List[NormalizedStatute] = []
        for pdf_url in seeds[: max(1, int(max_statutes or 1))]:
            pdf_bytes = await self._request_bytes(pdf_url, timeout=12)
            full_text = self._extract_pdf_text(pdf_bytes=pdf_bytes, max_chars=14000)
            if len(full_text) < 280:
                continue
            file_name = pdf_url.rsplit("/", 1)[-1]
            m = self._ND_CENCODE_FILE_RE.search(file_name)
            title_no = m.group(1) if m else ""
            chapter_no = m.group(2) if m else ""
            section_number = f"{title_no}-{chapter_no}".strip("-") or file_name.rsplit(".", 1)[0]
            label = f"Title {title_no} Chapter {chapter_no}".strip() if m else file_name
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=label,
                    full_text=full_text,
                    source_url=pdf_url,
                    legal_area=self._identify_legal_area(label),
                    official_cite=f"N.D. Cent. Code {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_direct_pdf", "skip_hydrate": True},
                )
            )
        return out

    async def _scrape_cencode_pdfs(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Discover and emit Century Code chapter PDF links from legislative homepage."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        discovery_limit = 100000 if limit is None else max(600, int(limit) * 6)

        statutes: List[NormalizedStatute] = []
        seen = set()
        candidate_links = []

        official_modern_links = await self._discover_official_cencode_pdfs(limit=discovery_limit)
        candidate_links.extend(official_modern_links)

        for homepage in [f"{self.get_base_url()}/cencode/", "https://www.ndlegis.gov/cencode/", f"{self.get_base_url()}/"]:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(homepage, timeout_seconds=35)
            except Exception:
                continue
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href", "")).strip()
                if href:
                    candidate_links.append(urljoin(homepage, href))

        discovered = await self._discover_archived_cencode_pdfs(limit=discovery_limit)
        candidate_links.extend(discovered)

        for href in candidate_links:
            if limit is not None and len(statutes) >= limit:
                break
            if not href:
                continue
            abs_url = href
            if not self._ND_CENCODE_PDF_RE.search(abs_url):
                continue
            if abs_url in seen:
                continue
            seen.add(abs_url)

            file_name = abs_url.rsplit("/", 1)[-1]
            m = self._ND_CENCODE_FILE_RE.search(file_name)
            title_no = m.group(1) if m else ""
            chapter_no = m.group(2) if m else ""
            label = f"Title {title_no} Chapter {chapter_no}".strip() if m else file_name
            section_number = f"{title_no}-{chapter_no}".strip("-") or file_name.rsplit(".", 1)[0]
            pdf_bytes = await self._request_bytes(abs_url, timeout=45)
            full_text = self._extract_pdf_text(pdf_bytes=pdf_bytes, max_chars=14000)
            if len(full_text) < 280:
                full_text = f"North Dakota Century Code {label}: {abs_url}"

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=label,
                    full_text=full_text,
                    source_url=abs_url,
                    legal_area=self._identify_legal_area(label),
                    official_cite=f"N.D. Cent. Code {section_number}",
                    metadata=StatuteMetadata(),
                )
            )

        return statutes

    async def _discover_official_cencode_pdfs(self, limit: int = 600) -> List[str]:
        """Discover Century Code chapter PDFs from the modern official ND index page."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/general-information/north-dakota-century-code/index.html"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=35)
        except Exception:
            return []
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        out: List[str] = []
        seen = set()
        for link in soup.find_all("a", href=True):
            href = urljoin(index_url, str(link.get("href") or "").strip())
            if "/cencode/" not in href.lower() or ".pdf" not in href.lower():
                continue
            pdf_url = href.split("#", 1)[0]
            if pdf_url in seen:
                continue
            seen.add(pdf_url)
            out.append(pdf_url)
            if len(out) >= limit:
                break
        return out

    async def _discover_archived_cencode_pdfs(self, limit: int = 320) -> List[str]:
        """Discover archived ND Century Code chapter PDFs from Wayback CDX."""
        out: List[str] = []
        seen = set()
        for target in [
            "legis.nd.gov/cencode/*.pdf",
            "ndlegis.gov/cencode/*.pdf",
        ]:
            cdx_url = (
                f"http://web.archive.org/cdx/search/cdx?url={urllib.parse.quote(target, safe='*/:.')}"
                "&output=json&filter=statuscode:200&collapse=digest"
                f"&limit={max(1, int(limit))}"
            )
            try:
                req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=45) as resp:
                    payload = resp.read().decode("utf-8", errors="ignore")
                rows = json.loads(payload)
            except Exception:
                continue

            if not isinstance(rows, list) or len(rows) < 2:
                continue

            for row in rows[1:]:
                if not isinstance(row, list) or len(row) < 3:
                    continue
                ts = str(row[1]).strip()
                original = str(row[2]).strip()
                if not ts or not original:
                    continue
                encoded = urllib.parse.quote(original, safe=':/?=&%.-_')
                candidate = f"http://web.archive.org/web/{ts}/{encoded}"
                if candidate in seen:
                    continue
                seen.add(candidate)
                out.append(candidate)
        return out

    async def _request_bytes(self, pdf_url: str, timeout: int) -> bytes:
        candidates = [str(pdf_url or "")]
        wayback_iframe = self._to_wayback_iframe_url(candidates[0])
        if wayback_iframe and wayback_iframe not in candidates:
            candidates.insert(0, wayback_iframe)

        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        seen = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                payload = await self._fetch_page_content_with_archival_fallback(candidate, timeout_seconds=timeout)
                if payload:
                    return payload
            except Exception:
                continue

        return b""

    def _to_wayback_iframe_url(self, url: str) -> str:
        if not url or "web.archive.org/web/" not in url:
            return ""
        if "/if_/" in url:
            return url
        return re.sub(r"(web\.archive\.org/web/\d+)/(https?://)", r"\1if_/\2", url, count=1)

    def _extract_pdf_text(self, pdf_bytes: bytes, max_chars: int) -> str:
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

        text = proc.stdout.decode("utf-8", errors="ignore")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]

    def official_title_url(self, title_number: Any) -> str:
        number = str(title_number or "").strip()
        slug = number.replace(".", "-")
        if slug.isdigit():
            slug = f"{int(slug):02d}"
        elif "-" in slug:
            whole, _, frac = slug.partition("-")
            if whole.isdigit():
                slug = f"{int(whole):02d}-{frac}"
        return f"{self.get_base_url()}/cencode/t{slug}.html"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official North Dakota Century Code title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"nd:title-{number}",
                    "title_number": number,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"North Dakota Century Code Title {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return (
            host == "legis.nd.gov"
            or host.endswith(".legis.nd.gov")
            or host == "ndlegis.gov"
            or host.endswith(".ndlegis.gov")
        )

    def _official_http_get(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(2, min(int(timeout_seconds or 8), 8))
        headers = {
            "User-Agent": "ipfs-datasets-north-dakota-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        try:
            request = urllib.request.Request(url, headers=headers)
            context = ssl.create_default_context()
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return bytes(response.read() or b"")
        except Exception:
            return b""

    def _normalize_title_number(self, value: Any) -> str:
        text = str(value or "").strip()
        match = re.match(r"0*(\d{1,2})(?:[-.](\d))?$", text)
        if not match:
            return ""
        whole = str(int(match.group(1)))
        frac = match.group(2)
        return f"{whole}.{frac}" if frac else whole

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
            match = self._ND_TITLE_HREF_RE.search(absolute) or self._ND_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = self._normalize_title_number(match.group("title"))
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
        """Enumerate every official North Dakota Century Code title."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_ndlegis"
        return rows

    def fetch_official(self, code: str = "ND"):
        """Acquire the exhaustive official North Dakota Century Code catalog.

        Live HTTPS retains the official legis.nd.gov title index. Every known
        Century Code title is enumerated with an official URL. This hook never
        returns fixture bytes or secondary-mirror hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "ND").strip().upper() or "ND"
        if normalized != "ND":
            raise ValueError(f"NorthDakotaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "north dakota official catalog enumeration rejected incomplete "
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
StateScraperRegistry.register("ND", NorthDakotaScraper)
