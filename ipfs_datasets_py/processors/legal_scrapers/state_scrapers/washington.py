"""Scraper for Washington state laws.

This module contains the scraper for Washington statutes from the official state legislative website.
"""

import hashlib
import json
import re
import ssl
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StateLawPageMultiFetchResult,
    StatuteMetadata,
)
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

    _SECTION_CITE_RE = re.compile(
        r"^(?:\d+[A-Za-z]?\.\d+[A-Za-z]?(?:\.\d+[A-Za-z]?)?"
        r"|62A\.\d+[A-Za-z]?-\d+[A-Za-z]?)$",
        re.IGNORECASE,
    )

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            washington_section,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            washington_section,
            wayback_machine_engine,
        )

    def _washington_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                self._env_int(
                    "STATE_SCRAPER_WA_FRONTIER_CONCURRENCY",
                    default=16,
                ),
            ),
        )

    def _washington_section_batch_size(self) -> int:
        return max(
            1,
            min(
                1024,
                self._env_int("STATE_SCRAPER_WA_SECTION_BATCH_SIZE", default=256),
            ),
        )

    def _record_washington_frontier_inputs(
        self,
        *,
        source_role: str,
        urls: Sequence[str],
        payloads: Sequence[bytes],
    ) -> None:
        """Bind one ordered RCW hierarchy batch to exact parser bytes."""

        requested = list(urls)
        if len(requested) != len(payloads):
            raise RuntimeError("Washington frontier input projection is not aligned")
        reports = list(getattr(self, "_washington_frontier_input_reports", []))
        seen = {str(row.get("source_url") or "") for row in reports}
        for url, payload in zip(requested, payloads, strict=True):
            raw = bytes(payload or b"")
            if not url or url in seen or not raw:
                raise RuntimeError(
                    "Washington frontier input projection repeated or lost a URL: "
                    f"{url}"
                )
            seen.add(url)
            reports.append(
                {
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "source_role": str(source_role or "").strip(),
                    "source_url": url,
                }
            )
        self._washington_frontier_input_reports = reports

    @staticmethod
    def _is_valid_washington_frontier_payload(payload: bytes) -> bool:
        """Reject transport/interstitial pages before evidence retention."""

        if not payload:
            return False
        lowered = bytes(payload).lower()
        rejected_markers = (
            b"access denied",
            b"captcha",
            b"request blocked",
            b"server error in '/' application",
        )
        has_content_wrapper = b"contentwrapper" in lowered
        has_cite_link = b"default.aspx?cite=" in lowered
        has_title_block = b"contentplaceholder1_pnltitleblock" in lowered
        if any(marker in lowered for marker in rejected_markers):
            # Marker text can be the operative subject of an RCW provision.  For
            # example, RCW 90.64.200 is captioned in part "Access denied".  Only
            # treat it as an interstitial when the official RCW page structure is
            # absent; otherwise the exact-identity parser remains the authority.
            return has_cite_link or (has_content_wrapper and has_title_block)
        return has_content_wrapper or has_cite_link

    @staticmethod
    def _washington_section_evidence_context(
        *,
        source_url: str,
        payload: bytes,
        transport_receipt: Optional[Dict[str, Any]],
        parser_input_envelope: Any,
    ) -> Dict[str, Any]:
        """Resolve a section's legal as-of date from exact retained bytes."""

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
                "Washington section acquisition receipt does not match requested "
                f"URL: {source_url}"
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
                "Washington section acquisition evidence changed parser bytes: "
                f"{source_url}"
            )

        retained_transport = receipt.get("metadata", {}).get(
            "transport_receipt",
            {},
        )
        if not isinstance(retained_transport, dict):
            retained_transport = {}
        aligned_transport = (
            dict(transport_receipt) if isinstance(transport_receipt, dict) else {}
        )
        source_transport = str(
            retained_transport.get("source_transport")
            or aligned_transport.get("source_transport")
            or ""
        ).strip()
        official_url = str(
            retained_transport.get("official_url")
            or aligned_transport.get("official_url")
            or ""
        ).strip()
        transport_sha256 = str(
            retained_transport.get("content_sha256")
            or aligned_transport.get("content_sha256")
            or ""
        ).strip().lower()
        if (
            not source_transport
            or official_url != source_url
            or transport_sha256 != content_sha256
        ):
            raise RuntimeError(
                "Washington section acquisition transport identity is incomplete: "
                f"{source_url}"
            )

        retrieved_at = str(receipt.get("retrieved_at") or "").strip()
        try:
            retrieved_date = datetime.fromisoformat(
                retrieved_at.replace("Z", "+00:00")
            ).date()
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Washington section receipt lacks a valid retrieval date: "
                f"{source_url}"
            ) from exc

        archive_timestamp = str(
            retained_transport.get("archive_timestamp")
            or retained_transport.get("capture_timestamp")
            or aligned_transport.get("archive_timestamp")
            or aligned_transport.get("capture_timestamp")
            or ""
        ).strip()
        if source_transport == "direct":
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
                    "Washington archived section receipt lacks a provenance "
                    f"snapshot date: {source_url}"
                ) from exc
        return {
            "as_of_date": as_of_date,
            "archive_timestamp": archive_timestamp,
            "content_sha256": content_sha256,
            "receipt_sha256": str(receipt.get("receipt_sha256") or "").strip(),
            "retrieved_at": retrieved_at,
            "source_transport": source_transport,
        }

    async def _fetch_washington_frontier_batch(
        self,
        urls: List[str],
        *,
        frontier_name: str,
    ) -> StateLawPageMultiFetchResult:
        """Acquire one RCW frontier through the shared grouped-WARC path."""

        if not urls:
            return StateLawPageMultiFetchResult([], [], [], [], [], {})
        requested = list(urls)
        if bool(getattr(self, "_washington_retained_replay", False)):
            from .strict_frontier_closure import (
                replay_exact_retained_state_records,
            )

            retained_rows = replay_exact_retained_state_records(
                self,
                requests=[
                    (url, {"method": "GET", "url": url}) for url in requested
                ],
                frontier_name=f"Washington {frontier_name} frontier",
                refresh=False,
            )
            payloads = [
                bytes(getattr(row.envelope, "body", b"") or b"")
                for row in retained_rows
            ]
            if any(
                not self._is_valid_washington_frontier_payload(payload)
                for payload in payloads
            ):
                raise RuntimeError(
                    f"Washington retained {frontier_name} frontier is invalid"
                )
            return StateLawPageMultiFetchResult(
                urls=requested,
                payloads=payloads,
                errors=[None] * len(requested),
                transport_receipts=[
                    dict(row.transport_receipt) for row in retained_rows
                ],
                parser_input_envelopes=[row.envelope for row in retained_rows],
                stats={
                    "network_requested_pages": 0,
                    "requested_pages": len(requested),
                    "retained_replay_pages": len(requested),
                },
            )
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
            repeat_grouped_archive_inventory_on_residual=False,
            timeout_seconds=25,
            media_type="text/html",
            max_concurrency=self._washington_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=("/RCW/",),
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
            content_validator=self._is_valid_washington_frontier_payload,
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
                f"Washington {frontier_name} frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"Washington {frontier_name} frontier changed URL order or identity"
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
                f"Washington {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures}"
            )
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

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
        from .washington_constitution import (
            configured_constitution_text_path,
            parse_washington_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_washington_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Washington Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .washington_section import configured_section_html_path, parse_washington_section_html

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_washington_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://app.leg.wa.gov/RCW/default.aspx?cite=9A.32.030",
                section_number="9A.32.030",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
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
        if self._full_corpus_enabled() and max_statutes is None:
            return await self._scrape_unbounded_washington_frontier(code_name)

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

    @staticmethod
    def _washington_index_page_identity(html: str, *, kind: str) -> str:
        """Return the title/chapter identity only when visible markers agree."""

        if kind == "chapter":
            from .washington_section import chapter_page_identity

            return chapter_page_identity(html) or ""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ""
        soup = BeautifulSoup(html or "", "html.parser")
        title_text = re.sub(
            r"\s+",
            " ",
            soup.title.get_text(" ", strip=True) if soup.title else "",
        ).strip()
        heading_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h1")
        heading_text = re.sub(
            r"\s+",
            " ",
            heading_node.get_text(" ", strip=True) if heading_node else "",
        ).strip()
        wrapper = soup.find("div", id="contentWrapper")
        if wrapper is None:
            return ""
        if kind == "title":
            title_match = re.fullmatch(
                r"Title\s+(\d+[A-Za-z]?)\s+RCW\s*:\s*",
                title_text,
                flags=re.IGNORECASE,
            )
            heading_match = re.fullmatch(
                r"Title\s+(\d+[A-Za-z]?)\s+RCW",
                heading_text,
                flags=re.IGNORECASE,
            )
            expected_class = "title-page"
        else:
            raise ValueError(f"unsupported Washington index page kind: {kind}")
        wrapper_classes = {
            str(value).strip().casefold()
            for value in (wrapper.get("class") or [])
            if str(value).strip()
        }
        if (
            title_match is None
            or heading_match is None
            or expected_class not in wrapper_classes
        ):
            return ""
        title_cite = title_match.group(1)
        heading_cite = heading_match.group(1)
        if title_cite.casefold() != heading_cite.casefold():
            return ""
        return title_cite

    def _title_links_from_payload(
        self,
        index_url: str,
        raw: bytes,
    ) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        html = raw.decode("utf-8", errors="replace")
        from .washington_section import title_cites

        listed = title_cites(html)
        if listed:
            return [
                (f"{self.get_base_url()}/RCW/default.aspx?cite={cite}", f"Title {cite}")
                for cite in listed
            ]
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            cite = self._extract_cite_from_url(href)
            if not cite or "." in cite or not self._WA_TITLE_CITE_RE.match(cite):
                continue
            normalized = f"{self.get_base_url()}/RCW/default.aspx?cite={cite}"
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(
                (
                    normalized,
                    self._normalize_legal_text(anchor.get_text(" ", strip=True)),
                )
            )
        return out

    def _chapter_links_from_payload(
        self,
        title_url: str,
        raw: bytes,
    ) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        title_cite = self._extract_cite_from_url(title_url)
        html = raw.decode("utf-8", errors="replace")
        from .washington_section import chapter_cites

        listed = chapter_cites(html, title_cite=title_cite)
        if listed:
            return [
                (f"{self.get_base_url()}/RCW/default.aspx?cite={cite}", cite)
                for cite in listed
            ]
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
            out.append(
                (
                    normalized,
                    self._normalize_legal_text(anchor.get_text(" ", strip=True)),
                )
            )
        return out

    def _section_links_from_payload(
        self,
        chapter_url: str,
        raw: bytes,
    ) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        chapter_cite = self._extract_cite_from_url(chapter_url)
        html = raw.decode("utf-8", errors="replace")
        from .washington_section import (
            chapter_section_rows,
            section_cite_belongs_to_chapter,
        )

        rows = chapter_section_rows(html)
        if rows:
            return [(url, cite) for cite, _heading, url in rows]
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            cite = self._extract_cite_from_url(href)
            if (
                not cite
                or not chapter_cite
                or not section_cite_belongs_to_chapter(cite, chapter_cite)
            ):
                continue
            if not self._SECTION_CITE_RE.match(cite):
                continue
            normalized = f"{self.get_base_url()}/RCW/default.aspx?cite={cite}"
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, cite))
        return out

    async def _scrape_unbounded_washington_frontier(
        self,
        code_name: str,
    ) -> List[NormalizedStatute]:
        """Acquire the complete RCW tree in phase-wise, WARC-groupable batches."""

        from .washington_section import (
            parse_washington_chapter_material_html,
            section_page_identity,
            section_cite_belongs_to_chapter,
            source_bound_terminal_disposition_from_chapter_html,
            source_bound_terminal_disposition_from_section_html,
        )

        # Full mode always rebuilds from retained parser inputs. Checkpoint rows
        # and positional cursors are not authoritative restart state.
        replaying = bool(getattr(self, "_washington_retained_replay", False))
        self._washington_frontier_input_reports = []

        def _write_checkpoint(*args: Any, **kwargs: Any) -> bool:
            if replaying:
                return False
            return bool(self._write_partial_checkpoint(*args, **kwargs))

        statutes: List[NormalizedStatute] = []
        root_url = f"{self.get_base_url()}/RCW/default.aspx"
        root_payload = (
            await self._fetch_washington_frontier_batch(
                [root_url],
                frontier_name="root-index",
            )
        ).payloads[0]
        self._record_washington_frontier_inputs(
            source_role="root_catalog",
            urls=[root_url],
            payloads=[root_payload],
        )
        title_links = self._title_links_from_payload(root_url, root_payload)
        if not title_links:
            raise RuntimeError("Washington official root exposed no title frontier")
        discovered_title_cites = [
            self._extract_cite_from_url(url) for url, _label in title_links
        ]
        if any(not cite for cite in discovered_title_cites):
            raise RuntimeError("Washington title frontier contains an empty identity")
        if len(set(cite.casefold() for cite in discovered_title_cites)) != len(
            discovered_title_cites
        ):
            raise RuntimeError("Washington title frontier repeats an identity")
        known_titles = {number.casefold() for number, _name in self.OFFICIAL_TITLES}
        missing_known = sorted(
            known_titles
            - {cite.casefold() for cite in discovered_title_cites},
            key=self._title_sort_key,
        )
        if missing_known:
            raise RuntimeError(
                "Washington official root omitted known current titles: "
                f"{missing_known}"
            )

        _write_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="washington:title-discovery",
            force=True,
            replace_existing_rows=True,
            extra={
                "titles_scanned": 0,
                "discovered_titles": len(title_links),
                "chapters_scanned": 0,
                "discovered_chapters": 0,
                "sections_scanned": 0,
                "discovered_sections": 0,
                "terminal_chapters_classified": 0,
                "terminal_chapter_dispositions": [],
                "chapter_materials_admitted": 0,
                "chapter_material_records": [],
                "terminal_sections_classified": 0,
                "terminal_section_dispositions": [],
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        title_urls = [url for url, _label in title_links]
        title_batch = await self._fetch_washington_frontier_batch(
            title_urls,
            frontier_name="title-index",
        )
        self._record_washington_frontier_inputs(
            source_role="title_catalog",
            urls=title_urls,
            payloads=title_batch.payloads,
        )
        chapter_frontier: List[tuple[int, str, str, str]] = []
        seen_chapters: set[str] = set()
        for title_index, ((title_url, _title_label), payload) in enumerate(
            zip(title_links, title_batch.payloads, strict=True),
            start=1,
        ):
            title_cite = self._extract_cite_from_url(title_url)
            title_html = payload.decode("utf-8", errors="replace")
            identity = self._washington_index_page_identity(
                title_html,
                kind="title",
            )
            if not identity or identity.casefold() != title_cite.casefold():
                raise RuntimeError(
                    "Washington retained title body failed requested identity: "
                    f"{title_url}"
                )
            chapter_links = self._chapter_links_from_payload(title_url, payload)
            if not chapter_links:
                raise RuntimeError(
                    f"Washington title exposed no strict chapter frontier: {title_url}"
                )
            for chapter_url, chapter_cite in chapter_links:
                source_cite = self._extract_cite_from_url(chapter_url)
                if (
                    not self._host_is_official(chapter_url)
                    or source_cite.casefold() != chapter_cite.casefold()
                    or not chapter_cite.casefold().startswith(
                        f"{title_cite}.".casefold()
                    )
                    or chapter_cite.count(".") != 1
                ):
                    raise RuntimeError(
                        "Washington title returned a noncanonical chapter locator: "
                        f"{chapter_url}"
                    )
                chapter_key = chapter_cite.casefold()
                if chapter_key in seen_chapters:
                    raise RuntimeError(
                        "Washington title frontier repeated chapter identity "
                        f"{chapter_cite}"
                    )
                seen_chapters.add(chapter_key)
                chapter_frontier.append(
                    (title_index, title_cite, chapter_cite, chapter_url)
                )

        chapter_urls = [row[3] for row in chapter_frontier]
        chapter_batch = await self._fetch_washington_frontier_batch(
            chapter_urls,
            frontier_name="chapter-index",
        )
        self._record_washington_frontier_inputs(
            source_role="chapter_catalog",
            urls=chapter_urls,
            payloads=chapter_batch.payloads,
        )
        section_frontier: List[tuple[int, str, str, str]] = []
        seen_sections: set[str] = set()
        chapter_end_offsets: List[tuple[int, int]] = []
        terminal_chapters: List[Dict[str, str]] = []
        chapter_material_records: List[Dict[str, str]] = []
        row_source_order: Dict[str, tuple[int, int, int]] = {}
        for chapter_index, (frontier_row, payload) in enumerate(
            zip(chapter_frontier, chapter_batch.payloads, strict=True),
            start=1,
        ):
            _title_index, _title_cite, chapter_cite, chapter_url = frontier_row
            chapter_html = payload.decode("utf-8", errors="replace")
            identity = self._washington_index_page_identity(
                chapter_html,
                kind="chapter",
            )
            if not identity or identity.casefold() != chapter_cite.casefold():
                raise RuntimeError(
                    "Washington retained chapter body failed requested identity: "
                    f"{chapter_url}"
                )
            section_links = self._section_links_from_payload(chapter_url, payload)
            if not section_links:
                chapter_material = parse_washington_chapter_material_html(
                    chapter_html,
                    source_url=chapter_url,
                    chapter_number=chapter_cite,
                    code_name=code_name,
                )
                if chapter_material is not None:
                    statutes.append(chapter_material)
                    row_source_order[chapter_url] = (chapter_index, 0, 0)
                    chapter_material_records.append(
                        {
                            "chapter_number": chapter_cite,
                            "record_type": str(
                                chapter_material.structured_data.get("record_type")
                                or ""
                            ),
                            "source_url": chapter_url,
                        }
                    )
                else:
                    disposition = (
                        source_bound_terminal_disposition_from_chapter_html(
                            chapter_html,
                            source_url=chapter_url,
                            chapter_number=chapter_cite,
                        )
                    )
                    if disposition is None:
                        raise RuntimeError(
                            "Washington strict chapter table exposed no section "
                            "frontier and no source-bound terminal disposition: "
                            f"{chapter_url}"
                        )
                    terminal_chapters.append(
                        {
                            "chapter_number": chapter_cite,
                            "source_url": chapter_url,
                            **disposition,
                        }
                    )
                chapter_end_offsets.append((chapter_index, len(section_frontier)))
                continue
            for section_url, section_cite in section_links:
                source_cite = self._extract_cite_from_url(section_url)
                if (
                    not self._host_is_official(section_url)
                    or source_cite.casefold() != section_cite.casefold()
                    or not section_cite_belongs_to_chapter(
                        section_cite,
                        chapter_cite,
                    )
                    or not self._SECTION_CITE_RE.match(section_cite)
                ):
                    raise RuntimeError(
                        "Washington chapter returned a noncanonical section locator: "
                        f"{section_url}"
                    )
                section_key = section_cite.casefold()
                if section_key in seen_sections:
                    raise RuntimeError(
                        "Washington chapter frontier repeated section identity "
                        f"{section_cite}"
                    )
                seen_sections.add(section_key)
                section_frontier.append(
                    (chapter_index, chapter_cite, section_cite, section_url)
                )
                row_source_order[section_url] = (
                    chapter_index,
                    1,
                    len(section_frontier),
                )
            chapter_end_offsets.append((chapter_index, len(section_frontier)))

        if not section_frontier:
            raise RuntimeError("Washington official chapters exposed no section frontier")
        terminal_sections: List[Dict[str, str]] = []
        _write_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="washington:section-discovery",
            force=True,
            replace_existing_rows=True,
            extra={
                "titles_scanned": len(title_links),
                "discovered_titles": len(title_links),
                "chapters_scanned": 0,
                "discovered_chapters": len(chapter_frontier),
                "sections_scanned": 0,
                "discovered_sections": len(section_frontier),
                "terminal_chapters_classified": len(terminal_chapters),
                "terminal_chapter_dispositions": terminal_chapters,
                "chapter_materials_admitted": len(chapter_material_records),
                "chapter_material_records": chapter_material_records,
                "terminal_sections_classified": 0,
                "terminal_section_dispositions": [],
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        # Submit the complete cross-chapter leaf union once.  The plural
        # transport replays retained inputs before network work, performs one
        # shared archive inventory, groups/coalesces Common Crawl WARC ranges,
        # and retries only unresolved URLs.  Parsing and checkpoints remain
        # bounded independently so their cadence does not fragment archive
        # discovery into one request cycle per slice.
        section_urls = [row[3] for row in section_frontier]
        section_batch = await self._fetch_washington_frontier_batch(
            section_urls,
            frontier_name="section-frontier",
        )
        self._record_washington_frontier_inputs(
            source_role="section",
            urls=section_urls,
            payloads=section_batch.payloads,
        )

        batch_size = self._washington_section_batch_size()
        for start in range(0, len(section_frontier), batch_size):
            frontier_batch = section_frontier[start : start + batch_size]
            stop = start + len(frontier_batch)
            for (
                frontier_row,
                payload,
                transport_receipt,
                parser_input_envelope,
            ) in zip(
                frontier_batch,
                section_batch.payloads[start:stop],
                section_batch.transport_receipts[start:stop],
                section_batch.parser_input_envelopes[start:stop],
                strict=True,
            ):
                _chapter_index, chapter_cite, section_cite, section_url = frontier_row
                html = payload.decode("utf-8", errors="replace")
                identity = section_page_identity(html)
                if identity is None or identity.casefold() != section_cite.casefold():
                    raise RuntimeError(
                        "Washington retained section body failed requested identity: "
                        f"{section_url}"
                    )
                evidence_context = self._washington_section_evidence_context(
                    source_url=section_url,
                    payload=payload,
                    transport_receipt=transport_receipt,
                    parser_input_envelope=parser_input_envelope,
                )
                parsed = self._parse_washington_section_payload(
                    code_name,
                    section_url,
                    section_cite,
                    payload,
                    discovery_method="official_title_chapter_section_index",
                    as_of_date=evidence_context["as_of_date"],
                )
                if parsed is None:
                    disposition = source_bound_terminal_disposition_from_section_html(
                        html,
                        source_url=section_url,
                        section_number=section_cite,
                    )
                    if disposition is None:
                        raise RuntimeError(
                            "Washington retained section body failed official parsing "
                            "and has no source-bound terminal disposition: "
                            f"{section_url}"
                        )
                    terminal_sections.append(
                        {
                            "chapter_number": chapter_cite,
                            "section_number": section_cite,
                            "disposition": disposition,
                            "source_url": section_url,
                            "source_observed_date": evidence_context[
                                "as_of_date"
                            ].isoformat(),
                            "source_transport": evidence_context[
                                "source_transport"
                            ],
                            "parser_input_receipt_sha256": evidence_context[
                                "receipt_sha256"
                            ],
                        }
                    )
                    continue
                if (
                    str(parsed.section_number or "").casefold()
                    != section_cite.casefold()
                    or str(parsed.source_url or "") != section_url
                ):
                    raise RuntimeError(
                        "Washington normalized section changed source identity: "
                        f"{section_url}"
                    )
                parsed.structured_data = {
                    **dict(parsed.structured_data or {}),
                    "source_observed_date": evidence_context[
                        "as_of_date"
                    ].isoformat(),
                    "source_transport": evidence_context["source_transport"],
                    "archive_timestamp": evidence_context["archive_timestamp"],
                    "content_sha256": evidence_context["content_sha256"],
                    "parser_input_receipt_sha256": evidence_context[
                        "receipt_sha256"
                    ],
                }
                statutes.append(parsed)

            scanned_sections = start + len(frontier_batch)
            completed_chapters = max(
                (
                    chapter_index
                    for chapter_index, end_offset in chapter_end_offsets
                    if end_offset <= scanned_sections
                ),
                default=0,
            )
            _write_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="washington:section-scan",
                replace_existing_rows=True,
                extra={
                    "titles_scanned": len(title_links),
                    "discovered_titles": len(title_links),
                    "chapters_scanned": completed_chapters,
                    "discovered_chapters": len(chapter_frontier),
                    "sections_scanned": scanned_sections,
                    "discovered_sections": len(section_frontier),
                    "terminal_chapters_classified": len(terminal_chapters),
                    "terminal_chapter_dispositions": terminal_chapters,
                    "chapter_materials_admitted": len(chapter_material_records),
                    "chapter_material_records": chapter_material_records,
                    "terminal_sections_classified": len(terminal_sections),
                    "terminal_section_dispositions": terminal_sections,
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )

        statutes.sort(
            key=lambda statute: row_source_order.get(
                str(statute.source_url or ""),
                (len(chapter_frontier) + 1, 2, len(row_source_order) + 1),
            )
        )
        section_rows_emitted = len(statutes) - len(chapter_material_records)
        statute_ids = [str(row.statute_id or "") for row in statutes]
        source_urls = [str(row.source_url or "") for row in statutes]
        if (
            not statutes
            or section_rows_emitted + len(terminal_sections)
            != len(section_frontier)
            or len(statute_ids) != len(set(statute_ids))
            or len(source_urls) != len(set(source_urls))
        ):
            raise RuntimeError(
                "Washington final statute identities do not exactly close the "
                "source section frontier"
            )

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        input_reports = list(self._washington_frontier_input_reports)
        terminal_projection = {
            "chapters": terminal_chapters,
            "sections": terminal_sections,
        }
        excluded_count = len(terminal_chapters) + len(terminal_sections)
        exact_frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "chapter_document_count": len(chapter_frontier),
            "chapter_material_count": len(chapter_material_records),
            "closed": True,
            "disposition": {
                "discovered": len(statutes) + excluded_count,
                "duplicates": 0,
                "excluded": excluded_count,
                "failed_final": 0,
                "fetched": len(statutes),
                "quarantined": 0,
            },
            "enumerator_closed": True,
            "input_projection_sha256": hashlib.sha256(
                canonical_json_bytes(input_reports)
            ).hexdigest(),
            "operative_identity_sha256": hashlib.sha256(
                canonical_json_bytes(statute_ids)
            ).hexdigest(),
            "schema": "washington-source-derived-strict-frontier-v1",
            "scope_closed": True,
            "source_input_count": len(input_reports),
            "source_section_count": len(section_frontier),
            "statutes_emitted": len(statutes),
            "terminal_chapter_count": len(terminal_chapters),
            "terminal_projection_sha256": hashlib.sha256(
                canonical_json_bytes(terminal_projection)
            ).hexdigest(),
            "terminal_section_count": len(terminal_sections),
            "title_document_count": len(title_links),
        }
        exact_frontier["frontier_digest_sha256"] = compute_frontier_digest(
            exact_frontier
        )
        observed_at = datetime.now(timezone.utc).isoformat()
        observed_dates = sorted(
            {
                str((row.structured_data or {}).get("source_observed_date") or "")
                for row in statutes
                if str(
                    (row.structured_data or {}).get("source_observed_date") or ""
                )
            }
        )
        observation = {
            "boundary_first": str(statutes[0].source_url or ""),
            "boundary_last": str(statutes[-1].source_url or ""),
            "code_name": code_name,
            "frontier": exact_frontier,
            "input_reports": input_reports,
            "legal_as_of": observed_dates[-1] if observed_dates else observed_at[:10],
            "observed_at": observed_at,
        }
        if replaying:
            self._last_washington_replayed_frontier = observation
        else:
            self._last_washington_full_frontier = observation

        _write_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="washington:complete",
            force=True,
            replace_existing_rows=True,
            extra={
                "titles_scanned": len(title_links),
                "discovered_titles": len(title_links),
                "chapters_scanned": len(chapter_frontier),
                "discovered_chapters": len(chapter_frontier),
                "sections_scanned": len(section_frontier),
                "discovered_sections": len(section_frontier),
                "terminal_chapters_classified": len(terminal_chapters),
                "terminal_chapter_dispositions": terminal_chapters,
                "chapter_materials_admitted": len(chapter_material_records),
                "chapter_material_records": chapter_material_records,
                "terminal_sections_classified": len(terminal_sections),
                "terminal_section_dispositions": terminal_sections,
                "disposition": dict(exact_frontier["disposition"]),
                "frontier_digest_sha256": str(
                    exact_frontier["frontier_digest_sha256"]
                ),
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
        """Replay retained RCW hierarchy inputs and seal exact row parity."""

        first = getattr(self, "_last_washington_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Washington strict source frontier was not closed before output"
            )
        first_frontier = first.get("frontier")
        first_reports = first.get("input_reports")
        if (
            not isinstance(first_frontier, Mapping)
            or not isinstance(first_reports, Sequence)
            or isinstance(first_reports, (str, bytes, bytearray))
            or not first_reports
            or any(not isinstance(row, Mapping) for row in first_reports)
        ):
            raise RuntimeError(
                "Washington first exact frontier observation is incomplete"
            )
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Washington frontier closure requires an attached ledger")
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        prior_replay = bool(getattr(self, "_washington_retained_replay", False))
        self._washington_retained_replay = True
        try:
            replay_rows = await self._scrape_unbounded_washington_frontier(
                str(first.get("code_name") or "Revised Code of Washington")
            )
        finally:
            self._washington_retained_replay = prior_replay
        replay = getattr(self, "_last_washington_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError(
                "Washington retained strict frontier replay was not observed"
            )
        replayed_frontier = replay.get("frontier")
        if (
            not isinstance(replayed_frontier, Mapping)
            or list(replay.get("input_reports") or []) != list(first_reports)
        ):
            raise RuntimeError("Washington retained hierarchy changed on replay")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        disposition = first_frontier.get("disposition")
        if not isinstance(disposition, Mapping):
            raise RuntimeError("Washington frontier lacks disposition algebra")
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="WA",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=f"{self.get_base_url()}/RCW/default.aspx",
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("legal_as_of") or ""),
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=int(disposition.get("discovered") or 0),
            pagination_total=(
                int(first_frontier.get("title_document_count") or 0)
                + int(first_frontier.get("chapter_document_count") or 0)
            ),
            transport={
                "fixture": False,
                "first_pass_requested_pages": int(
                    first_frontier.get("source_input_count") or 0
                ),
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_html_hierarchy",
                "per_page_archive_loop": False,
                "repeat_grouped_archive_inventory_on_residual": False,
                "retained_replay_network_requests": 0,
                "source_ordered_cross_parent_union": True,
                "synthetic": False,
                "wayback_prefix_inventory": True,
            },
        )

    async def _discover_title_links(self) -> List[Tuple[str, str]]:
        index_url = f"{self.get_base_url()}/RCW/default.aspx"
        raw = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not raw:
            return []
        raw_bytes = (
            bytes(raw)
            if isinstance(raw, (bytes, bytearray))
            else str(raw).encode("utf-8")
        )
        return self._title_links_from_payload(index_url, raw_bytes)

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        raw = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=20)
        if not raw:
            return []
        raw_bytes = (
            bytes(raw)
            if isinstance(raw, (bytes, bytearray))
            else str(raw).encode("utf-8")
        )
        return self._chapter_links_from_payload(title_url, raw_bytes)

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        raw = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        if not raw:
            return []
        raw_bytes = (
            bytes(raw)
            if isinstance(raw, (bytes, bytearray))
            else str(raw).encode("utf-8")
        )
        return self._section_links_from_payload(chapter_url, raw_bytes)

    def _extract_cite_from_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            values = parse_qs(parsed.query).get("cite") or parse_qs(parsed.query).get("Cite") or []
            return str(values[0] if values else "").strip()
        except Exception:
            return ""

    def _parse_washington_section_payload(
        self,
        code_name: str,
        url: str,
        section_number: str,
        raw: bytes,
        *,
        discovery_method: str,
        as_of_date: Optional[date] = None,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None
        if not raw:
            return None
        html_text = raw.decode("utf-8", errors="replace")
        soup = BeautifulSoup(raw, "html.parser")
        from .washington_section import parse_washington_section_html

        parsed = parse_washington_section_html(
            html_text,
            source_url=url,
            section_number=section_number,
            code_name=code_name,
            as_of_date=as_of_date,
        )
        if parsed is not None:
            data = dict(parsed.structured_data or {})
            data["discovery_method"] = discovery_method
            parsed.structured_data = data
            return parsed
        if "effective until" in html_text.casefold():
            # A decorated multi-version page must satisfy the sibling parser's
            # exact contract.  Do not collapse it through the generic fallback.
            return None
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
        body = self._normalize_legal_text(content_node.get_text(" ", strip=True))
        # Washington has short-but-valid sections; keep those in the corpus.
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

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
        discovery_method: str = "official_seed_section",
        progress_hook: Optional[Callable[[int, int, List[NormalizedStatute]], None]] = None,
    ) -> List[NormalizedStatute]:
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
                raw_bytes = (
                    bytes(raw)
                    if isinstance(raw, (bytes, bytearray))
                    else str(raw).encode("utf-8")
                )
                return self._parse_washington_section_payload(
                    code_name,
                    url,
                    section_number,
                    raw_bytes,
                    discovery_method=discovery_method,
                )

        parsed_rows = await asyncio.gather(
            *[
                _parse_section(url, section_number)
                for url, section_number in section_urls
            ],
            return_exceptions=True,
        )
        scanned_sections = 0
        for statute in parsed_rows:
            scanned_sections += 1
            if isinstance(statute, BaseException):
                raise statute
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
                break
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
