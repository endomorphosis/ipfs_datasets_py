"""Scraper for North Carolina state laws.

Official-source path walks the North Carolina General Assembly HTML tree on
ncleg.gov. The withdrawn v2026.07 contaminated NC bucket object is replaced
from official clean statutory catalog text. Secondary Justia mirrors are
never sole-admitted for full-corpus certification.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import ssl
import urllib.request
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class NorthCarolinaScraper(BaseStateScraper):
    """Scraper for North Carolina state laws from https://www.ncleg.gov"""

    OFFICIAL_DOMAIN = "www.ncleg.gov"
    OFFICIAL_ENTRY_PATH = "/Laws/GeneralStatutes"
    OFFICIAL_ENTRY_URL = "https://www.ncleg.gov/Laws/GeneralStatutes"
    OFFICIAL_TOC_URL = "https://www.ncleg.gov/Laws/GeneralStatutesTOC"
    CONTAMINATED_BUCKET_REPLACEMENT_REASON = (
        "contaminated_bucket_replaced_from_official_clean_text"
    )
    NAVIGATION_FOOTER_MARKERS = (
        "skip to main",
        "skip to content",
        "skip to navigation",
        "privacy policy",
        "site map",
        "sitemap",
        "copyright ©",
        "footer navigation",
        "cookie policy",
        "terms of use",
    )
    _NC_SECTION_URL_RE = re.compile(r"/enactedlegislation/statutes/html/bysection/chapter_[0-9A-Za-z]+/gs_[0-9A-Za-z\-\.]+\.html$", re.IGNORECASE)
    _NC_CHAPTER_URL_RE = re.compile(r"/laws/generalstatutesections/chapter[0-9A-Za-z]+$", re.IGNORECASE)
    _NC_CHAPTER_PATH_RE = re.compile(
        r"/laws/generalstatutesections/chapter([0-9]+[A-Za-z]?)$",
        re.IGNORECASE,
    )
    _NC_CHAPTER_BYCHAPTER_RE = re.compile(
        r"/enactedlegislation/statutes/html/bychapter/chapter_([0-9]+[A-Za-z]?)\.html$",
        re.IGNORECASE,
    )
    _NC_CHAPTER_LABEL_RE = re.compile(r"\bChapter\s+([0-9]+[A-Za-z]?)\b", re.IGNORECASE)
    OFFICIAL_CHAPTERS = (
        ("1", "Civil Procedure"),
        ("1A", "Rules of Civil Procedure"),
        ("1B", "Contribution"),
        ("1C", "Enforcement of Judgments"),
        ("1D", "Punitive Damages"),
        ("1E", "Eastern Band of Cherokee Indians"),
        ("1F", "North Carolina Uniform Interstate Depositions and Discovery Act"),
        ("1G", "North Carolina False Claims Act"),
        ("4", "Common Law"),
        ("5A", "Contempt"),
        ("6", "Liability for Court Costs"),
        ("7A", "Judicial Department"),
        ("7B", "Juvenile Code"),
        ("8", "Evidence"),
        ("8B", "Interpreters for Deaf Persons"),
        ("8C", "Evidence Code"),
        ("9", "Jurors"),
        ("10B", "Notaries"),
        ("11", "Oaths"),
        ("12", "Statutory Construction"),
        ("13", "Citizenship Restored"),
        ("14", "Criminal Law"),
        ("15", "Criminal Procedure"),
        ("15A", "Criminal Procedure Act"),
        ("15B", "Victims Compensation"),
        ("15C", "Address Confidentiality Program"),
        ("16", "Gaming Contracts and Futures"),
        ("17", "Habeas Corpus"),
        ("17C", "North Carolina Criminal Justice Education and Training Standards Commission"),
        ("17D", "North Carolina Justice Academy"),
        ("17E", "North Carolina Sheriffs' Education and Training Standards Commission"),
        ("18B", "Regulation of Alcoholic Beverages"),
        ("18C", "North Carolina State Lottery"),
        ("19", "Offenses Against Public Morals"),
        ("19A", "Protection of Animals"),
        ("20", "Motor Vehicles"),
        ("22B", "Contracts Against Public Policy"),
        ("22C", "Payments to Subcontractors"),
        ("23", "Debtor and Creditor"),
        ("24", "Interest"),
        ("25", "Uniform Commercial Code"),
        ("25A", "Retail Installment Sales Act"),
        ("25B", "Credit"),
        ("26", "Suretyship"),
        ("28A", "Administration of Decedents' Estates"),
        ("28B", "Estates of Absentees in Military Service"),
        ("28C", "Estates of Missing Persons"),
        ("29", "Intestate Succession"),
        ("30", "Surviving Spouses"),
        ("31", "Wills"),
        ("31A", "Acts Barring Property Rights"),
        ("31B", "Renunciation of Property and Renunciation of Fiduciary Powers Act"),
        ("32", "Fiduciaries"),
        ("32A", "Powers of Attorney"),
        ("32C", "North Carolina Uniform Power of Attorney Act"),
        ("33A", "North Carolina Uniform Transfers to Minors Act"),
        ("34", "Veterans' Guardianship Act"),
        ("35A", "Incompetency and Guardianship"),
        ("36C", "North Carolina Uniform Trust Code"),
        ("36E", "Uniform Prudent Management of Institutional Funds Act"),
        ("38A", "Landowner Liability"),
        ("39", "Conveyances"),
        ("40A", "Eminent Domain"),
        ("41", "Estates"),
        ("41A", "State Fair Housing Act"),
        ("42", "Landlord and Tenant"),
        ("42A", "Vacation Rentals"),
        ("43", "Land Registration"),
        ("44A", "Statutory Liens and Charges"),
        ("45", "Mortgages and Deeds of Trust"),
        ("45A", "Good Funds Settlement Act"),
        ("46A", "Partition"),
        ("47", "Probate and Registration"),
        ("47B", "Real Property Marketable Title Act"),
        ("47C", "North Carolina Condominium Act"),
        ("47E", "Residential Property Disclosure Act"),
        ("47F", "North Carolina Planned Community Act"),
        ("48", "Adoptions"),
        ("48A", "Minors"),
        ("49", "Children Born Out of Wedlock"),
        ("50", "Divorce and Alimony"),
        ("50A", "Uniform Child-Custody Jurisdiction and Enforcement Act"),
        ("50B", "Domestic Violence"),
        ("50C", "Civil No-Contact Orders"),
        ("51", "Marriage"),
        ("52", "Powers and Liabilities of Married Persons"),
        ("52B", "Uniform Premarital Agreement Act"),
        ("52C", "Uniform Interstate Family Support Act"),
        ("53C", "Regulation of Banks"),
        ("54", "Cooperative Organizations"),
        ("54B", "Savings and Loan Associations"),
        ("54C", "Savings Banks"),
        ("55", "North Carolina Business Corporation Act"),
        ("55A", "North Carolina Nonprofit Corporation Act"),
        ("55B", "Professional Corporation Act"),
        ("55D", "Filings, Names, and Registered Agents"),
        ("57D", "North Carolina Limited Liability Company Act"),
        ("58", "Insurance"),
        ("59", "Partnership"),
        ("62", "Public Utilities"),
        ("63", "Aeronautics"),
        ("64", "Aliens"),
        ("65", "Cemeteries"),
        ("66", "Commerce and Business"),
        ("67", "Dogs"),
        ("68", "Fences and Stock Law"),
        ("69", "Fire Protection"),
        ("70", "Indian Antiquities, Archaeological Resources and Unmarked Human Skeletal Remains Protection"),
        ("71A", "Indians"),
        ("72", "Inns, Hotels and Restaurants"),
        ("74", "Mines and Quarries"),
        ("74C", "Private Protective Services"),
        ("74D", "Alarm Systems"),
        ("74E", "Company Police Act"),
        ("74F", "Locksmith Licensing Act"),
        ("74G", "Campus Police Act"),
        ("75", "Monopolies, Trusts and Consumer Protection"),
        ("75A", "Boating and Water Safety"),
        ("75D", "Racketeer Influenced and Corrupt Organizations"),
        ("77", "Rivers, Creeks and Coastal Waters"),
        ("78A", "North Carolina Securities Act"),
        ("78C", "Investment Advisers"),
        ("80", "Trademarks, Brands, etc."),
        ("81A", "Weights and Measures Act of 1975"),
        ("83A", "Architects"),
        ("84", "Attorneys-at-Law"),
        ("85B", "Auctions and Auctioneers"),
        ("86A", "Barbers"),
        ("87", "Contractors"),
        ("88B", "Cosmetic Art"),
        ("89C", "Engineering and Land Surveying"),
        ("89E", "Geologists"),
        ("89F", "North Carolina Soil Scientist Licensing Act"),
        ("90", "Medicine and Allied Occupations"),
        ("90A", "Sanitarians and Water and Wastewater Treatment Facility Operators"),
        ("90B", "Social Worker Certification and Licensure Act"),
        ("93", "Certified Public Accountants"),
        ("93A", "Real Estate License Law"),
        ("93B", "Occupational Licensing Boards"),
        ("93E", "North Carolina Appraisers Act"),
        ("95", "Department of Labor and Labor Regulations"),
        ("96", "Employment Security"),
        ("97", "Workers' Compensation Act"),
        ("99B", "Products Liability"),
        ("99E", "Special Liability Provisions"),
        ("100", "Monuments, Memorials and Parks"),
        ("101", "Names of Persons"),
        ("102", "Official Survey Base"),
        ("103", "Sundays, Holidays and Special Days"),
        ("104E", "North Carolina Radiation Protection Act"),
        ("105", "Taxation"),
        ("105A", "Setoff Debt Collection Act"),
        ("106", "Agriculture"),
        ("108A", "Social Services"),
        ("110", "Child Welfare"),
        ("111", "Aid to the Blind"),
        ("113", "Conservation and Development"),
        ("113A", "Pollution Control and Environment"),
        ("114", "Department of Justice"),
        ("115C", "Elementary and Secondary Education"),
        ("115D", "Community Colleges"),
        ("116", "Higher Education"),
        ("120", "General Assembly"),
        ("121", "Archives and History"),
        ("122C", "Mental Health, Developmental Disabilities, and Substance Abuse Act of 1985"),
        ("126", "North Carolina Human Resources Act"),
        ("127A", "Militia"),
        ("128", "Offices and Public Officers"),
        ("130A", "Public Health"),
        ("131D", "Inspection and Licensing of Facilities"),
        ("131E", "Health Care Facilities and Services"),
        ("132", "Public Records"),
        ("135", "Retirement System for Teachers and State Employees; Social Security; State Health Plan"),
        ("136", "Transportation"),
        ("138A", "State Government Ethics Act"),
        ("143", "State Departments, Institutions, and Commissions"),
        ("143B", "Executive Organization Act of 1973"),
        ("143C", "State Budget Act"),
        ("146", "State Lands"),
        ("147", "State Officers"),
        ("148", "State Prison System"),
        ("150B", "Administrative Procedure Act"),
        ("153A", "Counties"),
        ("159", "Local Government Finance"),
        ("160A", "Cities and Towns"),
        ("160D", "Local Planning and Development Regulation"),
        ("161", "Register of Deeds"),
        ("162", "Sheriff"),
        ("163", "Elections and Election Laws"),
        ("164", "Concerning the General Statutes of North Carolina"),
        ("165", "Veterans"),
        ("166A", "North Carolina Emergency Management Act"),
        ("168", "Persons with Disabilities"),
        ("168A", "Persons With Disabilities Protection Act"),
    )
    OFFICIAL_CHAPTER_COUNT = len(OFFICIAL_CHAPTERS)
    DEFAULT_CONTAMINATED_BUCKET_SEEDS = (
        {
            "canonical_key": "nc:bucket-chapter-1",
            "label": "North Carolina General Statutes Chapter 1 Civil Procedure",
            "source_url": "https://law.justia.com/codes/north-carolina/chapter-1/",
            "chapter_number": "1",
            "text": (
                "Skip to main content Site Map Privacy Policy Copyright © "
                "North Carolina General Assembly Footer navigation Chapter 1 Civil Procedure"
            ),
        },
        {
            "canonical_key": "nc:bucket-chapter-14",
            "label": "North Carolina General Statutes Chapter 14 Criminal Law",
            "source_url": "https://law.justia.com/codes/north-carolina/chapter-14/",
            "chapter_number": "14",
            "text": (
                "Skip to navigation Cookie Policy Footer navigation Copyright © "
                "North Carolina Chapter 14 Criminal Law sitemap"
            ),
        },
        {
            "canonical_key": "nc:bucket-contaminated-untitled",
            "label": "open-us-law-bucket North Carolina seed row with navigation and footer contamination",
            "source_url": "",
            "text": "Skip to main content Privacy Policy Footer navigation Copyright ©",
        },
        {
            "canonical_key": "nc:bucket-absent-object",
            "label": "Absent contaminated North Carolina v2026.07 bucket object without a recoverable official identifier",
            "source_url": "",
        },
    )

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._NC_SECTION_URL_RE.search(source) or self._NC_CHAPTER_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for North Carolina's legislative website."""
        return "https://www.ncleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for North Carolina."""
        return [{
            "name": "North Carolina General Statutes",
            "url": f"{self.get_base_url()}/Laws/GeneralStatutes",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from North Carolina's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._effective_scrape_limit(max_statutes, default=160) or 1000000
        official = await self._scrape_official_index(
            code_name,
            max_statutes=None if return_threshold == 1000000 else int(return_threshold),
        )
        if official:
            return official[: int(return_threshold)]

        candidate_urls = [
            f"{self.get_base_url()}/Laws/GeneralStatuteSections/Chapter1",
            f"{self.get_base_url()}/Laws/GeneralStatutesTOC",
            code_url,
            f"{self.get_base_url()}/Laws/GeneralStatutes",
            f"{self.get_base_url()}/Laws",
            # Archive fallback candidate when live endpoints fluctuate.
            "https://web.archive.org/web/20251017000000/https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter1",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
            if direct:
                return direct[: int(return_threshold)]
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "N.C. Gen. Stat.",
                        max_sections=max(10, return_threshold),
                        wait_for_selector="a[href*='/BySection/'][href*='GS_'], a[href*='/GeneralStatuteSections/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= int(return_threshold):
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "N.C. Gen. Stat.", max_sections=max(10, return_threshold))
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= int(return_threshold):
                return statutes

        return best_statutes

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        resumed = self._load_partial_checkpoint_statutes(code_name=code_name, max_statutes=limit)
        chapter_urls = await self._discover_chapter_urls()
        self.logger.info("North Carolina official index: discovered %s chapter urls", len(chapter_urls))
        statutes: List[NormalizedStatute] = []
        seen_source_urls: set[str] = set()
        seen_keys: set[str] = set()

        def _extend_unique(batch: List[NormalizedStatute]) -> None:
            for statute in batch:
                source_url = str(statute.source_url or "").strip()
                key = str(statute.statute_id or source_url).strip().lower()
                if source_url and source_url in seen_source_urls:
                    continue
                if key and key in seen_keys:
                    continue
                if source_url:
                    seen_source_urls.add(source_url)
                if key:
                    seen_keys.add(key)
                statutes.append(statute)
                if limit is not None and len(statutes) >= limit:
                    break

        if resumed:
            _extend_unique(resumed)
            self.logger.info(
                "North Carolina official index: resumed %s statutes from checkpoint",
                len(statutes),
            )

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="north-carolina:chapter-discovery",
            extra={
                "chapters_scanned": 0,
                "discovered_chapters": int(len(chapter_urls)),
                "codes_completed": 0,
                "codes_total": 1,
            },
        )
        for chapter_index, chapter_url in enumerate(chapter_urls, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            remaining = None if limit is None else max(0, limit - len(statutes))
            if remaining is not None and remaining <= 0:
                break
            section_urls = await self._discover_section_urls(chapter_url, limit=remaining)
            if seen_source_urls:
                section_urls = [url for url in section_urls if url not in seen_source_urls]
            parsed = await self._scrape_section_urls(
                code_name,
                section_urls,
                max_statutes=remaining,
                progress_hook=(
                    lambda scanned_sections, total_sections, partial_batch, chapter_index=chapter_index: (
                        self._write_partial_checkpoint(
                            statutes + partial_batch,
                            code_name=code_name,
                            stage_label="north-carolina:section-scan",
                            extra={
                                "chapters_scanned": int(max(0, chapter_index - 1)),
                                "current_chapter": int(chapter_index),
                                "discovered_chapters": int(len(chapter_urls)),
                                "sections_scanned": int(scanned_sections),
                                "discovered_sections": int(total_sections),
                                "codes_completed": 0,
                                "codes_total": 1,
                            },
                        )
                        if (
                            scanned_sections == 1
                            or scanned_sections % 200 == 0
                            or scanned_sections == total_sections
                        )
                        else None
                    )
                ),
            )
            _extend_unique(parsed)
            if chapter_index == 1 or chapter_index % 25 == 0 or chapter_index == len(chapter_urls):
                self.logger.info(
                    "North Carolina official index: chapter=%s/%s sections=%s statutes_so_far=%s",
                    chapter_index,
                    len(chapter_urls),
                    len(section_urls),
                    len(statutes),
                )
            if chapter_index == 1 or chapter_index % 10 == 0 or chapter_index == len(chapter_urls):
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="north-carolina:chapter-scan",
                    extra={
                        "chapters_scanned": int(chapter_index),
                        "discovered_chapters": int(len(chapter_urls)),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="north-carolina:complete",
            force=True,
            extra={
                "chapters_scanned": int(len(chapter_urls)),
                "discovered_chapters": int(len(chapter_urls)),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return statutes[:limit] if limit is not None else statutes

    async def _discover_chapter_urls(self) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        toc_url = f"{self.get_base_url()}/Laws/GeneralStatutesTOC"
        html = await self._request_text_direct(toc_url, timeout=30)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href.startswith("/Laws/GeneralStatuteSections/Chapter"):
                continue
            absolute = urljoin(toc_url, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            out.append(absolute)
        return out

    async def _discover_section_urls(self, chapter_url: str, limit: Optional[int] = None) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._request_text_direct(chapter_url, timeout=40)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href.startswith("/EnactedLegislation/Statutes/HTML/BySection/Chapter_") or not href.endswith(".html"):
                continue
            absolute = urljoin(chapter_url, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            out.append(absolute)
            if limit is not None and len(out) >= int(limit):
                break
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[str],
        *,
        max_statutes: Optional[int],
        progress_hook: Optional[Callable[[int, int, List[NormalizedStatute]], None]] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        concurrency = max(1, int(os.getenv("NORTH_CAROLINA_SECTION_CONCURRENCY", "8") or "8"))
        sem = asyncio.Semaphore(concurrency)

        async def _parse_source_url(source_url: str) -> Optional[NormalizedStatute]:
            html = await self._request_text_direct(source_url, timeout=20)
            if not html:
                return None
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 80:
                return None
            section_number_match = re.search(r"§\s*([0-9A-Za-z\-\.]+)\.", text)
            section_number = section_number_match.group(1).strip() if section_number_match else ""
            if not section_number:
                derived = source_url.rsplit("/", 1)[-1]
                derived = re.sub(r"^GS_", "", derived, flags=re.IGNORECASE)
                derived = re.sub(r"\.html$", "", derived, flags=re.IGNORECASE)
                section_number = derived.replace("_", "-")
            section_name_match = re.search(rf"§\s*{re.escape(section_number)}\.\s*([^\.]{{2,220}})", text)
            section_name = self._normalize_legal_text(section_name_match.group(1)) if section_name_match else f"G.S. {section_number}"
            return NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § {section_number}",
                code_name=code_name,
                section_number=section_number,
                section_name=section_name[:200],
                full_text=text[:14000],
                legal_area=self._identify_legal_area(section_name or text[:800]),
                source_url=source_url,
                official_cite=f"N.C. Gen. Stat. § {section_number}",
                structured_data={
                    "source_kind": "official_north_carolina_general_statutes_html",
                    "discovery_method": "official_toc_chapter_section_html",
                    "skip_hydrate": True,
                },
            )

        async def _bounded_parse(source_url: str) -> Optional[NormalizedStatute]:
            async with sem:
                try:
                    return await _parse_source_url(source_url)
                except Exception:
                    return None

        tasks = [asyncio.create_task(_bounded_parse(source_url)) for source_url in section_urls]
        total_sections = len(tasks)
        cancelled_early = False
        for scanned_sections, task in enumerate(asyncio.as_completed(tasks), start=1):
            statute = await task
            if statute is not None:
                out.append(statute)
            if progress_hook is not None:
                try:
                    progress_hook(scanned_sections, total_sections, out)
                except Exception:
                    pass
            if limit is not None and len(out) >= limit:
                cancelled_early = True
                for pending_task in tasks:
                    if not pending_task.done():
                        pending_task.cancel()
                break
        if cancelled_early:
            await asyncio.gather(*tasks, return_exceptions=True)
        return out

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("1-1", f"{self.get_base_url()}/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-1.html"),
            ("14-17", f"{self.get_base_url()}/EnactedLegislation/Statutes/HTML/BySection/Chapter_14/GS_14-17.html"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, source_url in seeds[: max(1, int(max_statutes or 1))]:
            html = await self._request_text_direct(source_url, timeout=18)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 80:
                continue
            name_match = re.search(rf"§\s*{re.escape(section_number)}[.;]?\s*([^§]{{4,180}}?)(?:\.|$)", text)
            section_name = name_match.group(1).strip() if name_match else f"G.S. {section_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text[:14000],
                    legal_area=self._identify_legal_area(section_name),
                    source_url=source_url,
                    official_cite=f"N.C. Gen. Stat. § {section_number}",
                    structured_data={
                        "source_kind": "official_north_carolina_general_statutes_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        canonical = self._canonicalize_statute_url(url)
        for _ in range(2):
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    canonical,
                    timeout_seconds=max(5, int(timeout)),
                )
            except Exception:
                payload = b""
            if payload:
                try:
                    return payload.decode("utf-8", errors="replace")
                except Exception:
                    return ""
            await asyncio.sleep(0.2)

        def _request() -> str:
            try:
                req = urllib.request.Request(canonical, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""

    def official_chapter_url(self, chapter_number: object) -> str:
        number = str(chapter_number or "").strip()
        return f"{self.get_base_url()}/Laws/GeneralStatuteSections/Chapter{number}"

    def official_chapter_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official North Carolina General Statutes chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_CHAPTERS:
            url = self.official_chapter_url(number)
            rows.append(
                {
                    "canonical_key": f"nc:chapter-{number.lower()}",
                    "chapter_number": number,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": self._official_clean_text(number, name, url),
                }
            )
        return rows

    def is_official_nc_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith(".ncleg.gov") or host == "ncleg.gov"

    def _looks_like_bucket_seed_url(self, url: str) -> bool:
        text = str(url or "").strip().lower()
        if not text:
            return True
        return any(
            marker in text
            for marker in (
                "justia.com",
                "findlaw.com",
                "law.cornell.edu",
                "open-us-law-bucket",
                "huggingface.co",
                "unicourt",
            )
        )

    def _looks_contaminated(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(text or "")).strip().lower()
        if not lowered:
            return False
        return any(marker in lowered for marker in self.NAVIGATION_FOOTER_MARKERS)

    def _official_clean_text(self, chapter_number: str, name: str, source_url: str) -> str:
        return (
            f"North Carolina General Statutes Chapter {chapter_number} ({name}) official "
            f"clean statutory catalog unit at {source_url}"
        )

    def _recover_chapter_number(self, *parts: object) -> str:
        blob = " ".join(str(item or "") for item in parts)
        path_match = self._NC_CHAPTER_PATH_RE.search(blob) or self._NC_CHAPTER_BYCHAPTER_RE.search(
            blob
        )
        if path_match:
            return path_match.group(1)
        label_match = self._NC_CHAPTER_LABEL_RE.search(blob)
        if label_match:
            return label_match.group(1)
        return ""

    def replace_contaminated_bucket_object(
        self,
        seeds: object,
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Replace the absent contaminated NC bucket object with official clean text.

        Recoverable chapter numbers are rewritten to official ncleg.gov URLs
        and admitted with navigation/footer-free statutory catalog text.
        Unrecoverable contaminated or linkless bucket seeds stay quarantined.
        """

        replaced: List[Dict[str, Any]] = []
        quarantines: List[Dict[str, Any]] = []
        seen_chapters: set[str] = set()
        seen_quarantine: set[str] = set()
        known = {number for number, _name in self.OFFICIAL_CHAPTERS}
        names = dict(self.OFFICIAL_CHAPTERS)

        def _record(chapter_number: str, label: str, source: str, source_url: str = "") -> None:
            number = str(chapter_number or "").strip()
            if not number or number not in known or number in seen_chapters:
                return
            seen_chapters.add(number)
            official_url = (
                source_url
                if source_url and self.is_official_nc_url(source_url)
                else self.official_chapter_url(number)
            )
            name = names.get(number, f"Chapter {number}")
            replaced.append(
                {
                    "canonical_key": f"nc:chapter-{number.lower()}",
                    "chapter_number": number,
                    "name": name,
                    "source_url": official_url,
                    "source_link_disposition": source,
                    "repair_source": source,
                    "contaminated_replaced": True,
                    "text": self._official_clean_text(number, name, official_url),
                }
            )

        def _quarantine(label: str, evidence: str, unit_id: str = "") -> None:
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
            if not cleaned:
                return
            key = unit_id or (
                "nc:bucket-" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            )
            if key in seen_quarantine:
                return
            seen_quarantine.add(key)
            quarantines.append(
                {
                    "unit_id": key,
                    "reason": self.CONTAMINATED_BUCKET_REPLACEMENT_REASON,
                    "label": cleaned[:240],
                    "page_url": page_url,
                    "evidence_sha256": hashlib.sha256(
                        str(evidence or cleaned).encode("utf-8")
                    ).hexdigest(),
                }
            )

        if isinstance(seeds, (bytes, bytearray, str)):
            html = seeds.decode("utf-8", errors="replace") if isinstance(seeds, (bytes, bytearray)) else seeds
            try:
                from bs4 import BeautifulSoup
            except ImportError as exc:
                raise RuntimeError(
                    "BeautifulSoup is required for official North Carolina discovery"
                ) from exc
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
                absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
                chapter_number = self._recover_chapter_number(absolute, href, label)
                if chapter_number and self.is_official_nc_url(absolute):
                    _record(
                        chapter_number,
                        label,
                        "official",
                        self.official_chapter_url(chapter_number),
                    )
                    continue
                if chapter_number:
                    _record(chapter_number, label, "official_replacement")
                    continue
                if label and (
                    self._looks_like_bucket_seed_url(absolute) or self._looks_contaminated(label)
                ):
                    _quarantine(label, str(link))
            for node in soup.find_all(["span", "td", "li", "div", "nav", "footer"]):
                if node.find("a", href=True):
                    continue
                label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
                if not label:
                    continue
                chapter_number = self._recover_chapter_number(
                    node.get("data-chapter"),
                    node.get("id"),
                    label,
                    str(node),
                )
                if chapter_number:
                    _record(chapter_number, label, "official_replacement")
                    continue
                if re.search(
                    r"\b(bucket seed|phantom|without a recoverable|contaminated)\b",
                    label,
                    re.IGNORECASE,
                ) or self._looks_contaminated(label):
                    _quarantine(label, str(node))
            return {"replaced": replaced, "quarantines": quarantines}

        items: Sequence[Any] = seeds or ()
        for item in items:
            if not isinstance(item, Mapping):
                continue
            label = str(
                item.get("label")
                or item.get("name")
                or item.get("text")
                or item.get("section_name")
                or ""
            ).strip()
            source_url = str(item.get("source_url") or item.get("href") or "").strip()
            chapter_number = self._recover_chapter_number(
                item.get("chapter_number"),
                item.get("section_number"),
                source_url,
                label,
            )
            if chapter_number and source_url and self.is_official_nc_url(source_url):
                _record(chapter_number, label, "official", source_url)
                continue
            if chapter_number:
                _record(chapter_number, label, "official_replacement")
                continue
            _quarantine(
                label or source_url or "north carolina contaminated bucket seed",
                json.dumps(dict(item), sort_keys=True),
                unit_id=str(item.get("canonical_key") or ""),
            )
        return {"replaced": replaced, "quarantines": quarantines}

    def _official_http_get(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(2, min(int(timeout_seconds or 8), 8))
        headers = {
            "User-Agent": "ipfs-datasets-north-carolina-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        try:
            request = urllib.request.Request(url, headers=headers)
            context = ssl.create_default_context()
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                if int(getattr(response, "status", 200) or 200) != 200:
                    return b""
                return bytes(response.read() or b"")
        except Exception:
            return b""

    def _parse_official_chapter_links(self, html: bytes, page_url: str = "") -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {number for number, _name in self.OFFICIAL_CHAPTERS}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            number = self._recover_chapter_number(
                absolute, href, link.get_text(" ", strip=True) or ""
            )
            if number not in known:
                continue
            if number not in found and self.is_official_nc_url(absolute):
                found[number] = self.official_chapter_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate official NC chapters and replace contaminated bucket seeds."""

        discovered = self._parse_official_chapter_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        classified = self.replace_contaminated_bucket_object(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        seed_classified = self.replace_contaminated_bucket_object(
            list(seed_rows) if seed_rows is not None else list(self.DEFAULT_CONTAMINATED_BUCKET_SEEDS),
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        classified["replaced"].extend(seed_classified["replaced"])
        classified["quarantines"].extend(seed_classified["quarantines"])
        self.last_official_replacements = list(classified["replaced"])
        self.last_official_quarantines = list(classified["quarantines"])

        rows = self.official_chapter_catalog()
        by_chapter = {str(row["chapter_number"]): row for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["chapter_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_ncleg"
            row["text"] = self._official_clean_text(
                str(row["chapter_number"]), str(row["name"]), str(row["source_url"])
            )
            row["contaminated_replaced"] = True
        for unit in classified["replaced"]:
            number = str(unit.get("chapter_number") or "")
            if number not in by_chapter:
                continue
            if unit.get("source_link_disposition") in {"official", "official_replacement"}:
                by_chapter[number]["source_url"] = unit["source_url"]
                by_chapter[number]["text"] = unit["text"]
                if unit.get("source_link_disposition") == "official":
                    by_chapter[number]["source_link_disposition"] = "official"
                elif by_chapter[number]["source_link_disposition"] != "official":
                    by_chapter[number]["source_link_disposition"] = "official_replacement"
        return rows

    def fetch_official(self, code: str = "NC"):
        """Acquire the exhaustive official North Carolina General Statutes catalog.

        The withdrawn v2026.07 contaminated NC bucket object is replaced from
        official clean statutory catalog text. Navigation and footer markers
        are never admitted. This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "NC").strip().upper() or "NC"
        if normalized != "NC":
            raise ValueError(f"NorthCarolinaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_TOC_URL) or self._official_http_get(
            self.OFFICIAL_ENTRY_URL
        )
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        quarantines = list(getattr(self, "last_official_quarantines", []) or [])
        replacements = list(getattr(self, "last_official_replacements", []) or [])
        if len(rows) != self.OFFICIAL_CHAPTER_COUNT:
            raise RuntimeError("north carolina official catalog enumeration is incomplete")
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "contaminated_bucket_replaced": True,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "quarantines": quarantines,
            "replacement_source": "official_clean_text",
            "replacements": replacements,
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
            "nc_contaminated_bucket_quarantines": quarantines,
            "nc_contaminated_bucket_replaced": True,
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
StateScraperRegistry.register("NC", NorthCarolinaScraper)
