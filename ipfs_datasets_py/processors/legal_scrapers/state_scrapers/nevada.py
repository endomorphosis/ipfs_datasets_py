"""Scraper for Nevada state laws.

This module contains the scraper for Nevada statutes from the official state legislative website.
"""

import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union
from urllib.parse import urljoin, urlparse
from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StateLawPageMultiFetchResult,
)
from .registry import StateScraperRegistry


class NevadaScraper(BaseStateScraper):
    """Scraper for Nevada state laws from https://www.leg.state.nv.us"""

    OFFICIAL_DOMAIN = "www.leg.state.nv.us"
    OFFICIAL_ENTRY_PATH = "/NRS/"
    OFFICIAL_ENTRY_URL = "https://www.leg.state.nv.us/NRS/"
    OFFICIAL_TITLE_COUNT = 59
    OFFICIAL_CHAPTER_FLOOR = 835
    MISSING_LINK_DISPOSITION = "missing_official_source_link"
    LINKLESS_BUCKET_DISPOSITION = "linkless_bucket_row"
    last_official_quarantines: List[Dict[str, str]] = []
    _NRS_CHAPTER_HREF_RE = re.compile(r"^NRS-\d{3}[A-Z]?\.html$", re.IGNORECASE)
    _NRS_CHAPTER_ABS_RE = re.compile(
        r"/NRS/NRS-(?P<chapter>\d{1,4}[A-Z]?)\.html",
        re.IGNORECASE,
    )
    _NRS_SECTION_NUMBER_RE = re.compile(r"^\d+[A-Z]?\.\d+(?:\.\d+)?[A-Z]?$")
    _NRS_REF_RE = re.compile(
        r"\b(?:NRS[-\s]*)?(?P<chapter>\d{1,4}[A-Z]?)(?:\.(?P<section>\d+(?:\.\d+)*[A-Z]?))?\b",
        re.IGNORECASE,
    )
    _NRS_LINKLESS_LABEL_RE = re.compile(
        r"\b(?:NRS|Title\s+\d+|Chapter\s+\d+)",
        re.IGNORECASE,
    )
    _SECONDARY_HOST_MARKERS = (
        "justia.com",
        "findlaw.com",
        "unicourt.github.io",
        "law.cornell.edu",
    )
    OFFICIAL_TITLE_FIRST_CHAPTER = {
        1: "1", 2: "7", 3: "28", 4: "47", 5: "62A", 6: "63", 7: "75", 8: "97",
        9: "106", 10: "123", 11: "132", 12: "159", 13: "169", 14: "193",
        15: "209", 16: "217", 17: "231", 18: "240", 19: "244", 20: "277",
        21: "281", 22: "293", 23: "313", 24: "328", 25: "332", 26: "341",
        27: "353", 28: "361", 29: "378", 30: "381", 31: "386", 32: "389",
        33: "403", 34: "412", 35: "422", 36: "439", 37: "463", 38: "469",
        39: "475", 40: "481", 41: "488", 42: "493", 43: "497", 44: "512",
        45: "527", 46: "532", 47: "552", 48: "563", 49: "573", 50: "590",
        51: "598", 52: "607", 53: "623", 54: "657", 55: "679A", 56: "701",
        57: "706", 58: "714", 59: "722",
    }
    OFFICIAL_TITLE_NAMES = {
        1: "State Judicial Department",
        2: "Civil Practice",
        3: "Remedies; Special Actions and Proceedings",
        4: "Witnesses and Evidence",
        5: "Juvenile Justice",
        6: "Children",
        7: "Business Associations; Securities; Commodities",
        8: "Commercial Instruments and Transactions",
        9: "Security Instruments of Public Utilities; Mortgages; Deeds of Trust; Other Liens",
        10: "Property Rights and Transactions",
        11: "Domestic Relations",
        12: "Wills and Estates of Deceased Persons",
        13: "Guardianships; Conservatorships; Trusts",
        14: "Procedure in Criminal Cases",
        15: "Crimes and Punishments",
        16: "Correctional Institutions; Aid to Victims of Crime",
        17: "State Legislative Department",
        18: "State Executive Department",
        19: "Miscellaneous Matters Related to Government and Public Affairs",
        20: "Counties and Townships: Formation, Government and Officers",
        21: "Cities and Towns",
        22: "Cooperative Agreements by Public Agencies; Planning and Zoning",
        23: "Public Officers and Employees",
        24: "Elections",
        25: "Public Organizations for Community Service",
        26: "Public Lands",
        27: "Public Property and Purchasing",
        28: "Public Financial Administration",
        29: "Revenue and Taxation",
        30: "Public Borrowing and Obligations",
        31: "Public Financial Administration",
        32: "Education",
        33: "Highways; Roads; Bridges; Parks; Outdoor Recreation",
        34: "Military Affairs and Civil Emergencies",
        35: "Highways; Vehicles; Watercraft; Aviation",
        36: "Public Health and Safety",
        37: "Veterans; Privileges; Benefits",
        38: "Public Welfare",
        39: "Mental Health",
        40: "Public Health and Safety",
        41: "Gaming; Horse Racing; Sporting Events",
        42: "Agriculture",
        43: "Public Safety; Vehicles; Watercraft",
        44: "Aeronautics",
        45: "Wildlife",
        46: "Mines and Minerals",
        47: "Forestry; Fire Protection",
        48: "Water",
        49: "Agriculture",
        50: "Animals",
        51: "Food and Other Commodities",
        52: "Trade Regulations and Practices",
        53: "Labor and Industrial Relations",
        54: "Professions, Occupations and Businesses",
        55: "Banks and Related Organizations",
        56: "Insurance",
        57: "Other Financial Institutions",
        58: "Energy; Public Utilities and Similar Entities",
        59: "Electronic Records and Transactions",
    }

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind the sibling NRS chapter parser into retained closure identity."""

        from . import nevada_chapter

        return (nevada_chapter,)

    @staticmethod
    def _nevada_reports_sha256(reports: Sequence[Mapping[str, Any]]) -> str:
        payload = json.dumps(
            [dict(report) for report in reports],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def _nevada_chapter_urls_from_index_html(cls, html: str) -> List[str]:
        """Return the exact ordered chapter frontier published by the NRS root."""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        soup = BeautifulSoup(html or "", "html.parser")
        urls: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not cls._NRS_CHAPTER_HREF_RE.match(href):
                continue
            chapter_url = urljoin(cls.OFFICIAL_ENTRY_URL, href)
            if chapter_url in seen:
                continue
            seen.add(chapter_url)
            urls.append(chapter_url)
        return urls

    def _nevada_exact_frontier(
        self,
        *,
        catalog_report: Mapping[str, Any],
        chapter_reports: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Build exact root/chapter/temporal disposition algebra."""

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        catalog_digest = str(catalog_report.get("content_sha256") or "")
        catalog_url = str(catalog_report.get("source_url") or "")
        if (
            re.fullmatch(r"[0-9a-f]{64}", catalog_digest) is None
            or self._canonical_fetch_url(catalog_url)
            != self._canonical_fetch_url(self.OFFICIAL_ENTRY_URL)
        ):
            raise RuntimeError("Nevada exact root report is not source-bound")
        if int(catalog_report.get("chapter_count") or 0) != len(chapter_reports):
            raise RuntimeError("Nevada root and chapter membership do not reconcile")
        if len(chapter_reports) < self.OFFICIAL_CHAPTER_FLOOR:
            raise RuntimeError("Nevada exact chapter frontier regressed below its floor")

        source_urls = [
            str(report.get("source_url") or "") for report in chapter_reports
        ]
        page_identities = [
            str(report.get("chapter_identity") or "") for report in chapter_reports
        ]
        expected_urls_sha256 = self._nevada_reports_sha256(
            [{"source_url": value} for value in source_urls]
        )
        if (
            any(not value for value in source_urls)
            or len(source_urls) != len(set(source_urls))
            or any(not value for value in page_identities)
            or len(page_identities) != len(set(page_identities))
            or expected_urls_sha256
            != str(catalog_report.get("chapter_urls_sha256") or "")
        ):
            raise RuntimeError("Nevada exact chapter membership changed identity")

        totals: Counter[str] = Counter()
        legal_as_of_dates: set[str] = set()
        canonical_digests: List[str] = []
        for report in chapter_reports:
            if re.fullmatch(
                r"[0-9a-f]{64}", str(report.get("content_sha256") or "")
            ) is None or re.fullmatch(
                r"[0-9a-f]{64}",
                str(report.get("canonical_identities_sha256") or ""),
            ) is None:
                raise RuntimeError("Nevada chapter report lost exact source identity")
            values: Dict[str, int] = {}
            for field in (
                "canonical_identities",
                "excluded_variant_records",
                "operative_identities",
                "selected_multi_variant_identities",
                "selected_temporal_variants_excluded",
                "temporal_excluded_identities",
                "terminal_identities",
                "toc_variant_records",
            ):
                raw = report.get(field)
                if isinstance(raw, bool):
                    raise RuntimeError("Nevada chapter counts must be integers")
                try:
                    values[field] = int(raw)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"Nevada chapter report lacks {field}"
                    ) from exc
                if values[field] < 0:
                    raise RuntimeError("Nevada chapter counts cannot be negative")
                totals[field] += values[field]
            classified = (
                values["operative_identities"]
                + values["temporal_excluded_identities"]
                + values["terminal_identities"]
            )
            variant_records = (
                classified
                + values["selected_temporal_variants_excluded"]
                + values["excluded_variant_records"]
                - values["temporal_excluded_identities"]
            )
            if (
                values["canonical_identities"] != classified
                or values["toc_variant_records"] != variant_records
            ):
                raise RuntimeError(
                    "Nevada chapter temporal variants do not reconcile"
                )
            legal_as_of = str(report.get("source_observed_date") or "")
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", legal_as_of) is None:
                raise RuntimeError("Nevada chapter lacks a legal-as-of date")
            legal_as_of_dates.add(legal_as_of)
            canonical_digests.append(
                str(report.get("canonical_identities_sha256") or "")
            )

        if len(legal_as_of_dates) != 1:
            raise RuntimeError(
                "Nevada current corpus requires one coherent legal-as-of date"
            )
        disposition = {
            "discovered": totals["canonical_identities"],
            "fetched": totals["operative_identities"],
            "excluded": (
                totals["temporal_excluded_identities"]
                + totals["terminal_identities"]
            ),
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        }
        if disposition["discovered"] != (
            disposition["fetched"] + disposition["excluded"]
        ):
            raise RuntimeError("Nevada exact source disposition did not close")
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": False,
            "catalog_content_sha256": catalog_digest,
            "chapter_document_count": len(chapter_reports),
            "chapter_frontier_sha256": self._nevada_reports_sha256(
                chapter_reports
            ),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": totals["canonical_identities"],
            "legal_as_of": next(iter(legal_as_of_dates)),
            "operative_identity_count": totals["operative_identities"],
            "pagination_closed": True,
            "schema_version": "nevada-source-derived-temporal-frontier-v1",
            "scope_closed": True,
            "selected_multi_variant_identity_count": totals[
                "selected_multi_variant_identities"
            ],
            "selected_temporal_variants_excluded": totals[
                "selected_temporal_variants_excluded"
            ],
            "source_canonical_identities_sha256": self._nevada_reports_sha256(
                [{"sha256": value} for value in canonical_digests]
            ),
            "source_identity_count": totals["canonical_identities"],
            "temporal_excluded_identity_count": totals[
                "temporal_excluded_identities"
            ],
            "terminal_identity_count": totals["terminal_identities"],
            "toc_exhausted": True,
            "toc_variant_record_count": totals["toc_variant_records"],
            "unvisited_continuation_links": [],
            "visited_index_units": totals["canonical_identities"],
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    def _analyze_nevada_chapter_input(
        self,
        *,
        code_name: str,
        chapter_url: str,
        payload: bytes,
        transport_receipt: Optional[Dict[str, Any]],
        parser_input_envelope: Any,
        discovery_method: str,
    ) -> Dict[str, Any]:
        """Classify one exact chapter input for both first pass and replay."""

        from .nevada_chapter import (
            nevada_chapter_page_identity,
            nevada_chapter_terminal_sections,
            nevada_chapter_toc_section_identities,
            parse_nevada_chapter_html,
        )

        raw = bytes(payload)
        html = raw.decode("windows-1252", errors="replace")
        requested_identity = self._requested_nevada_chapter_identity(chapter_url)
        page_identity = self._normalized_nevada_chapter_token(
            nevada_chapter_page_identity(html)
        )
        if not page_identity or page_identity != requested_identity:
            raise RuntimeError(
                "Nevada retained chapter body failed requested chapter "
                f"identity verification: {chapter_url}"
            )
        evidence = self._nevada_chapter_evidence_context(
            source_url=chapter_url,
            payload=raw,
            transport_receipt=transport_receipt,
            parser_input_envelope=parser_input_envelope,
        )
        chapter_temporal_exclusions: List[Dict[str, Any]] = []
        try:
            chapter_rows = parse_nevada_chapter_html(
                html,
                source_url=chapter_url,
                code_name=code_name,
                as_of_date=evidence["as_of_date"],
                temporal_exclusions=chapter_temporal_exclusions,
            )
        except ValueError as exc:
            raise RuntimeError(
                "Nevada strict temporal chapter parsing failed: "
                f"{chapter_url}: {exc}"
            ) from exc
        chapter_terminals = nevada_chapter_terminal_sections(html)
        toc_identities = nevada_chapter_toc_section_identities(html)
        if not toc_identities:
            raise RuntimeError(
                "Nevada chapter official table of contents is empty: "
                f"{chapter_url}"
            )
        toc_counts = Counter(value.casefold() for value in toc_identities)
        accounted_counts: Counter[str] = Counter()
        for row in chapter_rows:
            data = dict(row.structured_data or {})
            accounted_counts[str(row.section_number or "").casefold()] += int(
                data.get("effective_variant_count") or 1
            )
        for item in chapter_temporal_exclusions:
            accounted_counts[
                str(item.get("section_number") or "").casefold()
            ] += len(item.get("variants") or [])
        for item in chapter_terminals:
            accounted_counts[
                str(item.get("section_number") or "").casefold()
            ] += 1
        if accounted_counts != toc_counts:
            raise RuntimeError(
                "Nevada parsed chapter variants do not reconcile with its "
                "official table of contents: "
                f"url={chapter_url} missing={dict(toc_counts - accounted_counts)} "
                f"extra={dict(accounted_counts - toc_counts)}"
            )
        if (
            not chapter_rows
            and not chapter_terminals
            and not chapter_temporal_exclusions
        ):
            raise RuntimeError(
                "Nevada retained chapter exposed neither an operative section "
                f"nor an exact terminal disposition: {chapter_url}"
            )

        classified: Dict[str, str] = {}

        def _claim_identity(section_number: str, disposition: str) -> str:
            normalized = str(section_number or "").strip()
            section_chapter = self._normalized_nevada_chapter_token(
                normalized.split(".", 1)[0]
            )
            if section_chapter != requested_identity:
                raise RuntimeError(
                    "Nevada chapter classification changed chapter identity: "
                    f"section={normalized} disposition={disposition} "
                    f"url={chapter_url}"
                )
            canonical_key = normalized.casefold()
            if not canonical_key or canonical_key in classified:
                raise RuntimeError(
                    "Nevada chapter repeated a classified canonical identity: "
                    f"section={normalized} url={chapter_url}"
                )
            classified[canonical_key] = disposition
            return canonical_key

        enriched_exclusions: List[Dict[str, Any]] = []
        for exclusion in chapter_temporal_exclusions:
            section_number = str(exclusion.get("section_number") or "").strip()
            _claim_identity(section_number, "temporal_exclusion")
            enriched_exclusions.append(
                {
                    **dict(exclusion),
                    "archive_timestamp": evidence["archive_timestamp"],
                    "chapter_url": chapter_url,
                    "content_sha256": evidence["content_sha256"],
                    "parser_input_receipt_sha256": evidence["receipt_sha256"],
                    "source_retrieved_at": evidence["retrieved_at"],
                    "source_transport": evidence["source_transport"],
                    "source_transport_chain": evidence[
                        "source_transport_chain"
                    ],
                }
            )

        enriched_terminals: List[Dict[str, Any]] = []
        for terminal in chapter_terminals:
            section_number = str(terminal.get("section_number") or "").strip()
            _claim_identity(section_number, "terminal")
            enriched_terminals.append(
                {
                    **dict(terminal),
                    "chapter_url": chapter_url,
                    "content_sha256": evidence["content_sha256"],
                    "source_observed_date": evidence["as_of_date"].isoformat(),
                    "source_retrieved_at": evidence["retrieved_at"],
                    "source_transport": evidence["source_transport"],
                    "source_transport_chain": evidence[
                        "source_transport_chain"
                    ],
                    "parser_input_receipt_sha256": evidence["receipt_sha256"],
                }
            )

        temporal_identities = 0
        temporal_variants_excluded = 0
        reconstructed_identities = 0
        truncated_display_names = 0
        for row in chapter_rows:
            section_number = str(row.section_number or "").strip()
            _claim_identity(section_number, "operative")
            if str(row.source_url or "").split("#", 1)[0] != chapter_url:
                raise RuntimeError(
                    "Nevada normalized section changed official source URL: "
                    f"{chapter_url}"
                )
            data = dict(row.structured_data or {})
            variant_count = int(data.get("effective_variant_count") or 1)
            if variant_count > 1:
                temporal_identities += 1
                temporal_variants_excluded += variant_count - 1
            reconstructed_identities += bool(
                data.get("source_section_identity_reconstructed")
            )
            truncated_display_names += bool(
                data.get("source_section_name_truncated_for_display")
            )
            data.update(
                {
                    "archive_timestamp": evidence["archive_timestamp"],
                    "chapter_url": chapter_url,
                    "content_sha256": evidence["content_sha256"],
                    "discovery_method": discovery_method,
                    "parser_input_receipt_sha256": evidence["receipt_sha256"],
                    "source_observed_date": evidence["as_of_date"].isoformat(),
                    "source_retrieved_at": evidence["retrieved_at"],
                    "source_transport": evidence["source_transport"],
                    "source_transport_chain": evidence[
                        "source_transport_chain"
                    ],
                }
            )
            row.structured_data = data

        canonical_identities = list(dict.fromkeys(toc_counts))
        if len(canonical_identities) != len(classified) or set(
            canonical_identities
        ) != set(classified):
            raise RuntimeError(
                "Nevada chapter canonical identities did not exactly reconcile: "
                f"{chapter_url}"
            )
        excluded_variant_records = sum(
            len(item.get("variants") or [])
            for item in chapter_temporal_exclusions
        )
        report = {
            "canonical_identities": len(canonical_identities),
            "canonical_identities_sha256": self._nevada_reports_sha256(
                [
                    {"canonical_identity": value}
                    for value in canonical_identities
                ]
            ),
            "chapter_identity": requested_identity,
            "content_sha256": evidence["content_sha256"],
            "excluded_variant_records": excluded_variant_records,
            "first_canonical_identity": canonical_identities[0],
            "last_canonical_identity": canonical_identities[-1],
            "operative_identities": len(chapter_rows),
            "selected_multi_variant_identities": temporal_identities,
            "selected_temporal_variants_excluded": temporal_variants_excluded,
            "source_observed_date": evidence["as_of_date"].isoformat(),
            "source_transport": evidence["source_transport"],
            "source_url": chapter_url,
            "temporal_excluded_identities": len(chapter_temporal_exclusions),
            "terminal_identities": len(chapter_terminals),
            "toc_variant_records": len(toc_identities),
        }
        return {
            "evidence": evidence,
            "report": report,
            "rows": chapter_rows,
            "temporal_exclusions": enriched_exclusions,
            "terminals": enriched_terminals,
            "reconstructed_identities": reconstructed_identities,
            "truncated_display_names": truncated_display_names,
        }
    
    def get_base_url(self) -> str:
        """Return the base URL for Nevada's legislative website."""
        return "https://www.leg.state.nv.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Nevada."""
        return [{
            "name": "Nevada Revised Statutes",
            "url": f"{self.get_base_url()}/NRS/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Nevada's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .nevada_constitution import (
            configured_constitution_html_path,
            parse_nevada_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_nevada_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Nevada Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .nevada_chapter import configured_chapter_html_path, parse_nevada_chapter_html

        local_chapter = configured_chapter_html_path()
        if local_chapter is not None:
            local_rows = parse_nevada_chapter_html(
                local_chapter.read_text(encoding="utf-8", errors="replace"),
                source_url="https://www.leg.state.nv.us/NRS/NRS-200.html",
                code_name=code_name,
                max_statutes=limit,
            )
            if local_rows:
                return local_rows if limit is None else local_rows[: int(limit)]
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        official = self._filter_official_host_statutes(official)
        if official:
            return official if limit is None else official[: int(limit)]

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=max(1, int(limit or 2)),
            )
            direct = self._filter_official_host_statutes(direct)
            if direct:
                return direct if limit is None else direct[: int(limit)]

        if self._full_corpus_enabled() and max_statutes is None:
            return []
        if any(marker in str(code_url).lower() for marker in self._SECONDARY_HOST_MARKERS):
            return []
        fallback_limit = max(10, int(limit or 40))
        generic = await self._generic_scrape(
            code_name, code_url, "Nev. Rev. Stat.", max_sections=fallback_limit
        )
        return self._filter_official_host_statutes(generic)

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 2) -> List[NormalizedStatute]:
        seeds = [
            ("1.010", f"{self.get_base_url()}/NRS/NRS-001.html"),
            ("200.010", f"{self.get_base_url()}/NRS/NRS-200.html"),
        ]
        chapter_rows = await self._scrape_chapter_pages(
            code_name,
            [url for _, url in seeds[: max(1, int(max_statutes or 1))]],
            max_statutes=max_statutes,
            discovery_method="official_seed_chapter_inline_sections",
        )
        return chapter_rows[: max(1, int(max_statutes or 1))]

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        chapter_pages = await self._discover_chapter_pages()
        self.logger.info("Nevada official index: discovered %s chapter pages", len(chapter_pages))
        if (
            max_statutes is None
            and len(chapter_pages) < self.OFFICIAL_CHAPTER_FLOOR
        ):
            raise RuntimeError(
                "Nevada official index regressed below the retained complete "
                f"chapter frontier: observed={len(chapter_pages)} "
                f"floor={self.OFFICIAL_CHAPTER_FLOOR}"
            )
        return await self._scrape_chapter_pages(
            code_name,
            chapter_pages,
            max_statutes=max_statutes,
            discovery_method="official_title_chapter_inline_sections",
        )

    async def _discover_chapter_pages(self) -> List[str]:
        index_url = self.OFFICIAL_ENTRY_URL
        payload = await self._request_bytes_direct(index_url, timeout=30)
        if not payload:
            return []
        html = payload.decode("windows-1252", errors="replace")
        chapter_urls = self._nevada_chapter_urls_from_index_html(html)
        self._last_nevada_catalog_input = None
        if getattr(self, "_state_law_acquisition_ledger", None) is not None:
            evidence = self._nevada_chapter_evidence_context(
                source_url=index_url,
                payload=payload,
                transport_receipt=dict(
                    getattr(self, "_last_page_fetch_transport_evidence", {}) or {}
                ),
                parser_input_envelope=getattr(
                    self, "_last_page_parser_input_envelope", None
                ),
            )
            self._last_nevada_catalog_input = {
                "chapter_count": len(chapter_urls),
                "chapter_urls_sha256": self._nevada_reports_sha256(
                    [{"source_url": value} for value in chapter_urls]
                ),
                "content_sha256": evidence["content_sha256"],
                "source_observed_date": evidence["as_of_date"].isoformat(),
                "source_retrieved_at": evidence["retrieved_at"],
                "source_transport": evidence["source_transport"],
                "source_url": index_url,
            }
        return chapter_urls

    async def _scrape_chapter_pages(
        self,
        code_name: str,
        chapter_pages: List[str],
        *,
        max_statutes: Optional[int],
        discovery_method: str,
    ) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        if limit is None:
            return await self._scrape_unbounded_nevada_chapters(
                code_name,
                chapter_pages,
                discovery_method=discovery_method,
            )
        for chapter_index, chapter_url in enumerate(chapter_pages, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            remaining = None if limit is None else max(0, limit - len(statutes))
            if remaining is not None and remaining <= 0:
                break
            chapter_rows = await self._extract_sections_from_chapter_page(
                code_name,
                chapter_url,
                discovery_method=discovery_method,
                max_statutes=remaining,
            )
            statutes.extend(chapter_rows)
            if chapter_index == 1 or chapter_index % 25 == 0 or chapter_index == len(chapter_pages):
                self.logger.info(
                    "Nevada official index: chapter=%s/%s yielded=%s statutes_so_far=%s",
                    chapter_index,
                    len(chapter_pages),
                    len(chapter_rows),
                    len(statutes),
                )
        return statutes[:limit] if limit is not None else statutes

    async def _scrape_unbounded_nevada_chapters(
        self,
        code_name: str,
        chapter_pages: List[str],
        *,
        discovery_method: str,
    ) -> List[NormalizedStatute]:
        """Parse every exact NRS chapter once with byte-bound as-of authority."""

        requested = list(chapter_pages)
        if len(requested) != len(set(requested)):
            raise RuntimeError("Nevada chapter frontier contains duplicate exact URLs")
        if any(not self._requested_nevada_chapter_identity(url) for url in requested):
            raise RuntimeError("Nevada chapter frontier contains a malformed official URL")

        statutes: List[NormalizedStatute] = []
        seen_sections: Dict[str, str] = {}
        terminal_sections: List[Dict[str, Any]] = []
        temporally_excluded_identities: List[Dict[str, Any]] = []
        chapter_reports: List[Dict[str, Any]] = []
        batch_stats: List[Dict[str, Any]] = []
        source_retrieved_at: List[str] = []
        temporal_identities = 0
        temporal_variants_excluded = 0
        reconstructed_identities = 0
        truncated_display_names = 0

        def _claim_frontier_identity(section_number: str, chapter_url: str) -> None:
            canonical_key = str(section_number or "").strip().casefold()
            prior_url = seen_sections.get(canonical_key)
            if not canonical_key or prior_url is not None:
                raise RuntimeError(
                    "Nevada frontier repeated a canonical identity: "
                    f"section={section_number} first={prior_url} second={chapter_url}"
                )
            seen_sections[canonical_key] = chapter_url

        batch_size = self._nevada_chapter_batch_size()
        for start in range(0, len(requested), batch_size):
            chapter_urls = requested[start : start + batch_size]
            batch = await self._fetch_nevada_chapter_frontier_batch(
                chapter_urls,
                frontier_name=f"chapters-{start + 1}-{start + len(chapter_urls)}",
            )
            batch_stats.append(dict(batch.stats or {}))
            for (
                chapter_url,
                payload,
                transport_receipt,
                parser_input_envelope,
            ) in zip(
                chapter_urls,
                batch.payloads,
                batch.transport_receipts,
                batch.parser_input_envelopes,
                strict=True,
            ):
                analyzed = self._analyze_nevada_chapter_input(
                    code_name=code_name,
                    chapter_url=chapter_url,
                    payload=payload,
                    transport_receipt=transport_receipt,
                    parser_input_envelope=parser_input_envelope,
                    discovery_method=discovery_method,
                )
                report = dict(analyzed["report"])
                chapter_reports.append(report)
                evidence = dict(analyzed["evidence"])
                source_retrieved_at.append(str(evidence["retrieved_at"]))
                chapter_rows = list(analyzed["rows"])
                chapter_exclusions = list(analyzed["temporal_exclusions"])
                chapter_terminals = list(analyzed["terminals"])
                for row in chapter_rows:
                    _claim_frontier_identity(row.section_number, chapter_url)
                for exclusion in chapter_exclusions:
                    _claim_frontier_identity(
                        str(exclusion.get("section_number") or ""), chapter_url
                    )
                for terminal in chapter_terminals:
                    _claim_frontier_identity(
                        str(terminal.get("section_number") or ""), chapter_url
                    )
                statutes.extend(chapter_rows)
                temporally_excluded_identities.extend(chapter_exclusions)
                terminal_sections.extend(chapter_terminals)
                temporal_identities += int(
                    report["selected_multi_variant_identities"]
                )
                temporal_variants_excluded += int(
                    report["selected_temporal_variants_excluded"]
                )
                reconstructed_identities += int(
                    analyzed["reconstructed_identities"]
                )
                truncated_display_names += int(analyzed["truncated_display_names"])

            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="nevada:chapter_frontier",
                force=True,
                extra={
                    "chapter_pages_completed": start + len(chapter_urls),
                    "chapter_pages_total": len(requested),
                    "source_identities_accounted": (
                        len(statutes)
                        + len(temporally_excluded_identities)
                        + len(terminal_sections)
                    ),
                    "reconstructed_section_identities": reconstructed_identities,
                    "temporal_identities_selected": temporal_identities,
                    "temporal_identities_excluded": len(
                        temporally_excluded_identities
                    ),
                    "temporal_variants_excluded": temporal_variants_excluded,
                    "terminal_sections_classified": len(terminal_sections),
                    "truncated_display_names_disclosed": truncated_display_names,
                },
            )

        self._last_nevada_chapter_batch_stats = batch_stats
        self._last_nevada_temporal_closure = {
            "canonical_statutes": len(statutes),
            "chapter_pages": len(requested),
            "duplicate_canonical_identities": 0,
            "reconstructed_section_identities": reconstructed_identities,
            "source_identities_accounted": (
                len(statutes)
                + len(temporally_excluded_identities)
                + len(terminal_sections)
            ),
            "temporal_identities_selected": temporal_identities,
            "temporal_identities_excluded": len(temporally_excluded_identities),
            "temporal_identity_exclusions": temporally_excluded_identities,
            "temporal_variants_excluded": temporal_variants_excluded,
            "terminal_sections": terminal_sections,
            "toc_variant_records": sum(
                int(report["toc_variant_records"]) for report in chapter_reports
            ),
            "truncated_display_names_disclosed": truncated_display_names,
        }
        catalog_report = getattr(self, "_last_nevada_catalog_input", None)
        if getattr(self, "_state_law_acquisition_ledger", None) is not None:
            if not isinstance(catalog_report, Mapping):
                raise RuntimeError(
                    "Nevada exact root catalog input was not retained before closure"
                )
            exact_frontier = self._nevada_exact_frontier(
                catalog_report=catalog_report,
                chapter_reports=chapter_reports,
            )
            observed_candidates = source_retrieved_at + [
                str(catalog_report.get("source_retrieved_at") or "")
            ]
            observed_at = max(value for value in observed_candidates if value)
            self._last_nevada_full_frontier = {
                "boundary_first": str(
                    chapter_reports[0].get("first_canonical_identity") or ""
                ),
                "boundary_last": str(
                    chapter_reports[-1].get("last_canonical_identity") or ""
                ),
                "catalog_report": dict(catalog_report),
                "chapter_reports": chapter_reports,
                "code_name": code_name,
                "frontier": exact_frontier,
                "legal_as_of": str(exact_frontier.get("legal_as_of") or ""),
                "observed_at": observed_at,
                "transport_batch_stats": batch_stats,
            }
        return statutes

    def _replay_nevada_source_frontier(
        self,
        first: Mapping[str, Any],
    ) -> List[NormalizedStatute]:
        """Reparse all retained root and chapter inputs without network access."""

        catalog_report_raw = first.get("catalog_report")
        chapter_reports_raw = first.get("chapter_reports")
        if not isinstance(catalog_report_raw, Mapping):
            raise RuntimeError("Nevada retained root report is incomplete")
        if (
            not isinstance(chapter_reports_raw, Sequence)
            or isinstance(chapter_reports_raw, (str, bytes, bytearray))
            or not chapter_reports_raw
            or any(not isinstance(row, Mapping) for row in chapter_reports_raw)
        ):
            raise RuntimeError("Nevada retained chapter reports are incomplete")
        catalog_report = dict(catalog_report_raw)
        expected_chapter_reports = [dict(row) for row in chapter_reports_raw]
        root_url = self._canonical_fetch_url(
            str(catalog_report.get("source_url") or "")
        )
        expected_chapter_urls = [
            self._canonical_fetch_url(str(report.get("source_url") or ""))
            for report in expected_chapter_reports
        ]

        from .strict_frontier_closure import replay_exact_retained_state_records

        requested_urls = [root_url, *expected_chapter_urls]
        retained = replay_exact_retained_state_records(
            self,
            requests=[
                (url, {"method": "GET", "url": url}) for url in requested_urls
            ],
            frontier_name="Nevada exact root/chapter frontier",
        )
        root_retained = retained[0]
        root_raw = bytes(root_retained.envelope.body or b"")
        root_context = self._nevada_chapter_evidence_context(
            source_url=root_url,
            payload=root_raw,
            transport_receipt=dict(root_retained.transport_receipt),
            parser_input_envelope=root_retained.envelope,
        )
        replay_chapter_urls = self._nevada_chapter_urls_from_index_html(
            root_raw.decode("windows-1252", errors="replace")
        )
        if replay_chapter_urls != expected_chapter_urls:
            raise RuntimeError("Nevada retained root chapter membership changed")
        replay_catalog_report = {
            "chapter_count": len(replay_chapter_urls),
            "chapter_urls_sha256": self._nevada_reports_sha256(
                [{"source_url": value} for value in replay_chapter_urls]
            ),
            "content_sha256": root_context["content_sha256"],
            "source_observed_date": root_context["as_of_date"].isoformat(),
            "source_retrieved_at": root_context["retrieved_at"],
            "source_transport": root_context["source_transport"],
            "source_url": root_url,
        }
        if replay_catalog_report != catalog_report:
            raise RuntimeError("Nevada retained root report changed on replay")

        code_name = str(first.get("code_name") or "Nevada Revised Statutes")
        replay_rows: List[NormalizedStatute] = []
        replay_chapter_reports: List[Dict[str, Any]] = []
        seen_identities: Dict[str, str] = {}
        for chapter_url, chapter_retained in zip(
            expected_chapter_urls,
            retained[1:],
            strict=True,
        ):
            analysis = self._analyze_nevada_chapter_input(
                code_name=code_name,
                chapter_url=chapter_url,
                payload=bytes(chapter_retained.envelope.body or b""),
                transport_receipt=dict(chapter_retained.transport_receipt),
                parser_input_envelope=chapter_retained.envelope,
                discovery_method="official_title_chapter_inline_sections",
            )
            for item in (
                *list(analysis["rows"]),
                *list(analysis["temporal_exclusions"]),
                *list(analysis["terminals"]),
            ):
                if isinstance(item, NormalizedStatute):
                    section_number = str(item.section_number or "")
                else:
                    section_number = str(item.get("section_number") or "")
                key = section_number.strip().casefold()
                prior = seen_identities.get(key)
                if not key or prior is not None:
                    raise RuntimeError(
                        "Nevada retained replay repeated a canonical identity: "
                        f"section={section_number} first={prior} second={chapter_url}"
                    )
                seen_identities[key] = chapter_url
            replay_rows.extend(list(analysis["rows"]))
            replay_chapter_reports.append(dict(analysis["report"]))
        if replay_chapter_reports != expected_chapter_reports:
            raise RuntimeError("Nevada retained chapter reports changed on replay")
        replayed_frontier = self._nevada_exact_frontier(
            catalog_report=replay_catalog_report,
            chapter_reports=replay_chapter_reports,
        )
        self._last_nevada_replayed_frontier = {
            "frontier": replayed_frontier,
            "rows": replay_rows,
        }
        return replay_rows

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Seal exact Nevada temporal membership against retained replay."""

        if getattr(self, "_state_law_acquisition_ledger", None) is None:
            raise RuntimeError("Nevada frontier closure requires an attached ledger")
        first = getattr(self, "_last_nevada_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Nevada source-derived strict frontier was not retained before output"
            )
        replay_rows = self._replay_nevada_source_frontier(first)
        replay = getattr(self, "_last_nevada_replayed_frontier", None)
        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier") if isinstance(replay, Mapping) else None
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier, Mapping
        ):
            raise RuntimeError("Nevada exact frontier replay did not close")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        chapter_reports = [
            dict(report) for report in list(first.get("chapter_reports") or [])
        ]
        transport_counts = Counter(
            str(report.get("source_transport") or "")
            for report in chapter_reports
        )
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="NV",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("legal_as_of") or ""),
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(chapter_reports),
            pagination_total=int(
                first_frontier.get("source_identity_count") or 0
            ),
            transport={
                "fixture": False,
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_html",
                "per_page_archive_loop": False,
                "residual_only_retries": True,
                "retained_replay_network_requests": 0,
                "source_transport_counts": dict(sorted(transport_counts.items())),
                "synthetic": False,
                "first_pass_batch_stats": list(
                    first.get("transport_batch_stats") or []
                ),
            },
        )

    async def _extract_sections_from_chapter_page(
        self,
        code_name: str,
        chapter_url: str,
        *,
        discovery_method: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        if max_statutes is not None and int(max_statutes) <= 0:
            return []
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._request_text_direct(chapter_url, timeout=35)
        if not html:
            return []
        from .nevada_chapter import parse_nevada_chapter_html

        parsed = parse_nevada_chapter_html(
            html,
            source_url=chapter_url,
            code_name=code_name,
            max_statutes=max_statutes,
        )
        if parsed:
            for row in parsed:
                data = dict(row.structured_data or {})
                data["discovery_method"] = discovery_method
                row.structured_data = data
            return parsed
        soup = BeautifulSoup(html, "html.parser")
        paragraphs = soup.find_all("p")
        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        current: Dict[str, object] | None = None

        def _flush_current() -> None:
            nonlocal current
            if not current:
                return
            section_number = str(current.get("section_number") or "").strip()
            section_name = str(current.get("section_name") or "").strip()
            body_parts = [str(item).strip() for item in current.get("body_parts") or [] if str(item).strip()]
            if not section_number or not body_parts:
                current = None
                return
            full_text = self._normalize_legal_text(" ".join(body_parts))
            if len(full_text) < 120:
                current = None
                return
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=(section_name or f"NRS {section_number}")[:200],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(section_name or full_text[:800]),
                    source_url=f"{chapter_url}#{current.get('anchor')}" if current.get("anchor") else chapter_url,
                    official_cite=f"Nev. Rev. Stat. § {section_number}",
                    structured_data={
                        "source_kind": "official_nevada_revised_statutes_html",
                        "discovery_method": discovery_method,
                        "chapter_url": chapter_url,
                        "skip_hydrate": True,
                    },
                )
            )
            current = None

        for paragraph in paragraphs:
            if limit is not None and len(out) >= limit:
                break
            anchor = paragraph.find("a", attrs={"name": True})
            section_span = paragraph.find("span", class_="Section")
            if anchor is not None and section_span is not None:
                _flush_current()
                section_number = self._normalize_legal_text(section_span.get_text(" ", strip=True))
                if not self._NRS_SECTION_NUMBER_RE.match(section_number):
                    continue
                leadline = paragraph.find("span", class_="Leadline")
                section_name = self._normalize_legal_text(leadline.get_text(" ", strip=True)) if leadline else ""
                text = self._normalize_legal_text(paragraph.get_text(" ", strip=True))
                current = {
                    "anchor": str(anchor.get("name") or "").strip(),
                    "section_number": section_number,
                    "section_name": section_name,
                    "body_parts": [text] if text else [],
                }
                continue
            if current is None:
                continue
            css_classes = {str(value) for value in (paragraph.get("class") or [])}
            if "SectBody" not in css_classes:
                continue
            text = self._normalize_legal_text(paragraph.get_text(" ", strip=True))
            if text:
                cast_parts = current.setdefault("body_parts", [])
                if isinstance(cast_parts, list):
                    cast_parts.append(text)

        _flush_current()
        return out[:limit] if limit is not None else out

    async def _request_bytes_direct(self, url: str, timeout: int = 18) -> bytes:
        try:
            validator = (
                self._is_valid_nevada_index_payload
                if str(url or "").rstrip("/")
                == self.OFFICIAL_ENTRY_URL.rstrip("/")
                else None
            )
            return await self._fetch_parser_input_with_transport(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout_seconds=max(1, int(timeout)),
                content_validator=validator,
                allow_archival_fallback=True,
                media_type="text/html",
                provider="nevada_direct_chapter",
            )
        except Exception:
            return b""

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        payload = await self._request_bytes_direct(url, timeout=timeout)
        return payload.decode("windows-1252", errors="replace") if payload else ""

    def official_chapter_url(self, chapter: Any) -> str:
        token = str(chapter or "").strip().upper()
        if not token:
            return self.OFFICIAL_ENTRY_URL
        if token.isdigit():
            filename = f"NRS-{int(token):03d}.html"
        else:
            match = re.match(r"(\d+)([A-Z]+)$", token)
            if match:
                filename = f"NRS-{int(match.group(1)):03d}{match.group(2)}.html"
            else:
                filename = f"NRS-{token}.html"
        return f"{self.get_base_url()}/NRS/{filename}"

    def official_title_url(self, title_number: Any) -> str:
        first = self.OFFICIAL_TITLE_FIRST_CHAPTER.get(int(title_number), str(title_number))
        return self.official_chapter_url(first)

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Nevada Revised Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number in range(1, self.OFFICIAL_TITLE_COUNT + 1):
            url = self.official_title_url(number)
            name = self.OFFICIAL_TITLE_NAMES.get(number, f"Title {number}")
            rows.append(
                {
                    "canonical_key": f"nv:title-{number}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Nevada Revised Statutes Title {number} ({name}) official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        """Synchronously bridge the official catalog through shared evidence."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self._request_bytes_direct(
                    url,
                    timeout=max(5, int(timeout_seconds or 12)),
                )
            )
        raise RuntimeError(
            "Nevada fetch_official must run outside an active asyncio event loop"
        )

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        if any(marker in host for marker in self._SECONDARY_HOST_MARKERS):
            return False
        return host == "leg.state.nv.us" or host.endswith(".leg.state.nv.us")

    def _filter_official_host_statutes(
        self, statutes: List[NormalizedStatute]
    ) -> List[NormalizedStatute]:
        return [
            statute
            for statute in statutes
            if self._host_is_official(str(statute.source_url or ""))
        ]

    def _is_source_bound_operative_statute_record(
        self,
        statute: NormalizedStatute,
    ) -> bool:
        """Admit only exact retained NRS section rows past generic nav filters.

        Nevada's operative text legitimately contains words such as
        ``expression``, ``members``, ``agency``, and ``session``.  Those words
        overlap the generic navigation heuristic, so the state-owned parser
        must prove the row instead of asking that heuristic to interpret the
        prose.  This hook deliberately validates the complete row identity and
        retained-input projection; an official-looking host alone is never
        sufficient.
        """

        if not isinstance(statute, NormalizedStatute):
            return False
        section_number = str(statute.section_number or "").strip()
        if self._NRS_SECTION_NUMBER_RE.fullmatch(section_number) is None:
            return False
        chapter_raw, section_tail = section_number.split(".", 1)
        chapter_identity = self._normalized_nevada_chapter_token(chapter_raw)
        if not chapter_identity:
            return False
        chapter_match = re.fullmatch(
            r"(?P<number>\d+)(?P<suffix>[A-Z]?)",
            chapter_identity,
        )
        if chapter_match is None:
            return False
        chapter_file_token = (
            f"{int(chapter_match.group('number')):03d}"
            f"{chapter_match.group('suffix')}"
        )
        expected_chapter_url = (
            f"{self.OFFICIAL_ENTRY_URL}NRS-{chapter_file_token}.html"
        )
        expected_anchor = (
            f"NRS{chapter_file_token}Sec{section_tail.replace('.', '')}"
        )
        expected_source_url = f"{expected_chapter_url}#{expected_anchor}"

        source_url = str(statute.source_url or "").strip()
        parsed = urlparse(source_url)
        if (
            source_url != expected_source_url
            or parsed.scheme != "https"
            or parsed.hostname != self.OFFICIAL_DOMAIN
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.params
        ):
            return False
        if (
            str(statute.state_code or "").strip().upper() != "NV"
            or str(statute.state_name or "").strip() != "Nevada"
            or str(statute.code_name or "").strip() != "Nevada Revised Statutes"
            or str(statute.statute_id or "").strip()
            != f"Nevada Revised Statutes § {section_number}"
            or str(statute.official_cite or "").strip()
            != f"Nev. Rev. Stat. § {section_number}"
            or not str(statute.section_name or "").strip()
            or not str(statute.full_text or "").strip()
            or re.match(
                r"^\s*section\s+section-\d+\s*:",
                str(statute.full_text or ""),
                flags=re.IGNORECASE,
            )
            is not None
        ):
            return False

        data = statute.structured_data
        if not isinstance(data, Mapping):
            return False
        if (
            str(data.get("source_kind") or "")
            != "official_nevada_revised_statutes_html"
            or str(data.get("source_authority_class") or "") != "official"
            or str(data.get("discovery_method") or "")
            != "official_title_chapter_inline_sections"
            or data.get("skip_hydrate") is not True
            or str(data.get("chapter_url") or "") != expected_chapter_url
        ):
            return False
        for digest_field in ("content_sha256", "parser_input_receipt_sha256"):
            if re.fullmatch(
                r"[0-9a-f]{64}",
                str(data.get(digest_field) or ""),
            ) is None:
                return False

        fragments = data.get("source_section_number_fragments")
        if (
            not isinstance(fragments, list)
            or any(not isinstance(value, str) for value in fragments)
            or isinstance(data.get("source_section_number_span_count"), bool)
            or isinstance(data.get("source_section_number_empty_span_count"), bool)
        ):
            return False
        try:
            span_count = int(data.get("source_section_number_span_count"))
            empty_count = int(data.get("source_section_number_empty_span_count"))
        except (TypeError, ValueError):
            return False
        raw_number = str(data.get("source_section_number_raw") or "")
        if (
            span_count != len(fragments)
            or empty_count != sum(not value for value in fragments)
            or raw_number != "".join(fragments)
        ):
            return False
        repair = str(data.get("source_section_identity_repair") or "")
        reconstructed = data.get("source_section_identity_reconstructed")
        if reconstructed is not (
            sum(bool(value) for value in fragments) > 1 or bool(repair)
        ):
            return False
        if not repair:
            if raw_number.casefold() != section_number.casefold():
                return False
        elif repair == "official_chapter_anchor_prefix_repair":
            raw_parts = raw_number.split(".", 1)
            if (
                len(raw_parts) != 2
                or raw_parts[1].casefold() != section_tail.casefold()
                or self._normalized_nevada_chapter_token(raw_parts[0])
                == chapter_identity
            ):
                return False
        else:
            return False

        observed_at = str(data.get("source_observed_date") or "")
        retrieved_at = str(data.get("source_retrieved_at") or "")
        try:
            date.fromisoformat(observed_at)
            retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False
        if retrieved.tzinfo is None or retrieved.utcoffset() is None:
            return False
        transport = str(data.get("source_transport") or "").strip()
        transport_chain = data.get("source_transport_chain")
        if (
            not transport
            or not isinstance(transport_chain, list)
            or not transport_chain
            or any(not isinstance(value, str) or not value for value in transport_chain)
            or transport not in transport_chain
        ):
            return False
        archive_timestamp = str(data.get("archive_timestamp") or "")
        if archive_timestamp and re.fullmatch(r"\d{8,14}", archive_timestamp) is None:
            return False
        return True

    def _nevada_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                self._env_int("STATE_SCRAPER_NV_FRONTIER_CONCURRENCY", default=12),
            ),
        )

    def _nevada_chapter_batch_size(self) -> int:
        return max(
            1,
            min(
                1024,
                self._env_int("STATE_SCRAPER_NV_CHAPTER_BATCH_SIZE", default=512),
            ),
        )

    @staticmethod
    def _is_valid_nevada_chapter_payload(payload: bytes) -> bool:
        """Reject interstitial/error HTML before it becomes parser evidence."""

        if not payload:
            return False
        lowered = bytes(payload).lower()
        has_chapter_title = (
            b"nrs: chapter" in lowered
            or b"nrs: preliminary chapter" in lowered
        )
        return has_chapter_title and b'class="section"' in lowered

    @classmethod
    def _is_valid_nevada_index_payload(cls, payload: bytes) -> bool:
        """Require the retained, source-observed complete NRS chapter floor."""

        if not payload:
            return False
        text = payload.decode("windows-1252", errors="replace")
        chapters = {
            match.group(1).upper()
            for match in re.finditer(
                r"href\s*=\s*[\"']?NRS-(\d{3}[A-Za-z]?)\.html",
                text,
                flags=re.IGNORECASE,
            )
        }
        return len(chapters) >= cls.OFFICIAL_CHAPTER_FLOOR

    @staticmethod
    def _normalized_nevada_chapter_token(value: str) -> str:
        match = re.fullmatch(r"0*(?P<number>\d+)(?P<suffix>[A-Za-z]?)", value)
        if match is None:
            return ""
        return f"{int(match.group('number'))}{match.group('suffix').upper()}"

    @classmethod
    def _requested_nevada_chapter_identity(cls, source_url: str) -> str:
        match = cls._NRS_CHAPTER_ABS_RE.search(str(source_url or ""))
        if match is None:
            return ""
        return cls._normalized_nevada_chapter_token(match.group("chapter"))

    @staticmethod
    def _nevada_chapter_evidence_context(
        *,
        source_url: str,
        payload: bytes,
        transport_receipt: Optional[Dict[str, Any]],
        parser_input_envelope: Any,
    ) -> Dict[str, Any]:
        """Resolve the legal observation date from exact retained chapter bytes."""

        envelope = parser_input_envelope
        if not isinstance(envelope, dict):
            to_dict = getattr(envelope, "to_dict", None)
            if callable(to_dict):
                envelope = to_dict()
        if isinstance(envelope, dict) and isinstance(
            envelope.get("parser_input_envelope"),
            dict,
        ):
            envelope = envelope["parser_input_envelope"]
        receipt = (
            envelope.get("acquisition", {}).get("receipt", {})
            if isinstance(envelope, dict)
            else {}
        )
        if not isinstance(receipt, dict) or receipt.get("endpoint") != source_url:
            raise RuntimeError(
                "Nevada chapter acquisition receipt does not match requested URL: "
                f"{source_url}"
            )

        content_sha256 = hashlib.sha256(bytes(payload)).hexdigest()
        retained_sha256 = str(
            receipt.get("content", {}).get("sha256") or ""
        ).strip().lower()
        envelope_sha256 = str(
            envelope.get("acquisition", {}).get("body_sha256") or ""
        ).strip().lower()
        if (
            not retained_sha256
            or retained_sha256 != content_sha256
            or envelope_sha256 != content_sha256
        ):
            raise RuntimeError(
                "Nevada chapter acquisition evidence changed parser bytes: "
                f"{source_url}"
            )

        retained_transport = receipt.get("metadata", {}).get(
            "transport_receipt",
            {},
        )
        if not isinstance(retained_transport, dict):
            raise RuntimeError(
                "Nevada chapter receipt lacks retained transport evidence: "
                f"{source_url}"
            )
        aligned_transport = (
            dict(transport_receipt) if isinstance(transport_receipt, dict) else {}
        )
        from ...legal_data.state_laws_source_provenance import (
            StateLawTransportReceiptError,
            verify_state_law_transport_receipt,
        )

        try:
            verified_transport = verify_state_law_transport_receipt(
                retained_transport,
                official_url=source_url,
                content_sha256=content_sha256,
            )
            if aligned_transport:
                aligned_verified = verify_state_law_transport_receipt(
                    aligned_transport,
                    official_url=source_url,
                    content_sha256=content_sha256,
                )
                if aligned_verified != verified_transport:
                    raise StateLawTransportReceiptError(
                        "unaligned_transport_receipt",
                        "retained and aligned transport receipts disagree",
                    )
        except StateLawTransportReceiptError as exc:
            raise RuntimeError(
                "Nevada chapter acquisition transport identity is incomplete: "
                f"{source_url}"
            ) from exc
        source_transport = verified_transport.leaf_transport

        retrieved_at = str(receipt.get("retrieved_at") or "").strip()
        try:
            retrieved_date = datetime.fromisoformat(
                retrieved_at.replace("Z", "+00:00")
            ).date()
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Nevada chapter receipt lacks a valid retrieval date: {source_url}"
            ) from exc

        archive_timestamp = str(
            verified_transport.archive_timestamp or ""
        ).strip()
        if not verified_transport.is_archival:
            as_of_date = retrieved_date
        else:
            archive_match = re.fullmatch(
                r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})\d{0,6}",
                archive_timestamp,
            )
            try:
                if archive_match is None:
                    raise ValueError("invalid archive timestamp")
                as_of_date = date(
                    int(archive_match.group("year")),
                    int(archive_match.group("month")),
                    int(archive_match.group("day")),
                )
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "Nevada archived chapter receipt lacks a provenance snapshot "
                    f"date: {source_url}"
                ) from exc
        receipt_sha256 = str(receipt.get("receipt_sha256") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", receipt_sha256):
            raise RuntimeError(
                f"Nevada chapter receipt lacks an exact digest: {source_url}"
            )
        return {
            "as_of_date": as_of_date,
            "archive_timestamp": archive_timestamp,
            "content_sha256": content_sha256,
            "receipt_sha256": receipt_sha256,
            "retrieved_at": retrieved_at,
            "source_transport": source_transport,
            "source_transport_chain": list(verified_transport.transport_chain),
        }

    async def _fetch_nevada_chapter_frontier_batch(
        self,
        urls: List[str],
        *,
        frontier_name: str,
    ) -> StateLawPageMultiFetchResult:
        """Acquire one NRS frontier through the shared grouped-WARC path."""

        if not urls:
            return StateLawPageMultiFetchResult([], [], [], [], [], {})
        requested = list(urls)
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
            media_type="text/html",
            max_concurrency=self._nevada_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=("/NRS/NRS-",),
            common_crawl_mime_terms=("html",),
            content_validator=self._is_valid_nevada_chapter_payload,
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
                f"Nevada {frontier_name} frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"Nevada {frontier_name} frontier changed URL order or identity"
            )
        failures = [
            {"url": url, "error": error or "empty parser input"}
            for url, payload, error in zip(
                batch.urls,
                batch.payloads,
                batch.errors,
                strict=True,
            )
            if error is not None or not payload
        ]
        if failures:
            raise RuntimeError(
                f"Nevada {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures}"
            )
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    def _chapter_from_text(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        href_match = self._NRS_CHAPTER_ABS_RE.search(text)
        if href_match:
            return href_match.group("chapter").upper().lstrip("0") or "0"
        ref = self._NRS_REF_RE.search(text)
        if not ref:
            return ""
        chapter = str(ref.group("chapter") or "").upper().lstrip("0")
        return chapter or ""

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        current_title = ""
        for node in soup.find_all(["a", "b", "strong", "h2", "h3", "h4", "p"]):
            label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
            title_match = re.search(r"\bTitle\s+(\d{1,2})\b", label, flags=re.IGNORECASE)
            if title_match:
                current_title = str(int(title_match.group(1)))
            href = str(node.get("href") or "").strip() if node.name == "a" else ""
            if not href or not current_title or current_title in found:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            if self._NRS_CHAPTER_ABS_RE.search(absolute) or self._NRS_CHAPTER_HREF_RE.match(href):
                found[current_title] = self.official_title_url(current_title)
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._NRS_CHAPTER_ABS_RE.search(absolute)
            if not match:
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            title_match = re.search(r"\bTitle\s+(\d{1,2})\b", label, flags=re.IGNORECASE)
            if title_match:
                number = str(int(title_match.group(1)))
                if number not in found:
                    found[number] = self.official_title_url(number)
        return found

    def classify_linkless_bucket_rows(
        self,
        material: Union[bytes, str, Sequence[Mapping[str, Any]]],
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, str]]]:
        """Replace NV linkless bucket rows with official NRS URLs or quarantine them.

        Accepts either a live/index HTML fragment or a sequence of bucket-style
        row mappings. Recoverable chapter identifiers are rewritten to
        ``https://www.leg.state.nv.us/NRS/NRS-XXX.html``. Remaining linkless
        material is quarantined with a typed disposition and evidence hash.
        """

        if isinstance(material, (bytes, bytearray, str)):
            return self._classify_linkless_html(material, page_url=page_url)
        repaired: List[Dict[str, str]] = []
        quarantines: List[Dict[str, str]] = []
        seen: set[str] = set()
        for index, raw in enumerate(list(material or []), start=1):
            if not isinstance(raw, Mapping):
                continue
            source_url = str(
                raw.get("source_url") or raw.get("url") or raw.get("href") or ""
            ).strip()
            label = str(
                raw.get("section_number")
                or raw.get("statute_id")
                or raw.get("citation")
                or raw.get("name")
                or raw.get("text")
                or raw.get("label")
                or ""
            ).strip()
            blob = " ".join(
                str(raw.get(key) or "")
                for key in (
                    "source_url",
                    "url",
                    "href",
                    "section_number",
                    "statute_id",
                    "citation",
                    "name",
                    "text",
                    "label",
                    "chapter",
                    "title",
                )
            )
            chapter = self._chapter_from_text(blob) or self._chapter_from_text(label)
            official_url = self.official_chapter_url(chapter) if chapter else ""
            official_already = bool(source_url) and self._host_is_official(source_url)
            if official_already and chapter:
                unit_id = f"nv:chapter-{chapter.lower()}"
                if unit_id in seen:
                    continue
                seen.add(unit_id)
                repaired.append(
                    {
                        "canonical_key": unit_id,
                        "chapter": chapter,
                        "source_url": source_url,
                        "label": label or f"NRS {chapter}",
                        "repair_source": "official_href",
                        "source_link_disposition": "official",
                        "text": (
                            f"Nevada Revised Statutes Chapter {chapter} official "
                            f"catalog unit at {source_url}"
                        ),
                    }
                )
                continue
            if chapter and official_url:
                unit_id = f"nv:chapter-{chapter.lower()}"
                if unit_id in seen:
                    continue
                seen.add(unit_id)
                repaired.append(
                    {
                        "canonical_key": unit_id,
                        "chapter": chapter,
                        "source_url": official_url,
                        "label": label or f"NRS {chapter}",
                        "repair_source": "repaired_from_linkless_row",
                        "source_link_disposition": "repaired_official_leginfo",
                        "text": (
                            f"Nevada Revised Statutes Chapter {chapter} official "
                            f"catalog unit at {official_url}"
                        ),
                    }
                )
                continue
            evidence_src = json.dumps(dict(raw), sort_keys=True, default=str)
            unit_id = f"nv:missing-{hashlib.sha256(evidence_src.encode('utf-8')).hexdigest()[:16]}"
            if unit_id in seen:
                continue
            seen.add(unit_id)
            quarantines.append(
                {
                    "unit_id": unit_id,
                    "reason": self.LINKLESS_BUCKET_DISPOSITION,
                    "label": (label or f"linkless bucket row {index}")[:240],
                    "page_url": page_url or source_url,
                    "evidence_sha256": hashlib.sha256(evidence_src.encode("utf-8")).hexdigest(),
                }
            )
        return {"repaired": repaired, "quarantines": quarantines}

    def _classify_linkless_html(
        self,
        html: Union[bytes, str],
        *,
        page_url: str,
    ) -> Dict[str, List[Dict[str, str]]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for official Nevada discovery") from exc

        payload = html.decode("utf-8", errors="replace") if isinstance(html, (bytes, bytearray)) else str(html or "")
        soup = BeautifulSoup(payload, "html.parser")
        repaired: List[Dict[str, str]] = []
        quarantines: List[Dict[str, str]] = []
        seen: set[str] = set()
        seen_quarantine: set[str] = set()

        def _record(chapter: str, label: str, source: str) -> None:
            chapter = str(chapter or "").strip().upper().lstrip("0") or ""
            if not chapter:
                return
            unit_id = f"nv:chapter-{chapter.lower()}"
            if unit_id in seen:
                return
            seen.add(unit_id)
            official_url = self.official_chapter_url(chapter)
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip() or f"NRS {chapter}"
            repaired.append(
                {
                    "canonical_key": unit_id,
                    "chapter": chapter,
                    "source_url": official_url,
                    "label": cleaned,
                    "repair_source": source,
                    "source_link_disposition": (
                        "official" if source == "official_href" else "repaired_official_leginfo"
                    ),
                    "text": (
                        f"Nevada Revised Statutes Chapter {chapter} official "
                        f"catalog unit at {official_url}"
                    ),
                }
            )

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            match = self._NRS_CHAPTER_ABS_RE.search(absolute) or self._NRS_CHAPTER_HREF_RE.match(href)
            if match:
                chapter = match.group("chapter") if hasattr(match, "lastindex") and match.lastindex else (
                    href[4:-5] if href.upper().startswith("NRS-") else self._chapter_from_text(absolute)
                )
                if hasattr(match, "groupdict") and match.groupdict().get("chapter"):
                    chapter = match.group("chapter")
                _record(chapter, label, "official_href")
                continue
            nearby = " ".join(
                str(item or "")
                for item in (href, link.get("onclick"), link.get("id"), label)
            )
            chapter = self._chapter_from_text(nearby)
            if chapter:
                _record(chapter, label, "repaired_from_attributes")

        for node in soup.find_all(["span", "td", "li", "div", "p"]):
            label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
            if not label or not self._NRS_LINKLESS_LABEL_RE.search(label):
                continue
            if node.find("a", href=True):
                continue
            chapter = self._chapter_from_text(
                " ".join(str(item or "") for item in (node.get("data-chapter"), node.get("id"), label))
            )
            if chapter:
                _record(chapter, label, "repaired_from_linkless_row")
                continue
            unit_id = f"nv:missing-{hashlib.sha256(label.encode('utf-8')).hexdigest()[:16]}"
            if unit_id in seen_quarantine:
                continue
            seen_quarantine.add(unit_id)
            quarantines.append(
                {
                    "unit_id": unit_id,
                    "reason": self.MISSING_LINK_DISPOSITION,
                    "label": label[:240],
                    "page_url": page_url or self.OFFICIAL_ENTRY_URL,
                    "evidence_sha256": hashlib.sha256(str(node).encode("utf-8")).hexdigest(),
                }
            )
        return {"repaired": repaired, "quarantines": quarantines}

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official NRS title and repair missing live links."""

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

    def fetch_official(self, code: str = "NV"):
        """Acquire the exhaustive official Nevada Revised Statutes title catalog.

        Live HTTPS retains the official NRS index. Every NRS title is
        enumerated with an official leg.state.nv.us URL. Linkless bucket
        rows are repaired to official chapter URLs or quarantined with a
        typed disposition. This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "NV").strip().upper() or "NV"
        self.last_official_quarantines = []
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        if not html:
            raise RuntimeError(
                "nevada official catalog acquisition returned no retained parser bytes"
            )
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("nevada official catalog enumeration is incomplete")
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "nevada official catalog enumeration rejected incomplete "
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
            "quarantines": list(self.last_official_quarantines),
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        transport_receipt = getattr(
            self,
            "_last_page_fetch_transport_evidence",
            {},
        )
        source_transport = str(
            transport_receipt.get("source_transport") or ""
            if isinstance(transport_receipt, Mapping)
            else ""
        ).strip().lower()
        transport_kind = (
            "archived_https"
            if source_transport and source_transport != "direct"
            else "live_https"
        )
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
            "nv_linkless_quarantines": list(self.last_official_quarantines),
            "official_catalog_content_sha256": hashlib.sha256(html).hexdigest(),
            "official_catalog_source_transport": source_transport or "direct",
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code=normalized,
            request_bytes=request,
            response_bytes=html,
            body_bytes=body,
            source_domain=self.OFFICIAL_DOMAIN,
            source_path=self.OFFICIAL_ENTRY_PATH,
            frontier=frontier,
            rows=tuple(rows),
            transport_kind=transport_kind,
            fixture=False,
            first_hierarchy_unit=str(rows[0]["canonical_key"]),
            last_hierarchy_unit=str(rows[-1]["canonical_key"]),
        )


# Register this scraper with the registry
StateScraperRegistry.register("NV", NevadaScraper)
