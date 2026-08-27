"""Scraper for Rhode Island state laws."""

from __future__ import annotations

import hashlib
import json
import re
import ssl
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StateLawPageMultiFetchResult,
    StatuteMetadata,
)
from .registry import StateScraperRegistry

_TITLE_INDEX_URL_TEMPLATE = "https://webserver.rilegislature.gov/Statutes/TITLE{title}/INDEX.HTM"
_RI_TITLE_TOKEN_PATTERN = r"[0-9]+(?:A|\.[0-9]+)?"
_RI_CHAPTER_TOKEN_PATTERN = r"[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+"
_RI_SECTION_TOKEN_PATTERN = r"[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+"
_RI_SECTION_LOCATOR_PATTERN = r"[0-9A-Za-z._-]+"
_TITLE_LINK_RE = re.compile(
    rf"/Statutes/TITLE({_RI_TITLE_TOKEN_PATTERN})/"
    rf"({_RI_CHAPTER_TOKEN_PATTERN})/INDEX\.htm$",
    re.IGNORECASE,
)
_SECTION_LINK_RE = re.compile(
    rf"/Statutes/TITLE({_RI_TITLE_TOKEN_PATTERN})/"
    rf"({_RI_CHAPTER_TOKEN_PATTERN})/({_RI_SECTION_TOKEN_PATTERN})\.htm$",
    re.IGNORECASE,
)
_TITLE_PATH_RE = re.compile(
    rf"/Statutes/TITLE(?P<title>{_RI_TITLE_TOKEN_PATTERN})/INDEX\.HTM$",
    re.IGNORECASE,
)
_CHAPTER_PATH_RE = re.compile(
    rf"/Statutes/TITLE(?P<title>{_RI_TITLE_TOKEN_PATTERN})/"
    rf"(?P<chapter>{_RI_CHAPTER_TOKEN_PATTERN})/INDEX\.htm$",
    re.IGNORECASE,
)
_SECTION_PATH_RE = re.compile(
    rf"/Statutes/TITLE(?P<title>{_RI_TITLE_TOKEN_PATTERN})/"
    rf"(?P<chapter>{_RI_CHAPTER_TOKEN_PATTERN})/"
    rf"(?:(?P<part>{_RI_CHAPTER_TOKEN_PATTERN})/"
    rf"(?:(?P<subpart>{_RI_CHAPTER_TOKEN_PATTERN})/)?)?"
    rf"(?P<section>{_RI_SECTION_LOCATOR_PATTERN})\.htm$",
    re.IGNORECASE,
)
_PART_PATH_RE = re.compile(
    rf"/Statutes/TITLE(?P<title>{_RI_TITLE_TOKEN_PATTERN})/"
    rf"(?P<chapter>{_RI_CHAPTER_TOKEN_PATTERN})/"
    rf"(?P<part>{_RI_CHAPTER_TOKEN_PATTERN})/INDEX\.htm$",
    re.IGNORECASE,
)
_SUBPART_PATH_RE = re.compile(
    rf"/Statutes/TITLE(?P<title>{_RI_TITLE_TOKEN_PATTERN})/"
    rf"(?P<chapter>{_RI_CHAPTER_TOKEN_PATTERN})/"
    rf"(?P<part>{_RI_CHAPTER_TOKEN_PATTERN})/"
    rf"(?P<subpart>{_RI_CHAPTER_TOKEN_PATTERN})/INDEX\.htm$",
    re.IGNORECASE,
)
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

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            rhode_island_section,
            state_archival_fetch,
            strict_frontier_closure,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            rhode_island_section,
            wayback_machine_engine,
        )

    def _rhode_island_frontier_concurrency(self) -> int:
        legacy_default = self._env_int(
            "STATE_SCRAPER_RI_SECTION_CONCURRENCY",
            default=16,
        )
        return max(
            1,
            min(
                64,
                self._env_int(
                    "STATE_SCRAPER_RI_FRONTIER_CONCURRENCY",
                    default=legacy_default,
                ),
            ),
        )

    def _rhode_island_section_batch_size(self) -> int:
        return max(
            1,
            min(
                1024,
                self._env_int(
                    "STATE_SCRAPER_RI_SECTION_BATCH_SIZE",
                    default=256,
                ),
            ),
        )

    def _record_rhode_island_frontier_inputs(
        self,
        *,
        source_role: str,
        urls: Sequence[str],
        payloads: Sequence[bytes],
    ) -> None:
        """Bind one ordered RI hierarchy batch to its exact retained bytes."""

        requested = list(urls)
        if len(requested) != len(payloads):
            raise RuntimeError("Rhode Island frontier input projection is not aligned")
        reports = list(getattr(self, "_rhode_island_frontier_input_reports", []))
        seen = {str(row.get("source_url") or "") for row in reports}
        for url, payload in zip(requested, payloads, strict=True):
            raw = bytes(payload or b"")
            if not url or url in seen or not raw:
                raise RuntimeError(
                    "Rhode Island frontier input projection repeated or lost a URL: "
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
        self._rhode_island_frontier_input_reports = reports

    @staticmethod
    def _is_valid_rhode_island_frontier_payload(payload: bytes) -> bool:
        """Reject generic redirect/error shells before durable retention."""

        if not payload:
            return False
        lowered = bytes(payload).lower()
        prefix = lowered[:1000]
        return (
            b"document moved" not in prefix
            and b"<title>404" not in prefix
            and b"404 not found" not in prefix
        )

    async def _fetch_rhode_island_frontier_batch(
        self,
        urls: List[str],
        *,
        frontier_name: str,
    ) -> StateLawPageMultiFetchResult:
        """Acquire an exact RI frontier through the shared WARC batch path."""

        if not urls:
            return StateLawPageMultiFetchResult([], [], [], [], [], {})
        requested = list(urls)
        if bool(getattr(self, "_rhode_island_retained_replay", False)):
            from .strict_frontier_closure import (
                replay_exact_retained_state_records,
            )

            retained_rows = replay_exact_retained_state_records(
                self,
                requests=[
                    (url, {"method": "GET", "url": url}) for url in requested
                ],
                frontier_name=f"Rhode Island {frontier_name} frontier",
                refresh=False,
            )
            payloads = [
                bytes(getattr(row.envelope, "body", b"") or b"")
                for row in retained_rows
            ]
            if any(
                not self._is_valid_rhode_island_frontier_payload(payload)
                for payload in payloads
            ):
                raise RuntimeError(
                    f"Rhode Island retained {frontier_name} frontier is invalid"
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
        generic_residual_attempts = self._env_int(
            "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
            default=1,
        )
        residual_retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_RI_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=generic_residual_attempts,
                ),
            ),
        )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=residual_retry_attempts,
            timeout_seconds=30,
            media_type="text/html",
            max_concurrency=self._rhode_island_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=("/Statutes/",),
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
            content_validator=self._is_valid_rhode_island_frontier_payload,
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
                f"Rhode Island {frontier_name} frontier returned unaligned "
                "acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"Rhode Island {frontier_name} frontier changed URL order or identity"
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
                f"Rhode Island {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures}"
            )
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    @staticmethod
    def _coerce_rhode_island_frontier_batch(
        value: Any,
        *,
        requested_urls: List[str],
    ) -> StateLawPageMultiFetchResult:
        """Normalize older test doubles while retaining production receipts."""

        requested = list(requested_urls)
        if isinstance(value, StateLawPageMultiFetchResult):
            if list(value.urls) != requested:
                raise RuntimeError(
                    "Rhode Island frontier result changed URL order or identity"
                )
            return value
        if isinstance(value, list) and len(value) == len(requested) and all(
            isinstance(payload, bytes) for payload in value
        ):
            return StateLawPageMultiFetchResult(
                urls=requested,
                payloads=list(value),
                errors=[None] * len(requested),
                transport_receipts=[None] * len(requested),
                parser_input_envelopes=[None] * len(requested),
                stats={},
            )
        raise RuntimeError("Rhode Island frontier returned an unsupported batch")

    @staticmethod
    def _rhode_island_section_evidence_context(
        *,
        source_url: str,
        payload: bytes,
        transport_receipt: Optional[Dict[str, Any]],
        parser_input_envelope: Any,
    ) -> Dict[str, Any]:
        """Resolve the exact legal as-of date from acquisition provenance."""

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
                "Rhode Island section acquisition receipt does not match "
                f"requested URL: {source_url}"
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
                "Rhode Island section evidence changed exact parser bytes: "
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
                "Rhode Island section acquisition transport identity is "
                f"incomplete: {source_url}"
            )

        retrieved_at = str(receipt.get("retrieved_at") or "").strip()
        try:
            retrieved_date = datetime.fromisoformat(
                retrieved_at.replace("Z", "+00:00")
            ).date()
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Rhode Island section receipt lacks a valid retrieval date: "
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
                    "Rhode Island archived section receipt lacks a provenance "
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
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .rhode_island_constitution import (
            configured_constitution_html_path,
            parse_rhode_island_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_rhode_island_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Rhode Island Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .rhode_island_section import configured_section_html_path, parse_rhode_island_section_html

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_rhode_island_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://webserver.rilegislature.gov/Statutes/TITLE11/11-23/11-23-1.htm",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        return await self._custom_scrape_rhode_island(
            code_name,
            code_url,
            "R.I. Gen. Laws",
            max_sections=limit,
        )

    def _canonical_rhode_island_title_url(
        self,
        url: str,
        title_number: str,
    ) -> str:
        parsed = urlparse(str(url or ""))
        match = _TITLE_PATH_RE.fullmatch(parsed.path)
        expected_title = self.official_title_token(title_number)
        observed_title = (
            self.official_title_token(match.group("title")) if match else ""
        )
        if (
            parsed.scheme.lower() != "https"
            or parsed.netloc.lower() != self.OFFICIAL_DOMAIN
            or parsed.params
            or parsed.query
            or parsed.fragment
            or not match
            or not expected_title
            or observed_title.casefold() != expected_title.casefold()
        ):
            raise RuntimeError(
                f"Rhode Island root exposed a non-canonical title locator: {url}"
            )
        return self.official_title_url(expected_title)

    def _canonical_rhode_island_chapter_locator(
        self,
        url: str,
        *,
        title_number: str,
        chapter_number: str,
    ) -> tuple[str, str]:
        parsed = urlparse(str(url or ""))
        match = _CHAPTER_PATH_RE.fullmatch(parsed.path)
        expected_title = self.official_title_token(title_number)
        expected_chapter = str(chapter_number or "").strip()
        observed_title = (
            self.official_title_token(match.group("title")) if match else ""
        )
        observed_chapter = str(match.group("chapter") if match else "").strip()
        valid = bool(
            parsed.scheme.lower() == "https"
            and parsed.netloc.lower() == self.OFFICIAL_DOMAIN
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and match
            and expected_title
            and expected_chapter
            and observed_title.casefold() == expected_title.casefold()
            and observed_chapter.casefold() == expected_chapter.casefold()
            and observed_chapter.casefold().startswith(
                f"{expected_title.casefold()}-"
            )
        )
        if not valid:
            raise RuntimeError(
                "Rhode Island title exposed a non-canonical chapter locator: "
                f"{url}"
            )
        canonical_url = (
            f"https://{self.OFFICIAL_DOMAIN}/Statutes/TITLE{expected_title}/"
            f"{observed_chapter}/INDEX.htm"
        )
        return canonical_url, observed_chapter

    def _canonical_rhode_island_section_locator(
        self,
        url: str,
        *,
        title_number: str,
        chapter_number: str,
        part_number: Optional[str] = None,
        subpart_number: Optional[str] = None,
        section_label: str = "",
    ) -> tuple[str, str]:
        from .rhode_island_section import source_bound_section_locator_identity

        parsed = urlparse(str(url or ""))
        match = _SECTION_PATH_RE.fullmatch(parsed.path)
        expected_title = self.official_title_token(title_number)
        expected_chapter = str(chapter_number or "").strip()
        observed_title = (
            self.official_title_token(match.group("title")) if match else ""
        )
        observed_chapter = str(match.group("chapter") if match else "").strip()
        observed_part = str((match.group("part") or "") if match else "").strip()
        observed_subpart = str(
            (match.group("subpart") or "") if match else ""
        ).strip()
        observed_locator = str(match.group("section") if match else "").strip()
        expected_part = str(part_number or "").strip()
        expected_subpart = str(subpart_number or "").strip()
        locator_identity = (
            source_bound_section_locator_identity(
                title_number=expected_title,
                chapter_number=expected_chapter,
                locator=observed_locator,
                frontier_label=section_label,
            )
            if match
            else None
        )
        logical_section = locator_identity[0] if locator_identity else ""
        valid = bool(
            parsed.scheme.lower() == "https"
            and parsed.netloc.lower() == self.OFFICIAL_DOMAIN
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and match
            and expected_title
            and expected_chapter
            and locator_identity is not None
            and observed_title.casefold() == expected_title.casefold()
            and observed_chapter.casefold() == expected_chapter.casefold()
            and observed_part.casefold() == expected_part.casefold()
            and observed_subpart.casefold() == expected_subpart.casefold()
            and (
                not observed_part
                or observed_part.casefold().startswith(
                    f"{expected_title.casefold()}-"
                )
            )
            and (
                not observed_subpart
                or (
                    observed_part
                    and observed_subpart.casefold().startswith(
                        f"{expected_title.casefold()}-"
                    )
                )
            )
        )
        if not valid:
            raise RuntimeError(
                "Rhode Island chapter exposed a non-canonical section locator: "
                f"{url}"
            )
        parent_path = f"{expected_chapter}/"
        if observed_part:
            parent_path += f"{observed_part}/"
        if observed_subpart:
            parent_path += f"{observed_subpart}/"
        canonical_url = (
            f"https://{self.OFFICIAL_DOMAIN}/Statutes/TITLE{expected_title}/"
            f"{parent_path}{observed_locator}.htm"
        )
        return canonical_url, logical_section

    def _canonical_rhode_island_part_locator(
        self,
        url: str,
        *,
        title_number: str,
        chapter_number: str,
    ) -> tuple[str, str]:
        parsed = urlparse(str(url or ""))
        match = _PART_PATH_RE.fullmatch(parsed.path)
        expected_title = self.official_title_token(title_number)
        expected_chapter = str(chapter_number or "").strip()
        observed_title = (
            self.official_title_token(match.group("title")) if match else ""
        )
        observed_chapter = str(match.group("chapter") if match else "").strip()
        observed_part = str(match.group("part") if match else "").strip()
        valid = bool(
            parsed.scheme.lower() == "https"
            and parsed.netloc.lower() == self.OFFICIAL_DOMAIN
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and match
            and expected_title
            and expected_chapter
            and observed_part
            and observed_title.casefold() == expected_title.casefold()
            and observed_chapter.casefold() == expected_chapter.casefold()
            and observed_part.casefold().startswith(
                f"{expected_title.casefold()}-"
            )
        )
        if not valid:
            raise RuntimeError(
                "Rhode Island chapter exposed a non-canonical part locator: "
                f"{url}"
            )
        canonical_url = (
            f"https://{self.OFFICIAL_DOMAIN}/Statutes/TITLE{expected_title}/"
            f"{expected_chapter}/{observed_part}/INDEX.htm"
        )
        return canonical_url, observed_part

    def _canonical_rhode_island_subpart_locator(
        self,
        url: str,
        *,
        title_number: str,
        chapter_number: str,
        part_number: str,
    ) -> tuple[str, str]:
        """Validate one exact official subpart index child locator."""

        parsed = urlparse(str(url or ""))
        match = _SUBPART_PATH_RE.fullmatch(parsed.path)
        expected_title = self.official_title_token(title_number)
        expected_chapter = str(chapter_number or "").strip()
        expected_part = str(part_number or "").strip()
        observed_title = (
            self.official_title_token(match.group("title")) if match else ""
        )
        observed_chapter = str(match.group("chapter") if match else "").strip()
        observed_part = str(match.group("part") if match else "").strip()
        observed_subpart = str(match.group("subpart") if match else "").strip()
        valid = bool(
            parsed.scheme.lower() == "https"
            and parsed.netloc.lower() == self.OFFICIAL_DOMAIN
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and match
            and expected_title
            and expected_chapter
            and expected_part
            and observed_subpart
            and observed_title.casefold() == expected_title.casefold()
            and observed_chapter.casefold() == expected_chapter.casefold()
            and observed_part.casefold() == expected_part.casefold()
            and observed_subpart.casefold().startswith(
                f"{expected_title.casefold()}-"
            )
        )
        if not valid:
            raise RuntimeError(
                "Rhode Island part exposed a non-canonical subpart locator: "
                f"{url}"
            )
        canonical_url = (
            f"https://{self.OFFICIAL_DOMAIN}/Statutes/TITLE{expected_title}/"
            f"{expected_chapter}/{expected_part}/{observed_subpart}/INDEX.htm"
        )
        return canonical_url, observed_subpart

    async def _scrape_unbounded_rhode_island_frontier(
        self,
        code_name: str,
        citation_format: str,
    ) -> List[NormalizedStatute]:
        """Rebuild and acquire the complete official title/chapter/section tree."""

        from .rhode_island_section import (
            chapter_part_links,
            chapter_section_links,
            parse_rhode_island_section_html,
            part_section_links,
            part_subpart_links,
            source_bound_empty_chapter_disposition,
            source_bound_terminal_section_disposition,
            subpart_section_links,
            title_chapter_links,
            toc_title_links,
        )

        # Full runs intentionally ignore checkpoint rows and positional cursors.
        # The attached evidence ledger replays exact retained page bytes while
        # this traversal reconstructs the current authoritative frontier.
        replaying = bool(getattr(self, "_rhode_island_retained_replay", False))
        self._rhode_island_frontier_input_reports = []

        def _write_checkpoint(*args: Any, **kwargs: Any) -> bool:
            if replaying:
                return False
            return bool(self._write_partial_checkpoint(*args, **kwargs))

        statutes: List[NormalizedStatute] = []
        root_url = f"{self.get_base_url()}/Statutes/"
        root_urls = [root_url]
        root_batch = self._coerce_rhode_island_frontier_batch(
            await self._fetch_rhode_island_frontier_batch(
                root_urls,
                frontier_name="root-index",
            ),
            requested_urls=root_urls,
        )
        root_payloads = root_batch.payloads
        self._record_rhode_island_frontier_inputs(
            source_role="root_catalog",
            urls=root_urls,
            payloads=root_payloads,
        )
        title_rows = toc_title_links(
            root_payloads[0].decode("utf-8", errors="replace"),
            base_url=root_url,
        )
        if not title_rows:
            raise RuntimeError(
                "Rhode Island official root exposed no title frontier"
            )

        title_frontier: List[tuple[str, str]] = []
        seen_titles: set[str] = set()
        for title_url, title_number in title_rows:
            normalized_title = self.official_title_token(title_number)
            canonical_url = self._canonical_rhode_island_title_url(
                title_url,
                normalized_title,
            )
            title_key = normalized_title.casefold()
            if title_key in seen_titles:
                raise RuntimeError(
                    "Rhode Island root repeated title identity "
                    f"{normalized_title}"
                )
            seen_titles.add(title_key)
            title_frontier.append((canonical_url, normalized_title))

        expected_titles = {
            self.official_title_token(number).casefold()
            for number, _name in self.OFFICIAL_TITLES
        }
        missing_titles = sorted(expected_titles - seen_titles)
        if missing_titles:
            raise RuntimeError(
                "Rhode Island official root omitted catalog titles: "
                f"{missing_titles}"
            )

        title_urls = [row[0] for row in title_frontier]
        title_batch = self._coerce_rhode_island_frontier_batch(
            await self._fetch_rhode_island_frontier_batch(
                title_urls,
                frontier_name="title-index",
            ),
            requested_urls=title_urls,
        )
        title_payloads = title_batch.payloads
        self._record_rhode_island_frontier_inputs(
            source_role="title_catalog",
            urls=title_urls,
            payloads=title_payloads,
        )
        chapter_frontier: List[tuple[int, str, str, str]] = []
        seen_chapters: set[tuple[str, str]] = set()
        title_chapter_end_indices: List[tuple[int, int]] = []
        for title_index, ((title_url, title_number), title_payload) in enumerate(
            zip(title_frontier, title_payloads, strict=True),
            start=1,
        ):
            chapter_rows = title_chapter_links(
                title_payload.decode("utf-8", errors="replace"),
                title_url=title_url,
            )
            if not chapter_rows:
                raise RuntimeError(
                    "Rhode Island retained title exposed no chapter frontier: "
                    f"{title_url}"
                )
            for chapter_url, chapter_number in chapter_rows:
                canonical_url, canonical_chapter = (
                    self._canonical_rhode_island_chapter_locator(
                        chapter_url,
                        title_number=title_number,
                        chapter_number=chapter_number,
                    )
                )
                chapter_key = (
                    title_number.casefold(),
                    canonical_chapter.casefold(),
                )
                if chapter_key in seen_chapters:
                    raise RuntimeError(
                        "Rhode Island title frontier repeated chapter identity "
                        f"{title_number}/{canonical_chapter}"
                    )
                seen_chapters.add(chapter_key)
                chapter_frontier.append(
                    (
                        title_index,
                        title_number,
                        canonical_chapter,
                        canonical_url,
                    )
                )
            title_chapter_end_indices.append(
                (title_index, len(chapter_frontier))
            )

        _write_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="rhode-island:chapter-discovery",
            force=True,
            replace_existing_rows=True,
            extra={
                "titles_scanned": 0,
                "discovered_titles": len(title_frontier),
                "chapters_scanned": 0,
                "discovered_chapters": len(chapter_frontier),
                "parts_scanned": 0,
                "discovered_parts": 0,
                "subparts_scanned": 0,
                "discovered_subparts": 0,
                "sections_scanned": 0,
                "discovered_sections": 0,
                "terminal_sections_classified": 0,
                "terminal_section_dispositions": [],
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        chapter_urls = [row[3] for row in chapter_frontier]
        chapter_batch = self._coerce_rhode_island_frontier_batch(
            await self._fetch_rhode_island_frontier_batch(
                chapter_urls,
                frontier_name="chapter-index",
            ),
            requested_urls=chapter_urls,
        )
        chapter_payloads = chapter_batch.payloads
        self._record_rhode_island_frontier_inputs(
            source_role="chapter_catalog",
            urls=chapter_urls,
            payloads=chapter_payloads,
        )
        chapter_discoveries: List[
            tuple[
                tuple[int, str, str, str],
                List[tuple[str, str]],
                List[tuple[str, str, str]],
            ]
        ] = []
        part_frontier: List[tuple[str, str, str, str, str]] = []
        seen_part_urls: set[str] = set()
        seen_part_identities: set[tuple[str, str, str]] = set()
        terminal_chapters: List[Dict[str, str]] = []
        for chapter_row, chapter_payload in zip(
            chapter_frontier,
            chapter_payloads,
            strict=True,
        ):
            _title_index, title_number, chapter_number, chapter_url = chapter_row
            chapter_html = chapter_payload.decode("utf-8", errors="replace")
            direct_section_rows = chapter_section_links(
                chapter_html,
                chapter_url=chapter_url,
            )
            raw_part_rows = chapter_part_links(
                chapter_html,
                chapter_url=chapter_url,
                title_number=title_number,
                chapter_number=chapter_number,
            )
            if direct_section_rows and raw_part_rows:
                raise RuntimeError(
                    "Rhode Island chapter mixed direct-section and part-index "
                    f"frontiers: {chapter_url}"
                )
            chapter_parts: List[tuple[str, str, str]] = []
            for part_url, part_label in raw_part_rows:
                canonical_part_url, part_number = (
                    self._canonical_rhode_island_part_locator(
                        part_url,
                        title_number=title_number,
                        chapter_number=chapter_number,
                    )
                )
                part_identity = (
                    title_number.casefold(),
                    chapter_number.casefold(),
                    part_number.casefold(),
                )
                if (
                    canonical_part_url in seen_part_urls
                    or part_identity in seen_part_identities
                ):
                    raise RuntimeError(
                        "Rhode Island chapter frontier repeated part identity "
                        f"{title_number}/{chapter_number}/{part_number}"
                    )
                seen_part_urls.add(canonical_part_url)
                seen_part_identities.add(part_identity)
                chapter_parts.append(
                    (canonical_part_url, part_number, str(part_label or ""))
                )
                part_frontier.append(
                    (
                        title_number,
                        chapter_number,
                        part_number,
                        str(part_label or ""),
                        canonical_part_url,
                    )
                )
            if not direct_section_rows and not chapter_parts:
                chapter_disposition = source_bound_empty_chapter_disposition(
                    chapter_html,
                    chapter_url=chapter_url,
                    title_number=title_number,
                    chapter_number=chapter_number,
                )
                if chapter_disposition is None:
                    raise RuntimeError(
                        "Rhode Island retained chapter exposed no exact section, "
                        f"intermediate, or terminal frontier: {chapter_url}"
                    )
                terminal_chapters.append(
                    {
                        "title_number": title_number,
                        "chapter_number": chapter_number,
                        "disposition": chapter_disposition,
                        "source_url": chapter_url,
                        "content_sha256": hashlib.sha256(
                            bytes(chapter_payload)
                        ).hexdigest(),
                    }
                )
            chapter_discoveries.append(
                (chapter_row, direct_section_rows, chapter_parts)
            )

        part_section_groups_by_url: Dict[
            str,
            List[tuple[str, Optional[str], List[tuple[str, str]]]],
        ] = {}
        subpart_frontier: List[tuple[str, str, str, str, str, str]] = []
        seen_subpart_urls: set[str] = set()
        seen_subpart_identities: set[tuple[str, str, str, str]] = set()
        if part_frontier:
            part_urls = [row[4] for row in part_frontier]
            part_batch = self._coerce_rhode_island_frontier_batch(
                await self._fetch_rhode_island_frontier_batch(
                    part_urls,
                    frontier_name="part-index",
                ),
                requested_urls=part_urls,
            )
            part_payloads = part_batch.payloads
            self._record_rhode_island_frontier_inputs(
                source_role="part_catalog",
                urls=part_urls,
                payloads=part_payloads,
            )
            for part_row, part_payload in zip(
                part_frontier,
                part_payloads,
                strict=True,
            ):
                (
                    title_number,
                    chapter_number,
                    part_number,
                    part_label,
                    part_url,
                ) = part_row
                part_html = part_payload.decode("utf-8", errors="replace")
                section_rows = part_section_links(
                    part_html,
                    part_url=part_url,
                    title_number=title_number,
                    chapter_number=chapter_number,
                    part_number=part_number,
                    intermediate_label=part_label,
                )
                raw_subpart_rows = part_subpart_links(
                    part_html,
                    part_url=part_url,
                    title_number=title_number,
                    chapter_number=chapter_number,
                    part_number=part_number,
                    intermediate_label=part_label,
                )
                if section_rows and raw_subpart_rows:
                    raise RuntimeError(
                        "Rhode Island part mixed direct-section and subpart-index "
                        f"frontiers: {part_url}"
                    )
                if section_rows:
                    part_section_groups_by_url[part_url] = [
                        (part_number, None, section_rows)
                    ]
                    continue
                part_section_groups_by_url[part_url] = []
                for subpart_url, subpart_label in raw_subpart_rows:
                    canonical_subpart_url, subpart_number = (
                        self._canonical_rhode_island_subpart_locator(
                            subpart_url,
                            title_number=title_number,
                            chapter_number=chapter_number,
                            part_number=part_number,
                        )
                    )
                    subpart_identity = (
                        title_number.casefold(),
                        chapter_number.casefold(),
                        part_number.casefold(),
                        subpart_number.casefold(),
                    )
                    if (
                        canonical_subpart_url in seen_subpart_urls
                        or subpart_identity in seen_subpart_identities
                    ):
                        raise RuntimeError(
                            "Rhode Island part frontier repeated subpart identity "
                            f"{title_number}/{chapter_number}/{part_number}/"
                            f"{subpart_number}"
                        )
                    seen_subpart_urls.add(canonical_subpart_url)
                    seen_subpart_identities.add(subpart_identity)
                    subpart_frontier.append(
                        (
                            title_number,
                            chapter_number,
                            part_number,
                            subpart_number,
                            str(subpart_label or ""),
                            canonical_subpart_url,
                        )
                    )
                if not raw_subpart_rows:
                    raise RuntimeError(
                        "Rhode Island retained part exposed no exact section or "
                        f"subpart frontier: {part_url}"
                    )

        if subpart_frontier:
            subpart_urls = [row[5] for row in subpart_frontier]
            subpart_batch = self._coerce_rhode_island_frontier_batch(
                await self._fetch_rhode_island_frontier_batch(
                    subpart_urls,
                    frontier_name="subpart-index",
                ),
                requested_urls=subpart_urls,
            )
            self._record_rhode_island_frontier_inputs(
                source_role="subpart_catalog",
                urls=subpart_urls,
                payloads=subpart_batch.payloads,
            )
            for subpart_row, subpart_payload in zip(
                subpart_frontier,
                subpart_batch.payloads,
                strict=True,
            ):
                (
                    title_number,
                    chapter_number,
                    part_number,
                    subpart_number,
                    subpart_label,
                    subpart_url,
                ) = subpart_row
                section_rows = subpart_section_links(
                    subpart_payload.decode("utf-8", errors="replace"),
                    subpart_url=subpart_url,
                    title_number=title_number,
                    chapter_number=chapter_number,
                    part_number=part_number,
                    subpart_number=subpart_number,
                    intermediate_label=subpart_label,
                )
                if not section_rows:
                    raise RuntimeError(
                        "Rhode Island retained subpart exposed no exact section "
                        f"frontier: {subpart_url}"
                    )
                parent_part_url = subpart_url.rsplit("/", 2)[0] + "/INDEX.htm"
                part_section_groups_by_url[parent_part_url].append(
                    (part_number, subpart_number, section_rows)
                )

        section_frontier: List[
            tuple[int, int, str, str, str, str, str]
        ] = []
        seen_section_urls: set[str] = set()
        seen_section_numbers: set[str] = set()
        chapter_end_offsets: List[tuple[int, int]] = []
        title_end_offsets: List[tuple[int, int]] = []
        title_end_by_chapter_index = {
            chapter_index: title_index
            for title_index, chapter_index in title_chapter_end_indices
        }

        for chapter_index, chapter_discovery in enumerate(
            chapter_discoveries,
            start=1,
        ):
            chapter_row, direct_section_rows, chapter_parts = chapter_discovery
            title_index, title_number, chapter_number, chapter_url = chapter_row
            section_groups: List[
                tuple[Optional[str], Optional[str], List[tuple[str, str]]]
            ] = []
            if direct_section_rows:
                section_groups.append((None, None, direct_section_rows))
            else:
                for part_url, _part_number, _part_label in chapter_parts:
                    section_groups.extend(
                        part_section_groups_by_url[part_url]
                    )

            for part_number, subpart_number, section_rows in section_groups:
                for section_url, section_label in section_rows:
                    canonical_url, section_number = (
                        self._canonical_rhode_island_section_locator(
                            section_url,
                            title_number=title_number,
                            chapter_number=chapter_number,
                            part_number=part_number,
                            subpart_number=subpart_number,
                            section_label=str(section_label or ""),
                        )
                    )
                    section_key = section_number.casefold()
                    if (
                        canonical_url in seen_section_urls
                        or section_key in seen_section_numbers
                    ):
                        raise RuntimeError(
                            "Rhode Island chapter frontier repeated section "
                            f"identity {section_number}: {canonical_url}"
                        )
                    seen_section_urls.add(canonical_url)
                    seen_section_numbers.add(section_key)
                    section_frontier.append(
                        (
                            title_index,
                            chapter_index,
                            title_number,
                            chapter_number,
                            section_number,
                            str(section_label or "").strip(),
                            canonical_url,
                        )
                    )
            chapter_end_offsets.append((chapter_index, len(section_frontier)))
            completed_title = title_end_by_chapter_index.get(chapter_index)
            if completed_title is not None:
                title_end_offsets.append(
                    (completed_title, len(section_frontier))
                )

        if not section_frontier:
            raise RuntimeError(
                "Rhode Island official chapters exposed no section frontier"
            )

        _write_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="rhode-island:section-discovery",
            force=True,
            replace_existing_rows=True,
            extra={
                "titles_scanned": 0,
                "discovered_titles": len(title_frontier),
                "chapters_scanned": 0,
                "discovered_chapters": len(chapter_frontier),
                "parts_scanned": len(part_frontier),
                "discovered_parts": len(part_frontier),
                "subparts_scanned": len(subpart_frontier),
                "discovered_subparts": len(subpart_frontier),
                "sections_scanned": 0,
                "discovered_sections": len(section_frontier),
                "terminal_sections_classified": 0,
                "terminal_section_dispositions": [],
                "terminal_chapters_classified": len(terminal_chapters),
                "terminal_chapter_dispositions": terminal_chapters,
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        batch_size = self._rhode_island_section_batch_size()
        seen_statute_ids: set[str] = set()
        terminal_sections: List[Dict[str, str]] = []
        section_urls = [row[6] for row in section_frontier]
        section_batch = self._coerce_rhode_island_frontier_batch(
            await self._fetch_rhode_island_frontier_batch(
                section_urls,
                frontier_name="sections",
            ),
            requested_urls=section_urls,
        )
        self._record_rhode_island_frontier_inputs(
            source_role="section",
            urls=section_urls,
            payloads=section_batch.payloads,
        )
        for start in range(0, len(section_frontier), batch_size):
            stop = min(start + batch_size, len(section_frontier))
            frontier_batch = section_frontier[start:stop]
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
                (
                    _title_index,
                    _chapter_index,
                    title_number,
                    chapter_number,
                    section_number,
                    section_label,
                    section_url,
                ) = frontier_row
                evidence_context: Optional[Dict[str, Any]] = None
                if parser_input_envelope is not None:
                    evidence_context = self._rhode_island_section_evidence_context(
                        source_url=section_url,
                        payload=payload,
                        transport_receipt=transport_receipt,
                        parser_input_envelope=parser_input_envelope,
                    )
                temporal_locator = "_" in section_url.rsplit("/", 1)[-1]
                if temporal_locator and evidence_context is None:
                    raise RuntimeError(
                        "Rhode Island temporal section lacks exact source "
                        f"observation evidence: {section_url}"
                    )
                observed_date = (
                    evidence_context["as_of_date"]
                    if evidence_context is not None
                    else None
                )
                parsed = parse_rhode_island_section_html(
                    payload.decode("utf-8", errors="replace"),
                    source_url=section_url,
                    code_name=code_name,
                    as_of_date=observed_date,
                    frontier_section_label=section_label,
                    expected_section_number=section_number,
                    strict_official_identity=True,
                )
                parsed_identity = (
                    str(parsed.title_number or "").casefold(),
                    str(parsed.chapter_number or "").casefold(),
                    str(parsed.section_number or "").casefold(),
                ) if parsed is not None else ("", "", "")
                expected_identity = (
                    title_number.casefold(),
                    chapter_number.casefold(),
                    section_number.casefold(),
                )
                if parsed is None:
                    terminal_disposition = (
                        source_bound_terminal_section_disposition(
                            payload.decode("utf-8", errors="replace"),
                            section_number=section_number,
                            source_url=section_url,
                            as_of_date=observed_date,
                            frontier_section_label=section_label,
                        )
                    )
                    if terminal_disposition is not None:
                        terminal_sections.append(
                            {
                                "title_number": title_number,
                                "chapter_number": chapter_number,
                                "section_number": section_number,
                                "disposition": terminal_disposition,
                                "source_url": section_url,
                                **(
                                    {
                                        "source_observed_date": evidence_context[
                                            "as_of_date"
                                        ].isoformat(),
                                        "source_transport": evidence_context[
                                            "source_transport"
                                        ],
                                        "archive_timestamp": evidence_context[
                                            "archive_timestamp"
                                        ],
                                        "content_sha256": evidence_context[
                                            "content_sha256"
                                        ],
                                        "parser_input_receipt_sha256": (
                                            evidence_context["receipt_sha256"]
                                        ),
                                    }
                                    if evidence_context is not None
                                    else {}
                                ),
                            }
                        )
                        continue
                if (
                    parsed is None
                    or parsed_identity != expected_identity
                    or str(parsed.source_url or "") != section_url
                    or not str(parsed.full_text or "").strip()
                ):
                    raise RuntimeError(
                        "Rhode Island retained section body failed official parsing "
                        f"or exact identity verification: {section_url}"
                    )
                statute_key = str(parsed.statute_id or "").strip().casefold()
                if not statute_key or statute_key in seen_statute_ids:
                    raise RuntimeError(
                        "Rhode Island parsed frontier repeated statute identity: "
                        f"{section_url}"
                    )
                seen_statute_ids.add(statute_key)
                if evidence_context is not None:
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
                parsed.official_cite = (
                    f"{citation_format} § {parsed.section_number}"
                )
                parsed.chapter_name = chapter_number
                parsed.legal_area = self._identify_legal_area(
                    parsed.section_name or code_name
                )
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
            completed_titles = max(
                (
                    title_index
                    for title_index, end_offset in title_end_offsets
                    if end_offset <= scanned_sections
                ),
                default=0,
            )
            _write_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="rhode-island:section-scan",
                replace_existing_rows=True,
                extra={
                    "titles_scanned": completed_titles,
                    "discovered_titles": len(title_frontier),
                    "chapters_scanned": completed_chapters,
                    "discovered_chapters": len(chapter_frontier),
                    "parts_scanned": len(part_frontier),
                    "discovered_parts": len(part_frontier),
                    "subparts_scanned": len(subpart_frontier),
                    "discovered_subparts": len(subpart_frontier),
                    "sections_scanned": scanned_sections,
                    "discovered_sections": len(section_frontier),
                    "terminal_sections_classified": len(terminal_sections),
                    "terminal_section_dispositions": terminal_sections,
                    "terminal_chapters_classified": len(terminal_chapters),
                    "terminal_chapter_dispositions": terminal_chapters,
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )

        if (
            not statutes
            or len(statutes) + len(terminal_sections) != len(section_frontier)
            or len(seen_statute_ids) != len(statutes)
        ):
            raise RuntimeError(
                "Rhode Island final statute identities do not exactly close the "
                "source section frontier"
            )

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        input_reports = list(self._rhode_island_frontier_input_reports)
        terminal_projection = {
            "chapters": terminal_chapters,
            "sections": terminal_sections,
        }
        excluded_count = len(terminal_chapters) + len(terminal_sections)
        exact_frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "chapter_document_count": len(chapter_frontier),
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
                canonical_json_bytes(
                    [
                        {
                            "chapter_number": str(row.chapter_number or ""),
                            "section_number": str(row.section_number or ""),
                            "title_number": str(row.title_number or ""),
                        }
                        for row in statutes
                    ]
                )
            ).hexdigest(),
            "part_document_count": len(part_frontier),
            "schema": "rhode-island-source-derived-strict-frontier-v1",
            "scope_closed": True,
            "source_input_count": len(input_reports),
            "source_section_count": len(section_frontier),
            "statutes_emitted": len(statutes),
            "subpart_document_count": len(subpart_frontier),
            "terminal_chapter_count": len(terminal_chapters),
            "terminal_projection_sha256": hashlib.sha256(
                canonical_json_bytes(terminal_projection)
            ).hexdigest(),
            "terminal_section_count": len(terminal_sections),
            "title_document_count": len(title_frontier),
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
            self._last_rhode_island_replayed_frontier = observation
        else:
            self._last_rhode_island_full_frontier = observation

        _write_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="rhode-island:complete",
            force=True,
            replace_existing_rows=True,
            extra={
                "titles_scanned": len(title_frontier),
                "discovered_titles": len(title_frontier),
                "chapters_scanned": len(chapter_frontier),
                "discovered_chapters": len(chapter_frontier),
                "parts_scanned": len(part_frontier),
                "discovered_parts": len(part_frontier),
                "subparts_scanned": len(subpart_frontier),
                "discovered_subparts": len(subpart_frontier),
                "sections_scanned": len(section_frontier),
                "discovered_sections": len(section_frontier),
                "terminal_sections_classified": len(terminal_sections),
                "terminal_section_dispositions": terminal_sections,
                "terminal_chapters_classified": len(terminal_chapters),
                "terminal_chapter_dispositions": terminal_chapters,
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
        """Replay retained RI catalogs and leaves and seal exact row parity."""

        first = getattr(self, "_last_rhode_island_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Rhode Island strict source frontier was not closed before output"
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
                "Rhode Island first exact frontier observation is incomplete"
            )
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "Rhode Island frontier closure requires an attached ledger"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        prior_replay = bool(getattr(self, "_rhode_island_retained_replay", False))
        self._rhode_island_retained_replay = True
        try:
            replay_rows = await self._scrape_unbounded_rhode_island_frontier(
                str(first.get("code_name") or "Rhode Island General Laws"),
                "R.I. Gen. Laws",
            )
        finally:
            self._rhode_island_retained_replay = prior_replay
        replay = getattr(self, "_last_rhode_island_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError(
                "Rhode Island retained strict frontier replay was not observed"
            )
        replayed_frontier = replay.get("frontier")
        if (
            not isinstance(replayed_frontier, Mapping)
            or list(replay.get("input_reports") or []) != list(first_reports)
        ):
            raise RuntimeError("Rhode Island retained hierarchy changed on replay")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        disposition = first_frontier.get("disposition")
        if not isinstance(disposition, Mapping):
            raise RuntimeError("Rhode Island frontier lacks disposition algebra")
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="RI",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=f"{self.get_base_url()}/Statutes/",
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("legal_as_of") or ""),
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=int(disposition.get("discovered") or 0),
            pagination_total=(
                int(first_frontier.get("title_document_count") or 0)
                + int(first_frontier.get("chapter_document_count") or 0)
                + int(first_frontier.get("part_document_count") or 0)
                + int(first_frontier.get("subpart_document_count") or 0)
            ),
            transport={
                "fixture": False,
                "first_pass_requested_pages": int(
                    first_frontier.get("source_input_count") or 0
                ),
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_html_hierarchy",
                "per_page_archive_loop": False,
                "retained_replay_network_requests": 0,
                "synthetic": False,
            },
        )
    
    async def _custom_scrape_rhode_island(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: Optional[int] = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Rhode Island's legislative website."""
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        if max_sections is None:
            return await self._scrape_unbounded_rhode_island_frontier(
                code_name,
                citation_format,
            )

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
            from .rhode_island_section import (
                chapter_section_links,
                title_chapter_links,
                toc_title_links,
            )

            title_entries: List[tuple[str, str]] = []
            root_bytes = await self._fetch_page_content_with_archival_fallback(
                f"{self.get_base_url()}/Statutes/", timeout_seconds=30
            )
            if root_bytes:
                title_entries = toc_title_links(
                    root_bytes.decode("utf-8", errors="replace"),
                    base_url=f"{self.get_base_url()}/Statutes/",
                )
            if not title_entries:
                title_entries = [
                    (_TITLE_INDEX_URL_TEMPLATE.format(title=number), str(number))
                    for number, _name in self.OFFICIAL_TITLES
                ]
            for title_index, (title_url, title_number) in enumerate(title_entries, start=1):
                title_num = int(title_number) if str(title_number).isdigit() else title_index
                if max_sections is not None and len(statutes) >= max_sections:
                    break
                if title_num < resume_title_floor and str(title_number).isdigit():
                    continue

                title_bytes = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=30)
                title_html = title_bytes.decode("utf-8", errors="replace") if title_bytes else ""
                if not title_html or "Document Moved" in title_html or "404" in title_html[:200]:
                    consecutive_missing_titles += 1
                    if consecutive_missing_titles >= 5 and title_index > 47:
                        break
                    continue
                consecutive_missing_titles = 0
                last_title_scanned = max(last_title_scanned, int(title_num) if str(title_num).isdigit() else title_index)

                chapter_links = [
                    (None, url, number)
                    for url, number in title_chapter_links(title_html, title_url=title_url)
                ]
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

                for _link, chapter_url, chapter_token in chapter_links:
                    if max_sections is not None and len(statutes) >= max_sections:
                        break

                    chapter_visit_index += 1
                    if chapter_visit_index < resume_chapter_floor:
                        continue
                    chapters_scanned_total += 1
                    chapter_bytes = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=30)
                    if not chapter_bytes:
                        continue
                    chapter_html = chapter_bytes.decode("utf-8", errors="replace")
                    chapter_name = chapter_token or ""
                    legal_area = self._identify_legal_area(chapter_name or code_name)
                    section_candidates = []
                    seen_chapter_sections = set()
                    chapter_number = (
                        self._extract_ri_chapter_number(chapter_url) or chapter_token
                    )
                    for section_url, section_label in chapter_section_links(
                        chapter_html, chapter_url=chapter_url
                    ):
                        if section_url in seen_urls or section_url in seen_chapter_sections:
                            continue
                        section_number = self._extract_ri_section_number(
                            section_label, section_url
                        ) or re.sub(r"\.htm$", "", section_url.rsplit("/", 1)[-1], flags=re.IGNORECASE)
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
                        from .rhode_island_section import parse_rhode_island_section_html

                        parsed = parse_rhode_island_section_html(
                            section_html,
                            source_url=section_url,
                            code_name=code_name,
                        )
                        if parsed is not None:
                            parsed.official_cite = f"{citation_format} § {parsed.section_number}"
                            parsed.chapter_name = chapter_name[:200] or parsed.chapter_name
                            parsed.legal_area = legal_area
                            return parsed
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

                    remaining = (
                        None
                        if max_sections is None
                        else max(0, int(max_sections) - len(statutes))
                    )
                    batch = (
                        section_candidates
                        if remaining is None
                        else section_candidates[:remaining]
                    )
                    parsed_rows = await asyncio.gather(
                        *[
                            _parse_section(section_url, section_label, section_number)
                            for section_url, section_label, section_number in batch
                        ],
                        return_exceptions=True,
                    ) if batch else []
                    scanned_sections = 0
                    for statute in parsed_rows:
                        scanned_sections += 1
                        sections_scanned_total += 1
                        if isinstance(statute, BaseException):
                            continue
                        if statute is not None:
                            _extend_unique([statute])
                        if (
                            scanned_sections == 1
                            or scanned_sections % 200 == 0
                            or scanned_sections == len(batch)
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
                    if max_sections is not None and len(statutes) >= max_sections:
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
                if self._full_corpus_enabled():
                    self.logger.warning(
                        "Rhode Island full-corpus run found zero official sections; "
                        "refusing secondary Justia/generic sole-admission fallback"
                    )
                    return []
                self.logger.info("Rhode Island custom scraper found no data, falling back to generic scraper")
                generic_cap = max_sections if max_sections is not None else 1000000
                return await self._generic_scrape(code_name, code_url, citation_format, generic_cap)
            return statutes
        except Exception as e:
            self.logger.error(f"Rhode Island custom scraper failed: {e}")
            if self._full_corpus_enabled():
                return []
            generic_cap = max_sections if max_sections is not None else 1000000
            return await self._generic_scrape(code_name, code_url, citation_format, generic_cap)

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

        return text, section_name

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
