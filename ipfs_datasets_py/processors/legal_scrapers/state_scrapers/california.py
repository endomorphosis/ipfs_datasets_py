"""California state law scraper.

Scrapes laws from the California Legislative Information website
(https://leginfo.legislature.ca.gov/).
"""

from typing import List, Dict, Optional, Tuple
import os
import re
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
        code_type = self.CODE_TYPE_MAP.get(code_name)
        if not code_type:
            self.logger.warning("No code type mapping for %s", code_name)
            return []

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
            return official if limit is None else official[: int(limit)]

        # Bounded probe fallback to seeds when the official TOC tree is empty.
        if seeds:
            return seeds if limit is None else seeds[: int(limit)]

        return []
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
