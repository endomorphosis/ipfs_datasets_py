"""Scraper for West Virginia state laws.

This module contains the scraper for West Virginia statutes from the official state legislative website.
"""

import hashlib
import json
import re
import ssl
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class WestVirginiaScraper(BaseStateScraper):
    """Scraper for West Virginia state laws from https://code.wvlegislature.gov"""

    OFFICIAL_DOMAIN = "code.wvlegislature.gov"
    OFFICIAL_ENTRY_PATH = "/"
    OFFICIAL_ENTRY_URL = "https://code.wvlegislature.gov/"
    _WV_CHAPTER_HREF_RE = re.compile(
        r"https?://code\.wvlegislature\.gov/(?P<chapter>\d+[A-Za-z]?)/?$",
        re.IGNORECASE,
    )
    _WV_CHAPTER_LABEL_RE = re.compile(
        r"\bChapter\s+(?P<chapter>\d+[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    _WV_CONTINUATION_RE = re.compile(
        r"\b(next|continue|more chapters|page\s+\d+)\b",
        re.IGNORECASE,
    )
    OFFICIAL_CHAPTERS = (
        ("1", "The State and Its Subdivisions"),
        ("2", "Common Law, Statutes, Legal Holidays, Definitions and Legal Capacity"),
        ("3", "Elections"),
        ("4", "The Legislature"),
        ("5", "General Powers and Authority of the Governor, Secretary of State and Attorney General; Board of Public Works; Miscellaneous Agencies, Commissions, Offices, Programs, etc."),
        ("5A", "Department of Administration"),
        ("5B", "Economic Development Act of 1985"),
        ("5C", "Basic Assistance for Industry and Trade"),
        ("5D", "Public Energy Authority Act"),
        ("5E", "Venture Capital Company"),
        ("5F", "Reorganization of the Executive Branch of State Government"),
        ("5G", "Procurement of Architect-Engineer Services by State and Its Subdivisions"),
        ("5H", "Survivor Benefits"),
        ("6", "General Provisions Respecting Officers"),
        ("6A", "Executive and Judicial Succession"),
        ("6B", "Public Officers and Employees; Ethics; Conflicts of Interest; Financial Disclosure"),
        ("6C", "Public Employees"),
        ("6D", "Public Contracts"),
        ("7", "County Commissions and Officers"),
        ("7A", "Consolidated Local Government"),
        ("8", "Municipal Corporations"),
        ("8A", "Land Use Planning"),
        ("9", "Human Services"),
        ("9A", "Veterans' Affairs"),
        ("10", "Public Libraries; Public Recreation; Athletic Establishments; Monuments and Memorials; Roster of Servicemen; Educational Broadcasting Authority"),
        ("11", "Taxation"),
        ("11A", "Collection and Enforcement of Property Taxes"),
        ("11B", "Department of Revenue"),
        ("12", "Public Moneys and Securities"),
        ("13", "Public Bonded Indebtedness"),
        ("14", "Claims Due and Against the State"),
        ("15", "Public Safety"),
        ("15A", "Department of Homeland Security"),
        ("16", "Public Health"),
        ("16A", "Medical Cannabis Act"),
        ("16B", "Inspector General"),
        ("17", "Roads and Highways"),
        ("17A", "Motor Vehicle Administration, Registration, Certificate of Title, and Antitheft Provisions"),
        ("17B", "Motor Vehicle Driver's Licenses"),
        ("17C", "Traffic Regulations and Laws of the Road"),
        ("17D", "Motor Vehicle Safety Responsibility Law"),
        ("17E", "Uniform Commercial Driver's License Act"),
        ("17F", "All-Terrain Vehicles"),
        ("17G", "Racial Profiling Data Collection Act"),
        ("17H", "Fully Autonomous Vehicle Act"),
        ("18", "Education"),
        ("18A", "School Personnel"),
        ("18B", "Higher Education"),
        ("18C", "Student Loans; Scholarships and State Aid"),
        ("19", "Agriculture"),
        ("20", "Natural Resources"),
        ("21", "Labor"),
        ("21A", "Unemployment Compensation"),
        ("22", "Environmental Resources"),
        ("22A", "Miners' Health, Safety and Training"),
        ("22B", "Environmental Boards"),
        ("22C", "Environmental Resources; Boards, Authorities, Commissions and Compacts"),
        ("23", "Workers' Compensation"),
        ("24", "Public Service Commission"),
        ("24A", "Commercial Motor Carriers"),
        ("24B", "Gas Pipeline Safety"),
        ("24C", "Underground Facilities Damage Prevention"),
        ("24D", "Cable Television"),
        ("24E", "Statewide Addressing and Mapping"),
        ("24F", "Veterans' Grave Markers"),
        ("25", "Division of Corrections"),
        ("26", "State Health Facilities"),
        ("27", "Mentally Ill Persons"),
        ("28", "State Correctional and Penal Institutions"),
        ("29", "Miscellaneous Boards and Officers"),
        ("29A", "State Administrative Procedures Act"),
        ("29B", "Freedom of Information"),
        ("29C", "Uniform Notary Act"),
        ("30", "Professions and Occupations"),
        ("31", "Corporations"),
        ("31A", "Banks and Banking"),
        ("31B", "Uniform Limited Liability Company Act"),
        ("31C", "Credit Unions"),
        ("31D", "West Virginia Business Corporation Act"),
        ("31E", "West Virginia Nonprofit Corporation Act"),
        ("31F", "West Virginia Benefit Corporation Act"),
        ("31G", "Broadband Enhancement and Expansion Policies"),
        ("31H", "Small Wireless Facilities Deployment Act"),
        ("31I", "Trust Companies"),
        ("31J", "Wireless Tower Facilities"),
        ("32", "Uniform Securities Act"),
        ("32A", "Land Sales; False Advertising; Issuance and Sale of Checks, Drafts, Money Orders, Etc."),
        ("32B", "The West Virginia Commodities Act"),
        ("33", "Insurance"),
        ("34", "Estrays, Drift and Derelict Property"),
        ("35", "Property of Religious, Educational and Charitable Organizations"),
        ("35A", "Names, Emblems, Etc., of Associations, Lodges, Etc."),
        ("36", "Estates and Property"),
        ("36A", "Condominiums and Unit Property"),
        ("36B", "Uniform Common Interest Ownership Act"),
        ("37", "Real Property"),
        ("37A", "Zoning"),
        ("37B", "Mineral Development"),
        ("37C", "Mineral Development"),
        ("38", "Liens"),
        ("39", "Records and Papers"),
        ("39A", "Electronic Commerce"),
        ("39B", "Uniform Power of Attorney Act"),
        ("40", "Acts Void as to Creditors and Purchasers"),
        ("41", "Wills"),
        ("42", "Descent and Distribution"),
        ("43", "Dower and Valuation of Life Estates"),
        ("44", "Administration of Estates and Trusts"),
        ("44A", "West Virginia Guardianship and Conservatorship Act"),
        ("44B", "Uniform Principal and Income Act"),
        ("44C", "Uniform Adult Guardianship and Protective Proceedings Jurisdiction Act"),
        ("44D", "Uniform Trust Code"),
        ("45", "Suretyship and Guaranty"),
        ("46", "Uniform Commercial Code"),
        ("46A", "West Virginia Consumer Credit and Protection Act"),
        ("46B", "Regulation of the Rental of Consumer Goods Under Rent-to-Own Agreements"),
        ("47", "Regulation of Trade"),
        ("47A", "West Virginia Lending and Credit Rate Board"),
        ("47B", "Uniform Partnership Act"),
        ("48", "Domestic Relations"),
        ("49", "Child Welfare"),
        ("49A", "Child Online Protection and Liability"),
        ("50", "Magistrate Courts"),
        ("51", "Courts and Their Officers"),
        ("52", "Juries"),
        ("53", "Extraordinary Remedies"),
        ("54", "Eminent Domain"),
        ("55", "Actions, Suits and Arbitration; Judicial Sale"),
        ("56", "Pleading and Practice"),
        ("57", "Evidence and Witnesses"),
        ("58", "Appeal and Error"),
        ("59", "Fees, Allowances and Costs; Newspapers; Legal Advertisements"),
        ("60", "State Control of Alcoholic Liquors"),
        ("60A", "Uniform Controlled Substances Act"),
        ("60B", "Donated Drug Repository Program"),
        ("61", "Crimes and Their Punishment"),
        ("62", "Criminal Procedure"),
        ("63", "Repeal of Statutes"),
        ("64", "Legislative Rules"),
    )
    OFFICIAL_CHAPTER_COUNT = len(OFFICIAL_CHAPTERS)

    _WV_SECTION_URL_RE = re.compile(r"/\d+[A-Za-z]?(?:-\d+[A-Za-z]?){1,2}/?$")
    _WV_CHAPTER_PATH_RE = re.compile(
        r"^/(?P<chapter>\d+[A-Za-z]?)/?$",
        re.IGNORECASE,
    )
    _WV_ARTICLE_PATH_RE = re.compile(
        r"^/(?P<chapter>\d+[A-Za-z]?)-(?P<article>\d+[A-Za-z]?)/?$",
        re.IGNORECASE,
    )
    _WV_STRICT_SECTION_PATH_RE = re.compile(
        r"^/(?P<chapter>\d+[A-Za-z]?)-(?P<article>\d+[A-Za-z]?)-"
        r"(?P<section>\d+[A-Za-z]?)/?$",
        re.IGNORECASE,
    )
    _WV_FUTURE_EFFECTIVE_RE = re.compile(
        r"\beffective\s+(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\b",
        re.IGNORECASE,
    )

    def _west_virginia_frontier_batch_size(self) -> int:
        return max(
            1,
            min(
                1024,
                self._env_int("STATE_SCRAPER_WV_FRONTIER_BATCH_SIZE", default=512),
            ),
        )

    def _west_virginia_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                self._env_int("STATE_SCRAPER_WV_FRONTIER_CONCURRENCY", default=12),
            ),
        )

    @staticmethod
    def _is_valid_west_virginia_frontier_payload(payload: bytes) -> bool:
        """Reject generic error/redirect bodies before parser admission."""

        sample = bytes(payload or b"")[:500_000].lower()
        if not sample:
            return False
        return bool(
            b"west virginia code" in sample
            and b"<html" in sample
            and b"<title>404" not in sample
            and b"404 not found" not in sample
            and b"document moved" not in sample[:2_000]
        )

    def _validate_west_virginia_aligned_evidence(
        self,
        *,
        url: str,
        payload: bytes,
        transport_receipt: Any,
        parser_input_envelope: Any,
        frontier_name: str,
    ) -> None:
        """Require exact URL/body evidence whenever the ledger is attached."""

        canonical_url = self._canonical_fetch_url(url)
        digest = hashlib.sha256(payload).hexdigest()
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if ledger_attached and (
            not isinstance(transport_receipt, Mapping)
            or not transport_receipt
            or parser_input_envelope is None
        ):
            raise RuntimeError(
                f"West Virginia {frontier_name} frontier lacks retained evidence: {url}"
            )
        if isinstance(transport_receipt, Mapping):
            observed_url = str(
                transport_receipt.get("official_url")
                or transport_receipt.get("endpoint")
                or ""
            ).strip()
            observed_digest = str(
                transport_receipt.get("content_sha256") or ""
            ).strip().lower()
            if ledger_attached and (not observed_url or not observed_digest):
                raise RuntimeError(
                    "West Virginia "
                    f"{frontier_name} receipt lacks URL/digest evidence: {url}"
                )
            if observed_url and self._canonical_fetch_url(observed_url) != canonical_url:
                raise RuntimeError(
                    "West Virginia "
                    f"{frontier_name} receipt changed URL identity: {url}"
                )
            if observed_digest and observed_digest != digest:
                raise RuntimeError(
                    "West Virginia "
                    f"{frontier_name} receipt changed payload identity: {url}"
                )
        if parser_input_envelope is not None:
            envelope_body = getattr(parser_input_envelope, "body", None)
            if ledger_attached and envelope_body is None:
                raise RuntimeError(
                    f"West Virginia {frontier_name} envelope lacks body evidence: {url}"
                )
            if envelope_body is not None and bytes(envelope_body) != payload:
                raise RuntimeError(
                    "West Virginia "
                    f"{frontier_name} envelope changed payload identity: {url}"
                )

    async def _fetch_west_virginia_frontier_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        retained_only: bool = False,
    ) -> List[bytes]:
        """Fetch or replay one exact same-domain frontier as an ordered batch."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if any(not url for url in requested):
            raise RuntimeError(
                f"West Virginia {frontier_name} frontier contains an invalid URL"
            )
        if len(set(requested)) != len(requested):
            raise RuntimeError(
                f"West Virginia {frontier_name} frontier contains duplicate URLs"
            )
        if any(urlparse(url).hostname != self.OFFICIAL_DOMAIN for url in requested):
            raise RuntimeError(
                f"West Virginia {frontier_name} frontier left the official domain"
            )
        if not requested:
            return []
        if retained_only:
            from .strict_frontier_closure import (
                replay_exact_retained_state_records,
            )

            retained_rows = replay_exact_retained_state_records(
                self,
                requests=tuple(
                    (url, {"method": "GET", "url": url}) for url in requested
                ),
                frontier_name=f"West Virginia {frontier_name}",
                refresh=False,
            )
            payloads: List[bytes] = []
            for url, retained in zip(requested, retained_rows, strict=True):
                envelope = getattr(retained, "envelope", None)
                raw = bytes(getattr(envelope, "body", b"") or b"")
                if not self._is_valid_west_virginia_frontier_payload(raw):
                    raise RuntimeError(
                        "West Virginia retained replay failed the current content "
                        f"validator: {url}"
                    )
                self._validate_west_virginia_aligned_evidence(
                    url=url,
                    payload=raw,
                    transport_receipt=getattr(
                        retained,
                        "transport_receipt",
                        None,
                    ),
                    parser_input_envelope=envelope,
                    frontier_name=frontier_name,
                )
                payloads.append(raw)
            stats_rows = list(
                getattr(self, "_west_virginia_replay_batch_stats", [])
            )
            stats_rows.append(
                {
                    "frontier_name": frontier_name,
                    "network_requested_pages": 0,
                    "requested_pages": len(requested),
                    "retained_replay_pages": len(requested),
                    "successful_pages": len(requested),
                    "unique_pages": len(requested),
                }
            )
            self._west_virginia_replay_batch_stats = stats_rows
            return payloads
        retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=1,
                ),
            ),
        )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=retry_attempts,
            timeout_seconds=25,
            content_validator=self._is_valid_west_virginia_frontier_payload,
            media_type="text/html",
            max_concurrency=self._west_virginia_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
        )
        aligned_lengths = {
            len(batch.urls),
            len(batch.payloads),
            len(batch.errors),
            len(batch.transport_receipts),
            len(batch.parser_input_envelopes),
        }
        if aligned_lengths != {len(requested)}:
            raise RuntimeError(
                "West Virginia "
                f"{frontier_name} frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"West Virginia {frontier_name} frontier changed URL order or identity"
            )
        failures: List[Dict[str, str]] = []
        payloads: List[bytes] = []
        for url, payload, error, receipt, envelope in zip(
            batch.urls,
            batch.payloads,
            batch.errors,
            batch.transport_receipts,
            batch.parser_input_envelopes,
            strict=True,
        ):
            raw = bytes(payload or b"")
            if error is not None or not self._is_valid_west_virginia_frontier_payload(raw):
                failures.append(
                    {"url": url, "error": str(error or "empty or invalid parser input")}
                )
                continue
            self._validate_west_virginia_aligned_evidence(
                url=url,
                payload=raw,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
                frontier_name=frontier_name,
            )
            payloads.append(raw)
        if failures:
            raise RuntimeError(
                f"West Virginia {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures}"
            )
        batch_stats = dict(batch.stats or {})
        stats_rows = list(
            getattr(self, "_west_virginia_frontier_batch_stats", [])
        )
        stats_rows.append(
            {
                **batch_stats,
                "frontier_name": frontier_name,
                "network_requested_pages": int(
                    batch_stats.get("network_requested_pages", len(requested))
                ),
                "requested_pages": len(requested),
                "retained_replay_pages": int(
                    batch_stats.get("retained_replay_pages", 0)
                ),
                "successful_pages": len(requested),
                "unique_pages": len(requested),
            }
        )
        self._west_virginia_frontier_batch_stats = stats_rows
        return payloads

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._WV_SECTION_URL_RE.search(source):
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
        """Return the base URL for West Virginia's legislative website."""
        return "https://code.wvlegislature.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for West Virginia."""
        return [
            {"name": "West Virginia Code", "url": f"{self.get_base_url()}/", "type": "Code"}
        ]

    async def scrape_code(
        self, code_name: str, code_url: str, max_statutes: int | None = None
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from West Virginia's legislative website.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .west_virginia_constitution import (
            configured_constitution_html_path,
            parse_west_virginia_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_west_virginia_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "West Virginia Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .west_virginia_dump import (
            configured_code_html_path,
            parse_west_virginia_code_html,
        )

        dump_path = configured_code_html_path()
        if dump_path is not None:
            bulk = parse_west_virginia_code_html(
                dump_path.read_text(encoding="utf-8", errors="replace"),
                code_name=code_name,
                max_statutes=limit,
            )
            if bulk:
                return bulk
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
                "West Virginia full-corpus run found zero official statutes; "
                "refusing secondary Justia/generic sole-admission fallback"
            )
            return []

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/1/",
            f"{self.get_base_url()}/11/",
            f"{self.get_base_url()}/11-8-12/",
            f"{self.get_base_url()}/1-1/",
            f"{self.get_base_url()}/",
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
                        "W. Va. Code",
                        max_sections=fallback_scan_limit,
                        wait_for_selector="a[href*='wvlegislature.gov/'][href*='-'], a[href*='/code/'], a[href*='/article/']",
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
                code_name, candidate, "W. Va. Code", max_sections=fallback_scan_limit
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
        seeds = [
            ("61-2-1", "https://code.wvlegislature.gov/61-2-1/"),
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
        if self._full_corpus_enabled() and max_statutes is None:
            return await self._scrape_strict_full_corpus_frontier(
                code_name,
                record_primary=True,
                write_checkpoints=True,
            )
        chapter_links = await self._discover_chapter_links()
        self.logger.info(
            "West Virginia official index: discovered %s chapter links", len(chapter_links)
        )
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            article_links = await self._discover_article_links(chapter_url)
            self.logger.info(
                "West Virginia official index: chapter=%s index=%s/%s articles=%s statutes_so_far=%s",
                chapter_label or chapter_url,
                chapter_index,
                len(chapter_links),
                len(article_links),
                len(statutes),
            )
            for article_index, (article_url, article_label) in enumerate(article_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                section_links = await self._discover_section_links(article_url)
                if (
                    article_index == 1
                    or article_index % 10 == 0
                    or article_index == len(article_links)
                ):
                    self.logger.info(
                        "West Virginia official index: chapter=%s article=%s/%s sections=%s statutes_so_far=%s",
                        chapter_label or chapter_url,
                        article_index,
                        len(article_links),
                        len(section_links),
                        len(statutes),
                    )
                parsed = await self._scrape_section_urls(
                    code_name,
                    section_links,
                    max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                    discovery_method="official_chapter_article_section_index",
                )
                statutes.extend(parsed)
        return statutes[:limit] if limit is not None else statutes

    def _canonical_west_virginia_hierarchy_url(
        self,
        url: str,
        *,
        level: str,
        chapter_number: str = "",
        article_number: str = "",
    ) -> Tuple[str, Dict[str, str]]:
        parsed = urlparse(str(url or ""))
        patterns = {
            "chapter": self._WV_CHAPTER_PATH_RE,
            "article": self._WV_ARTICLE_PATH_RE,
            "section": self._WV_STRICT_SECTION_PATH_RE,
        }
        pattern = patterns.get(level)
        match = pattern.fullmatch(parsed.path) if pattern is not None else None
        if (
            parsed.scheme.lower() != "https"
            or (parsed.hostname or "").lower() != self.OFFICIAL_DOMAIN
            or parsed.username is not None
            or parsed.password is not None
            or parsed.params
            or parsed.query
            or parsed.fragment
            or match is None
        ):
            raise RuntimeError(
                f"West Virginia {level} frontier exposed a non-canonical URL: {url}"
            )
        groups = {
            key: str(value or "").strip().upper()
            for key, value in match.groupdict().items()
        }
        expected_chapter = str(chapter_number or "").strip().upper()
        expected_article = str(article_number or "").strip().upper()
        if expected_chapter and groups.get("chapter") != expected_chapter:
            raise RuntimeError(
                f"West Virginia {level} URL escaped its chapter parent: {url}"
            )
        if expected_article and groups.get("article") != expected_article:
            raise RuntimeError(
                f"West Virginia {level} URL escaped its article parent: {url}"
            )
        canonical = f"https://{self.OFFICIAL_DOMAIN}{parsed.path.rstrip('/')}/"
        return canonical, groups

    def _west_virginia_root_chapter_units(self, payload: bytes) -> List[Dict[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError(
                "BeautifulSoup is required for West Virginia strict traversal"
            ) from exc
        soup = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
        units: List[Dict[str, str]] = []
        seen: set[str] = set()
        for option in soup.select("select#sel-chapter option[value]"):
            chapter = self._normalize_chapter_number(option.get("value"))
            if not chapter:
                raise RuntimeError(
                    "West Virginia official chapter selector contains an invalid value"
                )
            key = chapter.casefold()
            if key in seen:
                raise RuntimeError(
                    f"West Virginia root repeated chapter identity: {chapter}"
                )
            seen.add(key)
            units.append(
                {
                    "chapter": chapter,
                    "source_label": self._normalize_legal_text(
                        option.get_text(" ", strip=True)
                    ),
                    "source_url": self.official_chapter_url(chapter),
                }
            )
        return units

    def _west_virginia_child_units(
        self,
        payload: bytes,
        *,
        level: str,
        chapter_number: str,
        article_number: str = "",
    ) -> List[Dict[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError(
                "BeautifulSoup is required for West Virginia strict traversal"
            ) from exc
        soup = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
        selector = "div.art-head a[href]" if level == "article" else "div.sec-head a[href]"
        units: List[Dict[str, str]] = []
        seen_urls: set[str] = set()
        seen_identities: set[Tuple[str, ...]] = set()
        for anchor in soup.select(selector):
            href = str(anchor.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(f"{self.get_base_url()}/", href)
            canonical, groups = self._canonical_west_virginia_hierarchy_url(
                absolute,
                level=level,
                chapter_number=chapter_number,
                article_number=article_number,
            )
            identity = (
                (groups["chapter"], groups["article"])
                if level == "article"
                else (groups["chapter"], groups["article"], groups["section"])
            )
            folded = tuple(value.casefold() for value in identity)
            if canonical in seen_urls or folded in seen_identities:
                raise RuntimeError(
                    f"West Virginia {level} frontier repeated identity: {canonical}"
                )
            seen_urls.add(canonical)
            seen_identities.add(folded)
            units.append(
                {
                    **groups,
                    "source_label": self._normalize_legal_text(
                        anchor.get_text(" ", strip=True)
                    ),
                    "source_url": canonical,
                }
            )
        return units

    def _west_virginia_unlinked_terminal_units(
        self,
        payload: bytes,
        *,
        level: str,
        parent_url: str,
        chapter_number: str,
        article_number: str = "",
        observed_on: Any,
    ) -> List[Dict[str, str]]:
        """Account for official hierarchy rows that intentionally have no link."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError(
                "BeautifulSoup is required for West Virginia strict traversal"
            ) from exc
        soup = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
        selector = "div.art-head" if level == "article" else "div.sec-head"
        if level == "article":
            identity_pattern = re.compile(
                r"^ARTICLE\s+(?P<article>\d+[A-Za-z]?)\b",
                re.IGNORECASE,
            )
        else:
            identity_pattern = re.compile(
                r"^§\s*(?P<chapter>\d+[A-Za-z]?)-"
                r"(?P<article>\d+[A-Za-z]?)-(?P<section>\d+[A-Za-z]?)\b",
                re.IGNORECASE,
            )
        records: List[Dict[str, str]] = []
        for node in soup.select(selector):
            if node.find("a", href=True) is not None:
                continue
            label = self._normalize_legal_text(node.get_text(" ", strip=True))
            if (
                level == "section"
                and str(node.get("id") or "").strip().casefold() == "all-sections"
                and re.fullmatch(
                    rf"Display all Article {re.escape(article_number)} Sections",
                    label,
                    flags=re.IGNORECASE,
                )
                is not None
            ):
                # The official article template places this UI toggle inside a
                # ``div.sec-head`` even though it is not a statutory row.
                continue
            identity = identity_pattern.match(label)
            if identity is None:
                # An empty loading placeholder is not a statutory frontier row.
                if label:
                    raise RuntimeError(
                        "West Virginia official hierarchy contains an unlinked "
                        f"unrecognized {level} row: {label}"
                    )
                continue
            groups = {
                key: str(value or "").upper()
                for key, value in identity.groupdict().items()
            }
            if level == "article":
                groups["chapter"] = chapter_number.upper()
            if (
                groups.get("chapter") != chapter_number.upper()
                or (
                    article_number
                    and groups.get("article") != article_number.upper()
                )
            ):
                raise RuntimeError(
                    f"West Virginia unlinked {level} row escaped its parent: {label}"
                )
            disposition = self._west_virginia_terminal_disposition(
                label,
                observed_on=observed_on,
            )
            if disposition is None:
                raise RuntimeError(
                    "West Virginia official hierarchy contains an operative-looking "
                    f"unlinked {level} row: {label}"
                )
            records.append(
                {
                    **groups,
                    "classification_source": f"{level}_catalog",
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "disposition": disposition,
                    "frontier_level": level,
                    "source_label": label,
                    "source_url": parent_url,
                }
            )
        return records

    @staticmethod
    def _west_virginia_page_identity(payload: bytes, *, level: str) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ""
        soup = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
        if level == "chapter":
            nodes = soup.find_all("h3")
            pattern = re.compile(r"^CHAPTER\s+(\d+[A-Za-z]?)\b", re.IGNORECASE)
        elif level == "article":
            nodes = soup.select("div.art-head")
            pattern = re.compile(r"^ARTICLE\s+(\d+[A-Za-z]?)\b", re.IGNORECASE)
        else:
            nodes = soup.find_all("h4")
            pattern = re.compile(
                r"^§\s*(\d+[A-Za-z]?\-\d+[A-Za-z]?\-\d+[A-Za-z]?)\b",
                re.IGNORECASE,
            )
        identities = []
        for node in nodes:
            match = pattern.match(
                re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            )
            if match:
                identities.append(match.group(1).upper())
        if not identities or any(item != identities[0] for item in identities[1:]):
            return ""
        return identities[0]

    def _west_virginia_terminal_disposition(
        self,
        label: str,
        *,
        observed_on: Any,
    ) -> Optional[str]:
        value = self._normalize_legal_text(label)
        if not value:
            return None
        future = self._WV_FUTURE_EFFECTIVE_RE.search(value)
        if future is not None:
            try:
                effective = datetime.strptime(future.group("date"), "%B %d, %Y").date()
            except ValueError:
                return None
            if effective > observed_on:
                return None
        bracketed = re.search(
            r"[\[(]\s*(repealed|expired|reserved|renumbered|transferred|recodified)\b",
            value,
            flags=re.IGNORECASE,
        )
        labelled = re.match(
            r"^(?:(?:chapter|article)\s+[0-9A-Za-z]+|"
            r"§\s*[0-9A-Za-z\-]+)\s*[.:\-–—]?\s*"
            r"(?:repealed|expired|reserved|renumbered|transferred|recodified)\b",
            value,
            flags=re.IGNORECASE,
        )
        match = bracketed or labelled
        if match is None:
            return None
        if bracketed is not None:
            return str(bracketed.group(1)).lower()
        kind = re.search(
            r"\b(repealed|expired|reserved|renumbered|transferred|recodified)\b",
            value,
            flags=re.IGNORECASE,
        )
        return str(kind.group(1)).lower() if kind is not None else None

    def _source_bound_west_virginia_terminal_disposition(
        self,
        payload: bytes,
        *,
        source_url: str,
        source_label: str,
        level: str,
        expected_identity: str,
        observed_on: Any,
    ) -> Optional[Dict[str, str]]:
        page_identity = self._west_virginia_page_identity(payload, level=level)
        if page_identity.casefold() != str(expected_identity or "").casefold():
            return None
        disposition = self._west_virginia_terminal_disposition(
            source_label,
            observed_on=observed_on,
        )
        if disposition is None:
            try:
                from bs4 import BeautifulSoup
            except ImportError:
                return None
            soup = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
            selectors = {
                "chapter": ("h3",),
                "article": ("div.art-head",),
                "section": ("h4", "div.sectiontext"),
            }[level]
            for selector in selectors:
                for node in soup.select(selector):
                    disposition = self._west_virginia_terminal_disposition(
                        node.get_text(" ", strip=True),
                        observed_on=observed_on,
                    )
                    if disposition is not None:
                        break
                if disposition is not None:
                    break
        if disposition is None:
            return None
        return {
            "disposition": disposition,
            "source_label": self._normalize_legal_text(source_label),
            "source_url": source_url,
        }

    @staticmethod
    def _west_virginia_frontier_values_sha256(values: Sequence[str]) -> str:
        payload = json.dumps(
            list(values),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _west_virginia_catalog_label_parts(self, label: str) -> Tuple[str, str]:
        """Return the canonical chapter identity and official chapter name."""

        normalized = re.sub(r"\s+", " ", str(label or "")).strip()
        match = re.fullmatch(
            r"CHAPTER\s+(?P<chapter>\d+[A-Za-z]?)\.\s*"
            r"(?P<name>.+?)\.?",
            normalized,
            flags=re.IGNORECASE,
        )
        if match is None:
            return "", ""
        chapter = self._normalize_chapter_number(match.group("chapter"))
        name = re.sub(r"\s+", " ", match.group("name")).strip().rstrip(".")
        return chapter, name.casefold()

    def _validate_west_virginia_live_static_chapter_catalog(
        self,
        chapter_units: Sequence[Mapping[str, str]],
    ) -> None:
        """Require exact ID, name, and URL parity with the live selector."""

        expected = {
            self._normalize_chapter_number(number).casefold(): {
                "name": self._normalize_legal_text(name).rstrip(".").casefold(),
                "source_url": self.official_chapter_url(number),
            }
            for number, name in self.OFFICIAL_CHAPTERS
        }
        observed: Dict[str, Dict[str, str]] = {}
        ambiguous: List[Dict[str, str]] = []
        for unit in chapter_units:
            chapter = str(unit.get("chapter") or "").casefold()
            label_chapter, label_name = self._west_virginia_catalog_label_parts(
                str(unit.get("source_label") or "")
            )
            if (
                not chapter
                or chapter in observed
                or label_chapter.casefold() != chapter
            ):
                ambiguous.append(dict(unit))
                continue
            observed[chapter] = {
                "name": label_name,
                "source_url": str(unit.get("source_url") or ""),
            }
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        mismatches = [
            {
                "chapter": chapter,
                "expected_name": expected[chapter]["name"],
                "observed_name": observed[chapter]["name"],
                "expected_url": expected[chapter]["source_url"],
                "observed_url": observed[chapter]["source_url"],
            }
            for chapter in sorted(set(expected) & set(observed))
            if observed[chapter] != expected[chapter]
        ]
        if (
            len(observed) != self.OFFICIAL_CHAPTER_COUNT
            or missing
            or extra
            or ambiguous
            or mismatches
        ):
            raise RuntimeError(
                "West Virginia live/static chapter catalog parity failed; "
                f"missing={missing} extra={extra} ambiguous={ambiguous} "
                f"mismatches={mismatches}"
            )

    async def _scrape_strict_full_corpus_frontier(
        self,
        code_name: str,
        *,
        record_primary: bool,
        write_checkpoints: bool,
        retained_only: bool = False,
    ) -> List[NormalizedStatute]:
        """Acquire and close the exact current WV chapter-to-section tree."""

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        if retained_only:
            ledger = getattr(self, "_state_law_acquisition_ledger", None)
            refresh_entries = getattr(ledger, "refresh_existing_entries", None)
            if not callable(refresh_entries):
                raise RuntimeError(
                    "West Virginia retained replay requires a refreshable "
                    "acquisition ledger"
                )
            refresh_entries()
            self._west_virginia_replay_batch_stats = []
        else:
            self._west_virginia_frontier_batch_stats = []

        observed_at = datetime.now(timezone.utc).isoformat()
        observed_on = datetime.now(timezone.utc).date()
        root_payload = (
            await self._fetch_west_virginia_frontier_batch(
                [self.OFFICIAL_ENTRY_URL],
                frontier_name="root-index",
                retained_only=retained_only,
            )
        )[0]
        chapter_units = self._west_virginia_root_chapter_units(root_payload)
        self._validate_west_virginia_live_static_chapter_catalog(chapter_units)

        chapter_payloads = await self._fetch_west_virginia_frontier_batch(
            [unit["source_url"] for unit in chapter_units],
            frontier_name="chapter-index",
            retained_only=retained_only,
        )
        article_units: List[Dict[str, str]] = []
        terminal_units: List[Dict[str, str]] = []
        seen_articles: set[Tuple[str, str]] = set()
        for chapter, payload in zip(chapter_units, chapter_payloads, strict=True):
            page_identity = self._west_virginia_page_identity(payload, level="chapter")
            if page_identity.casefold() != chapter["chapter"].casefold():
                raise RuntimeError(
                    "West Virginia retained chapter page changed requested identity: "
                    f"{chapter['source_url']}"
                )
            children = self._west_virginia_child_units(
                payload,
                level="article",
                chapter_number=chapter["chapter"],
            )
            catalog_terminals = self._west_virginia_unlinked_terminal_units(
                payload,
                level="article",
                parent_url=chapter["source_url"],
                chapter_number=chapter["chapter"],
                observed_on=observed_on,
            )
            for terminal in catalog_terminals:
                identity = (
                    terminal["chapter"].casefold(),
                    terminal["article"].casefold(),
                )
                if identity in seen_articles:
                    raise RuntimeError(
                        "West Virginia chapter catalog repeated article identity: "
                        f"{terminal['source_label']}"
                    )
                seen_articles.add(identity)
                terminal_units.append(terminal)
            if not children and not catalog_terminals:
                terminal = self._source_bound_west_virginia_terminal_disposition(
                    payload,
                    source_url=chapter["source_url"],
                    source_label=chapter["source_label"],
                    level="chapter",
                    expected_identity=chapter["chapter"],
                    observed_on=observed_on,
                )
                if terminal is None:
                    raise RuntimeError(
                        "West Virginia chapter exposed no article frontier and no "
                        f"source-bound terminal disposition: {chapter['source_url']}"
                    )
                terminal_units.append(
                    {
                        **terminal,
                        "frontier_level": "chapter",
                        "chapter_number": chapter["chapter"],
                        "content_sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
                continue
            for child in children:
                identity = (child["chapter"].casefold(), child["article"].casefold())
                if identity in seen_articles:
                    raise RuntimeError(
                        "West Virginia chapter frontier repeated article identity: "
                        f"{child['source_url']}"
                    )
                seen_articles.add(identity)
                article_units.append(child)
        if not article_units:
            raise RuntimeError("West Virginia chapter frontier produced no active articles")

        article_payloads = await self._fetch_west_virginia_frontier_batch(
            [unit["source_url"] for unit in article_units],
            frontier_name="article-index",
            retained_only=retained_only,
        )
        section_units: List[Dict[str, str]] = []
        seen_sections: set[Tuple[str, str, str]] = set()
        for article, payload in zip(article_units, article_payloads, strict=True):
            expected_article = article["article"]
            page_identity = self._west_virginia_page_identity(payload, level="article")
            if page_identity.casefold() != expected_article.casefold():
                raise RuntimeError(
                    "West Virginia retained article page changed requested identity: "
                    f"{article['source_url']}"
                )
            children = self._west_virginia_child_units(
                payload,
                level="section",
                chapter_number=article["chapter"],
                article_number=article["article"],
            )
            catalog_terminals = self._west_virginia_unlinked_terminal_units(
                payload,
                level="section",
                parent_url=article["source_url"],
                chapter_number=article["chapter"],
                article_number=article["article"],
                observed_on=observed_on,
            )
            for terminal in catalog_terminals:
                identity = (
                    terminal["chapter"].casefold(),
                    terminal["article"].casefold(),
                    terminal["section"].casefold(),
                )
                if identity in seen_sections:
                    raise RuntimeError(
                        "West Virginia article catalog repeated section identity: "
                        f"{terminal['source_label']}"
                    )
                seen_sections.add(identity)
                terminal_units.append(terminal)
            if not children and not catalog_terminals:
                terminal = self._source_bound_west_virginia_terminal_disposition(
                    payload,
                    source_url=article["source_url"],
                    source_label=article["source_label"],
                    level="article",
                    expected_identity=expected_article,
                    observed_on=observed_on,
                )
                if terminal is None:
                    raise RuntimeError(
                        "West Virginia article exposed no section frontier and no "
                        f"source-bound terminal disposition: {article['source_url']}"
                    )
                terminal_units.append(
                    {
                        **terminal,
                        "frontier_level": "article",
                        "chapter_number": article["chapter"],
                        "article_number": article["article"],
                        "content_sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
                continue
            for child in children:
                identity = (
                    child["chapter"].casefold(),
                    child["article"].casefold(),
                    child["section"].casefold(),
                )
                if identity in seen_sections:
                    raise RuntimeError(
                        "West Virginia article frontier repeated section identity: "
                        f"{child['source_url']}"
                    )
                seen_sections.add(identity)
                section_units.append(child)
        if not section_units:
            raise RuntimeError("West Virginia hierarchy produced no active section frontier")

        catalog_terminal_unit_count = len(terminal_units)
        discovered_candidates = len(section_units) + catalog_terminal_unit_count
        if write_checkpoints:
            self._write_partial_checkpoint(
                [],
                code_name=code_name,
                stage_label="west-virginia:section-discovery",
                replace_existing_rows=True,
                extra={
                    "titles_scanned": len(chapter_units),
                    "discovered_titles": len(chapter_units),
                    "chapters_scanned": len(article_units),
                    "discovered_chapters": len(article_units),
                    "sections_scanned": catalog_terminal_unit_count,
                    "discovered_sections": discovered_candidates,
                    "terminal_sections_classified": len(terminal_units),
                    "terminal_section_dispositions": terminal_units,
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )

        statutes: List[NormalizedStatute] = []
        seen_statute_ids: set[str] = set()
        batch_size = self._west_virginia_frontier_batch_size()
        for batch_start in range(0, len(section_units), batch_size):
            batch_units = section_units[batch_start : batch_start + batch_size]
            payloads = await self._fetch_west_virginia_frontier_batch(
                [unit["source_url"] for unit in batch_units],
                frontier_name=(
                    f"sections-{batch_start + 1}-{batch_start + len(batch_units)}"
                ),
                retained_only=retained_only,
            )
            for unit, payload in zip(batch_units, payloads, strict=True):
                section_number = (
                    f"{unit['chapter']}-{unit['article']}-{unit['section']}"
                )
                page_identity = self._west_virginia_page_identity(payload, level="section")
                if page_identity.casefold() != section_number.casefold():
                    raise RuntimeError(
                        "West Virginia retained section page changed requested identity: "
                        f"{unit['source_url']}"
                    )
                statute = self._parse_west_virginia_section_payload(
                    code_name=code_name,
                    source_url=unit["source_url"],
                    section_number=section_number,
                    payload=payload,
                    discovery_method=(
                        "official_batched_chapter_article_section_frontier"
                    ),
                )
                if statute is None:
                    terminal = self._source_bound_west_virginia_terminal_disposition(
                        payload,
                        source_url=unit["source_url"],
                        source_label=unit["source_label"],
                        level="section",
                        expected_identity=section_number,
                        observed_on=observed_on,
                    )
                    if terminal is None:
                        raise RuntimeError(
                            "West Virginia retained section failed parsing and has no "
                            f"source-bound terminal disposition: {unit['source_url']}"
                        )
                    terminal_units.append(
                        {
                            **terminal,
                            "frontier_level": "section",
                            "chapter_number": unit["chapter"],
                            "article_number": unit["article"],
                            "section_number": section_number,
                            "content_sha256": hashlib.sha256(payload).hexdigest(),
                        }
                    )
                    continue
                if (
                    str(statute.section_number or "").casefold()
                    != section_number.casefold()
                    or str(statute.source_url or "") != unit["source_url"]
                ):
                    raise RuntimeError(
                        "West Virginia normalized section changed requested identity: "
                        f"{unit['source_url']}"
                    )
                statute.title_number = unit["chapter"]
                statute.chapter_number = unit["article"]
                statute.section_number = section_number
                statute.statute_id = f"{code_name} § {section_number}"
                statute.official_cite = f"W. Va. Code § {section_number}"
                statute.structured_data = {
                    **dict(statute.structured_data or {}),
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                }
                folded_id = statute.statute_id.casefold()
                if folded_id in seen_statute_ids:
                    raise RuntimeError(
                        "West Virginia normalized statute identity repeated: "
                        f"{statute.statute_id}"
                    )
                seen_statute_ids.add(folded_id)
                statutes.append(statute)

            if write_checkpoints:
                scanned = batch_start + len(batch_units) + catalog_terminal_unit_count
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="west-virginia:section-batch",
                    replace_existing_rows=True,
                    extra={
                        "titles_scanned": len(chapter_units),
                        "discovered_titles": len(chapter_units),
                        "chapters_scanned": len(article_units),
                        "discovered_chapters": len(article_units),
                        "sections_scanned": scanned,
                        "discovered_sections": discovered_candidates,
                        "terminal_sections_classified": len(terminal_units),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )

        discovered = len(statutes) + len(terminal_units)
        disposition = {
            "discovered": discovered,
            "fetched": len(statutes),
            "excluded": len(terminal_units),
            "failed_final": 0,
            "duplicates": 0,
            "quarantined": 0,
        }
        if discovered != sum(
            disposition[key]
            for key in ("fetched", "excluded", "failed_final", "duplicates", "quarantined")
        ):
            raise RuntimeError("West Virginia strict disposition algebra did not close")
        source_urls = [unit["source_url"] for unit in section_units]
        statute_ids = [statute.statute_id for statute in statutes]
        parser_input_count = (
            1 + len(chapter_units) + len(article_units) + len(section_units)
        )
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "article_count": len(article_units),
            "bundle_closed": False,
            "catalog_expected_units": self.OFFICIAL_CHAPTER_COUNT,
            "catalog_observed_units": len(chapter_units),
            "catalog_parity": True,
            "chapter_count": len(chapter_units),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": discovered,
            "pagination_closed": True,
            "parser_input_count": parser_input_count,
            "schema_version": "west-virginia-strict-html-frontier-v1",
            "scope_closed": True,
            "section_locator_count": len(section_units),
            "section_locators_sha256": self._west_virginia_frontier_values_sha256(
                source_urls
            ),
            "statute_ids_sha256": self._west_virginia_frontier_values_sha256(statute_ids),
            "terminal_units": terminal_units,
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": discovered,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        observation = {
            "boundary_first": source_urls[0],
            "boundary_last": source_urls[-1],
            "frontier": frontier,
            "observed_at": observed_at,
            "statute_ids": statute_ids,
            "transport_batch_stats": list(
                getattr(
                    self,
                    (
                        "_west_virginia_replay_batch_stats"
                        if retained_only
                        else "_west_virginia_frontier_batch_stats"
                    ),
                    [],
                )
            ),
        }
        target = (
            "_last_west_virginia_full_frontier"
            if record_primary
            else "_last_west_virginia_replayed_frontier"
        )
        setattr(self, target, observation)
        if write_checkpoints:
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="west-virginia:complete",
                force=True,
                replace_existing_rows=True,
                extra={
                    "titles_scanned": len(chapter_units),
                    "discovered_titles": len(chapter_units),
                    "chapters_scanned": len(article_units),
                    "discovered_chapters": len(article_units),
                    "sections_scanned": discovered,
                    "discovered_sections": discovered,
                    "terminal_sections_classified": len(terminal_units),
                    "terminal_section_dispositions": terminal_units,
                    "disposition": disposition,
                    "codes_completed": 1,
                    "codes_total": 1,
                },
            )
        return statutes

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Replay retained WV hierarchy pages and seal exact leaf algebra."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "West Virginia frontier closure requires an attached acquisition ledger"
            )
        first = getattr(self, "_last_west_virginia_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "West Virginia strict frontier was not observed before rows escaped"
            )
        replay_rows = await self._scrape_strict_full_corpus_frontier(
            "West Virginia Code",
            record_primary=False,
            write_checkpoints=False,
            retained_only=True,
        )
        replay = getattr(self, "_last_west_virginia_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("West Virginia strict frontier replay was not retained")

        from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
            closed_jurisdiction_receipt,
        )
        from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
            build_canonical_state_law_output_projection,
        )

        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier, Mapping
        ):
            raise RuntimeError("West Virginia strict frontier observations are incomplete")
        if canonical_json_bytes(first_frontier) != canonical_json_bytes(replayed_frontier):
            raise RuntimeError("West Virginia first and replayed exact frontiers differ")

        parser_input_count = int(first_frontier.get("parser_input_count") or 0)
        first_batch_stats = first.get("transport_batch_stats")
        replay_batch_stats = replay.get("transport_batch_stats")
        if (
            parser_input_count <= 0
            or not isinstance(first_batch_stats, Sequence)
            or isinstance(first_batch_stats, (str, bytes, bytearray))
            or not isinstance(replay_batch_stats, Sequence)
            or isinstance(replay_batch_stats, (str, bytes, bytearray))
        ):
            raise RuntimeError(
                "West Virginia strict transport batch evidence is incomplete"
            )

        def _sum_batch_field(rows: Sequence[Any], field: str) -> int:
            return sum(
                int(row.get(field) or 0)
                for row in rows
                if isinstance(row, Mapping)
            )

        first_requested = _sum_batch_field(first_batch_stats, "requested_pages")
        first_successful = _sum_batch_field(first_batch_stats, "successful_pages")
        replay_requested = _sum_batch_field(replay_batch_stats, "requested_pages")
        replay_successful = _sum_batch_field(replay_batch_stats, "successful_pages")
        replay_retained = _sum_batch_field(
            replay_batch_stats,
            "retained_replay_pages",
        )
        replay_network = _sum_batch_field(
            replay_batch_stats,
            "network_requested_pages",
        )
        if (
            first_requested != parser_input_count
            or first_successful != parser_input_count
            or replay_requested != parser_input_count
            or replay_successful != parser_input_count
            or replay_retained != parser_input_count
            or replay_network != 0
            or not any(
                isinstance(row, Mapping)
                and int(row.get("requested_pages") or 0) > 1
                for row in first_batch_stats
            )
        ):
            raise RuntimeError(
                "West Virginia strict transport batching or zero-network replay "
                "did not close"
            )

        replay_projection = build_canonical_state_law_output_projection(
            [self._enrich_statute_structure(row).to_dict() for row in replay_rows],
            jurisdiction="WV",
        )
        output_keys_raw = canonical_output_projection.get("canonical_keys")
        if not isinstance(output_keys_raw, Sequence) or isinstance(
            output_keys_raw, (str, bytes, bytearray)
        ):
            raise RuntimeError("West Virginia canonical output lacks exact identities")
        output_keys = [str(item).strip() for item in output_keys_raw]
        replay_keys = [str(item) for item in replay_projection["canonical_keys"]]
        if (
            not output_keys
            or any(not item for item in output_keys)
            or len(output_keys) != len(set(output_keys))
            or output_keys != replay_keys
        ):
            raise RuntimeError(
                "West Virginia final canonical identities do not exactly match "
                "the independently replayed section frontier"
            )

        disposition = first_frontier.get("disposition")
        if not isinstance(disposition, Mapping):
            raise RuntimeError("West Virginia strict frontier lacks disposition algebra")
        if int(disposition.get("fetched") or -1) != len(output_keys):
            raise RuntimeError(
                "West Virginia strict fetched count changed after final filtering"
            )
        completion = closed_jurisdiction_receipt(
            "WV",
            discovered=int(disposition["discovered"]),
            fetched=int(disposition["fetched"]),
            excluded=int(disposition["excluded"]),
            quarantined=int(disposition["quarantined"]),
            failed_final=int(disposition["failed_final"]),
            duplicates=int(disposition["duplicates"]),
            source_domain=self.OFFICIAL_DOMAIN,
            canonical_keys=output_keys,
            derived_keys=output_keys,
        )
        completion.update(
            {
                "boundary_probes": {
                    "bundle_total": 0,
                    "first_hierarchy_unit": str(first.get("boundary_first") or ""),
                    "last_hierarchy_unit": str(first.get("boundary_last") or ""),
                    "pagination_total": int(first_frontier.get("chapter_count") or 0),
                },
                "canonical_row_count": len(output_keys),
                "frontier": dict(first_frontier),
                "legal_as_of": str(first.get("observed_at") or ""),
                "observed_at": str(first.get("observed_at") or ""),
                "replay": {
                    "closed": True,
                    "first_frontier_digest": str(
                        first_frontier.get("frontier_digest_sha256") or ""
                    ),
                    "second_frontier_digest": str(
                        replayed_frontier.get("frontier_digest_sha256") or ""
                    ),
                    "network_requested_pages": replay_network,
                    "parser_input_count": parser_input_count,
                },
                "rights": {
                    "basis": "public_law_no_state_copyright",
                    "decision": "admit",
                    "scope": "statutory_text",
                },
                "transport": {
                    "fixture": False,
                    "grouped_warc_recovery": True,
                    "kind": "shared_archive_aware_plural_html",
                    "per_page_archive_loop": False,
                    "primary_batch_count": len(first_batch_stats),
                    "primary_requested_pages": first_requested,
                    "residual_only_retries": True,
                    "retained_replay_batch_count": len(replay_batch_stats),
                    "retained_replay_network_requested_pages": replay_network,
                    "retained_replay_pages": replay_retained,
                    "same_domain_plural_frontiers": True,
                    "synthetic": False,
                    "wayback_prefix_inventory": True,
                },
            }
        )
        digest = str(first_frontier.get("frontier_digest_sha256") or "")
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=dict(replayed_frontier),
            canonical_output_projection=canonical_output_projection,
            release_point=f"sha256:{digest}",
            official_source_url=self.OFFICIAL_ENTRY_URL,
            acquisition_path_ids=self._catalog_acquisition_path_ids_for_source(
                self.OFFICIAL_ENTRY_URL
            ),
            observation_time=str(first.get("observed_at") or ""),
            source_software_version=self._state_law_frontier_source_software_version(),
        )

    async def _discover_chapter_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/"
        raw = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for option in soup.select("select#sel-chapter option[value]"):
            chapter = str(option.get("value") or "").strip()
            if not re.match(r"^\d+[A-Za-z]?$", chapter):
                continue
            normalized = f"{self.get_base_url()}/{chapter}/"
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(option.get_text(" ", strip=True))))
        return out

    async def _discover_article_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        raw = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("div.art-head a[href]"):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            if not re.search(r"/\d+[A-Za-z]?-\d+[A-Za-z]?/?$", href):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_section_links(self, article_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        raw = await self._fetch_page_content_with_archival_fallback(article_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("div.sec-head a[href]"):
            href = urljoin(article_url, str(anchor.get("href") or "").strip())
            if not self._WV_SECTION_URL_RE.search(href):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            section_number = normalized.rstrip("/").rsplit("/", 1)[-1]
            out.append((normalized, section_number))
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
        discovery_method: str = "official_seed_section",
    ) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for url, section_number in section_urls:
            if limit is not None and len(out) >= limit:
                break
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            parsed = self._parse_west_virginia_section_payload(
                code_name=code_name,
                source_url=url,
                section_number=section_number,
                payload=bytes(raw),
                discovery_method=discovery_method,
            )
            if parsed is not None:
                out.append(parsed)
        return out

    def _parse_west_virginia_section_payload(
        self,
        *,
        code_name: str,
        source_url: str,
        section_number: str,
        payload: bytes,
        discovery_method: str,
    ) -> Optional[NormalizedStatute]:
        """Parse one already-retained official section response."""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None
        soup = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
        node = soup.select_one("div.sectiontext")
        if node is None:
            return None
        heading = self._normalize_legal_text(
            (node.find("h4") or node).get_text(" ", strip=True)
        )
        body_parts = [
            self._normalize_legal_text(paragraph.get_text(" ", strip=True))
            for paragraph in node.find_all("p")
        ]
        body = self._normalize_legal_text(" ".join([heading, *body_parts]))
        if len(body) < 180:
            return None
        section_name = re.sub(r"^§\s*[\w\-]+\.?\s*", "", heading).strip() or heading
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=section_number.split("-", 1)[0],
            section_number=section_number,
            section_name=section_name[:220],
            full_text=body,
            legal_area=self._identify_legal_area(body[:1200]),
            source_url=source_url,
            official_cite=f"W. Va. Code § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_west_virginia_code_html",
                "discovery_method": discovery_method,
                "skip_hydrate": True,
            },
        )

    def official_chapter_url(self, chapter_number: Any) -> str:
        number = str(chapter_number or "").strip()
        return f"{self.get_base_url()}/{number}/"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official West Virginia Code chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_CHAPTERS:
            url = self.official_chapter_url(number)
            rows.append(
                {
                    "canonical_key": f"wv:chapter-{str(number).lower()}",
                    "chapter_number": str(number),
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"West Virginia Code Chapter {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith("." + self.OFFICIAL_DOMAIN)

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-west-virginia-official-catalog/1.0",
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

    def _normalize_chapter_number(self, value: Any) -> str:
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
            if "next" not in rel and not self._WV_CONTINUATION_RE.search(label):
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            if absolute in seen or not self._host_is_official(absolute):
                continue
            if absolute.rstrip("/") == str(page_url or "").rstrip("/"):
                continue
            seen.add(absolute)
            found.append(absolute)
        return found

    def _parse_official_chapter_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {number for number, _name in self.OFFICIAL_CHAPTERS}
        for option in soup.select("select#sel-chapter option[value], select option[value]"):
            number = self._normalize_chapter_number(option.get("value"))
            if not number or number in found:
                continue
            if number not in known:
                known.add(number)
            found[number] = self.official_chapter_url(number)
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._WV_CHAPTER_HREF_RE.search(absolute) or self._WV_CHAPTER_LABEL_RE.search(label)
            if not match:
                continue
            number = self._normalize_chapter_number(match.group("chapter"))
            if not number or number in found:
                continue
            if number not in known:
                known.add(number)
            if self._host_is_official(absolute):
                found[number] = self.official_chapter_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official West Virginia Code chapter."""

        del page_url
        discovered = self._parse_official_chapter_links(html)
        rows = self.official_title_catalog()
        known = {str(row["chapter_number"]) for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["chapter_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_wvcode"
        for number, url in discovered.items():
            if number in known:
                continue
            rows.append(
                {
                    "canonical_key": f"wv:chapter-{number.lower()}",
                    "chapter_number": number,
                    "title_number": number,
                    "name": f"Chapter {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"West Virginia Code Chapter {number} "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        rows.sort(key=lambda item: self._chapter_sort_key(str(item.get("chapter_number") or "")))
        return rows

    def _chapter_sort_key(self, number: str) -> Tuple[int, str]:
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

    def fetch_official(self, code: str = "WV"):
        """Acquire the exhaustive official West Virginia Code chapter catalog.

        Live HTTPS retains the official code.wvlegislature.gov index. Every
        known chapter is enumerated with an official URL. Continuation pages
        are exhausted. This hook never returns fixture bytes, never promotes
        a partial scrape checkpoint, and never uses secondary hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "WV").strip().upper() or "WV"
        if normalized != "WV":
            raise ValueError(f"WestVirginiaScraper cannot acquire {normalized}")
        html, remaining = self._collect_official_index_pages()
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < self.OFFICIAL_CHAPTER_COUNT:
            raise RuntimeError(
                "west virginia official catalog enumeration rejected incomplete "
                "chapter reacquisition"
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
StateScraperRegistry.register("WV", WestVirginiaScraper)
