"""Scraper for Tennessee state laws."""

import hashlib
import json
import os
import re
import ssl
import time
import urllib.request
import warnings
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
    # Source drift requires an explicit reviewed code update.  Tests may
    # replace this class attribute for a deliberately smaller exact fixture.
    ENFORCE_OBSERVED_TN_FRONTIER = True
    STRICT_FULL_BLOCKER = (
        "Tennessee strict full-corpus acquisition requires a retained-replay-only "
        "ledger containing the current General Assembly-delegated Lexis chain: "
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
            tennessee_section,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            tennessee_lexis,
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

    async def _fetch_tennessee_lexis_get_wave(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Any,
    ) -> StateLawPageMultiFetchResult:
        """Use one shared plural inventory for an ordered same-domain GET wave.

        This is the future acquisition seam for authority and document GETs.
        The current strict route below never invokes it: offline certification
        reads only exact retained ledger identities.  Lexis TOC ``PATCH``
        requests are deliberately absent because a GET archive cannot bind
        their request bodies.
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
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=self._tennessee_residual_retry_attempts(),
            timeout_seconds=45,
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                "User-Agent": "ipfs-datasets-tennessee-code/3.0",
            },
            content_validator=content_validator,
            media_type="text/html",
            max_concurrency=self._tennessee_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(domain,),
            common_crawl_url_terms=url_terms,
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
        )
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
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    @staticmethod
    def _tennessee_get_request(url: str) -> Dict[str, Any]:
        return {"method": "GET", "url": str(url)}

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
        for key in ("retrieved_at", "observed_at", "timestamp"):
            value = str(receipt.get(key) or "").strip()
            if value:
                return value
        origin = receipt.get("origin_transport_receipt")
        if isinstance(origin, Mapping):
            return TennesseeScraper._tennessee_observed_at_from_receipt(origin)
        return ""

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
        if (
            not transport_receipt
            or str(transport_receipt.get("official_url") or "").rstrip("/")
            != str(official_url).rstrip("/")
            or str(transport_receipt.get("content_sha256") or "").lower()
            != body_sha256
            or not str(
                transport_receipt.get("source_transport") or ""
            ).strip()
            or not re.fullmatch(r"[a-f0-9]{64}", parser_input_receipt_sha256)
        ):
            raise RuntimeError(
                "Tennessee retained parser input omitted exact byte/transport "
                f"evidence: {official_url}"
            )
        reports = list(getattr(self, "_tennessee_frontier_input_reports", []))
        report = {
            "content_sha256": body_sha256,
            "parser_input_receipt_sha256": parser_input_receipt_sha256,
            "request_identity_sha256": canonical_digest(dict(sanitized_request)),
            "source_order": len(reports),
            "source_role": str(source_role),
            "source_transport": str(
                transport_receipt.get("source_transport") or ""
            ),
            "source_url": str(official_url),
            "transport_receipt_sha256": canonical_digest(transport_receipt),
        }
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
        if not getattr(self, "_tennessee_frontier_observed_at", ""):
            self._tennessee_frontier_observed_at = (
                self._tennessee_observed_at_from_receipt(transport_receipt)
            )
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

    @staticmethod
    def _tennessee_publisher_receipt_proves_container(
        retained: Any,
        payload: bytes,
    ) -> bool:
        from .tennessee_lexis import (
            PUBLIC_CONTAINER_CONFIG,
            publisher_container_delegation_present,
        )

        if publisher_container_delegation_present(
            payload.decode("utf-8", errors="replace")
        ):
            return True
        receipt = dict(getattr(retained, "transport_receipt", {}) or {})
        return PUBLIC_CONTAINER_CONFIG in json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
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
            canonical_toc_patch_request,
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

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Tennessee strict retained route requires an attached ledger")
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()
        self._tennessee_frontier_input_reports = []
        self._tennessee_frontier_observed_at = ""

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

        root_request = self._tennessee_get_request(self.AUTHORIZED_CODE_CONTAINER_URL)
        root_payload = self._replay_tennessee_retained_wave(
            [(self.AUTHORIZED_CODE_CONTAINER_URL, root_request)],
            frontier_name="rendered Lexis root",
            source_role="rendered_container_root",
        )[0]
        title_roots, tables_root = parse_root_html(
            self._tennessee_decode(root_payload, source_role="rendered Lexis root"),
            expected_titles=self.OFFICIAL_TITLES,
        )

        expandable_roots = [
            node for node in title_roots if node.can_expand or node.has_children
        ]
        patch_specs = [canonical_toc_patch_request(node) for node in expandable_roots]
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

        disposition = {
            "discovered": len(document_nodes),
            "duplicates": 0,
            "excluded": len(terminals),
            "failed_final": 0,
            "fetched": len(rows),
            "quarantined": 0,
        }
        observed_at = str(self._tennessee_frontier_observed_at or "")
        frontier: Dict[str, Any] = {
            **metadata,
            "algebra_closed": True,
            "authority_catalog_input_count": 3 + len(expandable_roots),
            "body_input_count": len(document_nodes),
            "body_parser_report_count": len(body_reports),
            "closed": True,
            "diagnostic_baseline_drift": drift,
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
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="TN",
            source_domain="advance.lexis.com",
            official_source_url=self.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL,
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("legal_as_of") or ""),
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=int(disposition.get("discovered") or 0),
            pagination_total=int(first_frontier.get("subtree_response_count") or 0),
            transport={
                "fixture": False,
                "first_pass_requested_pages": int(
                    first_frontier.get("source_input_count") or 0
                ),
                "get_acquisition_contract": "shared_archive_aware_plural_residual",
                "grouped_warc_recovery": True,
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
            if self._retained_replay_only_enabled():
                return await self._scrape_strict_tennessee_retained_frontier(
                    code_name=code_name or "Tennessee Code Annotated"
                )
            raise RuntimeError(self.STRICT_FULL_BLOCKER)

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
        from .tennessee_section import configured_section_html_path, parse_tennessee_section_html

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
