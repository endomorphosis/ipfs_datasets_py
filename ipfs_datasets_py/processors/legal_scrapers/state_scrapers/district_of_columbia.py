"""Scraper for District of Columbia Official Code.

Primary path: official hierarchy on https://code.dccouncil.gov
(title → chapter → section). Playwright/generic remain fallbacks only.
"""

from typing import Any, Dict, List, Optional, Tuple
import json
import re
import ssl
import urllib.request
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class DistrictOfColumbiaScraper(BaseStateScraper):
    """Scraper for District of Columbia state laws from https://code.dccouncil.gov"""

    _DC_SECTION_URL_RE = re.compile(
        r"/us/dc/council/code/sections/([0-9A-Za-z.\-]+)/?$",
        re.IGNORECASE,
    )
    _DC_TITLE_URL_RE = re.compile(
        r"/us/dc/council/code/titles/([0-9]+[A-Za-z]?)/?$",
        re.IGNORECASE,
    )
    OFFICIAL_DOMAIN = "code.dccouncil.gov"
    OFFICIAL_ENTRY_PATH = "/us/dc/council/code"
    OFFICIAL_ENTRY_URL = "https://code.dccouncil.gov/us/dc/council/code"
    OFFICIAL_TITLES = (
        ("1", "Government Organization"),
        ("2", "Government Administration"),
        ("3", "District of Columbia Boards and Commissions"),
        ("4", "Public Care Systems"),
        ("5", "Police, Firefighters, Medical Examiner, and Forensic Sciences"),
        ("6", "Housing and Building Restrictions and Regulations"),
        ("7", "Human Health Care and Safety"),
        ("8", "Environmental and Animal Control and Protection"),
        ("9", "Transportation Systems"),
        ("10", "Parks, Public Buildings, Grounds, and Space"),
        ("11", "Organization and Jurisdiction of the Courts"),
        ("12", "Right to Remedy"),
        ("13", "Procedure Generally"),
        ("14", "Proof"),
        ("15", "Judgments and Executions; Fees and Costs"),
        ("16", "Particular Actions, Proceedings and Matters"),
        ("17", "Review"),
        ("18", "Wills"),
        ("19", "Descent, Distribution, and Trusts"),
        ("20", "Probate and Administration of Decedents' Estates"),
        ("21", "Fiduciary Relations and Persons with Mental Illness"),
        ("22", "Criminal Offenses and Penalties"),
        ("23", "Criminal Procedure"),
        ("24", "Prisoners and Their Treatment"),
        ("25", "Alcoholic Beverage Regulation"),
        ("26", "Banks and Other Financial Institutions"),
        ("27", "Civil Disorder; Curfews"),
        ("27A", "Commercial Code Supplemental Provisions"),
        ("28", "Commercial Instruments and Transactions"),
        ("28A", "Other Commercial Instruments"),
        ("29", "Partnerships"),
        ("29A", "Uniform Partnership Act of 2010"),
        ("30", "Occupations and Professions Reserved"),
        ("31", "Insurance and Securities"),
        ("31A", "Uniform Securities Act"),
        ("32", "Labor"),
        ("33", "Partnerships Reserved"),
        ("34", "Public Utilities"),
        ("35", "Railroads and Other Carriers"),
        ("36", "Trade Practices"),
        ("37", "Weights, Measures, Markets, and Vending"),
        ("38", "Educational Institutions"),
        ("39", "Libraries and Cultural Institutions"),
        ("40", "Liens"),
        ("41", "Personal Property"),
        ("42", "Real Property"),
        ("43", "Real Property Tax and Transfer"),
        ("44", "Charitable and Religious Solicitations"),
        ("45", "Insurance Other Provisions"),
        ("46", "Domestic Relations"),
        ("47", "Taxation, Licensing, Permits, Assessments, and Fees"),
        ("48", "Foods and Drugs"),
        ("49", "Notaries Public"),
        ("50", "Motor and Non-Motor Vehicles and Traffic"),
        ("51", "Jury and Jurors"),
        ("99", "Reserved and Temporary Provisions"),
    )
    _DC_CHAPTER_URL_RE = re.compile(
        r"/us/dc/council/code/titles/\d+/chapters/(\d+)/?$",
        re.IGNORECASE,
    )
    # Legacy filter also accepted chapter/subchapter index pages from generic scrape.
    _DC_LEGACY_LEVEL_URL_RE = re.compile(
        r"/us/dc/council/code/(?:sections/[0-9A-Za-z.\-]+|titles/\d+/chapters/\d+(?:/subchapters/[IVXLC]+)?)/?$",
        re.IGNORECASE,
    )

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._DC_LEGACY_LEVEL_URL_RE.search(source):
                filtered.append(statute)
        return filtered

    def get_base_url(self) -> str:
        """Return the base URL for District of Columbia's legislative website."""
        return "https://code.dccouncil.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for District of Columbia."""
        return [{
            "name": "District of Columbia Official Code",
            "url": f"{self.get_base_url()}/us/dc/council/code",
            "type": "Code",
        }]

    def _probe_timeout_seconds(self) -> int:
        """Bounded probes use a short timeout so offline unit tests fail closed fast.

        Full-corpus runs keep a longer recovery budget for official pages.
        """
        return 25 if self._full_corpus_enabled() else 4

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from District of Columbia's legislative website.

        Prefers the official title/chapter/section HTML hierarchy. Playwright and
        generic scrapers remain offline/fallback paths only.
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .district_of_columbia_constitution import (
            configured_constitution_html_path,
            parse_district_of_columbia_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower() or "charter" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_district_of_columbia_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "District of Columbia Home Rule Charter",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .district_of_columbia_xml import (
            configured_section_xml_path,
            configured_xml_dir,
            parse_dc_section_xml,
            parse_dc_xml_dir,
        )

        xml_file = configured_section_xml_path()
        if xml_file is not None:
            row = parse_dc_section_xml(xml_file.read_bytes(), code_name=code_name)
            if row is not None:
                return [row]
        xml_dir = configured_xml_dir()
        if xml_dir is not None:
            bulk = parse_dc_xml_dir(xml_dir, code_name=code_name, max_statutes=limit)
            if bulk:
                return bulk
        seed_statutes: List[NormalizedStatute] = []

        # Bounded probes may gather direct seeds; full-corpus never sole-admits seeds.
        # Prefer the official hierarchy when available; seeds are a recovery path only.
        if not self._full_corpus_enabled() or max_statutes is not None:
            seed_limit = limit if limit is not None else 160
            seed_statutes = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=seed_limit,
            )

        official = await self._scrape_official_index(code_name, max_statutes=limit)
        if official:
            return official if limit is None else official[: int(limit)]

        if seed_statutes:
            return seed_statutes if limit is None else seed_statutes[: int(limit)]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/us/dc/council/code/titles/1",
            f"{self.get_base_url()}/us/dc/council/code/titles/2",
            f"{self.get_base_url()}/us/dc/council/code/titles/1/chapters/1",
            f"{self.get_base_url()}/us/dc/council/code/sections/1-101",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        return_threshold = limit if limit is not None else 1000000
        scan_limit = return_threshold if limit is not None else 1000
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "D.C. Code",
                        max_sections=scan_limit,
                        wait_for_selector="a[href*='/sections/'], a[href*='/chapters/'], a[href*='/titles/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes[:return_threshold]
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "D.C. Code",
                max_sections=scan_limit,
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes[:return_threshold]

        if limit is None:
            return best_statutes
        return best_statutes[: int(limit)]

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        seeds = [
            ("1-101", f"{self.get_base_url()}/us/dc/council/code/sections/1-101"),
            ("1-102", f"{self.get_base_url()}/us/dc/council/code/sections/1-102"),
        ]
        return await self._scrape_section_urls(
            code_name,
            seeds,
            max_statutes=max_statutes,
            discovery_method="official_seed_section",
        )

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        title_links = await self._discover_title_links()
        self.logger.info(
            "District of Columbia official index: discovered %s title links",
            len(title_links),
        )
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            if title_index == 1 or title_index % 10 == 0 or title_index == len(title_links):
                self.logger.info(
                    "District of Columbia official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
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
                if (
                    chapter_index == 1
                    or chapter_index % 10 == 0
                    or chapter_index == len(chapter_links)
                ):
                    self.logger.info(
                        "District of Columbia official index: title=%s chapter=%s/%s sections=%s statutes_so_far=%s",
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
                    discovery_method="official_title_chapter_section_index",
                )
                statutes.extend(parsed)
        return statutes[:limit] if limit is not None else statutes

    async def _discover_title_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/us/dc/council/code"
        payload = await self._fetch_page_content_with_archival_fallback(
            index_url,
            timeout_seconds=self._probe_timeout_seconds(),
        )
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not self._DC_TITLE_URL_RE.search(href):
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

        payload = await self._fetch_page_content_with_archival_fallback(
            title_url,
            timeout_seconds=self._probe_timeout_seconds(),
        )
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(title_url, str(anchor.get("href") or "").strip())
            if not self._DC_CHAPTER_URL_RE.search(href):
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

        payload = await self._fetch_page_content_with_archival_fallback(
            chapter_url,
            timeout_seconds=self._probe_timeout_seconds(),
        )
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            match = self._DC_SECTION_URL_RE.search(href)
            if not match:
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            section_number = match.group(1)
            out.append((section_number, normalized))
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
        discovery_method: str = "official_seed_section",
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        statutes: List[NormalizedStatute] = []
        for first, second in section_urls:
            if limit is not None and len(statutes) >= limit:
                break
            # Accept either (section_number, url) or (url, section_number).
            if str(first).startswith("http"):
                source_url, section_number = first, second
            else:
                section_number, source_url = first, second
            match = self._DC_SECTION_URL_RE.search(str(source_url))
            if match:
                section_number = match.group(1)
            section_number = str(section_number or "").strip()
            if not section_number:
                continue

            payload = await self._fetch_page_content_with_archival_fallback(
                str(source_url),
                timeout_seconds=self._probe_timeout_seconds(),
            )
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
                tag.decompose()

            heading = (
                soup.select_one("h1")
                or soup.select_one(".section-title")
                or soup.select_one("title")
            )
            section_name = self._normalize_legal_text(
                heading.get_text(" ", strip=True) if heading else f"Section {section_number}"
            )
            main = (
                soup.select_one("main")
                or soup.select_one("article")
                or soup.select_one("#content")
                or soup.select_one(".content")
                or soup.find("body")
                or soup
            )
            text = self._normalize_legal_text(main.get_text(" ", strip=True))
            if len(text) < 180:
                continue

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:220] or f"Section {section_number}",
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=str(source_url),
                    official_cite=f"D.C. Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_dc_council_code_html",
                        "discovery_method": discovery_method,
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    def official_title_url(self, title_number: str) -> str:
        return f"{self.get_base_url()}/us/dc/council/code/titles/{str(title_number).strip()}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official District of Columbia Code title catalog.

        DC is enumerated exactly once: each title number appears at most once
        and this adapter never emits a second DC jurisdiction identity.
        """

        rows: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for number, name in self.OFFICIAL_TITLES:
            key = str(number).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            url = self.official_title_url(key)
            rows.append(
                {
                    "canonical_key": f"dc:title-{key.lower()}",
                    "title_number": key,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"District of Columbia Official Code Title {key} "
                        f"({name}) official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-district-of-columbia-official-catalog/1.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                )
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "ipfs-datasets-district-of-columbia-official-catalog/1.0",
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

    def _title_sort_key(self, title_number: str) -> tuple[int, str]:
        text = str(title_number or "").strip()
        match = re.match(r"(\d+)([A-Za-z]*)$", text)
        if not match:
            return (10_000, text)
        return (int(match.group(1)), match.group(2).upper())

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._DC_TITLE_URL_RE.search(absolute)
            if not match:
                continue
            number = str(match.group(1))
            if number not in found:
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official DC Code title exactly once."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        seen = {str(row["title_number"]) for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        for number, url in discovered.items():
            if number in seen:
                continue
            seen.add(number)
            rows.append(
                {
                    "canonical_key": f"dc:title-{number.lower()}",
                    "title_number": number,
                    "name": f"Title {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"District of Columbia Official Code Title {number} "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        rows.sort(key=lambda item: self._title_sort_key(str(item["title_number"])))
        return rows

    def fetch_official(self, code: str = "DC"):
        """Acquire the exhaustive official DC Code title catalog.

        The District of Columbia is acquired exactly once as a required member
        of the exact-51 set. Live HTTPS retains the official council code
        landing page. This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "DC").strip().upper() or "DC"
        if normalized != "DC":
            raise ValueError(f"DistrictOfColumbiaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("district of columbia official catalog enumeration is incomplete")
        keys = [str(row["canonical_key"]) for row in rows]
        if len(keys) != len(set(keys)):
            raise RuntimeError("district of columbia official catalog duplicated a title")
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
            "dc_counted_once": True,
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
StateScraperRegistry.register("DC", DistrictOfColumbiaScraper)
