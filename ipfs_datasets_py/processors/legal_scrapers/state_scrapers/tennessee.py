"""Scraper for Tennessee state laws."""

import hashlib
import json
import os
import re
import secrets
import ssl
import time
import urllib.request
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set
from urllib.parse import urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StateLawPageMultiFetchResult,
    StatuteMetadata,
)
from .registry import StateScraperRegistry


class _TennesseePhaseLedgerView:
    """Project shared GET retain/replay calls onto one signed TN phase."""

    def __init__(self, ledger: Any, *, phase_id: str, phase_started_at: str) -> None:
        self._ledger = ledger
        self.phase_id = phase_id
        self.phase_started_at = phase_started_at
        self.jurisdiction_root = ledger.jurisdiction_root
        self.parser_name = ledger.parser_name
        self.retained_replay_only = bool(
            getattr(ledger, "retained_replay_only", False)
        )

    def _request(self, value: Mapping[str, Any]) -> Dict[str, Any]:
        request = dict(value)
        conflicting = str(request.get("acquisition_phase_id") or "").strip()
        if conflicting and conflicting != self.phase_id:
            raise RuntimeError("Tennessee GET request crossed acquisition phases")
        request.update(
            {
                "acquisition_phase_id": self.phase_id,
                "acquisition_phase_schema": TennesseeScraper.TN_PHASE_SCHEMA,
                "acquisition_phase_started_at": self.phase_started_at,
            }
        )
        return request

    def replay_retained_parser_input(
        self,
        *,
        official_url: str,
        sanitized_request: Mapping[str, Any],
    ) -> Any:
        return self._ledger.replay_retained_parser_input(
            official_url=official_url,
            sanitized_request=self._request(sanitized_request),
        )

    def retain_parser_input(self, **kwargs: Any) -> Any:
        request = kwargs.get("sanitized_request")
        if not isinstance(request, Mapping):
            raise RuntimeError("Tennessee phased GET omitted its request identity")
        kwargs["sanitized_request"] = self._request(request)
        pagination = dict(kwargs.get("pagination") or {})
        pagination["tennessee_acquisition_phase"] = {
            "phase_id": self.phase_id,
            "schema_version": TennesseeScraper.TN_PHASE_SCHEMA,
            "started_at": self.phase_started_at,
        }
        kwargs["pagination"] = pagination
        return self._ledger.retain_parser_input(**kwargs)

    def refresh_existing_entries(self) -> None:
        refresh = getattr(self._ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

# Suppress SSL warnings for tn.gov
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


class TennesseeScraper(BaseStateScraper):
    """Scraper for Tennessee state laws from official TGA / capitol hosts."""

    _TN_JUSTIA_VERSION_RE = re.compile(r"/codes/tennessee/\d{4}/?$", re.IGNORECASE)
    _TN_JUSTIA_TITLE_RE = re.compile(r"/codes/tennessee/(?:\d{4}/)?title-\d+/?$", re.IGNORECASE)
    _TN_JUSTIA_INTERMEDIATE_RE = re.compile(
        r"/codes/tennessee/(?:\d{4}/)?title-\d+/(?!.*section-)[^?#]+/?$",
        re.IGNORECASE,
    )
    _TN_JUSTIA_SECTION_RE = re.compile(
        r"/codes/tennessee/(?:\d{4}/)?title-\d+/.*/section-[^/]+/?$",
        re.IGNORECASE,
    )
    _TN_SECTION_NUMBER_RE = re.compile(r"/section-([^/]+)/?$", re.IGNORECASE)
    _TN_CLOUDFLARE_CHALLENGE_RE = re.compile(
        r"(cf-mitigated|challenge-platform|enable javascript and cookies|just a moment)",
        re.IGNORECASE,
    )
    _TN_OFFICIAL_HOST_SUFFIXES = (
        "tn.gov",
        "capitol.tn.gov",
    )
    _TN_OFFICIAL_SECTION_RE = re.compile(
        r"(?:/tca/|/statutes?/|/code/)[^?#]*section[/_-]?([0-9]+(?:-[0-9A-Za-z.]+)+)",
        re.IGNORECASE,
    )
    _TN_OFFICIAL_TITLE_RE = re.compile(
        r"(?:title[/_-]|/tca/)(\d{1,3})(?:[/?#]|$)",
        re.IGNORECASE,
    )
    _TN_SECTION_LABEL_RE = re.compile(
        r"(?:§|Section)\s*([0-9]+(?:-[0-9A-Za-z.]+)+)",
        re.IGNORECASE,
    )
    OFFICIAL_DOMAIN = "www.tn.gov"
    OFFICIAL_ENTRY_PATH = "/tga/statutes.html"
    # Legacy compatibility locator only.  It returned HTTP 404 on 2026-08-26
    # and cannot authorize a current Tennessee Code frontier.
    OFFICIAL_ENTRY_URL = "https://www.tn.gov/tga/statutes.html"
    CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL = (
        "https://wapp.capitol.tn.gov/apps/WebPublications/"
    )
    AUTHORIZED_CODE_ENTRY_URL = "https://www.lexisnexis.com/hottopics/tncode"
    AUTHORIZED_CODE_CONTAINER_URL = (
        "https://advance.lexis.com/container?config="
        "014CJAA5ZGVhZjA3NS02MmMzLTRlZWQtOGJjNC00YzQ1MmZlNzc2YWYK"
        "AFBvZENhdGFsb2e9zYpNUjTRaIWVfyrur9ud"
    )
    AUTHORIZED_TOC_ROOT_ID = "6gf5kkk"
    AUTHORIZED_TOC_ENDPOINT = "/r/tocprovider/6gf5kkk/toc/6gf5kkk"
    LINKLESS_QUARANTINE_REASON = "missing_official_source_link"
    last_official_quarantines: List[Dict[str, str]] = []
    _TN_TITLE_HREF_RE = re.compile(
        r"/title-?(?P<title>\d{1,2})(?:/|$)",
        re.IGNORECASE,
    )
    _TN_TITLE_LABEL_RE = re.compile(
        r"\b(?:title|tca|tenn\.?\s*code(?:\s*ann\.?)?)\s+(?P<title>\d{1,2})\b",
        re.IGNORECASE,
    )
    _TN_SECTION_CITE_RE = re.compile(
        r"\b(?P<title>\d{1,2})-\d{1,2}-\d{1,4}(?:\.[0-9A-Za-z]+)?\b"
    )
    OFFICIAL_TITLES = (
        ("1", "Code and Statutes"),
        ("2", "Elections"),
        ("3", "Legislature"),
        ("4", "State Government"),
        ("5", "Counties"),
        ("6", "Cities and Towns"),
        ("7", "Consolidated Governments and Local Governmental Functions and Entities"),
        ("8", "Public Officers and Employees"),
        ("9", "Public Finances"),
        ("10", "Public Libraries, Archives and Records"),
        ("11", "Natural Areas and Recreation"),
        ("12", "Public Property, Printing and Contracts"),
        ("13", "Public Planning and Housing"),
        ("14", "COVID-19"),
        ("15", "Holidays and Days of Special Observance"),
        ("16", "Courts"),
        ("17", "Judges and Chancellors"),
        ("18", "Clerks of Courts"),
        ("19", "[Reserved]"),
        ("20", "Civil Procedure"),
        ("21", "Proceedings in Chancery"),
        ("22", "Juries and Jurors"),
        ("23", "Attorneys-at-law"),
        ("24", "Evidence and Witnesses"),
        ("25", "Judgments"),
        ("26", "Execution"),
        ("27", "Appeal and Review"),
        ("28", "Limitation of Actions"),
        ("29", "Remedies and Special Proceedings"),
        ("30", "Administration of Estates"),
        ("31", "Descent and Distribution"),
        ("32", "Wills"),
        (
            "33",
            "Mental Health and Substance Abuse and Intellectual and Developmental Disabilities",
        ),
        ("34", "Guardianship"),
        ("35", "Fiduciaries and Trust Estates"),
        ("36", "Domestic Relations"),
        ("37", "Juveniles"),
        ("38", "Prevention and Detection of Crime"),
        ("39", "Criminal Offenses"),
        ("40", "Criminal Procedure"),
        ("41", "Correctional Institutions and Inmates"),
        ("42", "Aeronautics"),
        ("43", "Agriculture and Horticulture"),
        ("44", "Animals and Animal Husbandry"),
        ("45", "Banks and Financial Institutions"),
        ("46", "Cemeteries"),
        ("47", "Commercial Instruments and Transactions"),
        ("48", "Securities, Corporations And Associations"),
        ("49", "Education"),
        ("50", "Employer and Employee"),
        ("51", "[Reserved]"),
        ("52", "Department of Disability and Aging"),
        ("53", "Food, Drugs and Cosmetics"),
        ("54", "Highways, Bridges and Ferries"),
        ("55", "Motor and Other Vehicles"),
        ("56", "Insurance"),
        ("57", "Intoxicating Liquors"),
        ("58", "Military Affairs, Emergencies and Civil Defense"),
        ("59", "Mines and Mining"),
        ("60", "Oil and Gas"),
        ("61", "Partnerships"),
        ("62", "Professions, Businesses and Trades"),
        ("63", "Professions of the Healing Arts"),
        ("64", "Regional Authorities"),
        ("65", "Public Utilities and Carriers"),
        ("66", "Property"),
        ("67", "Taxes and Licenses"),
        ("68", "Health, Safety and Environmental Protection"),
        ("69", "Waters, Waterways, Drains and Levees"),
        ("70", "Wildlife Resources"),
        ("71", "Welfare"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)
    OBSERVED_STRICT_INPUT_COUNT = 36_118
    OBSERVED_BODY_LEAF_COUNT = 36_046
    OBSERVED_SUBTREE_RESPONSE_COUNT = 69
    STRICT_GET_ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"
    TN_PHASE_SCHEMA = "tennessee-lexis-acquisition-phase-v1"
    TN_PHASE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
    TN_PHASE_MAX_SPAN_SECONDS = 2 * 24 * 60 * 60
    TN_PHASE_CLOCK_SKEW_SECONDS = 5 * 60
    # Source drift requires an explicit reviewed code update.  Tests may
    # replace this class attribute for a deliberately smaller exact fixture.
    ENFORCE_OBSERVED_TN_FRONTIER = True
    STRICT_FULL_BLOCKER = (
        "Tennessee strict full-corpus acquisition requires an attached live ledger "
        "or a retained-replay-only ledger containing the current General "
        "Assembly-delegated Lexis chain: "
        "publisher entry, exact root, all 69 deepest TOC responses, and every "
        "source-derived document body must be ledger-replayed; synthetic tn.gov, "
        "Justia, and Jina rows cannot prove this source frontier"
    )
    DEFAULT_LINKLESS_SEED_ROWS = (
        {
            "statute_id": "Tenn. Code Ann. § 39-17-402",
            "section_number": "39-17-402",
            "source_url": "",
            "text": "Definitions",
        },
        {
            "statute_id": "TCA 40-35-104",
            "source_url": "https://law.justia.com/codes/tennessee/title-40/chapter-35/section-40-35-104/",
            "text": "Sentencing alternatives",
        },
        {
            "name": "Unlabeled Tennessee bucket remnant",
            "source_url": "",
            "text": "legacy snapshot row with no citation",
        },
    )

    async def scrape_all(
        self,
        legal_areas: Optional[List[str]] = None,
        max_statutes: Optional[int] = None,
        rate_limit_delay: float = 2.0,
        hydrate_statute_text: bool = True,
    ) -> List[NormalizedStatute]:
        full_mode = self._full_corpus_enabled()
        if full_mode and (max_statutes is not None or legal_areas):
            raise RuntimeError(
                "Tennessee strict full-corpus route refuses caps or legal-area filters"
            )
        self.last_tennessee_full_corpus_report: Dict[str, Any] = {}
        rows = await super().scrape_all(
            legal_areas=legal_areas,
            max_statutes=max_statutes,
            rate_limit_delay=rate_limit_delay,
            hydrate_statute_text=hydrate_statute_text,
        )
        if full_mode and not self.last_tennessee_full_corpus_report.get("closed"):
            raise RuntimeError(
                "Tennessee strict full-corpus route did not emit a closed report"
            )
        return rows

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind the exact parser, replay, closure, and plural archive code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            tennessee_lexis,
            tennessee_lexis_live,
            tennessee_section,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            tennessee_lexis,
            tennessee_lexis_live,
            tennessee_section,
            wayback_machine_engine,
        )

    def _tennessee_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                self._env_int("STATE_SCRAPER_TN_FRONTIER_CONCURRENCY", default=16),
            ),
        )

    def _tennessee_residual_retry_attempts(self) -> int:
        return max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_TN_RESIDUAL_RETRY_ATTEMPTS",
                    default=self._env_int(
                        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                        default=1,
                    ),
                ),
            ),
        )

    @staticmethod
    def _parse_tennessee_timestamp(value: object, *, field: str) -> datetime:
        raw = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError(f"Tennessee {field} is not ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError(f"Tennessee {field} requires a timezone")
        return parsed.astimezone(UTC)

    @classmethod
    def _bind_tennessee_phase_request(
        cls,
        request: Mapping[str, Any],
        *,
        phase_id: str,
        phase_started_at: str,
    ) -> Dict[str, Any]:
        normalized_id = str(phase_id or "").strip().lower()
        normalized_start = cls._parse_tennessee_timestamp(
            phase_started_at,
            field="acquisition phase start",
        ).isoformat()
        if not re.fullmatch(r"[a-f0-9]{64}", normalized_id):
            raise RuntimeError("Tennessee acquisition phase ID is invalid")
        bound = dict(request)
        existing = str(bound.get("acquisition_phase_id") or "").strip().lower()
        if existing and existing != normalized_id:
            raise RuntimeError("Tennessee request crossed acquisition phases")
        bound.update(
            {
                "acquisition_phase_id": normalized_id,
                "acquisition_phase_schema": cls.TN_PHASE_SCHEMA,
                "acquisition_phase_started_at": normalized_start,
            }
        )
        return bound

    @classmethod
    def _phase_from_request(
        cls,
        request: Mapping[str, Any],
    ) -> tuple[str, str] | None:
        phase_id = str(request.get("acquisition_phase_id") or "").strip().lower()
        schema = str(request.get("acquisition_phase_schema") or "").strip()
        started_at = str(
            request.get("acquisition_phase_started_at") or ""
        ).strip()
        if not any((phase_id, schema, started_at)):
            return None
        if schema != cls.TN_PHASE_SCHEMA or not re.fullmatch(
            r"[a-f0-9]{64}", phase_id
        ):
            raise RuntimeError("Tennessee retained phase metadata is malformed")
        return (
            phase_id,
            cls._parse_tennessee_timestamp(
                started_at,
                field="retained acquisition phase start",
            ).isoformat(),
        )

    def _select_tennessee_acquisition_phase(
        self,
        *,
        allow_new: bool,
    ) -> tuple[str, str]:
        existing_id = str(
            getattr(self, "_tennessee_acquisition_phase_id", "") or ""
        ).strip().lower()
        existing_start = str(
            getattr(self, "_tennessee_acquisition_phase_started_at", "") or ""
        ).strip()
        if existing_id or existing_start:
            bound = self._bind_tennessee_phase_request(
                {},
                phase_id=existing_id,
                phase_started_at=existing_start,
            )
            return (
                str(bound["acquisition_phase_id"]),
                str(bound["acquisition_phase_started_at"]),
            )

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Tennessee acquisition phase requires an attached ledger")
        candidates: dict[str, str] = {}
        for retained in tuple(getattr(ledger, "entries", ()) or ()):
            receipt = getattr(retained, "receipt", None)
            request = getattr(receipt, "sanitized_request", None)
            if not isinstance(request, Mapping):
                continue
            phase = self._phase_from_request(request)
            if phase is None:
                continue
            phase_id, started_at = phase
            prior = candidates.get(phase_id)
            if prior is not None and prior != started_at:
                raise RuntimeError(
                    "Tennessee retained phase ID has conflicting start times"
                )
            candidates[phase_id] = started_at

        now = datetime.now(UTC)
        eligible: list[tuple[datetime, str, str]] = []
        for phase_id, started_at in candidates.items():
            started = self._parse_tennessee_timestamp(
                started_at,
                field="retained acquisition phase start",
            )
            age = (now - started).total_seconds()
            if age < -self.TN_PHASE_CLOCK_SKEW_SECONDS:
                raise RuntimeError("Tennessee retained acquisition phase begins in the future")
            if age <= self.TN_PHASE_MAX_AGE_SECONDS:
                eligible.append((started, phase_id, started_at))
        if eligible:
            _started, phase_id, started_at = max(eligible)
        elif allow_new:
            started_at = now.isoformat()
            phase_id = hashlib.sha256(
                json.dumps(
                    {
                        "jurisdiction": "TN",
                        "nonce": secrets.token_hex(32),
                        "schema_version": self.TN_PHASE_SCHEMA,
                        "started_at": started_at,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        elif candidates:
            raise RuntimeError("Tennessee retained acquisition phase is stale")
        else:
            raise RuntimeError(
                "Tennessee retained frontier lacks an acquisition phase binding"
            )
        self._tennessee_acquisition_phase_id = phase_id
        self._tennessee_acquisition_phase_started_at = started_at
        self._tennessee_ignored_phase_count = max(0, len(candidates) - 1)
        return phase_id, started_at

    async def _fetch_tennessee_lexis_get_wave(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Any,
        require_direct: bool = False,
    ) -> StateLawPageMultiFetchResult:
        """Use one shared plural inventory for an ordered same-domain GET wave.

        Lexis TOC ``PATCH`` requests are deliberately absent because a GET
        archive cannot bind their request bodies; GET archive cannot bind a
        PATCH identity.
        """

        from .tennessee_lexis import grouped_get_acquisition_contract

        requested = list(urls)
        if not requested:
            return StateLawPageMultiFetchResult([], [], [], [], [], {})
        contract = grouped_get_acquisition_contract(requested)
        domain = str(contract["source_domain"])
        if domain == "advance.lexis.com":
            url_terms = ("/shared/document/statutes-legislation/", "/container")
        elif domain == "wapp.capitol.tn.gov":
            url_terms = ("/apps/WebPublications/",)
        elif domain == "www.lexisnexis.com":
            url_terms = ("/hottopics/tncode",)
        else:
            raise RuntimeError(
                f"Tennessee {frontier_name} crossed an unbound source domain: {domain}"
            )
        headers = {
            **dict(self._tennessee_get_request(requested[0])["headers"]),
            "User-Agent": "ipfs-datasets-tennessee-code/3.0",
        }
        original_ledger = getattr(self, "_state_law_acquisition_ledger", None)
        phase_id = str(
            getattr(self, "_tennessee_acquisition_phase_id", "") or ""
        ).strip()
        phase_started_at = str(
            getattr(self, "_tennessee_acquisition_phase_started_at", "") or ""
        ).strip()
        phase_view: _TennesseePhaseLedgerView | None = None
        if original_ledger is not None and (phase_id or phase_started_at):
            phase_view = _TennesseePhaseLedgerView(
                original_ledger,
                phase_id=phase_id,
                phase_started_at=phase_started_at,
            )
            self._state_law_acquisition_ledger = phase_view
        try:
            batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
                requested,
                residual_retry_attempts=self._tennessee_residual_retry_attempts(),
                timeout_seconds=45,
                headers=headers,
                content_validator=content_validator,
                media_type="text/html",
                max_concurrency=self._tennessee_frontier_concurrency(),
                prefer_direct=True,
                common_crawl_domain_terms=(domain,),
                common_crawl_url_terms=url_terms,
                common_crawl_mime_terms=("html",),
                wayback_prefix_inventory=True,
                archive_recovery_enabled=not require_direct,
            )
        finally:
            if phase_view is not None:
                self._state_law_acquisition_ledger = original_ledger
        vectors = (
            batch.urls,
            batch.payloads,
            batch.errors,
            batch.transport_receipts,
            batch.parser_input_envelopes,
        )
        if any(len(vector) != len(requested) for vector in vectors):
            raise RuntimeError(
                f"Tennessee {frontier_name} returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"Tennessee {frontier_name} changed source URL order or identity"
            )
        failures = [
            {"error": error or "invalid parser input", "url": url}
            for url, payload, error in zip(
                batch.urls,
                batch.payloads,
                batch.errors,
                strict=True,
            )
            if error is not None or not content_validator(bytes(payload or b""))
        ]
        if failures:
            raise RuntimeError(
                f"Tennessee {frontier_name} is incomplete after residual-only "
                f"plural retries: {failures}"
            )
        if int((batch.stats or {}).get("common_crawl_inventory_queries", 0) or 0) > 1:
            raise RuntimeError(
                f"Tennessee {frontier_name} repeated a same-domain Common Crawl inventory"
            )
        if require_direct:
            non_direct = [
                {
                    "source_transport": str(
                        (receipt.get("source_transport") or "")
                        if isinstance(receipt, Mapping)
                        else ""
                    ),
                    "url": url,
                }
                for url, receipt in zip(
                    batch.urls,
                    batch.transport_receipts,
                    strict=True,
                )
                if not isinstance(receipt, Mapping)
                or str(receipt.get("source_transport") or "").casefold()
                != "direct"
            ]
            if non_direct:
                raise RuntimeError(
                    f"Tennessee {frontier_name} rejected non-direct current-source "
                    f"transport: {non_direct[:10]} (total={len(non_direct)})"
                )
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    def _tennessee_get_request(
        self,
        url: str,
        *,
        phase_id: str | None = None,
        phase_started_at: str | None = None,
    ) -> Dict[str, Any]:
        request = {
            "headers": {"Accept": TennesseeScraper.STRICT_GET_ACCEPT},
            "method": "GET",
            "url": str(url),
        }
        selected_id = str(
            phase_id
            or getattr(self, "_tennessee_acquisition_phase_id", "")
            or ""
        ).strip()
        selected_start = str(
            phase_started_at
            or getattr(self, "_tennessee_acquisition_phase_started_at", "")
            or ""
        ).strip()
        if selected_id or selected_start:
            return self._bind_tennessee_phase_request(
                request,
                phase_id=selected_id,
                phase_started_at=selected_start,
            )
        return request

    def _validate_tennessee_lexis_configuration(self) -> None:
        """Fail closed if class and parser source identities diverge."""

        from .tennessee_lexis import (
            GENERAL_ASSEMBLY_PUBLICATIONS_URL,
            PUBLIC_CONTAINER_URL,
            PUBLIC_ENTRY_URL,
            TOC_ENDPOINT_PATH,
            TOC_ROOT_ID,
        )

        observed = (
            self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL,
            self.AUTHORIZED_CODE_ENTRY_URL,
            self.AUTHORIZED_CODE_CONTAINER_URL,
            self.AUTHORIZED_TOC_ROOT_ID,
            self.AUTHORIZED_TOC_ENDPOINT,
        )
        expected = (
            GENERAL_ASSEMBLY_PUBLICATIONS_URL,
            PUBLIC_ENTRY_URL,
            PUBLIC_CONTAINER_URL,
            TOC_ROOT_ID,
            TOC_ENDPOINT_PATH,
        )
        if observed != expected:
            raise RuntimeError(
                "Tennessee delegated Lexis source configuration changed without review"
            )

    def _retain_tennessee_browser_input(
        self,
        *,
        official_url: str,
        body: bytes,
        sanitized_request: Mapping[str, Any],
        response_status: int,
        media_type: str,
        observed_at: str,
        response_proof: Mapping[str, Any],
    ) -> None:
        """Retain a rendered root or exact TOC PATCH before live parsing."""

        from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
            canonicalize_state_law_transport_receipt,
        )

        from .tennessee_lexis import (
            PUBLIC_CONTAINER_URL,
            PUBLIC_ENTRY_URL,
            TOC_ENDPOINT_URL,
            container_url_matches,
        )
        from .tennessee_lexis_live import (
            PATCH_ACCEPT,
            canonical_rendered_root_request,
        )

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Tennessee browser evidence requires an attached ledger")
        if self._retained_replay_only_enabled():
            self._raise_if_retained_replay_only_network(
                operation="Tennessee browser acquisition",
                url=official_url,
            )
        request = dict(sanitized_request)
        phase = self._phase_from_request(request)
        active_phase = self._select_tennessee_acquisition_phase(allow_new=False)
        if phase != active_phase:
            raise RuntimeError("Tennessee browser callback crossed acquisition phases")
        method = str(request.get("method") or "").upper()
        if method == "GET":
            valid_request = bool(
                official_url == PUBLIC_CONTAINER_URL
                and request
                == canonical_rendered_root_request(
                    acquisition_phase_id=active_phase[0],
                    acquisition_phase_started_at=active_phase[1],
                )
            )
        else:
            headers = request.get("headers")
            valid_request = bool(
                official_url == TOC_ENDPOINT_URL
                and method == "PATCH"
                and isinstance(headers, Mapping)
                and dict(headers)
                == {
                    "Accept": PATCH_ACCEPT,
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                }
                and re.fullmatch(
                    r"[a-f0-9]{64}",
                    str(request.get("request_body_sha256") or ""),
                )
                and int(request.get("request_body_length") or 0) > 0
                and request.get("session_request_header")
                == "X-LN-CurrentRequestId"
                and re.fullmatch(
                    r"[a-f0-9]{64}",
                    str(request.get("session_request_id_sha256") or ""),
                )
            )
        payload = bytes(body or b"")
        proof = dict(response_proof or {})
        proof_observed_at = self._parse_tennessee_timestamp(
            proof.get("response_observed_at"),
            field="browser response boundary",
        ).isoformat()
        callback_observed_at = self._parse_tennessee_timestamp(
            observed_at,
            field="browser callback boundary",
        ).isoformat()
        final_url = str(proof.get("final_url") or "").strip()
        redirect_chain = proof.get("redirect_chain")
        session_digest = str(
            proof.get("session_request_id_sha256") or ""
        ).strip().lower()
        proof_valid = bool(
            proof_observed_at == callback_observed_at
            and isinstance(redirect_chain, Sequence)
            and not isinstance(redirect_chain, (str, bytes, bytearray))
            and re.fullmatch(r"[a-f0-9]{64}", session_digest)
        )
        if method == "GET":
            proof_valid = bool(
                proof_valid
                and container_url_matches(final_url)
                and re.fullmatch(
                    r"[a-f0-9]{64}",
                    str(proof.get("final_url_sha256") or "").strip().lower(),
                )
                and all(
                    isinstance(item, Mapping)
                    and re.fullmatch(
                        r"[a-f0-9]{64}",
                        str(item.get("url_sha256") or "").strip().lower(),
                    )
                    and (
                        str(item.get("url") or "").rstrip("/")
                        == PUBLIC_ENTRY_URL.rstrip("/")
                        or container_url_matches(item.get("url"))
                    )
                    for item in redirect_chain
                )
            )
        else:
            proof_valid = bool(
                proof_valid
                and final_url == TOC_ENDPOINT_URL
                and proof.get("redirected") is False
                and list(redirect_chain) == []
                and session_digest
                == str(request.get("session_request_id_sha256") or "")
            )
        sensitive_projection = json.dumps(
            proof,
            sort_keys=True,
            separators=(",", ":"),
        ).casefold()
        if any(key in sensitive_projection for key in ('"cookie"', '"authorization"')):
            proof_valid = False
        if (
            not valid_request
            or not proof_valid
            or not payload
            or int(response_status) != 200
            or not str(observed_at or "").strip()
        ):
            raise RuntimeError(
                "Tennessee browser callback exposed an unbound request or response"
            )
        if method == "GET" and "html" not in str(media_type or "").casefold():
            raise RuntimeError("Tennessee rendered root omitted its HTML media type")
        if method == "PATCH" and "json" not in str(media_type or "").casefold():
            raise RuntimeError("Tennessee TOC PATCH omitted its JSON media type")
        digest = hashlib.sha256(payload).hexdigest()
        transport_receipt = canonicalize_state_law_transport_receipt(
            {
                "content_sha256": digest,
                "official_url": official_url,
                "source_transport": "browser_rendered",
            },
            official_url=official_url,
            content_sha256=digest,
        )
        retained = ledger.retain_parser_input(
            official_url=official_url,
            body=payload,
            transport_receipt=transport_receipt,
            retrieved_at=observed_at,
            response_status=int(response_status),
            media_type=media_type,
            sanitized_request=request,
            pagination={
                "tennessee_acquisition_phase": {
                    "phase_id": active_phase[0],
                    "schema_version": self.TN_PHASE_SCHEMA,
                    "started_at": active_phase[1],
                },
                "tennessee_browser_response": proof,
            },
            network_used=True,
        )
        if bytes(getattr(retained.envelope, "body", b"") or b"") != payload:
            raise RuntimeError("Tennessee ledger changed browser bytes before admission")

    @staticmethod
    def _tennessee_envelope_receipt_sha256(envelope: Any) -> str:
        value = envelope
        if not isinstance(value, Mapping):
            to_dict = getattr(value, "to_dict", None)
            if callable(to_dict):
                value = to_dict()
        if isinstance(value, Mapping) and isinstance(
            value.get("parser_input_envelope"), Mapping
        ):
            value = value["parser_input_envelope"]
        if not isinstance(value, Mapping):
            return ""
        acquisition = value.get("acquisition")
        receipt = acquisition.get("receipt") if isinstance(acquisition, Mapping) else None
        return (
            str(receipt.get("receipt_sha256") or "").strip()
            if isinstance(receipt, Mapping)
            else ""
        )

    @staticmethod
    def _tennessee_observed_at_from_receipt(receipt: Mapping[str, Any]) -> str:
        for key in ("retrieved_at", "observed_at", "timestamp", "fetched_at"):
            value = str(receipt.get(key) or "").strip()
            if value:
                return value
        origin = receipt.get("origin_transport_receipt")
        if isinstance(origin, Mapping):
            return TennesseeScraper._tennessee_observed_at_from_receipt(origin)
        return ""

    @classmethod
    def _tennessee_observed_at_from_retained(cls, retained: Any) -> str:
        observed_at = cls._tennessee_observed_at_from_receipt(
            dict(getattr(retained, "transport_receipt", {}) or {})
        )
        if observed_at:
            return observed_at
        receipt = getattr(retained, "receipt", None)
        return str(getattr(receipt, "retrieved_at", "") or "").strip()

    def _latest_tennessee_browser_record(
        self,
        official_url: str,
        sanitized_request: Mapping[str, Any],
    ) -> Any:
        """Select the latest exact phased browser observation by receipt time."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Tennessee browser replay requires an attached ledger")
        request = dict(sanitized_request)
        candidates = []
        for retained in tuple(getattr(ledger, "entries", ()) or ()):
            receipt = getattr(retained, "receipt", None)
            if (
                str(getattr(receipt, "endpoint", "") or "").rstrip("/")
                == str(official_url).rstrip("/")
                and isinstance(getattr(receipt, "sanitized_request", None), Mapping)
                and dict(receipt.sanitized_request) == request
            ):
                candidates.append(retained)
        if not candidates:
            replay_one = getattr(ledger, "replay_retained_parser_input", None)
            if callable(replay_one):
                return replay_one(
                    official_url=str(official_url),
                    sanitized_request=request,
                )
            replay_many = getattr(ledger, "replay_retained_parser_inputs", None)
            if callable(replay_many):
                rows = replay_many(requests=[(str(official_url), request)])
                return rows[0] if rows else None
            raise RuntimeError("Tennessee ledger lacks browser replay support")

        def _receipt_time(retained: Any) -> datetime:
            return self._parse_tennessee_timestamp(
                self._tennessee_observed_at_from_retained(retained),
                field="retained browser response boundary",
            )

        selected = max(candidates, key=_receipt_time)
        body = bytes(getattr(selected.envelope, "body", b"") or b"")
        body_path = getattr(selected, "body_path", None)
        if body_path is not None:
            source = Path(body_path)
            if source.is_symlink() or not source.is_file() or source.read_bytes() != body:
                raise RuntimeError(
                    "Tennessee latest browser response object changed after retention"
                )
        content = getattr(getattr(selected, "receipt", None), "content", None)
        if (
            not body
            or str(getattr(content, "sha256", "") or "").strip().lower()
            != hashlib.sha256(body).hexdigest()
        ):
            raise RuntimeError("Tennessee latest browser response failed fixity")
        return selected

    def _replay_optional_tennessee_input(
        self,
        official_url: str,
        sanitized_request: Mapping[str, Any],
    ) -> Any:
        """Return one exact live-ledger hit without recording a parse report."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Tennessee live resume requires an attached ledger")
        request = dict(sanitized_request)
        phase = self._phase_from_request(request)
        if phase is not None and phase != self._select_tennessee_acquisition_phase(
            allow_new=False
        ):
            raise RuntimeError("Tennessee live resume crossed acquisition phases")
        retained = self._latest_tennessee_browser_record(
            str(official_url),
            request,
        )
        if retained is None:
            return None
        body = bytes(getattr(retained.envelope, "body", b"") or b"")
        transport = dict(getattr(retained, "transport_receipt", {}) or {})
        digest = hashlib.sha256(body).hexdigest()
        if (
            not body
            or str(transport.get("official_url") or "").rstrip("/")
            != str(official_url).rstrip("/")
            or str(transport.get("content_sha256") or "").lower() != digest
            or str(transport.get("source_transport") or "")
            != "browser_rendered"
            or not self._tennessee_observed_at_from_retained(retained)
        ):
            raise RuntimeError(
                f"Tennessee live resume found invalid retained evidence: {official_url}"
            )
        receipt = getattr(retained, "receipt", None)
        pagination = getattr(receipt, "pagination", None)
        response_proof = (
            pagination.get("tennessee_browser_response")
            if isinstance(pagination, Mapping)
            else None
        )
        if phase is not None:
            if not isinstance(response_proof, Mapping):
                raise RuntimeError(
                    "Tennessee phased browser replay lacks response-bound proof"
                )
            proof_phase = pagination.get("tennessee_acquisition_phase")
            if not isinstance(proof_phase, Mapping) or (
                str(proof_phase.get("phase_id") or "").strip().lower(),
                self._parse_tennessee_timestamp(
                    proof_phase.get("started_at"),
                    field="retained browser phase start",
                ).isoformat(),
            ) != phase:
                raise RuntimeError(
                    "Tennessee phased browser replay has detached phase proof"
                )
        from .tennessee_lexis_live import TennesseeRetainedBrowserInput

        return TennesseeRetainedBrowserInput(
            body=body,
            response_proof=dict(response_proof or {}),
        )

    def _record_tennessee_retained_input(
        self,
        *,
        source_role: str,
        official_url: str,
        sanitized_request: Mapping[str, Any],
        retained: Any,
    ) -> bytes:
        """Bind one exact request identity, body, receipt, and source position."""

        from .tennessee_lexis import canonical_digest

        body = bytes(getattr(retained.envelope, "body", b"") or b"")
        transport_receipt = dict(
            getattr(retained, "transport_receipt", {}) or {}
        )
        body_sha256 = hashlib.sha256(body).hexdigest()
        parser_input_receipt_sha256 = self._tennessee_envelope_receipt_sha256(
            retained.envelope
        )
        observed_at = self._tennessee_observed_at_from_retained(retained)
        normalized_observed_at = self._parse_tennessee_timestamp(
            observed_at,
            field=f"{source_role} receipt time",
        ).isoformat()
        request_phase = self._phase_from_request(dict(sanitized_request))
        active_phase = self._select_tennessee_acquisition_phase(allow_new=False)
        receipt = getattr(retained, "receipt", None)
        pagination = getattr(receipt, "pagination", None)
        pagination_phase = (
            pagination.get("tennessee_acquisition_phase")
            if isinstance(pagination, Mapping)
            else None
        )
        retained_phase = None
        if isinstance(pagination_phase, Mapping):
            retained_phase = (
                str(pagination_phase.get("phase_id") or "").strip().lower(),
                self._parse_tennessee_timestamp(
                    pagination_phase.get("started_at"),
                    field=f"{source_role} retained phase start",
                ).isoformat(),
            )
        if (
            not body
            or not transport_receipt
            or str(transport_receipt.get("official_url") or "").rstrip("/")
            != str(official_url).rstrip("/")
            or str(transport_receipt.get("content_sha256") or "").lower()
            != body_sha256
            or not str(
                transport_receipt.get("source_transport") or ""
            ).strip()
            or not re.fullmatch(r"[a-f0-9]{64}", parser_input_receipt_sha256)
            or request_phase != active_phase
            or retained_phase != active_phase
            or not normalized_observed_at
        ):
            raise RuntimeError(
                "Tennessee retained parser input omitted exact byte/transport "
                f"evidence: {official_url}"
            )
        browser_proof: Dict[str, Any] = {}
        if source_role in {"rendered_container_root", "title_open_to_response"}:
            from .tennessee_lexis import (
                PUBLIC_CONTAINER_URL,
                TOC_ENDPOINT_URL,
                container_url_matches,
            )

            raw_browser_proof = (
                pagination.get("tennessee_browser_response")
                if isinstance(pagination, Mapping)
                else None
            )
            if not isinstance(raw_browser_proof, Mapping):
                raise RuntimeError(
                    "Tennessee browser receipt lacks response-bound URL proof"
                )
            browser_proof = dict(raw_browser_proof)
            proof_time = self._parse_tennessee_timestamp(
                browser_proof.get("response_observed_at"),
                field=f"{source_role} browser response boundary",
            ).isoformat()
            session_digest = str(
                browser_proof.get("session_request_id_sha256") or ""
            ).strip().lower()
            final_url = str(browser_proof.get("final_url") or "").strip()
            if (
                proof_time != normalized_observed_at
                or not re.fullmatch(r"[a-f0-9]{64}", session_digest)
                or (
                    source_role == "rendered_container_root"
                    and (
                        official_url != PUBLIC_CONTAINER_URL
                        or not container_url_matches(final_url)
                    )
                )
                or (
                    source_role == "title_open_to_response"
                    and (
                        official_url != TOC_ENDPOINT_URL
                        or final_url != TOC_ENDPOINT_URL
                        or browser_proof.get("redirected") is not False
                        or list(browser_proof.get("redirect_chain") or []) != []
                        or session_digest
                        != str(
                            sanitized_request.get("session_request_id_sha256") or ""
                        )
                    )
                )
            ):
                raise RuntimeError(
                    "Tennessee browser receipt has detached response/session proof"
                )
        reports = list(getattr(self, "_tennessee_frontier_input_reports", []))
        report = {
            "content_sha256": body_sha256,
            "acquisition_phase_id": active_phase[0],
            "acquisition_phase_started_at": active_phase[1],
            "parser_input_receipt_sha256": parser_input_receipt_sha256,
            "request_identity_sha256": canonical_digest(dict(sanitized_request)),
            "source_order": len(reports),
            "source_role": str(source_role),
            "source_transport": str(
                transport_receipt.get("source_transport") or ""
            ),
            "source_url": str(official_url),
            "observed_at": normalized_observed_at,
            "transport_receipt_sha256": canonical_digest(transport_receipt),
        }
        if browser_proof:
            report.update(
                {
                    "browser_response_proof_sha256": canonical_digest(browser_proof),
                    "final_response_url": str(browser_proof.get("final_url") or ""),
                    "response_redirected": browser_proof.get("redirected") is True,
                    "session_request_id_sha256": str(
                        browser_proof.get("session_request_id_sha256") or ""
                    ),
                }
            )
        expected_transport = {
            "state_delegation": "direct",
            "publisher_entry": "direct",
            "rendered_container_root": "browser_rendered",
            "title_open_to_response": "browser_rendered",
            "statute_document_body": "direct",
        }.get(str(source_role))
        if expected_transport and report["source_transport"] != expected_transport:
            raise RuntimeError(
                "Tennessee retained frontier rejected an inadmissible current-source "
                f"transport for {source_role}: {report['source_transport'] or 'missing'}"
            )
        request_identity = str(report["request_identity_sha256"])
        if any(
            str(item.get("request_identity_sha256") or "") == request_identity
            for item in reports
        ):
            raise RuntimeError(
                "Tennessee retained frontier repeated an exact request identity"
            )
        reports.append(report)
        self._tennessee_frontier_input_reports = reports
        return body

    def _replay_tennessee_retained_wave(
        self,
        requests: Sequence[tuple[str, Mapping[str, Any]]],
        *,
        frontier_name: str,
        source_role: str,
    ) -> tuple[bytes, ...]:
        """Replay one whole ordered hierarchy/body wave with zero I/O."""

        from .strict_frontier_closure import replay_exact_retained_state_records

        requested = [(str(url), dict(request)) for url, request in requests]
        retained_rows = replay_exact_retained_state_records(
            self,
            requests=requested,
            frontier_name=f"Tennessee {frontier_name}",
            refresh=False,
        )
        payloads: List[bytes] = []
        for (official_url, sanitized_request), retained in zip(
            requested,
            retained_rows,
            strict=True,
        ):
            payloads.append(
                self._record_tennessee_retained_input(
                    source_role=source_role,
                    official_url=official_url,
                    sanitized_request=sanitized_request,
                    retained=retained,
                )
            )
        return tuple(payloads)

    def _validate_tennessee_phase_reports(
        self,
        reports: Sequence[Mapping[str, Any]],
        *,
        patch_count: int,
        body_count: int,
    ) -> Dict[str, Any]:
        """Close one exact phase and its response-bound temporal interval."""

        from .tennessee_lexis import (
            PUBLIC_CONTAINER_URL,
            PUBLIC_ENTRY_URL,
            TOC_ENDPOINT_URL,
            canonical_digest,
            is_document_path,
        )

        phase_id, phase_started_at = self._select_tennessee_acquisition_phase(
            allow_new=False
        )
        expected_roles = [
            "state_delegation",
            "publisher_entry",
            "rendered_container_root",
            *(["title_open_to_response"] * int(patch_count)),
            *(["statute_document_body"] * int(body_count)),
        ]
        normalized = [dict(item) for item in reports]
        if (
            not normalized
            or len(normalized) != len(expected_roles)
            or [str(item.get("source_role") or "") for item in normalized]
            != expected_roles
            or [int(item.get("source_order", -1)) for item in normalized]
            != list(range(len(normalized)))
        ):
            raise RuntimeError("Tennessee acquisition phase changed exact wave order")
        if any(
            (
                str(item.get("acquisition_phase_id") or "").strip().lower(),
                self._parse_tennessee_timestamp(
                    item.get("acquisition_phase_started_at"),
                    field="input phase start",
                ).isoformat(),
            )
            != (phase_id, phase_started_at)
            for item in normalized
        ):
            raise RuntimeError("Tennessee closure mixed acquisition phases")
        if len(
            {
                str(item.get("request_identity_sha256") or "")
                for item in normalized
            }
        ) != len(normalized):
            raise RuntimeError("Tennessee phase repeats a request identity")

        expected_urls = (
            self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL,
            PUBLIC_ENTRY_URL,
            PUBLIC_CONTAINER_URL,
        )
        if tuple(str(normalized[index].get("source_url") or "") for index in range(3)) != expected_urls:
            raise RuntimeError("Tennessee phase changed the delegation chain locators")
        root_session = str(
            normalized[2].get("session_request_id_sha256") or ""
        ).strip().lower()
        patch_rows = normalized[3 : 3 + int(patch_count)]
        if any(
            str(item.get("source_url") or "") != TOC_ENDPOINT_URL
            or str(item.get("source_transport") or "") != "browser_rendered"
            or str(item.get("session_request_id_sha256") or "").strip().lower()
            != root_session
            or item.get("response_redirected") is not False
            for item in patch_rows
        ):
            raise RuntimeError("Tennessee phase has an unbound PATCH session/response")
        body_rows = normalized[3 + int(patch_count) :]
        if any(
            str(item.get("source_transport") or "") != "direct"
            or (urlparse(str(item.get("source_url") or "")).hostname or "").lower()
            != "advance.lexis.com"
            or not is_document_path(
                urlparse(str(item.get("source_url") or "")).path
            )
            for item in body_rows
        ):
            raise RuntimeError("Tennessee phase substituted a delegated body locator")

        observed = [
            self._parse_tennessee_timestamp(
                item.get("observed_at"),
                field=f"input {position} response boundary",
            )
            for position, item in enumerate(normalized)
        ]
        started = self._parse_tennessee_timestamp(
            phase_started_at,
            field="acquisition phase start",
        )
        completed = max(observed)
        earliest = min(observed)
        wave_observed = {
            "state_delegation": observed[0:1],
            "publisher_entry": observed[1:2],
            "rendered_container_root": observed[2:3],
            "title_open_to_response": observed[3 : 3 + int(patch_count)],
            "statute_document_body": observed[3 + int(patch_count) :],
        }
        ordered_waves = [
            wave_observed[name]
            for name in (
                "state_delegation",
                "publisher_entry",
                "rendered_container_root",
                "title_open_to_response",
                "statute_document_body",
            )
            if wave_observed[name]
        ]
        if any(
            max(left) > min(right)
            for left, right in zip(ordered_waves, ordered_waves[1:], strict=False)
        ):
            raise RuntimeError("Tennessee acquisition phase crossed temporal wave order")
        now = datetime.now(UTC)
        span = (completed - earliest).total_seconds()
        if (
            earliest < started
            or completed < started
            or span < 0
            or span > self.TN_PHASE_MAX_SPAN_SECONDS
            or (completed - started).total_seconds() > self.TN_PHASE_MAX_SPAN_SECONDS
            or completed
            > now + timedelta(seconds=self.TN_PHASE_CLOCK_SKEW_SECONDS)
        ):
            raise RuntimeError("Tennessee acquisition phase is temporally incoherent")
        projection = {
            "completed_at": completed.isoformat(),
            "delegated_body_source_domain": "advance.lexis.com",
            "delegating_authority_url": self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL,
            "input_count": len(normalized),
            "input_receipt_sha256s": [
                str(item.get("parser_input_receipt_sha256") or "")
                for item in normalized
            ],
            "observed_at_first": earliest.isoformat(),
            "observed_at_last": completed.isoformat(),
            "phase_id": phase_id,
            "phase_schema": self.TN_PHASE_SCHEMA,
            "phase_span_seconds": span,
            "phase_started_at": phase_started_at,
            "required_role_counts": {
                role: expected_roles.count(role) for role in dict.fromkeys(expected_roles)
            },
        }
        projection["projection_sha256"] = canonical_digest(projection)
        return projection

    @staticmethod
    def _tennessee_decode(payload: bytes, *, source_role: str) -> str:
        for encoding in ("utf-8-sig", "windows-1252"):
            try:
                return bytes(payload).decode(encoding, errors="strict")
            except UnicodeDecodeError:
                continue
        raise RuntimeError(
            f"Tennessee retained {source_role} input has no supported exact encoding"
        )

    @classmethod
    def _valid_tennessee_authority_payload(cls, payload: bytes) -> bool:
        raw = bytes(payload or b"")
        if not raw:
            return False
        try:
            html = cls._tennessee_decode(raw, source_role="authority")
        except RuntimeError:
            return False
        sample = html[:200_000]
        return bool(
            re.search(r"<html\b|<!doctype\s+html", sample, re.IGNORECASE)
            and not cls._TN_CLOUDFLARE_CHALLENGE_RE.search(sample)
            and not re.search(
                r"robot\s*validation|captcha|sign\s+in\s+to\s+continue",
                sample,
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _tennessee_receipt_proves_container(
        receipt: Mapping[str, Any],
    ) -> bool:
        """Accept only named final/redirect locator evidence, never arbitrary text."""

        from .tennessee_lexis import container_url_matches

        pending: List[Mapping[str, Any]] = [dict(receipt)]
        while pending:
            value = pending.pop()
            for key in ("final_url", "response_url"):
                locator = value.get(key)
                if isinstance(locator, str) and container_url_matches(locator):
                    return True
            for key in ("redirect_chain", "redirects"):
                chain = value.get(key)
                if not isinstance(chain, Sequence) or isinstance(
                    chain, (str, bytes, bytearray)
                ):
                    continue
                for hop in chain:
                    if isinstance(hop, str) and container_url_matches(hop):
                        return True
                    if isinstance(hop, Mapping):
                        for locator_key in ("url", "location", "final_url"):
                            locator = hop.get(locator_key)
                            if isinstance(locator, str) and container_url_matches(
                                locator
                            ):
                                return True
            origin = value.get("origin_transport_receipt")
            if isinstance(origin, Mapping):
                pending.append(origin)
        return False

    @staticmethod
    def _tennessee_publisher_receipt_proves_container(
        retained: Any,
        payload: bytes,
    ) -> bool:
        from .tennessee_lexis import publisher_container_delegation_present

        if publisher_container_delegation_present(
            payload.decode("utf-8", errors="replace")
        ):
            return True
        receipt = dict(getattr(retained, "transport_receipt", {}) or {})
        return TennesseeScraper._tennessee_receipt_proves_container(receipt)

    async def _acquire_tennessee_lexis_frontier(
        self,
        *,
        code_name: str,
    ) -> List[NormalizedStatute]:
        """Acquire five bounded live waves, then parse their retained replay."""

        from .tennessee_lexis import (
            derive_exact_metadata_frontier,
            document_url,
            general_assembly_delegation_present,
            observed_metadata_drift,
            publisher_container_delegation_present,
            valid_document_payload,
        )
        from .tennessee_lexis_live import acquire_live_catalog

        self._validate_tennessee_lexis_configuration()
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(self.STRICT_FULL_BLOCKER)
        if self._retained_replay_only_enabled():
            raise RuntimeError(
                "Tennessee live acquisition cannot run in retained-replay-only mode"
            )
        if not callable(getattr(ledger, "retain_parser_input", None)) or not callable(
            getattr(ledger, "replay_retained_parser_input", None)
        ):
            raise RuntimeError(
                "Tennessee live acquisition ledger lacks exact retain/replay support"
            )
        phase_id, phase_started_at = self._select_tennessee_acquisition_phase(
            allow_new=True
        )

        authority_batch = await self._fetch_tennessee_lexis_get_wave(
            [self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL],
            frontier_name="General Assembly delegation",
            content_validator=lambda payload: bool(
                self._valid_tennessee_authority_payload(payload)
                and general_assembly_delegation_present(
                    self._tennessee_decode(payload, source_role="state delegation")
                )
            ),
            require_direct=True,
        )
        authority_payload = bytes(authority_batch.payloads[0])
        if not general_assembly_delegation_present(
            self._tennessee_decode(
                authority_payload,
                source_role="state delegation",
            )
        ):
            raise RuntimeError(
                "Tennessee General Assembly page did not prove the exact Code delegation"
            )

        publisher_batch = await self._fetch_tennessee_lexis_get_wave(
            [self.AUTHORIZED_CODE_ENTRY_URL],
            frontier_name="publisher entry",
            content_validator=self._valid_tennessee_authority_payload,
            require_direct=True,
        )
        publisher_payload = bytes(publisher_batch.payloads[0])
        publisher_receipt = dict(publisher_batch.transport_receipts[0] or {})
        if not (
            publisher_container_delegation_present(
                publisher_payload.decode("utf-8", errors="replace")
            )
            or self._tennessee_receipt_proves_container(publisher_receipt)
        ):
            raise RuntimeError(
                "Tennessee publisher entry did not prove the exact Lexis container"
            )

        inventory = await acquire_live_catalog(
            acquisition_phase_id=phase_id,
            acquisition_phase_started_at=phase_started_at,
            expected_titles=self.OFFICIAL_TITLES,
            expected_patch_count=(
                self.OBSERVED_SUBTREE_RESPONSE_COUNT
                if self.ENFORCE_OBSERVED_TN_FRONTIER
                else sum(
                    number not in {"19", "51"}
                    for number, _label in self.OFFICIAL_TITLES
                )
            ),
            retain_parser_input=self._retain_tennessee_browser_input,
            replay_parser_input=self._replay_optional_tennessee_input,
            retries=max(
                1,
                min(
                    5,
                    self._env_int("TENNESSEE_LEXIS_PROBE_RETRIES", default=2),
                ),
            ),
            timeout_ms=max(
                15_000,
                self._env_int("TENNESSEE_LEXIS_PROBE_TIMEOUT_MS", default=60_000),
            ),
        )
        metadata = dict(inventory.metadata)
        # Re-derive here so a mocked or future live seam cannot inject body URLs.
        expected_metadata = derive_exact_metadata_frontier(
            inventory.title_roots,
            subtrees_by_root_id=inventory.subtrees_by_root_id,
        )
        if metadata != expected_metadata:
            raise RuntimeError("Tennessee live catalog returned injected metadata")
        document_nodes = list(metadata.pop("document_nodes"))
        drift = observed_metadata_drift(metadata)
        if self.ENFORCE_OBSERVED_TN_FRONTIER and drift:
            raise RuntimeError(
                "Tennessee live Lexis hierarchy drifted from the reviewed exact "
                f"frontier: {drift}"
            )
        body_urls = [document_url(node.link_href) for node in document_nodes]
        if len(body_urls) != len(set(body_urls)):
            raise RuntimeError("Tennessee live body frontier repeated a source URL")
        if (
            self.ENFORCE_OBSERVED_TN_FRONTIER
            and len(body_urls) != self.OBSERVED_BODY_LEAF_COUNT
        ):
            raise RuntimeError(
                "Tennessee live body wave changed reviewed membership without review"
            )
        await self._fetch_tennessee_lexis_get_wave(
            body_urls,
            frontier_name="document body wave",
            content_validator=valid_document_payload,
            require_direct=True,
        )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()
        return await self._scrape_strict_tennessee_retained_frontier(
            code_name=code_name
        )

    async def _scrape_strict_tennessee_retained_frontier(
        self,
        *,
        code_name: str,
    ) -> List[NormalizedStatute]:
        """Reconstruct all Tennessee rows from exact retained inputs only."""

        from .strict_frontier_closure import replay_exact_retained_state_records
        from .tennessee_lexis import (
            OBSERVED_TOTAL_RESIDUAL_COUNT,
            canonical_digest,
            derive_exact_metadata_frontier,
            document_url,
            general_assembly_delegation_present,
            observed_metadata_drift,
            parse_root_html,
            parse_tennessee_lexis_document_html,
            parse_title_subtree_payload,
            unresolved_temporal_variant_groups,
            valid_document_payload,
        )
        from .tennessee_lexis_live import (
            canonical_live_toc_patch_request,
            canonical_rendered_root_request,
        )

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Tennessee strict retained route requires an attached ledger")
        self._validate_tennessee_lexis_configuration()
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()
        phase_id, phase_started_at = self._select_tennessee_acquisition_phase(
            allow_new=False
        )
        self._tennessee_frontier_input_reports = []

        authority_request = self._tennessee_get_request(
            self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL
        )
        authority_payload = self._replay_tennessee_retained_wave(
            [(self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL, authority_request)],
            frontier_name="General Assembly delegation",
            source_role="state_delegation",
        )[0]
        if not general_assembly_delegation_present(
            self._tennessee_decode(authority_payload, source_role="state delegation")
        ):
            raise RuntimeError(
                "Tennessee retained General Assembly page does not prove the exact Code delegation"
            )

        publisher_request = self._tennessee_get_request(self.AUTHORIZED_CODE_ENTRY_URL)
        publisher_retained = replay_exact_retained_state_records(
            self,
            requests=[(self.AUTHORIZED_CODE_ENTRY_URL, publisher_request)],
            frontier_name="Tennessee publisher entry",
            refresh=False,
        )[0]
        publisher_payload = self._record_tennessee_retained_input(
            source_role="publisher_entry",
            official_url=self.AUTHORIZED_CODE_ENTRY_URL,
            sanitized_request=publisher_request,
            retained=publisher_retained,
        )
        if not self._tennessee_publisher_receipt_proves_container(
            publisher_retained,
            publisher_payload,
        ):
            raise RuntimeError(
                "Tennessee retained publisher entry does not prove the exact Lexis container"
            )

        root_request = canonical_rendered_root_request(
            acquisition_phase_id=phase_id,
            acquisition_phase_started_at=phase_started_at,
        )
        root_retained = self._latest_tennessee_browser_record(
            self.AUTHORIZED_CODE_CONTAINER_URL,
            root_request,
        )
        if root_retained is None:
            raise RuntimeError("Tennessee retained rendered root is missing")
        root_payload = self._record_tennessee_retained_input(
            source_role="rendered_container_root",
            official_url=self.AUTHORIZED_CODE_CONTAINER_URL,
            sanitized_request=root_request,
            retained=root_retained,
        )
        title_roots, tables_root = parse_root_html(
            self._tennessee_decode(root_payload, source_role="rendered Lexis root"),
            expected_titles=self.OFFICIAL_TITLES,
        )

        expandable_roots = [
            node for node in title_roots if node.can_expand or node.has_children
        ]
        root_report = self._tennessee_frontier_input_reports[2]
        root_session_digest = str(
            root_report.get("session_request_id_sha256") or ""
        ).strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", root_session_digest):
            raise RuntimeError("Tennessee retained root lacks its browser session binding")
        patch_specs = [
            canonical_live_toc_patch_request(
                node,
                acquisition_phase_id=phase_id,
                acquisition_phase_started_at=phase_started_at,
                session_request_id_sha256=root_session_digest,
            )
            for node in expandable_roots
        ]
        patch_requests = [
            (endpoint, sanitized_request)
            for endpoint, _request_body, sanitized_request in patch_specs
        ]
        patch_payloads = self._replay_tennessee_retained_wave(
            patch_requests,
            frontier_name="deepest title TOC wave",
            source_role="title_open_to_response",
        )
        subtrees: Dict[str, Sequence[Any]] = {}
        subtree_manifest: List[Dict[str, Any]] = []
        for parent, spec, payload in zip(
            expandable_roots,
            patch_specs,
            patch_payloads,
            strict=True,
        ):
            _endpoint, request_body, _sanitized = spec
            try:
                decoded = payload.decode("utf-8-sig", errors="strict")
                response = json.loads(decoded)
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"Tennessee Title {parent.title_number} retained TOC response is invalid JSON"
                ) from exc
            descendants, closed_expandable_ids, error = parse_title_subtree_payload(
                response,
                parent=parent,
                target_level=max(parent.open_to_levels),
            )
            if error:
                raise RuntimeError(
                    f"Tennessee Title {parent.title_number} TOC did not close: {error}"
                )
            subtrees[parent.node_id] = descendants
            subtree_manifest.append(
                {
                    "closed_expandable_node_count": len(closed_expandable_ids),
                    "parent_node_id": parent.node_id,
                    "request_body_sha256": hashlib.sha256(request_body).hexdigest(),
                    "response_sha256": hashlib.sha256(payload).hexdigest(),
                    "target_level": max(parent.open_to_levels),
                }
            )

        metadata = derive_exact_metadata_frontier(
            title_roots,
            subtrees_by_root_id=subtrees,
        )
        document_nodes = list(metadata.pop("document_nodes"))
        drift = observed_metadata_drift(metadata)
        if self.ENFORCE_OBSERVED_TN_FRONTIER and drift:
            raise RuntimeError(
                "Tennessee retained Lexis hierarchy drifted from the reviewed exact "
                f"frontier: {drift}"
            )

        body_urls = [document_url(node.link_href) for node in document_nodes]
        body_payloads = self._replay_tennessee_retained_wave(
            [(url, self._tennessee_get_request(url)) for url in body_urls],
            frontier_name="document body wave",
            source_role="statute_document_body",
        )
        rows: List[NormalizedStatute] = []
        body_reports: List[Dict[str, Any]] = []
        terminals: List[Dict[str, Any]] = []
        parser_residuals: List[Dict[str, Any]] = []
        for source_order, (node, url, payload) in enumerate(
            zip(document_nodes, body_urls, body_payloads, strict=True)
        ):
            if not valid_document_payload(payload):
                parser_residuals.append(
                    {
                        "content_item_id": node.content_item_id,
                        "reason": "invalid_or_blocked_document_payload",
                        "source_order": source_order,
                        "source_url": url,
                    }
                )
                continue
            parsed_rows, report = parse_tennessee_lexis_document_html(
                self._tennessee_decode(payload, source_role="document body"),
                source_url=url,
                node=node,
                source_order=source_order,
                code_name=code_name,
            )
            body_input_report = self._tennessee_frontier_input_reports[
                3 + len(expandable_roots) + source_order
            ]
            for row in parsed_rows:
                row.structured_data.update(
                    {
                        "parser_input_receipt_sha256": str(
                            body_input_report["parser_input_receipt_sha256"]
                        ),
                        "source_content_sha256": str(
                            body_input_report["content_sha256"]
                        ),
                        "source_request_identity_sha256": str(
                            body_input_report["request_identity_sha256"]
                        ),
                        "source_transport": str(
                            body_input_report["source_transport"]
                        ),
                        "transport_receipt_sha256": str(
                            body_input_report["transport_receipt_sha256"]
                        ),
                    }
                )
            for terminal in report.get("terminal_dispositions") or []:
                terminal.update(
                    {
                        "parser_input_receipt_sha256": str(
                            body_input_report["parser_input_receipt_sha256"]
                        ),
                        "source_content_sha256": str(
                            body_input_report["content_sha256"]
                        ),
                        "source_request_identity_sha256": str(
                            body_input_report["request_identity_sha256"]
                        ),
                        "source_transport": str(
                            body_input_report["source_transport"]
                        ),
                        "transport_receipt_sha256": str(
                            body_input_report["transport_receipt_sha256"]
                        ),
                    }
                )
            body_reports.append(report)
            rows.extend(parsed_rows)
            terminals.extend(report.get("terminal_dispositions") or [])
            parser_residuals.extend(report.get("parser_residuals") or [])
        if parser_residuals:
            raise RuntimeError(
                "Tennessee retained body frontier has parser residuals: "
                f"{parser_residuals[:10]} (total={len(parser_residuals)})"
            )

        temporal_residuals = unresolved_temporal_variant_groups(rows)
        if temporal_residuals:
            self.last_tennessee_full_corpus_report = {
                **metadata,
                "body_input_count": len(document_nodes),
                "closed": False,
                "disposition": "source_bound_temporal_reconciliation_required",
                "network_requested_pages": 0,
                "parser_residual_count": len(temporal_residuals),
                "retained_replay_only": True,
                "temporal_variant_residual_identity_count": len(
                    temporal_residuals
                ),
                "temporal_variant_residual_locator_count": sum(
                    int(item["candidate_count"]) for item in temporal_residuals
                ),
                "temporal_variant_residuals": temporal_residuals,
            }
            raise RuntimeError(
                "Tennessee retained body frontier requires source-bound temporal "
                f"reconciliation for {len(temporal_residuals)} repeated citation "
                "identities"
            )

        canonical_keys = [
            str((row.structured_data or {}).get("canonical_section_key") or "")
            for row in rows
        ]
        if (
            any(not key for key in canonical_keys)
            or len(canonical_keys) != len(set(canonical_keys))
            or len(rows) + len(terminals) != len(document_nodes)
        ):
            raise RuntimeError(
                "Tennessee body/terminal output does not close the content-item algebra"
            )

        input_reports = list(self._tennessee_frontier_input_reports)
        expected_inputs = 3 + len(expandable_roots) + len(document_nodes)
        if len(input_reports) != expected_inputs:
            raise RuntimeError("Tennessee strict input report count is not exact")
        if (
            self.ENFORCE_OBSERVED_TN_FRONTIER
            and expected_inputs != OBSERVED_TOTAL_RESIDUAL_COUNT
        ):
            raise RuntimeError(
                "Tennessee exact source input algebra changed without review"
            )
        phase_projection = self._validate_tennessee_phase_reports(
            input_reports,
            patch_count=len(expandable_roots),
            body_count=len(document_nodes),
        )

        disposition = {
            "discovered": len(document_nodes),
            "duplicates": 0,
            "excluded": len(terminals),
            "failed_final": 0,
            "fetched": len(rows),
            "quarantined": 0,
        }
        observed_at = str(phase_projection["completed_at"])
        delegated_body_authority = {
            "acquisition_phase": phase_projection,
            "body_input_count": len(document_nodes),
            "body_input_receipt_sha256s_digest": canonical_digest(
                [
                    item["parser_input_receipt_sha256"]
                    for item in input_reports[3 + len(expandable_roots) :]
                ]
            ),
            "body_url_path_prefix": "/shared/document/statutes-legislation/",
            "catalog_acquisition_path_id": "tn-tga",
            "delegated_body_source_domain": "advance.lexis.com",
            "delegated_container_url": self.AUTHORIZED_CODE_CONTAINER_URL,
            "delegated_toc_endpoint_url": (
                "https://advance.lexis.com" + self.AUTHORIZED_TOC_ENDPOINT
            ),
            "delegating_authority_url": self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL,
            "input_report_digest_sha256": canonical_digest(input_reports),
            "publisher_entry_url": self.AUTHORIZED_CODE_ENTRY_URL,
            "required_transports": {
                "publisher_entry": "direct",
                "rendered_container_root": "browser_rendered",
                "state_delegation": "direct",
                "statute_document_body": "direct",
                "title_open_to_response": "browser_rendered",
            },
            "schema_version": "tennessee-delegated-body-authority-v1",
        }
        delegated_body_authority["projection_sha256"] = canonical_digest(
            delegated_body_authority
        )
        frontier: Dict[str, Any] = {
            **metadata,
            "algebra_closed": True,
            "authority_catalog_input_count": 3 + len(expandable_roots),
            "body_input_count": len(document_nodes),
            "body_parser_report_count": len(body_reports),
            "closed": True,
            "diagnostic_baseline_drift": drift,
            "delegated_body_authority": delegated_body_authority,
            "delegated_body_authority_projection_sha256": delegated_body_authority[
                "projection_sha256"
            ],
            "disposition": disposition,
            "enumerator_closed": True,
            "excluded_root_count": 1,
            "excluded_root_label": tables_root.title,
            "input_report_digest_sha256": canonical_digest(input_reports),
            "method": "official_delegated_tennessee_lexis_retained_replay",
            "network_requested_pages": 0,
            "ordered_request_wave_counts": [1, 1, 1, len(expandable_roots), len(document_nodes)],
            "parser_residual_count": 0,
            "per_page_archive_inventory_loop": False,
            "retained_replay_only": True,
            "row_binding_digest_sha256": canonical_digest(
                [
                    [
                        key,
                        row.source_url,
                        str((row.structured_data or {}).get("content_item_id") or ""),
                        str(
                            (row.structured_data or {}).get(
                                "source_content_sha256"
                            )
                            or ""
                        ),
                    ]
                    for key, row in zip(canonical_keys, rows, strict=True)
                ]
            ),
            "scope_closed": True,
            "source_input_count": len(input_reports),
            "source_request_order_digest_sha256": canonical_digest(
                [
                    [
                        item["source_order"],
                        item["source_role"],
                        item["source_url"],
                        item["request_identity_sha256"],
                    ]
                    for item in input_reports
                ]
            ),
            "source_order_preserved": True,
            "source_parser_body_order_digest_sha256": canonical_digest(
                [
                    [
                        item["source_order"],
                        item["source_url"],
                        item["content_sha256"],
                    ]
                    for item in input_reports
                ]
            ),
            "subtree_manifest_sha256": canonical_digest(subtree_manifest),
            "terminal_binding_digest_sha256": canonical_digest(
                [
                    [
                        item.get("source_order"),
                        item.get("content_item_id"),
                        item.get("disposition"),
                        item.get("source_url"),
                        item.get("source_content_sha256"),
                        item.get("source_request_identity_sha256"),
                        item.get("parser_input_receipt_sha256"),
                        item.get("transport_receipt_sha256"),
                    ]
                    for item in terminals
                ]
            ),
            "terminal_document_count": len(terminals),
            "terminal_disposition_counts": {
                disposition_name: sum(
                    str(item.get("disposition") or "") == disposition_name
                    for item in terminals
                )
                for disposition_name in sorted(
                    {str(item.get("disposition") or "") for item in terminals}
                )
                if disposition_name
            },
            "toc_patch_archive_substitution_allowed": False,
            "unresolved_input_count": 0,
        }
        frontier["frontier_digest_sha256"] = canonical_digest(frontier)
        observation = {
            "boundary_first": body_urls[0] if body_urls else "",
            "boundary_last": body_urls[-1] if body_urls else "",
            "code_name": code_name,
            "frontier": frontier,
            "input_reports": input_reports,
            "legal_as_of": observed_at[:10] if observed_at else "",
            "observed_at": observed_at,
        }
        replaying = bool(getattr(self, "_tennessee_retained_replay", False))
        if replaying:
            self._last_tennessee_replayed_frontier = observation
        else:
            self._last_tennessee_full_frontier = observation
        self.last_tennessee_full_corpus_report = dict(frontier)
        return rows

    def retain_state_law_frontier_closure_projection(
        self,
        completion_receipt: Mapping[str, Any],
        *,
        replayed_frontier: Mapping[str, Any],
        canonical_output_projection: Mapping[str, Any] | None = None,
        release_point: str,
        official_source_url: str,
        acquisition_path_ids: Sequence[str],
        observation_time: str,
        source_software_version: str,
        relative_path: str | None = None,
        legacy_singleton: bool = False,
    ) -> Path:
        """Layer exact delegated-body proof over truthful ``tn-tga`` admission."""

        from .tennessee_lexis import canonical_digest

        completion = dict(completion_receipt)
        frontier = completion.get("frontier")
        replay_frontier = dict(replayed_frontier)
        if not isinstance(frontier, Mapping):
            raise RuntimeError("Tennessee closure lacks its exact source frontier")
        body_authority = frontier.get("delegated_body_authority")
        if not isinstance(body_authority, Mapping):
            raise RuntimeError("Tennessee closure lacks delegated body authority proof")
        body_projection = dict(body_authority)
        claimed_digest = str(body_projection.pop("projection_sha256", "") or "")
        if (
            official_source_url.rstrip("/")
            != self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL.rstrip("/")
            or list(acquisition_path_ids) != ["tn-tga"]
            or body_authority.get("delegating_authority_url")
            != self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL
            or body_authority.get("delegated_body_source_domain")
            != "advance.lexis.com"
            or body_authority.get("delegated_container_url")
            != self.AUTHORIZED_CODE_CONTAINER_URL
            or body_authority.get("publisher_entry_url")
            != self.AUTHORIZED_CODE_ENTRY_URL
            or not re.fullmatch(r"[a-f0-9]{64}", claimed_digest)
            or canonical_digest(body_projection) != claimed_digest
            or str(frontier.get("delegated_body_authority_projection_sha256") or "")
            != claimed_digest
            or replay_frontier.get("delegated_body_authority") != body_authority
        ):
            raise RuntimeError(
                "Tennessee closure detached generic authority from delegated bodies"
            )
        first = getattr(self, "_last_tennessee_full_frontier", None)
        reports = first.get("input_reports") if isinstance(first, Mapping) else None
        if (
            not isinstance(reports, Sequence)
            or isinstance(reports, (str, bytes, bytearray))
            or any(not isinstance(item, Mapping) for item in reports)
            or canonical_digest(list(reports))
            != str(body_authority.get("input_report_digest_sha256") or "")
            or any(
                str(item.get("source_role") or "") == "statute_document_body"
                and (
                    str(item.get("source_transport") or "") != "direct"
                    or (urlparse(str(item.get("source_url") or "")).hostname or "").lower()
                    != "advance.lexis.com"
                )
                for item in reports
                if isinstance(item, Mapping)
            )
        ):
            raise RuntimeError("Tennessee closure body receipts changed after parsing")
        validated_phase = self._validate_tennessee_phase_reports(
            reports,
            patch_count=int(frontier.get("subtree_response_count") or 0),
            body_count=int(frontier.get("body_input_count") or 0),
        )
        if validated_phase != body_authority.get("acquisition_phase"):
            raise RuntimeError("Tennessee closure phase proof changed after parsing")
        completion.update(
            {
                "catalog_authority_domain": "wapp.capitol.tn.gov",
                "delegated_body_authority": dict(body_authority),
                "delegated_body_source_domain": "advance.lexis.com",
                "delegating_authority_url": self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL,
                "source_domain": "wapp.capitol.tn.gov",
            }
        )
        return super().retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=replayed_frontier,
            canonical_output_projection=canonical_output_projection,
            release_point=release_point,
            official_source_url=official_source_url,
            acquisition_path_ids=acquisition_path_ids,
            observation_time=observation_time,
            source_software_version=source_software_version,
            relative_path=relative_path,
            legacy_singleton=legacy_singleton,
        )

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Repeat every exact Tennessee input by ordered ledger-only waves."""

        first = getattr(self, "_last_tennessee_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Tennessee strict source frontier was not closed before output"
            )
        first_frontier = first.get("frontier")
        first_reports = first.get("input_reports")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            first_reports, Sequence
        ):
            raise RuntimeError("Tennessee first exact frontier observation is incomplete")
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Tennessee closure requires an attached acquisition ledger")
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        prior = bool(getattr(self, "_tennessee_retained_replay", False))
        self._tennessee_retained_replay = True
        try:
            replay_rows = await self._scrape_strict_tennessee_retained_frontier(
                code_name=str(first.get("code_name") or "Tennessee Code Annotated")
            )
        finally:
            self._tennessee_retained_replay = prior
        replay = getattr(self, "_last_tennessee_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("Tennessee retained replay observation is missing")
        replayed_frontier = replay.get("frontier")
        if (
            not isinstance(replayed_frontier, Mapping)
            or list(replay.get("input_reports") or []) != list(first_reports)
        ):
            raise RuntimeError("Tennessee retained request/body identities changed on replay")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        disposition = first_frontier.get("disposition")
        if not isinstance(disposition, Mapping):
            raise RuntimeError("Tennessee frontier lacks disposition algebra")
        if any(
            (urlparse(str(row.source_url or "")).hostname or "").lower()
            != "advance.lexis.com"
            or str((row.structured_data or {}).get("source_transport") or "")
            != "direct"
            for row in replay_rows
        ):
            raise RuntimeError(
                "Tennessee closure rows escaped delegated Lexis body receipts"
            )
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="TN",
            source_domain="wapp.capitol.tn.gov",
            official_source_url=self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL,
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("legal_as_of") or ""),
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=int(disposition.get("discovered") or 0),
            pagination_total=int(first_frontier.get("subtree_response_count") or 0),
            transport={
                "archive_recovery_enabled": False,
                "body_get_transport": "direct",
                "browser_transport": "browser_rendered",
                "fixture": False,
                "first_pass_requested_pages": int(
                    first_frontier.get("source_input_count") or 0
                ),
                "get_acquisition_contract": "tennessee_current_authority_direct_only",
                "grouped_warc_recovery": False,
                "kind": "delegated_lexis_patch_ledger_plus_plural_get",
                "per_page_archive_loop": False,
                "retained_replay_network_requests": 0,
                "synthetic": False,
                "toc_patch_archive_substitution_allowed": False,
            },
        )

    def get_base_url(self) -> str:
        """Return the base URL for Tennessee's legislative website."""
        return "https://www.capitol.tn.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Tennessee."""
        return [
            {
                "name": "Tennessee Code Annotated",
                "url": self.AUTHORIZED_CODE_ENTRY_URL,
                "type": "Code",
            }
        ]

    def _justia_fallback_allowed(self) -> bool:
        return str(
            os.getenv("STATE_SCRAPER_TN_ALLOW_JUSTIA_FALLBACK", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}

    def _is_justia_url(self, url: str) -> bool:
        return "justia.com" in str(url or "").lower()

    def _is_official_host(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return any(host == s or host.endswith("." + s) for s in self._TN_OFFICIAL_HOST_SUFFIXES)

    def _filter_official_only(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        """Drop secondary/Justia rows when full-corpus admission is sealed."""
        if not self._full_corpus_enabled() or self._justia_fallback_allowed():
            return statutes
        return [
            s
            for s in statutes
            if self._is_official_host(str(s.source_url or ""))
            and "justia" not in str((s.structured_data or {}).get("source_kind") or "").lower()
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Tennessee statutes preferring official TGA/capitol sources.

        Justia TCA mirrors are secondary and cannot authorize full-corpus
        admission unless ``STATE_SCRAPER_TN_ALLOW_JUSTIA_FALLBACK`` is set.
        """
        if self._full_corpus_enabled():
            if max_statutes is not None:
                raise RuntimeError(
                    "Tennessee strict full-corpus route refuses a statute cap"
                )
            self._validate_tennessee_lexis_configuration()
            if (
                str(code_url or "").rstrip("/")
                != self.AUTHORIZED_CODE_ENTRY_URL.rstrip("/")
            ):
                raise RuntimeError(
                    "Tennessee strict full-corpus route requires the exact General "
                    "Assembly-delegated Lexis publisher entry URL"
                )
            ledger = getattr(self, "_state_law_acquisition_ledger", None)
            if ledger is None:
                raise RuntimeError(self.STRICT_FULL_BLOCKER)
            if self._retained_replay_only_enabled():
                return await self._scrape_strict_tennessee_retained_frontier(
                    code_name=code_name or "Tennessee Code Annotated"
                )
            return await self._acquire_tennessee_lexis_frontier(
                code_name=code_name or "Tennessee Code Annotated"
            )

        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .tennessee_constitution import (
            configured_constitution_text_path,
            parse_tennessee_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_tennessee_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Tennessee Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .tennessee_section import (
            configured_section_html_path,
            parse_tennessee_section_html,
        )

        local_section = configured_section_html_path()
        if local_section is not None:
            local_rows = parse_tennessee_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://www.tn.gov/tga/statutes/title-39/chapter-13/section-39-13-202.html",
                code_name=code_name,
                max_statutes=limit,
            )
            if local_rows:
                return local_rows if limit is None else local_rows[: int(limit)]
        allow_justia = self._justia_fallback_allowed()
        # Bounded probes that explicitly target Justia keep that recovery path
        # offline-friendly; full-corpus always prefers official hosts first.
        prefer_official = (not self._is_justia_url(code_url)) or self._full_corpus_enabled()
        merged: List[NormalizedStatute] = []
        seen: Set[str] = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(statute)

        if prefer_official:
            # Official hierarchy first (catalog path: tn.gov / capitol.tn.gov).
            official = await self._scrape_official_tga_tree(
                code_name=code_name,
                code_url=code_url,
                max_statutes=limit,
            )
            _merge(self._filter_official_only(official))
            if limit is not None and len(merged) >= int(limit):
                return merged[: int(limit)]
            if limit is None and merged:
                return merged

            # Bounded probes may use official seed sections.
            if not self._full_corpus_enabled() or max_statutes is not None:
                seed_budget = limit if limit is not None else 2
                direct = await self._scrape_official_seed_sections(
                    code_name,
                    max_statutes=max(1, int(seed_budget)),
                )
                _merge(self._filter_official_only(direct))
                if limit is not None and len(merged) >= int(limit):
                    return merged[: int(limit)]

            if merged and (not self._full_corpus_enabled() or max_statutes is not None):
                return merged[: int(limit)] if limit is not None else merged

        # Secondary Justia is never sole full-corpus admission unless re-enabled.
        if self._full_corpus_enabled() and max_statutes is None and not allow_justia:
            if merged:
                return merged
            self.logger.warning(
                "Tennessee full-corpus run found zero official statutes; "
                "refusing secondary Justia sole-admission fallback"
            )
            return []

        justia_limit = limit
        if self._is_justia_url(code_url) or allow_justia or not self._full_corpus_enabled():
            justia_statutes = await self._scrape_justia_code_tree(
                code_name=code_name,
                max_statutes=justia_limit,
            )
            _merge(justia_statutes)
            if limit is not None and len(merged) >= int(limit):
                return merged[: int(limit)]

        if not merged and not self._full_corpus_enabled():
            legacy = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=max(1, int(limit or 1)),
            )
            _merge(legacy)

        return merged[: int(limit)] if limit is not None else merged

    async def _scrape_official_tga_tree(
        self,
        *,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Walk official Tennessee portal pages for section-level statute rows."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        entry_urls = [
            code_url if self._is_official_host(code_url) else "",
            "https://www.tn.gov/tga/statutes.html",
            "https://www.tn.gov/tga",
            "https://www.capitol.tn.gov/legislation/",
            "https://www.capitol.tn.gov/",
        ]
        queue: List[str] = []
        seen_pages: Set[str] = set()
        for url in entry_urls:
            value = str(url or "").strip()
            if value and value not in seen_pages and self._is_official_host(value):
                queue.append(value)
                seen_pages.add(value)

        section_urls: List[str] = []
        seen_sections: Set[str] = set()
        page_budget = None if limit is None else max(24, int(limit) * 8)
        pages_scanned = 0

        while queue:
            if limit is not None and len(section_urls) >= max(24, int(limit) * 4):
                break
            if page_budget is not None and pages_scanned >= page_budget:
                break
            page_url = queue.pop(0)
            pages_scanned += 1
            payload = await self._fetch_page_content_with_archival_fallback(
                page_url,
                timeout_seconds=30,
            )
            if not payload:
                continue
            html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                if not href or href.startswith("#") or href.lower().startswith("javascript:"):
                    continue
                abs_url = urljoin(page_url, href)
                if not self._is_official_host(abs_url):
                    continue
                canonical = abs_url.split("#", 1)[0]
                label = self._normalize_legal_text(anchor.get_text(" ", strip=True))
                if self._looks_like_section_url(canonical, label):
                    if canonical not in seen_sections:
                        seen_sections.add(canonical)
                        section_urls.append(canonical)
                    continue
                if self._looks_like_index_url(canonical, label) and canonical not in seen_pages:
                    seen_pages.add(canonical)
                    queue.append(canonical)

        out: List[NormalizedStatute] = []
        for index, section_url in enumerate(section_urls, start=1):
            if limit is not None and len(out) >= int(limit):
                break
            statute = await self._build_official_section_statute(
                code_name=code_name,
                section_url=section_url,
                fallback_number=str(index),
            )
            if statute is not None:
                out.append(statute)
        return out

    def _looks_like_section_url(self, url: str, label: str = "") -> bool:
        value = str(url or "").lower()
        if self._TN_OFFICIAL_SECTION_RE.search(value):
            return True
        if self._TN_SECTION_LABEL_RE.search(label or "") and any(
            token in value for token in ("/statute", "/section", "/tca/", "code")
        ):
            return True
        return bool(re.search(r"section[/_-][0-9]+-[0-9]+", value))

    def _looks_like_index_url(self, url: str, label: str = "") -> bool:
        value = str(url or "").lower()
        label_l = str(label or "").lower()
        if any(token in value for token in ("/tga", "/statute", "/tca", "/code", "/title", "/chapter", "/legislation")):
            return True
        return any(token in label_l for token in ("title", "chapter", "statute", "code", "tca"))

    async def _build_official_section_statute(
        self,
        *,
        code_name: str,
        section_url: str,
        fallback_number: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        payload = await self._fetch_page_content_with_archival_fallback(
            section_url,
            timeout_seconds=30,
        )
        if not payload:
            return None
        html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        soup = BeautifulSoup(html, "html.parser")
        content = (
            soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one("#content")
            or soup.find("body")
            or soup
        )
        text = self._normalize_legal_text(content.get_text(" ", strip=True))
        if len(text) < 220:
            return None

        section_number = ""
        section_match = self._TN_OFFICIAL_SECTION_RE.search(section_url)
        if section_match:
            section_number = section_match.group(1)
        if not section_number:
            label_match = self._TN_SECTION_LABEL_RE.search(text[:400])
            if label_match:
                section_number = label_match.group(1)
        if not section_number:
            section_number = str(fallback_number)

        heading = soup.find(["h1", "h2", "h3"])
        section_name = self._normalize_legal_text(heading.get_text(" ", strip=True) if heading else "")
        if not section_name:
            section_name = f"Section {section_number}"
        title_number = section_number.split("-", 1)[0] if "-" in section_number else None

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=title_number,
            section_number=section_number,
            section_name=section_name[:200],
            full_text=text,
            legal_area=self._identify_legal_area(text[:1200]),
            source_url=section_url,
            official_cite=f"Tenn. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_tennessee_code_html",
                "discovery_method": "official_tga_capitol_hierarchy",
                "skip_hydrate": True,
            },
        )

    async def _scrape_official_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        seeds = [
            (
                "1-1-101",
                "Designation and citation",
                "https://www.tn.gov/tga/statutes/title-1/chapter-1/section-1-1-101.html",
            ),
            (
                "1-1-102",
                "Construction of code",
                "https://www.tn.gov/tga/statutes/title-1/chapter-1/section-1-1-102.html",
            ),
            (
                "39-13-202",
                "First degree murder",
                "https://www.capitol.tn.gov/legislation/statutes/title-39/chapter-13/section-39-13-202.html",
            ),
        ]
        out: List[NormalizedStatute] = []
        for section_number, section_name, source_url in seeds[: max(1, int(max_statutes or 1))]:
            statute = await self._build_official_section_statute(
                code_name=code_name,
                section_url=source_url,
                fallback_number=section_number,
            )
            if statute is None:
                # Offline/bounded fixtures may supply page HTML without live body
                # extraction succeeding; still admit labeled official seeds only
                # when the page fetch returns substantive text via generic path.
                payload = await self._fetch_page_content_with_archival_fallback(
                    source_url,
                    timeout_seconds=25,
                )
                if not payload:
                    continue
                text = self._normalize_legal_text(
                    payload.decode("utf-8", errors="replace")
                    if isinstance(payload, bytes)
                    else str(payload)
                )
                text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
                text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
                text = re.sub(r"(?is)<[^>]+>", " ", text)
                text = self._normalize_legal_text(text)
                if len(text) < 220:
                    continue
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name,
                    full_text=text,
                    legal_area=self._identify_legal_area(text[:1200]),
                    source_url=source_url,
                    official_cite=f"Tenn. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_tennessee_code_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            else:
                # Prefer known seed metadata when the page body is present.
                statute.section_number = section_number
                statute.section_name = section_name
                statute.statute_id = f"{code_name} § {section_number}"
                statute.official_cite = f"Tenn. Code Ann. § {section_number}"
                if statute.structured_data is None:
                    statute.structured_data = {}
                statute.structured_data["discovery_method"] = "official_seed_section"
            out.append(statute)
        return out

    async def _scrape_justia_code_tree(
        self,
        *,
        code_name: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = "https://law.justia.com/codes/tennessee/"
        payload = await self._fetch_justia_listing_html(index_url, timeout_seconds=30)
        if not payload:
            payload = await self._fetch_justia_listing_html(
                "https://law.justia.com/codes/tennessee/2024/",
                timeout_seconds=30,
            )
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        candidate_indexes = ["https://law.justia.com/codes/tennessee/2024/"]
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not self._TN_JUSTIA_VERSION_RE.search(href):
                continue
            if href not in candidate_indexes:
                candidate_indexes.append(href)

        title_urls: List[str] = []
        seen_titles = set()
        title_limit = None if max_statutes is None else max(1, int(max_statutes))
        for title_index_url in candidate_indexes:
            title_payload = await self._fetch_justia_listing_html(title_index_url, timeout_seconds=30)
            if not title_payload:
                continue
            title_soup = BeautifulSoup(title_payload, "html.parser")
            for anchor in title_soup.find_all("a", href=True):
                href = urljoin(title_index_url, str(anchor.get("href") or "").strip())
                if not self._TN_JUSTIA_TITLE_RE.search(href):
                    continue
                canonical = self._canonicalize_tn_justia_url(href)
                if canonical in seen_titles:
                    continue
                seen_titles.add(canonical)
                title_urls.append(canonical)
                if title_limit is not None and len(title_urls) >= title_limit:
                    break
            if title_urls:
                break

        self.logger.info("Tennessee Justia: discovered_titles=%d", len(title_urls))
        if not title_urls:
            return []

        section_url_limit = None if max_statutes is None else max(24, int(max_statutes) * 5)
        intermediate_limit = None if max_statutes is None else max(16, int(max_statutes) * 3)
        section_urls: List[str] = []
        intermediate_urls: List[str] = []
        seen_sections = set()
        seen_intermediate = set()
        heartbeat_seconds = max(15.0, float(self._env_int("STATE_SCRAPER_HEARTBEAT_SECONDS", default=60)))
        last_heartbeat = time.monotonic()

        for title_url in title_urls:
            title_payload = await self._fetch_justia_listing_html(title_url, timeout_seconds=30)
            if not title_payload:
                continue
            title_soup = BeautifulSoup(title_payload, "html.parser")
            for anchor in title_soup.find_all("a", href=True):
                href = urljoin(title_url, str(anchor.get("href") or "").strip())
                canonical = self._canonicalize_tn_justia_url(href)
                if self._TN_JUSTIA_SECTION_RE.search(canonical):
                    if canonical not in seen_sections:
                        seen_sections.add(canonical)
                        section_urls.append(canonical)
                elif self._TN_JUSTIA_INTERMEDIATE_RE.search(canonical) and canonical != title_url:
                    if canonical not in seen_intermediate:
                        seen_intermediate.add(canonical)
                        intermediate_urls.append(canonical)
                if section_url_limit is not None and len(section_urls) >= section_url_limit:
                    break
                if intermediate_limit is not None and len(intermediate_urls) >= intermediate_limit:
                    break
            if section_url_limit is not None and len(section_urls) >= section_url_limit:
                break
            if intermediate_limit is not None and len(intermediate_urls) >= intermediate_limit:
                break

        self.logger.info(
            "Tennessee Justia: discovered_direct_sections=%d intermediate_pages=%d",
            len(section_urls),
            len(intermediate_urls),
        )

        pages_to_scan = intermediate_urls if intermediate_limit is None else intermediate_urls[:intermediate_limit]
        for idx, page_url in enumerate(pages_to_scan, start=1):
            page_payload = await self._fetch_justia_listing_html(page_url, timeout_seconds=30)
            if not page_payload:
                continue
            page_soup = BeautifulSoup(page_payload, "html.parser")
            for anchor in page_soup.find_all("a", href=True):
                href = urljoin(page_url, str(anchor.get("href") or "").strip())
                canonical = self._canonicalize_tn_justia_url(href)
                if not self._TN_JUSTIA_SECTION_RE.search(canonical):
                    continue
                if canonical in seen_sections:
                    continue
                seen_sections.add(canonical)
                section_urls.append(canonical)
                if section_url_limit is not None and len(section_urls) >= section_url_limit:
                    break
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                self.logger.info(
                    "Tennessee Justia: scanned_intermediate=%d/%d section_urls=%d",
                    idx,
                    len(pages_to_scan),
                    len(section_urls),
                )
                last_heartbeat = now
            if section_url_limit is not None and len(section_urls) >= section_url_limit:
                break

        self.logger.info("Tennessee Justia: total_section_urls=%d", len(section_urls))
        if not section_urls:
            return []

        sem = asyncio.Semaphore(4)

        async def _fetch_one(section_url: str, index: int) -> NormalizedStatute | None:
            async with sem:
                return await self._build_justia_statute(
                    code_name=code_name,
                    section_url=section_url,
                    fallback_number=str(index),
                )

        out: List[NormalizedStatute] = []
        urls_to_fetch = section_urls if max_statutes is None else section_urls[: max(24, int(max_statutes) * 4)]
        batch_size = 24
        last_heartbeat = time.monotonic()
        for offset in range(0, len(urls_to_fetch), batch_size):
            batch = urls_to_fetch[offset : offset + batch_size]
            jobs = [_fetch_one(section_url, offset + idx) for idx, section_url in enumerate(batch, start=1)]
            for result in await asyncio.gather(*jobs, return_exceptions=True):
                if isinstance(result, Exception) or result is None:
                    continue
                out.append(result)
                if max_statutes is not None and len(out) >= max_statutes:
                    return out[:max_statutes]
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                self.logger.info(
                    "Tennessee Justia: fetched_sections=%d/%d statutes=%d",
                    min(offset + len(batch), len(urls_to_fetch)),
                    len(urls_to_fetch),
                    len(out),
                )
                last_heartbeat = now

        return out[:max_statutes] if max_statutes is not None else out

    async def _custom_scrape_tennessee(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 280,
    ) -> List[NormalizedStatute]:
        """Compatibility fallback used by older tests and recovery paths."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(code_url, timeout_seconds=45)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        statutes: List[NormalizedStatute] = []
        seen = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            label = self._normalize_legal_text(anchor.get_text(" ", strip=True))
            if not href or not label:
                continue
            full_url = urljoin(code_url, href)
            section_number = self._extract_section_number(label)
            if not section_number:
                section_number = f"TN-{len(statutes) + 1}"
            key = f"{section_number}|{full_url}".lower()
            if key in seen:
                continue
            seen.add(key)
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=label[:200],
                    full_text=f"Section {section_number}: {label}",
                    legal_area=self._identify_legal_area(label),
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "tennessee_compatibility_link_listing",
                        "discovery_method": "archival_link_listing",
                    },
                )
            )
            if len(statutes) >= max_sections:
                break
        return statutes

    async def _fetch_justia_listing_html(self, url: str, timeout_seconds: int = 30) -> bytes:
        timeout = max(5, int(timeout_seconds or 30))
        payload = await self._fetch_non_authoritative_reference_bytes(
            url,
            timeout_seconds=timeout,
            content_validator=lambda body: bool(body)
            and self._TN_CLOUDFLARE_CHALLENGE_RE.search(
                body[:12000].decode("utf-8", errors="ignore")
            )
            is None,
            enable_common_crawl=True,
        )
        self._record_fetch_event(
            provider="shared_secondary_tennessee_recovery",
            success=bool(payload),
        )
        if payload:
            await self._cache_successful_page_fetch(
                url=url,
                payload=payload,
                provider="shared_secondary_tennessee_recovery",
            )
        return payload

    async def _fetch_justia_section_markdown(self, url: str, timeout_seconds: int = 25) -> str:
        reader_url = f"https://r.jina.ai/http://{url}"
        timeout = max(5, int(timeout_seconds or 25))
        payload = await self._fetch_non_authoritative_reference_bytes(
            reader_url,
            timeout_seconds=timeout,
            enable_common_crawl=False,
        )
        return payload.decode("utf-8", errors="replace") if payload else ""

    async def _build_justia_statute(
        self,
        *,
        code_name: str,
        section_url: str,
        fallback_number: str,
    ) -> NormalizedStatute | None:
        markdown = await self._fetch_justia_section_markdown(section_url, timeout_seconds=25)
        if not markdown:
            return None

        match = self._TN_SECTION_NUMBER_RE.search(section_url)
        section_number = match.group(1) if match else fallback_number
        section_name = self._extract_justia_section_name(markdown, section_number)
        body = self._extract_justia_reader_section(markdown, section_number)
        if len(body) < 220:
            return None

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=section_number.split("-", 1)[0],
            section_number=section_number,
            section_name=section_name[:200],
            full_text=body,
            legal_area=self._identify_legal_area(body[:1200]),
            source_url=section_url,
            official_cite=f"Tenn. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "jina_reader_justia_tennessee_code",
                "discovery_method": "justia_tennessee_code_tree",
                "reader_url": f"https://r.jina.ai/http://{section_url}",
                "skip_hydrate": True,
            },
        )

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 1,
    ) -> List[NormalizedStatute]:
        seeds = [
            (
                "39-13-202",
                "First degree murder",
                "https://law.justia.com/codes/tennessee/title-39/chapter-13/part-2/section-39-13-202/",
            ),
        ]
        out: List[NormalizedStatute] = []
        for section_number, section_name, source_url in seeds[: max(1, int(max_statutes or 1))]:
            markdown = await self._fetch_justia_section_markdown(source_url, timeout_seconds=25)
            if not markdown:
                continue
            body = self._extract_justia_reader_section(markdown, section_number)
            if len(body) < 220:
                continue
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name,
                    full_text=body,
                    legal_area=self._identify_legal_area(body[:1200]),
                    source_url=source_url,
                    official_cite=f"Tenn. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "jina_reader_justia_tennessee_code",
                        "discovery_method": "cloudflare_block_recovery_seed_section",
                        "reader_url": f"https://r.jina.ai/http://{source_url}",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def _canonicalize_tn_justia_url(self, url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return value
        value = re.sub(r"/codes/tennessee/\d{4}/", "/codes/tennessee/", value, flags=re.IGNORECASE)
        if value.endswith("/") and "section-" not in value:
            return value
        return value.rstrip("/") + "/"

    def _extract_justia_section_name(self, markdown: str, section_number: str) -> str:
        text = str(markdown or "")
        patterns = [
            rf"#\s*Tennessee Code §\s*{re.escape(section_number)}\s*\(\d{{4}}\)\s*-\s*(.+?)\s*::",
            rf"Section\s+{re.escape(section_number)}\s*-\s*(.+)",
            rf"TN Code §\s*{re.escape(section_number)}\s*\(\d{{4}}\)\s*-\s*(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return self._normalize_legal_text(match.group(1))[:200]
        return f"Section {section_number}"

    def _extract_justia_reader_section(self, markdown: str, section_number: str) -> str:
        text = str(markdown or "")
        start = text.find(f"Section {section_number}")
        cite_start = text.find(f"TN Code § {section_number}")
        if cite_start >= 0:
            start = cite_start
        if start < 0:
            start = text.find(f"§ {section_number}")
        if start < 0:
            return ""
        tail = text[start:]
        end_markers = ["Disclaimer:", "Justia Free Databases", "Newsletter", "Want to receive"]
        end = len(tail)
        for marker in end_markers:
            idx = tail.find(marker)
            if idx >= 0:
                end = min(end, idx)
        body = tail[:end]
        body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
        body = re.sub(r"\*\*([^*]+)\*\*", r"\1", body)
        return self._normalize_legal_text(body)

    def official_title_url(self, title_number: Any) -> str:
        number = str(int(str(title_number).strip()))
        return f"https://www.tn.gov/tga/statutes/title-{number}/"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Tennessee Code Annotated title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"tn:title-{int(number)}",
                    "title_number": str(int(number)),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Tennessee Code Annotated Title {int(number)} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-tennessee-official-catalog/1.0",
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

    def normalize_title_number(self, value: Any) -> str:
        text = str(value or "").strip()
        match = re.search(r"0*(\d{1,2})", text)
        if not match:
            return ""
        number = str(int(match.group(1)))
        known = {str(int(item)) for item, _name in self.OFFICIAL_TITLES}
        return number if number in known else ""

    def _recover_title_number(self, *parts: Any) -> str:
        for part in parts:
            text = str(part or "").strip()
            if not text:
                continue
            href_match = self._TN_TITLE_HREF_RE.search(text)
            if href_match:
                number = self.normalize_title_number(href_match.group("title"))
                if number:
                    return number
            label_match = self._TN_TITLE_LABEL_RE.search(text)
            if label_match:
                number = self.normalize_title_number(label_match.group("title"))
                if number:
                    return number
            cite_match = self._TN_SECTION_CITE_RE.search(text)
            if cite_match:
                number = self.normalize_title_number(cite_match.group("title"))
                if number:
                    return number
        return ""

    def _title_row(
        self,
        title_number: str,
        label: str,
        source: str,
        source_url: str = "",
    ) -> Dict[str, str]:
        official_url = source_url or self.official_title_url(title_number)
        cleaned = re.sub(r"\s+", " ", str(label or "")).strip() or f"Title {title_number}"
        return {
            "canonical_key": f"tn:title-{int(title_number)}",
            "title_number": str(int(title_number)),
            "name": cleaned,
            "source_url": official_url,
            "source_link_disposition": source,
            "repair_source": source,
            "text": (
                f"Tennessee Code Annotated {cleaned} official title catalog unit "
                f"at {official_url}"
            ),
        }

    def classify_linkless_seed_rows(
        self,
        seeds: object,
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, str]]]:
        """Reacquire official TCA titles or quarantine remaining linkless seeds.

        Recoverable title numbers are rewritten to official tn.gov URLs.
        Remaining linkless material is quarantined with
        ``missing_official_source_link``.
        """

        repaired: List[Dict[str, str]] = []
        quarantines: List[Dict[str, str]] = []
        seen_titles: set[str] = set()
        seen_quarantine: set[str] = set()

        def _record(title_number: str, label: str, source: str, source_url: str = "") -> None:
            number = self.normalize_title_number(title_number)
            if not number or number in seen_titles:
                return
            seen_titles.add(number)
            repaired.append(self._title_row(number, label, source, source_url=source_url))

        def _quarantine(label: str, evidence: str) -> None:
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
            if not cleaned:
                return
            unit_id = (
                "tn:missing-"
                + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            )
            if unit_id in seen_quarantine:
                return
            seen_quarantine.add(unit_id)
            quarantines.append(
                {
                    "unit_id": unit_id,
                    "reason": self.LINKLESS_QUARANTINE_REASON,
                    "label": cleaned[:240],
                    "page_url": page_url or self.OFFICIAL_ENTRY_URL,
                    "evidence_sha256": hashlib.sha256(
                        str(evidence or cleaned).encode("utf-8")
                    ).hexdigest(),
                }
            )

        if isinstance(seeds, (bytes, bytearray, str)):
            html = (
                seeds.decode("utf-8", errors="replace")
                if isinstance(seeds, (bytes, bytearray))
                else seeds
            )
            if not str(html or "").strip():
                return {"repaired": repaired, "quarantines": quarantines}
            try:
                from bs4 import BeautifulSoup
            except ImportError:
                return {"repaired": repaired, "quarantines": quarantines}
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
                absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
                title_number = self._recover_title_number(absolute, href, label)
                if title_number and self._is_official_host(absolute):
                    _record(title_number, label, "official", self.official_title_url(title_number))
                    continue
                if title_number:
                    _record(title_number, label, "repaired_from_linkless_row")
                    continue
                if label:
                    _quarantine(label, str(link))
            for node in soup.find_all(["span", "td", "li", "div", "p"]):
                if node.find("a", href=True):
                    continue
                label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
                if not label:
                    continue
                title_number = self._recover_title_number(
                    node.get("href"),
                    node.get("data-title"),
                    node.get("id"),
                    label,
                    str(node),
                )
                if title_number:
                    _record(title_number, label, "repaired_from_linkless_row")
                elif re.search(
                    r"title|statute|chapter|section|tennessee|tca|phantom|appendix|bucket|legacy",
                    label,
                    re.IGNORECASE,
                ):
                    _quarantine(label, str(node))
            return {"repaired": repaired, "quarantines": quarantines}

        for item in seeds or ():
            if not isinstance(item, Mapping):
                continue
            label = str(
                item.get("label")
                or item.get("name")
                or item.get("text")
                or item.get("statute_id")
                or item.get("section_name")
                or ""
            ).strip()
            source_url = str(item.get("source_url") or item.get("href") or "").strip()
            title_number = self._recover_title_number(
                item.get("title_number"),
                item.get("section_number"),
                item.get("statute_id"),
                source_url,
                label,
            )
            if title_number and source_url and self._is_official_host(source_url):
                _record(title_number, label, "official", self.official_title_url(title_number))
                continue
            if title_number:
                _record(title_number, label, "repaired_from_linkless_row")
                continue
            _quarantine(
                label or source_url or "linkless tennessee seed",
                json.dumps(dict(item), sort_keys=True),
            )
        return {"repaired": repaired, "quarantines": quarantines}

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate official TCA titles and reacquire or quarantine linkless seeds."""

        discovered = self._parse_official_title_links(html)
        classified = self.classify_linkless_seed_rows(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        seed_classified = self.classify_linkless_seed_rows(
            list(seed_rows) if seed_rows is not None else list(self.DEFAULT_LINKLESS_SEED_ROWS),
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        classified["repaired"].extend(seed_classified["repaired"])
        classified["quarantines"].extend(seed_classified["quarantines"])
        self.last_official_quarantines = list(classified["quarantines"])

        rows = self.official_title_catalog()
        by_title = {str(row["title_number"]): row for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        for unit in classified["repaired"]:
            number = str(unit.get("title_number") or "")
            if number in by_title:
                if unit.get("source_link_disposition") == "official":
                    by_title[number]["source_url"] = unit["source_url"]
                    by_title[number]["source_link_disposition"] = "official"
                elif by_title[number].get("source_link_disposition") != "official":
                    by_title[number]["source_link_disposition"] = str(
                        unit.get("source_link_disposition") or "repaired_from_linkless_row"
                    )
                continue
            rows.append(unit)
            by_title[number] = unit
        rows.sort(key=lambda item: int(str(item.get("title_number") or "0") or 0))
        return rows

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {str(int(number)) for number, _name in self.OFFICIAL_TITLES}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            number = self._recover_title_number(absolute, href, label)
            if not number or number not in known or number in found:
                continue
            if self._is_official_host(absolute):
                found[number] = self.official_title_url(number)
        return found

    def fetch_official(self, code: str = "TN"):
        """Acquire the exhaustive official Tennessee Code Annotated catalog.

        Linkless bucket seed material is independently reacquired onto
        official tn.gov title URLs when a title number can be recovered.
        Remaining linkless rows are quarantined with typed
        ``missing_official_source_link`` disposition. This hook never
        returns fixture bytes or secondary-mirror hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "TN").strip().upper() or "TN"
        if normalized != "TN":
            raise ValueError(f"TennesseeScraper cannot acquire {normalized}")
        self.last_official_quarantines = []
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        if self._full_corpus_enabled():
            discovered = self._parse_official_title_links(html)
            expected = [str(int(number)) for number, _name in self.OFFICIAL_TITLES]
            if list(discovered) != expected or list(discovered.values()) != [
                self.official_title_url(number) for number in expected
            ]:
                missing = sorted(set(expected).difference(discovered), key=int)
                unexpected = sorted(set(discovered).difference(expected), key=int)
                raise RuntimeError(
                    "tennessee official entry did not prove the exact 71-title "
                    f"catalog; missing={missing} unexpected={unexpected}"
                )
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        quarantines = list(getattr(self, "last_official_quarantines", []) or [])
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "tennessee official catalog enumeration rejected incomplete "
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
            "quarantines": quarantines,
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
            "tn_linkless_seed_quarantines": quarantines,
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


StateScraperRegistry.register("TN", TennesseeScraper)
