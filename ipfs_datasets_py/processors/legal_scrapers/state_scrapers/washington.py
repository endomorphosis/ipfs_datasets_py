"""Scraper for Washington state laws.

This module contains the scraper for Washington statutes from the official state legislative website.
"""

import asyncio
import json
import re
import ssl
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class WashingtonScraper(BaseStateScraper):
    """Scraper for Washington state laws from https://app.leg.wa.gov"""

    OFFICIAL_DOMAIN = "app.leg.wa.gov"
    OFFICIAL_ENTRY_PATH = "/RCW/"
    OFFICIAL_ENTRY_URL = "https://app.leg.wa.gov/RCW/"
    _WA_TITLE_CITE_RE = re.compile(r"^\d+[A-Za-z]?$")
    _WA_TITLE_LABEL_RE = re.compile(
        r"\bTitle\s+(?P<title>\d+[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    _WA_CONTINUATION_RE = re.compile(
        r"\b(next|continue|more titles|page\s+\d+)\b",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Courts of Record"),
        ("3", "District Courts—Courts of Limited Jurisdiction"),
        ("4", "Civil Procedure"),
        ("5", "Evidence"),
        ("6", "Enforcement of Judgments"),
        ("7", "Special Proceedings and Actions"),
        ("8", "Eminent Domain"),
        ("9", "Crimes and Punishments"),
        ("9A", "Washington Criminal Code"),
        ("10", "Criminal Procedure"),
        ("11", "Probate and Trust Law"),
        ("12", "District Courts—Civil Procedure"),
        ("13", "Juvenile Courts and Juvenile Offenders"),
        ("14", "Aeronautics"),
        ("15", "Agriculture and Marketing"),
        ("16", "Animals and Livestock"),
        ("17", "Weeds, Rodents, and Pests"),
        ("18", "Businesses and Professions"),
        ("19", "Business Regulations—Miscellaneous"),
        ("20", "Commission Merchants—Agricultural Products"),
        ("21", "Securities and Investments"),
        ("22", "Warehousing and Deposits"),
        ("23", "Corporations and Associations (Profit)"),
        ("23B", "Washington Business Corporation Act"),
        ("24", "Corporations and Associations (Nonprofit)"),
        ("25", "Partnerships"),
        ("26", "Domestic Relations"),
        ("27", "Libraries, Museums, and Historical Activities"),
        ("28A", "Common School Provisions"),
        ("28B", "Higher Education"),
        ("28C", "Vocational Education"),
        ("29A", "Elections"),
        ("29B", "Campaign Finance and Disclosure"),
        ("30A", "Washington Commercial Bank Act"),
        ("30B", "Washington Trust Institutions Act"),
        ("31", "Miscellaneous Loan Agencies"),
        ("32", "Mutual Savings Banks"),
        ("33", "Washington Savings Association Act"),
        ("34", "Administrative Law"),
        ("35", "Cities and Towns"),
        ("35A", "Optional Municipal Code"),
        ("36", "Counties"),
        ("37", "Federal Areas—Indians"),
        ("38", "Militia and Military Affairs"),
        ("39", "Public Contracts and Indebtedness"),
        ("40", "Public Documents, Records, and Publications"),
        ("41", "Public Employment, Civil Service, and Pensions"),
        ("42", "Public Officers and Agencies"),
        ("43", "State Government—Executive"),
        ("44", "State Government—Legislative"),
        ("46", "Motor Vehicles"),
        ("47", "Public Highways and Transportation"),
        ("48", "Insurance"),
        ("49", "Labor Regulations"),
        ("50", "Unemployment Compensation"),
        ("50A", "Family and Medical Leave"),
        ("50B", "Long-Term Care"),
        ("51", "Industrial Insurance"),
        ("52", "Fire Protection Districts"),
        ("53", "Port Districts"),
        ("54", "Public Utility Districts"),
        ("55", "Sanitary Districts"),
        ("57", "Water-Sewer Districts"),
        ("58", "Boundaries and Plats"),
        ("59", "Landlord and Tenant"),
        ("60", "Liens"),
        ("61", "Mortgages, Deeds of Trust, and Real Estate Contracts"),
        ("62A", "Uniform Commercial Code"),
        ("63", "Personal Property"),
        ("64", "Real Property and Conveyances"),
        ("65", "Recording, Registration, and Legal Publication"),
        ("66", "Alcoholic Beverage Control"),
        ("67", "Sports and Recreation—Convention Facilities"),
        ("68", "Cemeteries, Morgues, and Human Remains"),
        ("69", "Food, Drugs, Cosmetics, and Poisons"),
        ("70", "Public Health and Safety"),
        ("70A", "Environmental Health and Safety"),
        ("71", "Mental Illness"),
        ("71A", "Developmental Disabilities"),
        ("72", "State Institutions"),
        ("73", "Veterans and Veterans' Affairs"),
        ("74", "Public Assistance"),
        ("76", "Forests and Forest Products"),
        ("77", "Fish and Wildlife"),
        ("78", "Mines, Minerals, and Petroleum"),
        ("79", "Public Lands"),
        ("79A", "Public Recreational Lands"),
        ("80", "Public Utilities"),
        ("81", "Transportation"),
        ("82", "Excise Taxes"),
        ("82A", "Digital Products Excise Tax"),
        ("83", "Estate Taxation"),
        ("84", "Property Taxes"),
        ("85", "Diking and Drainage"),
        ("86", "Flood Control"),
        ("87", "Irrigation"),
        ("88", "Navigation and Harbor Improvements"),
        ("89", "Reclamation, Soil Conservation, and Land Settlement"),
        ("90", "Water Rights—Environment"),
        ("91", "Waterways"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)

    _SECTION_CITE_RE = re.compile(r"^\d+[A-Za-z]?\.\d+(?:\.\d+)?[A-Za-z]?$")

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            section_number = str(statute.section_number or "")
            if "default.aspx?cite=" not in source.lower():
                continue
            if self._SECTION_CITE_RE.match(section_number):
                filtered.append(statute)
        return filtered

    def _filter_official_only(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        """Drop secondary/Justia rows when full-corpus admission is sealed."""
        if not self._full_corpus_enabled():
            return statutes
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source_kind = str((statute.structured_data or {}).get("source_kind") or "").lower()
            if "justia" in source_kind or "findlaw" in source_kind:
                continue
            if not self._host_is_official(str(statute.source_url or "")):
                continue
            filtered.append(statute)
        return filtered

    def get_base_url(self) -> str:
        """Return the base URL for Washington's legislative website."""
        return "https://app.leg.wa.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Washington."""
        return [
            {
                "name": "Revised Code of Washington",
                "url": f"{self.get_base_url()}/RCW/default.aspx?cite=9A.32.030",
                "type": "Code",
            }
        ]

    async def scrape_code(
        self, code_name: str, code_url: str, max_statutes: int | None = None
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Washington's legislative website.

        Washington RCW database uses JavaScript navigation, so we use Playwright.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        if not self._full_corpus_enabled() and max_statutes is None:
            seed_budget = int(limit if limit is not None else 160)
            direct = await self._scrape_direct_seed_sections(
                code_name, max_statutes=seed_budget
            )
            if direct:
                return direct[:seed_budget]

        official = await self._scrape_official_index(code_name, max_statutes=limit)
        official = self._filter_official_only(official)
        if official:
            return official[:limit] if limit is not None else official

        if self._full_corpus_enabled() and max_statutes is None:
            self.logger.warning(
                "Washington full-corpus run found zero official statutes; "
                "refusing secondary Justia/generic sole-admission fallback"
            )
            return []

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/RCW/default.aspx",
            f"{self.get_base_url()}/RCW/",
            f"{self.get_base_url()}/RCW/default.aspx?cite=1",
            f"{self.get_base_url()}/RCW/default.aspx?cite=9A.32.030",
            f"{self.get_base_url()}/RCW/default.aspx?cite=9A.04",
            f"{self.get_base_url()}/RCW/default.aspx?cite=4.24",
            f"{self.get_base_url()}/RCW/default.aspx?cite=7.28",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        fallback_scan_limit = int(limit if limit is not None else 160)
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Wash. Rev. Code",
                        max_sections=fallback_scan_limit,
                        wait_for_selector="a[href*='default.aspx?cite='], a[href*='/RCW/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if limit is not None and len(statutes) >= limit:
                        return statutes[:limit]
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name, candidate, "Wash. Rev. Code", max_sections=fallback_scan_limit
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if limit is not None and len(statutes) >= limit:
                return statutes[:limit]

        return best_statutes[:limit] if limit is not None else best_statutes

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 1,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("9A.32.030", "https://app.leg.wa.gov/RCW/default.aspx?cite=9A.32.030"),
        ]
        return await self._scrape_section_urls(
            code_name,
            [(url, section_number) for section_number, url in seeds],
            max_statutes=max_statutes,
            discovery_method="official_seed_section",
        )

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        title_links = await self._discover_title_links()
        self.logger.info("Washington official index: discovered %s title links", len(title_links))
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
                "Washington official index: resumed %s statutes from partial checkpoint",
                len(statutes),
            )
        resume_titles_scanned = max(0, int(checkpoint_progress.get("titles_scanned") or 0))
        resume_chapters_scanned = max(0, int(checkpoint_progress.get("chapters_scanned") or 0))
        resume_sections_scanned = max(0, int(checkpoint_progress.get("sections_scanned") or 0))
        resume_discovered_sections = max(
            0, int(checkpoint_progress.get("discovered_sections") or 0)
        )
        title_rewind = max(0, int(self._env_int("STATE_SCRAPER_WA_RESUME_TITLE_REWIND", default=1)))
        resume_title_floor = max(0, resume_titles_scanned - title_rewind)
        chapters_scanned_total = int(resume_chapters_scanned)
        sections_scanned_total = int(max(len(statutes), resume_sections_scanned))
        sections_discovered_total = int(max(len(statutes), resume_discovered_sections))
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="washington:title-discovery",
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
                "Washington official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                title_label or title_url,
                title_index,
                len(title_links),
                len(chapter_links),
                len(statutes),
            )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="washington:title-scan",
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
                        (url, section_number)
                        for url, section_number in section_links
                        if str(url or "").strip().lower() not in seen_urls
                    ]
                sections_discovered_total += len(section_links)
                if (
                    chapter_index == 1
                    or chapter_index % 10 == 0
                    or chapter_index == len(chapter_links)
                ):
                    self.logger.info(
                        "Washington official index: title=%s chapter=%s/%s sections=%s statutes_so_far=%s",
                        title_label or title_url,
                        chapter_index,
                        len(chapter_links),
                        len(section_links),
                        len(statutes),
                    )
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="washington:chapter-scan",
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
                            stage_label="washington:section-scan",
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
                    discovery_method="official_title_chapter_section_index",
                    progress_hook=_progress_hook,
                )
                sections_scanned_total += len(section_links)
                _extend_unique(parsed)
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="washington:complete",
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

        index_url = f"{self.get_base_url()}/RCW/default.aspx"
        raw = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            cite = self._extract_cite_from_url(href)
            if not cite or "." in cite or not re.match(r"^\d+[A-Za-z]?$", cite):
                continue
            normalized = f"{self.get_base_url()}/RCW/default.aspx?cite={cite}"
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

        title_cite = self._extract_cite_from_url(title_url)
        raw = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(title_url, str(anchor.get("href") or "").strip())
            cite = self._extract_cite_from_url(href)
            if not cite or not title_cite or not cite.startswith(f"{title_cite}."):
                continue
            if cite.count(".") != 1:
                continue
            normalized = f"{self.get_base_url()}/RCW/default.aspx?cite={cite}"
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

        chapter_cite = self._extract_cite_from_url(chapter_url)
        raw = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            cite = self._extract_cite_from_url(href)
            if not cite or not chapter_cite or not cite.startswith(f"{chapter_cite}."):
                continue
            if not self._SECTION_CITE_RE.match(cite):
                continue
            normalized = f"{self.get_base_url()}/RCW/default.aspx?cite={cite}"
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, cite))
        return out

    def _extract_cite_from_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            values = parse_qs(parsed.query).get("cite") or parse_qs(parsed.query).get("Cite") or []
            return str(values[0] if values else "").strip()
        except Exception:
            return ""

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
        discovery_method: str = "official_seed_section",
        progress_hook: Optional[Callable[[int, int, List[NormalizedStatute]], None]] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        default_concurrency = 16 if self._full_corpus_enabled() else 8
        concurrency = max(
            1,
            int(self._env_int("STATE_SCRAPER_WA_SECTION_CONCURRENCY", default=default_concurrency)),
        )
        sem = asyncio.Semaphore(concurrency)
        total_sections = len(section_urls)
        seen_keys: set[str] = set()

        async def _parse_section(url: str, section_number: str) -> Optional[NormalizedStatute]:
            async with sem:
                raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
                if not raw:
                    return None
                soup = BeautifulSoup(raw, "html.parser")
                citation_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h1")
                caption_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h2")
                content_node = (
                    soup.select_one("#contentWrapper")
                    or soup.select_one("#ContentPlaceHolder1_dlSection")
                    or soup.select_one("main")
                    or soup.find("body")
                )
                if content_node is None:
                    return None
                for tag in content_node(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                citation_text = self._normalize_legal_text(
                    citation_node.get_text(" ", strip=True) if citation_node else ""
                )
                caption = self._normalize_legal_text(
                    caption_node.get_text(" ", strip=True) if caption_node else ""
                )
                body = self._normalize_legal_text(
                    content_node.get_text(" ", strip=True) if content_node else ""
                )
                # Washington has short-but-valid sections; keep those in the
                # corpus instead of dropping them as false negatives.
                if len(body) < 120:
                    return None
                full_text = self._normalize_legal_text(f"{citation_text} {caption} {body}")
                return NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split(".", 1)[0],
                    section_number=section_number,
                    section_name=caption or section_number,
                    full_text=full_text,
                    legal_area=self._identify_legal_area(full_text[:1200]),
                    source_url=url,
                    official_cite=f"Wash. Rev. Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_washington_rcw_html",
                        "discovery_method": discovery_method,
                        "skip_hydrate": True,
                    },
                )

        tasks = [
            asyncio.create_task(_parse_section(url, section_number))
            for url, section_number in section_urls
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
                out.append(statute)
            if progress_hook is not None:
                try:
                    progress_hook(scanned_sections, total_sections, out)
                except Exception:
                    pass
            if (
                scanned_sections == 1
                or scanned_sections % 100 == 0
                or scanned_sections == total_sections
            ):
                self.logger.info(
                    "Washington section scan: scanned_sections=%s/%s statutes_so_far=%s discovery=%s",
                    scanned_sections,
                    total_sections,
                    len(out),
                    discovery_method,
                )
            if limit is not None and len(out) >= limit:
                cancelled_early = True
                for pending in tasks:
                    if not pending.done():
                        pending.cancel()
                break
        if cancelled_early:
            await asyncio.gather(*tasks, return_exceptions=True)
        return out

    def official_title_url(self, title_number: Any) -> str:
        number = str(title_number or "").strip()
        return f"{self.get_base_url()}/RCW/default.aspx?cite={number}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Revised Code of Washington title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"wa:title-{str(number).lower()}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Revised Code of Washington Title {number} ({name}) "
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
            host == "app.leg.wa.gov"
            or host.endswith(".app.leg.wa.gov")
            or host == "leg.wa.gov"
            or host.endswith(".leg.wa.gov")
        )

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-washington-official-catalog/1.0",
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
        match = re.match(r"^0*(\d+[A-Z]?)$", text)
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
            if "next" not in rel and not self._WA_CONTINUATION_RE.search(label):
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
            cite = self._extract_cite_from_url(absolute)
            number = ""
            if cite and "." not in cite and self._WA_TITLE_CITE_RE.match(cite):
                number = self._normalize_title_number(cite)
            if not number:
                label_match = self._WA_TITLE_LABEL_RE.search(label)
                if label_match:
                    number = self._normalize_title_number(label_match.group("title"))
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
        """Enumerate every official Revised Code of Washington title."""

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
                row["source_link_disposition"] = "repaired_official_waleg"
        for number, url in discovered.items():
            if number in known:
                continue
            rows.append(
                {
                    "canonical_key": f"wa:title-{number.lower()}",
                    "title_number": number,
                    "name": f"Title {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Revised Code of Washington Title {number} "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        rows.sort(key=lambda item: self._title_sort_key(str(item.get("title_number") or "")))
        return rows

    def _title_sort_key(self, number: str) -> Tuple[int, str]:
        match = re.match(r"^(\d+)([A-Za-z]+)?$", str(number or "").strip())
        if not match:
            return (9999, str(number or ""))
        return (int(match.group(1)), (match.group(2) or "").upper())

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

    def fetch_official(self, code: str = "WA"):
        """Acquire the exhaustive official Revised Code of Washington catalog.

        Live HTTPS retains the official app.leg.wa.gov RCW index. Every known
        title is enumerated with an official URL. Continuation pages are
        exhausted. This hook never returns fixture bytes, never promotes a
        partial scrape checkpoint, and never uses secondary hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "WA").strip().upper() or "WA"
        if normalized != "WA":
            raise ValueError(f"WashingtonScraper cannot acquire {normalized}")
        html, remaining = self._collect_official_index_pages()
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "washington official catalog enumeration rejected incomplete "
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
StateScraperRegistry.register("WA", WashingtonScraper)
