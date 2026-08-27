"""Scraper for Virginia state laws.

This module contains the scraper for Virginia statutes from the official state legislative website.
"""

import asyncio
import hashlib
import json
import re
import ssl
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StateLawPageMultiFetchResult,
    StatuteMetadata,
    _sanitized_multifetch_headers,
    _sanitized_multifetch_request,
)
from .registry import StateScraperRegistry


class VirginiaScraper(BaseStateScraper):
    """Scraper for Virginia state laws from https://law.lis.virginia.gov"""

    OFFICIAL_DOMAIN = "law.lis.virginia.gov"
    OFFICIAL_ENTRY_PATH = "/vacode/"
    OFFICIAL_ENTRY_URL = "https://law.lis.virginia.gov/vacode/"
    OFFICIAL_LIBRARY_PATH = "/law-library"
    OFFICIAL_LIBRARY_URL = "https://law.lis.virginia.gov/law-library"
    STRICT_EXPECTED_TITLE_CSVS = 76
    STRICT_EXPECTED_CONTINGENT_SECTION_PAGES = 32
    STRICT_EXPECTED_BODY_HYDRATION_PAGES = 0
    STRICT_EXPECTED_OFFICIAL_EMPTY_PLACEHOLDER_PAGES = 1
    STRICT_EXPECTED_CURRENT_SECTION_PAGES = 33
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
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            virginia_csv,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            virginia_csv,
            wayback_machine_engine,
        )

    @staticmethod
    def _virginia_frontier_headers(media_type: str) -> dict[str, str]:
        return {
            "Accept": (
                "text/csv,text/plain;q=0.9,*/*;q=0.7"
                if media_type == "text/csv"
                else "text/html,application/xhtml+xml;q=0.9,*/*;q=0.7"
            ),
            "User-Agent": "ipfs-datasets-virginia-laws/2.0",
        }

    def _virginia_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                24,
                self._env_int("STATE_SCRAPER_VA_FRONTIER_CONCURRENCY", default=8),
            ),
        )

    def _virginia_frontier_batch_size(self) -> int:
        return max(
            2,
            min(
                128,
                self._env_int("STATE_SCRAPER_VA_FRONTIER_BATCH_SIZE", default=128),
            ),
        )

    @classmethod
    def _is_valid_virginia_law_library(cls, payload: bytes) -> bool:
        sample = bytes(payload or b"").lower()
        if not (
            len(sample) > 5_000
            and b"virginia law online library" in sample
            and b"/csv/covtitle_" in sample
        ):
            return False
        try:
            from .virginia_csv import virginia_title_csv_links

            rows = virginia_title_csv_links(
                payload,
                base_url=cls.OFFICIAL_LIBRARY_URL,
            )
        except Exception:
            return False
        title_numbers = [str(row[0]).strip().casefold() for row in rows]
        title_urls = [str(row[2]).strip() for row in rows]
        return bool(
            len(rows) == int(cls.STRICT_EXPECTED_TITLE_CSVS)
            and len(title_numbers) == len(set(title_numbers))
            and len(title_urls) == len(set(title_urls))
            and all(
                (urlparse(url).scheme or "").casefold() == "https"
                and (urlparse(url).hostname or "").casefold()
                == cls.OFFICIAL_DOMAIN
                for url in title_urls
            )
        )

    @staticmethod
    def _is_valid_virginia_title_csv(payload: bytes) -> bool:
        raw = bytes(payload or b"")
        if len(raw) < 180 or b"\x00" in raw:
            return False
        try:
            first_line = raw.decode("utf-8-sig", errors="strict").splitlines()[0]
        except (IndexError, UnicodeError):
            return False
        return first_line == (
            "TitleNum,TitleName,SubTitleNum,SubTitleName,PartNum,PartName,"
            "ChapterNum,ChapterName,ArticleNum,ArticleName,SubPartNum,SubPartName,"
            "Section,Title,Body"
        )

    @staticmethod
    def _is_valid_virginia_current_section_page(payload: bytes) -> bool:
        try:
            from .virginia_csv import (
                virginia_current_section_body_text,
                virginia_current_section_identity,
                virginia_official_empty_placeholder_evidence,
            )

            return bool(
                (
                    virginia_current_section_identity(payload)
                    and virginia_current_section_body_text(payload)
                )
                or virginia_official_empty_placeholder_evidence(payload)
            )
        except Exception:
            return False

    @staticmethod
    def _is_valid_virginia_official_empty_placeholder_page(
        payload: bytes,
    ) -> bool:
        """Validate only the exact current § 19.2-399 empty-body witness."""

        try:
            from .virginia_csv import (
                virginia_official_empty_placeholder_evidence,
            )

            return bool(virginia_official_empty_placeholder_evidence(payload))
        except Exception:
            return False

    @staticmethod
    def _virginia_source_observation(envelope: Any) -> tuple[str, datetime]:
        receipt = getattr(
            getattr(envelope, "acquisition", None),
            "receipt",
            None,
        )
        retrieved_at = getattr(receipt, "retrieved_at", None)
        if isinstance(retrieved_at, datetime):
            observed = retrieved_at
        elif retrieved_at:
            observed = datetime.fromisoformat(str(retrieved_at).replace("Z", "+00:00"))
        else:
            observed = datetime.now(UTC)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        observed = observed.astimezone(UTC)
        return observed.isoformat(), observed

    def _validate_virginia_aligned_evidence(
        self,
        *,
        url: str,
        payload: bytes,
        transport_receipt: Any,
        parser_input_envelope: Any,
        frontier_name: str,
    ) -> None:
        canonical_url = self._canonical_fetch_url(url)
        digest = hashlib.sha256(payload).hexdigest()
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if ledger_attached and (
            not isinstance(transport_receipt, Mapping)
            or not transport_receipt
            or parser_input_envelope is None
        ):
            raise RuntimeError(
                f"Virginia {frontier_name} frontier lacks retained evidence: {url}"
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
                    f"Virginia {frontier_name} receipt lacks URL/digest: {url}"
                )
            if observed_url and self._canonical_fetch_url(observed_url) != canonical_url:
                raise RuntimeError(
                    f"Virginia {frontier_name} receipt changed URL identity: {url}"
                )
            if observed_digest and observed_digest != digest:
                raise RuntimeError(
                    f"Virginia {frontier_name} receipt changed payload identity: {url}"
                )
        if parser_input_envelope is not None:
            envelope_body = getattr(parser_input_envelope, "body", None)
            if ledger_attached and envelope_body is None:
                raise RuntimeError(
                    f"Virginia {frontier_name} envelope lacks body evidence: {url}"
                )
            if envelope_body is not None and bytes(envelope_body) != payload:
                raise RuntimeError(
                    f"Virginia {frontier_name} envelope changed payload identity: {url}"
                )

    async def _fetch_virginia_frontier_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Callable[[bytes], bool],
        media_type: str,
        common_crawl_url_terms: Sequence[str],
    ) -> StateLawPageMultiFetchResult:
        """Fetch one exact plural frontier through grouped archive recovery."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if not requested:
            return StateLawPageMultiFetchResult([], [], [], [], [], {})
        if any(not url for url in requested) or len(set(requested)) != len(requested):
            raise RuntimeError(
                f"Virginia {frontier_name} frontier has invalid or duplicate URLs"
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
            timeout_seconds=60 if media_type == "text/csv" else 25,
            headers=self._virginia_frontier_headers(media_type),
            content_validator=content_validator,
            media_type=media_type,
            max_concurrency=self._virginia_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN, "lis.virginia.gov"),
            common_crawl_url_terms=tuple(common_crawl_url_terms),
            common_crawl_mime_terms=(
                ("csv", "text/plain", "octet-stream")
                if media_type == "text/csv"
                else ("html",)
            ),
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
                f"Virginia {frontier_name} frontier changed exact URL alignment"
            )
        failures: list[dict[str, str]] = []
        for url, payload, error, receipt, envelope in zip(
            batch.urls,
            batch.payloads,
            batch.errors,
            batch.transport_receipts,
            batch.parser_input_envelopes,
            strict=True,
        ):
            raw = bytes(payload or b"")
            if error is not None or not raw or not content_validator(raw):
                failures.append(
                    {"url": url, "error": str(error or "empty or invalid parser input")}
                )
                continue
            self._validate_virginia_aligned_evidence(
                url=url,
                payload=raw,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
                frontier_name=frontier_name,
            )
        if failures:
            raise RuntimeError(
                f"Virginia {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures[:10]}"
            )
        stats_rows = list(getattr(self, "_virginia_frontier_batch_stats", []))
        stats_rows.append(
            {
                **dict(batch.stats or {}),
                "frontier_name": frontier_name,
                "requested_pages": len(requested),
            }
        )
        self._virginia_frontier_batch_stats = stats_rows
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    def _replay_virginia_retained_batch(
        self,
        inputs: Sequence[
            tuple[str, str, Callable[[bytes], bool], str]
        ],
    ) -> StateLawPageMultiFetchResult:
        """Replay one ordered retained catalog/CSV batch without network access."""

        from .strict_frontier_closure import replay_exact_retained_state_records

        normalized: list[
            tuple[str, str, Callable[[bytes], bool], str]
        ] = []
        requests: list[tuple[str, Mapping[str, Any]]] = []
        for url, media_type, content_validator, frontier_name in inputs:
            canonical_url = self._canonical_fetch_url(url)
            if not canonical_url:
                raise RuntimeError("Virginia retained replay contains an empty URL")
            sanitized_headers = _sanitized_multifetch_headers(
                self._virginia_frontier_headers(media_type)
            )
            normalized.append(
                (canonical_url, media_type, content_validator, frontier_name)
            )
            requests.append(
                (
                    canonical_url,
                    _sanitized_multifetch_request(
                        canonical_url,
                        sanitized_headers=sanitized_headers,
                    ),
                )
            )
        if not normalized or len({row[0] for row in normalized}) != len(normalized):
            raise RuntimeError(
                "Virginia retained replay requires nonempty unique exact inputs"
            )
        retained_rows = replay_exact_retained_state_records(
            self,
            requests=requests,
            frontier_name="Virginia exact Law Library/title CSV frontier",
            refresh=False,
        )
        payloads: list[bytes] = []
        receipts: list[Mapping[str, Any]] = []
        envelopes: list[Any] = []
        for (url, _media_type, validator, frontier_name), retained in zip(
            normalized,
            retained_rows,
            strict=True,
        ):
            envelope = getattr(retained, "envelope", None)
            raw = bytes(getattr(envelope, "body", b"") or b"")
            if not raw or not validator(raw):
                raise RuntimeError(
                    f"Virginia retained replay input is invalid: {url}"
                )
            receipt = dict(getattr(retained, "transport_receipt", {}) or {})
            self._validate_virginia_aligned_evidence(
                url=url,
                payload=raw,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
                frontier_name=frontier_name,
            )
            payloads.append(raw)
            receipts.append(receipt)
            envelopes.append(envelope)
        requested_pages = len(normalized)
        stats = {
            "network_requested_pages": 0,
            "requested_pages": requested_pages,
            "retained_replay_pages": requested_pages,
            "retained_replay_unique_pages": requested_pages,
            "successful_pages": requested_pages,
            "unique_pages": requested_pages,
        }
        self._last_virginia_replay_batch_stats = dict(stats)
        return StateLawPageMultiFetchResult(
            urls=[row[0] for row in normalized],
            payloads=payloads,
            errors=[None] * requested_pages,
            transport_receipts=receipts,
            parser_input_envelopes=envelopes,
            stats=stats,
        )

    def _virginia_exact_frontier(
        self,
        *,
        catalog_content_sha256: str,
        title_reports: Sequence[Mapping[str, Any]],
        current_section_reports: Sequence[Mapping[str, Any]],
        observation_date: str,
        terminal_dispositions: Mapping[str, int],
        source_status_records: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        source_records = sum(int(row["source_records"]) for row in title_reports)
        operative_records = sum(int(row["operative_records"]) for row in title_reports)
        terminal_records = sum(int(row["terminal_records"]) for row in title_reports)
        source_status_count = sum(
            int(row.get("source_status_records") or 0) for row in title_reports
        )
        status_rows = [dict(row) for row in source_status_records]
        status_identities = [
            str(row.get("section_number") or "").strip().casefold()
            for row in status_rows
        ]
        if (
            len(status_rows) != source_status_count
            or any(not identity for identity in status_identities)
            or len(status_identities) != len(set(status_identities))
        ):
            raise RuntimeError(
                "Virginia source-status records did not preserve unique identities"
            )
        if (
            source_records
            != operative_records + terminal_records + source_status_count
        ):
            raise RuntimeError("Virginia exact CSV source algebra did not close")
        disposition = {
            "discovered": source_records,
            "fetched": operative_records,
            "excluded": terminal_records + source_status_count,
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        }
        source_rows = [
            {
                "title_number": str(row["title_number"]),
                "source_url": str(row["source_url"]),
                "content_sha256": str(row["content_sha256"]),
            }
            for row in title_reports
        ]
        source_frontier_sha256 = hashlib.sha256(
            json.dumps(source_rows, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        current_section_rows = [
            {
                "section_number": str(row["section_number"]),
                "source_url": str(row["source_url"]),
                "content_sha256": str(row["content_sha256"]),
                "purpose": str(row["purpose"]),
            }
            for row in current_section_reports
        ]
        current_section_frontier_sha256 = hashlib.sha256(
            json.dumps(
                current_section_rows,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        frontier: dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": True,
            "catalog_content_sha256": str(catalog_content_sha256),
            "catalog_title_count": len(title_reports),
            "closed": True,
            "current_section_frontier_sha256": current_section_frontier_sha256,
            "current_section_page_count": len(current_section_reports),
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": source_records,
            "pagination_closed": True,
            "parser_input_count": 1 + len(title_reports) + len(current_section_reports),
            "schema_version": "virginia-title-csv-source-frontier-v1",
            "scope_closed": True,
            "source_record_count": source_records,
            "source_status_record_count": source_status_count,
            "source_status_records": status_rows,
            "source_statuses": {
                str(status): sum(
                    1
                    for row in source_status_records
                    if str(row.get("source_status") or "") == str(status)
                )
                for status in sorted(
                    {
                        str(row.get("source_status") or "")
                        for row in source_status_records
                        if str(row.get("source_status") or "")
                    }
                )
            },
            "source_observation_date": str(observation_date),
            "terminal_dispositions": {
                str(key): int(value)
                for key, value in sorted(terminal_dispositions.items())
            },
            "title_csv_document_count": len(title_reports),
            "title_csv_frontier_sha256": source_frontier_sha256,
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": source_records,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    _VA_SECTION_URL_RE = re.compile(
        r"^/vacode/title[0-9A-Za-z\.]+/chapter[0-9A-Za-z\.]+/section[0-9A-Za-z\-\.:]+/?$",
        re.IGNORECASE,
    )
    _VA_DIRECT_SECTION_URL_RE = re.compile(
        r"^/vacode/[0-9A-Za-z\.]+-[0-9A-Za-z\-\.:]+/?$",
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
            r"/vacode/title[0-9A-Za-z.]+/chapter[0-9A-Za-z.]+/section([0-9A-Za-z.:\-]+)/?$",
            path,
            flags=re.IGNORECASE,
        )
        if section_match:
            return str(section_match.group(1) or "").strip()
        direct_match = re.search(
            r"/vacode/([0-9A-Za-z.]+-[0-9A-Za-z.:\-]+)/?$", path, flags=re.IGNORECASE
        )
        if direct_match:
            return str(direct_match.group(1) or "").strip()
        return ""

    def get_base_url(self) -> str:
        """Return the base URL for Virginia's legislative website."""
        return "https://law.lis.virginia.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Virginia."""
        return [
            {
                "name": "Code of Virginia",
                "url": f"{self.get_base_url()}/vacode/",
                "type": "Code",
            }
        ]

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
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .virginia_constitution import (
            configured_constitution_html_path,
            parse_virginia_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_virginia_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Virginia Constitution",
                    source_url="https://law.lis.virginia.gov/constitution/article1/section1/",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        official = self._filter_official_only(official)
        if official:
            return official[:limit] if limit is not None else official

        if limit is not None:
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
            direct = self._filter_official_only(direct)
            if direct:
                return direct[:limit]

        if self._full_corpus_enabled() and max_statutes is None:
            self.logger.warning(
                "Virginia full-corpus run found zero official statutes; "
                "refusing secondary Justia/generic sole-admission fallback"
            )
            return []

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
        section_urls = [
            "https://law.lis.virginia.gov/vacode/title1/chapter1/section1-1/",
            "https://law.lis.virginia.gov/vacode/title18.2/chapter7/section18.2-247/",
        ]
        return await self._scrape_section_urls(
            code_name,
            [(url, "") for url in section_urls],
            max_statutes=max_statutes,
            discovery_method="official_direct_section",
        )

    async def _scrape_official_title_csv_frontier(
        self,
        code_name: str,
    ) -> list[NormalizedStatute]:
        """Close the source-derived Law Library catalog over bulk title CSVs."""

        from .virginia_csv import (
            parse_virginia_title_csv_closure,
            virginia_current_section_frontier,
            virginia_title_csv_links,
        )

        self._virginia_frontier_batch_stats = []
        catalog_batch = await self._fetch_virginia_frontier_batch(
            [self.OFFICIAL_LIBRARY_URL],
            frontier_name="law-library-catalog",
            content_validator=self._is_valid_virginia_law_library,
            media_type="text/html",
            common_crawl_url_terms=(self.OFFICIAL_LIBRARY_PATH,),
        )
        catalog_payload = bytes(catalog_batch.payloads[0])
        observed_at, observed_datetime = self._virginia_source_observation(
            catalog_batch.parser_input_envelopes[0]
            if catalog_batch.parser_input_envelopes
            else None
        )
        observation_date = observed_datetime.date()
        catalog_rows = virginia_title_csv_links(
            catalog_payload,
            base_url=self.OFFICIAL_LIBRARY_URL,
        )
        title_numbers = [str(row[0]).strip() for row in catalog_rows]
        title_urls = [self._canonical_fetch_url(str(row[2])) for row in catalog_rows]
        if (
            len(catalog_rows) != int(self.STRICT_EXPECTED_TITLE_CSVS)
            or len(title_numbers) != len({number.casefold() for number in title_numbers})
            or len(title_urls) != len(set(title_urls))
            or any(not self._host_is_official(url) for url in title_urls)
            or any(
                re.fullmatch(
                    r"https://law\.lis\.virginia\.gov/CSV/CoVTitle_"
                    r"\d+(?:\.\d+)?[A-Za-z]?\.csv",
                    url,
                    flags=re.IGNORECASE,
                )
                is None
                for url in title_urls
            )
        ):
            raise RuntimeError(
                "Virginia official Law Library did not expose a closed title CSV "
                f"catalog: observed={len(catalog_rows)} "
                f"expected={self.STRICT_EXPECTED_TITLE_CSVS}"
            )

        title_inputs: list[dict[str, Any]] = []
        batch_size = self._virginia_frontier_batch_size()
        for start in range(0, len(catalog_rows), batch_size):
            selected_rows = catalog_rows[start : start + batch_size]
            selected_urls = title_urls[start : start + batch_size]
            batch = await self._fetch_virginia_frontier_batch(
                selected_urls,
                frontier_name=f"title-csv-{start + 1}-{start + len(selected_rows)}",
                content_validator=self._is_valid_virginia_title_csv,
                media_type="text/csv",
                common_crawl_url_terms=("/CSV/", "CoVTitle_", ".csv"),
            )
            for catalog_row, source_url, payload, receipt in zip(
                selected_rows,
                batch.urls,
                batch.payloads,
                batch.transport_receipts,
                strict=True,
            ):
                title_number, title_name, expected_url = catalog_row
                if self._canonical_fetch_url(expected_url) != source_url:
                    raise RuntimeError(
                        "Virginia title CSV acquisition changed catalog URL identity"
                    )
                raw = bytes(payload)
                content_sha256 = hashlib.sha256(raw).hexdigest()
                title_inputs.append(
                    {
                        "title_number": title_number,
                        "title_name": title_name,
                        "source_url": source_url,
                        "raw": raw,
                        "content_sha256": content_sha256,
                        "receipt": dict(receipt or {}),
                    }
                )

        if len(title_inputs) != len(catalog_rows):
            raise RuntimeError("Virginia title CSV document frontier did not reconcile")

        current_specs: list[dict[str, str]] = []
        for title_input in title_inputs:
            title_number = str(title_input["title_number"])
            for section_number, source_url, purpose in virginia_current_section_frontier(
                bytes(title_input["raw"]),
                expected_title_number=title_number,
            ):
                current_specs.append(
                    {
                        "title_number": title_number,
                        "section_number": section_number,
                        "source_url": self._canonical_fetch_url(source_url),
                        "purpose": purpose,
                    }
                )
        current_urls = [row["source_url"] for row in current_specs]
        purpose_counts: dict[str, int] = {}
        for row in current_specs:
            purpose = row["purpose"]
            purpose_counts[purpose] = purpose_counts.get(purpose, 0) + 1
        if (
            len(current_specs) != int(self.STRICT_EXPECTED_CURRENT_SECTION_PAGES)
            or purpose_counts.get("contingent_variant_selector", 0)
            != int(self.STRICT_EXPECTED_CONTINGENT_SECTION_PAGES)
            or purpose_counts.get("operative_body_hydration", 0)
            != int(self.STRICT_EXPECTED_BODY_HYDRATION_PAGES)
            or purpose_counts.get("official_empty_placeholder_witness", 0)
            != int(self.STRICT_EXPECTED_OFFICIAL_EMPTY_PLACEHOLDER_PAGES)
            or len(current_urls) != len(set(current_urls))
            or len({row["section_number"].casefold() for row in current_specs})
            != len(current_specs)
            or any(not self._host_is_official(url) for url in current_urls)
            or any(not self._is_section_source_url(url) for url in current_urls)
        ):
            raise RuntimeError(
                "Virginia current-section witness frontier did not close: "
                f"observed={len(current_specs)} "
                f"expected={self.STRICT_EXPECTED_CURRENT_SECTION_PAGES} "
                f"purposes={dict(sorted(purpose_counts.items()))}"
            )

        current_section_reports: list[dict[str, Any]] = []
        current_pages_by_title: dict[str, dict[str, bytes]] = {}
        if current_urls:
            current_batch = await self._fetch_virginia_frontier_batch(
                current_urls,
                frontier_name=(
                    "current-section-pages-1-"
                    f"{len(current_urls)}"
                ),
                content_validator=self._is_valid_virginia_current_section_page,
                media_type="text/html",
                common_crawl_url_terms=("/vacode/", "/section"),
            )
            for spec, source_url, payload in zip(
                current_specs,
                current_batch.urls,
                current_batch.payloads,
                strict=True,
            ):
                if source_url != spec["source_url"]:
                    raise RuntimeError(
                        "Virginia current-section acquisition changed URL identity"
                    )
                raw = bytes(payload)
                current_pages_by_title.setdefault(
                    spec["title_number"], {}
                )[source_url] = raw
                current_section_reports.append(
                    {
                        **spec,
                        "content_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                )

        statutes: list[NormalizedStatute] = []
        seen_identities: set[str] = set()
        title_reports: list[dict[str, Any]] = []
        terminal_counts: dict[str, int] = {}
        source_status_records: list[dict[str, Any]] = []
        for title_input in title_inputs:
            title_number = str(title_input["title_number"])
            title_name = str(title_input["title_name"])
            source_url = str(title_input["source_url"])
            raw = bytes(title_input["raw"])
            content_sha256 = str(title_input["content_sha256"])
            report = parse_virginia_title_csv_closure(
                raw,
                expected_title_number=title_number,
                expected_title_name=title_name,
                code_name=code_name,
                source_bundle_url=source_url,
                observation_date=observation_date,
                current_section_pages=current_pages_by_title.get(title_number, {}),
            )
            if report.title_number != title_number or not report.closed:
                raise RuntimeError(
                    "Virginia title CSV failed exact parser closure: "
                    f"title={title_number} source={report.source_record_count} "
                    f"operative={len(report.statutes)} "
                    f"terminal={len(report.terminal_records)} "
                    f"source_status={len(report.source_status_records)} "
                    f"residuals={report.unclassified_records[:10]}"
                )
            receipt_dict = dict(title_input["receipt"])
            for terminal in report.terminal_records:
                disposition = str(terminal.get("disposition") or "excluded")
                terminal_counts[disposition] = (
                    terminal_counts.get(disposition, 0) + 1
                )
            source_status_records.extend(
                dict(status) for status in report.source_status_records
            )
            for statute in report.statutes:
                identity = str(statute.statute_id or "").strip().casefold()
                if not identity or identity in seen_identities:
                    raise RuntimeError(
                        "Virginia CSV frontier repeated normalized statute identity: "
                        f"{statute.statute_id}"
                    )
                seen_identities.add(identity)
                statute.legal_area = self._identify_legal_area(
                    str(statute.section_name or statute.full_text or "")
                )
                statute.structured_data = {
                    **dict(statute.structured_data or {}),
                    "content_sha256": content_sha256,
                    "parser_input_receipt_sha256": str(
                        receipt_dict.get("receipt_sha256") or ""
                    ),
                    "source_transport": str(
                        receipt_dict.get("source_transport")
                        or receipt_dict.get("transport_kind")
                        or ""
                    ),
                    "source_bundle": {
                        "official_url": source_url,
                        "media_type": "text/csv",
                        "byte_size": len(raw),
                        "content_sha256": content_sha256,
                    },
                }
                statutes.append(statute)
            title_reports.append(
                {
                    "title_number": title_number,
                    "title_name": title_name,
                    "source_url": source_url,
                    "content_sha256": content_sha256,
                    "source_records": report.source_record_count,
                    "operative_records": len(report.statutes),
                    "terminal_records": len(report.terminal_records),
                    "source_status_records": len(report.source_status_records),
                    "observation_date": observation_date.isoformat(),
                    "closed": True,
                }
            )

        source_records = sum(int(row["source_records"]) for row in title_reports)
        terminal_records = sum(int(row["terminal_records"]) for row in title_reports)
        source_status_count = sum(
            int(row["source_status_records"]) for row in title_reports
        )
        if source_records != len(statutes) + terminal_records + source_status_count:
            raise RuntimeError("Virginia global CSV source algebra failed reconciliation")
        catalog_content_sha256 = hashlib.sha256(catalog_payload).hexdigest()
        exact_frontier = self._virginia_exact_frontier(
            catalog_content_sha256=catalog_content_sha256,
            title_reports=title_reports,
            current_section_reports=current_section_reports,
            observation_date=observation_date.isoformat(),
            terminal_dispositions=terminal_counts,
            source_status_records=source_status_records,
        )
        first_observation = {
            "boundary_first": title_urls[0],
            "boundary_last": title_urls[-1],
            "code_name": code_name,
            "frontier": exact_frontier,
            "current_section_reports": current_section_reports,
            "observation_date": observation_date.isoformat(),
            "observed_at": observed_at,
            "title_reports": title_reports,
            "transport_batch_stats": list(self._virginia_frontier_batch_stats),
        }
        self._last_virginia_full_frontier = first_observation
        self._last_virginia_strict_closure = {
            "schema": "virginia-title-csv-strict-closure-v1",
            "closed": True,
            "catalog_source_url": self.OFFICIAL_LIBRARY_URL,
            "catalog_content_sha256": catalog_content_sha256,
            "catalog_titles": len(catalog_rows),
            "current_section_pages": len(current_section_reports),
            "title_csv_documents": len(title_reports),
            "source_records": source_records,
            "operative_sections": len(statutes),
            "terminal_records": terminal_records,
            "terminal_dispositions": dict(sorted(terminal_counts.items())),
            "source_status_records": source_status_records,
            "source_status_record_count": source_status_count,
            "unclassified_records": 0,
            "frontier_sha256": str(exact_frontier["title_csv_frontier_sha256"]),
            "current_section_reports": current_section_reports,
            "observation_date": observation_date.isoformat(),
            "title_reports": title_reports,
            "batch_stats": list(self._virginia_frontier_batch_stats),
            "frontier": exact_frontier,
            "observed_at": observed_at,
        }
        return statutes

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        if self._full_corpus_enabled() and max_statutes is None:
            return await self._scrape_official_title_csv_frontier(code_name)
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
                    discovery_method="official_title_chapter_section_index",
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
        discovery_method: str = "official_title_chapter_section_index",
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
                html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
                from .virginia_section import body_to_paragraphs

                soup = BeautifulSoup(html, "html.parser")
                node = (
                    soup.find(id="va_code")
                    or soup.find("article", id="vacode")
                    or soup.select_one("main")
                    or soup
                )
                for tag in node(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                paras = body_to_paragraphs(str(node))
                text = self._normalize_legal_text(" ".join(paras) if paras else node.get_text(" ", strip=True))
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
                        "discovery_method": discovery_method,
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

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Path | None:
        """Reparse retained title CSVs and seal zero-network publication parity."""

        first = getattr(self, "_last_virginia_full_frontier", None)
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Virginia frontier closure requires an attached ledger")
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Virginia source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        from .strict_frontier_closure import retain_exact_state_frontier_closure
        from .virginia_csv import (
            parse_virginia_title_csv_closure,
            virginia_title_csv_links,
        )

        first_frontier = first.get("frontier")
        first_reports_raw = first.get("title_reports")
        first_current_raw = first.get("current_section_reports")
        if (
            not isinstance(first_frontier, Mapping)
            or not isinstance(first_reports_raw, Sequence)
            or isinstance(first_reports_raw, (str, bytes, bytearray))
            or not first_reports_raw
            or any(not isinstance(row, Mapping) for row in first_reports_raw)
            or not isinstance(first_current_raw, Sequence)
            or isinstance(first_current_raw, (str, bytes, bytearray))
            or any(not isinstance(row, Mapping) for row in first_current_raw)
        ):
            raise RuntimeError("Virginia first exact frontier is incomplete")
        first_reports = [dict(row) for row in first_reports_raw]
        first_current_reports = [dict(row) for row in first_current_raw]
        observation_date_text = str(first.get("observation_date") or "")
        try:
            observation_date = date.fromisoformat(observation_date_text)
        except ValueError as exc:
            raise RuntimeError(
                "Virginia first exact frontier lacks a source observation date"
            ) from exc

        replay_batch = self._replay_virginia_retained_batch(
            [
                (
                    self.OFFICIAL_LIBRARY_URL,
                    "text/html",
                    self._is_valid_virginia_law_library,
                    "retained-law-library-replay",
                ),
                *[
                    (
                        str(report.get("source_url") or ""),
                        "text/csv",
                        self._is_valid_virginia_title_csv,
                        "retained-title-"
                        f"{str(report.get('title_number') or '')}-replay",
                    )
                    for report in first_reports
                ],
                *[
                    (
                        str(report.get("source_url") or ""),
                        "text/html",
                        self._is_valid_virginia_current_section_page,
                        "retained-current-section-"
                        f"{str(report.get('section_number') or '')}-replay",
                    )
                    for report in first_current_reports
                ],
            ]
        )
        replay_stats = dict(replay_batch.stats or {})
        expected_replay_pages = (
            1 + len(first_reports) + len(first_current_reports)
        )
        if (
            int(replay_stats.get("requested_pages") or 0)
            != expected_replay_pages
            or int(replay_stats.get("retained_replay_pages") or 0)
            != expected_replay_pages
            or int(replay_stats.get("retained_replay_unique_pages") or 0)
            != expected_replay_pages
            or int(replay_stats.get("successful_pages") or 0)
            != expected_replay_pages
            or int(replay_stats.get("network_requested_pages", -1)) != 0
        ):
            raise RuntimeError(
                "Virginia retained plural replay did not prove zero-network "
                f"exact-input parity: expected={expected_replay_pages} "
                f"stats={replay_stats}"
            )
        catalog_payload = bytes(replay_batch.payloads[0])
        catalog_digest = hashlib.sha256(catalog_payload).hexdigest()
        if catalog_digest != str(first_frontier.get("catalog_content_sha256") or ""):
            raise RuntimeError("Virginia retained Law Library digest changed on replay")
        replay_catalog = virginia_title_csv_links(
            catalog_payload,
            base_url=self.OFFICIAL_LIBRARY_URL,
        )
        replay_membership = [
            (str(number), str(name), self._canonical_fetch_url(str(url)))
            for number, name, url in replay_catalog
        ]
        expected_membership = [
            (
                str(row.get("title_number") or ""),
                str(row.get("title_name") or ""),
                self._canonical_fetch_url(str(row.get("source_url") or "")),
            )
            for row in first_reports
        ]
        if replay_membership != expected_membership:
            raise RuntimeError("Virginia retained title CSV catalog membership changed")

        title_payload_end = 1 + len(first_reports)
        replay_title_payloads = replay_batch.payloads[1:title_payload_end]
        replay_current_payloads = replay_batch.payloads[title_payload_end:]
        replay_current_reports: list[dict[str, Any]] = []
        current_pages_by_title: dict[str, dict[str, bytes]] = {}
        for expected, replay_payload in zip(
            first_current_reports,
            replay_current_payloads,
            strict=True,
        ):
            source_url = str(expected.get("source_url") or "")
            title_number = str(expected.get("title_number") or "")
            raw = bytes(replay_payload)
            content_sha256 = hashlib.sha256(raw).hexdigest()
            if content_sha256 != str(expected.get("content_sha256") or ""):
                raise RuntimeError(
                    "Virginia retained current section digest changed: "
                    f"{expected.get('section_number')}"
                )
            current_pages_by_title.setdefault(title_number, {})[source_url] = raw
            replay_current_reports.append(
                {
                    "title_number": title_number,
                    "section_number": str(expected.get("section_number") or ""),
                    "source_url": source_url,
                    "purpose": str(expected.get("purpose") or ""),
                    "content_sha256": content_sha256,
                }
            )
        if replay_current_reports != first_current_reports:
            raise RuntimeError(
                "Virginia retained current-section reports changed on replay"
            )

        code_name = str(first.get("code_name") or "Code of Virginia")
        replay_rows: list[NormalizedStatute] = []
        replay_reports: list[dict[str, Any]] = []
        terminal_counts: dict[str, int] = {}
        replay_source_status_records: list[dict[str, Any]] = []
        seen_identities: set[str] = set()
        for expected, replay_payload in zip(
            first_reports,
            replay_title_payloads,
            strict=True,
        ):
            title_number = str(expected.get("title_number") or "")
            title_name = str(expected.get("title_name") or "")
            source_url = str(expected.get("source_url") or "")
            raw = bytes(replay_payload)
            content_sha256 = hashlib.sha256(raw).hexdigest()
            if content_sha256 != str(expected.get("content_sha256") or ""):
                raise RuntimeError(
                    f"Virginia retained title CSV digest changed: {title_number}"
                )
            parsed = parse_virginia_title_csv_closure(
                raw,
                expected_title_number=title_number,
                expected_title_name=title_name,
                code_name=code_name,
                source_bundle_url=source_url,
                observation_date=observation_date,
                current_section_pages=current_pages_by_title.get(
                    title_number, {}
                ),
            )
            if parsed.title_number != title_number or not parsed.closed:
                raise RuntimeError(
                    f"Virginia retained title failed exact replay: {title_number}"
                )
            for terminal in parsed.terminal_records:
                disposition = str(terminal.get("disposition") or "excluded")
                terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1
            replay_source_status_records.extend(
                dict(status) for status in parsed.source_status_records
            )
            for statute in parsed.statutes:
                identity = str(statute.statute_id or "").strip().casefold()
                if not identity or identity in seen_identities:
                    raise RuntimeError(
                        "Virginia retained replay repeated normalized identity: "
                        f"{statute.statute_id}"
                    )
                seen_identities.add(identity)
                statute.legal_area = self._identify_legal_area(
                    str(statute.section_name or statute.full_text or "")
                )
                statute.structured_data = {
                    **dict(statute.structured_data or {}),
                    "content_sha256": content_sha256,
                    "source_bundle": {
                        "official_url": source_url,
                        "media_type": "text/csv",
                        "byte_size": len(raw),
                        "content_sha256": content_sha256,
                    },
                }
                replay_rows.append(statute)
            replay_reports.append(
                {
                    "title_number": title_number,
                    "title_name": title_name,
                    "source_url": source_url,
                    "content_sha256": content_sha256,
                    "source_records": parsed.source_record_count,
                    "operative_records": len(parsed.statutes),
                    "terminal_records": len(parsed.terminal_records),
                    "source_status_records": len(parsed.source_status_records),
                    "observation_date": observation_date.isoformat(),
                    "closed": True,
                }
            )
        if replay_reports != first_reports:
            raise RuntimeError("Virginia retained title reports changed on replay")
        replayed_frontier = self._virginia_exact_frontier(
            catalog_content_sha256=catalog_digest,
            title_reports=replay_reports,
            current_section_reports=replay_current_reports,
            observation_date=observation_date.isoformat(),
            terminal_dispositions=terminal_counts,
            source_status_records=replay_source_status_records,
        )
        first_stats_raw = first.get("transport_batch_stats")
        if (
            not isinstance(first_stats_raw, Sequence)
            or isinstance(first_stats_raw, (str, bytes, bytearray))
            or any(not isinstance(row, Mapping) for row in first_stats_raw)
        ):
            raise RuntimeError("Virginia first frontier lacks plural batch receipts")
        first_stats = [dict(row) for row in first_stats_raw]
        catalog_stats = [
            row
            for row in first_stats
            if row.get("frontier_name") == "law-library-catalog"
        ]
        title_stats = [
            row
            for row in first_stats
            if str(row.get("frontier_name") or "").startswith("title-csv-")
        ]
        current_stats = [
            row
            for row in first_stats
            if str(row.get("frontier_name") or "").startswith(
                "current-section-pages-"
            )
        ]
        expected_first_pages = (
            1 + len(first_reports) + len(first_current_reports)
        )
        first_requested_pages = sum(
            int(row.get("requested_pages") or 0) for row in first_stats
        )
        title_requested_pages = sum(
            int(row.get("requested_pages") or 0) for row in title_stats
        )
        current_requested_pages = sum(
            int(row.get("requested_pages") or 0) for row in current_stats
        )
        if (
            len(first_reports) != int(self.STRICT_EXPECTED_TITLE_CSVS)
            or len(first_current_reports)
            != int(self.STRICT_EXPECTED_CURRENT_SECTION_PAGES)
            or len(catalog_stats) != 1
            or int(catalog_stats[0].get("requested_pages") or 0) != 1
            or len(current_stats) != (1 if first_current_reports else 0)
            or len(catalog_stats) + len(title_stats) + len(current_stats)
            != len(first_stats)
            or first_requested_pages != expected_first_pages
            or title_requested_pages != len(first_reports)
            or current_requested_pages != len(first_current_reports)
            or (len(first_reports) > 1 and not any(
                int(row.get("requested_pages") or 0) > 1 for row in title_stats
            ))
            or (len(first_current_reports) > 1 and not any(
                int(row.get("requested_pages") or 0) > 1 for row in current_stats
            ))
        ):
            raise RuntimeError(
                "Virginia first frontier did not prove one exact source-derived "
                "catalog plus grouped title CSV/current-section acquisition: "
                f"expected={expected_first_pages} requested={first_requested_pages} "
                f"batches={first_stats}"
            )
        observed_at = str(first.get("observed_at") or "")
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="VA",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_LIBRARY_URL,
            observed_at=observed_at,
            legal_as_of=observed_at,
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(first_reports) + len(first_current_reports),
            pagination_total=1,
            transport={
                "direct_first": True,
                "first_pass_batch_stats": first_stats,
                "first_pass_requested_pages": first_requested_pages,
                "fixture": False,
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_html_csv_and_sections",
                "parser_input_count": expected_first_pages,
                "per_page_archive_loop": False,
                "plural_frontier_batches": len(first_stats),
                "replay_batch_stats": replay_stats,
                "retained_replay_batches": 1,
                "retained_replay_network_requests": int(
                    replay_stats["network_requested_pages"]
                ),
                "retained_replay_pages": int(
                    replay_stats["retained_replay_pages"]
                ),
                "residual_retry_enabled": self._env_int(
                    "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=1,
                )
                > 0,
                "source_bundle_format": (
                    "official_title_csv_plus_current_section_html"
                ),
                "synthetic": False,
                "wayback_prefix_inventory": True,
            },
        )

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
