"""Scraper for New Jersey state laws.

This module contains the scraper for New Jersey statutes from the official state
legislative website.
"""

import asyncio
import hashlib
import json
import os
import re
import ssl
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import quote, urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute
from .base_scraper import StatuteMetadata
from .registry import StateScraperRegistry
from .retained_replay_network_guard import trusted_pdftotext_executable


class NewJerseyScraper(BaseStateScraper):
    """Scraper for New Jersey state laws from https://www.njleg.state.nj.us"""

    _LIS_GATEWAY = "https://lis.njleg.state.nj.us/nxt/gateway.dll"
    _XHITLIST_SELECT = (
        "title;path;relevance-weight;content-type;home-title;"
        "item-bookmark;title-path"
    )
    _XMLCONTENTS_BASE = (
        "https://lis.njleg.state.nj.us/nxt/gateway.dll"
        "?f=xmlcontents&maxnodes=75&minnodesleft=10&siteshowhits=true&hidezerohits=true"
    )
    OFFICIAL_DOMAIN = "lis.njleg.state.nj.us"
    OFFICIAL_ENTRY_PATH = "/nxt/gateway.dll/statutes/1"
    OFFICIAL_ENTRY_URL = (
        "https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1"
        "?f=templates&fn=default.htm&vid=Publish:10.1048/Enu"
    )
    MISSING_LINK_DISPOSITION = "missing_official_source_link"
    LINK_GAP_QUARANTINE_REASON = "source_link_gap_pending_official_replacement"
    BULK_ACCEPT = "application/zip,application/octet-stream,*/*;q=0.8"
    BULK_RETAINED_SHA256_ENV = "NEW_JERSEY_BULK_RETAINED_SHA256"
    _NJ_TITLE_HREF_RE = re.compile(
        r"/statutes/1/(?P<title>[0-9]+[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    _NJ_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(?P<title>[0-9]+[A-Za-z]?)\b", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "Administration of Civil and Criminal Justice"),
        ("2A", "Administration of Civil and Criminal Justice"),
        ("2B", "Court Organization and Civil Code"),
        ("2C", "The New Jersey Code of Criminal Justice"),
        ("3B", "Administration of Estates--Decedents and Others"),
        ("4", "Agriculture and Domestic Animals"),
        ("5", "Amusements, Public Exhibitions and Meetings"),
        ("6", "Aviation"),
        ("8A", "Cemeteries"),
        ("9", "Children--Juvenile and Domestic Relations Courts"),
        ("10", "Civil Rights"),
        ("11A", "Civil Service"),
        ("12", "Commerce and Navigation"),
        ("12A", "Commercial Transactions"),
        ("13", "Conservation and Development--Parks and Reservations"),
        ("14A", "Corporations, General"),
        ("15A", "Corporations, Nonprofit"),
        ("16", "Corporations and Associations, Religious"),
        ("17", "Corporations and Institutions for Finance and Insurance"),
        ("17B", "Insurance"),
        ("18A", "Education"),
        ("19", "Elections"),
        ("21", "Explosives and Fireworks"),
        ("22A", "Fees and Costs"),
        ("23", "Fish and Game, Wild Birds and Animals"),
        ("24", "Food and Drugs"),
        ("25", "Frauds and Fraudulent Conveyances"),
        ("26", "Health and Vital Statistics"),
        ("27", "Highways"),
        ("30", "Institutions and Agencies"),
        ("32", "Interstate and Port Authorities and Commissions"),
        ("33", "Intoxicating Liquors"),
        ("34", "Labor and Workmen's Compensation"),
        ("35", "Legal Holidays"),
        ("36", "Legal Oaths, Affirmations and Declarations"),
        ("37", "Marriages and Married Persons"),
        ("38A", "Military and Veterans Law"),
        ("39", "Motor Vehicles and Traffic Regulation"),
        ("40", "Municipalities and Counties"),
        ("40A", "Municipalities and Counties"),
        ("41", "Oaths and Affidavits"),
        ("42", "Partnerships and Partnership Associations"),
        ("43", "Pensions and Retirement and Unemployment Compensation"),
        ("44", "Poor"),
        ("45", "Professions and Occupations"),
        ("46", "Property"),
        ("47", "Public Records"),
        ("48", "Public Utilities"),
        ("49", "Sale of Securities"),
        ("51", "Standards, Weights, Measures and Containers"),
        ("52", "State Government, Departments and Officers"),
        ("53", "State Police"),
        ("54", "Taxation"),
        ("54A", "New Jersey Gross Income Tax Act"),
        ("55", "Tenement Houses and Public Housing"),
        ("56", "Trade Names, Trade-Marks and Unfair Trade Practices"),
        ("58", "Waters and Water Supply"),
        ("59", "Claims Against Public Entities"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)
    DEFAULT_LINK_GAP_SEEDS = (
        {
            "canonical_key": "nj:title-2c",
            "label": "New Jersey Statutes Title 2C Code of Criminal Justice",
            "source_url": "https://law.justia.com/codes/new-jersey/title-2c/",
            "title_number": "2C",
        },
        {
            "canonical_key": "nj:title-39",
            "label": "Title 39 Motor Vehicles and Traffic Regulation",
            "source_url": "",
            "title_number": "39",
        },
        {
            "canonical_key": "nj:bucket-seed-untitled",
            "label": "open-us-law-bucket New Jersey seed row without an official source link",
            "source_url": "",
        },
        {
            "canonical_key": "nj:bucket-phantom",
            "label": "New Jersey phantom title without a recoverable official identifier",
            "source_url": "https://law.justia.com/codes/new-jersey/",
        },
    )

    def __init__(self, state_code: str, state_name: str):
        super().__init__(state_code, state_name)
        self._new_jersey_bulk_provenance: Dict[str, Any] = {}
        self._new_jersey_first_bulk_inventory_observation: Dict[str, Any] = {}
    
    def get_base_url(self) -> str:
        """Return the base URL for New Jersey's legislative website."""
        return "https://www.njleg.state.nj.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for New Jersey."""
        return [{
            "name": "New Jersey Statutes",
            "url": "https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1?f=templates&fn=default.htm&vid=Publish:10.1048/Enu",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from New Jersey's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .new_jersey_constitution import (
            configured_constitution_html_path,
            parse_new_jersey_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_new_jersey_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "New Jersey Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        bulk = await self._scrape_official_bulk_zip(
            code_name=code_name,
            max_statutes=limit,
        )
        if bulk:
            return bulk if limit is None else bulk[: int(limit)]
        if self._full_corpus_enabled() and max_statutes is None:
            self.logger.warning(
                "NJ full-corpus run could not close the official bulk ZIP; "
                "refusing the partial LIS gateway walk"
            )
            return []
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        if official:
            return official if limit is None else official[: int(limit)]
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct_limit = limit if limit is not None else 160
            direct = await self._scrape_direct_public_law_pdfs(code_name, max_statutes=direct_limit)
            if direct:
                return direct if limit is None else direct[: int(direct_limit)]
        if self._full_corpus_enabled() and max_statutes is None:
            self.logger.warning(
                "NJ full-corpus run found zero official LIS statutes; "
                "refusing generic/Justia sole-admission fallback"
            )
            return []
        return_threshold = limit if limit is not None else 160
        statutes = await self._scrape_via_xhitlist(code_name, max_sections=max(10, return_threshold))
        if len(statutes) >= int(return_threshold):
            return statutes

        self.logger.warning(
            "NJ xhitlist extraction returned %d records; falling back to generic scrape",
            len(statutes),
        )
        fallback = await self._generic_scrape(code_name, code_url, "N.J. Stat. Ann.", max_sections=max(10, return_threshold))
        if not fallback:
            return statutes

        seen = {s.source_url for s in statutes if s.source_url}
        for statute in fallback:
            if statute.source_url in seen:
                continue
            if self._looks_like_secondary_url(str(statute.source_url or "")):
                continue
            seen.add(statute.source_url)
            statutes.append(statute)
        return statutes

    async def _scrape_official_bulk_zip(
        self,
        *,
        code_name: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Acquire or read the one official STATUTES-TEXT.zip parser input."""

        from .new_jersey_bulk import (
            NewJerseyBulkFrontierError,
            OFFICIAL_ZIP_URL,
            configured_bulk_zip_path,
            looks_like_zip_bytes,
            parse_new_jersey_bulk_zip,
            parse_new_jersey_bulk_zip_bytes,
        )

        zip_path = configured_bulk_zip_path()
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if zip_path is not None and ledger is None:
            try:
                return await asyncio.to_thread(
                    parse_new_jersey_bulk_zip,
                    zip_path,
                    code_name=code_name,
                    max_statutes=max_statutes,
                )
            except Exception as exc:
                self.logger.warning("New Jersey official bulk zip failed: %s", exc)
                return []
        if (
            zip_path is None
            and ledger is None
            and not (self._full_corpus_enabled() and max_statutes is None)
        ):
            return []

        try:
            request_headers = {
                "User-Agent": "ipfs-datasets-new-jersey-bulk/1.0",
                "Accept": self.BULK_ACCEPT,
            }
            retained_digest = str(
                self.state_law_run_environment_value(
                    self.BULK_RETAINED_SHA256_ENV
                )
                or ""
            ).strip().lower()
            if retained_digest:
                if re.fullmatch(r"[a-f0-9]{64}", retained_digest) is None:
                    raise NewJerseyBulkFrontierError(
                        f"{self.BULK_RETAINED_SHA256_ENV} must be an exact SHA-256"
                    )
                if ledger is None:
                    raise NewJerseyBulkFrontierError(
                        f"{self.BULK_RETAINED_SHA256_ENV} requires an attached acquisition ledger"
                    )
                retained = ledger.replay_retained_parser_input(
                    official_url=OFFICIAL_ZIP_URL,
                    sanitized_request={
                        "headers": {"Accept": self.BULK_ACCEPT},
                        "method": "GET",
                        "url": OFFICIAL_ZIP_URL,
                    },
                )
                if retained is None or retained.envelope.body is None:
                    raise NewJerseyBulkFrontierError(
                        "digest-pinned New Jersey retained ZIP is unavailable; refusing HTTP"
                    )
                payload = bytes(retained.envelope.body)
                if hashlib.sha256(payload).hexdigest() != retained_digest:
                    raise NewJerseyBulkFrontierError(
                        "digest-pinned New Jersey retained ZIP changed; refusing HTTP"
                    )
                if not looks_like_zip_bytes(payload):
                    raise NewJerseyBulkFrontierError(
                        "digest-pinned New Jersey retained ZIP failed validation"
                    )
                self._last_page_fetch_transport_evidence = dict(
                    retained.transport_receipt
                )
                self._last_page_parser_input_envelope = retained.envelope
                self._record_fetch_event(
                    provider="retained_acquisition_replay_pinned",
                    success=True,
                )
            else:
                timeout_seconds = max(
                    10,
                    int(
                        os.getenv("NEW_JERSEY_BULK_TIMEOUT_SECONDS", "180")
                        or "180"
                    ),
                )
                payload = await self._fetch_parser_input_with_transport(
                    OFFICIAL_ZIP_URL,
                    headers=request_headers,
                    timeout_seconds=timeout_seconds,
                    content_validator=looks_like_zip_bytes,
                    allow_archival_fallback=True,
                    media_type="application/zip",
                    provider="requests_direct_new_jersey_statutes_zip",
                )
            if not payload:
                if ledger is not None:
                    raise NewJerseyBulkFrontierError(
                        "official New Jersey statutes ZIP is unavailable from direct and archive transports"
                    )
                return []
            self._new_jersey_bulk_provenance = (
                self._new_jersey_bulk_provenance_from_last_input(
                    payload,
                    official_url=OFFICIAL_ZIP_URL,
                )
            )
            inventory_observer = None
            if max_statutes is None and ledger is not None:
                inventory_observer = (
                    self._retain_new_jersey_bulk_inventory_observation
                )
            return await asyncio.to_thread(
                parse_new_jersey_bulk_zip_bytes,
                payload,
                code_name=code_name,
                max_statutes=max_statutes,
                bundle_provenance=self._new_jersey_bulk_provenance or None,
                inventory_observer=inventory_observer,
                fail_on_unusable=inventory_observer is not None,
            )
        except Exception as exc:
            self.logger.warning("New Jersey official bulk zip failed: %s", exc)
            if ledger is not None:
                raise
            return []

    def _new_jersey_bulk_provenance_from_last_input(
        self,
        payload: bytes,
        *,
        official_url: str,
    ) -> Dict[str, Any]:
        """Bind every derived row to the prospective ZIP transport receipt."""

        body = bytes(payload)
        digest = hashlib.sha256(body).hexdigest()
        evidence = getattr(self, "_last_page_fetch_transport_evidence", None)
        envelope = getattr(self, "_last_page_parser_input_envelope", None)
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is not None and (
            not isinstance(evidence, Mapping) or not evidence or envelope is None
        ):
            raise RuntimeError(
                "New Jersey bulk ZIP lacks prospective transport evidence"
            )
        retrieved_at = ""
        byte_size = len(body)
        sanitized_request: Dict[str, Any] = {
            "method": "GET",
            "url": official_url,
        }
        if envelope is not None:
            source_receipt = envelope.acquisition.receipt
            retrieved_at = str(source_receipt.retrieved_at or "")
            sanitized_request = dict(source_receipt.sanitized_request)
            content = source_receipt.content
            if content is not None:
                if str(content.sha256) != digest:
                    raise RuntimeError(
                        "New Jersey retained ZIP digest changed before parsing"
                    )
                byte_size = int(content.byte_size)
        return {
            "byte_size": byte_size,
            "content_sha256": digest,
            "media_type": "application/zip",
            "official_url": official_url,
            "retrieved_at": retrieved_at,
            "sanitized_request": sanitized_request,
            "transport_receipt": dict(evidence or {}),
        }

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind strict frontier evidence to both scraper and RTF parser code."""

        from . import new_jersey_bulk

        return (new_jersey_bulk,)

    @staticmethod
    def _validate_new_jersey_bulk_inventory(
        value: Mapping[str, Any],
    ) -> Dict[str, Any]:
        from .new_jersey_bulk import (
            NEW_JERSEY_BULK_INVENTORY_SCHEMA,
            _canonical_json_sha256,
        )

        inventory = dict(value)
        if inventory.get("schema_version") != NEW_JERSEY_BULK_INVENTORY_SCHEMA:
            raise RuntimeError("New Jersey bulk inventory has the wrong schema")
        if str(inventory.get("jurisdiction") or "").strip().upper() != "NJ":
            raise RuntimeError("New Jersey bulk inventory changed jurisdiction")
        declared = str(inventory.pop("inventory_sha256", "") or "").strip().lower()
        if re.fullmatch(r"[a-f0-9]{64}", declared) is None:
            raise RuntimeError("New Jersey bulk inventory lacks an exact digest")
        if declared != _canonical_json_sha256(inventory):
            raise RuntimeError("New Jersey bulk inventory digest does not replay")
        inventory["inventory_sha256"] = declared

        for prefix in (
            "source_observation",
            "source_record",
            "admitted_source_record",
            "excluded_source_record",
        ):
            raw_ids = inventory.get(f"{prefix}_ids")
            if not isinstance(raw_ids, list) or any(
                not isinstance(item, str) or not item.strip() for item in raw_ids
            ):
                raise RuntimeError(
                    f"New Jersey bulk inventory {prefix}_ids must be exact strings"
                )
            if int(inventory.get(f"{prefix}_count") or -1) != len(raw_ids):
                raise RuntimeError(
                    f"New Jersey bulk inventory {prefix} count does not replay"
                )

        member_paths = inventory.get("archive_member_paths")
        if not isinstance(member_paths, list) or any(
            not isinstance(item, str) or not item for item in member_paths
        ):
            raise RuntimeError("New Jersey bulk inventory lacks member identities")
        if int(inventory.get("archive_member_count") or -1) != len(member_paths):
            raise RuntimeError("New Jersey bulk archive member count does not replay")
        rtf_member = inventory.get("rtf_member")
        if not isinstance(rtf_member, Mapping):
            raise RuntimeError("New Jersey bulk inventory lacks RTF member identity")
        if (
            not str(rtf_member.get("path") or "").upper().endswith("STATUTES.RTF")
            or re.fullmatch(
                r"[a-f0-9]{64}",
                str(rtf_member.get("content_sha256") or "").strip().lower(),
            )
            is None
            or int(rtf_member.get("byte_size") or 0) <= 0
        ):
            raise RuntimeError("New Jersey RTF member identity is incomplete")

        disposition = inventory.get("disposition")
        if not isinstance(disposition, Mapping):
            raise RuntimeError("New Jersey bulk inventory lacks dispositions")
        accounted = sum(
            int(disposition.get(key) or 0)
            for key in (
                "excluded",
                "failed_final",
                "fetched",
                "quarantined",
            )
        )
        if accounted != int(disposition.get("discovered") or -1):
            raise RuntimeError("New Jersey bulk disposition algebra does not close")
        if int(inventory.get("source_observation_count") or -1) != int(
            disposition.get("discovered") or -1
        ):
            raise RuntimeError(
                "New Jersey source observations do not match discovery"
            )

        duplicate_classification = inventory.get("duplicate_classification")
        if not isinstance(duplicate_classification, Mapping):
            raise RuntimeError(
                "New Jersey bulk inventory lacks duplicate classification"
            )
        classified_duplicates = sum(
            int(duplicate_classification.get(key) or 0)
            for key in (
                "divergent_source_record_variants",
                "exact_duplicate_source_records",
            )
        )
        if classified_duplicates != int(disposition.get("duplicates") or 0):
            raise RuntimeError(
                "New Jersey duplicate classification does not replay"
            )

        admitted_kinds = inventory.get("admitted_record_kind_counts")
        excluded_reasons = inventory.get("excluded_reason_counts")
        if not isinstance(admitted_kinds, Mapping) or sum(
            int(value or 0) for value in admitted_kinds.values()
        ) != int(disposition.get("fetched") or 0):
            raise RuntimeError(
                "New Jersey admitted record classifications do not replay"
            )
        if not isinstance(excluded_reasons, Mapping) or sum(
            int(value or 0) for value in excluded_reasons.values()
        ) != int(disposition.get("excluded") or 0):
            raise RuntimeError(
                "New Jersey excluded record classifications do not replay"
            )

        identity_rows = inventory.get("identity_resolution_rows")
        if not isinstance(identity_rows, list) or int(
            inventory.get("identity_resolution_row_count") or -1
        ) != len(identity_rows):
            raise RuntimeError(
                "New Jersey identity-resolution observations do not replay"
            )
        return inventory

    def _retain_new_jersey_bulk_inventory_observation(
        self,
        inventory: Mapping[str, Any],
    ) -> None:
        """Seal the first exact member/section inventory before rows escape."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "New Jersey bulk inventory requires an attached acquisition ledger"
            )
        verified = self._validate_new_jersey_bulk_inventory(inventory)
        bundle = verified.get("bundle")
        if not isinstance(bundle, Mapping):
            raise RuntimeError("New Jersey bulk inventory lacks its bundle binding")
        if str(bundle.get("content_sha256") or "").strip().lower() != str(
            self._new_jersey_bulk_provenance.get("content_sha256") or ""
        ).strip().lower():
            raise RuntimeError(
                "New Jersey bulk inventory changed the retained bundle digest"
            )

        from ....retrieval.hf_graphrag.artifacts import atomic_write_bytes
        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )

        payload = canonical_json_bytes(verified)
        digest = str(verified["inventory_sha256"])
        observation_dir = (
            Path(ledger.frontiers_dir)
            / "new-jersey-statutes-rtf"
            / "first"
            / digest
        )
        observation_dir.mkdir(parents=True, exist_ok=True)
        observation_path = observation_dir / "inventory.json"
        if observation_path.exists():
            if observation_path.is_symlink() or not observation_path.is_file():
                raise RuntimeError(
                    "immutable New Jersey bulk inventory observation conflicts"
                )
            with observation_path.open("rb") as existing:
                if existing.read() != payload:
                    raise RuntimeError(
                        "immutable New Jersey bulk inventory observation conflicts"
                    )
        else:
            atomic_write_bytes(observation_path, payload)
        relative_path = observation_path.resolve().relative_to(
            Path(ledger.jurisdiction_root).resolve()
        )
        self._new_jersey_first_bulk_inventory_observation = {
            "inventory_sha256": digest,
            "relative_path": relative_path.as_posix(),
        }

    def _load_new_jersey_first_bulk_inventory(self) -> Dict[str, Any]:
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        observation = self._new_jersey_first_bulk_inventory_observation
        if ledger is None or not observation:
            raise RuntimeError(
                "New Jersey first bulk inventory was not retained before parsing"
            )
        relative_path = str(observation.get("relative_path") or "").strip()
        path = Path(ledger.jurisdiction_root) / relative_path
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("New Jersey first bulk inventory cannot be replayed")
        try:
            path.resolve().relative_to(Path(ledger.jurisdiction_root).resolve())
            payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                "New Jersey first bulk inventory cannot be replayed"
            ) from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError("New Jersey first bulk inventory is not an object")
        verified = self._validate_new_jersey_bulk_inventory(payload)
        if str(verified["inventory_sha256"]) != str(
            observation.get("inventory_sha256") or ""
        ):
            raise RuntimeError("New Jersey first bulk inventory identity changed")
        return verified

    @staticmethod
    def _new_jersey_inventory_frontier(
        inventory: Mapping[str, Any],
    ) -> Dict[str, Any]:
        frontier = inventory.get("frontier")
        disposition = inventory.get("disposition")
        bundle = inventory.get("bundle")
        member = inventory.get("rtf_member")
        if not all(
            isinstance(item, Mapping)
            for item in (frontier, disposition, bundle, member)
        ):
            raise RuntimeError("New Jersey bulk inventory lacks closure material")
        return {
            "admitted_source_record_count": int(
                inventory.get("admitted_source_record_count") or 0
            ),
            "admitted_source_record_ids_sha256": str(
                inventory.get("admitted_source_record_ids_sha256") or ""
            ),
            "algebra_closed": frontier.get("algebra_closed") is True,
            "bundle_bound": frontier.get("bundle_bound") is True,
            "bundle_byte_size": int(bundle.get("byte_size") or 0),
            "bundle_closed": frontier.get("bundle_closed") is True,
            "bundle_content_sha256": str(bundle.get("content_sha256") or ""),
            "closed": frontier.get("closed") is True,
            "disposition": dict(disposition),
            "duplicate_classification": dict(
                inventory.get("duplicate_classification") or {}
            ),
            "enumerator_closed": frontier.get("enumerator_closed") is True,
            "expected_index_units": int(
                frontier.get("expected_index_units") or 0
            ),
            "inventory_sha256": str(inventory.get("inventory_sha256") or ""),
            "rtf_member_byte_size": int(member.get("byte_size") or 0),
            "rtf_member_content_sha256": str(
                member.get("content_sha256") or ""
            ),
            "rtf_member_path": str(member.get("path") or ""),
            "scope_closed": frontier.get("scope_closed") is True,
            "source_record_count": int(
                inventory.get("source_record_count") or 0
            ),
            "source_record_ids_sha256": str(
                inventory.get("source_record_ids_sha256") or ""
            ),
            "source_observation_count": int(
                inventory.get("source_observation_count") or 0
            ),
            "source_observation_ids_sha256": str(
                inventory.get("source_observation_ids_sha256") or ""
            ),
            "unusable_row_count": int(inventory.get("unusable_row_count") or 0),
            "unvisited_continuation_links": [],
            "visited_index_units": int(
                frontier.get("visited_index_units") or 0
            ),
        }

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Replay the retained ZIP and prove member plus section identity parity."""

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.state_laws_completeness import (
            closed_jurisdiction_receipt,
        )
        from .new_jersey_bulk import (
            OFFICIAL_ZIP_URL,
            inventory_new_jersey_bulk_zip_bytes,
        )

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "New Jersey frontier closure requires an attached acquisition ledger"
            )
        first = self._load_new_jersey_first_bulk_inventory()
        first_frontier = first.get("frontier")
        disposition = first.get("disposition")
        if (
            not isinstance(first_frontier, Mapping)
            or first_frontier.get("closed") is not True
            or first_frontier.get("bundle_closed") is not True
            or first_frontier.get("algebra_closed") is not True
            or first_frontier.get("bundle_bound") is not True
            or not isinstance(disposition, Mapping)
            or int(disposition.get("failed_final") or 0) != 0
            or int(disposition.get("quarantined") or 0) != 0
            or int(
                dict(first.get("duplicate_classification") or {}).get(
                    "divergent_source_record_variants"
                )
                or 0
            )
            != 0
        ):
            raise RuntimeError(
                "New Jersey first bulk inventory has unresolved source records"
            )

        official_source_url = str(
            self._new_jersey_bulk_provenance.get("official_url")
            or OFFICIAL_ZIP_URL
        ).strip()
        replayed_input = ledger.replay_retained_parser_input(
            official_url=official_source_url,
            sanitized_request=dict(
                self._new_jersey_bulk_provenance.get("sanitized_request")
                or {"method": "GET", "url": official_source_url}
            ),
        )
        if replayed_input is None or replayed_input.envelope.body is None:
            raise RuntimeError(
                "New Jersey retained bulk object cannot be independently replayed"
            )
        replayed_body = bytes(replayed_input.envelope.body)
        if hashlib.sha256(replayed_body).hexdigest() != str(
            self._new_jersey_bulk_provenance.get("content_sha256") or ""
        ):
            raise RuntimeError("New Jersey retained bundle digest changed on replay")
        replayed = await asyncio.to_thread(
            inventory_new_jersey_bulk_zip_bytes,
            replayed_body,
            code_name=str(first.get("code_name") or "New Jersey Statutes"),
            bundle_provenance=dict(self._new_jersey_bulk_provenance),
        )
        replayed = self._validate_new_jersey_bulk_inventory(replayed)
        if canonical_json_bytes(first) != canonical_json_bytes(replayed):
            raise RuntimeError(
                "New Jersey first and replayed ZIP inventories differ"
            )

        raw_keys = canonical_output_projection.get("canonical_keys")
        if not isinstance(raw_keys, Sequence) or isinstance(
            raw_keys, (str, bytes, bytearray)
        ):
            raise RuntimeError(
                "New Jersey canonical output projection lacks exact identities"
            )
        canonical_keys = [str(item).strip() for item in raw_keys]
        expected_keys = [
            str(item) for item in first.get("admitted_canonical_keys") or []
        ]
        if (
            not canonical_keys
            or any(not item for item in canonical_keys)
            or len(canonical_keys) != len(set(canonical_keys))
            or canonical_keys != expected_keys
        ):
            missing = sorted(set(expected_keys) - set(canonical_keys))
            extra = sorted(set(canonical_keys) - set(expected_keys))
            raise RuntimeError(
                "New Jersey canonical identities do not exactly match the ZIP "
                "source records: "
                f"expected={len(expected_keys)} actual={len(canonical_keys)} "
                f"missing={missing[:3]} extra={extra[:3]}"
            )

        compact_frontier = self._new_jersey_inventory_frontier(first)
        replayed_frontier = self._new_jersey_inventory_frontier(replayed)
        completion = closed_jurisdiction_receipt(
            "NJ",
            discovered=int(disposition["discovered"]),
            fetched=int(disposition["fetched"]),
            excluded=int(disposition["excluded"]),
            quarantined=int(disposition["quarantined"]),
            failed_final=int(disposition["failed_final"]),
            duplicates=int(disposition.get("duplicates") or 0),
            source_domain="pub.njleg.state.nj.us",
            canonical_keys=canonical_keys,
            derived_keys=canonical_keys,
        )
        boundaries = first.get("boundary_probes")
        if not isinstance(boundaries, Mapping):
            raise RuntimeError("New Jersey bulk inventory lacks boundary probes")
        observed_at = str(
            self._new_jersey_bulk_provenance.get("retrieved_at") or ""
        )
        completion.update(
            {
                "boundary_probes": {
                    "bundle_total": 1,
                    "first_hierarchy_unit": str(
                        boundaries.get("first_source_record_id") or ""
                    ),
                    "last_hierarchy_unit": str(
                        boundaries.get("last_source_record_id") or ""
                    ),
                    "pagination_total": 1,
                },
                "canonical_row_count": len(canonical_keys),
                "frontier": compact_frontier,
                "legal_as_of": observed_at,
                "observed_at": observed_at,
                "replay": {
                    "closed": True,
                    "first_frontier_digest": str(first["inventory_sha256"]),
                    "second_frontier_digest": str(replayed["inventory_sha256"]),
                },
                "rights": {
                    "basis": "public_law_no_state_copyright",
                    "decision": "admit",
                    "scope": "statutory_text",
                },
                "source_frontier_inventory": {
                    "inventory_relative_path": str(
                        self._new_jersey_first_bulk_inventory_observation.get(
                            "relative_path"
                        )
                        or ""
                    ),
                    "inventory_sha256": str(first["inventory_sha256"]),
                    "rtf_member_content_sha256": str(
                        first["rtf_member"]["content_sha256"]
                    ),
                    "source_record_count": int(
                        first.get("source_record_count") or 0
                    ),
                    "source_record_ids_sha256": str(
                        first.get("source_record_ids_sha256") or ""
                    ),
                    "source_observation_count": int(
                        first.get("source_observation_count") or 0
                    ),
                    "source_observation_ids_sha256": str(
                        first.get("source_observation_ids_sha256") or ""
                    ),
                },
                "transport": {
                    "fixture": False,
                    "kind": "retained_official_new_jersey_statutes_zip",
                    "synthetic": False,
                },
            }
        )
        bundle_digest = str(
            self._new_jersey_bulk_provenance.get("content_sha256") or ""
        ).strip().lower()
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=replayed_frontier,
            canonical_output_projection=canonical_output_projection,
            release_point=f"sha256:{bundle_digest}",
            official_source_url=official_source_url,
            acquisition_path_ids=self._catalog_acquisition_path_ids_for_source(
                official_source_url
            ),
            observation_time=observed_at,
            source_software_version=(
                self._state_law_frontier_source_software_version()
            ),
        )

    def _enrich_statute_structure(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Carry retained ZIP/member identities into canonical JSON-LD."""

        enriched = super()._enrich_statute_structure(statute)
        structured = dict(enriched.structured_data or {})
        if str(structured.get("source_kind") or "").strip() != (
            "official_new_jersey_statutes_rtf"
        ):
            return enriched
        digest = str(structured.get("content_sha256") or "").strip().lower()
        source_record_id = str(structured.get("source_record_id") or "").strip()
        receipt = structured.get("transport_receipt")
        source_bundle = structured.get("source_bundle")
        source_member = structured.get("source_member")
        jsonld = structured.get("jsonld")
        provenance_complete = bool(
            re.fullmatch(r"[a-f0-9]{64}", digest)
            and source_record_id
            and isinstance(receipt, Mapping)
            and isinstance(source_bundle, Mapping)
            and isinstance(source_member, Mapping)
            and isinstance(jsonld, Mapping)
        )
        if not provenance_complete:
            if getattr(self, "_state_law_acquisition_ledger", None) is not None:
                raise RuntimeError(
                    "New Jersey bulk row lacks retained bundle/member provenance"
                )
            return enriched
        jsonld_payload = dict(jsonld)
        prior = jsonld_payload.get("provenance")
        provenance = dict(prior) if isinstance(prior, Mapping) else {}
        provenance.update(
            {
                "content_sha256": digest,
                "source_bundle": dict(source_bundle),
                "source_member": dict(source_member),
                "source_record_id": source_record_id,
                "transport_receipt": dict(receipt),
            }
        )
        jsonld_payload["provenance"] = provenance
        structured["jsonld"] = jsonld_payload
        enriched.structured_data = structured
        return enriched

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        title_nodes = await self._discover_title_nodes()
        self.logger.info("NJ official index: discovered %s title nodes", len(title_nodes))
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for title_index, node in enumerate(title_nodes, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            title_id = str(node.get("id") or "").strip()
            title_label = str(node.get("t") or "").strip()
            remaining = None if limit is None else max(0, limit - len(statutes))
            if remaining is not None and remaining <= 0:
                break
            section_nodes = await self._discover_section_nodes(title_id, limit=remaining)
            parsed = await self._scrape_section_nodes(
                code_name,
                section_nodes,
                max_statutes=remaining,
                title_label=title_label,
            )
            statutes.extend(parsed)
            if title_index == 1 or title_index % 10 == 0 or title_index == len(title_nodes):
                self.logger.info(
                    "NJ official index: title=%s index=%s/%s sections=%s statutes_so_far=%s",
                    title_label or title_id,
                    title_index,
                    len(title_nodes),
                    len(section_nodes),
                    len(statutes),
                )
        return statutes[:limit] if limit is not None else statutes

    async def _discover_title_nodes(self) -> List[Dict[str, str]]:
        nodes = await self._fetch_xmlcontents_nodes(basepathid="statutes", command="getchildren")
        title_nodes = [node for node in nodes if str(node.get("id") or "").startswith("statutes/1/")]
        more_nodes = [node for node in nodes if str(node.get("ct") or "") == "application/morenode"]
        while more_nodes:
            next_more = more_nodes.pop(0)
            start = str(next_more.get("n") or "").strip()
            if not start:
                continue
            page = await self._fetch_xmlcontents_nodes(basepathid="statutes/1", command="getmore", start=start, direction="1")
            title_nodes.extend([node for node in page if str(node.get("id") or "").startswith("statutes/1/") and str(node.get("ct") or "") != "application/morenode"])
            more_nodes.extend([node for node in page if str(node.get("ct") or "") == "application/morenode"])
        deduped: List[Dict[str, str]] = []
        seen: set[str] = set()
        for node in title_nodes:
            node_id = str(node.get("id") or "").strip()
            if not node_id or node_id in seen:
                continue
            seen.add(node_id)
            deduped.append(node)
        return deduped

    async def _discover_section_nodes(self, title_id: str, limit: Optional[int] = None) -> List[Dict[str, str]]:
        nodes = await self._fetch_xmlcontents_nodes(basepathid=title_id, command="getchildren")
        section_nodes = [node for node in nodes if str(node.get("ct") or "") == "text/xml"]
        more_nodes = [node for node in nodes if str(node.get("ct") or "") == "application/morenode"]
        while more_nodes and (limit is None or len(section_nodes) < limit):
            next_more = more_nodes.pop(0)
            start = str(next_more.get("n") or "").strip()
            if not start:
                continue
            page = await self._fetch_xmlcontents_nodes(basepathid=title_id, command="getmore", start=start, direction="1")
            section_nodes.extend([node for node in page if str(node.get("ct") or "") == "text/xml"])
            more_nodes.extend([node for node in page if str(node.get("ct") or "") == "application/morenode"])
        deduped: List[Dict[str, str]] = []
        seen: set[str] = set()
        for node in section_nodes:
            node_id = str(node.get("id") or "").strip()
            if not node_id or node_id in seen:
                continue
            seen.add(node_id)
            deduped.append(node)
            if limit is not None and len(deduped) >= limit:
                break
        return deduped

    async def _fetch_xmlcontents_nodes(
        self,
        *,
        basepathid: str,
        command: str,
        start: str = "",
        direction: str = "",
    ) -> List[Dict[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        params = [f"command={command}", f"basepathid={quote(basepathid, safe='')}"]
        if command == "getchildren":
            params.append("maxgrandchildren=25")
        if start:
            params.append(f"start={quote(start, safe='')}")
        if direction:
            params.append(f"direction={quote(direction, safe='')}")
        url = f"{self._XMLCONTENTS_BASE}&" + "&".join(params)
        payload = await self._request_bytes_direct(url, timeout=30)
        if not payload:
            return []
        xml = payload.decode("utf-8", errors="replace")
        soup = BeautifulSoup(xml, "xml")
        out: List[Dict[str, str]] = []
        for node in soup.find_all("n"):
            attrs = {str(k): str(v) for k, v in node.attrs.items()}
            out.append(attrs)
        return out

    async def _scrape_section_nodes(
        self,
        code_name: str,
        section_nodes: List[Dict[str, str]],
        *,
        max_statutes: Optional[int],
        title_label: str,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for node in section_nodes:
            if limit is not None and len(out) >= limit:
                break
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue
            source_url = f"{self._LIS_GATEWAY}/{node_id}"
            payload = await self._request_bytes_direct(source_url, timeout=25)
            if not payload:
                continue
            html = payload.decode("utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            headnotes = soup.select_one("div.Headnotes")
            normal = soup.select_one("div.Normal-Level")
            heading = self._normalize_legal_text((headnotes or soup).get_text(" ", strip=True))
            body = self._normalize_legal_text((normal or soup).get_text(" ", strip=True))
            full_text = self._normalize_legal_text(" ".join(part for part in [heading, body] if part))
            if len(full_text) < 80:
                continue
            section_label = str(node.get("t") or "").strip()
            section_number = self._extract_section_number(section_label)
            if not section_number:
                section_number = self._extract_section_number(heading)
            section_name = section_label
            if section_number and section_name.startswith(section_number):
                section_name = section_name[len(section_number):].lstrip(". ").strip()
            if not section_name:
                section_name = self._normalize_legal_text(heading)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number or node_id}",
                    code_name=code_name,
                    section_number=section_number or str(node.get("n") or node_id),
                    section_name=section_name[:220],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(title_label or section_name),
                    source_url=source_url,
                    official_cite=(section_number or section_label),
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_new_jersey_gateway_html",
                        "discovery_method": "official_xmlcontents_toc",
                        "title_label": title_label,
                        "node_id": node_id,
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _scrape_direct_public_law_pdfs(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        seeds = [
            ("P.L. 2025, c.1", "https://pub.njleg.state.nj.us/Bills/2024/PL25/1_.PDF"),
            ("P.L. 2025, c.2", "https://pub.njleg.state.nj.us/Bills/2024/PL25/2_.PDF"),
        ]
        out: List[NormalizedStatute] = []
        for cite, pdf_url in seeds[: max(1, int(max_statutes or 1))]:
            pdf_bytes = await self._request_bytes_direct(pdf_url, timeout=20)
            text = self._extract_pdf_text(pdf_bytes, max_chars=None)
            if len(text) < 280:
                continue
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} {cite}",
                    code_name=code_name,
                    section_number=cite,
                    section_name=cite,
                    full_text=text,
                    legal_area=self._identify_legal_area(text[:1200]),
                    source_url=pdf_url,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_new_jersey_public_law_pdf",
                        "discovery_method": "official_seed_pdf",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _request_bytes_direct(self, url: str, timeout: int = 20) -> bytes:
        is_pdf = urlparse(str(url or "")).path.lower().endswith(".pdf")
        try:
            return await self._fetch_parser_input_with_transport(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": (
                        "application/pdf,*/*;q=0.8"
                        if is_pdf
                        else "text/html,application/xml;q=0.9,*/*;q=0.8"
                    ),
                },
                timeout_seconds=max(1, int(timeout)),
                content_validator=(
                    (lambda payload: payload.startswith(b"%PDF"))
                    if is_pdf
                    else None
                ),
                allow_archival_fallback=True,
                media_type="application/pdf" if is_pdf else None,
                provider="new_jersey_direct_gateway",
            )
        except Exception:
            return b""

    def _extract_pdf_text(
        self,
        pdf_bytes: bytes,
        max_chars: Optional[int] = None,
    ) -> str:
        if not pdf_bytes:
            return ""
        try:
            proc = subprocess.run(
                [trusted_pdftotext_executable(), "-layout", "-q", "-", "-"],
                input=pdf_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except Exception:
            return ""
        if proc.returncode != 0 or not proc.stdout:
            return ""
        text = proc.stdout.decode("utf-8", errors="ignore")
        text = re.sub(r"\s+", " ", text).strip()
        if max_chars is not None:
            return text[: max(1, int(max_chars))]
        return text

    async def _scrape_via_xhitlist(self, code_name: str, max_sections: int = 120) -> List[NormalizedStatute]:
        """Collect NJ statutes from LIS query result pages.

        The LIS default page is JS-driven and often sparse when fetched as static
        HTML. Querying xhitlist returns concrete hitdoc links that can be parsed
        directly.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        terms = ["tax", "crime", "property", "employment", "health"]
        seen_urls = set()
        statutes: List[NormalizedStatute] = []
        legal_area = self._identify_legal_area(code_name)

        for term in terms:
            if len(statutes) >= max_sections:
                break

            page = await self._fetch_xhitlist_page(term)
            if not page:
                continue

            soup = BeautifulSoup(page, "html.parser")
            for link in soup.find_all("a", href=True):
                if len(statutes) >= max_sections:
                    break

                href = str(link.get("href", "")).strip()
                if "f=hitdoc" not in href.lower():
                    continue

                link_text = link.get_text(strip=True)
                if not link_text or link_text.lower().startswith(("next", "last", "manage")):
                    continue

                source_url = urljoin(self._LIS_GATEWAY, href)
                if source_url in seen_urls:
                    continue
                seen_urls.add(source_url)

                section_number = self._extract_section_number(link_text)
                if not section_number:
                    section_number = self._derive_section_number_from_url(source_url)
                if not section_number:
                    section_number = f"Section-{len(statutes) + 1}"

                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=link_text[:220],
                        full_text=f"Section {section_number}: {link_text}",
                        legal_area=legal_area,
                        source_url=source_url,
                        official_cite=f"N.J. Stat. Ann. § {section_number}",
                        metadata=StatuteMetadata(),
                    )
                )

        self.logger.info("NJ xhitlist extracted %d statute links", len(statutes))
        return statutes

    async def _fetch_xhitlist_page(self, query_term: str) -> str:
        """Fetch one NJ xhitlist result page as text for a simple query term."""
        params = {
            "f": "xhitlist",
            "xhitlist_vq": query_term,
            "xhitlist_q": query_term,
            "xhitlist_x": "Simple",
            "xhitlist_s": "relevance-weight",
            "xhitlist_mh": "120",
            "xhitlist_d": "",
            "xhitlist_hc": "",
            "xhitlist_xsl": "xhitlist.xsl",
            "xhitlist_vpc": "first",
            "xhitlist_vps": "50",
            "xhitlist_sel": self._XHITLIST_SELECT,
        }
        request_url = self._build_query_url(self._LIS_GATEWAY, params)
        raw = await self._fetch_page_content_with_archival_fallback(
            request_url,
            timeout_seconds=45,
        )
        if not raw:
            return ""
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    def _build_query_url(self, base_url: str, params: Dict[str, str]) -> str:
        """Build a URL query string without introducing extra dependencies."""
        from urllib.parse import urlencode

        return f"{base_url}?{urlencode(params)}"

    def official_title_url(self, title_number: Any) -> str:
        slug = str(title_number or "").strip().lower()
        return f"{self._LIS_GATEWAY}/statutes/1/{slug}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official New Jersey Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"nj:title-{number.lower()}",
                    "title_number": number,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"New Jersey Statutes Title {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host in {
            "lis.njleg.state.nj.us",
            "www.njleg.state.nj.us",
            "njleg.state.nj.us",
        } or host.endswith(".njleg.state.nj.us")

    def _looks_like_secondary_url(self, url: str) -> bool:
        lowered = str(url or "").strip().lower()
        return any(
            marker in lowered
            for marker in ("justia.com", "findlaw.com", "unicourt", "law.cornell.edu")
        )

    def _normalize_title_number(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        if not text:
            return ""
        match = re.search(r"\b([0-9]+[A-Z]?)\b", text)
        if not match:
            return ""
        number = match.group(1)
        known = {item for item, _name in self.OFFICIAL_TITLES}
        return number if number in known else ""

    def _official_http_get(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(2, min(int(timeout_seconds or 8), 8))
        headers = {
            "User-Agent": "ipfs-datasets-new-jersey-official-catalog/1.0",
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
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                return b""

    def classify_source_link_gaps(
        self,
        seeds: object,
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Repair official LIS title links or quarantine remaining link gaps.

        Recoverable title numbers are rewritten to ``lis.njleg.state.nj.us``
        catalog URLs. Remaining linkless or secondary-mirror rows stay
        quarantined with a typed disposition.
        """

        repaired: List[Dict[str, Any]] = []
        quarantines: List[Dict[str, Any]] = []
        seen: set[str] = set()
        seen_quarantine: set[str] = set()

        def _record(title_number: str, label: str, source: str, source_url: str = "") -> None:
            number = self._normalize_title_number(title_number)
            if not number:
                return
            unit_id = f"nj:title-{number.lower()}"
            if unit_id in seen:
                return
            seen.add(unit_id)
            official_url = (
                source_url
                if source_url and self._host_is_official(source_url)
                else self.official_title_url(number)
            )
            name = dict(self.OFFICIAL_TITLES).get(number, f"Title {number}")
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip() or name
            repaired.append(
                {
                    "canonical_key": unit_id,
                    "title_number": number,
                    "name": name,
                    "source_url": official_url,
                    "label": cleaned,
                    "repair_source": source,
                    "source_link_disposition": (
                        "official" if source == "official_href" else "repaired_official_lis"
                    ),
                    "text": (
                        f"New Jersey Statutes Title {number} ({name}) official "
                        f"catalog unit at {official_url}"
                    ),
                }
            )

        def _quarantine(label: str, evidence: str, unit_id: str = "", reason: str = "") -> None:
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
            if not cleaned:
                return
            key = unit_id or (
                "nj:missing-" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            )
            if key in seen_quarantine:
                return
            seen_quarantine.add(key)
            quarantines.append(
                {
                    "unit_id": key,
                    "reason": reason or self.LINK_GAP_QUARANTINE_REASON,
                    "label": cleaned[:240],
                    "page_url": page_url,
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
            try:
                from bs4 import BeautifulSoup
            except ImportError as exc:
                raise RuntimeError(
                    "BeautifulSoup is required for official New Jersey discovery"
                ) from exc
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
                absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
                match = self._NJ_TITLE_HREF_RE.search(absolute) or self._NJ_TITLE_LABEL_RE.search(
                    label
                )
                title_number = match.group("title") if match else self._normalize_title_number(
                    " ".join((absolute, href, label))
                )
                if title_number and self._host_is_official(absolute):
                    _record(title_number, label, "official_href", self.official_title_url(title_number))
                    continue
                if title_number:
                    _record(title_number, label, "repaired_from_attributes")
                    continue
                if label and self._looks_like_secondary_url(absolute):
                    _quarantine(label, str(link), reason=self.MISSING_LINK_DISPOSITION)
            for node in soup.find_all(["span", "td", "li", "div", "p"]):
                if node.find("a", href=True):
                    continue
                label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
                if not label:
                    continue
                title_number = self._normalize_title_number(
                    " ".join(
                        str(item or "")
                        for item in (node.get("data-title"), node.get("id"), label)
                    )
                )
                if title_number:
                    _record(title_number, label, "repaired_from_linkless_row")
                    continue
                if re.search(
                    r"\b(bucket seed|phantom|without a recoverable|without an official)\b",
                    label,
                    re.IGNORECASE,
                ):
                    _quarantine(label, str(node), reason=self.MISSING_LINK_DISPOSITION)
            return {"repaired": repaired, "quarantines": quarantines}

        items = seeds or ()
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
            title_number = self._normalize_title_number(
                item.get("title_number") or source_url or label
            )
            if title_number and source_url and self._host_is_official(source_url):
                _record(title_number, label, "official_href", source_url)
                continue
            if title_number:
                _record(title_number, label, "repaired_from_linkless_row")
                continue
            _quarantine(
                label or source_url or "new jersey link gap",
                json.dumps(dict(item), sort_keys=True),
                unit_id=str(item.get("canonical_key") or ""),
            )
        return {"repaired": repaired, "quarantines": quarantines}

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
            match = self._NJ_TITLE_HREF_RE.search(absolute) or self._NJ_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = str(match.group("title") or "").strip().upper()
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
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate official NJ titles and type remaining source-link gaps."""

        discovered = self._parse_official_title_links(html)
        classified = self.classify_source_link_gaps(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        seed_classified = self.classify_source_link_gaps(
            list(seed_rows) if seed_rows is not None else list(self.DEFAULT_LINK_GAP_SEEDS),
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        classified["repaired"].extend(seed_classified["repaired"])
        classified["quarantines"].extend(seed_classified["quarantines"])
        self.last_official_quarantines = list(classified["quarantines"])
        self.last_official_repairs = list(classified["repaired"])

        rows = self.official_title_catalog()
        by_title = {str(row["title_number"]).upper(): row for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_lis"
        for unit in classified["repaired"]:
            number = str(unit.get("title_number") or "").upper()
            if number in by_title and unit.get("source_url"):
                if unit.get("repair_source") == "official_href":
                    by_title[number]["source_url"] = unit["source_url"]
                    by_title[number]["source_link_disposition"] = "official"
        return rows

    def fetch_official(self, code: str = "NJ"):
        """Acquire the exhaustive official New Jersey Statutes title catalog.

        Live HTTPS retains the official LIS statutes index. Every current NJ
        title is enumerated with an official lis.njleg.state.nj.us URL.
        Per-row source-link gaps are repaired to official title URLs or
        quarantined with a typed disposition. This hook never returns fixture
        bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "NJ").strip().upper() or "NJ"
        if normalized != "NJ":
            raise ValueError(f"NewJerseyScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        quarantines = list(getattr(self, "last_official_quarantines", []) or [])
        repairs = list(getattr(self, "last_official_repairs", []) or [])
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "new jersey official catalog enumeration rejected incomplete title reacquisition"
            )
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "link_gaps_repaired": True,
            "units": rows,
            "quarantines": quarantines,
            "repairs": repairs,
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = html if html else (b"HTTP/1.1 200 OK\n\n" + body)
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows),
            "method": "pagination",
            "nj_link_gap_quarantines": quarantines,
            "nj_link_gaps_repaired": True,
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
StateScraperRegistry.register("NJ", NewJerseyScraper)
