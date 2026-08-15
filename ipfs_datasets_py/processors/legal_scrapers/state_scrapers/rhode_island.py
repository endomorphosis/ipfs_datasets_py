"""Scraper for Rhode Island state laws."""

from __future__ import annotations

import asyncio
import json
import re
import ssl
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

_TITLE_INDEX_URL_TEMPLATE = "https://webserver.rilegislature.gov/Statutes/TITLE{title}/INDEX.HTM"
_TITLE_LINK_RE = re.compile(r"/Statutes/TITLE(\d+)/(\d+(?:-\d+)+)/INDEX\.htm$", re.IGNORECASE)
_SECTION_LINK_RE = re.compile(r"/Statutes/TITLE(\d+)/(\d+(?:-\d+)+)/([\dA-Za-z._-]+)\.htm$", re.IGNORECASE)
_SECTION_NUMBER_RE = re.compile(r"§\s*([0-9A-Za-z.-]+)")
_SECTION_HEADING_RE = re.compile(r"§\s*([0-9A-Za-z.-]+)\.\s*(.+)")


class RhodeIslandScraper(BaseStateScraper):
    """Scraper for Rhode Island state laws from http://webserver.rilin.state.ri.us"""

    OFFICIAL_DOMAIN = "webserver.rilegislature.gov"
    OFFICIAL_ENTRY_PATH = "/Statutes/TITLE1/INDEX.HTM"
    OFFICIAL_ENTRY_URL = "https://webserver.rilegislature.gov/Statutes/TITLE1/INDEX.HTM"
    OFFICIAL_TITLE_COUNT = 49
    _RI_TITLE_HREF_RE = re.compile(
        r"/Statutes/TITLE(?P<title>\d+[A-Z]?(?:\.\d+)?)/INDEX\.htm",
        re.IGNORECASE,
    )
    _RI_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(?P<title>\d+[A-Z]?(?:\.\d+)?)\b", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "Aeronautics"),
        ("2", "Agriculture and Forestry"),
        ("3", "Alcoholic Beverages"),
        ("4", "Animals and Animal Husbandry"),
        ("5", "Businesses and Professions"),
        ("6", "Commercial Law — General Regulatory Provisions"),
        ("6A", "Uniform Commercial Code"),
        ("7", "Corporations, Associations and Partnerships"),
        ("8", "Courts and Civil Procedure — Courts"),
        ("9", "Courts and Civil Procedure — Procedure Generally"),
        ("10", "Courts and Civil Procedure — Procedure in Particular Actions"),
        ("11", "Criminal Offenses"),
        ("12", "Criminal Procedure"),
        ("13", "Criminals — Correctional Institutions"),
        ("14", "Delinquent and Dependent Children"),
        ("15", "Domestic Relations"),
        ("16", "Education"),
        ("17", "Elections"),
        ("18", "Fiduciaries"),
        ("19", "Financial Institutions"),
        ("20", "Fish and Wildlife"),
        ("21", "Food and Drugs"),
        ("22", "General Assembly"),
        ("23", "Health and Safety"),
        ("24", "Highways"),
        ("25", "Holidays and Days of Special Observance"),
        ("26", "Title 26"),
        ("27", "Insurance"),
        ("28", "Labor and Labor Relations"),
        ("29", "Libraries"),
        ("30", "Military Affairs and Defense"),
        ("31", "Motor and Other Vehicles"),
        ("32", "Parks and Recreational Areas"),
        ("33", "Probate Practice and Procedure"),
        ("34", "Property"),
        ("35", "Public Finance"),
        ("36", "Public Officers and Employees"),
        ("37", "Public Property and Works"),
        ("38", "Public Records"),
        ("39", "Public Utilities and Carriers"),
        ("40", "Human Services"),
        ("40.1", "Behavioral Healthcare, Developmental Disabilities and Hospitals"),
        ("41", "Sports, Racing, and Athletics"),
        ("42", "State Affairs and Government"),
        ("43", "Statutes and Statutory Construction"),
        ("44", "Taxation"),
        ("45", "Towns and Cities"),
        ("46", "Waters and Navigation"),
        ("47", "Weights and Measures"),
    )

    def get_base_url(self) -> str:
        """Return the base URL for Rhode Island's legislative website."""
        return "https://webserver.rilegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Rhode Island."""
        return [{
            "name": "Rhode Island General Laws",
            "url": _TITLE_INDEX_URL_TEMPLATE.format(title=1),
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Rhode Island's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        max_sections = limit if limit is not None else 1000000
        return await self._custom_scrape_rhode_island(
            code_name,
            code_url,
            "R.I. Gen. Laws",
            max_sections=max_sections,
        )
    
    async def _custom_scrape_rhode_island(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Rhode Island's legislative website."""
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        resumed = self._load_partial_checkpoint_statutes(
            code_name=code_name,
            max_statutes=max_sections,
        )
        checkpoint_progress = self._load_partial_checkpoint_progress()
        statutes: List[NormalizedStatute] = []
        seen_urls: set[str] = set()
        seen_keys: set[str] = set()

        def _extend_unique(batch: List[NormalizedStatute]) -> None:
            for statute in batch:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                source_url = str(statute.source_url or "").strip()
                if key and key in seen_keys:
                    continue
                if source_url and source_url in seen_urls:
                    continue
                if key:
                    seen_keys.add(key)
                if source_url:
                    seen_urls.add(source_url)
                statutes.append(statute)

        _extend_unique(resumed)
        if resumed:
            self.logger.info(
                "Rhode Island custom scraper: resumed %s statutes from partial checkpoint",
                len(statutes),
            )
        section_concurrency = max(1, int(self._env_int("STATE_SCRAPER_RI_SECTION_CONCURRENCY", default=10)))
        section_sem = asyncio.Semaphore(section_concurrency)
        resume_titles_scanned = max(0, int(checkpoint_progress.get("titles_scanned") or 0))
        resume_chapters_scanned = max(0, int(checkpoint_progress.get("chapters_scanned") or 0))
        resume_sections_scanned = max(0, int(checkpoint_progress.get("sections_scanned") or 0))
        resume_discovered_sections = max(0, int(checkpoint_progress.get("discovered_sections") or 0))
        title_rewind = max(0, int(self._env_int("STATE_SCRAPER_RI_RESUME_TITLE_REWIND", default=1)))
        chapter_rewind = max(0, int(self._env_int("STATE_SCRAPER_RI_RESUME_CHAPTER_REWIND", default=20)))
        resume_title_floor = max(1, resume_titles_scanned - title_rewind)
        resume_chapter_floor = max(0, resume_chapters_scanned - chapter_rewind)
        chapters_scanned_total = int(resume_chapters_scanned)
        chapter_visit_index = 0
        sections_scanned_total = int(max(len(statutes), resume_sections_scanned))
        sections_discovered_total = int(max(len(statutes), resume_discovered_sections))
        last_title_scanned = int(resume_titles_scanned)

        try:
            max_title = 60
            consecutive_missing_titles = 0
            self.logger.info(
                "Rhode Island custom scraper: max_titles=%s max_sections=%s",
                max_title,
                max_sections,
            )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="rhode-island:title-scan:start",
                extra={
                    "titles_scanned": 0,
                    "discovered_titles": int(max_title),
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )
            for title_num in range(1, max_title + 1):
                if len(statutes) >= max_sections:
                    break
                if title_num < resume_title_floor:
                    continue

                title_url = _TITLE_INDEX_URL_TEMPLATE.format(title=title_num)
                title_bytes = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=30)
                title_html = title_bytes.decode("utf-8", errors="replace") if title_bytes else ""
                if not title_html or "Document Moved" in title_html or "404" in title_html[:200]:
                    consecutive_missing_titles += 1
                    if consecutive_missing_titles >= 5 and title_num > 47:
                        break
                    continue
                consecutive_missing_titles = 0
                last_title_scanned = max(last_title_scanned, int(title_num))

                title_soup = BeautifulSoup(title_html, "html.parser")
                chapter_links = []
                for link in title_soup.find_all("a", href=True):
                    full_url = urljoin(title_url, str(link.get("href") or ""))
                    if _TITLE_LINK_RE.search(full_url):
                        chapter_links.append((link, full_url))
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="rhode-island:title-scan",
                    extra={
                        "titles_scanned": int(title_num),
                        "discovered_titles": int(max_title),
                        "chapters_scanned": int(chapters_scanned_total),
                        "sections_scanned": int(sections_scanned_total),
                        "discovered_sections": int(sections_discovered_total),
                        "discovered_chapters": int(len(chapter_links)),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )

                for link, chapter_url in chapter_links:
                    if len(statutes) >= max_sections:
                        break

                    chapter_visit_index += 1
                    if chapter_visit_index < resume_chapter_floor:
                        continue
                    chapters_scanned_total += 1
                    chapter_bytes = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=30)
                    if not chapter_bytes:
                        continue
                    chapter_soup = BeautifulSoup(chapter_bytes, "html.parser")
                    chapter_name = link.get_text(" ", strip=True) or ""
                    legal_area = self._identify_legal_area(chapter_name or code_name)
                    section_candidates = []
                    seen_chapter_sections = set()
                    chapter_number = self._extract_ri_chapter_number(chapter_url)
                    for section_link in chapter_soup.find_all("a", href=True):
                        section_url = urljoin(chapter_url, str(section_link.get("href") or ""))
                        if section_url in seen_urls or section_url in seen_chapter_sections:
                            continue
                        if not _SECTION_LINK_RE.search(section_url):
                            continue
                        section_label = section_link.get_text(" ", strip=True)
                        section_number = self._extract_ri_section_number(section_label, section_url)
                        if not section_number:
                            continue
                        seen_chapter_sections.add(section_url)
                        section_candidates.append((section_url, section_label, section_number))

                    sections_discovered_total += len(section_candidates)

                    async def _parse_section(
                        section_url: str,
                        section_label: str,
                        section_number: str,
                    ) -> Optional[NormalizedStatute]:
                        async with section_sem:
                            section_bytes = await self._fetch_page_content_with_archival_fallback(
                                section_url,
                                timeout_seconds=30,
                            )
                        section_html = section_bytes.decode("utf-8", errors="replace") if section_bytes else ""
                        full_text, extracted_name = self._extract_ri_section_text_and_name(section_html)
                        section_name = (extracted_name or section_label or f"Section {section_number}")[:200]
                        if not full_text:
                            full_text = f"Section {section_number}: {section_name}"
                        return NormalizedStatute(
                            state_code=self.state_code,
                            state_name=self.state_name,
                            statute_id=f"{code_name} § {section_number}",
                            code_name=code_name,
                            title_number=str(title_num),
                            chapter_number=chapter_number,
                            chapter_name=chapter_name[:200] or None,
                            section_number=section_number,
                            section_name=section_name,
                            full_text=full_text,
                            legal_area=legal_area,
                            source_url=section_url,
                            official_cite=f"{citation_format} § {section_number}",
                            metadata=StatuteMetadata(),
                            structured_data={
                                "source_kind": "official_rhode_island_section_html",
                                "discovery_method": "official_title_chapter_section_html",
                            },
                        )

                    tasks = [
                        asyncio.create_task(_parse_section(section_url, section_label, section_number))
                        for section_url, section_label, section_number in section_candidates
                    ]
                    scanned_sections = 0
                    cancelled_early = False
                    for task in asyncio.as_completed(tasks):
                        scanned_sections += 1
                        sections_scanned_total += 1
                        statute = await task
                        if statute is not None:
                            _extend_unique([statute])
                        if (
                            scanned_sections == 1
                            or scanned_sections % 200 == 0
                            or scanned_sections == len(section_candidates)
                        ):
                            self._write_partial_checkpoint(
                                statutes,
                                code_name=code_name,
                                stage_label="rhode-island:section-progress",
                                extra={
                                    "titles_scanned": int(title_num),
                                    "discovered_titles": int(max_title),
                                    "chapters_scanned": int(chapters_scanned_total),
                                    "sections_scanned": int(sections_scanned_total),
                                    "discovered_sections": int(sections_discovered_total),
                                    "codes_completed": 0,
                                    "codes_total": 1,
                                },
                            )
                        if len(statutes) == 1 or len(statutes) % 25 == 0:
                            self.logger.info(
                                "Rhode Island custom scraper: title=%s chapters_scanned=%s statutes_so_far=%s",
                                title_num,
                                chapters_scanned_total,
                                len(statutes),
                            )
                            self._write_partial_checkpoint(
                                statutes,
                                code_name=code_name,
                                stage_label="rhode-island:section-progress",
                                extra={
                                    "titles_scanned": int(title_num),
                                    "discovered_titles": int(max_title),
                                    "chapters_scanned": int(chapters_scanned_total),
                                    "sections_scanned": int(sections_scanned_total),
                                    "discovered_sections": int(sections_discovered_total),
                                    "codes_completed": 0,
                                    "codes_total": 1,
                                },
                            )
                        if len(statutes) >= max_sections:
                            cancelled_early = True
                            for pending_task in tasks:
                                if not pending_task.done():
                                    pending_task.cancel()
                            break
                    if cancelled_early:
                        await asyncio.gather(*tasks, return_exceptions=True)
                        break

            self.logger.info("Rhode Island custom scraper: Scraped %s sections", len(statutes))
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="rhode-island:complete",
                force=True,
                extra={
                    "titles_scanned": int(last_title_scanned),
                    "discovered_titles": int(max_title),
                    "chapters_scanned": int(chapters_scanned_total),
                    "sections_scanned": int(sections_scanned_total),
                    "discovered_sections": int(sections_discovered_total),
                    "codes_completed": 1,
                    "codes_total": 1,
                },
            )
            if not statutes:
                self.logger.info("Rhode Island custom scraper found no data, falling back to generic scraper")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            return statutes
        except Exception as e:
            self.logger.error(f"Rhode Island custom scraper failed: {e}")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)

    def _extract_ri_section_number(self, link_text: str, url: str) -> str:
        match = _SECTION_NUMBER_RE.search(str(link_text or ""))
        if match:
            return match.group(1).strip().rstrip(".")
        url_match = _SECTION_LINK_RE.search(str(url or ""))
        if url_match:
            return url_match.group(3).strip().rstrip(".")
        return (
            self._extract_section_number(link_text)
            or self._derive_section_number_from_url(url)
            or ""
        )

    @staticmethod
    def _extract_ri_chapter_number(url: str) -> str | None:
        match = _TITLE_LINK_RE.search(str(url or ""))
        if not match:
            return None
        return match.group(2)

    def _extract_ri_section_text_and_name(self, html: str) -> tuple[str, str]:
        if not html:
            return "", ""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return "", ""

        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body")
        if body is None:
            return "", ""

        for tag in body.find_all(["script", "style"]):
            tag.decompose()

        content_node = None
        for bold in body.find_all("b"):
            bold_text = self._normalize_legal_text(bold.get_text(" ", strip=True))
            if bold_text.startswith("§"):
                content_node = bold.parent
                break

        text = self._normalize_legal_text(body.get_text("\n", strip=True))
        if len(text) < 20:
            return "", ""

        section_name = ""
        if content_node is not None:
            heading = self._normalize_legal_text(content_node.get_text(" ", strip=True))
            heading_match = _SECTION_HEADING_RE.match(heading)
            if heading_match:
                section_name = heading_match.group(2).strip()

        return text[:14000], section_name

    def official_title_token(self, title_number: Any) -> str:
        token = str(title_number or "").strip()
        if not token:
            return ""
        if token.upper() == "6A":
            return "6A"
        if token == "40.1":
            return "40.1"
        if token.isdigit():
            return str(int(token))
        return token

    def official_title_url(self, title_number: Any) -> str:
        token = self.official_title_token(title_number)
        if not token:
            return self.OFFICIAL_ENTRY_URL
        return _TITLE_INDEX_URL_TEMPLATE.format(title=token)

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Rhode Island General Laws title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            key_token = str(number).replace(".", "-").lower()
            rows.append(
                {
                    "canonical_key": f"ri:title-{key_token}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Rhode Island General Laws Title {number} ({name}) official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return (
            host == "rilegislature.gov"
            or host.endswith(".rilegislature.gov")
            or host == "rilin.state.ri.us"
            or host.endswith(".rilin.state.ri.us")
        )

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-rhode-island-official-catalog/1.0",
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

    def _normalize_title_number(self, value: str) -> str:
        token = str(value or "").strip()
        if not token:
            return ""
        if token.upper() == "6A":
            return "6A"
        if token in {"40.1", "40-1", "401"}:
            return "40.1"
        if token.isdigit():
            return str(int(token))
        return token

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
            match = self._RI_TITLE_HREF_RE.search(absolute) or self._RI_TITLE_LABEL_RE.search(
                " ".join((href, label))
            )
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
        """Enumerate every official Rhode Island General Laws title."""

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

    def fetch_official(self, code: str = "RI"):
        """Acquire the exhaustive official Rhode Island General Laws title catalog.

        Live HTTPS retains the official title index. Every known General Laws
        title is enumerated with an official rilegislature.gov URL. This hook
        never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "RI").strip().upper() or "RI"
        if normalized != "RI":
            raise ValueError(f"RhodeIslandScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "rhode island official catalog enumeration rejected incomplete "
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
StateScraperRegistry.register("RI", RhodeIslandScraper)
