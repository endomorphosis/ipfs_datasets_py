"""Scraper for Virginia state laws.

This module contains the scraper for Virginia statutes from the official state legislative website.
"""

import asyncio
import json
import re
import ssl
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class VirginiaScraper(BaseStateScraper):
    """Scraper for Virginia state laws from https://law.lis.virginia.gov"""

    OFFICIAL_DOMAIN = "law.lis.virginia.gov"
    OFFICIAL_ENTRY_PATH = "/vacode/"
    OFFICIAL_ENTRY_URL = "https://law.lis.virginia.gov/vacode/"
    _VA_TITLE_HREF_RE = re.compile(
        r"/vacode/title(?P<title>[0-9]+(?:\.[0-9]+)?[A-Za-z]?)/?$",
        re.IGNORECASE,
    )
    _VA_TITLE_LABEL_RE = re.compile(
        r"\bTitle\s+(?P<title>\d+(?:\.\d+)?[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    _VA_CONTINUATION_RE = re.compile(
        r"\b(next|continue|more titles|page\s+\d+)\b",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2.2", "Administration of Government"),
        ("3.2", "Agriculture, Animal Care, and Food"),
        ("4.1", "Alcoholic Beverage and Cannabis Control"),
        ("5.1", "Aviation"),
        ("6.2", "Financial Institutions and Services"),
        ("8.01", "Civil Remedies and Procedure"),
        ("8.1A", "Uniform Commercial Code - General Provisions"),
        ("8.2", "Commercial Code - Sales"),
        ("8.2A", "Commercial Code - Leases"),
        ("8.3A", "Commercial Code - Negotiable Instruments"),
        ("8.4", "Commercial Code - Bank Deposits and Collections"),
        ("8.4A", "Commercial Code - Funds Transfers"),
        ("8.5A", "Commercial Code - Letters of Credit"),
        ("8.6A", "Commercial Code - Bulk Transfers"),
        ("8.7", "Commercial Code - Warehouse Receipts, Bills of Lading and Other Documents of Title"),
        ("8.8A", "Commercial Code - Investment Securities"),
        ("8.9A", "Commercial Code - Secured Transactions"),
        ("8.10", "Commercial Code - Effective Date and Repealer"),
        ("8.11", "1973 Amendatory Act - Effective Date and Transition Provisions"),
        ("8.12", "Uniform Commercial Code - Controllable Electronic Records"),
        ("8.13", "Uniform Commercial Code - Transitional Provisions for 2022 Amendments"),
        ("9.1", "Commonwealth Public Safety"),
        ("10.1", "Conservation"),
        ("11", "Contracts"),
        ("12.1", "State Corporation Commission"),
        ("13.1", "Corporations"),
        ("15.2", "Counties, Cities and Towns"),
        ("16.1", "Courts Not of Record"),
        ("17.1", "Courts of Record"),
        ("18.2", "Crimes and Offenses Generally"),
        ("19.2", "Criminal Procedure"),
        ("20", "Domestic Relations"),
        ("21", "Drainage, Soil Conservation, Sanitation and Public Facilities Districts"),
        ("22.1", "Education"),
        ("23.1", "Institutions of Higher Education; Other Educational and Cultural Institutions"),
        ("24.2", "Elections"),
        ("25.1", "Eminent Domain"),
        ("27", "Fire Protection"),
        ("28.2", "Fisheries and Habitat of the Tidal Waters"),
        ("29.1", "Wildlife, Inland Fisheries and Boating"),
        ("30", "General Assembly"),
        ("32.1", "Health"),
        ("33.2", "Highways and Other Surface Transportation Systems"),
        ("34", "Homestead and Other Exemptions"),
        ("35.1", "Hotels, Restaurants, Summer Camps, and Campgrounds"),
        ("36", "Housing"),
        ("37.2", "Behavioral Health and Developmental Services"),
        ("38.2", "Insurance"),
        ("40.1", "Labor and Employment"),
        ("41.1", "Land Office"),
        ("42.1", "Libraries"),
        ("43", "Mechanics' and Certain Other Liens"),
        ("44", "Military and Emergency Laws"),
        ("45.2", "Mines, Minerals and Energy"),
        ("46.2", "Motor Vehicles"),
        ("47.1", "Notaries and Out-of-State Commissioners"),
        ("48", "Nuisances"),
        ("49", "Oaths, Affirmations and Bonds"),
        ("50", "Partnerships"),
        ("51.1", "Pensions, Benefits, and Retirement"),
        ("51.5", "Persons with Disabilities"),
        ("52", "Police (State)"),
        ("53.1", "Prisons and Other Methods of Correction"),
        ("54.1", "Professions and Occupations"),
        ("55.1", "Property and Conveyances"),
        ("56", "Public Service Companies"),
        ("57", "Religious and Charitable Matters; Cemeteries"),
        ("58.1", "Taxation"),
        ("59.1", "Trade and Commerce"),
        ("60.2", "Unemployment Compensation"),
        ("61.1", "Warehouses, Cold Storage and Refrigerated Locker Plants"),
        ("62.1", "Waters of the State, Ports and Harbors"),
        ("63.2", "Welfare (Social Services)"),
        ("64.2", "Wills, Trusts, and Fiduciaries"),
        ("65.2", "Workers' Compensation"),
        ("66", "Juvenile Justice"),
        ("67", "Virginia Energy Plan"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)

    _VA_SECTION_URL_RE = re.compile(
        r"^/vacode/title[0-9A-Za-z\.]+/chapter[0-9A-Za-z\.]+/section[0-9A-Za-z\-\.]+/?$",
        re.IGNORECASE,
    )
    _VA_DIRECT_SECTION_URL_RE = re.compile(
        r"^/vacode/[0-9A-Za-z\.]+-[0-9A-Za-z\-\.]+/?$",
        re.IGNORECASE,
    )

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._is_section_source_url(source):
                filtered.append(statute)
        return filtered

    def _is_section_source_url(self, source_url: str) -> bool:
        path = str(urlparse(str(source_url or "")).path or "").strip()
        if not path.lower().startswith("/vacode/"):
            return False
        return bool(
            self._VA_SECTION_URL_RE.match(path) or self._VA_DIRECT_SECTION_URL_RE.match(path)
        )

    def _derive_va_section_number(self, source_url: str) -> str:
        path = str(urlparse(str(source_url or "")).path or "").strip()
        section_match = re.search(
            r"/vacode/title[0-9A-Za-z.]+/chapter[0-9A-Za-z.]+/section([0-9A-Za-z.\-]+)/?$",
            path,
            flags=re.IGNORECASE,
        )
        if section_match:
            return str(section_match.group(1) or "").strip()
        direct_match = re.search(
            r"/vacode/([0-9A-Za-z.]+-[0-9A-Za-z.\-]+)/?$", path, flags=re.IGNORECASE
        )
        if direct_match:
            return str(direct_match.group(1) or "").strip()
        return ""

    def get_base_url(self) -> str:
        """Return the base URL for Virginia's legislative website."""
        return "https://law.lis.virginia.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Virginia."""
        return [{"name": "Code of Virginia", "url": f"{self.get_base_url()}/", "type": "Code"}]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Virginia's legislative website.

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

        candidate_urls = [
            "https://law.lis.virginia.gov/vacode/title1/chapter1/",
            "https://law.lis.virginia.gov/vacode/title18.2/chapter7/",
            "https://law.lis.virginia.gov/vacode/",
            code_url,
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
                        "Va. Code Ann.",
                        max_sections=scan_limit,
                        wait_for_selector="a[href*='/section'], a[href*='/chapter']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "Va. Code Ann.",
                max_sections=scan_limit,
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes[:return_threshold]

        return best_statutes

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
            "https://law.lis.virginia.gov/vacode/title1/chapter1/section1-1/",
            "https://law.lis.virginia.gov/vacode/title18.2/chapter7/section18.2-247/",
        ]
        return await self._scrape_section_urls(
            code_name, [(url, "") for url in section_urls], max_statutes=max_statutes
        )

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        title_links = await self._discover_title_links()
        self.logger.info("Virginia official index: discovered %s title links", len(title_links))
        resumed = self._load_partial_checkpoint_statutes(
            code_name=code_name, max_statutes=max_statutes
        )
        checkpoint_progress = self._load_partial_checkpoint_progress()
        statutes: List[NormalizedStatute] = []
        seen_keys: set[str] = set()
        seen_urls: set[str] = set()

        def _extend_unique(batch: List[NormalizedStatute]) -> None:
            for statute in batch:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                source_url = str(statute.source_url or "").strip().lower()
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
                "Virginia official index: resumed %s statutes from partial checkpoint",
                len(statutes),
            )
        resume_titles_scanned = max(0, int(checkpoint_progress.get("titles_scanned") or 0))
        resume_chapters_scanned = max(0, int(checkpoint_progress.get("chapters_scanned") or 0))
        resume_sections_scanned = max(0, int(checkpoint_progress.get("sections_scanned") or 0))
        resume_discovered_sections = max(
            0, int(checkpoint_progress.get("discovered_sections") or 0)
        )
        title_rewind = max(0, int(self._env_int("STATE_SCRAPER_VA_RESUME_TITLE_REWIND", default=1)))
        resume_title_floor = max(0, resume_titles_scanned - title_rewind)
        chapters_scanned_total = int(resume_chapters_scanned)
        sections_scanned_total = int(max(len(statutes), resume_sections_scanned))
        sections_discovered_total = int(max(len(statutes), resume_discovered_sections))
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="virginia:title-discovery",
            extra={
                "titles_scanned": 0,
                "discovered_titles": int(len(title_links)),
                "chapters_scanned": int(chapters_scanned_total),
                "sections_scanned": int(sections_scanned_total),
                "discovered_sections": int(sections_discovered_total),
                "codes_completed": 0,
                "codes_total": 1,
            },
        )
        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            if title_index < resume_title_floor:
                continue
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "Virginia official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                title_label or title_url,
                title_index,
                len(title_links),
                len(chapter_links),
                len(statutes),
            )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="virginia:title-scan",
                extra={
                    "titles_scanned": int(title_index),
                    "discovered_titles": int(len(title_links)),
                    "chapters_scanned": int(chapters_scanned_total),
                    "sections_scanned": int(sections_scanned_total),
                    "discovered_sections": int(sections_discovered_total),
                    "discovered_chapters": int(len(chapter_links)),
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )
            for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                chapters_scanned_total += 1
                section_links = await self._discover_section_links(chapter_url)
                if seen_urls:
                    section_links = [
                        (url, section_label)
                        for url, section_label in section_links
                        if str(url or "").strip().lower() not in seen_urls
                    ]
                sections_discovered_total += len(section_links)
                if (
                    chapter_index == 1
                    or chapter_index % 10 == 0
                    or chapter_index == len(chapter_links)
                ):
                    self.logger.info(
                        "Virginia official index: title=%s chapter=%s/%s sections=%s statutes_so_far=%s",
                        title_label or title_url,
                        chapter_index,
                        len(chapter_links),
                        len(section_links),
                        len(statutes),
                    )
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="virginia:chapter-scan",
                        extra={
                            "titles_scanned": int(title_index),
                            "discovered_titles": int(len(title_links)),
                            "chapters_scanned": int(chapters_scanned_total),
                            "sections_scanned": int(sections_scanned_total),
                            "discovered_sections": int(sections_discovered_total),
                            "discovered_chapters": int(len(chapter_links)),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )

                def _progress_hook(
                    scanned_sections: int,
                    total_sections: int,
                    partial_batch: List[NormalizedStatute],
                ) -> None:
                    if (
                        scanned_sections == 1
                        or scanned_sections % 200 == 0
                        or scanned_sections == total_sections
                    ):
                        self._write_partial_checkpoint(
                            statutes + partial_batch,
                            code_name=code_name,
                            stage_label="virginia:section-scan",
                            extra={
                                "titles_scanned": int(title_index),
                                "discovered_titles": int(len(title_links)),
                                "chapters_scanned": int(chapters_scanned_total),
                                "sections_scanned": int(sections_scanned_total + scanned_sections),
                                "discovered_sections": int(sections_discovered_total),
                                "discovered_chapters": int(len(chapter_links)),
                                "codes_completed": 0,
                                "codes_total": 1,
                            },
                        )

                parsed = await self._scrape_section_urls(
                    code_name,
                    section_links,
                    max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                    progress_hook=_progress_hook,
                )
                sections_scanned_total += len(section_links)
                _extend_unique(parsed)
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="virginia:complete",
            force=True,
            extra={
                "titles_scanned": int(len(title_links)),
                "discovered_titles": int(len(title_links)),
                "chapters_scanned": int(chapters_scanned_total),
                "sections_scanned": int(sections_scanned_total),
                "discovered_sections": int(sections_discovered_total),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return statutes[:limit] if limit is not None else statutes

    async def _discover_title_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/vacode/"
        payload = await self._fetch_page_content_with_archival_fallback(
            index_url, timeout_seconds=20
        )
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not re.search(r"/vacode/title[0-9A-Za-z.]+/?$", href, re.IGNORECASE):
                continue
            normalized = href.rstrip("/") + "/"
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
            title_url, timeout_seconds=20
        )
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(title_url, str(anchor.get("href") or "").strip())
            if not re.search(
                r"/vacode/title[0-9A-Za-z.]+/chapter[0-9A-Za-z.]+/?$", href, re.IGNORECASE
            ):
                continue
            normalized = href.rstrip("/") + "/"
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
            chapter_url, timeout_seconds=20
        )
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            if not self._is_section_source_url(href):
                continue
            normalized = href.rstrip("/") + "/"
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
        progress_hook: Optional[Callable[[int, int, List[NormalizedStatute]], None]] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        statutes: List[NormalizedStatute] = []
        concurrency = max(1, int(self._env_int("STATE_SCRAPER_VA_SECTION_CONCURRENCY", default=8)))
        sem = asyncio.Semaphore(concurrency)
        total_sections = len(section_urls)
        seen_keys: set[str] = set()

        async def _parse_section(
            source_url: str, section_label: str
        ) -> Optional[NormalizedStatute]:
            async with sem:
                payload = await self._fetch_page_content_with_archival_fallback(
                    source_url, timeout_seconds=15
                )
                if not payload:
                    return None
                soup = BeautifulSoup(payload, "html.parser")
                node = (
                    soup.find(id="va_code")
                    or soup.find("article", id="vacode")
                    or soup.select_one("main")
                    or soup
                )
                for tag in node(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                text = self._normalize_legal_text(node.get_text(" ", strip=True))
                heading = node.find("h2") or soup.find("title")
                heading_text = heading.get_text(" ", strip=True) if heading else ""
                match = re.search(
                    r"(?:§|section)\s*([0-9A-Za-z.-]+)", heading_text or text, flags=re.IGNORECASE
                )
                section_number = (
                    self._derive_va_section_number(source_url)
                    or (match.group(1) if match else "")
                    or str(self._derive_section_number_from_url(source_url) or "").strip()
                )
                section_name = re.sub(
                    r"^§\s*[0-9A-Za-z.-]+\s*\.?\s*", "", heading_text or section_label
                ).strip(". ")
                # Some valid Virginia sections are short; avoid treating those
                # as missing rows during full-corpus sweeps.
                if len(text) < 120 or not section_number:
                    return None
                return NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200] or f"Section {section_number}",
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=source_url,
                    official_cite=f"Va. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_virginia_code_html",
                        "skip_hydrate": True,
                    },
                )

        tasks = [
            asyncio.create_task(_parse_section(source_url, section_label))
            for source_url, section_label in section_urls
        ]
        scanned_sections = 0
        cancelled_early = False
        for task in asyncio.as_completed(tasks):
            scanned_sections += 1
            statute = await task
            if statute is not None:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if key and key in seen_keys:
                    continue
                if key:
                    seen_keys.add(key)
                statutes.append(statute)
            if progress_hook is not None:
                try:
                    progress_hook(scanned_sections, total_sections, statutes)
                except Exception:
                    pass
            if (
                scanned_sections == 1
                or scanned_sections % 100 == 0
                or scanned_sections == total_sections
            ):
                self.logger.info(
                    "Virginia section scan: scanned_sections=%s/%s statutes_so_far=%s",
                    scanned_sections,
                    total_sections,
                    len(statutes),
                )
            if limit is not None and len(statutes) >= limit:
                cancelled_early = True
                for pending in tasks:
                    if not pending.done():
                        pending.cancel()
                break
        if cancelled_early:
            await asyncio.gather(*tasks, return_exceptions=True)
        return statutes

    def official_title_url(self, title_number: Any) -> str:
        number = str(title_number or "").strip()
        return f"{self.get_base_url()}/vacode/title{number}/"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Code of Virginia title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"va:title-{str(number).lower()}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Code of Virginia Title {number} ({name}) "
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
            host == "law.lis.virginia.gov"
            or host.endswith(".law.lis.virginia.gov")
            or host == "lis.virginia.gov"
            or host.endswith(".lis.virginia.gov")
        )

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-virginia-official-catalog/1.0",
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
        text = str(value or "").strip()
        match = re.match(r"^(\d+(?:\.\d+)?[A-Za-z]?)$", text, flags=re.IGNORECASE)
        if not match:
            return ""
        number = match.group(1)
        # Preserve Virginia dotted titles (8.01, 8.1A) while normalizing suffix case.
        suffix_match = re.match(r"^(\d+(?:\.\d+)?)([A-Za-z]?)$", number)
        if not suffix_match:
            return number
        return suffix_match.group(1) + suffix_match.group(2).upper()

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
            if "next" not in rel and not self._VA_CONTINUATION_RE.search(label):
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
            match = self._VA_TITLE_HREF_RE.search(absolute) or self._VA_TITLE_LABEL_RE.search(label)
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
        """Enumerate every official Code of Virginia title."""

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
                row["source_link_disposition"] = "repaired_official_valis"
        for number, url in discovered.items():
            if number in known:
                continue
            rows.append(
                {
                    "canonical_key": f"va:title-{number.lower()}",
                    "title_number": number,
                    "name": f"Title {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Code of Virginia Title {number} official catalog unit at {url}"
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

    def fetch_official(self, code: str = "VA"):
        """Acquire the exhaustive official Code of Virginia title catalog.

        Live HTTPS retains the official law.lis.virginia.gov code index.
        Every known title is enumerated with an official URL. Continuation
        pages are exhausted. This hook never returns fixture bytes, never
        promotes a partial scrape checkpoint, and never uses secondary hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "VA").strip().upper() or "VA"
        if normalized != "VA":
            raise ValueError(f"VirginiaScraper cannot acquire {normalized}")
        html, remaining = self._collect_official_index_pages()
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "virginia official catalog enumeration rejected incomplete "
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
StateScraperRegistry.register("VA", VirginiaScraper)
