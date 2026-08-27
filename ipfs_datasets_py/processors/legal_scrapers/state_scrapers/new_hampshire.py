"""Scraper for New Hampshire state laws.

This module contains the scraper for New Hampshire statutes from the official state legislative website.
"""

import hashlib
import inspect
import json
import os
import re
import ssl
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StatuteMetadata,
    current_partial_checkpoint_run_directory,
)
from .registry import StateScraperRegistry


class NewHampshireScraper(BaseStateScraper):
    """Scraper for New Hampshire state laws from gencourt/gc.nh.gov sources."""

    _NH_STATUTE_URL_RE = re.compile(
        r"/rsa/html/(?:NHTOC/[^/?#]+\.htm|(?:[^/?#]+/)+[^/?#]+\.htm)$",
        re.IGNORECASE,
    )
    _NH_TITLE_TEXT_RE = re.compile(r"^TITLE\s+([A-Z0-9-]+)\s*:\s*(.+)$", re.IGNORECASE)
    _NH_CHAPTER_TEXT_RE = re.compile(r"^CHAPTER\s+([0-9A-Z-]+)\s*:\s*(.+)$", re.IGNORECASE)
    _NH_SECTION_LINK_RE = re.compile(r"^Section\s+([0-9A-Z:.-]+)\s+(.+)$", re.IGNORECASE)

    _DIRECT_FETCH_HOST_MARKERS = (
        "web.archive.org/web/",
        "www.gencourt.state.nh.us/",
        "gc.nh.gov/",
    )
    _NH_SECTIONISH_ARCHIVE_RE = re.compile(
        r"/rsa/html/(?!nhtoc/)(?:[ivxlcdm0-9a-z-]+/){2,}[0-9a-z:.-]+\.htm$",
        re.IGNORECASE,
    )
    OFFICIAL_DOMAIN = "gc.nh.gov"
    OFFICIAL_ENTRY_PATH = "/rsa/html/NHTOC.htm"
    # The legacy root is already retained with exact acquisition evidence and
    # remains the stable catalog bootstrap.  The General Court migrated its
    # live RSA tree to gc.nh.gov; every descendant locator is canonicalized to
    # that current official host below instead of equating the two request
    # identities.
    OFFICIAL_ENTRY_URL = "https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm"
    CURRENT_OFFICIAL_ENTRY_URL = "https://gc.nh.gov/rsa/html/NHTOC.htm"
    _NH_TITLE_HREF_RE = re.compile(
        r"/rsa/html/NHTOC/NHTOC-([IVXLCDM]+(?:-[A-Z]+)?)\.htm$",
        re.IGNORECASE,
    )
    _NH_TITLE_LABEL_RE = re.compile(
        r"\bTITLE\s+([IVXLCDM]+(?:-[A-Z]+)?)\b",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("I", "The State and Its Government"),
        ("II", "Counties"),
        ("III", "Towns, Cities, Village Districts, and Unincorporated Places"),
        ("IV", "Elections"),
        ("V", "Taxation"),
        ("VI", "Public Officers and Employees"),
        ("VII", "Sheriffs, Constables, and Police Officers"),
        ("VIII", "Public Defense and Veterans' Affairs"),
        ("IX", "Acquisition of Lands by United States; Federal Aid"),
        ("X", "Public Health"),
        ("XI", "Hospitals and Sanitaria"),
        ("XII", "Public Safety and Welfare"),
        ("XIII", "Alcoholic Beverages"),
        ("XIV", "Milk and Milk Products"),
        ("XV", "Education"),
        ("XVI", "Libraries"),
        ("XVII", "Housing and Redevelopment"),
        ("XVIII", "Fish and Game"),
        ("XIX", "Public Recreation"),
        ("XIX-A", "Forestry"),
        ("XX", "Transportation"),
        ("XXI", "Motor Vehicles"),
        ("XXII", "Navigation; Harbors; Coast Survey"),
        ("XXIII", "Labor"),
        ("XXIV", "Games, Amusements, and Athletic Exhibitions"),
        ("XXV", "Holidays"),
        ("XXVI", "Cemeteries; Burials; Dead Bodies"),
        ("XXVII", "Corporations, Associations, and Proprietors of Common Lands"),
        ("XXVIII", "Partnerships"),
        ("XXIX", "Religious Societies"),
        ("XXX", "Occupations and Professions"),
        ("XXXI", "Trade and Commerce"),
        ("XXXII", "Chattel Mortgages"),
        ("XXXIII", "Conditional Sales"),
        ("XXXIII-A", "Retail Installment Sales"),
        ("XXXIV", "Public Utilities"),
        ("XXXIV-A", "Uniform Commercial Code"),
        ("XXXV", "Banks and Banking; Loan Associations; Credit Unions"),
        ("XXXVI", "Pawnbrokers and Moneylenders"),
        ("XXXVII", "Insurance"),
        ("XXXVIII", "Securities"),
        ("XXXIX", "Aeronautics"),
        ("XL", "Agriculture, Horticulture and Animal Husbandry"),
        ("XLI", "Liens"),
        ("XLII", "Notaries, Commissioners, Justices of the Peace, and Acknowledgments"),
        ("XLIII", "Domestic Relations"),
        ("XLIV", "Guardians and Conservators"),
        ("XLV", "Animals"),
        ("XLVI", "Lost Property; Strays"),
        ("XLVII", "Boundaries, Fences and Common Fields"),
        ("XLVIII", "Conveyances and Mortgages of Realty"),
        ("XLIX", "Homesteads"),
        ("L", "Water Management and Protection"),
        ("LI", "Courts"),
        ("LII", "Actions, Process, and Service of Process"),
        ("LIII", "Proceedings in Court"),
        ("LIV", "Executions, Levies, Bail, and the Relief of Poor Debtors"),
        ("LV", "Proceedings in Special Cases"),
        ("LVI", "Probate Courts and Decedents' Estates"),
        ("LVII", "Insolvency Proceedings and Assignments for Creditors"),
        ("LVIII", "Public Justice"),
        ("LIX", "Proceedings in Criminal Cases"),
        ("LX", "Correction and Punishment"),
        ("LXI", "Acts Repealed"),
        ("LXII", "Criminal Code"),
        ("LXIII", "Elections"),
        ("LXIV", "Planning and Zoning"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)
    # The retained official root classifies Title IV itself, rather than a
    # fetched child document, as terminal.  Keep this projection explicit so
    # loss or broadening of the source label cannot silently change the 66-page
    # active title frontier.
    OFFICIAL_TERMINAL_TITLES = (("IV", "repealed"),)
    OFFICIAL_TERMINAL_TITLE_COUNT = len(OFFICIAL_TERMINAL_TITLES)
    OFFICIAL_ACTIVE_TITLE_COUNT = (
        OFFICIAL_TITLE_COUNT - OFFICIAL_TERMINAL_TITLE_COUNT
    )

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind the exact RSA hierarchy parser into closure identity."""

        from . import new_hampshire_section

        return (new_hampshire_section,)
    
    def get_base_url(self) -> str:
        """Return the base URL for New Hampshire's legislative website."""
        return "https://gc.nh.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for New Hampshire."""
        return [{
            "name": "New Hampshire Revised Statutes",
            "url": f"{self.get_base_url()}/rsa/html/NHTOC.htm",
            "type": "Code"
        }]

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = self._normalize_wayback_like_url(str(statute.source_url or ""))
            statute.source_url = source
            if self._NH_STATUTE_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from New Hampshire's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .new_hampshire_constitution import (
            configured_constitution_html_path,
            parse_new_hampshire_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_new_hampshire_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "New Hampshire Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .new_hampshire_section import (
            configured_section_html_path,
            parse_configured_new_hampshire_sections,
            parse_new_hampshire_section_html,
        )

        local_rows = parse_configured_new_hampshire_sections(
            code_name=code_name,
            max_statutes=limit,
        )
        if local_rows:
            return local_rows if limit is None else local_rows[: int(limit)]
        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_new_hampshire_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://www.gencourt.state.nh.us/rsa/html/LXII/630/630-1.htm",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/rsa/html/NHTOC.htm",
            f"{self.get_base_url()}/rsa/html/",
            "https://gc.nh.gov/rsa/html/NHTOC.htm",
            "https://gc.nh.gov/rsa/html/",
            "http://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
            "http://web.archive.org/web/20250101000000/https://gc.nh.gov/rsa/html/NHTOC.htm",
            "https://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
            "https://web.archive.org/web/20250101000000/https://gc.nh.gov/rsa/html/NHTOC.htm",
        ]
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        full_corpus_unbounded = self._full_corpus_enabled() and max_statutes is None
        if full_corpus_unbounded:
            return await self._scrape_official_rsa_tree_batched(
                code_name=code_name,
                checkpoint=_NewHampshireCheckpoint(self.state_code),
            )
        official = await self._scrape_official_rsa_tree(code_name, max_statutes=limit)
        if official:
            return official if limit is None else official[: int(limit)]

        return_threshold = limit if limit is not None else self._bounded_return_threshold(160)
        if max_statutes is not None:
            return_threshold = max(1, min(int(return_threshold), int(max_statutes)))
        full_corpus_unbounded = self._full_corpus_enabled() and max_statutes is None
        checkpoint = _NewHampshireCheckpoint(self.state_code)

        # Keep archive discovery bounded so full-corpus runs do not request an
        # effectively unbounded CDX window.
        if full_corpus_unbounded:
            full_corpus_discovery_limit_raw = str(
                os.getenv("STATE_SCRAPER_NH_ARCHIVE_DISCOVERY_LIMIT", "1200") or "1200"
            ).strip()
            try:
                discovery_limit = int(full_corpus_discovery_limit_raw) if full_corpus_discovery_limit_raw else 1200
            except Exception:
                discovery_limit = 1200
            discovery_limit = max(120, min(2500, discovery_limit))
        else:
            discovery_limit = max(10, return_threshold)
        discovered_archive_candidates = await self._discover_archived_rsa_urls(limit=discovery_limit)
        full_corpus_max_candidates_raw = str(
            os.getenv("STATE_SCRAPER_NH_FULL_CORPUS_MAX_CANDIDATES", "120") or "120"
        ).strip()
        try:
            full_corpus_max_candidates = int(full_corpus_max_candidates_raw) if full_corpus_max_candidates_raw else 120
        except Exception:
            full_corpus_max_candidates = 120
        full_corpus_max_candidates = max(12, min(800, full_corpus_max_candidates))
        for archived in discovered_archive_candidates:
            normalized_archived = self._normalize_wayback_like_url(str(archived or ""))
            if not normalized_archived:
                continue
            if full_corpus_unbounded and not self._is_archived_index_candidate(normalized_archived):
                continue
            if normalized_archived not in candidate_urls:
                candidate_urls.append(normalized_archived)
            if full_corpus_unbounded and len(candidate_urls) >= full_corpus_max_candidates:
                break

        resumed_statutes = checkpoint.load(
            default_state_name=self.state_name,
            default_code_name=code_name,
            max_statutes=None if full_corpus_unbounded else max(20, return_threshold * 4),
        )

        archived_title_kwargs: Dict[str, Any] = {
            "max_statutes": None if full_corpus_unbounded else max(10, return_threshold),
        }
        if "checkpoint" in inspect.signature(self._scrape_archived_title_stubs).parameters:
            archived_title_kwargs["checkpoint"] = checkpoint
        archived_title_stubs = await self._scrape_archived_title_stubs(
            code_name,
            **archived_title_kwargs,
        )

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        _merge(resumed_statutes)
        if resumed_statutes:
            checkpoint.maybe_write(merged, code_name=code_name, stage_label="resume-seed")

        _merge(archived_title_stubs)
        if archived_title_stubs:
            checkpoint.maybe_write(merged, code_name=code_name, stage_label="archived-title-stubs")
            if full_corpus_unbounded:
                checkpoint.write(
                    merged,
                    code_name=code_name,
                    stage_label="complete",
                    progress={
                        "codes_completed": 1,
                        "codes_total": 1,
                    },
                )
                self.logger.info(
                    "New Hampshire full-corpus archived crawl: statutes=%s; skipping generic fallback sweep",
                    len(merged),
                )
                return merged
        if not full_corpus_unbounded and len(merged) >= return_threshold:
            return merged

        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_archived_seed_sections(code_name, max_statutes=return_threshold)
            if direct:
                return direct[:return_threshold]

        full_corpus_stagnation_cap_raw = str(
            os.getenv("STATE_SCRAPER_NH_MAX_STAGNANT_CANDIDATES", "20") or "20"
        ).strip()
        try:
            full_corpus_stagnation_cap = int(full_corpus_stagnation_cap_raw) if full_corpus_stagnation_cap_raw else 20
        except Exception:
            full_corpus_stagnation_cap = 20
        full_corpus_stagnation_cap = max(4, min(200, full_corpus_stagnation_cap))
        bounded_stagnation_cap_raw = str(
            os.getenv("STATE_SCRAPER_NH_MAX_STAGNANT_CANDIDATES_BOUNDED", "8") or "8"
        ).strip()
        try:
            bounded_stagnation_cap = int(bounded_stagnation_cap_raw) if bounded_stagnation_cap_raw else 8
        except Exception:
            bounded_stagnation_cap = 8
        bounded_stagnation_cap = max(2, min(64, bounded_stagnation_cap))
        stagnant_candidates = 0

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            merged_before = len(merged)

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "N.H. Rev. Stat.",
                max_sections=max(10, return_threshold),
            )
            statutes = self._filter_section_level(statutes)
            if self._full_corpus_enabled():
                statutes = [
                    row
                    for row in statutes
                    if not self._looks_like_secondary_url(str(row.source_url or ""))
                ]
            _merge(statutes)
            if statutes:
                checkpoint.maybe_write(merged, code_name=code_name, stage_label=f"candidate:{candidate}")
            if not full_corpus_unbounded and len(merged) >= return_threshold:
                return merged
            if full_corpus_unbounded:
                if len(merged) <= merged_before:
                    stagnant_candidates += 1
                    if stagnant_candidates >= full_corpus_stagnation_cap:
                        self.logger.info(
                            "New Hampshire full-corpus fallback: stopping after %s stagnant candidates with statutes_so_far=%s",
                            stagnant_candidates,
                            len(merged),
                        )
                        break
                else:
                    stagnant_candidates = 0
            else:
                if len(merged) <= merged_before:
                    stagnant_candidates += 1
                    if merged and stagnant_candidates >= bounded_stagnation_cap:
                        self.logger.info(
                            "New Hampshire bounded fallback: stopping after %s stagnant candidates with statutes_so_far=%s",
                            stagnant_candidates,
                            len(merged),
                        )
                        break
                else:
                    stagnant_candidates = 0

        checkpoint.write(
            merged,
            code_name=code_name,
            stage_label="complete",
            progress={
                "codes_completed": 1 if merged else 0,
                "codes_total": 1,
            },
        )
        return merged

    def _new_hampshire_frontier_batch_size(self) -> int:
        return max(
            1,
            min(
                1024,
                int(
                    self._env_int(
                        "STATE_SCRAPER_NH_FRONTIER_BATCH_SIZE",
                        default=512,
                    )
                    or 512
                ),
            ),
        )

    def _new_hampshire_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                int(
                    self._env_int(
                        "STATE_SCRAPER_NH_FRONTIER_CONCURRENCY",
                        default=12,
                    )
                    or 12
                ),
            ),
        )

    def _record_new_hampshire_frontier_inputs(
        self,
        *,
        source_role: str,
        urls: Sequence[str],
        payloads: Sequence[bytes],
    ) -> None:
        """Retain the ordered URL/body projection used by one exact traversal."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if len(requested) != len(payloads):
            raise RuntimeError(
                "New Hampshire frontier input projection is not aligned"
            )
        reports = list(
            getattr(self, "_new_hampshire_frontier_input_reports", [])
        )
        seen = {str(row.get("source_url") or "") for row in reports}
        for url, payload in zip(requested, payloads, strict=True):
            if not url or url in seen:
                raise RuntimeError(
                    "New Hampshire frontier input projection repeated a URL: "
                    f"{url}"
                )
            raw = bytes(payload or b"")
            if not raw:
                raise RuntimeError(
                    f"New Hampshire frontier input projection is empty: {url}"
                )
            seen.add(url)
            reports.append(
                {
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "source_role": str(source_role or "").strip(),
                    "source_url": url,
                }
            )
        self._new_hampshire_frontier_input_reports = reports

    @staticmethod
    def _new_hampshire_root_payload(payload: bytes) -> bool:
        sample = bytes(payload or b"")[:500_000].lower()
        return (
            b"new hampshire statutes" in sample
            and b"table of contents" in sample
            and b"nhtoc/nhtoc-" in sample
        )

    @staticmethod
    def _new_hampshire_title_payload(payload: bytes) -> bool:
        sample = bytes(payload or b"")[:500_000].lower()
        return (
            b"new hampshire statutes" in sample
            and b"table of contents" in sample
            and (b"chapter" in sample or b"entire title was repealed" in sample)
        )

    @staticmethod
    def _new_hampshire_chapter_payload(payload: bytes) -> bool:
        sample = bytes(payload or b"")[:500_000].lower()
        return (
            b"new hampshire statutes" in sample
            and b"chapter" in sample
            and (
                b"section" in sample
                or b"repealed" in sample
                or b"reserved" in sample
                or b"omitted" in sample
            )
        )

    @staticmethod
    def _new_hampshire_section_payload(payload: bytes) -> bool:
        sample = bytes(payload or b"")[:500_000].lower()
        return b"<codesect" in sample and b"section" in sample

    def _validate_new_hampshire_aligned_evidence(
        self,
        *,
        url: str,
        payload: bytes,
        transport_receipt: Optional[Dict[str, Any]],
        parser_input_envelope: Any,
        frontier_name: str,
    ) -> None:
        """Bind optional transport evidence to its exact aligned NH payload."""

        canonical_url = self._canonical_fetch_url(url)
        digest = hashlib.sha256(payload).hexdigest()
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if ledger_attached and (
            not isinstance(transport_receipt, Mapping)
            or not transport_receipt
            or parser_input_envelope is None
        ):
            raise RuntimeError(
                f"New Hampshire {frontier_name} frontier lacks retained receipt/envelope evidence: {url}"
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
                    f"New Hampshire {frontier_name} receipt lacks exact URL/digest evidence: {url}"
                )
            if observed_url and self._canonical_fetch_url(observed_url) != canonical_url:
                raise RuntimeError(
                    f"New Hampshire {frontier_name} receipt changed URL identity: {url}"
                )
            if observed_digest and observed_digest != digest:
                raise RuntimeError(
                    f"New Hampshire {frontier_name} receipt changed payload identity: {url}"
                )
        if parser_input_envelope is not None:
            envelope_body = getattr(parser_input_envelope, "body", None)
            if ledger_attached and envelope_body is None:
                raise RuntimeError(
                    f"New Hampshire {frontier_name} envelope lacks exact body evidence: {url}"
                )
            if envelope_body is not None and bytes(envelope_body) != payload:
                raise RuntimeError(
                    f"New Hampshire {frontier_name} envelope changed payload identity: {url}"
                )

    async def _fetch_new_hampshire_frontier_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Callable[[bytes], bool],
    ) -> List[bytes]:
        """Fetch one exact NH frontier through the shared grouped-WARC seam."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if any(not url for url in requested):
            raise RuntimeError(
                f"New Hampshire {frontier_name} frontier contains an invalid URL"
            )
        if len(set(requested)) != len(requested):
            raise RuntimeError(
                f"New Hampshire {frontier_name} frontier contains duplicate URLs"
            )
        if not requested:
            return []
        if bool(getattr(self, "_new_hampshire_retained_replay", False)):
            from .strict_frontier_closure import (
                replay_exact_retained_state_records,
            )

            retained_rows = replay_exact_retained_state_records(
                self,
                requests=[
                    (url, {"method": "GET", "url": url}) for url in requested
                ],
                frontier_name=f"New Hampshire {frontier_name} frontier",
                refresh=False,
            )
            payloads: List[bytes] = []
            for url, retained in zip(requested, retained_rows, strict=True):
                raw = bytes(getattr(retained.envelope, "body", b"") or b"")
                if not content_validator(raw):
                    raise RuntimeError(
                        "New Hampshire retained frontier input is no longer valid: "
                        f"{url}"
                    )
                payloads.append(raw)
            stats_rows = list(
                getattr(self, "_new_hampshire_frontier_batch_stats", [])
            )
            stats_rows.append(
                {
                    "frontier_name": frontier_name,
                    "network_requested_pages": 0,
                    "requested_pages": len(requested),
                    "retained_replay_pages": len(requested),
                }
            )
            self._new_hampshire_frontier_batch_stats = stats_rows
            return payloads
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
            # One grouped archive inventory is authoritative for this logical
            # frontier wave.  Residual retries may repeat the plural direct
            # attempt, but must not fan back out into CC/CDX/archive lookups.
            repeat_grouped_archive_inventory_on_residual=False,
            timeout_seconds=20,
            content_validator=content_validator,
            media_type="text/html",
            max_concurrency=self._new_hampshire_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(
                "gc.nh.gov",
                "www.gencourt.state.nh.us",
            ),
            common_crawl_url_terms=("/rsa/html/",),
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
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
                f"New Hampshire {frontier_name} frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"New Hampshire {frontier_name} frontier changed URL order or identity"
            )
        failures: List[Dict[str, str]] = []
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
            self._validate_new_hampshire_aligned_evidence(
                url=url,
                payload=raw,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
                frontier_name=frontier_name,
            )
        if failures:
            raise RuntimeError(
                f"New Hampshire {frontier_name} frontier is incomplete; unresolved exact URLs: "
                f"{failures[:10]}"
            )
        stats_rows = list(getattr(self, "_new_hampshire_frontier_batch_stats", []))
        stats_rows.append(
            {
                "frontier_name": frontier_name,
                "requested_pages": len(requested),
                **dict(batch.stats or {}),
            }
        )
        self._new_hampshire_frontier_batch_stats = stats_rows
        return [bytes(payload) for payload in batch.payloads]

    async def _fetch_new_hampshire_frontier_in_chunks(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Callable[[bytes], bool],
    ) -> List[bytes]:
        payloads: List[bytes] = []
        requested = list(urls)
        batch_size = self._new_hampshire_frontier_batch_size()
        for batch_start in range(0, len(requested), batch_size):
            batch_urls = requested[batch_start : batch_start + batch_size]
            payloads.extend(
                await self._fetch_new_hampshire_frontier_batch(
                    batch_urls,
                    frontier_name=(
                        f"{frontier_name}-{batch_start + 1}-"
                        f"{batch_start + len(batch_urls)}"
                    ),
                    content_validator=content_validator,
                )
            )
        return payloads

    async def _scrape_official_rsa_tree_batched(
        self,
        *,
        code_name: str,
        checkpoint: "_NewHampshireCheckpoint",
    ) -> List[NormalizedStatute]:
        """Close the exact RSA title/chapter/section tree breadth-first."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError(
                "New Hampshire full-corpus acquisition requires BeautifulSoup"
            ) from exc
        from .new_hampshire_section import (
            new_hampshire_section_page_identity,
            nhtoc_chapter_units,
            nhtoc_section_units,
            nhtoc_title_units,
            parse_new_hampshire_section_html,
            source_bound_terminal_disposition_from_section_html,
            terminal_disposition_from_label,
        )

        self._new_hampshire_frontier_batch_stats = []
        self._new_hampshire_frontier_input_reports = []
        root_payloads = await self._fetch_new_hampshire_frontier_batch(
            [self.OFFICIAL_ENTRY_URL],
            frontier_name="root",
            content_validator=self._new_hampshire_root_payload,
        )
        self._record_new_hampshire_frontier_inputs(
            source_role="root_catalog",
            urls=[self.OFFICIAL_ENTRY_URL],
            payloads=root_payloads,
        )
        root_html = root_payloads[0].decode("utf-8", errors="replace")
        title_units = nhtoc_title_units(
            root_html,
            base_url=self.CURRENT_OFFICIAL_ENTRY_URL,
        )
        expected_titles = [number for number, _name in self.OFFICIAL_TITLES]
        expected_title_names = dict(self.OFFICIAL_TITLES)
        observed_titles = [str(unit["title_number"]) for unit in title_units]
        if observed_titles != expected_titles:
            missing = [number for number in expected_titles if number not in observed_titles]
            unexpected = [number for number in observed_titles if number not in expected_titles]
            raise RuntimeError(
                "New Hampshire root title frontier does not match the exact official "
                f"catalog: observed={len(observed_titles)} expected={len(expected_titles)} "
                f"missing={missing} unexpected={unexpected}"
            )
        for unit in title_units:
            title_number = str(unit["title_number"])
            expected_url = self.official_title_url(title_number)
            observed_name = self._normalize_legal_text(str(unit["title_name"]))
            expected_name = self._normalize_legal_text(
                expected_title_names[title_number]
            )
            if (
                str(unit["source_url"]) != expected_url
                or not self._host_is_official(expected_url)
                or observed_name.casefold() != expected_name.casefold()
            ):
                raise RuntimeError(
                    f"New Hampshire root changed title identity: {title_number}"
                )

        terminal_titles: List[Dict[str, str]] = []
        active_title_units: List[Dict[str, str]] = []
        for unit in title_units:
            disposition = str(unit.get("terminal_disposition") or "")
            if disposition:
                terminal_titles.append(
                    {
                        "title_number": str(unit["title_number"]),
                        "disposition": disposition,
                        "source_url": str(unit["source_url"]),
                        "source_label": str(unit.get("catalog_note") or ""),
                    }
                )
            else:
                active_title_units.append(unit)
        expected_terminal_titles = [
            (number, disposition)
            for number, disposition in self.OFFICIAL_TERMINAL_TITLES
            if number in expected_titles
        ]
        observed_terminal_titles = [
            (str(unit["title_number"]), str(unit["terminal_disposition"]))
            for unit in title_units
            if str(unit.get("terminal_disposition") or "")
        ]
        if observed_terminal_titles != expected_terminal_titles:
            raise RuntimeError(
                "New Hampshire root changed its exact terminal title projection: "
                f"observed={observed_terminal_titles} "
                f"expected={expected_terminal_titles}"
            )
        if len(active_title_units) != len(expected_titles) - len(
            expected_terminal_titles
        ):
            raise RuntimeError(
                "New Hampshire root changed its exact active title count: "
                f"observed={len(active_title_units)} "
                f"expected={len(expected_titles) - len(expected_terminal_titles)}"
            )
        if not active_title_units:
            raise RuntimeError("New Hampshire root contains no active title frontier")

        title_payloads = await self._fetch_new_hampshire_frontier_in_chunks(
            [str(unit["source_url"]) for unit in active_title_units],
            frontier_name="titles",
            content_validator=self._new_hampshire_title_payload,
        )
        self._record_new_hampshire_frontier_inputs(
            source_role="title_catalog",
            urls=[str(unit["source_url"]) for unit in active_title_units],
            payloads=title_payloads,
        )
        chapter_frontier: List[Dict[str, str]] = []
        terminal_chapters: List[Dict[str, str]] = []
        seen_chapter_urls: set[str] = set()
        seen_chapter_identities: set[tuple[str, str]] = set()
        for unit, payload in zip(active_title_units, title_payloads, strict=True):
            title_number = str(unit["title_number"])
            title_url = str(unit["source_url"])
            html = payload.decode("utf-8", errors="replace")
            title_soup = BeautifulSoup(html, "html.parser")
            page_identities = []
            for heading in title_soup.find_all("h2"):
                heading_text = self._normalize_legal_text(heading.get_text(" ", strip=True))
                match = re.fullmatch(
                    r"([IVXLCDM]+(?:-[A-Z]+)?)\s*:\s*.+",
                    heading_text,
                    flags=re.IGNORECASE,
                )
                if match:
                    page_identities.append(match.group(1).upper())
            if page_identities != [title_number]:
                raise RuntimeError(
                    "New Hampshire retained title page failed requested identity: "
                    f"{title_url}"
                )
            chapters = nhtoc_chapter_units(
                html,
                title_number=title_number,
                base_url=title_url,
            )
            if not chapters:
                codesect = title_soup.find("codesect")
                body_text = self._normalize_legal_text(
                    codesect.get_text(" ", strip=True) if codesect is not None else ""
                )
                if not re.fullmatch(
                    r"Entire\s+Title\s+was\s+repealed\.?",
                    body_text,
                    flags=re.IGNORECASE,
                ):
                    raise RuntimeError(
                        "New Hampshire active title produced no chapter frontier and no "
                        f"source-bound terminal disposition: {title_url}"
                    )
                terminal_titles.append(
                    {
                        "title_number": title_number,
                        "disposition": "repealed",
                        "source_url": title_url,
                        "source_label": body_text,
                    }
                )
                continue
            for chapter in chapters:
                chapter_url = str(chapter["source_url"])
                chapter_identity = (
                    title_number.casefold(),
                    str(chapter["chapter_number"]).casefold(),
                )
                if (
                    chapter_url.casefold() in seen_chapter_urls
                    or chapter_identity in seen_chapter_identities
                    or not self._host_is_official(chapter_url)
                ):
                    raise RuntimeError(
                        f"New Hampshire chapter frontier has a duplicate or invalid identity: {chapter_url}"
                    )
                seen_chapter_urls.add(chapter_url.casefold())
                seen_chapter_identities.add(chapter_identity)
                disposition = str(chapter.get("terminal_disposition") or "")
                if disposition:
                    terminal_chapters.append(
                        {
                            "title_number": title_number,
                            "chapter_number": str(chapter["chapter_number"]),
                            "disposition": disposition,
                            "source_url": chapter_url,
                            "source_label": str(chapter.get("label") or ""),
                        }
                    )
                else:
                    chapter_frontier.append(chapter)
        if not chapter_frontier:
            raise RuntimeError("New Hampshire title frontier produced no active chapters")

        catalog_terminal_chapter_count = len(terminal_chapters)
        chapter_payloads = await self._fetch_new_hampshire_frontier_in_chunks(
            [str(unit["source_url"]) for unit in chapter_frontier],
            frontier_name="chapters",
            content_validator=self._new_hampshire_chapter_payload,
        )
        self._record_new_hampshire_frontier_inputs(
            source_role="chapter_catalog",
            urls=[str(unit["source_url"]) for unit in chapter_frontier],
            payloads=chapter_payloads,
        )
        section_frontier: List[Dict[str, str]] = []
        terminal_sections: List[Dict[str, str]] = []
        seen_section_urls: set[str] = set()
        seen_section_identities: set[str] = set()
        for chapter, payload in zip(chapter_frontier, chapter_payloads, strict=True):
            title_number = str(chapter["title_number"])
            chapter_number = str(chapter["chapter_number"])
            chapter_url = str(chapter["source_url"])
            html = payload.decode("utf-8", errors="replace")
            chapter_soup = BeautifulSoup(html, "html.parser")
            chapter_page_ids: List[str] = []
            for heading in chapter_soup.find_all("h2"):
                heading_text = self._normalize_legal_text(heading.get_text(" ", strip=True))
                match = re.match(
                    r"^CHAPTER\s+([0-9]+(?:-[A-Z0-9]+)*)\b",
                    heading_text,
                    flags=re.IGNORECASE,
                )
                if match:
                    chapter_page_ids.append(match.group(1).upper())
            if chapter_page_ids != [chapter_number]:
                raise RuntimeError(
                    "New Hampshire retained chapter page failed requested identity: "
                    f"{chapter_url}"
                )
            sections = nhtoc_section_units(
                html,
                title_number=title_number,
                chapter_number=chapter_number,
                base_url=chapter_url,
            )
            if not sections:
                codesect = chapter_soup.find("codesect")
                body_text = self._normalize_legal_text(
                    codesect.get_text(" ", strip=True) if codesect is not None else ""
                )
                disposition = terminal_disposition_from_label(body_text)
                if disposition is None:
                    raise RuntimeError(
                        "New Hampshire chapter produced no section frontier and no "
                        f"source-bound terminal disposition: {chapter_url}"
                    )
                terminal_chapters.append(
                    {
                        "title_number": title_number,
                        "chapter_number": chapter_number,
                        "disposition": disposition,
                        "source_url": chapter_url,
                        "source_label": body_text,
                    }
                )
                continue
            for section in sections:
                section_url = str(section["source_url"])
                section_number = str(section["section_number"])
                if (
                    section_url.casefold() in seen_section_urls
                    or section_number.casefold() in seen_section_identities
                    or not self._host_is_official(section_url)
                ):
                    raise RuntimeError(
                        f"New Hampshire section frontier has a duplicate or invalid identity: {section_url}"
                    )
                seen_section_urls.add(section_url.casefold())
                seen_section_identities.add(section_number.casefold())
                disposition = str(section.get("terminal_disposition") or "")
                if disposition:
                    terminal_sections.append(
                        {
                            "title_number": title_number,
                            "chapter_number": chapter_number,
                            "section_number": section_number,
                            "disposition": disposition,
                            "source_url": section_url,
                            "source_label": str(section.get("label") or ""),
                            "classification_source": "chapter_catalog",
                        }
                    )
                else:
                    section_frontier.append(section)
        if not section_frontier:
            raise RuntimeError("New Hampshire chapter frontier produced no active sections")

        total_section_locators = len(section_frontier) + len(terminal_sections)
        catalog_terminal_section_count = len(terminal_sections)
        total_chapter_units = len(chapter_frontier) + catalog_terminal_chapter_count
        checkpoint.write(
            [],
            code_name=code_name,
            stage_label="new-hampshire:section-discovery",
            progress={
                "titles_scanned": len(title_units),
                "discovered_titles": len(title_units),
                "title_pages_fetched": len(active_title_units),
                "terminal_titles_classified": len(terminal_titles),
                "terminal_title_dispositions": terminal_titles,
                "chapters_scanned": total_chapter_units,
                "discovered_chapters": total_chapter_units,
                "chapter_pages_fetched": len(chapter_frontier),
                "terminal_chapters_classified": len(terminal_chapters),
                "terminal_chapter_dispositions": terminal_chapters,
                "sections_scanned": len(terminal_sections),
                "discovered_sections": total_section_locators,
                "terminal_sections_classified": len(terminal_sections),
                "terminal_section_dispositions": terminal_sections,
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        statutes: List[NormalizedStatute] = []
        batch_size = self._new_hampshire_frontier_batch_size()
        for batch_start in range(0, len(section_frontier), batch_size):
            batch_units = section_frontier[batch_start : batch_start + batch_size]
            batch_urls = [str(unit["source_url"]) for unit in batch_units]
            payloads = await self._fetch_new_hampshire_frontier_batch(
                batch_urls,
                frontier_name=(
                    f"sections-{batch_start + 1}-{batch_start + len(batch_units)}"
                ),
                content_validator=self._new_hampshire_section_payload,
            )
            self._record_new_hampshire_frontier_inputs(
                source_role="section",
                urls=batch_urls,
                payloads=payloads,
            )
            for unit, payload in zip(batch_units, payloads, strict=True):
                section_url = str(unit["source_url"])
                section_number = str(unit["section_number"])
                html = payload.decode("utf-8", errors="replace")
                identity = new_hampshire_section_page_identity(html)
                if not identity or identity.casefold() != section_number.casefold():
                    raise RuntimeError(
                        "New Hampshire retained section page failed requested identity: "
                        f"{section_url}"
                    )
                statute = parse_new_hampshire_section_html(
                    html,
                    source_url=section_url,
                    code_name=code_name,
                )
                if statute is None:
                    disposition = source_bound_terminal_disposition_from_section_html(
                        html,
                        source_url=section_url,
                        section_number=section_number,
                    )
                    if disposition is None:
                        raise RuntimeError(
                            "New Hampshire retained section failed official parsing and "
                            f"has no source-bound terminal disposition: {section_url}"
                        )
                    terminal_sections.append(
                        {
                            "title_number": str(unit["title_number"]),
                            "chapter_number": str(unit["chapter_number"]),
                            "section_number": section_number,
                            "disposition": str(disposition["disposition"]),
                            "source_url": section_url,
                            "source_label": "",
                            "classification_source": "section_body",
                            "content_sha256": hashlib.sha256(payload).hexdigest(),
                        }
                    )
                    continue
                if (
                    str(statute.section_number or "").casefold()
                    != section_number.casefold()
                    or str(statute.source_url or "") != section_url
                ):
                    raise RuntimeError(
                        f"New Hampshire normalized section changed source identity: {section_url}"
                    )
                # The locator/TOC spelling is the canonical frontier identity;
                # official body headings occasionally vary only in letter case.
                statute.section_number = section_number
                statute.chapter_number = str(unit["chapter_number"])
                statute.statute_id = f"{code_name} § {section_number}"
                statute.official_cite = f"N.H. Rev. Stat. § {section_number}"
                statute.structured_data = {
                    **dict(statute.structured_data or {}),
                    "discovery_method": "official_batched_title_chapter_section_frontier",
                    "title_number": str(unit["title_number"]),
                    "chapter_number": str(unit["chapter_number"]),
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                }
                statutes.append(statute)

            scanned_active = batch_start + len(batch_units)
            sections_scanned = catalog_terminal_section_count + scanned_active
            self.logger.info(
                "New Hampshire aligned section progress: scanned_active=%s/%s statutes=%s terminal=%s",
                scanned_active,
                len(section_frontier),
                len(statutes),
                len(terminal_sections),
            )
            checkpoint.maybe_write(
                statutes,
                code_name=code_name,
                stage_label="new-hampshire:section-batch",
                progress={
                    "titles_scanned": len(title_units),
                    "discovered_titles": len(title_units),
                    "title_pages_fetched": len(active_title_units),
                    "terminal_titles_classified": len(terminal_titles),
                    "chapters_scanned": total_chapter_units,
                    "discovered_chapters": total_chapter_units,
                    "chapter_pages_fetched": len(chapter_frontier),
                    "terminal_chapters_classified": len(terminal_chapters),
                    "sections_scanned": sections_scanned,
                    "discovered_sections": total_section_locators,
                    "terminal_sections_classified": len(terminal_sections),
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )

        statute_ids = [str(row.statute_id or "") for row in statutes]
        source_urls = [str(row.source_url or "") for row in statutes]
        if (
            not statutes
            or len(set(statute_ids)) != len(statute_ids)
            or len(set(source_urls)) != len(source_urls)
            or len(statutes) + len(terminal_sections) != total_section_locators
        ):
            raise RuntimeError(
                "New Hampshire final statute identities do not exactly close the section frontier"
            )
        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        input_reports = list(self._new_hampshire_frontier_input_reports)
        terminal_projection = {
            "chapters": terminal_chapters,
            "sections": terminal_sections,
            "titles": terminal_titles,
        }
        excluded_count = (
            len(terminal_titles) + len(terminal_chapters) + len(terminal_sections)
        )
        exact_frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "chapter_document_count": total_chapter_units,
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
                    [str(row.section_number or "") for row in statutes]
                )
            ).hexdigest(),
            "schema": "new-hampshire-source-derived-strict-frontier-v1",
            "scope_closed": True,
            "source_input_count": len(input_reports),
            "source_section_count": total_section_locators,
            "statutes_emitted": len(statutes),
            "terminal_chapter_count": len(terminal_chapters),
            "terminal_projection_sha256": hashlib.sha256(
                canonical_json_bytes(terminal_projection)
            ).hexdigest(),
            "terminal_section_count": len(terminal_sections),
            "terminal_title_count": len(terminal_titles),
            "title_document_count": len(title_units),
        }
        exact_frontier["frontier_digest_sha256"] = compute_frontier_digest(
            exact_frontier
        )
        observed_at = datetime.now(timezone.utc).isoformat()
        observation = {
            "closed": True,
            "boundary_first": str(statutes[0].source_url or ""),
            "boundary_last": str(statutes[-1].source_url or ""),
            "code_name": code_name,
            "frontier": exact_frontier,
            "input_reports": input_reports,
            "legal_as_of": observed_at[:10],
            "observed_at": observed_at,
            "titles_discovered": len(title_units),
            "title_pages_fetched": len(active_title_units),
            "terminal_titles": terminal_titles,
            "chapters_discovered": total_chapter_units,
            "chapter_pages_fetched": len(chapter_frontier),
            "terminal_chapters": terminal_chapters,
            "section_locators_discovered": total_section_locators,
            "active_section_pages_fetched": len(section_frontier),
            "terminal_sections": terminal_sections,
            "statutes_emitted": len(statutes),
            "batch_calls": list(self._new_hampshire_frontier_batch_stats),
        }
        if bool(getattr(self, "_new_hampshire_retained_replay", False)):
            self._last_new_hampshire_replayed_frontier = observation
        else:
            self._last_new_hampshire_full_frontier = observation
        checkpoint.write(
            statutes,
            code_name=code_name,
            stage_label="new-hampshire:complete",
            replace_statutes=True,
            progress={
                "titles_scanned": len(title_units),
                "discovered_titles": len(title_units),
                "title_pages_fetched": len(active_title_units),
                "terminal_titles_classified": len(terminal_titles),
                "terminal_title_dispositions": terminal_titles,
                "chapters_scanned": total_chapter_units,
                "discovered_chapters": total_chapter_units,
                "chapter_pages_fetched": len(chapter_frontier),
                "terminal_chapters_classified": len(terminal_chapters),
                "terminal_chapter_dispositions": terminal_chapters,
                "sections_scanned": total_section_locators,
                "discovered_sections": total_section_locators,
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
        """Replay every retained RSA hierarchy input and seal exact row parity."""

        first = getattr(self, "_last_new_hampshire_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "New Hampshire strict source frontier was not closed before output"
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
                "New Hampshire first exact frontier observation is incomplete"
            )
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "New Hampshire frontier closure requires an attached ledger"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        class _NoopCheckpoint:
            def write(self, *_args: Any, **_kwargs: Any) -> None:
                return None

            def maybe_write(self, *_args: Any, **_kwargs: Any) -> None:
                return None

        prior_replay = bool(
            getattr(self, "_new_hampshire_retained_replay", False)
        )
        self._new_hampshire_retained_replay = True
        try:
            replay_rows = await self._scrape_official_rsa_tree_batched(
                code_name=str(
                    first.get("code_name") or "New Hampshire Revised Statutes"
                ),
                checkpoint=_NoopCheckpoint(),  # type: ignore[arg-type]
            )
        finally:
            self._new_hampshire_retained_replay = prior_replay
        replay = getattr(self, "_last_new_hampshire_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError(
                "New Hampshire retained strict frontier replay was not observed"
            )
        replayed_frontier = replay.get("frontier")
        replay_reports = replay.get("input_reports")
        if (
            not isinstance(replayed_frontier, Mapping)
            or list(replay_reports or []) != list(first_reports)
        ):
            raise RuntimeError(
                "New Hampshire retained hierarchy inputs changed on replay"
            )

        from .strict_frontier_closure import (
            retain_exact_state_frontier_closure,
        )

        batch_stats = [
            row
            for row in list(first.get("batch_calls") or [])
            if isinstance(row, Mapping)
        ]
        disposition = first_frontier.get("disposition")
        if not isinstance(disposition, Mapping):
            raise RuntimeError(
                "New Hampshire strict frontier lacks disposition algebra"
            )
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="NH",
            source_domain=str(urlparse(self.OFFICIAL_ENTRY_URL).hostname or ""),
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("legal_as_of") or ""),
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=int(disposition.get("discovered") or 0),
            pagination_total=(
                1
                + int(first.get("title_pages_fetched") or 0)
                + int(first.get("chapter_pages_fetched") or 0)
            ),
            transport={
                "current_official_domain": self.OFFICIAL_DOMAIN,
                "fixture": False,
                "first_pass_request_batches": len(batch_stats),
                "first_pass_requested_pages": sum(
                    int(row.get("requested_pages") or 0) for row in batch_stats
                ),
                "grouped_warc_recovery": True,
                "kind": "archived_root_plus_shared_archive_aware_plural_html",
                "per_page_archive_loop": False,
                "retained_replay_network_requests": 0,
                "synthetic": False,
            },
        )

    async def _scrape_official_rsa_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Walk the live gencourt RSA title/chapter/section HTML tree."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        root_url = self.OFFICIAL_ENTRY_URL
        html = await self._request_text_direct(root_url, timeout=18)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        title_urls: List[str] = []
        seen_titles = set()
        from .new_hampshire_section import (
            nhtoc_chapter_links,
            nhtoc_section_links,
            nhtoc_title_links,
        )

        for href, _roman in nhtoc_title_links(html, base_url=root_url):
            abs_url = self._normalize_wayback_like_url(href)
            if not self._host_is_official(abs_url) or abs_url in seen_titles:
                continue
            seen_titles.add(abs_url)
            title_urls.append(abs_url)
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            text = str(anchor.get_text(" ", strip=True) or "").strip()
            abs_url = self._normalize_wayback_like_url(urljoin(root_url, href))
            if not self._host_is_official(abs_url):
                continue
            if "/rsa/html/nhtoc/" not in abs_url.lower() and not self._NH_TITLE_TEXT_RE.match(text):
                continue
            if "/rsa/html/" not in abs_url.lower() or not abs_url.lower().endswith(".htm"):
                continue
            if abs_url in seen_titles:
                continue
            seen_titles.add(abs_url)
            title_urls.append(abs_url)

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        for title_url in title_urls:
            if limit is not None and len(statutes) >= limit:
                break
            title_html = await self._request_text_direct(title_url, timeout=18)
            if not title_html:
                continue
            title_soup = BeautifulSoup(title_html, "html.parser")
            chapter_urls: List[tuple[str, str]] = []
            seen_chapters = set()
            title_base = title_url.rsplit("/", 1)[0] + "/"
            for href in nhtoc_chapter_links(title_html):
                chapter_url = self._normalize_wayback_like_url(urljoin(title_base, href))
                if not self._host_is_official(chapter_url) or chapter_url in seen_chapters:
                    continue
                seen_chapters.add(chapter_url)
                ch_match = re.search(
                    r"NHTOC-[A-Z][A-Z\-]*-(\d+[\w\-]*)\.htm", href, re.IGNORECASE
                )
                chapter_id = ch_match.group(1) if ch_match else href
                chapter_urls.append((chapter_id, chapter_url))
            for anchor in title_soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                text = str(anchor.get_text(" ", strip=True) or "").strip()
                if not href.lower().endswith(".htm"):
                    continue
                match = self._NH_CHAPTER_TEXT_RE.match(text)
                if not match:
                    continue
                chapter_id = match.group(1).upper()
                chapter_url = self._normalize_wayback_like_url(urljoin(title_url, href))
                if not self._host_is_official(chapter_url) or chapter_url in seen_chapters:
                    continue
                seen_chapters.add(chapter_url)
                chapter_urls.append((chapter_id, chapter_url))

            for chapter_id, chapter_url in chapter_urls:
                if limit is not None and len(statutes) >= limit:
                    break
                chapter_html = await self._request_text_direct(chapter_url, timeout=18)
                if not chapter_html:
                    continue
                chapter_soup = BeautifulSoup(chapter_html, "html.parser")
                chapter_base = chapter_url.rsplit("/", 1)[0] + "/"
                section_hrefs = list(nhtoc_section_links(chapter_html))
                for href in section_hrefs:
                    if limit is not None and len(statutes) >= limit:
                        break
                    section_url = self._normalize_wayback_like_url(urljoin(chapter_base, href))
                    if not self._host_is_official(section_url):
                        continue
                    section_number = self._derive_section_number_from_href(
                        chapter_id=chapter_id,
                        section_url=section_url,
                        href_text="",
                    )
                    if not section_number:
                        continue
                    section_key = section_number.lower()
                    if section_key in seen_sections:
                        continue
                    seen_sections.add(section_key)
                    statute = await self._build_official_rsa_section(
                        code_name,
                        section_number=section_number,
                        section_title="",
                        section_url=section_url,
                    )
                    if statute is not None:
                        statutes.append(statute)
                for anchor in chapter_soup.find_all("a", href=True):
                    if limit is not None and len(statutes) >= limit:
                        break
                    href = str(anchor.get("href") or "").strip()
                    text = str(anchor.get_text(" ", strip=True) or "").strip()
                    if not href.lower().endswith(".htm"):
                        continue
                    section_url = self._normalize_wayback_like_url(urljoin(chapter_url, href))
                    if not self._host_is_official(section_url):
                        continue
                    match = self._NH_SECTION_LINK_RE.match(text)
                    if match:
                        section_number = match.group(1).strip()
                        section_title = match.group(2).strip().rstrip(".")
                    else:
                        section_number = self._derive_section_number_from_href(
                            chapter_id=chapter_id,
                            section_url=section_url,
                            href_text=text,
                        )
                        section_title = text.strip().rstrip(".")
                    if not section_number:
                        continue
                    section_key = section_number.lower()
                    if section_key in seen_sections:
                        continue
                    seen_sections.add(section_key)
                    statute = await self._build_official_rsa_section(
                        code_name,
                        section_number=section_number,
                        section_title=section_title,
                        section_url=section_url,
                    )
                    if statute is not None:
                        statutes.append(statute)
        return statutes

    async def _build_official_rsa_section(
        self,
        code_name: str,
        *,
        section_number: str,
        section_title: str,
        section_url: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._request_text_direct(section_url, timeout=18)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        from .new_hampshire_section import parse_new_hampshire_section_html

        parsed = parse_new_hampshire_section_html(
            html, source_url=section_url, code_name=code_name
        )
        if parsed is not None:
            return parsed
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()
        text = self._normalize_legal_text(soup.get_text(" ", strip=True))
        if len(text) < 80:
            return None
        section_name = f"Section {section_number} {section_title}".strip()
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name[:200],
            full_text=text,
            legal_area=self._identify_legal_area(section_name),
            source_url=section_url,
            official_cite=f"N.H. Rev. Stat. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_new_hampshire_rsa_html",
                "discovery_method": "official_title_chapter_section",
                "skip_hydrate": True,
            },
        )

    async def _scrape_direct_archived_seed_sections(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            (
                "1:1",
                "https://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/I/1/1-1.htm",
            ),
            (
                "1:2",
                "https://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/I/1/1-2.htm",
            ),
        ]
        out: List[NormalizedStatute] = []
        for section_number, source_url in seeds[: max(1, int(max_statutes or 1))]:
            html = await self._request_text_direct(source_url, timeout=20)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 160:
                continue
            title_match = re.search(rf"\b{re.escape(section_number)}\s+([^–-]{{4,180}})", text)
            section_name = title_match.group(1).strip() if title_match else f"Section {section_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name),
                    source_url=source_url,
                    official_cite=f"N.H. Rev. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_new_hampshire_rsa_wayback_html",
                        "discovery_method": "wayback_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _request_text_direct(self, url: str, timeout: int = 20) -> str:
        canonical = self._normalize_wayback_like_url(url)

        try:
            host = (urlparse(canonical).hostname or "").lower()
            if host in {"www.gencourt.state.nh.us", "gencourt.state.nh.us", "gc.nh.gov"}:
                payload = await self._fetch_parser_input_with_transport(
                    canonical,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout_seconds=max(1, int(timeout)),
                    allow_archival_fallback=False,
                    media_type="text/html",
                    provider="new_hampshire_official_direct",
                )
                direct_text = payload.decode("utf-8", errors="replace") if payload else ""
            else:
                # Direct replay/CDX requests remain a distinct archive source
                # hop until the shared adapter can express that provenance.
                direct_text = await self._request_archival_source_text_direct(
                    canonical,
                    timeout=timeout,
                )
            if direct_text:
                return direct_text
        except Exception:
            direct_text = ""

        # Avoid expensive archival/search fallbacks for known NH/Wayback URLs.
        # These paths are best served by direct fetch + replay variants.
        if self._should_prefer_direct_only_fetch(canonical):
            return direct_text or ""

        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                canonical,
                timeout_seconds=max(5, int(timeout)),
            )
        except Exception:
            payload = b""
        if payload:
            try:
                return payload.decode("utf-8", errors="replace")
            except Exception:
                return ""
        return ""

    async def _request_archival_source_text_direct(
        self,
        url: str,
        *,
        timeout: int,
    ) -> str:
        normalized = str(url or "").strip()
        if "web.archive.org/cdx/search/cdx" in normalized.lower():
            rows = await self._fetch_wayback_cdx_rows(
                normalized,
                timeout_seconds=timeout,
            )
            return json.dumps(rows) if rows else ""
        if "web.archive.org/web/" not in normalized.lower():
            return ""
        payload = await self._fetch_wayback_replay_parser_input(
            normalized,
            timeout_seconds=timeout,
            media_type="text/html",
        )
        return payload.decode("utf-8", errors="replace") if payload else ""

    async def _fetch_known_rsa_page(self, url: str, timeout_seconds: int = 35) -> bytes:
        # Known official/Wayback RSA pages should be fetched directly before invoking
        # the heavier archival/search fallback stack.
        normalized_url = self._normalize_wayback_like_url(url)
        lower_url = str(normalized_url or "").lower()
        is_known_rsa = "/rsa/html/" in lower_url and (
            "gencourt.state.nh.us/" in lower_url
            or "gc.nh.gov/" in lower_url
            or "web.archive.org/web/" in lower_url
        )
        if is_known_rsa:
            wayback_candidates = self._wayback_replay_candidates(normalized_url)
            ordered_candidates: List[str] = []
            for candidate in wayback_candidates:
                candidate_text = str(candidate or "").strip()
                if candidate_text and candidate_text not in ordered_candidates:
                    ordered_candidates.append(candidate_text)
            for candidate in ordered_candidates:
                direct = await self._request_text_direct(candidate, timeout=max(5, timeout_seconds))
                if direct:
                    return direct.encode("utf-8", errors="replace")
            # Avoid expensive archival/search fallback loops for known RSA/Wayback
            # URLs when direct replay fetches miss.
            return b""
        return await self._fetch_page_content_with_archival_fallback(normalized_url, timeout_seconds=timeout_seconds)

    def _should_prefer_direct_only_fetch(self, url: str) -> bool:
        value = str(url or "").strip().lower()
        if not value:
            return False
        if "/rsa/html/" not in value:
            return False
        return any(marker in value for marker in self._DIRECT_FETCH_HOST_MARKERS)

    def _derive_direct_rsa_candidates(self, value: str) -> List[str]:
        url = str(value or "").strip()
        if not url:
            return []
        out: List[str] = []
        if "web.archive.org/web/" in url.lower():
            match = re.search(
                r"/web/\d+(?:if_|id_)?/(https?://.+)$",
                url,
                flags=re.IGNORECASE,
            )
            if match:
                out.append(self._normalize_wayback_like_url(match.group(1)))
        lower_candidates = [str(candidate or "").strip().lower() for candidate in out]
        if any("www.gencourt.state.nh.us/" in candidate for candidate in lower_candidates):
            out.append(
                re.sub(
                    r"^https?://www\.gencourt\.state\.nh\.us/",
                    "https://gc.nh.gov/",
                    out[0],
                    flags=re.IGNORECASE,
                )
            )
        elif any("gc.nh.gov/" in candidate for candidate in lower_candidates):
            out.append(
                re.sub(
                    r"^https?://gc\.nh\.gov/",
                    "https://www.gencourt.state.nh.us/",
                    out[0],
                    flags=re.IGNORECASE,
                )
            )
        deduped: List[str] = []
        for candidate in out:
            text = str(candidate or "").strip()
            if text and text not in deduped:
                deduped.append(text)
        return deduped

    def _derive_section_number_from_href(self, *, chapter_id: str, section_url: str, href_text: str) -> str:
        chapter = str(chapter_id or "").strip()
        if not chapter:
            return ""
        normalized_url = self._normalize_wayback_like_url(section_url)
        lower_url = normalized_url.lower()
        if "/rsa/html/" not in lower_url:
            return ""
        try:
            path_part = normalized_url.split("://", 1)[-1].split("/", 1)[-1]
        except Exception:
            path_part = normalized_url
        if not path_part:
            return ""
        basename = PurePosixPath(path_part).name
        if not basename.lower().endswith(".htm"):
            return ""
        stem = basename[:-4].strip()
        if not stem:
            return ""
        stem = re.sub(r"[^0-9A-Za-z:-]", "", stem)
        if not stem:
            return ""
        chapter_lower = chapter.lower()
        stem_lower = stem.lower()
        if stem_lower.startswith(chapter_lower + "-"):
            suffix = stem[len(chapter) + 1 :].strip()
            if suffix:
                return f"{chapter}:{suffix}"
        if stem_lower.startswith(chapter_lower + ":"):
            suffix = stem[len(chapter) + 1 :].strip()
            if suffix:
                return f"{chapter}:{suffix}"
        if stem_lower == chapter_lower:
            fallback_match = re.search(r"\b([0-9A-Za-z:.-]{2,})\b", str(href_text or ""))
            if fallback_match:
                candidate = fallback_match.group(1).strip()
                if candidate and candidate.lower() != chapter_lower:
                    return candidate
            return ""
        if ":" in stem:
            return stem
        # Last-resort: treat `<chapter>-<suffix>` as `<chapter>:<suffix>` when possible.
        suffix_match = re.match(rf"^{re.escape(chapter_lower)}-([0-9A-Za-z.-]+)$", stem_lower)
        if suffix_match:
            suffix = str(suffix_match.group(1) or "").strip()
            if suffix:
                return f"{chapter}:{suffix}"
        return ""

    async def _scrape_archived_title_stubs(
        self,
        code_name: str,
        max_statutes: Optional[int] = 100,
        checkpoint: Optional["_NewHampshireCheckpoint"] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        root_candidates = [
            "https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
            "https://gc.nh.gov/rsa/html/NHTOC.htm",
            "https://web.archive.org/web/20250124114611/https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
            "https://web.archive.org/web/20250124114611/https://gc.nh.gov/rsa/html/NHTOC.htm",
        ]
        root_url = ""
        payload = b""

        try:
            for candidate in root_candidates:
                candidate_url = self._normalize_wayback_like_url(str(candidate or ""))
                if not candidate_url:
                    continue
                root_url = candidate_url
                payload = await self._fetch_known_rsa_page(candidate_url, timeout_seconds=35)
                if payload:
                    break
            if not payload:
                if checkpoint is not None:
                    checkpoint.write(
                        [],
                        code_name=code_name,
                        stage_label="root-unavailable",
                        progress={
                            "titles_scanned": 0,
                            "discovered_titles": 0,
                            "chapters_scanned": 0,
                            "discovered_chapters": 0,
                            "codes_completed": 0,
                            "codes_total": 1,
                            "fetch_status": "root_unavailable",
                        },
                    )
                return []
        except Exception:
            if checkpoint is not None:
                checkpoint.write(
                    [],
                    code_name=code_name,
                    stage_label="root-fetch-error",
                    progress={
                        "titles_scanned": 0,
                        "discovered_titles": 0,
                        "chapters_scanned": 0,
                        "discovered_chapters": 0,
                        "codes_completed": 0,
                        "codes_total": 1,
                        "fetch_status": "root_fetch_error",
                    },
                )
            return []

        soup = BeautifulSoup(payload, "html.parser")
        full_corpus_mode = self._full_corpus_enabled()

        def _limit_reached(size: int) -> bool:
            return max_statutes is not None and size >= max_statutes

        title_urls: List[str] = []
        seen_titles = set()
        title_stubs: List[NormalizedStatute] = []
        title_url_limit = max_statutes if max_statutes is not None else None
        if not full_corpus_mode and title_url_limit is not None:
            title_url_limit = min(title_url_limit, 12)
        for a in soup.find_all("a", href=True):
            text = str(a.get_text(" ", strip=True) or "").strip()
            title_match = self._NH_TITLE_TEXT_RE.match(text)
            href = str(a.get("href") or "").strip()
            full_url = self._normalize_wayback_like_url(urljoin(root_url, href))
            if "/rsa/html/nhtoc/" not in full_url.lower():
                continue
            if full_url in seen_titles:
                continue
            seen_titles.add(full_url)
            title_urls.append(full_url)
            if title_match and not full_corpus_mode and not _limit_reached(len(title_stubs)):
                title_no = title_match.group(1).upper()
                title_name = title_match.group(2).strip()
                title_stubs.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § Title {title_no}",
                        code_name=code_name,
                        section_number=f"Title {title_no}",
                        section_name=text[:200],
                        full_text=f"New Hampshire Revised Statutes {text}",
                        source_url=full_url,
                        legal_area=self._identify_legal_area(title_name),
                        official_cite=f"N.H. Rev. Stat. Title {title_no}",
                        metadata=StatuteMetadata(),
                        structured_data={"skip_hydrate": True, "record_type": "archived_title_stub"},
                    )
                )
                if checkpoint is not None:
                    checkpoint.maybe_write(title_stubs, code_name=code_name, stage_label=f"title:{title_no}")
            if title_url_limit is not None and len(title_urls) >= title_url_limit:
                break

        if checkpoint is not None and not title_urls:
            checkpoint.write(
                title_stubs,
                code_name=code_name,
                stage_label="title-discovery-empty",
                progress={
                    "titles_scanned": 0,
                    "discovered_titles": 0,
                    "chapters_scanned": 0,
                    "discovered_chapters": 0,
                    "codes_completed": 0,
                    "codes_total": 1,
                    "fetch_status": "no_titles_discovered",
                },
            )

        if title_urls:
            self.logger.info(
                "New Hampshire archived index: discovered_titles=%s full_corpus=%s",
                len(title_urls),
                self._full_corpus_enabled(),
            )

        out: List[NormalizedStatute] = list(title_stubs)
        seen_output_keys: set[str] = set()
        for statute in out:
            statute_id_key = str(statute.statute_id or "").strip().lower()
            source_key = str(statute.source_url or "").strip().lower()
            if statute_id_key:
                seen_output_keys.add(statute_id_key)
            if source_key:
                seen_output_keys.add(source_key)
        seen_chapters = set()
        chapter_urls: List[tuple[str, str, str]] = []

        chapter_fetch_limit = None if max_statutes is None else max(8, int(max_statutes) * 4)

        total_titles = len(title_urls)
        for title_index, title_url in enumerate(title_urls, start=1):
            if _limit_reached(len(out)):
                break
            if chapter_fetch_limit is not None and len(chapter_urls) >= chapter_fetch_limit:
                break
            try:
                title_payload = await self._fetch_known_rsa_page(title_url, timeout_seconds=35)
                if not title_payload:
                    continue
            except Exception:
                continue

            title_soup = BeautifulSoup(title_payload, "html.parser")
            for a in title_soup.find_all("a", href=True):
                if _limit_reached(len(out)):
                    break
                href = str(a.get("href") or "").strip()
                text = str(a.get_text(" ", strip=True) or "").strip()
                if not href.endswith(".htm"):
                    continue
                match = self._NH_CHAPTER_TEXT_RE.match(text)
                if not match:
                    continue
                chapter_id = match.group(1).upper()
                key = chapter_id.lower()
                if key in seen_chapters:
                    continue
                seen_chapters.add(key)

                source_url = self._normalize_wayback_like_url(urljoin(title_url, href))
                chapter_name = text[:200] if text else f"Chapter {chapter_id}"
                chapter_urls.append((chapter_id, chapter_name, source_url))
                if not full_corpus_mode:
                    out.append(
                        NormalizedStatute(
                            state_code=self.state_code,
                            state_name=self.state_name,
                            statute_id=f"{code_name} § Chapter {chapter_id}",
                            code_name=code_name,
                            section_number=f"Chapter {chapter_id}",
                            section_name=chapter_name,
                            full_text=f"New Hampshire Revised Statutes {chapter_name}: {source_url}",
                            source_url=source_url,
                            legal_area=self._identify_legal_area(chapter_name),
                            official_cite=f"N.H. Rev. Stat. ch. {chapter_id}",
                            metadata=StatuteMetadata(),
                            structured_data={"skip_hydrate": True, "record_type": "archived_chapter_stub"},
                        )
                    )
                    if checkpoint is not None:
                        checkpoint.maybe_write(out, code_name=code_name, stage_label=f"chapter-stub:{chapter_id}")

            if title_index == 1 or title_index % 5 == 0:
                self.logger.info(
                    "New Hampshire archived index: titles_scanned=%s/%s sections=%s statutes_so_far=%s",
                    title_index,
                    total_titles,
                    len(chapter_urls),
                    len(out),
                )
                if checkpoint is not None:
                    checkpoint.maybe_write(
                        out,
                        code_name=code_name,
                        stage_label=f"title-scan:{title_index}",
                        progress={
                            "titles_scanned": int(title_index),
                            "discovered_titles": int(total_titles),
                            "discovered_chapters": int(len(chapter_urls)),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )

        if _limit_reached(len(out)):
            return out[:max_statutes]

        section_concurrency = max(
            1,
            int(os.getenv("STATE_SCRAPER_NH_SECTION_CONCURRENCY", "6") or "6"),
        )
        section_sem = anyio_compat.Semaphore(section_concurrency)

        async def _fetch_chapter_sections(chapter_id: str, chapter_name: str, chapter_url: str) -> List[NormalizedStatute]:
            try:
                chapter_payload = await self._fetch_known_rsa_page(chapter_url, timeout_seconds=35)
                if not chapter_payload:
                    return []
            except Exception:
                return []

            chapter_soup = BeautifulSoup(chapter_payload, "html.parser")
            section_links: List[tuple[str, str, str]] = []
            seen_local = set()
            for a in chapter_soup.find_all("a", href=True):
                href = str(a.get("href") or "").strip()
                text = str(a.get_text(" ", strip=True) or "").strip()
                if not href.endswith(".htm"):
                    continue
                match = self._NH_SECTION_LINK_RE.match(text)
                section_url = self._normalize_wayback_like_url(urljoin(chapter_url, href))
                section_number = ""
                section_title = ""
                if match:
                    section_number = match.group(1).strip()
                    section_title = match.group(2).strip().rstrip(".")
                else:
                    section_number = self._derive_section_number_from_href(
                        chapter_id=chapter_id,
                        section_url=section_url,
                        href_text=text,
                    )
                    if not section_number:
                        continue
                    section_title = text.strip().rstrip(".")
                if not section_title:
                    section_title = f"Section {section_number}"
                section_key = section_number.lower()
                if section_key in seen_local:
                    continue
                seen_local.add(section_key)
                statute_id_key = f"{code_name} § {section_number}".strip().lower()
                source_key = str(section_url or "").strip().lower()
                if statute_id_key in seen_output_keys or source_key in seen_output_keys:
                    continue
                section_links.append(
                    (
                        section_number,
                        section_title,
                        section_url,
                    )
                )

            section_statutes: List[NormalizedStatute] = []
            seen_local_statute_keys: set[str] = set()

            async def _fetch_section(
                section_number: str,
                section_title: str,
                section_url: str,
            ) -> Optional[NormalizedStatute]:
                async with section_sem:
                    try:
                        section_payload = await self._fetch_known_rsa_page(section_url, timeout_seconds=35)
                    except Exception:
                        return None
                    section_text = self._extract_statute_text(section_payload)
                    if len(section_text) < 160:
                        return None
                    section_name = f"Section {section_number} {section_title}".strip()
                    return NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=section_name[:200],
                        full_text=section_text,
                        source_url=section_url,
                        legal_area=self._identify_legal_area(section_name or chapter_name),
                        official_cite=f"N.H. Rev. Stat. § {section_number}",
                        metadata=StatuteMetadata(),
                    )

            section_results = await anyio_compat.gather(
                *[
                    _fetch_section(section_number, section_title, section_url)
                    for section_number, section_title, section_url in section_links
                ],
                return_exceptions=True,
            )
            scanned_sections = 0
            for result in section_results:
                scanned_sections += 1
                statute = result if isinstance(result, NormalizedStatute) else None
                if statute is None:
                    continue
                local_key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if local_key and local_key in seen_local_statute_keys:
                    continue
                if local_key:
                    seen_local_statute_keys.add(local_key)
                section_statutes.append(statute)
                if len(section_statutes) == 1 or len(section_statutes) % 40 == 0:
                    self.logger.info(
                        "New Hampshire archived index: chapter=%s scanned_sections=%s/%s statutes_so_far=%s",
                        chapter_id,
                        len(section_statutes),
                        len(section_links),
                        len(section_statutes),
                    )
                if checkpoint is not None and (
                    scanned_sections == 1
                    or scanned_sections % 200 == 0
                    or scanned_sections == len(section_links)
                ):
                    progress_statutes = list(out) + list(section_statutes)
                    checkpoint.maybe_write(
                        progress_statutes,
                        code_name=code_name,
                        stage_label=f"chapter-progress:{chapter_id}:{scanned_sections}",
                        progress={
                            "titles_scanned": int(total_titles),
                            "discovered_titles": int(total_titles),
                            "chapters_scanned": 0,
                            "discovered_chapters": int(len(chapter_urls)),
                            "chapter_id": str(chapter_id),
                            "sections_scanned": int(scanned_sections),
                            "discovered_sections": int(len(section_links)),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )
                if _limit_reached(len(section_statutes)):
                    break
            if section_links:
                self.logger.info(
                    "New Hampshire archived index: chapter=%s scanned_sections=%s/%s statutes_so_far=%s",
                    chapter_id,
                    len(section_statutes),
                    len(section_links),
                    len(section_statutes),
                )
            return section_statutes

        sem = anyio_compat.Semaphore(4)

        async def _bounded_fetch(chapter_id: str, chapter_name: str, chapter_url: str) -> List[NormalizedStatute]:
            async with sem:
                return await _fetch_chapter_sections(chapter_id, chapter_name, chapter_url)

        if self._full_corpus_enabled():
            chapters_to_fetch = chapter_urls if max_statutes is None else chapter_urls[: chapter_fetch_limit or len(chapter_urls)]
        else:
            chapters_to_fetch = chapter_urls[:8]
        if chapter_urls:
            self.logger.info(
                "New Hampshire archived index: discovered_chapters=%s fetched_chapters=%s",
                len(chapter_urls),
                len(chapters_to_fetch),
            )
            if checkpoint is not None:
                checkpoint.maybe_write(
                    out,
                    code_name=code_name,
                    stage_label="chapter-discovery",
                    progress={
                        "titles_scanned": int(total_titles),
                        "discovered_titles": int(total_titles),
                        "chapters_scanned": 0,
                        "discovered_chapters": int(len(chapters_to_fetch)),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )
        async def _bounded_fetch_with_meta(
            chapter_id: str,
            chapter_name: str,
            chapter_url: str,
        ) -> tuple[str, list[NormalizedStatute], Optional[Exception]]:
            try:
                section_batch = await _bounded_fetch(chapter_id, chapter_name, chapter_url)
                return chapter_id, section_batch, None
            except Exception as exc:  # pragma: no cover - defensive guard
                return chapter_id, [], exc

        chapter_results = await anyio_compat.gather(
            *[
                _bounded_fetch_with_meta(chapter_id, chapter_name, chapter_url)
                for chapter_id, chapter_name, chapter_url in chapters_to_fetch
            ],
            return_exceptions=True,
        )
        completed_chapters = 0
        for completed_result in chapter_results:
            if not isinstance(completed_result, tuple):
                continue
            chapter_id, section_batch, section_error = completed_result
            completed_chapters += 1
            chapter_index = completed_chapters
            if section_error is not None:
                continue
            if checkpoint is not None and (
                chapter_index == 1
                or chapter_index % 20 == 0
                or chapter_index == len(chapters_to_fetch)
            ):
                checkpoint.maybe_write(
                    out,
                    code_name=code_name,
                    stage_label=f"chapter-scan:{chapter_index}",
                    progress={
                        "titles_scanned": int(total_titles),
                        "discovered_titles": int(total_titles),
                        "chapters_scanned": int(chapter_index),
                        "discovered_chapters": int(len(chapters_to_fetch)),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )
            for statute in section_batch:
                statute_id_key = str(statute.statute_id or "").strip().lower()
                source_key = str(statute.source_url or "").strip().lower()
                if (statute_id_key and statute_id_key in seen_output_keys) or (
                    source_key and source_key in seen_output_keys
                ):
                    continue
                if statute_id_key:
                    seen_output_keys.add(statute_id_key)
                if source_key:
                    seen_output_keys.add(source_key)
                out.append(statute)
                if checkpoint is not None and (len(out) == 1 or len(out) % 40 == 0):
                    checkpoint.maybe_write(
                        out,
                        code_name=code_name,
                        stage_label=f"chapter:{chapter_id}",
                        progress={
                            "titles_scanned": int(total_titles),
                            "discovered_titles": int(total_titles),
                            "chapters_scanned": int(chapter_index),
                            "discovered_chapters": int(len(chapters_to_fetch)),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )
                if len(out) == 1 or len(out) % 40 == 0:
                    self.logger.info(
                        "New Hampshire archived index: global_total_statutes_so_far=%s chapter=%s",
                        len(out),
                        chapter_id,
                    )
                if _limit_reached(len(out)):
                    if checkpoint is not None:
                        checkpoint.write(
                            out,
                            code_name=code_name,
                            stage_label=f"limit:{chapter_id}",
                            progress={
                                "titles_scanned": int(total_titles),
                                "discovered_titles": int(total_titles),
                                "chapters_scanned": int(chapter_index),
                                "discovered_chapters": int(len(chapters_to_fetch)),
                                "codes_completed": 1,
                                "codes_total": 1,
                            },
                        )
                    return out[:max_statutes]

        if checkpoint is not None:
            checkpoint.write(
                out,
                code_name=code_name,
                stage_label="archived-title-stubs-complete",
                progress={
                    "titles_scanned": int(total_titles),
                    "discovered_titles": int(total_titles),
                    "chapters_scanned": int(len(chapters_to_fetch)),
                    "discovered_chapters": int(len(chapters_to_fetch)),
                    "codes_completed": 1,
                    "codes_total": 1,
                },
            )
        return out

    def _extract_statute_text(self, payload: bytes) -> str:
        if not payload:
            return ""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ""

        soup = BeautifulSoup(payload, "html.parser")
        text = " ".join(soup.get_text(" ", strip=True).split())
        match = re.search(
            r"(Section\s+[0-9A-Z:.-]+.*?Source\.[^\n]*?(?:\d{4}[^\n]*)?)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1)[:4000]
        return text[:4000]

    async def _discover_archived_rsa_urls(self, limit: int = 180) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=www.gencourt.state.nh.us/rsa/html/*"
            "&output=json&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._request_text_direct(cdx_url, timeout=35)
            if not payload:
                payload = await self._fetch_page_content_with_archival_fallback(cdx_url, timeout_seconds=35)
            rows = self._parse_json_rows(payload)
        except Exception:
            return []

        out: List[str] = []
        seen = set()
        for row in rows:
            if len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue
            lower_original = original.lower()
            if "/rsa/html/" not in lower_original:
                continue
            replay = self._normalize_wayback_like_url(
                f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}"
            )
            if replay in seen:
                continue
            seen.add(replay)
            out.append(replay)
            if len(out) >= limit:
                break

        return out

    def _normalize_wayback_like_url(self, value: str) -> str:
        url = str(value or "").strip()
        if not url:
            return url
        url = re.sub(r"(web\.archive\.org/web/\d+/https?):/([^/])", r"\1://\2", url, flags=re.IGNORECASE)
        url = re.sub(r"(web\.archive\.org/web/\d+/http):/([^/])", r"\1://\2", url, flags=re.IGNORECASE)
        return url

    def _parse_json_rows(self, payload: bytes) -> List[List[object]]:
        if not payload:
            return []
        try:
            parsed = json.loads(payload.decode("utf-8", errors="ignore"))
        except Exception:
            return []
        if not isinstance(parsed, list):
            return []
        return [row for row in parsed[1:] if isinstance(row, list)]

    def _is_archived_index_candidate(self, url: str) -> bool:
        value = self._normalize_wayback_like_url(str(url or ""))
        lower = value.lower()
        if "/rsa/html/" not in lower:
            return False
        if "/rsa/html/nhtoc" in lower:
            return True
        if lower.endswith("/rsa/html") or lower.endswith("/rsa/html/"):
            return True
        if self._NH_SECTIONISH_ARCHIVE_RE.search(lower):
            return False
        return lower.endswith(".htm")

    def official_title_url(self, title_number: Any) -> str:
        roman = str(title_number or "").strip().upper()
        return f"{self.get_base_url()}/rsa/html/NHTOC/NHTOC-{roman}.htm"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official New Hampshire RSA title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"nh:title-{number.lower()}",
                    "title_number": number,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"New Hampshire Revised Statutes Title {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host in {"www.gencourt.state.nh.us", "gencourt.state.nh.us", "gc.nh.gov"} or host.endswith(
            ".gencourt.state.nh.us"
        )

    def _looks_like_secondary_url(self, url: str) -> bool:
        lowered = str(url or "").strip().lower()
        return any(
            marker in lowered
            for marker in ("justia.com", "findlaw.com", "unicourt", "law.cornell.edu")
        )

    def _official_http_get(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(2, min(int(timeout_seconds or 8), 8))
        headers = {
            "User-Agent": "ipfs-datasets-new-hampshire-official-catalog/1.0",
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
            match = self._NH_TITLE_HREF_RE.search(absolute) or self._NH_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = str(match.group(1) or "").strip().upper()
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
        """Enumerate every official New Hampshire RSA title."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_gencourt"
        return rows

    def fetch_official(self, code: str = "NH"):
        """Acquire the exhaustive official New Hampshire RSA title catalog.

        Live HTTPS retains the official gencourt RSA index. Every RSA title is
        enumerated with an official gencourt.state.nh.us URL. This hook never
        returns fixture bytes or secondary-mirror hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "NH").strip().upper() or "NH"
        if normalized != "NH":
            raise ValueError(f"NewHampshireScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "new hampshire official catalog enumeration rejected incomplete title reacquisition"
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


_NORMALIZED_STATUTE_FIELD_NAMES = {field.name for field in dataclass_fields(NormalizedStatute)}
_STATUTE_METADATA_FIELD_NAMES = {field.name for field in dataclass_fields(StatuteMetadata)}


def _statute_from_checkpoint_row(
    row: Dict[str, Any],
    *,
    default_state_code: str,
    default_state_name: str,
    default_code_name: str,
) -> Optional[NormalizedStatute]:
    if not isinstance(row, dict):
        return None
    kwargs: Dict[str, Any] = {}
    for name in _NORMALIZED_STATUTE_FIELD_NAMES:
        if name in row:
            kwargs[name] = row.get(name)
    metadata_payload = kwargs.get("metadata")
    if isinstance(metadata_payload, dict):
        metadata_kwargs = {
            key: metadata_payload.get(key)
            for key in _STATUTE_METADATA_FIELD_NAMES
            if key in metadata_payload
        }
        history = metadata_kwargs.get("history")
        if history is None:
            metadata_kwargs["history"] = []
        elif not isinstance(history, list):
            metadata_kwargs["history"] = [str(history)]
        kwargs["metadata"] = StatuteMetadata(**metadata_kwargs)
    elif not isinstance(metadata_payload, StatuteMetadata):
        kwargs["metadata"] = None

    kwargs["state_code"] = str(kwargs.get("state_code") or default_state_code).upper()
    kwargs["state_name"] = str(kwargs.get("state_name") or default_state_name).strip() or default_state_name
    kwargs["code_name"] = str(kwargs.get("code_name") or default_code_name).strip() or default_code_name
    kwargs["statute_id"] = str(kwargs.get("statute_id") or "").strip()
    if not kwargs["statute_id"]:
        return None
    kwargs["source_url"] = str(kwargs.get("source_url") or "").strip()
    kwargs["scraped_at"] = str(kwargs.get("scraped_at") or datetime.now().isoformat())
    kwargs["scraper_version"] = str(kwargs.get("scraper_version") or "1.0")
    kwargs["structured_data"] = dict(kwargs.get("structured_data") or {})
    return NormalizedStatute(**kwargs)


class _NewHampshireCheckpoint:
    """Best-effort partial progress checkpoint for New Hampshire archive crawls."""

    def __init__(self, state_code: str) -> None:
        raw_dir = current_partial_checkpoint_run_directory()
        if not raw_dir:
            self.path: Optional[Path] = None
        else:
            self.path = Path(raw_dir).expanduser().resolve() / f"STATE-{state_code.upper()}-partial.json"
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_code = state_code.upper()
        self.interval = max(1, int(float(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_INTERVAL", "500") or 500)))
        self.last_count = 0
        self.last_write_ts = 0.0
        self.last_stage_label = ""

    def load(
        self,
        *,
        default_state_name: str,
        default_code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        if not self.path or not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        rows = payload.get("statutes") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        loaded: List[NormalizedStatute] = []
        seen_keys = set()
        for row in rows:
            statute = _statute_from_checkpoint_row(
                row,
                default_state_code=self.state_code,
                default_state_name=default_state_name,
                default_code_name=default_code_name,
            )
            if statute is None:
                continue
            key = str(statute.statute_id or statute.source_url or "").strip().lower()
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            loaded.append(statute)
            if max_statutes is not None and len(loaded) >= int(max_statutes):
                break
        self.last_count = len(loaded)
        return loaded

    def maybe_write(
        self,
        statutes: List[NormalizedStatute],
        *,
        code_name: str,
        stage_label: str,
        progress: Optional[Dict[str, Any]] = None,
    ) -> None:
        count = len(statutes)
        has_progress = isinstance(progress, dict) and bool(progress)
        current_stage_label = str(stage_label or "").strip()
        if not self.path:
            return
        if count <= 0 and not has_progress:
            return
        now_ts = time.time()
        stage_changed = bool(current_stage_label) and current_stage_label != self.last_stage_label
        min_seconds = 30 if has_progress else 120
        if (
            not stage_changed
            and count - self.last_count < self.interval
            and now_ts - self.last_write_ts < min_seconds
        ):
            return
        self.write(statutes, code_name=code_name, stage_label=stage_label, progress=progress)

    def write(
        self,
        statutes: List[NormalizedStatute],
        *,
        code_name: str,
        stage_label: str,
        progress: Optional[Dict[str, Any]] = None,
        replace_statutes: bool = False,
    ) -> None:
        if not self.path:
            return
        existing_rows: List[Dict[str, Any]] = []
        existing_progress: Dict[str, Any] = {}
        if self.path.exists() and not replace_statutes:
            try:
                existing_payload = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                existing_payload = {}
            if isinstance(existing_payload, dict):
                raw_rows = existing_payload.get("statutes")
                if isinstance(raw_rows, list):
                    existing_rows = [row for row in raw_rows if isinstance(row, dict)]
                raw_progress = existing_payload.get("progress")
                if isinstance(raw_progress, dict):
                    existing_progress = dict(raw_progress)

        serialized_rows = [statute.to_dict() for statute in statutes if isinstance(statute, NormalizedStatute)]
        if not serialized_rows and existing_rows:
            serialized_rows = list(existing_rows)
        elif serialized_rows and existing_rows and len(serialized_rows) < len(existing_rows):
            merged_rows = list(existing_rows)
            seen_keys: set[str] = set()
            for row in merged_rows:
                statute_id = str(row.get("statute_id") or "").strip().lower()
                source_url = str(row.get("source_url") or "").strip().lower()
                if statute_id:
                    seen_keys.add(f"id:{statute_id}")
                if source_url:
                    seen_keys.add(f"url:{source_url}")
            for row in serialized_rows:
                statute_id = str(row.get("statute_id") or "").strip().lower()
                source_url = str(row.get("source_url") or "").strip().lower()
                key_id = f"id:{statute_id}" if statute_id else ""
                key_url = f"url:{source_url}" if source_url else ""
                if (key_id and key_id in seen_keys) or (key_url and key_url in seen_keys):
                    continue
                if key_id:
                    seen_keys.add(key_id)
                if key_url:
                    seen_keys.add(key_url)
                merged_rows.append(row)
            serialized_rows = merged_rows

        progress_payload: Dict[str, Any] = {}
        if existing_progress:
            progress_payload.update(existing_progress)
        if isinstance(progress, dict) and progress:
            progress_payload.update(progress)

        payload = {
            "state_code": self.state_code,
            "updated_at": time.time(),
            "statutes_count": len(serialized_rows),
            "code_name": code_name,
            "stage_label": stage_label,
            "statutes": serialized_rows,
        }
        if progress_payload:
            payload["progress"] = progress_payload
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(serialized_rows)
        self.last_write_ts = time.time()
        self.last_stage_label = str(stage_label or "").strip()


# Register this scraper with the registry
StateScraperRegistry.register("NH", NewHampshireScraper)
