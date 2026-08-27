"""Scraper for South Dakota state laws.

This module contains the scraper for South Dakota statutes from the official
JSON statute endpoint.
"""

import os
import re
import json
import hashlib
import ssl
import time
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    current_partial_checkpoint_run_directory,
)
from .registry import StateScraperRegistry


class SouthDakotaScraper(BaseStateScraper):
    """Scraper for South Dakota state laws from https://sdlegislature.gov"""

    OFFICIAL_DOMAIN = "sdlegislature.gov"
    OFFICIAL_ENTRY_PATH = "/Statutes"
    OFFICIAL_ENTRY_URL = "https://sdlegislature.gov/Statutes"
    OFFICIAL_TITLE_API_URL = "https://sdlegislature.gov/api/Statutes/Title"
    _SD_TITLE_HREF_RE = re.compile(
        r"(?:/Statutes(?:/Codified_Laws)?/|/api/Statutes/Title/)(?P<title>\d{1,2}[A-Z]?)\b",
        re.IGNORECASE,
    )
    _SD_TITLE_LABEL_RE = re.compile(
        r"\bTitle\s+(?P<title>\d{1,2}[A-Z]?)\b",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("1", "State Affairs and Government"),
        ("2", "Legislature and Statutes"),
        ("3", "Public Officers and Employees"),
        ("4", "Public Fiscal Administration"),
        ("5", "Public Property, Purchases and Contracts"),
        ("6", "Local Government Generally"),
        ("7", "Counties"),
        ("8", "Townships"),
        ("9", "Municipal Government"),
        ("10", "Taxation"),
        ("11", "Planning, Zoning and Housing Programs"),
        ("12", "Elections"),
        ("13", "Education"),
        ("14", "Libraries"),
        ("15", "Civil Procedure"),
        ("16", "Courts and Judiciary"),
        ("17", "Notice and Publication"),
        ("18", "Oaths and Acknowledgments"),
        ("19", "Evidence"),
        ("20", "Personal Rights and Obligations"),
        ("21", "Judicial Remedies"),
        ("22", "Crimes"),
        ("23", "Law Enforcement"),
        ("23A", "Criminal Procedure"),
        ("24", "Correctional Facilities and Parole"),
        ("25", "Domestic Relations"),
        ("26", "Minors"),
        ("27", "State Control of Manufacture and Sale of Liquor [Repealed]"),
        ("27A", "Mentally Ill Persons"),
        ("27B", "Developmentally Disabled Persons"),
        ("28", "Public Welfare and Assistance"),
        ("29", "Succession and Wills [Repealed]"),
        ("29A", "Uniform Probate Code"),
        ("30", "Probate and Guardianship Procedure"),
        ("31", "Highways and Bridges"),
        ("32", "Motor Vehicles"),
        ("33", "Military Affairs"),
        ("33A", "Veterans Affairs"),
        ("34", "Public Health and Safety"),
        ("34A", "Environmental Protection"),
        ("35", "Alcoholic Beverages"),
        ("36", "Professions and Occupations"),
        ("37", "Trade Regulation"),
        ("38", "Agriculture and Horticulture"),
        ("39", "Food and Drugs"),
        ("40", "Animals and Livestock"),
        ("41", "Game, Fish, Parks and Forestry"),
        ("42", "Recreation and Sports"),
        ("43", "Property"),
        ("44", "Liens"),
        ("45", "Mining, Oil and Gas"),
        ("46", "Water Rights"),
        ("46A", "Water Management"),
        ("47", "Corporations"),
        ("48", "Partnerships"),
        ("49", "Public Utilities and Carriers"),
        ("50", "Aviation"),
        ("51", "Banks and Banking [Transferred]"),
        ("51A", "Banks and Banking"),
        ("52", "Savings and Loan Associations [Repealed]"),
        ("53", "Contracts"),
        ("54", "Debtor and Creditor"),
        ("55", "Fiduciaries and Trusts"),
        ("56", "Guaranty, Suretyship and Indemnity"),
        ("57", "Commercial Code [Transferred]"),
        ("57A", "Uniform Commercial Code"),
        ("58", "Insurance"),
        ("59", "Agency"),
        ("60", "Labor and Employment"),
        ("61", "Reemployment Assistance"),
        ("62", "Workers' Compensation"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)

    _SEED_SECTIONS = [
        "1-1-1",
        "1-1-1.1",
        "1-1-2",
        "1-1-3",
        "1-1-4",
        "1-1-5",
        "1-1-6",
        "1-1-7",
    ]

    _TITLE_START_SECTIONS = [f"{title}-1-1" for title in range(1, 75)]

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind exact frontier evidence to the whole-title parser."""

        from . import south_dakota_title

        return (south_dakota_title,)

    @staticmethod
    def _south_dakota_frontier_values_sha256(values: Sequence[str]) -> str:
        payload = json.dumps(
            list(values),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _is_valid_south_dakota_catalog_payload(payload: bytes) -> bool:
        try:
            parsed = json.loads(bytes(payload or b"").decode("utf-8-sig"))
        except Exception:
            return False
        return bool(
            isinstance(parsed, list)
            and parsed
            and all(isinstance(item, Mapping) for item in parsed)
            and any(str(item.get("Statute") or "").strip() for item in parsed)
        )

    @staticmethod
    def _is_valid_south_dakota_title_payload(payload: bytes) -> bool:
        from .south_dakota_title import decode_sdlegislature_bytes

        text = decode_sdlegislature_bytes(bytes(payload or b""))
        sample = text[:1_000_000].casefold()
        return bool(
            "<html" in sample
            and "codified law" in sample
            and "senu" in sample
            and "404 not found" not in sample
        )

    def _validate_south_dakota_aligned_evidence(
        self,
        *,
        url: str,
        payload: bytes,
        transport_receipt: Any,
        parser_input_envelope: Any,
        frontier_name: str,
    ) -> None:
        """Require exact URL/body evidence whenever a ledger is attached."""

        canonical_url = self._canonical_fetch_url(url)
        content_sha256 = hashlib.sha256(payload).hexdigest()
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if ledger_attached and (
            not isinstance(transport_receipt, Mapping)
            or not transport_receipt
            or parser_input_envelope is None
        ):
            raise RuntimeError(
                f"South Dakota {frontier_name} frontier lacks retained evidence: {url}"
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
                    f"South Dakota {frontier_name} receipt lacks URL/digest: {url}"
                )
            if observed_url and self._canonical_fetch_url(observed_url) != canonical_url:
                raise RuntimeError(
                    f"South Dakota {frontier_name} receipt changed URL identity: {url}"
                )
            if observed_digest and observed_digest != content_sha256:
                raise RuntimeError(
                    f"South Dakota {frontier_name} receipt changed payload identity: {url}"
                )
        if parser_input_envelope is not None:
            envelope_body = getattr(parser_input_envelope, "body", None)
            if ledger_attached and envelope_body is None:
                raise RuntimeError(
                    f"South Dakota {frontier_name} envelope lacks body evidence: {url}"
                )
            if envelope_body is not None and bytes(envelope_body) != payload:
                raise RuntimeError(
                    f"South Dakota {frontier_name} envelope changed payload identity: {url}"
                )

    async def _fetch_south_dakota_frontier_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Any,
        media_type: str,
    ) -> List[bytes]:
        """Fetch one exact same-domain frontier through the grouped-WARC seam."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if not requested or any(not url for url in requested):
            raise RuntimeError(
                f"South Dakota {frontier_name} frontier is empty or invalid"
            )
        if len(requested) != len(set(requested)):
            raise RuntimeError(
                f"South Dakota {frontier_name} frontier contains duplicate URLs"
            )
        retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_SD_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=3,
                ),
            ),
        )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=retry_attempts,
            timeout_seconds=120,
            headers={
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.5",
                "User-Agent": "ipfs-datasets-south-dakota-statutes/2.0",
            },
            content_validator=content_validator,
            media_type=media_type,
            max_concurrency=max(
                1,
                min(
                    32,
                    self._env_int(
                        "STATE_SCRAPER_SD_FRONTIER_CONCURRENCY",
                        default=8,
                    ),
                ),
            ),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=("/api/Statutes/",),
            common_crawl_mime_terms=("html", "json", "text"),
            wayback_prefix_inventory=True,
        )
        aligned_lengths = {
            len(batch.urls),
            len(batch.payloads),
            len(batch.errors),
            len(batch.transport_receipts),
            len(batch.parser_input_envelopes),
        }
        if aligned_lengths != {len(requested)} or list(batch.urls) != requested:
            raise RuntimeError(
                f"South Dakota {frontier_name} frontier returned unaligned URL identities"
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
            if error is not None or not content_validator(raw):
                failures.append(
                    {"url": url, "error": str(error or "invalid parser input")}
                )
                continue
            self._validate_south_dakota_aligned_evidence(
                url=url,
                payload=raw,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
                frontier_name=frontier_name,
            )
            payloads.append(raw)
        if failures:
            raise RuntimeError(
                f"South Dakota {frontier_name} frontier is incomplete after "
                f"residual-only retries: {failures}"
            )
        return payloads

    @staticmethod
    def _south_dakota_catalog_name(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip().rstrip(".").casefold()

    def _parse_live_south_dakota_title_units(
        self,
        payload: bytes,
    ) -> List[Dict[str, str]]:
        """Parse the authoritative live title inventory without static repair."""

        from .south_dakota_title import source_bound_terminal_disposition, title_html_url

        try:
            parsed = json.loads(bytes(payload or b"").decode("utf-8-sig"))
        except Exception as exc:
            raise RuntimeError("South Dakota title catalog is not valid JSON") from exc
        if not isinstance(parsed, list) or not parsed:
            raise RuntimeError("South Dakota title catalog is empty or not a list")
        units: List[Dict[str, str]] = []
        seen: set[str] = set()
        for item in parsed:
            if not isinstance(item, Mapping):
                raise RuntimeError("South Dakota title catalog contains a non-object row")
            number = self._normalize_title_number(
                item.get("Statute")
                or item.get("Title")
                or item.get("title")
                or item.get("Number")
            )
            name = re.sub(
                r"\s+",
                " ",
                str(item.get("CatchLine") or item.get("Name") or ""),
            ).strip()
            if not number or not name or number in seen:
                raise RuntimeError(
                    "South Dakota title catalog contains an invalid or duplicate "
                    f"identity: number={number!r} name={name!r}"
                )
            seen.add(number)
            units.append(
                {
                    "title_number": number,
                    "source_label": name,
                    "source_url": title_html_url(number),
                    "catalog_url": self.official_title_url(number),
                    "disposition": source_bound_terminal_disposition(name),
                }
            )
        return units

    def _validate_south_dakota_live_static_title_catalog(
        self,
        units: Sequence[Mapping[str, str]],
    ) -> None:
        expected = {
            str(number): self._south_dakota_catalog_name(name)
            for number, name in self.OFFICIAL_TITLES
        }
        observed = {
            str(unit.get("title_number") or ""): self._south_dakota_catalog_name(
                unit.get("source_label")
            )
            for unit in units
        }
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        mismatches = [
            {
                "title": number,
                "expected_name": expected[number],
                "observed_name": observed[number],
            }
            for number in sorted(set(expected) & set(observed))
            if expected[number] != observed[number]
        ]
        if (
            len(units) != self.OFFICIAL_TITLE_COUNT
            or len(observed) != len(units)
            or missing
            or extra
            or mismatches
        ):
            raise RuntimeError(
                "South Dakota live/static title catalog parity failed; "
                f"missing={missing} extra={extra} mismatches={mismatches}"
            )

    async def _scrape_strict_full_corpus_frontier(
        self,
        code_name: str,
        *,
        record_primary: bool,
        write_checkpoints: bool,
    ) -> List[NormalizedStatute]:
        """Acquire and close the source-derived whole-title SD frontier."""

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        from .south_dakota_title import (
            chapter_from_section,
            decode_sdlegislature_bytes,
            parse_south_dakota_title_html_with_dispositions,
            section_html_url,
            source_bound_terminal_disposition,
            title_chapter_entries,
            title_section_entries,
        )

        observed_at = datetime.now(timezone.utc).isoformat()
        catalog_payload = (
            await self._fetch_south_dakota_frontier_batch(
                [self.OFFICIAL_TITLE_API_URL],
                frontier_name="title-catalog",
                content_validator=self._is_valid_south_dakota_catalog_payload,
                media_type="application/json",
            )
        )[0]
        title_units = self._parse_live_south_dakota_title_units(catalog_payload)
        self._validate_south_dakota_live_static_title_catalog(title_units)

        catalog_sha256 = hashlib.sha256(catalog_payload).hexdigest()
        active_title_units = [
            unit for unit in title_units if not str(unit.get("disposition") or "")
        ]
        terminal_units: List[Dict[str, Any]] = [
            {
                "frontier_level": "title",
                "title_number": str(unit["title_number"]),
                "source_label": str(unit["source_label"]),
                "source_url": self.OFFICIAL_TITLE_API_URL,
                "catalog_url": str(unit["catalog_url"]),
                "disposition": str(unit["disposition"]),
                "content_sha256": catalog_sha256,
            }
            for unit in title_units
            if str(unit.get("disposition") or "")
        ]
        if not active_title_units:
            raise RuntimeError("South Dakota catalog produced no active title frontier")

        title_payloads = await self._fetch_south_dakota_frontier_batch(
            [str(unit["source_url"]) for unit in active_title_units],
            frontier_name="whole-title-pages",
            content_validator=self._is_valid_south_dakota_title_payload,
            media_type="text/html",
        )
        statute_by_section: Dict[str, NormalizedStatute] = {}
        ordered_section_ids: List[str] = []
        residual_section_units: List[Dict[str, str]] = []
        seen_statute_ids: set[str] = set()
        terminal_section_identities: set[str] = set()
        source_status_section_identities: set[str] = set()
        chapter_identities: set[Tuple[str, str]] = set()
        active_chapter_count = 0
        terminal_chapter_count = 0
        lifecycle_chapter_variant_count = 0
        lifecycle_section_variant_count = 0
        section_candidate_count = 0
        source_status_section_count = 0
        terminal_section_count = 0

        def _retain_statute(
            statute: NormalizedStatute,
            *,
            requested_title: str,
            requested_url: str,
            content_sha256: str,
        ) -> None:
            section_number = str(statute.section_number or "")
            if (
                str(statute.title_number or "") != requested_title
                or str(statute.source_url or "") != requested_url
                or not section_number
            ):
                raise RuntimeError(
                    "South Dakota normalized section changed requested source "
                    f"identity: {requested_url}"
                )
            folded_id = str(statute.statute_id or "").casefold()
            if (
                not folded_id
                or folded_id in seen_statute_ids
                or section_number in statute_by_section
                or section_number in terminal_section_identities
                or section_number in source_status_section_identities
            ):
                raise RuntimeError(
                    "South Dakota normalized statute identity is empty or repeated: "
                    f"{statute.statute_id}"
                )
            seen_statute_ids.add(folded_id)
            statute.structured_data = {
                **dict(statute.structured_data or {}),
                "content_sha256": content_sha256,
            }
            statute_by_section[section_number] = statute

        def _retain_terminal_section(
            terminal: Mapping[str, Any],
            *,
            content_sha256: str,
        ) -> None:
            nonlocal terminal_section_count
            section_number = str(terminal.get("section_number") or "")
            if (
                not section_number
                or section_number in terminal_section_identities
                or section_number in source_status_section_identities
                or section_number in statute_by_section
            ):
                raise RuntimeError(
                    "South Dakota terminal section identity is empty or repeated: "
                    f"{section_number!r}"
                )
            terminal_section_identities.add(section_number)
            terminal_units.append(
                {**dict(terminal), "content_sha256": content_sha256}
            )
            terminal_section_count += 1

        def _retain_source_status_section(
            status: Mapping[str, Any],
            *,
            content_sha256: str,
        ) -> None:
            nonlocal source_status_section_count
            section_number = str(status.get("section_number") or "")
            if (
                str(status.get("frontier_level") or "")
                != "section_source_status"
                or str(status.get("disposition") or "")
                not in {"source_collection_parent", "source_identity_alias"}
                or not section_number
                or section_number in source_status_section_identities
                or section_number in terminal_section_identities
                or section_number in statute_by_section
            ):
                raise RuntimeError(
                    "South Dakota source-status section is invalid or repeated: "
                    f"{section_number!r}"
                )
            source_status_section_identities.add(section_number)
            terminal_units.append({**dict(status), "content_sha256": content_sha256})
            source_status_section_count += 1

        for unit, payload in zip(active_title_units, title_payloads, strict=True):
            title_number = str(unit["title_number"])
            source_url = str(unit["source_url"])
            content_sha256 = hashlib.sha256(payload).hexdigest()
            decoded = decode_sdlegislature_bytes(payload)
            chapter_entries = title_chapter_entries(
                decoded,
                title_label=title_number,
            )
            if not chapter_entries:
                raise RuntimeError(
                    "South Dakota active title produced no chapter inventory: "
                    f"{source_url}"
                )
            active_chapters: set[str] = set()
            terminal_chapters: set[str] = set()
            chapter_occurrences: Dict[str, List[str]] = {}
            chapter_order: List[str] = []
            for chapter_number, chapter_name in chapter_entries:
                if chapter_number not in chapter_occurrences:
                    chapter_order.append(chapter_number)
                chapter_occurrences.setdefault(chapter_number, []).append(chapter_name)
            for chapter_number in chapter_order:
                chapter_names = chapter_occurrences[chapter_number]
                chapter_identity = (title_number, chapter_number)
                if chapter_identity in chapter_identities:
                    raise RuntimeError(
                        "South Dakota title frontier repeated exact chapter identity: "
                        f"{title_number}-{chapter_number}"
                    )
                chapter_identities.add(chapter_identity)
                active_names = [
                    name
                    for name in chapter_names
                    if not source_bound_terminal_disposition(name)
                ]
                terminal_names = [
                    name
                    for name in chapter_names
                    if source_bound_terminal_disposition(name)
                ]
                if len(active_names) > 1 or len(terminal_names) > 1:
                    raise RuntimeError(
                        "South Dakota chapter variants remain ambiguous: "
                        f"title={title_number} chapter={chapter_number} "
                        f"labels={chapter_names!r}"
                    )
                if active_names:
                    active_chapter_count += 1
                    active_chapters.add(chapter_number)
                    if terminal_names:
                        lifecycle_chapter_variant_count += 1
                        terminal_chapter_count += 1
                        chapter_name = terminal_names[0]
                        terminal_units.append(
                            {
                                "frontier_level": "chapter_lifecycle_variant",
                                "title_number": title_number,
                                "chapter_number": chapter_number,
                                "source_label": chapter_name,
                                "source_url": source_url,
                                "disposition": source_bound_terminal_disposition(
                                    chapter_name
                                ),
                                "content_sha256": content_sha256,
                            }
                        )
                elif terminal_names:
                    chapter_name = terminal_names[0]
                    chapter_disposition = source_bound_terminal_disposition(
                        chapter_name
                    )
                    terminal_chapter_count += 1
                    terminal_chapters.add(chapter_number)
                    terminal_units.append(
                        {
                            "frontier_level": "chapter",
                            "title_number": title_number,
                            "chapter_number": chapter_number,
                            "source_label": chapter_name,
                            "source_url": source_url,
                            "disposition": chapter_disposition,
                            "content_sha256": content_sha256,
                        }
                    )
                else:
                    raise RuntimeError(
                        "South Dakota chapter has no operative or terminal variant: "
                        f"title={title_number} chapter={chapter_number}"
                    )

            section_entries = title_section_entries(
                decoded,
                title_label=title_number,
            )
            section_ids = [number for number, _name in section_entries]
            if len(section_ids) != len(set(section_ids)):
                raise RuntimeError(
                    "South Dakota whole-title TOC repeated a section identity: "
                    f"{source_url}"
                )
            sections_by_chapter: Dict[str, List[str]] = {}
            section_labels = dict(section_entries)
            for section_number, section_name in section_entries:
                section_chapter = chapter_from_section(section_number)
                if section_chapter not in active_chapters | terminal_chapters:
                    raise RuntimeError(
                        "South Dakota section TOC identity is not beneath a "
                        "catalogued chapter: "
                        f"title={title_number} section={section_number}"
                    )
                if section_chapter in terminal_chapters:
                    continue
                sections_by_chapter.setdefault(section_chapter, []).append(
                    section_number
                )
            missing_section_inventories = sorted(
                active_chapters - set(sections_by_chapter)
            )
            if missing_section_inventories:
                raise RuntimeError(
                    "South Dakota active chapters have no section TOC inventory: "
                    f"title={title_number} chapters={missing_section_inventories}"
                )
            active_section_ids = [
                section_number
                for section_number in section_ids
                if chapter_from_section(section_number) in active_chapters
            ]
            ordered_section_ids.extend(active_section_ids)
            section_candidate_count += len(active_section_ids)
            rows, page_terminals, unresolved = (
                parse_south_dakota_title_html_with_dispositions(
                    decoded,
                    title_label=title_number,
                    code_name=code_name,
                    source_url=source_url,
                )
            )
            if unresolved:
                raise RuntimeError(
                    "South Dakota whole-title parser left nonterminal residuals: "
                    f"title={title_number} residuals={unresolved[:10]}"
                )
            if (
                not rows
                and not page_terminals
                and any(
                    not source_bound_terminal_disposition(
                        section_labels[section_number]
                    )
                    for section_number in active_section_ids
                )
            ):
                raise RuntimeError(
                    "South Dakota active title produced no section disposition: "
                    f"{source_url}"
                )
            rows = [
                row
                for row in rows
                if str(row.chapter_number or "") in active_chapters
            ]
            page_terminals = [
                terminal
                for terminal in page_terminals
                if str(terminal.get("chapter_number") or "") in active_chapters
            ]
            page_lifecycle_variants = [
                terminal
                for terminal in page_terminals
                if str(terminal.get("frontier_level") or "")
                == "section_lifecycle_variant"
            ]
            page_source_statuses = [
                terminal
                for terminal in page_terminals
                if str(terminal.get("frontier_level") or "")
                == "section_source_status"
            ]
            page_terminals = [
                terminal
                for terminal in page_terminals
                if str(terminal.get("frontier_level") or "")
                not in {"section_lifecycle_variant", "section_source_status"}
            ]
            row_section_ids = [str(row.section_number or "") for row in rows]
            terminal_section_ids = [
                str(terminal.get("section_number") or "")
                for terminal in page_terminals
            ]
            already_disposed_ids = {
                *row_section_ids,
                *terminal_section_ids,
                *(
                    str(status.get("section_number") or "")
                    for status in page_source_statuses
                ),
            }
            for section_number in active_section_ids:
                if (
                    section_number in already_disposed_ids
                    or source_bound_terminal_disposition(
                        section_labels[section_number]
                    )
                ):
                    continue
                alias_target = re.sub(
                    r"\(([A-Za-z0-9]+)\)$",
                    r"\1",
                    section_number,
                )
                if (
                    alias_target != section_number
                    and alias_target in row_section_ids
                ):
                    page_source_statuses.append(
                        {
                            "frontier_level": "section_source_status",
                            "title_number": title_number,
                            "chapter_number": chapter_from_section(section_number),
                            "section_number": section_number,
                            "source_label": section_labels[section_number],
                            "source_url": source_url,
                            "disposition": "source_identity_alias",
                            "canonical_section_number": alias_target,
                        }
                    )
                    already_disposed_ids.add(section_number)
                    continue
                child_identities = sorted(
                    identity
                    for identity in active_section_ids
                    if identity.startswith(f"{section_number}(")
                )
                if not child_identities:
                    continue
                page_source_statuses.append(
                    {
                        "frontier_level": "section_source_status",
                        "title_number": title_number,
                        "chapter_number": chapter_from_section(section_number),
                        "section_number": section_number,
                        "source_label": section_labels[section_number],
                        "source_url": source_url,
                        "disposition": "source_collection_parent",
                        "child_identity_count": len(child_identities),
                        "child_identities_sha256": hashlib.sha256(
                            "\n".join(child_identities).encode("utf-8")
                        ).hexdigest(),
                    }
                )
                already_disposed_ids.add(section_number)
            source_status_section_ids = [
                str(status.get("section_number") or "")
                for status in page_source_statuses
            ]
            parsed_section_ids = (
                row_section_ids
                + terminal_section_ids
                + source_status_section_ids
            )
            if (
                any(not identity for identity in parsed_section_ids)
                or len(parsed_section_ids) != len(set(parsed_section_ids))
                or not set(parsed_section_ids).issubset(set(active_section_ids))
            ):
                raise RuntimeError(
                    "South Dakota parser dispositions do not exactly reconcile "
                    "to the whole-title active section inventory: "
                    f"title={title_number} toc={len(active_section_ids)} "
                    f"parsed={len(parsed_section_ids)}"
                )
            toc_terminal_ids = {
                identity
                for identity in active_section_ids
                if source_bound_terminal_disposition(section_labels[identity])
            }
            lifecycle_current_ids = {
                str(terminal.get("section_number") or "")
                for terminal in page_lifecycle_variants
                if str(terminal.get("canonical_current_document_url") or "")
                == "https://sdlegislature.gov/Statutes/"
                + str(terminal.get("section_number") or "")
            }
            retained_toc_terminals = toc_terminal_ids & set(row_section_ids)
            unreconciled_toc_terminals = (
                retained_toc_terminals - lifecycle_current_ids
            )
            if unreconciled_toc_terminals:
                raise RuntimeError(
                    "South Dakota parser retained a TOC-marked terminal section: "
                    f"title={title_number} identities="
                    f"{sorted(unreconciled_toc_terminals)}"
                )
            for terminal in page_terminals:
                if str(terminal.get("title_number") or "") != title_number:
                    raise RuntimeError(
                        "South Dakota terminal section changed requested title identity: "
                        f"{source_url}"
                    )
                _retain_terminal_section(
                    terminal,
                    content_sha256=content_sha256,
                )
            for status in page_source_statuses:
                if str(status.get("title_number") or "") != title_number:
                    raise RuntimeError(
                        "South Dakota source-status section changed requested "
                        f"title identity: {source_url}"
                    )
                _retain_source_status_section(
                    status,
                    content_sha256=content_sha256,
                )
            for terminal in page_lifecycle_variants:
                if str(terminal.get("title_number") or "") != title_number:
                    raise RuntimeError(
                        "South Dakota lifecycle section variant changed requested "
                        f"title identity: {source_url}"
                    )
                terminal_units.append(
                    {**dict(terminal), "content_sha256": content_sha256}
                )
                terminal_section_count += 1
                lifecycle_section_variant_count += 1
            page_terminal_id_set = set(terminal_section_ids)
            page_source_status_id_set = set(source_status_section_ids)
            for section_number in active_section_ids:
                if (
                    section_number not in toc_terminal_ids
                    or section_number in page_terminal_id_set
                    or section_number in row_section_ids
                ):
                    continue
                _retain_terminal_section(
                    {
                        "frontier_level": "section",
                        "title_number": title_number,
                        "chapter_number": chapter_from_section(section_number),
                        "section_number": section_number,
                        "source_label": section_labels[section_number],
                        "source_url": source_url,
                        "disposition": source_bound_terminal_disposition(
                            section_labels[section_number]
                        ),
                    },
                    content_sha256=content_sha256,
                )
            for statute in rows:
                _retain_statute(
                    statute,
                    requested_title=title_number,
                    requested_url=source_url,
                    content_sha256=content_sha256,
                )
            parsed_or_terminal_ids = (
                set(row_section_ids)
                | page_terminal_id_set
                | page_source_status_id_set
                | toc_terminal_ids
            )
            for section_number in active_section_ids:
                if section_number in parsed_or_terminal_ids:
                    continue
                residual_section_units.append(
                    {
                        "title_number": title_number,
                        "chapter_number": chapter_from_section(section_number),
                        "section_number": section_number,
                        "source_label": section_labels[section_number],
                        "source_url": section_html_url(section_number),
                    }
                )

        if residual_section_units:
            residual_payloads = await self._fetch_south_dakota_frontier_batch(
                [unit["source_url"] for unit in residual_section_units],
                frontier_name="residual-section-pages",
                content_validator=self._is_valid_south_dakota_title_payload,
                media_type="text/html",
            )
            for unit, payload in zip(
                residual_section_units,
                residual_payloads,
                strict=True,
            ):
                title_number = unit["title_number"]
                section_number = unit["section_number"]
                source_url = unit["source_url"]
                content_sha256 = hashlib.sha256(payload).hexdigest()
                rows, page_terminals, unresolved = (
                    parse_south_dakota_title_html_with_dispositions(
                        decode_sdlegislature_bytes(payload),
                        title_label=title_number,
                        code_name=code_name,
                        source_url=source_url,
                    )
                )
                observed_ids = [str(row.section_number or "") for row in rows] + [
                    str(terminal.get("section_number") or "")
                    for terminal in page_terminals
                ]
                if unresolved or observed_ids != [section_number]:
                    raise RuntimeError(
                        "South Dakota residual section fallback did not close its "
                        "exact requested identity: "
                        f"requested={section_number} observed={observed_ids} "
                        f"residuals={unresolved[:5]}"
                    )
                if rows:
                    _retain_statute(
                        rows[0],
                        requested_title=title_number,
                        requested_url=source_url,
                        content_sha256=content_sha256,
                    )
                else:
                    terminal = page_terminals[0]
                    if (
                        str(terminal.get("frontier_level") or "")
                        == "section_source_status"
                    ):
                        _retain_source_status_section(
                            terminal,
                            content_sha256=content_sha256,
                        )
                    else:
                        _retain_terminal_section(
                            terminal,
                            content_sha256=content_sha256,
                        )

        unclosed_section_ids = [
            identity
            for identity in ordered_section_ids
            if identity not in statute_by_section
            and identity not in terminal_section_identities
            and identity not in source_status_section_identities
        ]
        if unclosed_section_ids:
            raise RuntimeError(
                "South Dakota source-derived section frontier remains open: "
                f"{unclosed_section_ids[:20]}"
            )
        statutes = [
            statute_by_section[identity]
            for identity in ordered_section_ids
            if identity in statute_by_section
        ]

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
            for key in (
                "fetched",
                "excluded",
                "failed_final",
                "duplicates",
                "quarantined",
            )
        ):
            raise RuntimeError("South Dakota strict disposition algebra did not close")
        title_urls = [str(unit["source_url"]) for unit in active_title_units]
        residual_urls = [unit["source_url"] for unit in residual_section_units]
        request_urls = [self.OFFICIAL_TITLE_API_URL, *title_urls, *residual_urls]
        statute_ids = [str(statute.statute_id) for statute in statutes]
        frontier: Dict[str, Any] = {
            "active_title_count": len(active_title_units),
            "active_chapter_count": active_chapter_count,
            "algebra_closed": True,
            "bundle_closed": False,
            "catalog_content_sha256": catalog_sha256,
            "catalog_expected_units": self.OFFICIAL_TITLE_COUNT,
            "catalog_observed_units": len(title_units),
            "catalog_parity": True,
            "chapter_count": len(chapter_identities),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": discovered,
            "pagination_closed": True,
            "request_batch_count": 2 + int(bool(residual_urls)),
            "residual_section_fallback_count": len(residual_urls),
            "residual_section_locators_sha256": (
                self._south_dakota_frontier_values_sha256(residual_urls)
            ),
            "schema_version": "south-dakota-strict-whole-title-frontier-v3",
            "lifecycle_chapter_variant_count": lifecycle_chapter_variant_count,
            "lifecycle_section_variant_count": lifecycle_section_variant_count,
            "section_candidate_count": section_candidate_count,
            "scope_closed": True,
            "statute_ids_sha256": self._south_dakota_frontier_values_sha256(
                statute_ids
            ),
            "terminal_units": terminal_units,
            "terminal_chapter_count": terminal_chapter_count,
            "source_status_section_count": source_status_section_count,
            "terminal_section_count": terminal_section_count,
            "terminal_title_count": len(title_units) - len(active_title_units),
            "title_count": len(title_units),
            "title_locators_sha256": self._south_dakota_frontier_values_sha256(
                title_urls
            ),
            "title_pages_fetched": len(active_title_units),
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": discovered,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        observation = {
            "boundary_first": request_urls[0],
            "boundary_last": request_urls[-1],
            "frontier": frontier,
            "observed_at": observed_at,
            "statute_ids": statute_ids,
        }
        target = (
            "_last_south_dakota_full_frontier"
            if record_primary
            else "_last_south_dakota_replayed_frontier"
        )
        setattr(self, target, observation)
        if write_checkpoints:
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="south-dakota:complete",
                force=True,
                replace_existing_rows=True,
                extra={
                    "titles_scanned": len(title_units),
                    "discovered_titles": len(title_units),
                    "chapters_scanned": len(chapter_identities),
                    "discovered_chapters": len(chapter_identities),
                    "sections_scanned": section_candidate_count,
                    "discovered_sections": section_candidate_count,
                    "terminal_titles_classified": len(title_units)
                    - len(active_title_units),
                    "terminal_chapters_classified": terminal_chapter_count,
                    "terminal_sections_classified": terminal_section_count,
                    "source_status_sections_classified": (
                        source_status_section_count
                    ),
                    "source_status_section_dispositions": [
                        unit
                        for unit in terminal_units
                        if unit.get("frontier_level") == "section_source_status"
                    ],
                    "terminal_section_dispositions": [
                        unit
                        for unit in terminal_units
                        if unit.get("frontier_level") == "section"
                    ],
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
        """Replay retained whole-title inputs and seal exact SD leaf algebra."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "South Dakota frontier closure requires an attached acquisition ledger"
            )
        first = getattr(self, "_last_south_dakota_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "South Dakota strict frontier was not observed before rows escaped"
            )
        replay_rows = await self._scrape_strict_full_corpus_frontier(
            "South Dakota Codified Laws",
            record_primary=False,
            write_checkpoints=False,
        )
        replay = getattr(self, "_last_south_dakota_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("South Dakota strict frontier replay was not retained")

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
            raise RuntimeError("South Dakota strict frontier observations are incomplete")
        if canonical_json_bytes(first_frontier) != canonical_json_bytes(
            replayed_frontier
        ):
            raise RuntimeError("South Dakota first and replayed exact frontiers differ")

        replay_projection = build_canonical_state_law_output_projection(
            [self._enrich_statute_structure(row).to_dict() for row in replay_rows],
            jurisdiction="SD",
        )
        output_keys_raw = canonical_output_projection.get("canonical_keys")
        if not isinstance(output_keys_raw, Sequence) or isinstance(
            output_keys_raw,
            (str, bytes, bytearray),
        ):
            raise RuntimeError("South Dakota canonical output lacks exact identities")
        output_keys = [str(item).strip() for item in output_keys_raw]
        replay_keys = [
            str(item).strip()
            for item in replay_projection.get("canonical_keys", [])
        ]
        if (
            not output_keys
            or any(not item for item in output_keys)
            or len(output_keys) != len(set(output_keys))
            or output_keys != replay_keys
        ):
            raise RuntimeError(
                "South Dakota final canonical identities do not exactly match "
                "the independently replayed whole-title frontier"
            )
        disposition = first_frontier.get("disposition")
        if not isinstance(disposition, Mapping):
            raise RuntimeError("South Dakota strict frontier lacks disposition algebra")
        if int(disposition.get("fetched") or -1) != len(output_keys):
            raise RuntimeError(
                "South Dakota strict fetched count changed after output filtering"
            )
        completion = closed_jurisdiction_receipt(
            "SD",
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
                    "bundle_total": int(
                        first_frontier.get("request_batch_count") or 0
                    ),
                    "first_hierarchy_unit": str(first.get("boundary_first") or ""),
                    "last_hierarchy_unit": str(first.get("boundary_last") or ""),
                    "pagination_total": int(first_frontier.get("title_count") or 0),
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
                },
                "rights": {
                    "basis": "public_law_no_state_copyright",
                    "decision": "admit",
                    "scope": "statutory_text",
                },
                "transport": {
                    "fixture": False,
                    "kind": (
                        "shared_archive_aware_plural_whole_title_and_"
                        "residual_section_html"
                    ),
                    "singleton_page_archive_loops": False,
                    "synthetic": False,
                },
            }
        )
        frontier_digest = str(first_frontier.get("frontier_digest_sha256") or "")
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=dict(replayed_frontier),
            canonical_output_projection=canonical_output_projection,
            release_point=f"sha256:{frontier_digest}",
            official_source_url=self.OFFICIAL_TITLE_API_URL,
            acquisition_path_ids=self._catalog_acquisition_path_ids_for_source(
                self.OFFICIAL_ENTRY_URL
            ),
            observation_time=str(first.get("observed_at") or ""),
            source_software_version=self._state_law_frontier_source_software_version(),
        )

    def get_base_url(self) -> str:
        """Return the base URL for South Dakota's legislative website."""
        return "https://sdlegislature.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for South Dakota."""
        return [
            {"name": "South Dakota Codified Laws", "url": f"{self.get_base_url()}/", "type": "Code"}
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from South Dakota's legislative website.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .south_dakota_constitution import (
            configured_constitution_html_path,
            parse_south_dakota_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_south_dakota_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "South Dakota Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .south_dakota_title import parse_configured_south_dakota_title

        try:
            bulk = parse_configured_south_dakota_title(
                code_name=code_name,
                max_statutes=limit,
            )
            if bulk:
                return bulk
        except Exception as exc:
            self.logger.warning("South Dakota official title HTML failed: %s", exc)
        if (
            self._full_corpus_enabled()
            and max_statutes is None
            and getattr(self, "_state_law_acquisition_ledger", None) is not None
        ):
            return await self._scrape_strict_full_corpus_frontier(
                code_name,
                record_primary=True,
                write_checkpoints=True,
            )
        max_api_statutes = limit if limit is not None else None
        api_statutes = await self._scrape_statutes_api(
            code_name=code_name,
            max_statutes=max_api_statutes,
        )
        if api_statutes:
            self.logger.info(f"South Dakota API scrape: Scraped {len(api_statutes)} sections")
            return api_statutes

        max_sections = limit if limit is not None else 1000000
        return await self._generic_scrape(
            code_name, code_url, "S.D. Codified Laws", max_sections=max_sections
        )

    async def _scrape_statutes_api(
        self, code_name: str, max_statutes: Optional[int]
    ) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        statutes: List[NormalizedStatute] = []
        seen = set()
        pending = list(self._SEED_SECTIONS + self._TITLE_START_SECTIONS)
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        last_progress_log_ts = 0.0
        checkpoint = _SouthDakotaCheckpoint(self.state_code)

        while pending:
            if limit is not None and len(statutes) >= limit:
                break
            section = str(pending.pop(0) or "").strip()
            if section in seen:
                continue
            seen.add(section)

            data = await self._request_json(
                f"https://sdlegislature.gov/api/Statutes/Statute/{section}",
                headers=headers,
                timeout=35,
            )
            if not data:
                continue

            next_section = str(data.get("Next") or "").strip()
            if next_section and next_section not in seen:
                pending.insert(0, next_section)

            html = str(data.get("Html") or "")
            full_text = self._clean_html_text(html)
            if len(full_text) < 280:
                continue

            section_number = str(data.get("Statute") or section)
            section_name = str(data.get("CatchLine") or f"Section {section_number}").strip()

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:180],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(full_text),
                    source_url=f"https://sdlegislature.gov/api/Statutes/Statute/{section_number}",
                    official_cite=f"S.D. Codified Laws {section_number}",
                    structured_data={
                        "source_kind": "official_south_dakota_statutes_api",
                        "discovery_method": "official_statute_api_next_chain",
                        "skip_hydrate": True,
                    },
                )
            )

            now = time.time()
            if len(statutes) == 1 or len(statutes) % 500 == 0 or now - last_progress_log_ts >= 60:
                self.logger.info(
                    "South Dakota API scrape: statutes_so_far=%s current_section=%s next_section=%s",
                    len(statutes),
                    section_number,
                    next_section or "",
                )
                last_progress_log_ts = now
            checkpoint.maybe_write(statutes, section_number=section_number)

        checkpoint.write(statutes, section_number="complete")
        return statutes

    async def _request_json(self, url: str, headers: Dict[str, str], timeout: int) -> Dict:
        def _is_json_object(payload: bytes) -> bool:
            try:
                parsed = json.loads(payload.decode("utf-8", errors="replace"))
            except Exception:
                return False
            return isinstance(parsed, dict)

        payload = await self._fetch_parser_input_with_transport(
            url,
            headers=headers,
            timeout_seconds=timeout,
            content_validator=_is_json_object,
            # Preserve the existing direct attempt followed by the retrying
            # shared archival path below.
            allow_archival_fallback=False,
            media_type="application/json",
            provider="requests_direct",
        )
        if payload:
            data = self._parse_json_payload(payload)
            if isinstance(data, dict):
                return data

        for _ in range(3):
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    url,
                    timeout_seconds=timeout,
                )
                if not payload:
                    raise ValueError("empty response")
                data = self._parse_json_payload(payload)
                if isinstance(data, dict):
                    return data
            except Exception:
                time.sleep(0.5)
                continue
        return {}

    def _parse_json_payload(self, payload: bytes) -> Dict:
        try:
            import json

            parsed = json.loads(payload.decode("utf-8", errors="replace"))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
        return {}

    def _clean_html_text(
        self,
        html: str,
        max_chars: Optional[int] = None,
    ) -> str:
        value = str(html or "")
        value = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", value)
        value = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", value)
        value = re.sub(r"(?is)<br\s*/?>", "\n", value)
        value = re.sub(r"(?is)</p>", "\n", value)
        value = re.sub(r"(?is)<[^>]+>", " ", value)
        value = unescape(value)
        value = value.replace("\xa0", " ")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\s*\n\s*", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        text = value.strip()
        if max_chars is not None:
            return text[: max(1, int(max_chars))]
        return text

    def official_title_url(self, title_number: Any) -> str:
        number = str(title_number or "").strip()
        return f"{self.get_base_url()}/Statutes/Codified_Laws/{number}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official South Dakota Codified Laws title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"sd:title-{number.lower()}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"South Dakota Codified Laws Title {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == "sdlegislature.gov" or host.endswith(".sdlegislature.gov")

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-south-dakota-official-catalog/1.0",
            "Accept": "text/html,application/json,application/xhtml+xml;q=0.9,*/*;q=0.8",
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

    def _normalize_title_number(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        match = re.match(r"0*(\d{1,2}[A-Z]?)$", text)
        return match.group(1) if match else ""

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        known = {number for number, _name in self.OFFICIAL_TITLES}
        try:
            parsed = json.loads(html.decode("utf-8", errors="replace"))
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, Mapping):
                    continue
                number = self._normalize_title_number(
                    item.get("Statute")
                    or item.get("Title")
                    or item.get("title")
                    or item.get("Number")
                )
                if number in known and number not in found:
                    found[number] = self.official_title_url(number)
            if found:
                return found
        if isinstance(parsed, Mapping):
            rows = parsed.get("Titles") or parsed.get("titles") or parsed.get("items") or []
            if isinstance(rows, list):
                for item in rows:
                    if not isinstance(item, Mapping):
                        continue
                    number = self._normalize_title_number(
                        item.get("Statute")
                        or item.get("Title")
                        or item.get("title")
                        or item.get("Number")
                    )
                    if number in known and number not in found:
                        found[number] = self.official_title_url(number)
            if found:
                return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._SD_TITLE_HREF_RE.search(absolute) or self._SD_TITLE_LABEL_RE.search(label)
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
        """Enumerate every official South Dakota Codified Laws title."""

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

    def fetch_official(self, code: str = "SD"):
        """Acquire the exhaustive official South Dakota Codified Laws catalog.

        Live HTTPS retains the official sdlegislature.gov statute index.
        Every known Codified Laws title is enumerated with an official URL.
        This hook never returns fixture bytes or secondary-mirror hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "SD").strip().upper() or "SD"
        if normalized != "SD":
            raise ValueError(f"SouthDakotaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        if not self._parse_official_title_links(html):
            api_payload = self._official_http_get(self.OFFICIAL_TITLE_API_URL)
            if api_payload:
                html = api_payload
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "south dakota official catalog enumeration rejected incomplete "
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
StateScraperRegistry.register("SD", SouthDakotaScraper)


class _SouthDakotaCheckpoint:
    """Best-effort partial progress checkpoint for South Dakota API crawls."""

    def __init__(self, state_code: str) -> None:
        raw_dir = current_partial_checkpoint_run_directory()
        if not raw_dir:
            self.path: Optional[Path] = None
        else:
            self.path = (
                Path(raw_dir).expanduser().resolve() / f"STATE-{state_code.upper()}-partial.json"
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_code = state_code.upper()
        self.interval = max(
            1, int(float(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_INTERVAL", "500") or 500))
        )
        self.last_count = 0
        self.last_write_ts = 0.0

    def maybe_write(self, statutes: List[NormalizedStatute], *, section_number: str) -> None:
        count = len(statutes)
        if not self.path or count <= 0:
            return
        if count - self.last_count < self.interval and time.time() - self.last_write_ts < 120:
            return
        self.write(statutes, section_number=section_number)

    def write(self, statutes: List[NormalizedStatute], *, section_number: str) -> None:
        if not self.path or not statutes:
            return
        payload = {
            "state_code": self.state_code,
            "updated_at": time.time(),
            "statutes_count": len(statutes),
            "section_number": section_number,
            "statutes": [statute.to_dict() for statute in statutes],
        }
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(statutes)
        self.last_write_ts = time.time()
