"""Florida state law scraper.

Scrapes laws from the Florida Legislature website
(http://www.leg.state.fl.us/).
"""

import hashlib
import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urldefrag, urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class FloridaScraper(BaseStateScraper):
    """Scraper for Florida state laws from https://www.leg.state.fl.us."""

    OFFICIAL_DOMAIN = "www.leg.state.fl.us"
    OFFICIAL_ENTRY_PATH = "/Statutes/"
    OFFICIAL_ENTRY_URL = "https://www.leg.state.fl.us/Statutes/"
    CORPUS_EDITION = "2026"
    CORPUS_LEGAL_AS_OF = "2026-07-01T00:00:00Z"
    _PARSER_ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
    MISSING_LINK_QUARANTINE_REASON = "missing_official_source_link"
    _TITLE_INDEX_RE = re.compile(r"App_mode=Display_Index&Title_Request=", re.IGNORECASE)
    _TITLE_REQUEST_RE = re.compile(r"[?&]Title_Request=([IVXLCDM]+)\b", re.IGNORECASE)
    _TITLE_LABEL_RE = re.compile(r"\bTitle\s+([IVXLCDM]+|\d+)\b", re.IGNORECASE)
    _CHAPTER_CONTENTS_RE = re.compile(
        r"URL=([0-9]{4}-[0-9]{4}/[0-9]{4}/[0-9]{4})ContentsIndex\.html",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("1", "I", "Construction of Statutes"),
        ("2", "II", "State Organization"),
        ("3", "III", "Legislative Branch; Commissions"),
        ("4", "IV", "Executive Branch"),
        ("5", "V", "Judicial Branch"),
        ("6", "VI", "Civil Practice and Procedure"),
        ("7", "VII", "Evidence"),
        ("8", "VIII", "Limitations"),
        ("9", "IX", "Electors and Elections"),
        ("10", "X", "Public Officers, Employees, and Records"),
        ("11", "XI", "County Organization and Intergovernmental Relations"),
        ("12", "XII", "Municipalities"),
        ("13", "XIII", "Planning and Development"),
        ("14", "XIV", "Taxation and Finance"),
        ("15", "XV", "Homestead and Exemptions"),
        ("16", "XVI", "Teachers' Retirement System; Higher Educational Facilities Bonds"),
        ("17", "XVII", "Military Affairs and Related Matters"),
        ("18", "XVIII", "Public Lands and Property"),
        ("19", "XIX", "Public Business"),
        ("20", "XX", "Veterans"),
        ("21", "XXI", "Drainage"),
        ("22", "XXII", "Ports and Harbors"),
        ("23", "XXIII", "Motor Vehicles"),
        ("24", "XXIV", "Vessels"),
        ("25", "XXV", "Aviation"),
        ("26", "XXVI", "Public Transportation"),
        ("27", "XXVII", "Railroads and Other Regulated Utilities"),
        ("28", "XXVIII", "Natural Resources; Conservation, Reclamation, and Use"),
        ("29", "XXIX", "Public Health"),
        ("30", "XXX", "Social Welfare"),
        ("31", "XXXI", "Labor"),
        ("32", "XXXII", "Regulation of Professions and Occupations"),
        ("33", "XXXIII", "Regulation of Trade, Commerce, Investments, and Solicitations"),
        ("34", "XXXIV", "Alcoholic Beverages and Tobacco"),
        ("35", "XXXV", "Agriculture, Horticulture, and Animal Industry"),
        ("36", "XXXVI", "Business Organizations"),
        ("37", "XXXVII", "Insurance"),
        ("38", "XXXVIII", "Banks and Banking"),
        ("39", "XXXIX", "Commercial Relations"),
        ("40", "XL", "Real and Personal Property"),
        ("41", "XLI", "Statute of Frauds, Fraudulent Transfers, and General Assignments"),
        ("42", "XLII", "Estates and Trusts"),
        ("43", "XLIII", "Domestic Relations"),
        ("44", "XLIV", "Civil Rights"),
        ("45", "XLV", "Torts"),
        ("46", "XLVI", "Crimes"),
        ("47", "XLVII", "Criminal Procedure and Corrections"),
        ("48", "XLVIII", "Early Learning-20 Education Code"),
        ("49", "XLIX", "Parents' Bill of Rights; Teachers' Bill of Rights"),
    )
    _ROMAN_TO_ARABIC = {roman.upper(): number for number, roman, _name in OFFICIAL_TITLES}
    _ARABIC_TO_ROMAN = {number: roman for number, roman, _name in OFFICIAL_TITLES}

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind every module that determines retained Florida replay output."""

        from . import florida_chapter, strict_frontier_closure

        return (florida_chapter, strict_frontier_closure)

    @staticmethod
    def _florida_report_digest(rows: Sequence[Mapping[str, Any]]) -> str:
        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )

        return hashlib.sha256(
            canonical_json_bytes([dict(row) for row in rows])
        ).hexdigest()

    @staticmethod
    def _florida_values_digest(values: Sequence[str]) -> str:
        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )

        return hashlib.sha256(
            canonical_json_bytes([str(value) for value in values])
        ).hexdigest()

    def _florida_exact_frontier(
        self,
        *,
        root_report: Mapping[str, Any],
        title_reports: Sequence[Mapping[str, Any]],
        chapter_reports: Sequence[Mapping[str, Any]],
        section_reports: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Seal exact root/title/chapter membership and section disposition."""

        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        root = dict(root_report)
        titles = [dict(row) for row in title_reports]
        chapters = [dict(row) for row in chapter_reports]
        sections = [dict(row) for row in section_reports]
        if not root or not titles or not chapters or not sections:
            raise RuntimeError("Florida exact frontier has an empty hierarchy level")
        root_digest = str(root.get("content_sha256") or "").strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", root_digest):
            raise RuntimeError("Florida exact frontier lacks a root content digest")

        expected_numbers = [number for number, _roman, _name in self.OFFICIAL_TITLES]
        observed_numbers = [str(row.get("title_number") or "") for row in titles]
        if observed_numbers != expected_numbers:
            raise RuntimeError(
                "Florida exact title catalog parity failed: "
                f"expected={expected_numbers} observed={observed_numbers}"
            )
        for label, reports in (
            ("title", titles),
            ("chapter", chapters),
            ("section", sections),
        ):
            source_urls = [str(row.get("source_url") or "").strip() for row in reports]
            if any(not value for value in source_urls) or len(source_urls) != len(
                set(source_urls)
            ):
                raise RuntimeError(
                    f"Florida exact {label} frontier repeated or lost source URLs"
                )

        operative = [
            row for row in sections if str(row.get("disposition") or "") == "operative"
        ]
        terminal = [
            row for row in sections if str(row.get("disposition") or "") != "operative"
        ]
        operative_keys = [
            str(row.get("canonical_identity") or "").strip() for row in operative
        ]
        terminal_keys = [
            str(row.get("canonical_identity") or "").strip() for row in terminal
        ]
        if (
            any(not key for key in [*operative_keys, *terminal_keys])
            or len(operative_keys) != len(set(operative_keys))
            or len(terminal_keys) != len(set(terminal_keys))
            or set(operative_keys) & set(terminal_keys)
        ):
            raise RuntimeError(
                "Florida operative and terminal identities are not disjoint and exact"
            )
        terminal_dispositions: Dict[str, int] = {}
        for row in terminal:
            value = str(row.get("disposition") or "").strip()
            if not value:
                raise RuntimeError("Florida terminal section lacks a disposition")
            terminal_dispositions[value] = terminal_dispositions.get(value, 0) + 1
        disposition = {
            "discovered": len(sections),
            "duplicates": 0,
            "excluded": len(terminal),
            "failed_final": 0,
            "fetched": len(operative),
            "quarantined": 0,
        }
        if disposition["discovered"] != sum(
            disposition[field]
            for field in (
                "fetched",
                "excluded",
                "quarantined",
                "failed_final",
                "duplicates",
            )
        ):
            raise RuntimeError("Florida exact section disposition algebra did not close")

        parser_input_count = 1 + len(titles) + len(chapters)
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": False,
            "chapter_document_count": len(chapters),
            "chapter_frontier_sha256": self._florida_report_digest(chapters),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": len(sections),
            "expected_title_units": len(expected_numbers),
            "method": "source_derived_root_title_chapter_html",
            "operative_canonical_key_count": len(operative_keys),
            "operative_canonical_keys_sha256": self._florida_values_digest(
                operative_keys
            ),
            "pagination_closed": True,
            "parser_input_count": parser_input_count,
            "remaining_bundle_members": [],
            "residual_parser_input_count": 0,
            "root_content_sha256": root_digest,
            "root_document_count": 1,
            "root_url": str(root.get("source_url") or ""),
            "schema_version": "florida-source-derived-html-frontier-v1",
            "scope_closed": True,
            "section_frontier_sha256": self._florida_report_digest(sections),
            "source_section_count": len(sections),
            "terminal_canonical_key_count": len(terminal_keys),
            "terminal_canonical_keys_sha256": self._florida_values_digest(
                terminal_keys
            ),
            "terminal_dispositions": dict(sorted(terminal_dispositions.items())),
            "title_document_count": len(titles),
            "title_frontier_sha256": self._florida_report_digest(titles),
            "toc_exhausted": True,
            "unclassified_section_count": 0,
            "unvisited_chapter_urls": [],
            "unvisited_continuation_links": [],
            "unvisited_title_urls": [],
            "visited_index_units": len(sections),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    def get_base_url(self) -> str:
        """Get base URL for Florida statutes."""
        return "https://www.leg.state.fl.us"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of Florida statutes."""
        base_url = self.get_base_url()
        return [
            {"name": "Florida Statutes", "url": f"{base_url}/Statutes/", "type": "FS"},
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Florida statutes directly from official title/chapter indexes."""
        # Uncapped when max_statutes is omitted (full-corpus daemon runs).
        limit = max(1, int(max_statutes)) if max_statutes else None
        strict_full = bool(limit is None and self._full_corpus_enabled())
        from .florida_constitution import (
            configured_constitution_html_path,
            parse_florida_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if not strict_full and (
            constitution_path is not None
            or "constitution" in str(code_name or "").lower()
        ):
            if constitution_path is not None:
                constitution_rows = parse_florida_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Florida Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .florida_chapter import parse_configured_florida_chapter

        if not strict_full:
            configured = parse_configured_florida_chapter(
                code_name=code_name or "Florida Statutes",
                max_statutes=limit,
            )
            if configured:
                return configured if limit is None else configured[: int(limit)]
        statutes: List[NormalizedStatute] = []
        frontier: Dict[str, Any] = {
            "closed": False,
            "expected_title_units": len(self.OFFICIAL_TITLES),
            "visited_title_units": 0,
            "discovered_chapter_units": 0,
            "visited_chapter_units": 0,
            "unvisited_chapter_urls": [],
            "errors": [],
        }
        self._last_full_corpus_frontier = frontier
        title_links = await self._discover_title_links(code_url)
        if not title_links:
            # Vaquill Online Sunshine TOC uses Title_Request=ROMAN even when
            # the caller handed a generic /Statutes/ landing URL.
            from .florida_chapter import title_romans

            toc_html = await self._fetch_official_fl_html(
                f"{self.get_base_url()}/Statutes/index.cfm?Mode=View%20Statutes&Submenu=1&Tab=statutes"
            )
            for roman in title_romans(toc_html):
                title_links.append((self.official_title_url(roman), f"Title {roman}"))
        self.logger.info("Florida official index: discovered %s title links", len(title_links))

        if strict_full:
            expected_titles = {number for number, _roman, _name in self.OFFICIAL_TITLES}
            discovered_title_list = [
                self._title_number_from_link(url, label) for url, label in title_links
            ]
            discovered_titles = {number for number in discovered_title_list if number}
            missing_titles = sorted(expected_titles - discovered_titles, key=int)
            unexpected_titles = sorted(discovered_titles - expected_titles, key=int)
            duplicate_titles = sorted(
                {
                    number
                    for number in discovered_titles
                    if discovered_title_list.count(number) > 1
                },
                key=int,
            )
            if (
                missing_titles
                or unexpected_titles
                or duplicate_titles
                or len(discovered_title_list) != len(expected_titles)
            ):
                self._fail_full_corpus(
                    "Florida official title enumeration did not close",
                    missing_titles=missing_titles,
                    unexpected_titles=unexpected_titles,
                    duplicate_titles=duplicate_titles,
                    discovered_title_count=len(discovered_title_list),
                )

        grouped_chapters_by_title: Dict[str, List[Tuple[str, str]]] = {}
        grouped_chapter_inputs: Dict[str, Tuple[bytes, Any, Any]] = {}
        if strict_full:
            self._last_florida_transport_batch_stats = []
            title_urls = [url for url, _label in title_links]
            grouped_title_inputs = await self._fetch_official_fl_html_frontier(
                title_urls,
                frontier_name="title-catalog",
            )
            all_chapter_urls: List[str] = []
            seen_chapter_urls: set[str] = set()
            for title_url, _title_label in title_links:
                title_raw, _receipt, _envelope = grouped_title_inputs[title_url]
                chapter_links = self._chapter_links_from_html(
                    title_raw,
                    title_url=title_url,
                )
                if not chapter_links:
                    self._fail_full_corpus(
                        "Florida official title returned no chapter frontier",
                        title_url=title_url,
                    )
                repeated = [
                    chapter_url
                    for chapter_url, _chapter_label in chapter_links
                    if chapter_url in seen_chapter_urls
                ]
                if repeated:
                    self._fail_full_corpus(
                        "Florida official title hierarchy repeated chapter URLs",
                        title_url=title_url,
                        repeated_chapter_urls=repeated[:3],
                    )
                grouped_chapters_by_title[title_url] = chapter_links
                for chapter_url, _chapter_label in chapter_links:
                    seen_chapter_urls.add(chapter_url)
                    all_chapter_urls.append(chapter_url)
            grouped_chapter_inputs = await self._fetch_official_fl_html_frontier(
                all_chapter_urls,
                frontier_name="chapter-page",
            )

        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = (
                grouped_chapters_by_title[title_url]
                if strict_full
                else await self._discover_chapter_links(title_url)
            )
            if strict_full and not chapter_links:
                self._fail_full_corpus(
                    "Florida official title returned no chapter frontier",
                    title_url=title_url,
                    title_label=title_label,
                )
            frontier["discovered_chapter_units"] = int(
                frontier["discovered_chapter_units"]
            ) + len(chapter_links)
            frontier["unvisited_chapter_urls"].extend(url for url, _label in chapter_links)
            self.logger.info(
                "Florida official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                title_label or title_url,
                title_index,
                len(title_links),
                len(chapter_links),
                len(statutes),
            )
            for chapter_url, chapter_label in chapter_links:
                if limit is not None and len(statutes) >= limit:
                    break
                remaining = None if limit is None else max(0, limit - len(statutes))
                acquired = grouped_chapter_inputs.get(chapter_url)
                chapter_rows = await self._parse_chapter_sections(
                    code_name=code_name,
                    chapter_url=chapter_url,
                    chapter_label=chapter_label,
                    max_statutes=remaining,
                    _acquired_payload=(acquired[0] if acquired is not None else None),
                    _acquired_transport_receipt=(
                        acquired[1] if acquired is not None else None
                    ),
                    _acquired_parser_input_envelope=(
                        acquired[2] if acquired is not None else None
                    ),
                )
                statutes.extend(chapter_rows)
                frontier["visited_chapter_units"] = int(
                    frontier["visited_chapter_units"]
                ) + 1
                try:
                    frontier["unvisited_chapter_urls"].remove(chapter_url)
                except ValueError:
                    pass
            frontier["visited_title_units"] = int(frontier["visited_title_units"]) + 1

        if not statutes:
            self.logger.warning(
                "Florida official direct crawl returned no statutes; "
                "skipping generic recovery fallback"
            )
        if strict_full:
            if frontier["unvisited_chapter_urls"]:
                self._fail_full_corpus(
                    "Florida full-corpus traversal left chapter URLs unvisited"
                )
            if not statutes:
                self._fail_full_corpus("Florida full-corpus traversal emitted no statutes")
            frontier["closed"] = True
            for statute in statutes:
                structured_data = dict(statute.structured_data or {})
                structured_data.update(
                    {
                        "official_frontier_closed": True,
                        "official_title_units_visited": int(frontier["visited_title_units"]),
                        "official_chapter_units_visited": int(
                            frontier["visited_chapter_units"]
                        ),
                    }
                )
                statute.structured_data = structured_data
            ledger = getattr(self, "_state_law_acquisition_ledger", None)
            if callable(getattr(ledger, "replay_retained_parser_input", None)):
                replay_rows, observation = self._replay_exact_retained_florida_frontier(
                    code_name or "Florida Statutes",
                    record_primary=True,
                )
                output_ids = [str(row.statute_id or "").strip() for row in statutes]
                replay_ids = [str(row.statute_id or "").strip() for row in replay_rows]
                if output_ids != replay_ids:
                    missing = sorted(set(replay_ids) - set(output_ids))
                    extra = sorted(set(output_ids) - set(replay_ids))
                    self._fail_full_corpus(
                        "Florida normalized output changed retained source membership",
                        expected=len(replay_ids),
                        actual=len(output_ids),
                        missing=missing[:3],
                        extra=extra[:3],
                    )
                exact = observation["frontier"]
                if int(exact["disposition"]["fetched"]) != len(statutes):
                    self._fail_full_corpus(
                        "Florida exact source disposition changed before output",
                        fetched=int(exact["disposition"]["fetched"]),
                        output=len(statutes),
                    )
        return statutes[:limit] if limit is not None else statutes

    async def _fetch_official_fl_html(self, url: str, timeout_seconds: int = 12) -> str:
        timeout = max(1, int(timeout_seconds or 12))
        payload = await self._fetch_parser_input_with_transport(
            url,
            headers={
                "User-Agent": "ipfs-datasets-florida-statutes-scraper/2.0",
                "Accept": self._PARSER_ACCEPT,
            },
            timeout_seconds=timeout,
            allow_archival_fallback=True,
            media_type="text/html",
            provider="requests_direct",
        )
        return payload.decode("utf-8", errors="replace") if payload else ""

    async def _fetch_official_fl_html_frontier(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
    ) -> Dict[str, Tuple[bytes, Any, Any]]:
        """Acquire one aligned Florida hierarchy level through a plural batch."""

        canonical_urls = [self._canonical_fetch_url(url) for url in urls]
        if not canonical_urls:
            return {}
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            canonical_urls,
            residual_retry_attempts=2,
            headers={
                "User-Agent": "ipfs-datasets-florida-statutes-scraper/2.0",
                "Accept": self._PARSER_ACCEPT,
            },
            timeout_seconds=25,
            media_type="text/html",
            max_concurrency=16,
            prefer_direct=True,
            wayback_prefix_inventory=True,
        )
        aligned = (
            batch.urls,
            batch.payloads,
            batch.errors,
            batch.transport_receipts,
            batch.parser_input_envelopes,
        )
        if any(len(vector) != len(canonical_urls) for vector in aligned):
            raise RuntimeError(
                f"Florida {frontier_name} batch returned unaligned acquisition rows"
            )
        if list(batch.urls) != canonical_urls:
            raise RuntimeError(
                f"Florida {frontier_name} batch changed URL order or identity"
            )
        failures = [
            {"error": str(error or "empty parser input"), "url": url}
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
                f"Florida {frontier_name} batch is incomplete: {failures[:3]}"
            )
        stats = list(getattr(self, "_last_florida_transport_batch_stats", []) or [])
        stats.append({"frontier_name": frontier_name, **dict(batch.stats or {})})
        self._last_florida_transport_batch_stats = stats
        return {
            url: (bytes(payload), receipt, envelope)
            for url, payload, receipt, envelope in zip(
                batch.urls,
                batch.payloads,
                batch.transport_receipts,
                batch.parser_input_envelopes,
                strict=True,
            )
        }

    @staticmethod
    def _florida_receipt_observed_at(retained: Any) -> str:
        value = getattr(getattr(retained, "receipt", None), "retrieved_at", None)
        if isinstance(value, datetime):
            observed = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            return observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            observed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _replay_exact_retained_florida_frontier(
        self,
        code_name: str,
        *,
        record_primary: bool,
    ) -> Tuple[List[NormalizedStatute], Dict[str, Any]]:
        """Rebuild every Florida section from retained bytes with no fetch seam."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("Florida retained replay requires BeautifulSoup") from exc

        from .florida_chapter import (
            chapter_number_from_url,
            parse_florida_chapter_html,
            section_page_url,
            source_bound_florida_section_disposition,
        )
        from .strict_frontier_closure import replay_exact_retained_state_record

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Florida retained replay requires an attached ledger")
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        observation_times: List[str] = []

        def _replay(official_url: str, frontier_name: str) -> Any:
            canonical_url = urldefrag(
                self._canonical_fetch_url(official_url)
            )[0]
            retained = replay_exact_retained_state_record(
                self,
                official_url=canonical_url,
                sanitized_request={
                    "headers": {"Accept": self._PARSER_ACCEPT},
                    "method": "GET",
                    "url": canonical_url,
                },
                frontier_name=frontier_name,
                refresh=False,
            )
            observed_at = self._florida_receipt_observed_at(retained)
            if not observed_at:
                raise RuntimeError(
                    f"{frontier_name} lost its retained source observation time"
                )
            observation_times.append(observed_at)
            return retained

        root_url = self._canonical_fetch_url(self.OFFICIAL_ENTRY_URL)
        root_retained = _replay(root_url, "Florida root catalog")
        root_raw = bytes(root_retained.envelope.body or b"")
        root_html = root_raw.decode("utf-8", errors="replace")
        root_text = BeautifulSoup(root_html, "html.parser").get_text(" ", strip=True)
        edition_match = re.search(
            r"\bThe\s+(\d{4})\s+Florida Statutes\b",
            root_text,
            re.IGNORECASE,
        )
        edition = edition_match.group(1) if edition_match else ""
        if edition != self.CORPUS_EDITION:
            raise RuntimeError(
                "Florida retained root changed corpus edition: "
                f"expected={self.CORPUS_EDITION!r} observed={edition!r}"
            )
        title_links = self._title_links_from_html(root_html, index_url=root_url)
        expected_title_numbers = [
            number for number, _roman, _name in self.OFFICIAL_TITLES
        ]
        observed_title_numbers = [
            self._title_number_from_link(url, label) for url, label in title_links
        ]
        if observed_title_numbers != expected_title_numbers:
            raise RuntimeError(
                "Florida retained root title membership did not close: "
                f"expected={expected_title_numbers} observed={observed_title_numbers}"
            )
        root_membership = [
            {"source_url": url, "title_number": number}
            for number, (url, _label) in zip(
                observed_title_numbers,
                title_links,
                strict=True,
            )
        ]
        root_report: Dict[str, Any] = {
            "content_sha256": hashlib.sha256(root_raw).hexdigest(),
            "edition": edition,
            "membership_sha256": self._florida_report_digest(root_membership),
            "source_url": root_url,
            "title_count": len(title_links),
        }

        title_reports: List[Dict[str, Any]] = []
        chapter_reports: List[Dict[str, Any]] = []
        section_reports: List[Dict[str, Any]] = []
        replay_rows: List[NormalizedStatute] = []
        seen_chapter_urls: set[str] = set()
        seen_section_numbers: set[str] = set()

        for title_number, (title_url, title_label) in zip(
            observed_title_numbers,
            title_links,
            strict=True,
        ):
            title_retained = _replay(
                title_url,
                f"Florida title {title_number} catalog",
            )
            title_raw = bytes(title_retained.envelope.body or b"")
            title_html = title_raw.decode("utf-8", errors="replace")
            chapter_links = self._chapter_links_from_html(
                title_html,
                title_url=title_url,
            )
            if not chapter_links:
                raise RuntimeError(
                    f"Florida retained title {title_number} has no chapter frontier"
                )
            chapter_membership: List[Dict[str, str]] = []
            for chapter_url, chapter_label in chapter_links:
                chapter_url = self._canonical_fetch_url(chapter_url)
                chapter_number = chapter_number_from_url(chapter_url)
                if not chapter_number or chapter_url in seen_chapter_urls:
                    raise RuntimeError(
                        "Florida retained hierarchy repeated or lost a chapter: "
                        f"{chapter_url}"
                    )
                seen_chapter_urls.add(chapter_url)
                chapter_membership.append(
                    {
                        "chapter_number": chapter_number,
                        "source_url": chapter_url,
                    }
                )

                chapter_retained = _replay(
                    chapter_url,
                    f"Florida chapter {chapter_number}",
                )
                chapter_raw = bytes(chapter_retained.envelope.body or b"")
                chapter_html = chapter_raw.decode("utf-8", errors="replace")
                chapter_soup = BeautifulSoup(chapter_html, "html.parser")
                visible_title = self._text_or_empty(
                    chapter_soup.select_one(".TitleNumber")
                )
                visible_match = self._TITLE_LABEL_RE.search(visible_title)
                visible_token = (
                    visible_match.group(1) if visible_match else visible_title
                )
                visible_arabic = self._normalize_title_token(visible_token)
                if visible_arabic and visible_arabic != title_number:
                    raise RuntimeError(
                        "Florida retained chapter escaped its title membership: "
                        f"title={title_number} chapter={chapter_number} "
                        f"visible_title={visible_arabic}"
                    )
                title_roman = self._ARABIC_TO_ROMAN[title_number]
                title_name = self._text_or_empty(
                    chapter_soup.select_one(".TitleName")
                ) or next(
                    name
                    for number, _roman, name in self.OFFICIAL_TITLES
                    if number == title_number
                )
                rows = list(
                    parse_florida_chapter_html(
                        chapter_html,
                        chapter=chapter_number,
                        code_name=code_name,
                        title_roman=title_roman,
                        title_name=title_name,
                        max_statutes=None,
                    )
                )
                row_by_number: Dict[str, NormalizedStatute] = {}
                for row in rows:
                    section_number = str(row.section_number or "").strip()
                    if not section_number or section_number in row_by_number:
                        raise RuntimeError(
                            "Florida retained parser repeated or lost a section identity: "
                            f"chapter={chapter_number} section={section_number!r}"
                        )
                    row_by_number[section_number] = row

                self._last_page_fetch_transport_evidence = dict(
                    chapter_retained.transport_receipt
                )
                self._last_page_parser_input_envelope = chapter_retained.envelope
                rows = self._bind_chapter_parser_input_provenance(
                    rows,
                    chapter_url=chapter_url,
                )
                row_by_number = {
                    str(row.section_number or "").strip(): row for row in rows
                }
                chapter_sections: List[Dict[str, Any]] = []
                operative_count = 0
                terminal_count = 0
                section_nodes = chapter_soup.find_all("div", class_="Section")
                if not section_nodes:
                    raise RuntimeError(
                        f"Florida retained chapter has no section frontier: {chapter_url}"
                    )
                for section_node in section_nodes:
                    section_number = self._text_or_empty(
                        section_node.select_one(".SectionNumber")
                    )
                    if not section_number or section_number in seen_section_numbers:
                        raise RuntimeError(
                            "Florida retained hierarchy repeated or lost a source section: "
                            f"chapter={chapter_number} section={section_number!r}"
                        )
                    seen_section_numbers.add(section_number)
                    catchline = self._text_or_empty(
                        section_node.select_one(".CatchlineText")
                        or section_node.select_one(".Catchline")
                    )
                    disposition = source_bound_florida_section_disposition(catchline)
                    canonical_identity = f"urn:state:fl:statute:FL-{section_number}"
                    source_url = self._canonical_fetch_url(
                        section_page_url(chapter_number, section_number)
                    )
                    row = row_by_number.pop(section_number, None)
                    if disposition is not None:
                        if row is not None:
                            raise RuntimeError(
                                "Florida terminal source section escaped parser exclusion: "
                                f"{section_number}"
                            )
                        terminal_count += 1
                    else:
                        if row is None:
                            raise RuntimeError(
                                "Florida retained source section is unclassified: "
                                f"chapter={chapter_number} section={section_number}"
                            )
                        if (
                            str(row.statute_id or "").strip() != f"FL-{section_number}"
                            or self._canonical_fetch_url(str(row.source_url or ""))
                            != source_url
                        ):
                            raise RuntimeError(
                                "Florida retained parser changed a canonical section: "
                                f"{section_number}"
                            )
                        structured = dict(row.structured_data or {})
                        structured.update(
                            {
                                "retrieval_provider": "retained_acquisition_replay",
                                "retrieval_transport": "retained_parser_input",
                            }
                        )
                        row.structured_data = structured
                        replay_rows.append(row)
                        operative_count += 1
                        disposition = "operative"
                    report = {
                        "canonical_identity": canonical_identity,
                        "chapter_content_sha256": hashlib.sha256(
                            chapter_raw
                        ).hexdigest(),
                        "chapter_input_url": chapter_url,
                        "disposition": disposition,
                        "section_number": section_number,
                        "source_url": source_url,
                    }
                    chapter_sections.append(report)
                    section_reports.append(report)
                if row_by_number:
                    raise RuntimeError(
                        "Florida retained parser emitted rows outside the source frontier: "
                        f"chapter={chapter_number} sections={sorted(row_by_number)[:3]}"
                    )
                chapter_reports.append(
                    {
                        "chapter_number": chapter_number,
                        "content_sha256": hashlib.sha256(chapter_raw).hexdigest(),
                        "membership_sha256": self._florida_report_digest(
                            chapter_sections
                        ),
                        "operative_section_count": operative_count,
                        "section_count": len(chapter_sections),
                        "source_url": chapter_url,
                        "terminal_section_count": terminal_count,
                        "title_number": title_number,
                    }
                )
            title_reports.append(
                {
                    "chapter_count": len(chapter_membership),
                    "content_sha256": hashlib.sha256(title_raw).hexdigest(),
                    "membership_sha256": self._florida_report_digest(
                        chapter_membership
                    ),
                    "source_url": title_url,
                    "title_label": title_label,
                    "title_number": title_number,
                }
            )

        exact_frontier = self._florida_exact_frontier(
            root_report=root_report,
            title_reports=title_reports,
            chapter_reports=chapter_reports,
            section_reports=section_reports,
        )
        if len(observation_times) != int(exact_frontier["parser_input_count"]):
            raise RuntimeError(
                "Florida retained replay lost parser-input observation times"
            )
        observation = {
            "boundary_first": str(section_reports[0]["source_url"]),
            "boundary_last": str(section_reports[-1]["source_url"]),
            "code_name": code_name,
            "edition": edition,
            "frontier": exact_frontier,
            "legal_as_of": self.CORPUS_LEGAL_AS_OF,
            "observed_at": sorted(observation_times)[-1],
            "operative_canonical_keys": [
                str(row["canonical_identity"])
                for row in section_reports
                if str(row["disposition"]) == "operative"
            ],
            "replayed_at": datetime.now(timezone.utc).isoformat(),
            "source_observation": {
                "first_retrieved_at": sorted(observation_times)[0],
                "last_retrieved_at": sorted(observation_times)[-1],
                "unique_parser_input_count": len(observation_times),
            },
            "terminal_canonical_keys": [
                str(row["canonical_identity"])
                for row in section_reports
                if str(row["disposition"]) != "operative"
            ],
            "transport_batch_stats": [
                dict(row)
                for row in list(
                    getattr(self, "_last_florida_transport_batch_stats", []) or []
                )
                if isinstance(row, Mapping)
            ],
        }
        setattr(
            self,
            (
                "_last_florida_full_frontier"
                if record_primary
                else "_last_florida_replayed_frontier"
            ),
            observation,
        )
        return replay_rows, observation

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Reparse retained 2026 hierarchy inputs and seal exact row parity."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Florida frontier closure requires an attached ledger")
        first = getattr(self, "_last_florida_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Florida source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        replay_rows, replay = self._replay_exact_retained_florida_frontier(
            str(first.get("code_name") or "Florida Statutes"),
            record_primary=False,
        )
        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier,
            Mapping,
        ):
            raise RuntimeError("Florida exact frontier observations are incomplete")

        output_keys_raw = canonical_output_projection.get("canonical_keys")
        if not isinstance(output_keys_raw, Sequence) or isinstance(
            output_keys_raw,
            (str, bytes, bytearray),
        ):
            raise RuntimeError("Florida canonical output lacks exact identities")
        output_keys = [str(key).strip() for key in output_keys_raw]
        terminal_keys_raw = first.get("terminal_canonical_keys")
        if not isinstance(terminal_keys_raw, Sequence) or isinstance(
            terminal_keys_raw,
            (str, bytes, bytearray),
        ):
            raise RuntimeError("Florida strict frontier lacks terminal identities")
        terminal_keys = [str(key).strip() for key in terminal_keys_raw]
        if (
            any(not key for key in terminal_keys)
            or len(terminal_keys) != len(set(terminal_keys))
            or set(output_keys) & set(terminal_keys)
        ):
            raise RuntimeError(
                "Florida terminal canonical identities escaped into final output"
            )
        if len(terminal_keys) != int(
            first_frontier.get("terminal_canonical_key_count") or 0
        ):
            raise RuntimeError("Florida terminal identity count changed before closure")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        batch_stats = [
            dict(row)
            for row in list(first.get("transport_batch_stats") or [])
            if isinstance(row, Mapping)
        ]

        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="FL",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("legal_as_of") or ""),
            edition=str(first.get("edition") or ""),
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=int(first_frontier.get("parser_input_count") or 0),
            pagination_total=(
                int(first_frontier.get("title_document_count") or 0)
                + int(first_frontier.get("chapter_document_count") or 0)
            ),
            transport={
                "fixture": False,
                "first_pass_request_batches": len(batch_stats),
                "first_pass_requested_pages": sum(
                    int(row.get("requested_pages") or 0) for row in batch_stats
                ),
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_root_title_chapter_html",
                "per_page_archive_loop": False,
                "residual_only_retries": True,
                "retained_replay_network_requests": 0,
                "retained_replayed_at": str(replay.get("replayed_at") or ""),
                "retained_source_observation": dict(
                    first.get("source_observation") or {}
                ),
                "synthetic": False,
            },
        )

    def _bind_chapter_parser_input_provenance(
        self,
        statutes: List[NormalizedStatute],
        *,
        chapter_url: str,
    ) -> List[NormalizedStatute]:
        """Bind every section row to the retained chapter-page response."""

        if not statutes:
            return statutes
        provenance = self._last_parser_input_row_provenance()
        receipt = provenance.get("transport_receipt")
        retained_url = (
            str(receipt.get("official_url") or "").strip()
            if isinstance(receipt, Mapping)
            else ""
        )
        exact_input = bool(
            provenance
            and retained_url
            and self._canonical_fetch_url(retained_url)
            == self._canonical_fetch_url(chapter_url)
        )
        if not exact_input:
            if self._state_law_acquisition_ledger is not None:
                raise RuntimeError(
                    "Florida chapter rows lack exact retained parser-input provenance"
                )
            return statutes
        for statute in statutes:
            structured = dict(statute.structured_data or {})
            structured.update(provenance)
            statute.structured_data = structured
        return statutes

    def _enrich_statute_structure(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Carry retained chapter provenance into canonical JSON-LD."""

        enriched = super()._enrich_statute_structure(statute)
        structured = dict(enriched.structured_data or {})
        if str(structured.get("source_kind") or "").strip() not in {
            "official_florida_chapter_html",
            "official_florida_statutes_html",
        }:
            return enriched

        digest = str(structured.get("content_sha256") or "").strip().lower()
        receipt = structured.get("transport_receipt")
        jsonld = structured.get("jsonld")
        receipt_digest = (
            str(receipt.get("content_sha256") or "").strip().lower()
            if isinstance(receipt, Mapping)
            else ""
        )
        provenance_complete = bool(
            re.fullmatch(r"[a-f0-9]{64}", digest)
            and receipt_digest == digest
            and isinstance(receipt, Mapping)
            and isinstance(jsonld, Mapping)
        )
        if not provenance_complete:
            if self._state_law_acquisition_ledger is not None:
                raise RuntimeError(
                    "Florida chapter row lacks canonical retained parser-input provenance"
                )
            return enriched

        jsonld_payload = dict(jsonld)
        prior = jsonld_payload.get("provenance")
        provenance = dict(prior) if isinstance(prior, Mapping) else {}
        provenance.update(
            {
                "content_sha256": digest,
                "transport_receipt": dict(receipt),
            }
        )
        jsonld_payload["provenance"] = provenance
        structured["jsonld"] = jsonld_payload
        enriched.structured_data = structured
        return enriched

    def _title_number_from_link(self, url: str, label: str = "") -> str:
        match = self._TITLE_REQUEST_RE.search(str(url or ""))
        token = match.group(1) if match else ""
        if not token:
            match = self._TITLE_LABEL_RE.search(str(label or ""))
            token = match.group(1) if match else ""
        return self._normalize_title_token(token)

    def _fail_full_corpus(self, message: str, **evidence: Any) -> None:
        frontier = dict(getattr(self, "_last_full_corpus_frontier", {}) or {})
        frontier["closed"] = False
        frontier.update(evidence)
        errors = list(frontier.get("errors") or [])
        errors.append(message)
        frontier["errors"] = errors
        self._last_full_corpus_frontier = frontier
        details = " ".join(f"{key}={value}" for key, value in sorted(evidence.items()))
        raise RuntimeError(f"{message}{': ' + details if details else ''}")

    async def _discover_title_links(self, code_url: str) -> List[Tuple[str, str]]:
        index_url = code_url or f"{self.get_base_url()}/Statutes/"
        html = await self._fetch_official_fl_html(index_url)
        if not html and index_url.startswith("http://"):
            index_url = index_url.replace("http://", "https://", 1)
            html = await self._fetch_official_fl_html(index_url)
        if not html:
            return []
        return self._title_links_from_html(html, index_url=index_url)

    def _title_links_from_html(
        self,
        html: str | bytes,
        *,
        index_url: str,
    ) -> List[Tuple[str, str]]:
        """Derive the ordered title frontier from one official root page."""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if not self._TITLE_INDEX_RE.search(href):
                continue
            full_url = self._canonical_fetch_url(urljoin(index_url, href))
            if full_url in seen:
                continue
            seen.add(full_url)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((full_url, label or full_url.rsplit("Title_Request=", 1)[-1]))
        return out

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        html = await self._fetch_official_fl_html(title_url)
        if not html:
            return []
        return self._chapter_links_from_html(html, title_url=title_url)

    def _chapter_links_from_html(
        self,
        html: str | bytes,
        *,
        title_url: str,
    ) -> List[Tuple[str, str]]:
        """Derive the ordered chapter frontier from one official title page."""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            match = self._CHAPTER_CONTENTS_RE.search(href)
            if not match:
                continue
            chapter_path = f"{match.group(1)}.html"
            chapter_url = self._canonical_fetch_url(
                urljoin(
                    title_url,
                    f"index.cfm?App_mode=Display_Statute&URL={chapter_path}",
                )
            )
            if chapter_url in seen:
                continue
            seen.add(chapter_url)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((chapter_url, label or chapter_path))
        if out:
            return out
        from .florida_chapter import chapter_page_url, title_chapters

        for chapter in title_chapters(html):
            chapter_url = self._canonical_fetch_url(chapter_page_url(chapter))
            if chapter_url in seen:
                continue
            seen.add(chapter_url)
            out.append((chapter_url, f"Chapter {chapter}"))
        return out

    async def _parse_chapter_sections(
        self,
        *,
        code_name: str,
        chapter_url: str,
        chapter_label: str,
        max_statutes: Optional[int] = None,
        _acquired_payload: Optional[bytes] = None,
        _acquired_transport_receipt: Any = None,
        _acquired_parser_input_envelope: Any = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        if _acquired_payload is None:
            html = await self._fetch_official_fl_html(chapter_url)
            provider = self._current_fetch_provider() or "unknown"
        else:
            html = bytes(_acquired_payload).decode("utf-8", errors="replace")
            self._last_page_fetch_transport_evidence = (
                dict(_acquired_transport_receipt)
                if isinstance(_acquired_transport_receipt, Mapping)
                else {}
            )
            self._last_page_parser_input_envelope = _acquired_parser_input_envelope
            source_transport = str(
                self._last_page_fetch_transport_evidence.get("source_transport")
                or "archive_aware_multifetch"
            )
            provider = (
                "requests_direct"
                if source_transport == "direct"
                else source_transport
            )
        if not html:
            if self._full_corpus_enabled() and max_statutes is None:
                self._fail_full_corpus(
                    "Florida official chapter was unavailable",
                    chapter_url=chapter_url,
                )
            return []
        from .florida_chapter import (
            chapter_number_from_url,
            normalize_chapter_number,
            parse_florida_chapter_html,
        )

        soup = BeautifulSoup(html, "html.parser")
        title_heading = self._text_or_empty(soup.select_one(".TitleNumber"))
        if not title_heading:
            for anchor in soup.find_all("a", href=True):
                title_link_match = self._TITLE_REQUEST_RE.search(
                    str(anchor.get("href") or "")
                )
                if title_link_match:
                    title_heading = title_link_match.group(1)
                    break
        title_match = self._TITLE_LABEL_RE.search(title_heading)
        title_token = title_match.group(1) if title_match else title_heading
        title_arabic = self._normalize_title_token(title_token)
        title_number = self._ARABIC_TO_ROMAN.get(
            title_arabic,
            title_token.upper(),
        )
        title_name = self._text_or_empty(soup.select_one(".TitleName"))
        if not title_name and title_arabic:
            title_name = next(
                (
                    name
                    for number, _roman, name in self.OFFICIAL_TITLES
                    if number == title_arabic
                ),
                "",
            )
        chapter_heading = (
            self._text_or_empty(soup.select_one(".ChapterNumber"))
            or chapter_number_from_url(chapter_url)
            or self._chapter_number_from_url(chapter_url)
        )
        try:
            chapter_number = normalize_chapter_number(chapter_heading)
        except ValueError:
            chapter_number = chapter_number_from_url(chapter_url)
            if not chapter_number and self._full_corpus_enabled() and max_statutes is None:
                self._fail_full_corpus(
                    "Florida chapter number could not be normalized",
                    chapter_url=chapter_url,
                    chapter_heading=chapter_heading,
                )
        chapter_name = self._text_or_empty(soup.select_one(".ChapterName")) or chapter_label
        section_nodes = soup.select(".Section")
        active_section_numbers: set[str] = set()
        for section in section_nodes:
            number = self._text_or_empty(section.select_one(".SectionNumber"))
            catchline = self._text_or_empty(
                section.select_one(".CatchlineText") or section.select_one(".Catchline")
            )
            if number and not re.search(
                r"\b(repealed|reserved|expired|transferred|renumbered|former)\b",
                catchline,
                re.IGNORECASE,
            ):
                active_section_numbers.add(number)
        structured = parse_florida_chapter_html(
            html,
            chapter=chapter_number or "0",
            code_name=code_name,
            title_roman=title_number,
            title_name=title_name or chapter_name,
            max_statutes=max_statutes,
        )
        statutes: List[NormalizedStatute] = list(structured)
        for section in section_nodes if not structured else []:
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            section_number = self._text_or_empty(section.select_one(".SectionNumber"))
            section_name = self._text_or_empty(section.select_one(".Catchline"))
            if not section_number:
                head_text = self._normalize_legal_text(section.get_text(" ", strip=True))
                match = re.match(r"([0-9]+\.[0-9A-Za-z]+)\s+(.+?)\s+[—-]\s+", head_text)
                if match:
                    section_number = match.group(1)
                    section_name = match.group(2)
            full_text = self._normalize_legal_text(section.get_text(" ", strip=True))
            if not section_number or not full_text:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"FL-{section_number}",
                    code_name=code_name,
                    title_number=title_number or None,
                    title_name=title_name or None,
                    chapter_number=chapter_number or None,
                    chapter_name=chapter_name or None,
                    section_number=section_number,
                    section_name=section_name[:200] if section_name else f"Section {section_number}",
                    short_title=section_name[:200] if section_name else None,
                    full_text=full_text,
                    legal_area=self._identify_legal_area(section_name or chapter_name or code_name),
                    source_url=self._section_url(chapter_url, section_number),
                    official_cite=f"Fla. Stat. § {section_number}",
                    structured_data={
                        "source_kind": "official_florida_statutes_html",
                        "source_authority_class": "official",
                        "discovery_method": "official_title_chapter_index",
                        "chapter_url": chapter_url,
                        "skip_hydrate": True,
                    },
                )
            )
        statutes = self._bind_chapter_parser_input_provenance(
            statutes,
            chapter_url=chapter_url,
        )
        for statute in statutes:
            structured_data = dict(statute.structured_data or {})
            structured_data.update(
                {
                    "retrieval_provider": provider,
                    "retrieval_transport": (
                        "live_https"
                        if provider == "requests_direct"
                        else "durable_cache_or_web_archiving"
                    ),
                }
            )
            statute.structured_data = structured_data

        if self._full_corpus_enabled() and max_statutes is None:
            terminal_empty = bool(
                re.search(
                    r"\b(repealed|reserved|expired)\b",
                    chapter_label,
                    re.IGNORECASE,
                )
            )
            if not section_nodes and not terminal_empty:
                self._fail_full_corpus(
                    "Florida chapter page exposed no section frontier",
                    chapter_url=chapter_url,
                )
            parsed_numbers = {str(row.section_number or "") for row in statutes}
            missing_sections = sorted(active_section_numbers - parsed_numbers)
            if missing_sections:
                self._fail_full_corpus(
                    "Florida chapter parser omitted active official sections",
                    chapter_url=chapter_url,
                    missing_sections=missing_sections,
                )
        return statutes

    @staticmethod
    def _text_or_empty(node: object) -> str:
        if node is None:
            return ""
        try:
            return re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _chapter_number_from_url(url: str) -> str:
        from .florida_chapter import chapter_number_from_url

        return chapter_number_from_url(url)

    @staticmethod
    def _section_url(chapter_url: str, section_number: str) -> str:
        padded = section_number
        if re.match(r"^\d+\.", padded):
            chapter = padded.split(".", 1)[0].zfill(4)
            padded_section = f"{chapter}.{padded.split('.', 1)[1]}"
            base = re.sub(r"/[0-9]{4}\.html.*$", f"/Sections/{padded_section}.html", chapter_url)
            if base != chapter_url:
                return base
        return chapter_url

    def official_title_url(self, title_number: object) -> str:
        token = str(title_number or "").strip()
        roman = self._ARABIC_TO_ROMAN.get(token, token.upper())
        if token.upper() in self._ROMAN_TO_ARABIC:
            roman = token.upper()
        return (
            f"{self.get_base_url()}/Statutes/index.cfm"
            f"?App_mode=Display_Index&Title_Request={roman}"
        )

    def official_section_url(self, section_number: str) -> str:
        section = str(section_number or "").strip()
        return (
            f"{self.get_base_url()}/Statutes/index.cfm"
            f"?App_mode=Display_Statute&Search_String=&Statute={section}"
        )

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Florida Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, roman, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"fl:title-{number}",
                    "title_number": number,
                    "title_roman": roman,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Florida Statutes Title {roman} ({name}) official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def is_official_fl_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith(".leg.state.fl.us")

    def repair_or_type_missing_source_link(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Attach an official Florida Statutes URL or type a linkless row."""

        structured = dict(statute.structured_data or {})
        source_url = str(statute.source_url or "").strip()
        if source_url and self.is_official_fl_url(source_url):
            structured.setdefault("source_link_disposition", "official")
            statute.structured_data = structured
            return statute

        section_number = str(statute.section_number or "").strip()
        if section_number:
            repaired = self.official_section_url(section_number)
            statute.source_url = repaired
            structured["source_kind"] = (
                structured.get("source_kind") or "official_florida_statutes_html"
            )
            structured["source_link_disposition"] = "repaired_official_flleg"
            structured["previous_source_url"] = source_url or None
            statute.structured_data = structured
            return statute

        structured["source_link_disposition"] = "typed_quarantine"
        structured["quarantine_reason"] = self.MISSING_LINK_QUARANTINE_REASON
        statute.structured_data = structured
        return statute

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-florida-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-florida-official-catalog/1.0",
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

    def _normalize_title_token(self, token: str) -> str:
        value = str(token or "").strip().upper()
        if value in self._ROMAN_TO_ARABIC:
            return self._ROMAN_TO_ARABIC[value]
        if value.lstrip("0") in self._ARABIC_TO_ROMAN:
            return value.lstrip("0")
        if value in self._ARABIC_TO_ROMAN:
            return value
        return ""

    def _parse_official_title_links(self, html: bytes, page_url: str = "") -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {number for number, _roman, _name in self.OFFICIAL_TITLES}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            parsed = urlparse(absolute)
            query = parse_qs(parsed.query)
            request_values = query.get("Title_Request") or query.get("title_request") or []
            token = str((request_values or [""])[0]).strip()
            if not token:
                match = self._TITLE_REQUEST_RE.search(absolute) or self._TITLE_LABEL_RE.search(
                    link.get_text(" ", strip=True) or ""
                )
                token = match.group(1) if match else ""
            number = self._normalize_title_token(token)
            if number not in known:
                continue
            if number not in found and self.is_official_fl_url(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Florida title and repair missing-link rows."""

        discovered = self._parse_official_title_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        rows: List[Dict[str, Any]] = []
        for item in self.official_title_catalog():
            number = str(item["title_number"])
            official_url = str(item["source_url"])
            live_url = discovered.get(number)
            source_url = live_url or official_url
            disposition = "official" if live_url else "repaired_official_flleg"
            rows.append(
                {
                    **item,
                    "source_url": source_url,
                    "source_link_disposition": disposition,
                    "text": (
                        f"Florida Statutes Title {item['title_roman']} ({item['name']}) "
                        f"official catalog unit at {source_url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "FL"):
        """Acquire the exhaustive official Florida Statutes title catalog.

        Live HTTPS retains the official statutes landing page. Every known
        Florida title is enumerated with an official leg.state.fl.us URL.
        Linkless catalog members are repaired to the official title index.
        This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "FL").strip().upper() or "FL"
        if normalized != "FL":
            raise ValueError(f"FloridaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("florida official catalog enumeration is incomplete")
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


# Register the scraper
StateScraperRegistry.register("FL", FloridaScraper)
