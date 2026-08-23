"""California state law scraper.

Scrapes laws from the California Legislative Information website
(https://leginfo.legislature.ca.gov/).
"""

from typing import Any, List, Dict, Mapping, Optional, Sequence, Tuple
import json
import os
import re
import ssl
import urllib.request
from urllib.parse import urljoin, urlparse, parse_qs
from ipfs_datasets_py.utils import anyio_compat as asyncio
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class CaliforniaScraper(BaseStateScraper):
    """Scraper for California state laws."""

    CODE_TYPE_MAP = {
        "Business and Professions Code": "BPC",
        "Civil Code": "CIV",
        "Code of Civil Procedure": "CCP",
        "Commercial Code": "COM",
        "Corporations Code": "CORP",
        "Education Code": "EDC",
        "Elections Code": "ELEC",
        "Evidence Code": "EVID",
        "Family Code": "FAM",
        "Financial Code": "FIN",
        "Fish and Game Code": "FGC",
        "Food and Agricultural Code": "FAC",
        "Government Code": "GOV",
        "Harbors and Navigation Code": "HNC",
        "Health and Safety Code": "HSC",
        "Insurance Code": "INS",
        "Labor Code": "LAB",
        "Military and Veterans Code": "MVC",
        "Penal Code": "PEN",
        "Probate Code": "PROB",
        "Public Contract Code": "PCC",
        "Public Resources Code": "PRC",
        "Public Utilities Code": "PUC",
        "Revenue and Taxation Code": "RTC",
        "Streets and Highways Code": "SHC",
        "Unemployment Insurance Code": "UIC",
        "Vehicle Code": "VEH",
        "Water Code": "WAT",
        "Welfare and Institutions Code": "WIC",
    }

    _SECTION_DISPLAY_RE = re.compile(r"codes_displayText\.xhtml", re.IGNORECASE)
    _SECTION_NUM_QUERY_RE = re.compile(r"sectionNum=([^&]+)", re.IGNORECASE)
    OFFICIAL_DOMAIN = "leginfo.legislature.ca.gov"
    OFFICIAL_CODES_PATH = "/faces/codes.xhtml"
    OFFICIAL_ENTRY_URL = "https://leginfo.legislature.ca.gov/faces/codes.xhtml"
    MISSING_LINK_QUARANTINE_REASON = "missing_official_source_link"

    def get_base_url(self) -> str:
        """Get base URL for California Legislative Information."""
        return "https://leginfo.legislature.ca.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of California codes.

        California has 29 codes organized by subject matter.
        """
        base_url = self.get_base_url()

        codes = [
            {"name": "Business and Professions Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=BPC", "type": "BPC"},
            {"name": "Civil Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=CIV", "type": "CIV"},
            {"name": "Code of Civil Procedure", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=CCP", "type": "CCP"},
            {"name": "Commercial Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=COM", "type": "COM"},
            {"name": "Corporations Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=CORP", "type": "CORP"},
            {"name": "Education Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=EDC", "type": "EDC"},
            {"name": "Elections Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=ELEC", "type": "ELEC"},
            {"name": "Evidence Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=EVID", "type": "EVID"},
            {"name": "Family Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FAM", "type": "FAM"},
            {"name": "Financial Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FIN", "type": "FIN"},
            {"name": "Fish and Game Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FGC", "type": "FGC"},
            {"name": "Food and Agricultural Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FAC", "type": "FAC"},
            {"name": "Government Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=GOV", "type": "GOV"},
            {"name": "Harbors and Navigation Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=HNC", "type": "HNC"},
            {"name": "Health and Safety Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=HSC", "type": "HSC"},
            {"name": "Insurance Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=INS", "type": "INS"},
            {"name": "Labor Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=LAB", "type": "LAB"},
            {"name": "Military and Veterans Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=MVC", "type": "MVC"},
            {"name": "Penal Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PEN", "type": "PEN"},
            {"name": "Probate Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PROB", "type": "PROB"},
            {"name": "Public Contract Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PCC", "type": "PCC"},
            {"name": "Public Resources Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PRC", "type": "PRC"},
            {"name": "Public Utilities Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PUC", "type": "PUC"},
            {"name": "Revenue and Taxation Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=RTC", "type": "RTC"},
            {"name": "Streets and Highways Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=SHC", "type": "SHC"},
            {"name": "Unemployment Insurance Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=UIC", "type": "UIC"},
            {"name": "Vehicle Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=VEH", "type": "VEH"},
            {"name": "Water Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=WAT", "type": "WAT"},
            {"name": "Welfare and Institutions Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=WIC", "type": "WIC"},
            {
                "name": "California Constitution",
                "url": f"{base_url}/faces/codes_displayText.xhtml?lawCode=CONS&article=I",
                "type": "CONS",
            },
        ]

        return codes

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific California code from official leginfo HTML.

        Full-corpus mode with ``max_statutes=None`` remains uncapped. Bounded
        probes may use compact seed sections first, then fall through to the
        official TOC/section tree.
        """
        limit = self._effective_scrape_limit(max_statutes, default=250)
        from .california_constitution import (
            configured_constitution_html_path,
            parse_california_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_california_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    article_id="I",
                    code_name=code_name or "California Constitution",
                    max_statutes=limit,
                )
                if constitution_rows:
                    return constitution_rows if limit is None else constitution_rows[: int(limit)]
        code_type = self.CODE_TYPE_MAP.get(code_name)
        if not code_type:
            self.logger.warning("No code type mapping for %s", code_name)
            return []

        bulk = self._scrape_official_bulk_zip(
            code_name=code_name,
            code_type=code_type,
            max_statutes=limit,
        )
        if bulk:
            admitted = bulk if limit is None else bulk[: int(limit)]
            return self._repair_or_type_missing_source_links(admitted)

        seeds: List[NormalizedStatute] = []
        # Seed path is for bounded probes only — never sole full-corpus path.
        if not self._full_corpus_enabled() or max_statutes is not None:
            seed_budget = limit if limit is not None else 2
            seeds = await self._scrape_direct_seed_sections(
                code_name,
                code_type,
                max_statutes=max(1, int(seed_budget)),
            )

        official = await self._scrape_official_leginfo_tree(
            code_name,
            code_url,
            code_type,
            max_statutes=limit,
        )
        if official:
            admitted = official if limit is None else official[: int(limit)]
            return self._repair_or_type_missing_source_links(admitted)

        # Bounded probe fallback to seeds when the official TOC tree is empty.
        if seeds:
            admitted = seeds if limit is None else seeds[: int(limit)]
            return self._repair_or_type_missing_source_links(admitted)

        return []

    def _scrape_official_bulk_zip(
        self,
        *,
        code_name: str,
        code_type: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Read the official pubinfo ZIP when CALIFORNIA_BULK_ZIP is set.

        Does not download the 1 GB archive by default. Operators point the env
        at a local copy from downloads.leginfo.legislature.ca.gov.
        """

        from .california_bulk import configured_bulk_zip_path, parse_california_bulk_zip

        zip_path = configured_bulk_zip_path()
        if zip_path is None:
            return []
        try:
            return parse_california_bulk_zip(
                zip_path,
                code_type=code_type,
                max_statutes=max_statutes,
                code_name=code_name,
            )
        except Exception as exc:
            self.logger.warning("California official bulk zip failed: %s", exc)
            return []

    def official_code_toc_url(self, code_type: str) -> str:
        """Return the official LegInfo TOC URL for one California code family."""

        return f"{self.get_base_url()}/faces/codedisplayexpand.xhtml?tocCode={code_type}"

    def official_section_url(self, code_type: str, section_number: str) -> str:
        """Return the official LegInfo display URL for one section."""

        section = str(section_number or "").strip().rstrip(".")
        return (
            f"{self.get_base_url()}/faces/codes_displayText.xhtml"
            f"?lawCode={code_type}&sectionNum={section}."
        )

    def official_code_catalog(self) -> List[Dict[str, str]]:
        """Return the exhaustive official California code-family catalog."""

        return [
            {
                "name": name,
                "type": code_type,
                "url": self.official_code_toc_url(code_type),
            }
            for name, code_type in self.CODE_TYPE_MAP.items()
        ]

    def is_official_leginfo_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        return host == self.OFFICIAL_DOMAIN or host.endswith("." + self.OFFICIAL_DOMAIN)

    def repair_or_type_missing_source_link(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Attach an official LegInfo URL or type a linkless row as quarantine."""

        structured = dict(statute.structured_data or {})
        source_url = str(statute.source_url or "").strip()
        if source_url and self.is_official_leginfo_url(source_url):
            structured.setdefault("source_link_disposition", "official")
            statute.structured_data = structured
            return statute

        code_type = str(
            structured.get("law_code")
            or self.CODE_TYPE_MAP.get(str(statute.code_name or ""), "")
        ).strip().upper()
        section_number = str(statute.section_number or "").strip()
        if code_type and section_number:
            repaired = self.official_section_url(code_type, section_number)
            statute.source_url = repaired
            structured["law_code"] = code_type
            structured["source_kind"] = (
                structured.get("source_kind") or "official_california_leginfo_html"
            )
            structured["source_link_disposition"] = "repaired_official_leginfo"
            structured["previous_source_url"] = source_url or None
            statute.structured_data = structured
            return statute

        structured["source_link_disposition"] = "typed_quarantine"
        structured["quarantine_reason"] = self.MISSING_LINK_QUARANTINE_REASON
        statute.structured_data = structured
        return statute

    def _repair_or_type_missing_source_links(
        self,
        statutes: Sequence[NormalizedStatute],
    ) -> List[NormalizedStatute]:
        return [self.repair_or_type_missing_source_link(item) for item in statutes]

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        """Synchronous official HTTPS GET. Returns empty bytes on transport failure."""

        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-california-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-california-official-catalog/1.0",
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

    def _parse_official_code_links(self, html: bytes, page_url: str) -> List[Dict[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        found: List[Dict[str, str]] = []
        seen: set[str] = set()
        inverse = {code_type: name for name, code_type in self.CODE_TYPE_MAP.items()}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(page_url, href)
            parsed = urlparse(absolute)
            query = parse_qs(parsed.query)
            toc_values = query.get("tocCode") or query.get("toccode") or []
            law_values = query.get("lawCode") or query.get("lawcode") or []
            code_type = str((toc_values or law_values or [""])[0]).strip().upper()
            if code_type not in inverse:
                continue
            if code_type in seen:
                continue
            seen.add(code_type)
            found.append(
                {
                    "name": inverse[code_type],
                    "type": code_type,
                    "url": self.official_code_toc_url(code_type),
                }
            )
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official CA code family and type missing-link rows."""

        discovered = {
            str(item["type"]).upper(): item
            for item in self._parse_official_code_links(
                html, page_url or self.OFFICIAL_ENTRY_URL
            )
        }
        rows: List[Dict[str, Any]] = []
        for item in self.official_code_catalog():
            code_type = str(item["type"]).upper()
            official_url = str(item["url"])
            live = discovered.get(code_type)
            source_url = str((live or {}).get("url") or official_url)
            if source_url and self.is_official_leginfo_url(source_url):
                disposition = "official" if live else "repaired_official_leginfo"
            else:
                source_url = official_url
                disposition = "repaired_official_leginfo"
            rows.append(
                {
                    "canonical_key": f"ca:{code_type.lower()}",
                    "code_type": code_type,
                    "name": item["name"],
                    "source_url": source_url,
                    "source_link_disposition": disposition,
                    "text": (
                        f"California {item['name']} ({code_type}) official LegInfo "
                        f"catalog unit at {source_url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "CA"):
        """Acquire the exhaustive official California code catalog.

        Live HTTPS retains the official codes landing page. Every known
        California code family is enumerated with an official LegInfo URL.
        Linkless catalog members are repaired to the official TOC URL or
        typed as quarantine. This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "CA").strip().upper() or "CA"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("california official catalog enumeration is incomplete")
        request = (
            f"GET {self.OFFICIAL_CODES_PATH} HTTP/1.1\n"
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
            source_path=self.OFFICIAL_CODES_PATH,
            frontier=frontier,
            rows=tuple(rows),
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=str(rows[0]["canonical_key"]),
            last_hierarchy_unit=str(rows[-1]["canonical_key"]),
        )

    async def _scrape_official_leginfo_tree(
        self,
        code_name: str,
        code_url: str,
        code_type: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error("Required library not available: %s", e)
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        fetch_timeout = max(
            5,
            int(float(os.getenv("CALIFORNIA_CODE_FETCH_TIMEOUT_SECONDS", "45") or 45)),
        )
        self.logger.info(
            "California: fetching %s from %s with timeout=%ss",
            code_name,
            code_url,
            fetch_timeout,
        )

        page_bytes = await self._fetch_code_index_page(code_url, timeout_seconds=fetch_timeout)
        if not page_bytes:
            self.logger.warning("California: empty response for %s", code_name)
            return []

        soup = BeautifulSoup(page_bytes, "html.parser")
        legal_area = self._identify_legal_area(code_name)
        section_links = self._discover_section_links(soup, code_url, code_type)
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()

        for section_url, link_text in section_links:
            if limit is not None and len(statutes) >= int(limit):
                break
            section_number = self._section_number_from_url(section_url) or self._extract_section_number(
                link_text or ""
            )
            if not section_number:
                continue
            key = section_number.lower()
            if key in seen_sections:
                continue
            seen_sections.add(key)

            statute = await self._build_section_statute(
                code_name=code_name,
                code_type=code_type,
                section_url=section_url,
                section_number=section_number,
                link_text=link_text,
                legal_area=legal_area,
                timeout_seconds=fetch_timeout,
            )
            if statute is not None:
                statutes.append(statute)

        self.logger.info("Scraped %s sections from %s", len(statutes), code_name)
        return statutes

    def _discover_section_links(
        self,
        soup,
        code_url: str,
        code_type: str,
    ) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            section_text = (link.get_text(strip=True) or "").strip()
            section_url = str(link.get("href") or "").strip()
            if not section_url:
                continue
            if not section_url.startswith("http"):
                section_url = urljoin(code_url, section_url)

            parsed = urlparse(section_url)
            if not self._SECTION_DISPLAY_RE.search(parsed.path or ""):
                continue

            query = parse_qs(parsed.query)
            law_codes = query.get("lawCode") or query.get("lawcode") or []
            if not law_codes or str(law_codes[0]).upper() != code_type:
                continue
            if not section_text or not re.search(r"\d", section_text):
                # Still accept when sectionNum is present in the query.
                if not self._section_number_from_url(section_url):
                    continue

            if section_url in seen:
                continue
            seen.add(section_url)
            out.append((section_url, section_text))
        return out

    def _section_number_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        values = query.get("sectionNum") or query.get("sectionnum") or []
        if values:
            return str(values[0]).strip().rstrip(".")
        match = self._SECTION_NUM_QUERY_RE.search(url)
        if match:
            return str(match.group(1)).strip().rstrip(".")
        return ""

    async def _build_section_statute(
        self,
        *,
        code_name: str,
        code_type: str,
        section_url: str,
        section_number: str,
        link_text: str,
        legal_area: str,
        timeout_seconds: int = 45,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        page_bytes = await self._fetch_code_index_page(section_url, timeout_seconds=timeout_seconds)
        if not page_bytes:
            return None

        soup = BeautifulSoup(page_bytes, "html.parser")
        body = self._extract_section_body(soup)
        if len(body) < 80:
            return None

        section_name = (link_text or "").strip()
        if not section_name or section_name == section_number:
            heading = soup.find(["h1", "h2", "h3", "h4"])
            if heading is not None:
                section_name = self._normalize_legal_text(heading.get_text(" ", strip=True))
        if not section_name:
            section_name = f"Section {section_number}"
        if section_number not in section_name:
            section_name = f"Section {section_number}: {section_name}"[:200]
        else:
            section_name = section_name[:200]

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name,
            full_text=body[:24000],
            source_url=section_url,
            legal_area=legal_area,
            official_cite=f"Cal. {code_name} § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_california_leginfo_html",
                "discovery_method": "official_toc_section_display",
                "law_code": code_type,
                "skip_hydrate": True,
            },
        )

    def _extract_section_body(self, soup) -> str:
        """Extract non-placeholder statute body from a leginfo display page."""
        for selector in (
            "#manylawsections",
            "#codeLawSectionNoHead",
            ".codeGroup",
            "#content_main",
            "div#content",
            "main",
            "article",
        ):
            node = soup.select_one(selector)
            if node is None:
                continue
            for tag in node(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(node.get_text(" ", strip=True))
            if len(text) >= 80:
                return text

        paragraphs = []
        for para in soup.find_all("p"):
            text = self._normalize_legal_text(para.get_text(" ", strip=True))
            if text:
                paragraphs.append(text)
        if paragraphs:
            return "\n".join(paragraphs)

        body = soup.body or soup
        for tag in body(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        return self._normalize_legal_text(body.get_text(" ", strip=True))

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        code_type: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        """Compact official seed sections for bounded offline/probe runs."""
        base = self.get_base_url()
        seeds = [
            (
                "187",
                f"{base}/faces/codes_displayText.xhtml?lawCode={code_type}&sectionNum=187.",
                "Murder defined",
            ),
            (
                "188",
                f"{base}/faces/codes_displayText.xhtml?lawCode={code_type}&sectionNum=188.",
                "Malice defined",
            ),
        ]
        # Prefer Penal Code seeds; for other codes still attempt generic sectionNums.
        if code_type != "PEN":
            seeds = [
                (
                    "1",
                    f"{base}/faces/codes_displayText.xhtml?lawCode={code_type}&sectionNum=1.",
                    "Section 1",
                ),
                (
                    "2",
                    f"{base}/faces/codes_displayText.xhtml?lawCode={code_type}&sectionNum=2.",
                    "Section 2",
                ),
            ]

        out: List[NormalizedStatute] = []
        legal_area = self._identify_legal_area(code_name)
        for section_number, source_url, fallback_name in seeds[: max(1, int(max_statutes or 1))]:
            statute = await self._build_section_statute(
                code_name=code_name,
                code_type=code_type,
                section_url=source_url,
                section_number=section_number,
                link_text=fallback_name,
                legal_area=legal_area,
            )
            if statute is not None:
                # Seed discovery method is distinct for auditability.
                structured = dict(statute.structured_data or {})
                structured["discovery_method"] = "official_seed_section"
                statute.structured_data = structured
                out.append(statute)
        return out

    async def _fetch_code_index_page(self, url: str, timeout_seconds: int = 45) -> bytes:
        """Fetch California code pages without the heavy recovery stack.

        The generic archival/search fetch path can initialize multiple search
        engines and has non-cancellable recovery branches. California code
        pages are first-party HTML, so a direct bounded request plus the
        shared persistent cache is safer for long daemon runs.
        """
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached

        timeout = max(5, int(timeout_seconds or 45))

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-california-code-scraper/2.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                    timeout=(min(10, timeout), timeout),
                )
                if int(response.status_code or 0) != 200:
                    return b""
                return bytes(response.content or b"")
            except Exception:
                return b""

        try:
            payload = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except TimeoutError:
            self._record_fetch_event(
                provider="requests_direct",
                success=False,
                error="california_direct_timeout",
            )
            return b""

        self._record_fetch_event(provider="requests_direct", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(
                url=url,
                payload=payload,
                provider="requests_direct",
            )
            return payload

        # Keep the generic recovery hook available for tests and for real
        # blocked/archived California pages; direct is merely the first try.
        return await self._fetch_page_content_with_archival_fallback(
            url,
            timeout_seconds=timeout,
        )


# Register the scraper
StateScraperRegistry.register("CA", CaliforniaScraper)
