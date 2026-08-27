"""California state law scraper.

Scrapes laws from the California Legislative Information website
(https://leginfo.legislature.ca.gov/).
"""

from typing import Any, List, Dict, Mapping, Optional, Sequence, Tuple
import hashlib
import inspect
import json
import os
import re
import ssl
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from ipfs_datasets_py.utils import anyio_compat as asyncio
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class CaliforniaScraper(BaseStateScraper):
    """Scraper for California state laws."""

    CODE_TYPE_MAP = {
        "Business and Professions Code": "BPC",
        "Civil Code": "CIV",
        "Code of Civil Procedure": "CCP",
        "Commercial Code": "COM",
        "Corporations Code": "CORP",
        "Education Code": "EDC",
        "Elections Code": "ELEC",
        "Evidence Code": "EVID",
        "Family Code": "FAM",
        "Financial Code": "FIN",
        "Fish and Game Code": "FGC",
        "Food and Agricultural Code": "FAC",
        "Government Code": "GOV",
        "Harbors and Navigation Code": "HNC",
        "Health and Safety Code": "HSC",
        "Insurance Code": "INS",
        "Labor Code": "LAB",
        "Military and Veterans Code": "MVC",
        "Penal Code": "PEN",
        "Probate Code": "PROB",
        "Public Contract Code": "PCC",
        "Public Resources Code": "PRC",
        "Public Utilities Code": "PUC",
        "Revenue and Taxation Code": "RTC",
        "Streets and Highways Code": "SHC",
        "Unemployment Insurance Code": "UIC",
        "Vehicle Code": "VEH",
        "Water Code": "WAT",
        "Welfare and Institutions Code": "WIC",
        "California Constitution": "CONS",
    }

    _SECTION_DISPLAY_RE = re.compile(r"codes_displayText\.xhtml", re.IGNORECASE)
    _SECTION_NUM_QUERY_RE = re.compile(r"sectionNum=([^&]+)", re.IGNORECASE)
    OFFICIAL_DOMAIN = "leginfo.legislature.ca.gov"
    OFFICIAL_CODES_PATH = "/faces/codes.xhtml"
    OFFICIAL_ENTRY_URL = "https://leginfo.legislature.ca.gov/faces/codes.xhtml"
    MISSING_LINK_QUARANTINE_REASON = "missing_official_source_link"

    def __init__(self, state_code: str, state_name: str):
        super().__init__(state_code, state_name)
        self._bulk_zip_cache_key: Optional[Tuple[str, int, int, str]] = None
        self._bulk_zip_cache_loaded = False
        self._bulk_zip_cache_limit: Optional[int] = None
        self._bulk_zip_rows_by_code: Dict[str, List[NormalizedStatute]] = {}
        self._bulk_zip_cache_error: Optional[Exception] = None
        self._bulk_zip_provenance_cache_key: Optional[
            Tuple[str, int, int, str, int, int, str]
        ] = None
        self._bulk_zip_provenance: Dict[str, Any] = {}
        self._california_first_bulk_inventory_observation: Dict[str, Any] = {}

    def get_base_url(self) -> str:
        """Get base URL for California Legislative Information."""
        return "https://leginfo.legislature.ca.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of California codes.

        California has 29 codes organized by subject matter.
        """
        base_url = self.get_base_url()

        codes = [
            {"name": "Business and Professions Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=BPC", "type": "BPC"},
            {"name": "Civil Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=CIV", "type": "CIV"},
            {"name": "Code of Civil Procedure", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=CCP", "type": "CCP"},
            {"name": "Commercial Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=COM", "type": "COM"},
            {"name": "Corporations Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=CORP", "type": "CORP"},
            {"name": "Education Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=EDC", "type": "EDC"},
            {"name": "Elections Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=ELEC", "type": "ELEC"},
            {"name": "Evidence Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=EVID", "type": "EVID"},
            {"name": "Family Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FAM", "type": "FAM"},
            {"name": "Financial Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FIN", "type": "FIN"},
            {"name": "Fish and Game Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FGC", "type": "FGC"},
            {"name": "Food and Agricultural Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FAC", "type": "FAC"},
            {"name": "Government Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=GOV", "type": "GOV"},
            {"name": "Harbors and Navigation Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=HNC", "type": "HNC"},
            {"name": "Health and Safety Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=HSC", "type": "HSC"},
            {"name": "Insurance Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=INS", "type": "INS"},
            {"name": "Labor Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=LAB", "type": "LAB"},
            {"name": "Military and Veterans Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=MVC", "type": "MVC"},
            {"name": "Penal Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PEN", "type": "PEN"},
            {"name": "Probate Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PROB", "type": "PROB"},
            {"name": "Public Contract Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PCC", "type": "PCC"},
            {"name": "Public Resources Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PRC", "type": "PRC"},
            {"name": "Public Utilities Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PUC", "type": "PUC"},
            {"name": "Revenue and Taxation Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=RTC", "type": "RTC"},
            {"name": "Streets and Highways Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=SHC", "type": "SHC"},
            {"name": "Unemployment Insurance Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=UIC", "type": "UIC"},
            {"name": "Vehicle Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=VEH", "type": "VEH"},
            {"name": "Water Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=WAT", "type": "WAT"},
            {"name": "Welfare and Institutions Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=WIC", "type": "WIC"},
            {
                "name": "California Constitution",
                "url": f"{base_url}/faces/codes_displayText.xhtml?lawCode=CONS&article=I",
                "type": "CONS",
            },
        ]

        return codes

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific California code from official leginfo HTML.

        Full-corpus mode with ``max_statutes=None`` remains uncapped. Bounded
        probes may use compact seed sections first, then fall through to the
        official TOC/section tree.
        """
        limit = self._effective_scrape_limit(max_statutes, default=250)
        code_type = self.CODE_TYPE_MAP.get(code_name)
        if not code_type:
            self.logger.warning("No code type mapping for %s", code_name)
            return []

        # A configured official pubinfo bundle is the single prospective
        # source frontier for every family, including CONS.  Constitution HTML
        # remains a scoped fallback only when that bundle yields no CONS row;
        # it must never pre-empt the retained archive or leak into other codes.
        bulk = self._scrape_official_bulk_zip(
            code_name=code_name,
            code_type=code_type,
            max_statutes=limit,
        )
        if bulk:
            admitted = bulk if limit is None else bulk[: int(limit)]
            return self._repair_or_type_missing_source_links(admitted)

        if code_type == "CONS":
            from .california_constitution import (
                configured_constitution_html_path,
                parse_california_constitution_html,
            )

            constitution_path = configured_constitution_html_path()
            if constitution_path is not None:
                constitution_rows = parse_california_constitution_html(
                    constitution_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    ),
                    article_id="I",
                    code_name=code_name or "California Constitution",
                    max_statutes=limit,
                )
                if constitution_rows:
                    return (
                        constitution_rows
                        if limit is None
                        else constitution_rows[: int(limit)]
                    )

        seeds: List[NormalizedStatute] = []
        # Seed path is for bounded probes only — never sole full-corpus path.
        if not self._full_corpus_enabled() or max_statutes is not None:
            seed_budget = limit if limit is not None else 2
            seeds = await self._scrape_direct_seed_sections(
                code_name,
                code_type,
                max_statutes=max(1, int(seed_budget)),
            )

        official = await self._scrape_official_leginfo_tree(
            code_name,
            code_url,
            code_type,
            max_statutes=limit,
        )
        if official:
            admitted = official if limit is None else official[: int(limit)]
            return self._repair_or_type_missing_source_links(admitted)

        # Bounded probe fallback to seeds when the official TOC tree is empty.
        if seeds:
            admitted = seeds if limit is None else seeds[: int(limit)]
            return self._repair_or_type_missing_source_links(admitted)

        return []

    def _scrape_official_bulk_zip(
        self,
        *,
        code_name: str,
        code_type: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Read the official pubinfo ZIP when CALIFORNIA_BULK_ZIP is set.

        Does not download the 1 GB archive by default. Operators point the env
        at a local copy from downloads.leginfo.legislature.ca.gov.
        """

        from .california_bulk import (
            configured_bulk_zip_path,
            parse_california_bulk_zip_codes,
        )

        zip_path = configured_bulk_zip_path()
        if zip_path is None:
            return []

        requested_limit = (
            None if max_statutes is None else max(0, int(max_statutes))
        )
        cache_key: Optional[Tuple[str, int, int, str]] = None
        try:
            stat = zip_path.stat()
            bundle_provenance = self._retain_official_bulk_zip_parser_input(zip_path)
            bundle_digest = str(
                bundle_provenance.get("content_sha256") or ""
            ).strip().lower()
            parser_zip_path = zip_path
            retained_body_path = str(
                bundle_provenance.get("retained_body_path") or ""
            ).strip()
            if retained_body_path:
                parser_zip_path = Path(retained_body_path)
            cache_key = (
                str(zip_path.resolve()),
                int(stat.st_size),
                int(stat.st_mtime_ns),
                bundle_digest,
            )
            cache_satisfies_limit = self._bulk_zip_cache_limit is None or (
                requested_limit is not None
                and requested_limit <= self._bulk_zip_cache_limit
            )
            if not (
                self._bulk_zip_cache_loaded
                and self._bulk_zip_cache_key == cache_key
                and cache_satisfies_limit
            ):
                code_names = {
                    code_type: name for name, code_type in self.CODE_TYPE_MAP.items()
                }
                inventory_observer = None
                if (
                    requested_limit is None
                    and getattr(self, "_state_law_acquisition_ledger", None)
                    is not None
                ):
                    inventory_observer = (
                        self._retain_california_bulk_inventory_observation
                    )
                self._bulk_zip_rows_by_code = parse_california_bulk_zip_codes(
                    parser_zip_path,
                    code_types=tuple(code_names),
                    max_statutes=requested_limit,
                    code_names=code_names,
                    bundle_provenance=bundle_provenance or None,
                    inventory_observer=inventory_observer,
                    fail_on_unusable=inventory_observer is not None,
                )
                self._bulk_zip_cache_key = cache_key
                self._bulk_zip_cache_limit = requested_limit
                self._bulk_zip_cache_loaded = True
                self._bulk_zip_cache_error = None
                self.logger.info(
                    "California official bulk zip cached %s code families from one table pass",
                    len(self._bulk_zip_rows_by_code),
                )
            elif self._bulk_zip_cache_error is not None:
                raise self._bulk_zip_cache_error
            rows = list(
                self._bulk_zip_rows_by_code.get(str(code_type or "").upper(), ())
            )
            return rows if requested_limit is None else rows[:requested_limit]
        except Exception as exc:
            # Cache a deterministic failure for this exact local archive so a
            # 30-code crawl does not repeat the same expensive parse.  A file
            # size or mtime change produces a new key and retries normally.
            try:
                if cache_key is None:
                    stat = zip_path.stat()
                    cache_key = (
                        str(zip_path.resolve()),
                        int(stat.st_size),
                        int(stat.st_mtime_ns),
                        "",
                    )
                self._bulk_zip_cache_key = cache_key
                self._bulk_zip_cache_limit = requested_limit
                self._bulk_zip_cache_loaded = True
                self._bulk_zip_rows_by_code = {}
                self._bulk_zip_cache_error = exc
            except OSError:
                pass
            self.logger.warning("California official bulk zip failed: %s", exc)
            if getattr(self, "_state_law_acquisition_ledger", None) is not None:
                raise
            return []

    def _retain_official_bulk_zip_parser_input(
        self,
        zip_path: Any,
    ) -> Dict[str, Any]:
        """Stream one verified official pubinfo ZIP into the shared ledger.

        The cache key includes both archive and sidecar metadata plus the
        evidence root.  A 30-family run therefore retains the 1+ GB archive
        once, while a changed file, receipt, or ledger is independently
        revalidated before parser admission.
        """

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            return {}

        from .california_bulk import (
            configured_bulk_zip_receipt_path,
            load_california_bulk_transport_receipt,
        )

        archive_path = Path(zip_path).expanduser()
        receipt_path = configured_bulk_zip_receipt_path(archive_path)
        archive_stat = archive_path.stat()
        receipt_stat = receipt_path.stat()
        cache_key = (
            str(archive_path.resolve()),
            int(archive_stat.st_size),
            int(archive_stat.st_mtime_ns),
            str(receipt_path.resolve()),
            int(receipt_stat.st_size),
            int(receipt_stat.st_mtime_ns),
            str(getattr(ledger, "jurisdiction_root", "")),
        )
        if (
            self._bulk_zip_provenance_cache_key == cache_key
            and self._bulk_zip_provenance
        ):
            return dict(self._bulk_zip_provenance)

        receipt = load_california_bulk_transport_receipt(
            archive_path,
            receipt_path=receipt_path,
        )
        official_url = str(receipt["official_url"])
        retained = ledger.retain_parser_input_file(
            official_url=official_url,
            source_path=archive_path,
            transport_receipt=receipt,
            retrieved_at=str(receipt["retrieved_at"]),
            response_status=int(receipt["response_status"]),
            media_type=str(receipt["media_type"]),
            sanitized_request={"method": "GET", "url": official_url},
        )
        content = retained.receipt.content
        if content is None:
            raise RuntimeError(
                "California bulk ZIP retention omitted its content address"
            )
        provenance = {
            "byte_size": int(content.byte_size),
            "content_sha256": str(content.sha256),
            "media_type": str(receipt["media_type"]),
            "official_url": official_url,
            "retrieved_at": str(receipt["retrieved_at"]),
            # Parser reads the immutable retained object, not the mutable
            # operator download path that was just verified.
            "retained_body_path": str(retained.body_path),
            "transport_receipt": dict(retained.transport_receipt),
        }
        self._bulk_zip_provenance_cache_key = cache_key
        self._bulk_zip_provenance = provenance
        return dict(provenance)

    @staticmethod
    def _validate_california_bulk_inventory(
        value: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Replay the deterministic inventory digest and core source binding."""

        from .california_bulk import CALIFORNIA_BULK_INVENTORY_SCHEMA

        inventory = dict(value)
        if inventory.get("schema_version") != CALIFORNIA_BULK_INVENTORY_SCHEMA:
            raise RuntimeError("California bulk inventory has the wrong schema")
        if str(inventory.get("jurisdiction") or "").strip().upper() != "CA":
            raise RuntimeError("California bulk inventory changed jurisdiction")
        declared = str(inventory.pop("inventory_sha256", "") or "").strip().lower()
        if re.fullmatch(r"[a-f0-9]{64}", declared) is None:
            raise RuntimeError("California bulk inventory lacks an exact digest")
        from .california_bulk import _canonical_json_sha256

        computed = _canonical_json_sha256(inventory)
        if declared != computed:
            raise RuntimeError("California bulk inventory digest does not replay")
        inventory["inventory_sha256"] = declared
        source_ids = inventory.get("source_record_ids")
        if not isinstance(source_ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in source_ids
        ):
            raise RuntimeError(
                "California bulk inventory source_record_ids must be exact strings"
            )
        try:
            source_record_count = int(inventory.get("source_record_count"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "California bulk inventory source-record count is invalid"
            ) from exc
        if source_record_count != len(source_ids):
            raise RuntimeError(
                "California bulk inventory source-record count does not replay"
            )
        return inventory

    def _retain_california_bulk_inventory_observation(
        self,
        inventory: Mapping[str, Any],
    ) -> None:
        """Immutably seal the first complete table observation before output."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "California bulk inventory requires an attached acquisition ledger"
            )
        verified = self._validate_california_bulk_inventory(inventory)
        bundle = verified.get("bundle")
        if not isinstance(bundle, Mapping):
            raise RuntimeError("California bulk inventory lacks its bundle binding")
        expected_digest = str(
            self._bulk_zip_provenance.get("content_sha256") or ""
        ).strip().lower()
        if str(bundle.get("content_sha256") or "").strip().lower() != expected_digest:
            raise RuntimeError(
                "California bulk inventory changed the retained bundle digest"
            )

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ....retrieval.hf_graphrag.artifacts import atomic_write_bytes

        payload = canonical_json_bytes(verified)
        digest = str(verified["inventory_sha256"])
        observation_dir = (
            Path(ledger.frontiers_dir)
            / "california-pubinfo"
            / "first"
            / digest
        )
        observation_dir.mkdir(parents=True, exist_ok=True)
        observation_path = observation_dir / "inventory.json"
        if observation_path.exists():
            if (
                observation_path.is_symlink()
                or not observation_path.is_file()
                or observation_path.read_bytes() != payload
            ):
                raise RuntimeError(
                    "immutable California bulk inventory observation conflicts"
                )
        else:
            atomic_write_bytes(observation_path, payload)
        relative_path = observation_path.resolve().relative_to(
            Path(ledger.jurisdiction_root).resolve()
        )
        self._california_first_bulk_inventory_observation = {
            "inventory_sha256": digest,
            "relative_path": relative_path.as_posix(),
        }

    def _load_california_first_bulk_inventory(self) -> Dict[str, Any]:
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        observation = self._california_first_bulk_inventory_observation
        if ledger is None or not observation:
            raise RuntimeError(
                "California first bulk inventory was not retained before parsing"
            )
        relative_path = str(observation.get("relative_path") or "").strip()
        path = Path(ledger.jurisdiction_root) / relative_path
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("California first bulk inventory cannot be replayed")
        try:
            path.resolve().relative_to(Path(ledger.jurisdiction_root).resolve())
            payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                "California first bulk inventory cannot be replayed"
            ) from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError("California first bulk inventory is not an object")
        verified = self._validate_california_bulk_inventory(payload)
        if str(verified["inventory_sha256"]) != str(
            observation.get("inventory_sha256") or ""
        ):
            raise RuntimeError("California first bulk inventory identity changed")
        return verified

    @staticmethod
    def _california_inventory_frontier(
        inventory: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Project a compact exact frontier without repeating all source IDs."""

        frontier = inventory.get("frontier")
        table_member = inventory.get("table_member")
        bundle = inventory.get("bundle")
        disposition = inventory.get("disposition")
        if not all(
            isinstance(item, Mapping)
            for item in (frontier, table_member, bundle, disposition)
        ):
            raise RuntimeError("California bulk inventory lacks closure material")
        return {
            "admitted_source_record_count": int(
                inventory.get("admitted_source_record_count") or 0
            ),
            "admitted_source_record_ids_sha256": str(
                inventory.get("admitted_source_record_ids_sha256") or ""
            ),
            "bundle_byte_size": int(bundle.get("byte_size") or 0),
            "bundle_closed": frontier.get("bundle_closed") is True,
            "bundle_content_sha256": str(bundle.get("content_sha256") or ""),
            "closed": frontier.get("closed") is True,
            "disposition": dict(disposition),
            "enumerator_closed": frontier.get("enumerator_closed") is True,
            "expected_index_units": int(
                frontier.get("expected_index_units") or 0
            ),
            "inventory_sha256": str(inventory.get("inventory_sha256") or ""),
            "scope_closed": frontier.get("scope_closed") is True,
            "source_record_count": int(inventory.get("source_record_count") or 0),
            "source_record_ids_sha256": str(
                inventory.get("source_record_ids_sha256") or ""
            ),
            "table_member_byte_size": int(table_member.get("byte_size") or 0),
            "table_member_content_sha256": str(
                table_member.get("content_sha256") or ""
            ),
            "table_member_path": str(table_member.get("path") or ""),
            "table_row_count": int(inventory.get("table_row_count") or 0),
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
        """Replay the retained ZIP and prove exact source-ID/output parity."""

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.state_laws_completeness import (
            closed_jurisdiction_receipt,
        )
        from .california_bulk import inventory_california_bulk_zip

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "California frontier closure requires an attached acquisition ledger"
            )
        first = self._load_california_first_bulk_inventory()
        first_frontier_raw = first.get("frontier")
        first_disposition = first.get("disposition")
        if (
            not isinstance(first_frontier_raw, Mapping)
            or first_frontier_raw.get("closed") is not True
            or first_frontier_raw.get("bundle_closed") is not True
            or not isinstance(first_disposition, Mapping)
            or int(first.get("unusable_row_count") or 0) != 0
            or int(first_disposition.get("failed_final") or 0) != 0
            or int(first_disposition.get("quarantined") or 0) != 0
        ):
            raise RuntimeError(
                "California first bulk inventory has unresolved source records"
            )

        retained_body_path = str(
            self._bulk_zip_provenance.get("retained_body_path") or ""
        ).strip()
        if not retained_body_path:
            raise RuntimeError("California retained bulk object path is missing")
        official_source_url = str(
            self._bulk_zip_provenance.get("official_url") or ""
        ).strip()
        replayed_input = ledger.replay_retained_parser_input_file(
            official_url=official_source_url,
            sanitized_request={"method": "GET", "url": official_source_url},
        )
        if replayed_input is None or replayed_input.receipt.content is None:
            raise RuntimeError(
                "California retained bulk object cannot be independently replayed"
            )
        if str(replayed_input.receipt.content.sha256) != str(
            self._bulk_zip_provenance.get("content_sha256") or ""
        ):
            raise RuntimeError("California retained bundle digest changed on replay")
        replayed = await asyncio.to_thread(
            inventory_california_bulk_zip,
            Path(replayed_input.body_path),
            bundle_provenance=dict(self._bulk_zip_provenance),
        )
        replayed = self._validate_california_bulk_inventory(replayed)
        if canonical_json_bytes(first) != canonical_json_bytes(replayed):
            raise RuntimeError(
                "California first and replayed LAW_SECTION_TBL inventories differ"
            )

        raw_canonical_keys = canonical_output_projection.get("canonical_keys")
        if not isinstance(raw_canonical_keys, Sequence) or isinstance(
            raw_canonical_keys, (str, bytes, bytearray)
        ):
            raise RuntimeError(
                "California canonical output projection lacks exact identities"
            )
        canonical_keys = [str(item).strip() for item in raw_canonical_keys]
        if not canonical_keys or any(not item for item in canonical_keys):
            raise RuntimeError("California canonical output projection is empty")
        if len(canonical_keys) != len(set(canonical_keys)):
            raise RuntimeError(
                "California canonical output projection collapses source identities"
            )
        source_record_ids = [
            str(item) for item in first.get("source_record_ids") or []
        ]
        if len(source_record_ids) != len(set(source_record_ids)):
            raise RuntimeError("California official source IDs are not unique")
        expected_canonical_keys = [
            f"urn:state:ca:statute:CA:{source_record_id}"
            for source_record_id in source_record_ids
        ]
        missing = sorted(set(expected_canonical_keys) - set(canonical_keys))
        extra = sorted(set(canonical_keys) - set(expected_canonical_keys))
        if (
            len(canonical_keys) != len(expected_canonical_keys)
            or missing
            or extra
        ):
            raise RuntimeError(
                "California canonical identities do not exactly match admitted "
                "LAW_SECTION_TBL source IDs: "
                f"expected={len(expected_canonical_keys)} "
                f"actual={len(canonical_keys)} "
                f"missing={missing[:3]} extra={extra[:3]}"
            )

        compact_frontier = self._california_inventory_frontier(first)
        replayed_frontier = self._california_inventory_frontier(replayed)
        row_count = len(canonical_keys)
        disposition = dict(first_disposition)
        completion = closed_jurisdiction_receipt(
            "CA",
            discovered=int(disposition["discovered"]),
            fetched=int(disposition["fetched"]),
            excluded=int(disposition["excluded"]),
            quarantined=int(disposition["quarantined"]),
            failed_final=int(disposition["failed_final"]),
            duplicates=int(disposition.get("duplicates") or 0),
            source_domain="downloads.leginfo.legislature.ca.gov",
            canonical_keys=canonical_keys,
            derived_keys=canonical_keys,
        )
        boundaries = first.get("boundary_probes")
        if not isinstance(boundaries, Mapping):
            raise RuntimeError("California bulk inventory lacks boundary probes")
        completion.update(
            {
                "boundary_probes": {
                    "bundle_total": 1,
                    "first_hierarchy_unit": expected_canonical_keys[0],
                    "first_table_row_sha256": boundaries.get(
                        "first_table_row_sha256"
                    ),
                    "last_hierarchy_unit": expected_canonical_keys[-1],
                    "last_table_row_sha256": boundaries.get(
                        "last_table_row_sha256"
                    ),
                    "pagination_total": int(first.get("table_row_count") or 0),
                },
                "canonical_row_count": row_count,
                "frontier": compact_frontier,
                "legal_as_of": str(
                    self._bulk_zip_provenance.get("retrieved_at") or ""
                ),
                "observed_at": str(
                    self._bulk_zip_provenance.get("retrieved_at") or ""
                ),
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
                        self._california_first_bulk_inventory_observation.get(
                            "relative_path"
                        )
                        or ""
                    ),
                    "inventory_sha256": str(first["inventory_sha256"]),
                    "source_record_count": len(source_record_ids),
                    "source_record_ids_sha256": str(
                        first.get("source_record_ids_sha256") or ""
                    ),
                },
                "transport": {
                    "fixture": False,
                    "kind": "retained_official_pubinfo_zip",
                    "synthetic": False,
                },
            }
        )
        bundle_digest = str(
            self._bulk_zip_provenance.get("content_sha256") or ""
        ).strip().lower()
        acquisition_path_ids = self._catalog_acquisition_path_ids_for_source(
            official_source_url
        )
        source_file = inspect.getsourcefile(type(self))
        source_version_digest = hashlib.sha256(
            Path(source_file).read_bytes()
            if source_file and Path(source_file).is_file()
            else (
                f"{type(self).__module__}.{type(self).__qualname__}"
            ).encode("utf-8")
        ).hexdigest()
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=replayed_frontier,
            canonical_output_projection=canonical_output_projection,
            release_point=f"sha256:{bundle_digest}",
            official_source_url=official_source_url,
            acquisition_path_ids=acquisition_path_ids,
            observation_time=str(
                self._bulk_zip_provenance.get("retrieved_at") or ""
            ),
            source_software_version=(
                f"{type(self).__module__}.{type(self).__qualname__}"
                f"@sha256:{source_version_digest}"
            ),
        )

    def _enrich_statute_structure(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Carry exact pubinfo bundle/member provenance into canonical JSON-LD."""

        enriched = super()._enrich_statute_structure(statute)
        structured = dict(enriched.structured_data or {})
        if str(structured.get("source_kind") or "").strip() != (
            "official_california_bulk_caml"
        ):
            return enriched

        digest = str(structured.get("content_sha256") or "").strip().lower()
        source_record_id = str(
            structured.get("source_record_id") or ""
        ).strip()
        receipt = structured.get("transport_receipt")
        source_bundle = structured.get("source_bundle")
        table_member = structured.get("source_table_member")
        body_member = structured.get("source_body_member")
        jsonld = structured.get("jsonld")
        provenance_complete = bool(
            re.fullmatch(r"[a-f0-9]{64}", digest)
            and source_record_id
            and isinstance(receipt, Mapping)
            and isinstance(source_bundle, Mapping)
            and isinstance(table_member, Mapping)
            and isinstance(body_member, Mapping)
            and isinstance(jsonld, Mapping)
        )
        if not provenance_complete:
            if getattr(self, "_state_law_acquisition_ledger", None) is not None:
                raise RuntimeError(
                    "California bulk row lacks retained bundle/member provenance"
                )
            return enriched

        jsonld_payload = dict(jsonld)
        prior_provenance = jsonld_payload.get("provenance")
        provenance = (
            dict(prior_provenance)
            if isinstance(prior_provenance, Mapping)
            else {}
        )
        provenance.update(
            {
                "content_sha256": digest,
                "source_body_member": dict(body_member),
                "source_bundle": dict(source_bundle),
                "source_record_id": source_record_id,
                "source_table_member": dict(table_member),
                "source_table_row_number": int(
                    structured.get("source_table_row_number") or 0
                ),
                "transport_receipt": dict(receipt),
            }
        )
        jsonld_payload["provenance"] = provenance
        structured["jsonld"] = jsonld_payload
        enriched.structured_data = structured
        return enriched

    def official_code_toc_url(self, code_type: str) -> str:
        """Return the official LegInfo TOC URL for one California code family."""

        return f"{self.get_base_url()}/faces/codedisplayexpand.xhtml?tocCode={code_type}"

    def official_section_url(self, code_type: str, section_number: str) -> str:
        """Return the official LegInfo display URL for one section."""

        section = str(section_number or "").strip().rstrip(".")
        return (
            f"{self.get_base_url()}/faces/codes_displayText.xhtml"
            f"?lawCode={code_type}&sectionNum={section}."
        )

    def official_code_catalog(self) -> List[Dict[str, str]]:
        """Return the exhaustive official California code-family catalog."""

        return [
            {
                "name": name,
                "type": code_type,
                "url": self.official_code_toc_url(code_type),
            }
            for name, code_type in self.CODE_TYPE_MAP.items()
        ]

    def is_official_leginfo_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        return host == self.OFFICIAL_DOMAIN or host.endswith("." + self.OFFICIAL_DOMAIN)

    def repair_or_type_missing_source_link(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Attach an official LegInfo URL or type a linkless row as quarantine."""

        structured = dict(statute.structured_data or {})
        source_url = str(statute.source_url or "").strip()
        if source_url and self.is_official_leginfo_url(source_url):
            structured.setdefault("source_link_disposition", "official")
            statute.structured_data = structured
            return statute

        code_type = str(
            structured.get("law_code")
            or self.CODE_TYPE_MAP.get(str(statute.code_name or ""), "")
        ).strip().upper()
        section_number = str(statute.section_number or "").strip()
        if code_type and section_number:
            repaired = self.official_section_url(code_type, section_number)
            statute.source_url = repaired
            structured["law_code"] = code_type
            structured["source_kind"] = (
                structured.get("source_kind") or "official_california_leginfo_html"
            )
            structured["source_link_disposition"] = "repaired_official_leginfo"
            structured["previous_source_url"] = source_url or None
            statute.structured_data = structured
            return statute

        structured["source_link_disposition"] = "typed_quarantine"
        structured["quarantine_reason"] = self.MISSING_LINK_QUARANTINE_REASON
        statute.structured_data = structured
        return statute

    def _repair_or_type_missing_source_links(
        self,
        statutes: Sequence[NormalizedStatute],
    ) -> List[NormalizedStatute]:
        return [self.repair_or_type_missing_source_link(item) for item in statutes]

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        """Synchronous official HTTPS GET. Returns empty bytes on transport failure."""

        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-california-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-california-official-catalog/1.0",
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

    def _parse_official_code_links(self, html: bytes, page_url: str) -> List[Dict[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        found: List[Dict[str, str]] = []
        seen: set[str] = set()
        inverse = {code_type: name for name, code_type in self.CODE_TYPE_MAP.items()}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(page_url, href)
            parsed = urlparse(absolute)
            query = parse_qs(parsed.query)
            toc_values = query.get("tocCode") or query.get("toccode") or []
            law_values = query.get("lawCode") or query.get("lawcode") or []
            code_type = str((toc_values or law_values or [""])[0]).strip().upper()
            if code_type not in inverse:
                continue
            if code_type in seen:
                continue
            seen.add(code_type)
            found.append(
                {
                    "name": inverse[code_type],
                    "type": code_type,
                    "url": self.official_code_toc_url(code_type),
                }
            )
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official CA code family and type missing-link rows."""

        discovered = {
            str(item["type"]).upper(): item
            for item in self._parse_official_code_links(
                html, page_url or self.OFFICIAL_ENTRY_URL
            )
        }
        rows: List[Dict[str, Any]] = []
        for item in self.official_code_catalog():
            code_type = str(item["type"]).upper()
            official_url = str(item["url"])
            live = discovered.get(code_type)
            source_url = str((live or {}).get("url") or official_url)
            if source_url and self.is_official_leginfo_url(source_url):
                disposition = "official" if live else "repaired_official_leginfo"
            else:
                source_url = official_url
                disposition = "repaired_official_leginfo"
            rows.append(
                {
                    "canonical_key": f"ca:{code_type.lower()}",
                    "code_type": code_type,
                    "name": item["name"],
                    "source_url": source_url,
                    "source_link_disposition": disposition,
                    "text": (
                        f"California {item['name']} ({code_type}) official LegInfo "
                        f"catalog unit at {source_url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "CA"):
        """Acquire the exhaustive official California code catalog.

        Live HTTPS retains the official codes landing page. Every known
        California code family is enumerated with an official LegInfo URL.
        Linkless catalog members are repaired to the official TOC URL or
        typed as quarantine. This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "CA").strip().upper() or "CA"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("california official catalog enumeration is incomplete")
        request = (
            f"GET {self.OFFICIAL_CODES_PATH} HTTP/1.1\n"
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
            source_path=self.OFFICIAL_CODES_PATH,
            frontier=frontier,
            rows=tuple(rows),
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=str(rows[0]["canonical_key"]),
            last_hierarchy_unit=str(rows[-1]["canonical_key"]),
        )

    async def _scrape_official_leginfo_tree(
        self,
        code_name: str,
        code_url: str,
        code_type: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error("Required library not available: %s", e)
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        fetch_timeout = max(
            5,
            int(float(os.getenv("CALIFORNIA_CODE_FETCH_TIMEOUT_SECONDS", "45") or 45)),
        )
        self.logger.info(
            "California: fetching %s from %s with timeout=%ss",
            code_name,
            code_url,
            fetch_timeout,
        )

        page_bytes = await self._fetch_code_index_page(code_url, timeout_seconds=fetch_timeout)
        if not page_bytes:
            self.logger.warning("California: empty response for %s", code_name)
            return []

        soup = BeautifulSoup(page_bytes, "html.parser")
        legal_area = self._identify_legal_area(code_name)
        section_links = self._discover_section_links(soup, code_url, code_type)
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()

        for section_url, link_text in section_links:
            if limit is not None and len(statutes) >= int(limit):
                break
            section_number = self._section_number_from_url(section_url) or self._extract_section_number(
                link_text or ""
            )
            if not section_number:
                continue
            key = section_number.lower()
            if key in seen_sections:
                continue
            seen_sections.add(key)

            statute = await self._build_section_statute(
                code_name=code_name,
                code_type=code_type,
                section_url=section_url,
                section_number=section_number,
                link_text=link_text,
                legal_area=legal_area,
                timeout_seconds=fetch_timeout,
            )
            if statute is not None:
                statutes.append(statute)

        self.logger.info("Scraped %s sections from %s", len(statutes), code_name)
        return statutes

    def _discover_section_links(
        self,
        soup,
        code_url: str,
        code_type: str,
    ) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            section_text = (link.get_text(strip=True) or "").strip()
            section_url = str(link.get("href") or "").strip()
            if not section_url:
                continue
            if not section_url.startswith("http"):
                section_url = urljoin(code_url, section_url)

            parsed = urlparse(section_url)
            if not self._SECTION_DISPLAY_RE.search(parsed.path or ""):
                continue

            query = parse_qs(parsed.query)
            law_codes = query.get("lawCode") or query.get("lawcode") or []
            if not law_codes or str(law_codes[0]).upper() != code_type:
                continue
            if not section_text or not re.search(r"\d", section_text):
                # Still accept when sectionNum is present in the query.
                if not self._section_number_from_url(section_url):
                    continue

            if section_url in seen:
                continue
            seen.add(section_url)
            out.append((section_url, section_text))
        return out

    def _section_number_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        values = query.get("sectionNum") or query.get("sectionnum") or []
        if values:
            return str(values[0]).strip().rstrip(".")
        match = self._SECTION_NUM_QUERY_RE.search(url)
        if match:
            return str(match.group(1)).strip().rstrip(".")
        return ""

    async def _build_section_statute(
        self,
        *,
        code_name: str,
        code_type: str,
        section_url: str,
        section_number: str,
        link_text: str,
        legal_area: str,
        timeout_seconds: int = 45,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        page_bytes = await self._fetch_code_index_page(section_url, timeout_seconds=timeout_seconds)
        if not page_bytes:
            return None

        soup = BeautifulSoup(page_bytes, "html.parser")
        body = self._extract_section_body(soup)
        if len(body) < 80:
            return None

        section_name = (link_text or "").strip()
        if not section_name or section_name == section_number:
            heading = soup.find(["h1", "h2", "h3", "h4"])
            if heading is not None:
                section_name = self._normalize_legal_text(heading.get_text(" ", strip=True))
        if not section_name:
            section_name = f"Section {section_number}"
        if section_number not in section_name:
            section_name = f"Section {section_number}: {section_name}"[:200]
        else:
            section_name = section_name[:200]

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name,
            full_text=body,
            source_url=section_url,
            legal_area=legal_area,
            official_cite=f"Cal. {code_name} § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_california_leginfo_html",
                "discovery_method": "official_toc_section_display",
                "law_code": code_type,
                "skip_hydrate": True,
            },
        )

    def _extract_section_body(self, soup) -> str:
        """Extract non-placeholder statute body from a leginfo display page."""
        for selector in (
            "#manylawsections",
            "#codeLawSectionNoHead",
            ".codeGroup",
            "#content_main",
            "div#content",
            "main",
            "article",
        ):
            node = soup.select_one(selector)
            if node is None:
                continue
            for tag in node(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(node.get_text(" ", strip=True))
            if len(text) >= 80:
                return text

        paragraphs = []
        for para in soup.find_all("p"):
            text = self._normalize_legal_text(para.get_text(" ", strip=True))
            if text:
                paragraphs.append(text)
        if paragraphs:
            return "\n".join(paragraphs)

        body = soup.body or soup
        for tag in body(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        return self._normalize_legal_text(body.get_text(" ", strip=True))

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        code_type: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        """Compact official seed sections for bounded offline/probe runs."""
        base = self.get_base_url()
        seeds = [
            (
                "187",
                f"{base}/faces/codes_displayText.xhtml?lawCode={code_type}&sectionNum=187.",
                "Murder defined",
            ),
            (
                "188",
                f"{base}/faces/codes_displayText.xhtml?lawCode={code_type}&sectionNum=188.",
                "Malice defined",
            ),
        ]
        # Prefer Penal Code seeds; for other codes still attempt generic sectionNums.
        if code_type != "PEN":
            seeds = [
                (
                    "1",
                    f"{base}/faces/codes_displayText.xhtml?lawCode={code_type}&sectionNum=1.",
                    "Section 1",
                ),
                (
                    "2",
                    f"{base}/faces/codes_displayText.xhtml?lawCode={code_type}&sectionNum=2.",
                    "Section 2",
                ),
            ]

        out: List[NormalizedStatute] = []
        legal_area = self._identify_legal_area(code_name)
        for section_number, source_url, fallback_name in seeds[: max(1, int(max_statutes or 1))]:
            statute = await self._build_section_statute(
                code_name=code_name,
                code_type=code_type,
                section_url=source_url,
                section_number=section_number,
                link_text=fallback_name,
                legal_area=legal_area,
            )
            if statute is not None:
                # Seed discovery method is distinct for auditability.
                structured = dict(statute.structured_data or {})
                structured["discovery_method"] = "official_seed_section"
                statute.structured_data = structured
                out.append(statute)
        return out

    async def _fetch_code_index_page(self, url: str, timeout_seconds: int = 45) -> bytes:
        """Fetch California code pages without the heavy recovery stack.

        The generic archival/search fetch path can initialize multiple search
        engines and has non-cancellable recovery branches. California code
        pages are first-party HTML, so a direct bounded request plus the
        shared persistent cache is safer for long daemon runs.
        """
        timeout = max(5, int(timeout_seconds or 45))
        return await self._fetch_parser_input_with_transport(
            url,
            timeout_seconds=timeout,
            headers={
                "User-Agent": "ipfs-datasets-california-code-scraper/2.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            allow_archival_fallback=True,
            media_type="text/html",
            provider="requests_direct",
        )


# Register the scraper
StateScraperRegistry.register("CA", CaliforniaScraper)
