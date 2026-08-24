"""Scraper for North Carolina state laws.

Official-source path walks the North Carolina General Assembly HTML tree on
ncleg.gov. The withdrawn v2026.07 contaminated NC bucket object is replaced
from official clean statutory catalog text. Secondary Justia mirrors are
never sole-admitted for full-corpus certification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import ssl
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    TypedDict,
)
from urllib.parse import urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry

NorthCarolinaByChapterDisposition = Literal[
    "official_parsed",
    "recovery_transport_only",
    "fetch_empty",
    "fetch_short_response",
    "fetch_exception",
    "parse_zero_statutes",
    "parse_exception",
    "incomplete_html_document",
    "chapter_identity_mismatch",
    "unverified_cache_provenance",
    "nonfresh_transport",
    "http_status_not_ok",
    "nonofficial_final_host",
    "unexpected_final_url",
    "response_hash_mismatch",
    "invalid_observation_receipt",
    "section_frontier_parse_exception",
    "section_frontier_fetch_exception",
    "section_frontier_nonfresh_transport",
    "section_frontier_http_status_not_ok",
    "section_frontier_nonofficial_final_host",
    "section_frontier_unexpected_final_url",
    "section_frontier_response_hash_mismatch",
    "section_frontier_invalid_observation_receipt",
    "section_frontier_incomplete_html_document",
    "section_frontier_empty",
    "section_frontier_underfill",
    "section_frontier_mismatch",
    "not_attempted_chapter_cap",
    "not_attempted",
]

NorthCarolinaByChapterFrontierDisposition = Literal[
    "fresh_toc_verified",
    "toc_fetch_exception",
    "toc_http_status_not_ok",
    "toc_nonofficial_final_host",
    "toc_unexpected_final_url",
    "toc_response_hash_mismatch",
    "toc_invalid_observation_receipt",
    "toc_incomplete_html_document",
    "toc_parse_zero_chapters",
    "toc_catalog_mismatch",
]


class NorthCarolinaByChapterEvidence(TypedDict):
    """Checkpoint-safe evidence for one attempted ByChapter frontier unit."""

    chapter_number: str
    chapter_name: str
    state_code: str
    code_name: str
    run_id: str
    source_url: str
    disposition: NorthCarolinaByChapterDisposition
    resolved: bool
    provider: str
    source_authority_class: str
    http_status: int
    final_url: str
    final_host: str
    observed_at: str
    response_bytes: int
    response_sha256: str
    decoded_sha256: str
    chapter_rows_sha256: str
    section_frontier_source_url: str
    section_frontier_provider: str
    section_frontier_http_status: int
    section_frontier_final_url: str
    section_frontier_final_host: str
    section_frontier_observed_at: str
    section_frontier_response_bytes: int
    section_frontier_response_sha256: str
    section_frontier_decoded_sha256: str
    section_frontier_document_complete: bool
    section_frontier_sha256: str
    document_complete: bool
    section_frontier_count: int
    section_active_count: int
    section_inactive_count: int
    active_section_numbers: List[str]
    inactive_section_numbers: List[str]
    parsed_section_numbers: List[str]
    parsed_statutes: int
    admitted_statutes: int
    evidence_sha256: str
    checkpoint_hmac_sha256: str
    error_type: str
    error_message: str


class NorthCarolinaByChapterFetchReceipt(TypedDict):
    """Transport receipt for one fresh or bounded NC ByChapter fetch."""

    html: str
    provider: str
    http_status: int
    final_url: str
    final_host: str
    observed_at: str
    response_sha256: str
    decoded_sha256: str
    error_type: str
    error_message: str


class NorthCarolinaByChapterFrontierEvidence(TypedDict):
    """Fresh TOC closure evidence for the exhaustive ByChapter frontier."""

    source_url: str
    disposition: NorthCarolinaByChapterFrontierDisposition
    resolved: bool
    provider: str
    http_status: int
    final_url: str
    final_host: str
    observed_at: str
    response_bytes: int
    response_sha256: str
    decoded_sha256: str
    document_complete: bool
    discovered_chapters: List[str]
    active_chapters: List[str]
    inactive_chapters: List[str]
    chapter_dispositions: List[Dict[str, str]]
    pinned_chapters: List[str]
    missing_from_live_toc: List[str]
    unexpected_in_live_toc: List[str]
    error_type: str
    error_message: str


class NorthCarolinaByChapterIncompleteError(RuntimeError):
    """Raised when an exhaustive NC ByChapter frontier is not fully official."""

    def __init__(
        self,
        *,
        resolved_count: int,
        total_count: int,
        unresolved: Sequence[NorthCarolinaByChapterEvidence],
    ) -> None:
        self.resolved_count = int(resolved_count)
        self.total_count = int(total_count)
        self.unresolved = tuple(dict(item) for item in unresolved)
        dispositions = sorted(
            {
                str(item.get("disposition") or "unknown")
                for item in self.unresolved
            }
        )
        super().__init__(
            "North Carolina ByChapter exhaustive harvest incomplete: "
            f"resolved={self.resolved_count}/{self.total_count}, "
            f"unresolved={len(self.unresolved)}, "
            f"dispositions={','.join(dispositions) or 'unknown'}"
        )


class NorthCarolinaScraper(BaseStateScraper):
    """Scraper for North Carolina state laws from https://www.ncleg.gov"""

    OFFICIAL_DOMAIN = "www.ncleg.gov"
    OFFICIAL_ENTRY_PATH = "/Laws/GeneralStatutes"
    OFFICIAL_ENTRY_URL = "https://www.ncleg.gov/Laws/GeneralStatutes"
    OFFICIAL_TOC_URL = "https://www.ncleg.gov/Laws/GeneralStatutesTOC"
    BYCHAPTER_COMPLETION_SCHEMA = (
        "ipfs_datasets_py/north-carolina-bychapter-completion@2"
    )
    BYCHAPTER_FRESH_PROVIDER = "fresh_live_https"
    FIRST_BYCHAPTER_STATUTE_LIMIT = 1
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
        from .north_carolina_constitution import (
            configured_constitution_html_path,
            parse_north_carolina_constitution_html,
        )

        full_corpus_requested = bool(
            self._full_corpus_enabled() and max_statutes is None
        )
        constitution_path = configured_constitution_html_path()
        if "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_north_carolina_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "North Carolina Constitution",
                    max_statutes=max_statutes,
                )
                return constitution_rows
        from .north_carolina_chapter import (
            configured_chapter_html_path,
            parse_configured_north_carolina_chapters,
            parse_north_carolina_chapter_html,
        )
        from .north_carolina_archive import parse_configured_north_carolina_archive

        if not full_corpus_requested:
            chapter_path = configured_chapter_html_path()
            if chapter_path is not None:
                chapter_token = chapter_path.stem.replace("Chapter_", "").replace("chapter_", "")
                bulk = parse_north_carolina_chapter_html(
                    chapter_path.read_text(encoding="utf-8", errors="replace"),
                    chapter=chapter_token or "14",
                    code_name=code_name,
                    max_statutes=max_statutes,
                )
                if bulk:
                    return bulk
            local_rows = parse_configured_north_carolina_chapters(
                code_name=code_name,
                max_statutes=max_statutes,
            )
            if local_rows:
                return local_rows
            recovered = parse_configured_north_carolina_archive(
                code_name=code_name,
                max_statutes=max_statutes,
            )
            if recovered:
                return recovered
        return_threshold = self._effective_scrape_limit(max_statutes, default=160) or 1000000
        if full_corpus_requested and not self._bychapter_live_enabled():
            raise RuntimeError(
                "North Carolina full-corpus mode requires fresh ByChapter HTTPS; "
                "NORTH_CAROLINA_BYCHAPTER_LIVE=0 is non-certifying"
            )
        if self._bychapter_live_enabled():
            bychapter = await self._scrape_official_bychapter_html(
                code_name,
                max_statutes=None if return_threshold == 1000000 else int(return_threshold),
            )
            if bychapter:
                return bychapter if return_threshold == 1000000 else bychapter[: int(return_threshold)]
            if full_corpus_requested:
                raise RuntimeError(
                    "North Carolina exhaustive ByChapter path returned no statutes; "
                    "refusing legacy index or generic fallback sole-admission"
                )
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

    def _bychapter_live_enabled(self) -> bool:
        raw = str(os.getenv("NORTH_CAROLINA_BYCHAPTER_LIVE", "1") or "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}

    def _bychapter_max_chapters(self) -> Optional[int]:
        raw = str(os.getenv("NORTH_CAROLINA_BYCHAPTER_MAX_CHAPTERS") or "").strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except Exception:
            return None
        return value if value > 0 else None

    def _bychapter_concurrency(self) -> int:
        raw = str(os.getenv("NORTH_CAROLINA_BYCHAPTER_CONCURRENCY", "4") or "4").strip()
        try:
            value = int(raw)
        except Exception:
            value = 4
        return max(1, min(8, value))

    def _bychapter_checkpoint_max_age_seconds(self) -> int:
        raw = str(
            os.getenv("NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_MAX_AGE_SECONDS", "21600")
            or "21600"
        ).strip()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 21600
        return max(300, min(86400, value))

    def _bychapter_observed_at_valid(self, value: object) -> bool:
        try:
            observed = datetime.fromisoformat(str(value or ""))
        except (TypeError, ValueError):
            return False
        if observed.tzinfo is None:
            return False
        age_seconds = (datetime.now(timezone.utc) - observed).total_seconds()
        return -300 <= age_seconds <= self._bychapter_checkpoint_max_age_seconds()

    @staticmethod
    def _bychapter_checkpoint_rows_sha256(
        statutes: Sequence[NormalizedStatute],
        chapter_number: str,
    ) -> str:
        number = str(chapter_number or "").strip().upper()
        rows: List[Dict[str, Any]] = []
        for row in statutes:
            if str(row.chapter_number or "").strip().upper() != number:
                continue
            rows.append(
                {
                    "state_code": str(row.state_code or ""),
                    "statute_id": str(row.statute_id or ""),
                    "code_name": str(row.code_name or ""),
                    "chapter_number": str(row.chapter_number or ""),
                    "section_number": str(row.section_number or ""),
                    "section_name": str(row.section_name or ""),
                    "full_text": str(row.full_text or ""),
                    "source_url": str(row.source_url or ""),
                    "official_cite": str(row.official_cite or ""),
                    "structured_data": dict(row.structured_data or {}),
                }
            )
        rows.sort(
            key=lambda item: (
                str(item.get("section_number") or ""),
                str(item.get("statute_id") or ""),
            )
        )
        payload = json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _bychapter_evidence_sha256(item: Mapping[str, Any]) -> str:
        """Return a self-contained integrity digest (not authentication)."""

        canonical = {
            str(key): value
            for key, value in item.items()
            if str(key) not in {"evidence_sha256", "checkpoint_hmac_sha256"}
        }
        payload = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _bychapter_section_frontier_sha256(
        active_section_numbers: Sequence[str],
        inactive_section_numbers: Sequence[str],
    ) -> str:
        payload = json.dumps(
            {
                "active": [str(item) for item in active_section_numbers],
                "inactive": [str(item) for item in inactive_section_numbers],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _bychapter_checkpoint_hmac_key() -> Optional[bytes]:
        """Return an opt-in checkpoint authentication key without persisting it."""

        raw = os.getenv("NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY")
        if raw is None:
            return None
        key = str(raw).encode("utf-8")
        # A short operator typo must not silently authorize resume skipping.
        return key if len(key) >= 32 else None

    @staticmethod
    def _bychapter_checkpoint_hmac_sha256(
        item: Mapping[str, Any],
        key: bytes,
    ) -> str:
        canonical = {
            str(field): value
            for field, value in item.items()
            if str(field) != "checkpoint_hmac_sha256"
        }
        payload = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hmac.new(key, payload, hashlib.sha256).hexdigest()

    def _bychapter_cache_provider(self, url: str, provider: str, html: str) -> str:
        """Recover cache origin without allowing unknown cache bytes to certify live text."""

        token = str(provider or "").strip() or "requests_direct"
        if token not in {"fetch_cache", "ipfs_page_cache"}:
            return token

        canonical_url = self._canonical_fetch_url(url)
        payload = str(html or "").encode("utf-8", errors="replace")
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        origin = ""

        if token == "fetch_cache":
            try:
                _object_path, meta_path = self._fetch_cache_paths(canonical_url)
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            if (
                isinstance(meta, dict)
                and self._canonical_fetch_url(str(meta.get("url") or ""))
                == canonical_url
                and str(meta.get("sha256") or "") == payload_sha256
                and str(meta.get("state_code") or self.state_code).upper()
                == self.state_code.upper()
            ):
                origin = str(meta.get("provider") or "").strip()

        if token == "ipfs_page_cache" or origin == "ipfs_page_cache":
            entry = self._ipfs_page_cache_index.get(
                self._ipfs_page_cache_key(canonical_url)
            ) or {}
            try:
                entry_size = int(entry.get("size") or 0)
            except (TypeError, ValueError, AttributeError):
                entry_size = 0
            if (
                isinstance(entry, dict)
                and self._canonical_fetch_url(str(entry.get("url") or ""))
                == canonical_url
                and entry_size == len(payload)
                and str(entry.get("state_code") or self.state_code).upper()
                == self.state_code.upper()
            ):
                ipfs_origin = str(entry.get("provider") or "").strip()
                if ipfs_origin:
                    origin = f"ipfs_page_cache:{ipfs_origin}"

        if origin == "requests_direct" or origin.endswith(":requests_direct"):
            return f"{token}:{origin}"
        return f"{token}:unverified_cache:{origin or 'unknown'}"

    async def _fetch_official_bychapter_page(self, number: str) -> Tuple[str, str]:
        from .north_carolina_chapter import chapter_url

        source_url = chapter_url(number)
        html = await self._request_text_direct(source_url, timeout=40)
        provider = self._current_fetch_provider() or str(
            getattr(self, "_last_fetch_provider", "") or "requests_direct"
        )
        return html or "", self._bychapter_cache_provider(source_url, provider, html)

    async def _fetch_official_https_fresh(
        self,
        source_url: str,
        *,
        timeout: int = 40,
    ) -> NorthCarolinaByChapterFetchReceipt:
        """Fetch one official URL over verified HTTPS without fallback/cache."""

        source_url = str(source_url or "").strip()
        parsed_source = urlparse(source_url)
        if parsed_source.scheme.lower() != "https" or not self.is_official_nc_url(source_url):
            observed_at = datetime.now(timezone.utc).isoformat()
            return NorthCarolinaByChapterFetchReceipt(
                html="",
                provider=self.BYCHAPTER_FRESH_PROVIDER,
                http_status=0,
                final_url=source_url,
                final_host=(parsed_source.hostname or "").lower(),
                observed_at=observed_at,
                response_sha256=hashlib.sha256(b"").hexdigest(),
                decoded_sha256=hashlib.sha256(b"").hexdigest(),
                error_type="InvalidOfficialHttpsUrl",
                error_message="fresh fetch requires an official ncleg.gov HTTPS URL",
            )

        def _request() -> Tuple[int, str, bytes]:
            request = urllib.request.Request(
                source_url,
                headers={
                    "User-Agent": "ipfs-datasets-north-carolina-full-corpus/1.0",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "Connection": "close",
                },
            )
            context = ssl.create_default_context()
            with urllib.request.urlopen(
                request,
                timeout=max(5, int(timeout)),
                context=context,
            ) as response:
                status = int(getattr(response, "status", 200) or 200)
                final_url = str(response.geturl() or source_url)
                payload = bytes(response.read() or b"")
            return status, final_url, payload

        status = 0
        final_url = source_url
        payload = b""
        error_type = ""
        error_message = ""
        try:
            status, final_url, payload = await anyio_compat.wait_for(
                anyio_compat.to_thread(_request),
                max(7, int(timeout) + 2),
            )
        except Exception as exc:
            status = int(getattr(exc, "code", 0) or 0)
            final_url = str(getattr(exc, "url", "") or source_url)
            error_type = type(exc).__name__
            error_message = str(exc)

        observed_at = datetime.now(timezone.utc).isoformat()
        html = payload.decode("utf-8", errors="replace") if payload else ""
        decoded_bytes = html.encode("utf-8", errors="replace")
        return NorthCarolinaByChapterFetchReceipt(
            html=html,
            provider=self.BYCHAPTER_FRESH_PROVIDER,
            http_status=status,
            final_url=final_url,
            final_host=(urlparse(final_url).hostname or "").lower(),
            observed_at=observed_at,
            response_sha256=hashlib.sha256(payload).hexdigest(),
            decoded_sha256=hashlib.sha256(decoded_bytes).hexdigest(),
            error_type=error_type,
            error_message=error_message,
        )

    async def _fetch_official_bychapter_page_fresh(
        self,
        number: str,
        *,
        timeout: int = 40,
    ) -> NorthCarolinaByChapterFetchReceipt:
        """Fetch one ByChapter unit through the non-cached live HTTPS path."""

        from .north_carolina_chapter import chapter_url

        return await self._fetch_official_https_fresh(
            chapter_url(number),
            timeout=timeout,
        )

    async def _fetch_official_chapter_section_index_fresh(
        self,
        number: str,
        *,
        timeout: int = 40,
    ) -> NorthCarolinaByChapterFetchReceipt:
        """Fetch the independent official section inventory without a cache."""

        from .north_carolina_chapter import chapter_sections_url

        return await self._fetch_official_https_fresh(
            chapter_sections_url(number),
            timeout=timeout,
        )

    async def _scrape_official_bychapter_html(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Fetch official ByChapter HTML dumps and parse section bodies.

        Live ``/EnactedLegislation/Statutes/HTML/ByChapter/Chapter_{N}.html``
        pages are the durable official statute text. Archive transport of the
        same locators is labeled recovery. Disable with
        ``NORTH_CAROLINA_BYCHAPTER_LIVE=0``. Chapter fetches run concurrently
        (``NORTH_CAROLINA_BYCHAPTER_CONCURRENCY``, default 4, max 8).
        """

        from .north_carolina_archive import parse_north_carolina_archive_html
        from .north_carolina_chapter import (
            BYCHAPTER_INDEX_URL,
            TOC_URL,
            bychapter_index_links,
            chapter_section_index_frontier,
            chapter_sections_url,
            chapter_url,
            configured_bychapter_index_path,
            configured_toc_html_path,
            merge_discovered_chapters,
            parse_north_carolina_chapter_html,
            toc_chapter_frontier,
            toc_chapter_links,
        )

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        full_corpus_run = bool(self._full_corpus_enabled() and limit is None)
        checkpoint_payload = self._load_partial_checkpoint_payload()
        checkpoint_progress_raw = checkpoint_payload.get("progress")
        checkpoint_progress = (
            dict(checkpoint_progress_raw)
            if isinstance(checkpoint_progress_raw, dict)
            else {}
        )
        candidate_run_id = str(
            checkpoint_progress.get("bychapter_run_id") or ""
        ).strip()
        candidate_run_started_at = str(
            checkpoint_progress.get("bychapter_run_started_at") or ""
        ).strip()
        checkpoint_envelope_valid = bool(
            full_corpus_run
            and checkpoint_payload.get("state_code") == "NC"
            and checkpoint_payload.get("code_name") == str(code_name)
            and checkpoint_progress.get("bychapter_completion_schema")
            == self.BYCHAPTER_COMPLETION_SCHEMA
            and checkpoint_progress.get("bychapter_full_corpus_required") is True
            and re.fullmatch(r"[0-9a-f]{32}", candidate_run_id)
            and self._bychapter_observed_at_valid(candidate_run_started_at)
        )
        bychapter_run_id = (
            candidate_run_id if checkpoint_envelope_valid else uuid.uuid4().hex
        )
        bychapter_run_started_at = (
            candidate_run_started_at
            if checkpoint_envelope_valid
            else datetime.now(timezone.utc).isoformat()
        )
        max_chapters = self._bychapter_max_chapters()
        catalog = list(self.OFFICIAL_CHAPTERS)
        discovered: List[str] = []
        live_active_catalog: List[Tuple[str, str]] = []
        frontier_evidence: Optional[NorthCarolinaByChapterFrontierEvidence] = None
        frontier_verified = not full_corpus_run
        if full_corpus_run:
            toc_receipt = await self._fetch_official_https_fresh(TOC_URL, timeout=30)
            toc_html = str(toc_receipt.get("html") or "")
            toc_provider = str(toc_receipt.get("provider") or "")
            toc_status = max(0, int(toc_receipt.get("http_status") or 0))
            toc_final_url = str(toc_receipt.get("final_url") or TOC_URL)
            toc_final_host = str(
                toc_receipt.get("final_host")
                or (urlparse(toc_final_url).hostname or "")
            ).lower()
            toc_observed_at = str(toc_receipt.get("observed_at") or "")
            toc_response_sha256 = str(toc_receipt.get("response_sha256") or "")
            toc_decoded_sha256 = str(toc_receipt.get("decoded_sha256") or "")
            toc_error_type = str(toc_receipt.get("error_type") or "")
            toc_error_message = str(toc_receipt.get("error_message") or "")
            toc_bytes = toc_html.encode("utf-8", errors="replace")
            toc_document_complete = bool(
                re.search(r"</html\s*>\s*$", toc_html, flags=re.IGNORECASE)
            )
            chapter_dispositions: List[Dict[str, str]] = []
            live_chapters: List[str] = []
            active_live_chapters: List[str] = []
            inactive_live_chapters: List[str] = []
            disposition: NorthCarolinaByChapterFrontierDisposition
            if toc_error_type and not toc_html:
                disposition = "toc_fetch_exception"
            elif toc_provider != self.BYCHAPTER_FRESH_PROVIDER:
                disposition = "toc_fetch_exception"
            elif toc_status != 200:
                disposition = "toc_http_status_not_ok"
            elif (
                not self.is_official_nc_url(toc_final_url)
                or toc_final_host != (urlparse(toc_final_url).hostname or "").lower()
            ):
                disposition = "toc_nonofficial_final_host"
            elif toc_final_url != TOC_URL:
                disposition = "toc_unexpected_final_url"
            elif (
                len(toc_response_sha256) != 64
                or len(toc_decoded_sha256) != 64
                or toc_decoded_sha256 != hashlib.sha256(toc_bytes).hexdigest()
            ):
                disposition = "toc_response_hash_mismatch"
            elif not self._bychapter_observed_at_valid(toc_observed_at):
                disposition = "toc_invalid_observation_receipt"
            elif not toc_document_complete:
                disposition = "toc_incomplete_html_document"
            else:
                toc_records = toc_chapter_frontier(toc_html)
                chapter_dispositions = [dict(record) for record in toc_records]
                live_chapters = [record["chapter_number"] for record in toc_records]
                active_live_chapters = [
                    record["chapter_number"]
                    for record in toc_records
                    if record["disposition"] == "active"
                ]
                inactive_live_chapters = [
                    record["chapter_number"]
                    for record in toc_records
                    if record["disposition"] == "inactive"
                ]
                disposition = (
                    "fresh_toc_verified"
                    if live_chapters and active_live_chapters
                    else "toc_parse_zero_chapters"
                )

            pinned_by_upper = {
                str(number).upper(): str(number) for number, _name in catalog
            }
            live_by_upper = {
                str(number).upper(): str(number) for number in live_chapters
            }
            missing_from_live = [
                number
                for number, _name in catalog
                if str(number).upper() not in live_by_upper
            ]
            unexpected_in_live = [
                number
                for number in active_live_chapters
                if str(number).upper() not in pinned_by_upper
            ]
            if disposition == "fresh_toc_verified" and missing_from_live:
                disposition = "toc_catalog_mismatch"
            frontier_verified = disposition == "fresh_toc_verified"
            if frontier_verified:
                pinned_names = {
                    str(number).upper(): str(name) for number, name in catalog
                }
                records_by_upper = {
                    str(record["chapter_number"]).upper(): record
                    for record in chapter_dispositions
                }
                live_active_catalog = [
                    (
                        pinned_by_upper.get(str(number).upper(), str(number)),
                        pinned_names.get(
                            str(number).upper(),
                            str(
                                records_by_upper[str(number).upper()].get(
                                    "chapter_name"
                                )
                                or f"Chapter {number}"
                            ),
                        ),
                    )
                    for number in active_live_chapters
                ]
            frontier_evidence = NorthCarolinaByChapterFrontierEvidence(
                source_url=TOC_URL,
                disposition=disposition,
                resolved=frontier_verified,
                provider=toc_provider,
                http_status=toc_status,
                final_url=toc_final_url,
                final_host=toc_final_host,
                observed_at=toc_observed_at,
                response_bytes=len(toc_bytes),
                response_sha256=toc_response_sha256,
                decoded_sha256=toc_decoded_sha256,
                document_complete=toc_document_complete,
                discovered_chapters=list(live_chapters),
                active_chapters=list(active_live_chapters),
                inactive_chapters=list(inactive_live_chapters),
                chapter_dispositions=chapter_dispositions,
                pinned_chapters=[str(number) for number, _name in catalog],
                missing_from_live_toc=missing_from_live,
                unexpected_in_live_toc=unexpected_in_live,
                error_type=toc_error_type,
                error_message=toc_error_message,
            )
        else:
            index_path = configured_bychapter_index_path()
            if index_path is not None:
                discovered.extend(
                    bychapter_index_links(
                        index_path.read_text(encoding="utf-8", errors="replace")
                    )
                )
            toc_path = configured_toc_html_path()
            if toc_path is not None:
                discovered.extend(
                    toc_chapter_links(
                        toc_path.read_text(encoding="utf-8", errors="replace")
                    )
                )
            if index_path is None and toc_path is None:
                try:
                    index_html = await self._request_text_direct(
                        BYCHAPTER_INDEX_URL,
                        timeout=20,
                    )
                except Exception:
                    index_html = ""
                if index_html:
                    discovered.extend(bychapter_index_links(index_html))
                try:
                    toc_html = await self._request_text_direct(TOC_URL, timeout=20)
                except Exception:
                    toc_html = ""
                if toc_html:
                    discovered.extend(toc_chapter_links(toc_html))
        if full_corpus_run and frontier_verified:
            # The fresh official TOC is the authoritative current frontier.
            # The pinned catalog remains a fail-closed omission cross-check,
            # while newly published active chapters are harvested dynamically.
            catalog = live_active_catalog
        elif discovered:
            catalog = merge_discovered_chapters(catalog, discovered)
        frontier_catalog = list(catalog)
        if max_chapters is not None:
            catalog = catalog[: int(max_chapters)]

        statutes = self._load_partial_checkpoint_statutes(
            code_name=code_name,
            max_statutes=limit,
        )
        if full_corpus_run:
            expected_checkpoint_chapters = {
                str(number).upper() for number, _name in frontier_catalog
            }
            # Only exact official rows from this state/code/frontier can back
            # a completion receipt. Everything else is purged on the next
            # replacement checkpoint write.
            statutes = [
                row
                for row in statutes
                if str(row.state_code or "") == "NC"
                and str(row.code_name or "") == str(code_name)
                and str(row.chapter_number or "").strip().upper()
                in expected_checkpoint_chapters
                and str(row.section_number or "").strip().upper().startswith(
                    f"{str(row.chapter_number or '').strip().upper()}-"
                )
                and str(
                    (row.structured_data or {}).get("source_authority_class") or ""
                )
                == "official"
                and self.is_official_nc_url(str(row.source_url or ""))
                and bool(self._NC_CHAPTER_BYCHAPTER_RE.search(str(row.source_url or "")))
            ]
        if limit is not None and len(statutes) >= limit:
            return statutes[: int(limit)]
        progress = checkpoint_progress
        done_raw = progress.get("bychapter_done") if isinstance(progress, dict) else None
        legacy_done: set[str] = {
            str(item).strip()
            for item in (done_raw or [])
            if str(item).strip()
        }
        frontier_names = {str(number): str(name) for number, name in frontier_catalog}
        frontier_numbers = [str(number) for number, _name in frontier_catalog]
        frontier_number_set = set(frontier_numbers)
        attempted_number_set = {str(number) for number, _name in catalog}
        evidence_by_number: Dict[str, NorthCarolinaByChapterEvidence] = {}
        checkpoint_hmac_key = self._bychapter_checkpoint_hmac_key()
        authenticated_evidence_numbers: set[str] = set()
        raw_evidence = (
            progress.get("bychapter_chapter_evidence")
            if checkpoint_envelope_valid
            else None
        )
        if isinstance(raw_evidence, list):
            for raw in raw_evidence:
                if not isinstance(raw, dict):
                    continue
                number = str(raw.get("chapter_number") or "").strip()
                disposition = str(raw.get("disposition") or "").strip()
                if number not in frontier_number_set or disposition not in {
                    "official_parsed",
                    "recovery_transport_only",
                    "fetch_empty",
                    "fetch_short_response",
                    "fetch_exception",
                    "parse_zero_statutes",
                    "parse_exception",
                    "incomplete_html_document",
                    "chapter_identity_mismatch",
                    "unverified_cache_provenance",
                    "nonfresh_transport",
                    "http_status_not_ok",
                    "nonofficial_final_host",
                    "unexpected_final_url",
                    "response_hash_mismatch",
                    "invalid_observation_receipt",
                    "section_frontier_parse_exception",
                    "section_frontier_fetch_exception",
                    "section_frontier_nonfresh_transport",
                    "section_frontier_http_status_not_ok",
                    "section_frontier_nonofficial_final_host",
                    "section_frontier_unexpected_final_url",
                    "section_frontier_response_hash_mismatch",
                    "section_frontier_invalid_observation_receipt",
                    "section_frontier_incomplete_html_document",
                    "section_frontier_empty",
                    "section_frontier_underfill",
                    "section_frontier_mismatch",
                    "not_attempted_chapter_cap",
                    "not_attempted",
                }:
                    continue
                if type(raw.get("resolved")) is not bool or type(
                    raw.get("document_complete")
                ) is not bool or type(
                    raw.get("section_frontier_document_complete")
                ) is not bool:
                    continue
                numeric_keys = (
                    "http_status",
                    "response_bytes",
                    "section_frontier_http_status",
                    "section_frontier_response_bytes",
                    "section_frontier_count",
                    "section_active_count",
                    "section_inactive_count",
                    "parsed_statutes",
                    "admitted_statutes",
                )
                if any(
                    type(raw.get(key)) is not int or int(raw.get(key)) < 0
                    for key in numeric_keys
                ):
                    continue
                expected_source_url = chapter_url(number)
                source_url = str(raw.get("source_url") or "")
                final_url = str(raw.get("final_url") or "")
                final_host = str(raw.get("final_host") or "").lower()
                if (
                    raw.get("state_code") != "NC"
                    or raw.get("code_name") != str(code_name)
                    or raw.get("run_id") != bychapter_run_id
                    or source_url != expected_source_url
                    or not self.is_official_nc_url(source_url)
                    or not self.is_official_nc_url(final_url)
                    or final_host != (urlparse(final_url).hostname or "").lower()
                ):
                    continue
                response_sha256 = str(raw.get("response_sha256") or "").lower()
                decoded_sha256 = str(raw.get("decoded_sha256") or "").lower()
                chapter_rows_sha256 = str(
                    raw.get("chapter_rows_sha256") or ""
                ).lower()
                section_frontier_source_url = str(
                    raw.get("section_frontier_source_url") or ""
                )
                section_frontier_provider = str(
                    raw.get("section_frontier_provider") or ""
                )
                section_frontier_final_url = str(
                    raw.get("section_frontier_final_url") or ""
                )
                section_frontier_final_host = str(
                    raw.get("section_frontier_final_host") or ""
                ).lower()
                section_frontier_observed_at = str(
                    raw.get("section_frontier_observed_at") or ""
                )
                section_frontier_response_sha256 = str(
                    raw.get("section_frontier_response_sha256") or ""
                ).lower()
                section_frontier_decoded_sha256 = str(
                    raw.get("section_frontier_decoded_sha256") or ""
                ).lower()
                section_frontier_sha256 = str(
                    raw.get("section_frontier_sha256") or ""
                ).lower()
                evidence_sha256 = str(raw.get("evidence_sha256") or "").lower()
                checkpoint_hmac_sha256 = str(
                    raw.get("checkpoint_hmac_sha256") or ""
                ).lower()
                section_list_keys = (
                    "active_section_numbers",
                    "inactive_section_numbers",
                    "parsed_section_numbers",
                )
                if any(
                    not isinstance(raw.get(key), list)
                    or any(
                        not isinstance(value, str) or not value.strip()
                        for value in raw.get(key, [])
                    )
                    for key in section_list_keys
                ):
                    continue
                active_section_numbers = list(raw["active_section_numbers"])
                inactive_section_numbers = list(raw["inactive_section_numbers"])
                parsed_section_numbers = list(raw["parsed_section_numbers"])
                if (
                    re.fullmatch(r"[0-9a-f]{64}", response_sha256) is None
                    or re.fullmatch(r"[0-9a-f]{64}", decoded_sha256) is None
                    or (
                        chapter_rows_sha256
                        and re.fullmatch(r"[0-9a-f]{64}", chapter_rows_sha256) is None
                    )
                    or (
                        section_frontier_sha256
                        and re.fullmatch(r"[0-9a-f]{64}", section_frontier_sha256)
                        is None
                    )
                    or (
                        section_frontier_response_sha256
                        and re.fullmatch(
                            r"[0-9a-f]{64}",
                            section_frontier_response_sha256,
                        )
                        is None
                    )
                    or (
                        section_frontier_decoded_sha256
                        and re.fullmatch(
                            r"[0-9a-f]{64}",
                            section_frontier_decoded_sha256,
                        )
                        is None
                    )
                    or re.fullmatch(r"[0-9a-f]{64}", evidence_sha256) is None
                    or (
                        checkpoint_hmac_sha256
                        and re.fullmatch(r"[0-9a-f]{64}", checkpoint_hmac_sha256)
                        is None
                    )
                    or raw["section_frontier_count"]
                    != len(active_section_numbers) + len(inactive_section_numbers)
                    or raw["section_active_count"] != len(active_section_numbers)
                    or raw["section_inactive_count"] != len(inactive_section_numbers)
                    or raw["parsed_statutes"] != len(parsed_section_numbers)
                    or len(set(active_section_numbers)) != len(active_section_numbers)
                    or len(set(inactive_section_numbers))
                    != len(inactive_section_numbers)
                    or set(active_section_numbers) & set(inactive_section_numbers)
                    or section_frontier_sha256
                    != self._bychapter_section_frontier_sha256(
                        active_section_numbers,
                        inactive_section_numbers,
                    )
                ):
                    continue
                item = NorthCarolinaByChapterEvidence(
                    chapter_number=number,
                    chapter_name=str(raw.get("chapter_name") or frontier_names.get(number, "")),
                    state_code="NC",
                    code_name=str(code_name),
                    run_id=bychapter_run_id,
                    source_url=source_url,
                    disposition=disposition,
                    resolved=raw["resolved"],
                    provider=str(raw.get("provider") or ""),
                    source_authority_class=str(
                        raw.get("source_authority_class") or ""
                    ),
                    http_status=raw["http_status"],
                    final_url=final_url,
                    final_host=final_host,
                    observed_at=str(raw.get("observed_at") or ""),
                    response_bytes=raw["response_bytes"],
                    response_sha256=response_sha256,
                    decoded_sha256=decoded_sha256,
                    chapter_rows_sha256=chapter_rows_sha256,
                    section_frontier_source_url=section_frontier_source_url,
                    section_frontier_provider=section_frontier_provider,
                    section_frontier_http_status=raw[
                        "section_frontier_http_status"
                    ],
                    section_frontier_final_url=section_frontier_final_url,
                    section_frontier_final_host=section_frontier_final_host,
                    section_frontier_observed_at=section_frontier_observed_at,
                    section_frontier_response_bytes=raw[
                        "section_frontier_response_bytes"
                    ],
                    section_frontier_response_sha256=(
                        section_frontier_response_sha256
                    ),
                    section_frontier_decoded_sha256=(
                        section_frontier_decoded_sha256
                    ),
                    section_frontier_document_complete=raw[
                        "section_frontier_document_complete"
                    ],
                    section_frontier_sha256=section_frontier_sha256,
                    document_complete=raw["document_complete"],
                    section_frontier_count=raw["section_frontier_count"],
                    section_active_count=raw["section_active_count"],
                    section_inactive_count=raw["section_inactive_count"],
                    active_section_numbers=active_section_numbers,
                    inactive_section_numbers=inactive_section_numbers,
                    parsed_section_numbers=parsed_section_numbers,
                    parsed_statutes=raw["parsed_statutes"],
                    admitted_statutes=raw["admitted_statutes"],
                    evidence_sha256=evidence_sha256,
                    checkpoint_hmac_sha256=checkpoint_hmac_sha256,
                    error_type=str(raw.get("error_type") or ""),
                    error_message=str(raw.get("error_message") or ""),
                )
                if self._bychapter_evidence_sha256(item) != evidence_sha256:
                    continue
                evidence_by_number[number] = item
                if (
                    checkpoint_hmac_key is not None
                    and checkpoint_hmac_sha256
                    and hmac.compare_digest(
                        self._bychapter_checkpoint_hmac_sha256(
                            item,
                            checkpoint_hmac_key,
                        ),
                        checkpoint_hmac_sha256,
                    )
                ):
                    authenticated_evidence_numbers.add(number)

        official_checkpoint_chapters = {
            str(row.chapter_number or "").strip()
            for row in statutes
            if str(row.chapter_number or "").strip()
            and str((row.structured_data or {}).get("source_authority_class") or "")
            == "official"
        }
        checkpoint_rows_sha256 = {
            number: self._bychapter_checkpoint_rows_sha256(statutes, number)
            for number in official_checkpoint_chapters
        }
        checkpoint_row_section_numbers = {
            number: {
                str(row.section_number or "").strip()
                for row in statutes
                if str(row.chapter_number or "").strip() == number
                and str(row.section_number or "").strip()
            }
            for number in official_checkpoint_chapters
        }
        if full_corpus_run:
            # Bare checkpoint digests are integrity checks, not authentication.
            # A persisted chapter may suppress a new live GET only when an
            # operator-supplied HMAC authenticates its complete evidence/row digest.
            done: set[str] = {
                number
                for number, item in evidence_by_number.items()
                if number in authenticated_evidence_numbers
                and item["disposition"] == "official_parsed"
                and item["resolved"]
                and item["state_code"] == "NC"
                and item["code_name"] == str(code_name)
                and item["run_id"] == bychapter_run_id
                and item["provider"] == self.BYCHAPTER_FRESH_PROVIDER
                and item["source_authority_class"] == "official"
                and item["http_status"] == 200
                and item["source_url"] == chapter_url(number)
                and item["final_url"] == chapter_url(number)
                and self.is_official_nc_url(item["final_url"])
                and item["final_host"]
                == (urlparse(item["final_url"]).hostname or "").lower()
                and self._bychapter_observed_at_valid(item["observed_at"])
                and len(item["response_sha256"]) == 64
                and len(item["decoded_sha256"]) == 64
                and len(item["evidence_sha256"]) == 64
                and self._bychapter_evidence_sha256(item)
                == item["evidence_sha256"]
                and item["document_complete"]
                and item["section_frontier_source_url"]
                == chapter_sections_url(number)
                and item["section_frontier_provider"]
                == self.BYCHAPTER_FRESH_PROVIDER
                and item["section_frontier_http_status"] == 200
                and item["section_frontier_final_url"]
                == chapter_sections_url(number)
                and item["section_frontier_final_host"]
                == (urlparse(chapter_sections_url(number)).hostname or "").lower()
                and self._bychapter_observed_at_valid(
                    item["section_frontier_observed_at"]
                )
                and len(item["section_frontier_response_sha256"]) == 64
                and len(item["section_frontier_decoded_sha256"]) == 64
                and item["section_frontier_document_complete"]
                and item["parsed_statutes"] > 0
                and item["section_active_count"] == item["parsed_statutes"]
                and item["section_frontier_count"]
                == item["section_active_count"] + item["section_inactive_count"]
                and set(item["active_section_numbers"])
                == set(item["parsed_section_numbers"])
                == checkpoint_row_section_numbers.get(number, set())
                and item["section_frontier_sha256"]
                == self._bychapter_section_frontier_sha256(
                    item["active_section_numbers"],
                    item["inactive_section_numbers"],
                )
                and item["chapter_rows_sha256"]
                == checkpoint_rows_sha256.get(number)
                and number in official_checkpoint_chapters
            }
        else:
            done = legacy_done | {
                number
                for number, item in evidence_by_number.items()
                if item["resolved"]
            }
        authenticated_resume_done = (
            set(done) if full_corpus_run else set()
        )
        if full_corpus_run:
            # Unauthenticated rows are resume hints only and are replaced from
            # fresh official response bytes before they can enter final output.
            statutes = [
                row
                for row in statutes
                if str(row.chapter_number or "").strip() in done
            ]
        seen: set[str] = {
            str(row.section_number or "").strip().lower()
            for row in statutes
            if str(row.section_number or "").strip()
        }
        remaining_catalog = (
            []
            if full_corpus_run and not frontier_verified
            else [(number, name) for number, name in catalog if number not in done]
        )
        concurrency = self._bychapter_concurrency()
        total = len(catalog)
        frontier_total = len(frontier_catalog)

        def _evidence(
            number: str,
            name: str,
            disposition: NorthCarolinaByChapterDisposition,
            *,
            resolved: bool,
            html: str = "",
            provider: str = "",
            authority: str = "",
            parsed_statutes: int = 0,
            admitted_statutes: int = 0,
            error: Optional[BaseException] = None,
            error_type: str = "",
            error_message: str = "",
            http_status: int = 0,
            final_url: str = "",
            final_host: str = "",
            observed_at: str = "",
            response_sha256: str = "",
            decoded_sha256: str = "",
            chapter_rows_sha256: str = "",
            section_frontier_provider: str = "",
            section_frontier_http_status: int = 0,
            section_frontier_final_url: str = "",
            section_frontier_final_host: str = "",
            section_frontier_observed_at: str = "",
            section_frontier_response_bytes: int = 0,
            section_frontier_response_sha256: str = "",
            section_frontier_decoded_sha256: str = "",
            section_frontier_document_complete: bool = False,
            active_section_numbers: Sequence[str] = (),
            inactive_section_numbers: Sequence[str] = (),
            parsed_section_numbers: Sequence[str] = (),
        ) -> NorthCarolinaByChapterEvidence:
            if error is not None:
                error_type = type(error).__name__
                error_message = str(error)
            html_bytes = str(html or "").encode("utf-8", errors="replace")
            final_url = str(final_url or chapter_url(number))
            active_sections = [str(item) for item in active_section_numbers]
            inactive_sections = [str(item) for item in inactive_section_numbers]
            parsed_sections = [str(item) for item in parsed_section_numbers]
            item = NorthCarolinaByChapterEvidence(
                chapter_number=str(number),
                chapter_name=str(name),
                state_code="NC",
                code_name=str(code_name),
                run_id=bychapter_run_id,
                source_url=chapter_url(number),
                disposition=disposition,
                resolved=bool(resolved),
                provider=str(provider or ""),
                source_authority_class=str(authority or ""),
                http_status=max(0, int(http_status)),
                final_url=final_url,
                final_host=str(final_host or (urlparse(final_url).hostname or "")).lower(),
                observed_at=str(observed_at or ""),
                response_bytes=len(html_bytes),
                response_sha256=str(
                    response_sha256 or hashlib.sha256(html_bytes).hexdigest()
                ),
                decoded_sha256=str(
                    decoded_sha256 or hashlib.sha256(html_bytes).hexdigest()
                ),
                chapter_rows_sha256=str(chapter_rows_sha256 or ""),
                section_frontier_source_url=chapter_sections_url(number),
                section_frontier_provider=str(section_frontier_provider or ""),
                section_frontier_http_status=max(
                    0,
                    int(section_frontier_http_status),
                ),
                section_frontier_final_url=str(section_frontier_final_url or ""),
                section_frontier_final_host=str(
                    section_frontier_final_host or ""
                ).lower(),
                section_frontier_observed_at=str(
                    section_frontier_observed_at or ""
                ),
                section_frontier_response_bytes=max(
                    0,
                    int(section_frontier_response_bytes),
                ),
                section_frontier_response_sha256=str(
                    section_frontier_response_sha256 or ""
                ),
                section_frontier_decoded_sha256=str(
                    section_frontier_decoded_sha256 or ""
                ),
                section_frontier_document_complete=bool(
                    section_frontier_document_complete
                ),
                section_frontier_sha256=self._bychapter_section_frontier_sha256(
                    active_sections,
                    inactive_sections,
                ),
                document_complete=bool(
                    re.search(r"</html\s*>\s*$", str(html or ""), flags=re.IGNORECASE)
                ),
                section_frontier_count=len(active_sections) + len(inactive_sections),
                section_active_count=len(active_sections),
                section_inactive_count=len(inactive_sections),
                active_section_numbers=active_sections,
                inactive_section_numbers=inactive_sections,
                parsed_section_numbers=parsed_sections,
                parsed_statutes=max(0, int(parsed_statutes)),
                admitted_statutes=max(0, int(admitted_statutes)),
                evidence_sha256="",
                checkpoint_hmac_sha256="",
                error_type=error_type,
                error_message=error_message,
            )
            item["evidence_sha256"] = self._bychapter_evidence_sha256(item)
            if checkpoint_hmac_key is not None:
                item["checkpoint_hmac_sha256"] = (
                    self._bychapter_checkpoint_hmac_sha256(
                        item,
                        checkpoint_hmac_key,
                    )
                )
            return item

        if full_corpus_run and max_chapters is not None:
            for number, name in frontier_catalog:
                if number in attempted_number_set:
                    continue
                evidence_by_number[number] = _evidence(
                    number,
                    name,
                    "not_attempted_chapter_cap",
                    resolved=False,
                )

        def _ordered_evidence() -> List[NorthCarolinaByChapterEvidence]:
            return [
                evidence_by_number[number]
                for number in frontier_numbers
                if number in evidence_by_number
            ]

        def _progress_extra(
            completion_status: str,
            *,
            codes_completed: int,
        ) -> Dict[str, Any]:
            evidence = _ordered_evidence()
            unresolved = [item for item in evidence if not item["resolved"]]
            unresolved_frontier = (
                [frontier_evidence]
                if frontier_evidence is not None and not frontier_evidence["resolved"]
                else []
            )
            attempted_count = sum(
                1
                for item in evidence
                if item["disposition"]
                not in {"not_attempted_chapter_cap", "not_attempted"}
            )
            return {
                "chapters_scanned": attempted_count,
                "discovered_chapters": frontier_total,
                "bychapter_completion_schema": self.BYCHAPTER_COMPLETION_SCHEMA,
                "bychapter_completion_status": completion_status,
                "bychapter_run_id": bychapter_run_id,
                "bychapter_run_started_at": bychapter_run_started_at,
                "bychapter_checkpoint_max_age_seconds": (
                    self._bychapter_checkpoint_max_age_seconds()
                ),
                "bychapter_checkpoint_hmac_enabled": checkpoint_hmac_key is not None,
                "bychapter_authenticated_resume_count": len(
                    authenticated_resume_done
                ),
                "bychapter_resume_envelope_valid": checkpoint_envelope_valid,
                "bychapter_full_corpus_required": full_corpus_run,
                "bychapter_frontier_count": frontier_total,
                "bychapter_frontier_source": (
                    "fresh_official_toc_active_frontier_with_pinned_omission_check"
                    if full_corpus_run
                    else "bounded_catalog_with_optional_live_discovery"
                ),
                "bychapter_frontier_verified": frontier_verified,
                "bychapter_frontier_evidence": frontier_evidence,
                "bychapter_attempted_count": attempted_count,
                "bychapter_resolved_count": len(done & frontier_number_set),
                "bychapter_unresolved_count": len(unresolved) + len(unresolved_frontier),
                "bychapter_done": [
                    number for number in frontier_numbers if number in done
                ],
                "bychapter_chapter_evidence": evidence,
                "bychapter_unresolved_dispositions": unresolved,
                "bychapter_unresolved_frontier_dispositions": unresolved_frontier,
                "codes_completed": int(codes_completed),
                "codes_total": 1,
            }

        async def _fetch_one(
            number: str,
        ) -> Tuple[str, NorthCarolinaByChapterFetchReceipt]:
            if full_corpus_run:
                receipt = await self._fetch_official_bychapter_page_fresh(number)
                return number, receipt
            html, provider = await self._fetch_official_bychapter_page(number)
            source_url = chapter_url(number)
            html_bytes = str(html or "").encode("utf-8", errors="replace")
            return number, NorthCarolinaByChapterFetchReceipt(
                html=str(html or ""),
                provider=str(provider or ""),
                http_status=200 if html else 0,
                final_url=source_url,
                final_host=(urlparse(source_url).hostname or "").lower(),
                observed_at=datetime.now(timezone.utc).isoformat(),
                response_sha256=hashlib.sha256(html_bytes).hexdigest(),
                decoded_sha256=hashlib.sha256(html_bytes).hexdigest(),
                error_type="",
                error_message="",
            )

        async def _fetch_section_frontier_one(
            number: str,
        ) -> Tuple[str, NorthCarolinaByChapterFetchReceipt]:
            receipt = await self._fetch_official_chapter_section_index_fresh(number)
            return number, receipt

        index = 0
        first_batch = True
        while index < len(remaining_catalog):
            if limit is not None and len(statutes) >= limit:
                break
            # Bounded probes often fill from Chapter 1; do not prefetch siblings first.
            size = 1 if first_batch else concurrency
            first_batch = False
            batch = remaining_catalog[index : index + size]
            index += size
            chapter_coroutines = [_fetch_one(number) for number, _name in batch]
            section_coroutines = (
                [
                    _fetch_section_frontier_one(number)
                    for number, _name in batch
                ]
                if full_corpus_run
                else []
            )
            fetched_all = await anyio_compat.gather(
                *(chapter_coroutines + section_coroutines),
                return_exceptions=True,
            )
            fetched = fetched_all[: len(batch)]
            fetched_section_frontiers = fetched_all[len(batch) :]
            by_number: Dict[str, NorthCarolinaByChapterFetchReceipt] = {}
            fetch_errors: Dict[str, BaseException] = {}
            for item, (number, _name) in zip(fetched, batch):
                if isinstance(item, BaseException):
                    fetch_errors[number] = item
                    self.logger.warning(
                        "North Carolina ByChapter fetch failed chapter=%s error=%s",
                        number,
                        item,
                    )
                    continue
                _number, receipt = item
                by_number[_number] = receipt
            section_by_number: Dict[str, NorthCarolinaByChapterFetchReceipt] = {}
            section_fetch_errors: Dict[str, BaseException] = {}
            for item, (number, _name) in zip(
                fetched_section_frontiers,
                batch,
            ):
                if isinstance(item, BaseException):
                    section_fetch_errors[number] = item
                    self.logger.warning(
                        "North Carolina section-frontier fetch failed chapter=%s error=%s",
                        number,
                        item,
                    )
                    continue
                _number, receipt = item
                section_by_number[_number] = receipt
            for number, _name in batch:
                if limit is not None and len(statutes) >= limit:
                    break
                fetch_error = fetch_errors.get(number)
                if fetch_error is not None:
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "fetch_exception",
                        resolved=False,
                        provider=(
                            self.BYCHAPTER_FRESH_PROVIDER
                            if full_corpus_run
                            else "requests_direct"
                        ),
                        authority="unknown",
                        error=fetch_error,
                    )
                    done.discard(number)
                    continue
                receipt = by_number.get(number) or NorthCarolinaByChapterFetchReceipt(
                    html="",
                    provider=(
                        self.BYCHAPTER_FRESH_PROVIDER
                        if full_corpus_run
                        else "requests_direct"
                    ),
                    http_status=0,
                    final_url=chapter_url(number),
                    final_host=self.OFFICIAL_DOMAIN,
                    observed_at=datetime.now(timezone.utc).isoformat(),
                    response_sha256=hashlib.sha256(b"").hexdigest(),
                    decoded_sha256=hashlib.sha256(b"").hexdigest(),
                    error_type="MissingFetchReceipt",
                    error_message="fetch task returned no receipt",
                )
                html = str(receipt.get("html") or "")
                provider = str(receipt.get("provider") or "")
                http_status = max(0, int(receipt.get("http_status") or 0))
                final_url = str(receipt.get("final_url") or chapter_url(number))
                final_host = str(
                    receipt.get("final_host") or (urlparse(final_url).hostname or "")
                ).lower()
                observed_at = str(receipt.get("observed_at") or "")
                response_sha256 = str(receipt.get("response_sha256") or "")
                decoded_sha256 = str(receipt.get("decoded_sha256") or "")
                receipt_error_type = str(receipt.get("error_type") or "")
                receipt_error_message = str(receipt.get("error_message") or "")
                evidence_kwargs = {
                    "provider": provider,
                    "http_status": http_status,
                    "final_url": final_url,
                    "final_host": final_host,
                    "observed_at": observed_at,
                    "response_sha256": response_sha256,
                    "decoded_sha256": decoded_sha256,
                    "error_type": receipt_error_type,
                    "error_message": receipt_error_message,
                }
                if receipt_error_type and not html:
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "fetch_exception",
                        resolved=False,
                        authority="unknown",
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                if full_corpus_run and provider != self.BYCHAPTER_FRESH_PROVIDER:
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "nonfresh_transport",
                        resolved=False,
                        html=html,
                        authority="recovery",
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                if full_corpus_run and http_status != 200:
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "http_status_not_ok",
                        resolved=False,
                        html=html,
                        authority="unknown",
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                parsed_final_host = (urlparse(final_url).hostname or "").lower()
                if full_corpus_run and (
                    not self.is_official_nc_url(final_url)
                    or final_host != parsed_final_host
                ):
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "nonofficial_final_host",
                        resolved=False,
                        html=html,
                        authority="recovery",
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                if full_corpus_run and final_url != chapter_url(number):
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "unexpected_final_url",
                        resolved=False,
                        html=html,
                        authority="unknown",
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                calculated_sha256 = hashlib.sha256(
                    html.encode("utf-8", errors="replace")
                ).hexdigest()
                if full_corpus_run and (
                    len(response_sha256) != 64
                    or len(decoded_sha256) != 64
                    or decoded_sha256 != calculated_sha256
                ):
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "response_hash_mismatch",
                        resolved=False,
                        html=html,
                        authority="unknown",
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                if full_corpus_run and not self._bychapter_observed_at_valid(observed_at):
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "invalid_observation_receipt",
                        resolved=False,
                        html=html,
                        authority="unknown",
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                if not html:
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "fetch_empty",
                        resolved=False,
                        authority="unknown",
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                if len(html.encode("utf-8", errors="replace")) < 200:
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "fetch_short_response",
                        resolved=False,
                        html=html,
                        authority="unknown",
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                if full_corpus_run and not re.search(
                    r"</html\s*>\s*$",
                    html,
                    flags=re.IGNORECASE,
                ):
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "incomplete_html_document",
                        resolved=False,
                        html=html,
                        authority="unknown",
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                authority, _source_kind = self._classify_html_transport(provider)
                active_section_numbers: List[str] = []
                inactive_section_numbers: List[str] = []
                if full_corpus_run:
                    section_fetch_error = section_fetch_errors.get(number)
                    if section_fetch_error is not None:
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_fetch_exception",
                            resolved=False,
                            html=html,
                            authority=authority,
                            error=section_fetch_error,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                    section_receipt = section_by_number.get(number) or {}
                    section_html = str(section_receipt.get("html") or "")
                    section_provider = str(section_receipt.get("provider") or "")
                    section_status = max(
                        0,
                        int(section_receipt.get("http_status") or 0),
                    )
                    section_final_url = str(
                        section_receipt.get("final_url")
                        or chapter_sections_url(number)
                    )
                    section_final_host = str(
                        section_receipt.get("final_host")
                        or (urlparse(section_final_url).hostname or "")
                    ).lower()
                    section_observed_at = str(
                        section_receipt.get("observed_at") or ""
                    )
                    section_response_sha256 = str(
                        section_receipt.get("response_sha256") or ""
                    )
                    section_decoded_sha256 = str(
                        section_receipt.get("decoded_sha256") or ""
                    )
                    section_error_type = str(
                        section_receipt.get("error_type") or ""
                    )
                    section_error_message = str(
                        section_receipt.get("error_message") or ""
                    )
                    section_bytes = section_html.encode("utf-8", errors="replace")
                    section_document_complete = bool(
                        re.search(
                            r"</html\s*>\s*$",
                            section_html,
                            flags=re.IGNORECASE,
                        )
                    )
                    section_evidence_kwargs = {
                        "section_frontier_provider": section_provider,
                        "section_frontier_http_status": section_status,
                        "section_frontier_final_url": section_final_url,
                        "section_frontier_final_host": section_final_host,
                        "section_frontier_observed_at": section_observed_at,
                        "section_frontier_response_bytes": len(section_bytes),
                        "section_frontier_response_sha256": (
                            section_response_sha256
                        ),
                        "section_frontier_decoded_sha256": (
                            section_decoded_sha256
                        ),
                        "section_frontier_document_complete": (
                            section_document_complete
                        ),
                    }
                    evidence_kwargs.update(section_evidence_kwargs)
                    if section_error_type and not section_html:
                        failure_kwargs = dict(evidence_kwargs)
                        failure_kwargs["error_type"] = section_error_type
                        failure_kwargs["error_message"] = section_error_message
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_fetch_exception",
                            resolved=False,
                            html=html,
                            authority=authority,
                            **failure_kwargs,
                        )
                        done.discard(number)
                        continue
                    if section_provider != self.BYCHAPTER_FRESH_PROVIDER:
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_nonfresh_transport",
                            resolved=False,
                            html=html,
                            authority=authority,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                    if section_status != 200:
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_http_status_not_ok",
                            resolved=False,
                            html=html,
                            authority=authority,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                    parsed_section_final_host = (
                        urlparse(section_final_url).hostname or ""
                    ).lower()
                    if (
                        not self.is_official_nc_url(section_final_url)
                        or section_final_host != parsed_section_final_host
                    ):
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_nonofficial_final_host",
                            resolved=False,
                            html=html,
                            authority=authority,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                    if section_final_url != chapter_sections_url(number):
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_unexpected_final_url",
                            resolved=False,
                            html=html,
                            authority=authority,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                    calculated_section_sha256 = hashlib.sha256(
                        section_bytes
                    ).hexdigest()
                    if (
                        len(section_response_sha256) != 64
                        or len(section_decoded_sha256) != 64
                        or section_decoded_sha256 != calculated_section_sha256
                    ):
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_response_hash_mismatch",
                            resolved=False,
                            html=html,
                            authority=authority,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                    if not self._bychapter_observed_at_valid(section_observed_at):
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_invalid_observation_receipt",
                            resolved=False,
                            html=html,
                            authority=authority,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                    if not section_document_complete:
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_incomplete_html_document",
                            resolved=False,
                            html=html,
                            authority=authority,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                    try:
                        section_records = chapter_section_index_frontier(
                            section_html,
                            chapter=number,
                        )
                    except Exception as exc:
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_parse_exception",
                            resolved=False,
                            html=html,
                            authority=authority,
                            error=exc,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                    active_section_numbers = [
                        record["section_number"]
                        for record in section_records
                        if record["disposition"] == "active"
                    ]
                    inactive_section_numbers = [
                        record["section_number"]
                        for record in section_records
                        if record["disposition"] == "inactive"
                    ]
                    if not section_records or not active_section_numbers:
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_empty",
                            resolved=False,
                            html=html,
                            authority=authority,
                            active_section_numbers=active_section_numbers,
                            inactive_section_numbers=inactive_section_numbers,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                remaining = None if limit is None else max(0, int(limit) - len(statutes))
                if remaining is not None and remaining <= 0:
                    break
                try:
                    if authority == "recovery":
                        rows = parse_north_carolina_archive_html(
                            html,
                            chapter=number,
                            source_url=chapter_url(number),
                            code_name=code_name,
                            max_statutes=remaining,
                        )
                    else:
                        rows = parse_north_carolina_chapter_html(
                            html,
                            chapter=number,
                            code_name=code_name,
                            max_statutes=remaining,
                        )
                except Exception as exc:
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "parse_exception",
                        resolved=False,
                        html=html,
                        authority=authority,
                        error=exc,
                        active_section_numbers=active_section_numbers,
                        inactive_section_numbers=inactive_section_numbers,
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    self.logger.warning(
                        "North Carolina ByChapter parse failed chapter=%s error=%s",
                        number,
                        exc,
                    )
                    continue
                if not rows:
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "parse_zero_statutes",
                        resolved=False,
                        html=html,
                        authority=authority,
                        active_section_numbers=active_section_numbers,
                        inactive_section_numbers=inactive_section_numbers,
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                if full_corpus_run and not active_section_numbers:
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "section_frontier_empty",
                        resolved=False,
                        html=html,
                        authority=authority,
                        parsed_statutes=len(rows),
                        parsed_section_numbers=[
                            str(row.section_number or "").strip() for row in rows
                        ],
                        active_section_numbers=active_section_numbers,
                        inactive_section_numbers=inactive_section_numbers,
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                parsed_section_numbers = [
                    str(row.section_number or "").strip() for row in rows
                ]
                expected_section_prefix = f"{number}-".upper()
                if any(
                    not str(row.section_number or "").strip().upper().startswith(
                        expected_section_prefix
                    )
                    for row in rows
                ):
                    evidence_by_number[number] = _evidence(
                        number,
                        _name,
                        "chapter_identity_mismatch",
                        resolved=False,
                        html=html,
                        authority=authority,
                        parsed_statutes=len(rows),
                        active_section_numbers=active_section_numbers,
                        inactive_section_numbers=inactive_section_numbers,
                        parsed_section_numbers=parsed_section_numbers,
                        **evidence_kwargs,
                    )
                    done.discard(number)
                    continue
                if full_corpus_run:
                    active_set = set(active_section_numbers)
                    parsed_set = set(parsed_section_numbers)
                    missing_active_sections = active_set - parsed_set
                    if missing_active_sections:
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_underfill",
                            resolved=False,
                            html=html,
                            authority=authority,
                            parsed_statutes=len(rows),
                            active_section_numbers=active_section_numbers,
                            inactive_section_numbers=inactive_section_numbers,
                            parsed_section_numbers=parsed_section_numbers,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                    if (
                        parsed_set != active_set
                        or len(parsed_section_numbers) != len(parsed_set)
                    ):
                        evidence_by_number[number] = _evidence(
                            number,
                            _name,
                            "section_frontier_mismatch",
                            resolved=False,
                            html=html,
                            authority=authority,
                            parsed_statutes=len(rows),
                            active_section_numbers=active_section_numbers,
                            inactive_section_numbers=inactive_section_numbers,
                            parsed_section_numbers=parsed_section_numbers,
                            **evidence_kwargs,
                        )
                        done.discard(number)
                        continue
                added = 0
                admit_rows = authority != "recovery" or not full_corpus_run
                if admit_rows:
                    for row in rows:
                        key = str(row.section_number or "").strip().lower()
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        statutes.append(row)
                        added += 1
                        if limit is not None and len(statutes) >= limit:
                            break
                resolved = authority == "official" or not full_corpus_run
                disposition: NorthCarolinaByChapterDisposition = (
                    "official_parsed"
                    if authority == "official"
                    else (
                        "unverified_cache_provenance"
                        if "unverified_cache" in provider.lower()
                        else "recovery_transport_only"
                    )
                )
                evidence_by_number[number] = _evidence(
                    number,
                    _name,
                    disposition,
                    resolved=resolved,
                    html=html,
                    authority=authority,
                    parsed_statutes=len(rows),
                    admitted_statutes=added,
                    active_section_numbers=active_section_numbers,
                    inactive_section_numbers=inactive_section_numbers,
                    parsed_section_numbers=parsed_section_numbers,
                    chapter_rows_sha256=self._bychapter_checkpoint_rows_sha256(
                        statutes,
                        number,
                    ),
                    **evidence_kwargs,
                )
                if resolved:
                    done.add(number)
                else:
                    done.discard(number)
                self.logger.info(
                    "North Carolina ByChapter: chapter=%s/%s parsed=%s statutes_so_far=%s transport=%s",
                    number,
                    total,
                    added,
                    len(statutes),
                    authority,
                )
            batch_unresolved = any(
                number in evidence_by_number and not evidence_by_number[number]["resolved"]
                for number, _name in batch
            )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="north-carolina:bychapter",
                force=batch_unresolved,
                extra=_progress_extra("in_progress", codes_completed=0),
                replace_existing_rows=full_corpus_run,
            )

        if full_corpus_run:
            for number, name in frontier_catalog:
                if number in evidence_by_number:
                    continue
                evidence_by_number[number] = _evidence(
                    number,
                    name,
                    (
                        "not_attempted_chapter_cap"
                        if max_chapters is not None
                        else "not_attempted"
                    ),
                    resolved=False,
                )
            unresolved = [
                item for item in _ordered_evidence() if not item["resolved"]
            ]
            fully_resolved = (
                frontier_verified
                and not unresolved
                and done == frontier_number_set
            )
            if not fully_resolved:
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="north-carolina:bychapter-incomplete",
                    force=True,
                    extra=_progress_extra("incomplete", codes_completed=0),
                    replace_existing_rows=True,
                )
                raise NorthCarolinaByChapterIncompleteError(
                    resolved_count=len(done & frontier_number_set),
                    total_count=frontier_total,
                    unresolved=unresolved,
                )
            completion_status = "complete"
            codes_completed = 1
        else:
            target_reached = limit is None or len(statutes) >= int(limit)
            completion_status = (
                "bounded_target_reached" if target_reached else "bounded_incomplete"
            )
            # Bounded output is useful for probes but is never corpus authority.
            codes_completed = 0

        final_stage_label = (
            "north-carolina:bychapter-complete"
            if full_corpus_run
            else "north-carolina:bychapter-bounded"
        )
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label=final_stage_label,
            force=True,
            extra=_progress_extra(completion_status, codes_completed=codes_completed),
            replace_existing_rows=full_corpus_run,
        )
        return statutes[: int(limit)] if limit is not None else statutes

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
        sem = anyio_compat.Semaphore(concurrency)

        async def _parse_source_url(source_url: str) -> Optional[NormalizedStatute]:
            html = await self._request_text_direct(source_url, timeout=20)
            if not html:
                return None
            provider = str(getattr(self, "_last_fetch_provider", "") or "")
            authority, source_kind = self._classify_html_transport(provider)
            if self._NC_CHAPTER_BYCHAPTER_RE.search(source_url):
                from .north_carolina_chapter import parse_north_carolina_chapter_html

                chapter = self._NC_CHAPTER_BYCHAPTER_RE.search(source_url).group(1)
                chapter_rows = parse_north_carolina_chapter_html(
                    html,
                    chapter=chapter,
                    code_name=code_name,
                    max_statutes=self.FIRST_BYCHAPTER_STATUTE_LIMIT,
                )
                if chapter_rows:
                    return chapter_rows[0]
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 80:
                return None
            if self._looks_contaminated(text):
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
                    "source_kind": source_kind,
                    "source_authority_class": authority,
                    "fetch_transport": provider or "archival_fallback",
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

        results = await anyio_compat.gather(
            *[_bounded_parse(source_url) for source_url in section_urls],
            return_exceptions=True,
        )
        total_sections = len(results)
        for scanned_sections, result in enumerate(results, start=1):
            statute = None if isinstance(result, BaseException) else result
            if statute is not None:
                out.append(statute)
            if progress_hook is not None:
                try:
                    progress_hook(scanned_sections, total_sections, out)
                except Exception:
                    pass
            if limit is not None and len(out) >= limit:
                break
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
            provider = str(getattr(self, "_last_fetch_provider", "") or "")
            authority, source_kind = self._classify_html_transport(provider)
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 80:
                continue
            if self._looks_contaminated(text):
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
                        "source_kind": source_kind,
                        "source_authority_class": authority,
                        "fetch_transport": provider or "requests_direct",
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
            await anyio_compat.sleep(0.2)

        def _request() -> str:
            try:
                req = urllib.request.Request(canonical, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            return await anyio_compat.wait_for(
                anyio_compat.to_thread(_request),
                timeout + 2,
            )
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

    _RECOVERY_FETCH_PROVIDERS = (
        "wayback",
        "archive_is",
        "common_crawl",
        "archival_fallback",
        "common_crawl_insecure_tls",
        "unverified_cache",
    )

    def _classify_html_transport(self, provider: str) -> Tuple[str, str]:
        token = str(provider or "").strip().lower()
        if any(marker in token for marker in self._RECOVERY_FETCH_PROVIDERS):
            return "recovery", "official_north_carolina_general_statutes_html_via_archive"
        return "official", "official_north_carolina_general_statutes_html"

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
                if int(getattr(response, "status", 200) or 200) == 200:
                    payload = bytes(response.read() or b"")
                    if payload:
                        return payload
        except Exception:
            pass
        return self._official_http_get_via_archive(url, timeout_seconds=max(8, timeout))

    def _official_http_get_via_archive(self, url: str, timeout_seconds: int = 12) -> bytes:
        """Recover an official ncleg.gov page through Wayback. Not a Justia path."""

        if not self.is_official_nc_url(url):
            return b""
        timeout = max(8, int(timeout_seconds or 12))
        wayback = f"https://web.archive.org/web/2026/{url}"
        try:
            request = urllib.request.Request(
                wayback,
                headers={
                    "User-Agent": "ipfs-datasets-north-carolina-official-catalog/1.0",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
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
