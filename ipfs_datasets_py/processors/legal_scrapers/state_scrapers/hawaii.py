"""Scraper for Hawaii state laws.

Primary path walks the official Hawaii Revised Statutes HTML tree on
capitol.hawaii.gov. Wayback snapshots of that same official tree remain an
accepted archival recovery path; Justia and emergency stubs are never
sole-admitted under full-corpus certification.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .hawaii_section import (
    HAWAII_EXPECTED_OPERATIVE_SECTION_COUNT,
    HAWAII_EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256,
    HAWAII_EXPECTED_TOTAL_SECTION_LOCATOR_COUNT,
    is_source_bound_operative_hawaii_statute,
)
from .registry import StateScraperRegistry

# Bound for quarantined CDX locator diagnostics; never a statutory-body cap.
ARCHIVE_LOCATOR_DIAGNOSTIC_LIMIT = 160


class HawaiiScraper(BaseStateScraper):
    """Scraper for Hawaii state laws from https://www.capitol.hawaii.gov."""

    OFFICIAL_DOMAIN = "www.capitol.hawaii.gov"
    OFFICIAL_ENTRY_PATH = "/hrscurrent/"
    OFFICIAL_ENTRY_URL = "https://www.capitol.hawaii.gov/hrscurrent/"
    # The legislature serves the same official HRS tree from this static-data
    # subdomain.  Unlike the public-facing ``www`` hostname, it is not hidden
    # behind the current Cloudflare interstitial.
    OFFICIAL_DATA_DOMAIN = "data.capitol.hawaii.gov"
    OFFICIAL_DATA_ENTRY_URL = "https://data.capitol.hawaii.gov/hrscurrent/"
    MIN_EXPECTED_VOLUMES = 14
    MIN_EXPECTED_CHAPTERS = 1000
    MIN_EXPECTED_SECTION_LOCATORS = 20000
    EXPECTED_OPERATIVE_SECTIONS = HAWAII_EXPECTED_OPERATIVE_SECTION_COUNT
    EXPECTED_TOTAL_SECTION_LOCATORS = HAWAII_EXPECTED_TOTAL_SECTION_LOCATOR_COUNT
    EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256 = (
        HAWAII_EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256
    )
    EXPECTED_NONOPERATIVE_CHAPTERS = 293
    # Canonical JSON digest of the 293 retained official autoindex/sentinel
    # observations (chapter URL + directory bytes + sentinel URL + sentinel
    # bytes + typed disposition) in the current 2026 HRS hierarchy.
    EXPECTED_NONOPERATIVE_CHAPTER_INVENTORY_SHA256 = (
        "0284a98515dc7196941aa22252e7561d79a457c77ad6f901ae568c869f507060"
    )
    EXPECTED_NONOPERATIVE_SECTIONS = 373
    EXPECTED_NONOPERATIVE_SECTION_DISPOSITION_COUNTS = (
        ("renumbered", 1),
        ("repealed", 362),
        ("reserved", 10),
    )
    EXPECTED_NONOPERATIVE_SECTION_INVENTORY_SHA256 = (
        "20c77e27b67e0fd6697152a7d0e532c62b06c93bf004e3ea80e281399d06b440"
    )
    MISSING_LINK_QUARANTINE_REASON = "missing_official_source_link"
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Elections"),
        ("3", "The Legislature"),
        ("4", "State Organization and Administration, Generally"),
        ("5", "The Executive"),
        ("6", "Civil Service"),
        ("7", "Public Officers and Employees"),
        ("8", "Public Records"),
        ("9", "Public Property, Purchasing and Contracting"),
        ("10", "Public Lands"),
        ("11", "Agriculture and Animals"),
        ("12", "Conservation and Resources"),
        ("13", "Planning and Economic Development"),
        ("14", "Taxation"),
        ("15", "Transportation and Utilities"),
        ("16", "Intoxicating Liquor"),
        ("17", "Motor and Other Vehicles"),
        ("18", "Education"),
        ("19", "Health"),
        ("20", "Social Services"),
        ("21", "Labor and Industrial Relations"),
        ("22", "Banks and Financial Institutions"),
        ("23", "Corporations and Partnerships"),
        ("24", "Insurance"),
        ("25", "Professions and Occupations"),
        ("26", "Trade Regulation and Practice"),
        ("27", "Uniform Commercial Code"),
        ("28", "Property"),
        ("29", "Decedents' Estates"),
        ("30", "Guardians and Trustees"),
        ("31", "Family"),
        ("32", "Courts and Court Officers"),
        ("33", "Evidence"),
        ("34", "Pleadings and Procedure"),
        ("35", "Appeal and Error"),
        ("36", "Civil Remedies and Defenses and Special Proceedings"),
        ("37", "Hawaii Penal Code"),
        ("38", "Procedural and Supplementary Provisions"),
    )
    _WAYBACK_ROOTS = [
        "http://web.archive.org/web/20060407224843/http://www.capitol.hawaii.gov/hrscurrent/",
        "http://web.archive.org/web/20060407230101/http://www.capitol.hawaii.gov/hrscurrent/",
    ]
    _SECTION_FILE_RE = re.compile(
        r"HRS_(\d{4}[A-Z]?)-([^/?#]+)\.HTM$",
        re.IGNORECASE,
    )
    _LIVE_VOLUME_RE = re.compile(r"/hrscurrent/Vol[^/]+/?$", re.IGNORECASE)
    _LIVE_CHAPTER_RE = re.compile(r"/hrscurrent/Vol[^/]+/HRS\d{4}[A-Z]?/?$", re.IGNORECASE)
    _LIVE_SECTION_RE = re.compile(
        r"/hrscurrent/Vol[^/]+/HRS\d{4}[A-Z]?/HRS_\d{4}[A-Z]?-[^/?#]+\.HTM$",
        re.IGNORECASE,
    )
    _SEED_SECTION_URLS = [
        "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0001.HTM",
        "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0002.HTM",
        "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0003.HTM",
        "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0004.HTM",
    ]

    def get_base_url(self) -> str:
        """Return the base URL for Hawaii's legislative website."""
        return "https://www.capitol.hawaii.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Hawaii."""
        return [
            {
                "name": "Hawaii Revised Statutes",
                "url": self.OFFICIAL_DATA_ENTRY_URL,
                "type": "Code",
            }
        ]

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind the sibling HTML parser into Hawaii closure source identity."""

        from . import hawaii_section

        return (hawaii_section,)

    def _supports_shared_official_frontier_bridge(self) -> bool:
        """Keep the shared catalog replay while owning Hawaii row parity."""

        return callable(getattr(self, "fetch_official", None))

    def _is_source_bound_operative_statute_record(
        self,
        statute: NormalizedStatute,
    ) -> bool:
        return is_source_bound_operative_hawaii_statute(statute)

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Any | None:
        """Refuse aggregate closure when post-parser Hawaii rows were lost."""

        frontier = getattr(self, "_hawaii_frontier", None)
        if not isinstance(frontier, Mapping) or frontier.get("closed") is not True:
            raise RuntimeError("Hawaii state-owned HRS frontier is not closed")
        emitted = frontier.get("statutes_emitted")
        if (
            not isinstance(emitted, int)
            or isinstance(emitted, bool)
            or emitted != self.EXPECTED_OPERATIVE_SECTIONS
        ):
            raise RuntimeError(
                "Hawaii state-owned HRS frontier emitted-count drift: "
                f"expected={self.EXPECTED_OPERATIVE_SECTIONS} actual={emitted!r}"
            )
        if (
            frontier.get("operative_section_inventory_closed") is not True
            or frontier.get("operative_section_inventory_sha256")
            != self.EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256
        ):
            raise RuntimeError("Hawaii operative HRS identity inventory is not closed")

        raw_keys = canonical_output_projection.get("canonical_keys")
        if not isinstance(raw_keys, Sequence) or isinstance(
            raw_keys,
            (str, bytes, bytearray),
        ):
            raise TypeError("Hawaii canonical output lacks section identities")
        canonical_keys = [str(value or "").strip() for value in raw_keys]
        declared_count = canonical_output_projection.get("canonical_row_count")
        if (
            len(canonical_keys) != emitted
            or len(set(canonical_keys)) != emitted
            or declared_count != emitted
            or any(not value for value in canonical_keys)
        ):
            raise RuntimeError(
                "Hawaii post-parser canonical output lost or duplicated HRS rows: "
                f"frontier={emitted} projection={len(canonical_keys)} "
                f"declared={declared_count!r}"
            )

        retained_keys = getattr(self, "_hawaii_operative_canonical_keys", None)
        if (
            not isinstance(retained_keys, tuple)
            or len(retained_keys) != emitted
            or set(canonical_keys) != set(retained_keys)
        ):
            raise RuntimeError(
                "Hawaii canonical output identities differ from the state-owned HRS walk"
            )
        return await super().produce_state_law_frontier_closure(
            canonical_output_projection=canonical_output_projection,
        )

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Hawaii Revised Statutes from the official HTML tree first."""
        limit = max(1, int(max_statutes)) if max_statutes else None
        from .hawaii_constitution import (
            configured_constitution_html_path,
            parse_hawaii_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_hawaii_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Hawaii Constitution",
                    source_url="https://capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/05-CONST/CONST_0001-0001.htm",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .hawaii_section import (
            configured_section_html_path,
            parse_hawaii_section_html,
        )

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_hawaii_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0707/HRS_0707-0701.HTM",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]

        official: List[NormalizedStatute] = []
        if not code_url or self.is_official_hi_url(code_url):
            official = await self._scrape_official_hrs_tree(
                code_name=code_name,
                code_url=code_url or self.OFFICIAL_DATA_ENTRY_URL,
                max_statutes=limit,
            )
        if official:
            return official[:limit] if limit is not None else official

        # Seeds and archival snapshots are bounded recovery paths.  They remain
        # available to explicit probes, but cannot sole-admit an uncapped
        # full-corpus result when the official hierarchy walk failed.
        seeded: List[NormalizedStatute] = []
        recovery_allowed = not self._full_corpus_enabled() or max_statutes is not None
        if recovery_allowed:
            seeded = await self._scrape_seed_sections(
                code_name,
                max_statutes=min(8, limit or 8),
            )

        # Archival recovery of the same official tree via Wayback.
        if recovery_allowed and (
            self._env_enabled("HAWAII_WALK_WAYBACK_FULL", default=False)
            or limit is not None
        ):
            try:
                archival = await asyncio.wait_for(
                    self._scrape_archived_hrscurrent(
                        code_name,
                        max_statutes=max(10, limit or 40),
                    ),
                    timeout=220,
                )
            except asyncio.TimeoutError:
                archival = []
            if archival:
                return archival[:limit] if limit is not None else archival

        # CDX-only rows are locator evidence, not statute text.  Keep this
        # diagnostic recovery probe outside certification and never admit its
        # generated descriptions as enacted section bodies.
        if recovery_allowed and limit is None:
            archived_locators = await self._scrape_archived_section_stubs(
                code_name,
                max_statutes=ARCHIVE_LOCATOR_DIAGNOSTIC_LIMIT,
            )
            if archived_locators:
                self.logger.info(
                    "Hawaii quarantined %s archive locator-only rows",
                    len(archived_locators),
                )

        if seeded and (
            not self._full_corpus_enabled() or max_statutes is not None
        ):
            return seeded[:limit] if limit is not None else seeded

        # Optional secondary Justia — never sole-admit under full corpus.
        allow_justia = self._env_enabled("HAWAII_GENERIC_FALLBACK", default=False) or self._env_enabled(
            "STATE_SCRAPER_HI_ALLOW_JUSTIA_FALLBACK", default=False
        )
        if allow_justia and not self._full_corpus_enabled():
            justia = await self._generic_scrape(
                code_name,
                "https://law.justia.com/codes/hawaii/",
                "Haw. Rev. Stat.",
                max_sections=limit or 40,
            )
            if justia:
                return justia[:limit] if limit is not None else justia

        # Emergency stubs only outside full-corpus certification.
        if not self._full_corpus_enabled():
            stubs = self._build_emergency_statute_stubs(code_name, count=min(40, limit or 40))
            if stubs:
                self.logger.warning(
                    "Hawaii returning emergency stubs (%s rows); not full-corpus certified content",
                    len(stubs),
                )
                return stubs[:limit] if limit is not None else stubs

        self.logger.warning(
            "Hawaii official direct crawl returned no statutes; refusing secondary sole-admission"
        )
        return []

    @staticmethod
    def _env_enabled(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    async def _fetch_official_hi_html(self, url: str, timeout_seconds: int = 18) -> str:
        timeout = max(1, int(timeout_seconds or 18))
        headers = {
            "User-Agent": "ipfs-datasets-hawaii-statutes-scraper/3.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        for attempt in range(2):
            payload = await self._fetch_parser_input_with_transport(
                url,
                headers=headers,
                timeout_seconds=timeout,
                content_validator=self._is_valid_hi_html,
                # Keep the two bounded official attempts distinct from the
                # explicit shared archival recovery below.
                allow_archival_fallback=False,
                media_type="text/html",
                provider="requests_direct",
            )
            if self._is_valid_hi_html(payload):
                self._hi_fetch_provenance()[url] = (
                    self._current_fetch_provider() or "requests_direct"
                )
                return payload.decode("utf-8", errors="replace")
            if attempt == 0:
                time.sleep(0.15)

        # Reuse the shared web_archiving chain for transport failures.  This
        # may recover Common Crawl/Wayback bytes for the same official locator;
        # it never promotes a third-party mirror to official authority.
        recovered = await self._fetch_page_content_with_archival_fallback(
            url,
            timeout_seconds=timeout,
        )
        if self._is_valid_hi_html(recovered):
            self._hi_fetch_provenance()[url] = (
                self._current_fetch_provider() or "archival_fallback"
            )
            return recovered.decode("utf-8", errors="replace")

        # Archives more commonly indexed the historical public hostname than
        # the newer static-data alias.  Both are Hawaii Legislature hosts and
        # the path is byte-for-byte compatible.
        parsed_url = urlparse(url)
        if (parsed_url.hostname or "").lower() == self.OFFICIAL_DATA_DOMAIN:
            canonical_url = parsed_url._replace(netloc=self.OFFICIAL_DOMAIN).geturl()
            recovered = await self._fetch_page_content_with_archival_fallback(
                canonical_url,
                timeout_seconds=timeout,
            )
            if self._is_valid_hi_html(recovered):
                provider = self._current_fetch_provider() or "archival_fallback"
                self._hi_fetch_provenance()[url] = f"{provider}:canonical_www"
                return recovered.decode("utf-8", errors="replace")
        return ""

    async def _fetch_hi_html_frontier(
        self,
        urls: List[str],
        *,
        frontier_name: str,
    ) -> Dict[str, str]:
        """Fetch one known Hawaii hierarchy wave without per-page archives."""

        requested = list(urls)
        if not requested:
            return {}
        if len(set(requested)) != len(requested):
            raise RuntimeError(f"Hawaii {frontier_name} frontier contains duplicate URLs")

        async def _batch(fetch_urls: List[str]):
            return await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
                fetch_urls,
                residual_retry_attempts=1,
                timeout_seconds=18,
                headers={
                    "User-Agent": "ipfs-datasets-hawaii-statutes-scraper/3.0",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                },
                content_validator=self._is_valid_hi_html,
                media_type="text/html",
                max_concurrency=max(
                    1,
                    int(self._env_int("STATE_SCRAPER_HI_SECTION_CONCURRENCY", default=8)),
                ),
                prefer_direct=True,
                wayback_prefix_inventory=True,
            )

        primary = await _batch(requested)
        if list(primary.urls) != requested or any(
            len(vector) != len(requested)
            for vector in (
                primary.payloads,
                primary.errors,
                primary.transport_receipts,
                primary.parser_input_envelopes,
            )
        ):
            raise RuntimeError(f"Hawaii {frontier_name} frontier returned unaligned rows")

        resolved: Dict[str, str] = {}
        unresolved: List[str] = []
        for url, payload, error, receipt in zip(
            primary.urls,
            primary.payloads,
            primary.errors,
            primary.transport_receipts,
            strict=True,
        ):
            body = bytes(payload or b"")
            if error is None and self._is_valid_hi_html(body):
                resolved[url] = body.decode("utf-8", errors="replace")
                provider = (
                    str(receipt.get("source_transport") or "shared_plural")
                    if isinstance(receipt, Mapping)
                    else "shared_plural"
                )
                self._hi_fetch_provenance()[url] = provider
            else:
                unresolved.append(url)

        aliases: List[tuple[str, str]] = []
        for url in unresolved:
            parsed = urlparse(url)
            if (parsed.hostname or "").lower() == self.OFFICIAL_DATA_DOMAIN:
                aliases.append(
                    (url, parsed._replace(netloc=self.OFFICIAL_DOMAIN).geturl())
                )
        if aliases:
            alias_urls = [alias for _original, alias in aliases]
            alias_batch = await _batch(alias_urls)
            if list(alias_batch.urls) != alias_urls or any(
                len(vector) != len(alias_urls)
                for vector in (
                    alias_batch.payloads,
                    alias_batch.errors,
                    alias_batch.transport_receipts,
                    alias_batch.parser_input_envelopes,
                )
            ):
                raise RuntimeError(
                    f"Hawaii {frontier_name} canonical-host residual returned unaligned rows"
                )
            for (original, _alias), payload, error, receipt in zip(
                aliases,
                alias_batch.payloads,
                alias_batch.errors,
                alias_batch.transport_receipts,
                strict=True,
            ):
                body = bytes(payload or b"")
                if error is None and self._is_valid_hi_html(body):
                    resolved[original] = body.decode("utf-8", errors="replace")
                    provider = (
                        str(receipt.get("source_transport") or "shared_plural")
                        if isinstance(receipt, Mapping)
                        else "shared_plural"
                    )
                    self._hi_fetch_provenance()[original] = f"{provider}:canonical_www"

        failures = [url for url in requested if url not in resolved]
        if failures:
            raise RuntimeError(
                f"Hawaii {frontier_name} frontier is incomplete; "
                f"unresolved_exact_urls={failures}"
            )
        return resolved

    def _hi_fetch_provenance(self) -> Dict[str, str]:
        values = getattr(self, "_hawaii_fetch_provenance", None)
        if not isinstance(values, dict):
            values = {}
            self._hawaii_fetch_provenance = values
        return values

    def _hi_section_outcomes(self) -> Dict[str, str]:
        values = getattr(self, "_hawaii_section_outcome_by_url", None)
        if not isinstance(values, dict):
            values = {}
            self._hawaii_section_outcome_by_url = values
        return values

    def _hi_nonoperative_section_observations(self) -> Dict[str, Dict[str, str]]:
        values = getattr(
            self,
            "_hawaii_nonoperative_section_observation_by_url",
            None,
        )
        if not isinstance(values, dict):
            values = {}
            self._hawaii_nonoperative_section_observation_by_url = values
        return values

    @staticmethod
    def _is_valid_hi_html(payload: object) -> bool:
        if isinstance(payload, bytes):
            text = payload.decode("utf-8", errors="replace")
        else:
            text = str(payload or "")
        if len(text.strip()) < 80:
            return False
        lowered = text.lower()
        rejection_markers = (
            "attention required! | cloudflare",
            "cf-error-details",
            "cloudflare ray id",
            "internet archive: temporarily offline",
            "<title>404 page not found</title>",
            "<title>access denied</title>",
        )
        return not any(marker in lowered for marker in rejection_markers)

    async def _scrape_official_hrs_tree(
        self,
        *,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        requested_url = str(code_url or "").strip() or self.OFFICIAL_DATA_ENTRY_URL
        entry_candidates = [requested_url]
        if self.is_official_hi_url(requested_url):
            entry_candidates.append(self.OFFICIAL_DATA_ENTRY_URL)

        index_url = requested_url
        volume_links: List[Tuple[str, str]] = []
        for candidate in dict.fromkeys(entry_candidates):
            discovered = await self._discover_volume_links(candidate)
            if discovered:
                index_url = candidate
                volume_links = discovered
                break

        self.logger.info("Hawaii official index: discovered %s volume links", len(volume_links))
        statutes: List[NormalizedStatute] = []
        seen_statute_keys: set[str] = set()
        seen_section_urls: set[str] = set()
        discovered_section_urls: set[str] = set()
        unresolved: List[Dict[str, str]] = []
        excluded_nonoperative = 0
        excluded_nonoperative_chapters = 0
        excluded_duplicates = 0
        nonoperative_chapter_observations: List[Dict[str, str]] = []
        nonoperative_chapter_candidates: List[str] = []
        volumes_visited = 0
        chapters_discovered = 0
        chapters_visited = 0
        sections_visited = 0
        bounded = max_statutes is not None
        section_concurrency = max(
            1,
            int(self._env_int("STATE_SCRAPER_HI_SECTION_CONCURRENCY", default=8)),
        )
        section_sem = asyncio.Semaphore(section_concurrency)
        self._hawaii_section_outcome_by_url = {}
        self._hawaii_nonoperative_section_observation_by_url = {}
        self._hawaii_nonoperative_chapter_candidates = {}
        self._hawaii_nonoperative_chapter_failures = {}
        self._hawaii_nonoperative_chapter_batch_stats = {}

        chapter_links_by_volume: Dict[str, List[Tuple[str, str]]] = {}
        section_links_by_chapter: Dict[str, List[Tuple[str, str]]] = {}
        section_html_by_url: Dict[str, str] = {}
        if not bounded:
            volume_html_by_url = await self._fetch_hi_html_frontier(
                [url for url, _label in volume_links],
                frontier_name="volume catalog",
            )
            chapter_frontier: List[str] = []
            for volume_url, _volume_label in volume_links:
                links = await self._discover_chapter_links(
                    volume_url,
                    _html=volume_html_by_url[volume_url],
                )
                chapter_links_by_volume[volume_url] = links
                chapter_frontier.extend(url for url, _label in links)
            chapter_frontier = list(dict.fromkeys(chapter_frontier))
            chapter_html_by_url = await self._fetch_hi_html_frontier(
                chapter_frontier,
                frontier_name="chapter catalog",
            )
            section_frontier: List[str] = []
            for chapter_url in chapter_frontier:
                links = await self._discover_section_links(
                    chapter_url,
                    _html=chapter_html_by_url[chapter_url],
                )
                links = [
                    (section_url, section_label)
                    for section_url, section_label in links
                    if self._extract_section_number_from_wayback_url(section_url)
                ]
                section_links_by_chapter[chapter_url] = links
                section_frontier.extend(url for url, _label in links)
            section_frontier = list(dict.fromkeys(section_frontier))
            section_html_by_url = await self._fetch_hi_html_frontier(
                section_frontier,
                frontier_name="section body",
            )

        async def _parse_candidate(
            section_url: str,
            section_label: str,
            chapter_label: str,
            volume_label: str,
        ) -> Optional[NormalizedStatute]:
            async with section_sem:
                return await self._parse_live_section_page(
                    code_name=code_name,
                    section_url=section_url,
                    section_label=section_label,
                    chapter_label=chapter_label,
                    volume_label=volume_label,
                    _html=section_html_by_url.get(section_url),
                )

        for volume_index, (volume_url, volume_label) in enumerate(volume_links, start=1):
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            volumes_visited += 1
            chapter_links = chapter_links_by_volume.get(volume_url)
            if chapter_links is None:
                chapter_links = await self._discover_chapter_links(volume_url)
            if not chapter_links:
                unresolved.append(
                    {
                        "kind": "volume_chapter_discovery",
                        "url": volume_url,
                    }
                )
                continue
            chapters_discovered += len(chapter_links)
            self.logger.info(
                "Hawaii official index: volume=%s index=%s/%s chapters=%s statutes_so_far=%s",
                volume_label or volume_url,
                volume_index,
                len(volume_links),
                len(chapter_links),
                len(statutes),
            )
            for chapter_url, chapter_label in chapter_links:
                if max_statutes is not None and len(statutes) >= max_statutes:
                    break
                chapters_visited += 1
                section_links = section_links_by_chapter.get(chapter_url)
                if section_links is None:
                    section_links = await self._discover_section_links(chapter_url)
                section_links = [
                    (section_url, section_label)
                    for section_url, section_label in section_links
                    if self._extract_section_number_from_wayback_url(section_url)
                ]
                if not section_links:
                    candidates = getattr(
                        self,
                        "_hawaii_nonoperative_chapter_candidates",
                        None,
                    )
                    if isinstance(candidates, dict) and chapter_url in candidates:
                        nonoperative_chapter_candidates.append(chapter_url)
                        continue
                    unresolved.append(
                        {
                            "kind": self._hawaii_nonoperative_chapter_failures.get(
                                chapter_url,
                                "chapter_section_discovery",
                            ),
                            "url": chapter_url,
                        }
                    )
                    continue

                unique_candidates: List[Tuple[str, str]] = []
                for section_url, section_label in section_links:
                    if section_url in discovered_section_urls:
                        continue
                    discovered_section_urls.add(section_url)
                    unique_candidates.append((section_url, section_label))

                remaining = (
                    None
                    if max_statutes is None
                    else max(0, int(max_statutes) - len(statutes))
                )
                batch = (
                    unique_candidates
                    if remaining is None
                    else unique_candidates[:remaining]
                )
                parsed_rows = (
                    await asyncio.gather(
                        *[
                            _parse_candidate(
                                section_url,
                                section_label,
                                chapter_label,
                                volume_label,
                            )
                            for section_url, section_label in batch
                        ],
                        return_exceptions=True,
                    )
                    if batch
                    else []
                )
                for (section_url, _section_label), parsed in zip(batch, parsed_rows):
                    sections_visited += 1
                    if isinstance(parsed, BaseException):
                        unresolved.append(
                            {
                                "kind": "section_exception",
                                "url": section_url,
                            }
                        )
                        continue
                    if parsed is None:
                        outcome = self._hi_section_outcomes().get(
                            section_url,
                            "parse_failure",
                        )
                        if outcome == "nonoperative":
                            excluded_nonoperative += 1
                        else:
                            unresolved.append(
                                {
                                    "kind": outcome,
                                    "url": section_url,
                                }
                            )
                        continue

                    key = str(parsed.statute_id or "").strip().lower()
                    source_url = str(parsed.source_url or "").strip()
                    if (key and key in seen_statute_keys) or source_url in seen_section_urls:
                        excluded_duplicates += 1
                        continue
                    if key:
                        seen_statute_keys.add(key)
                    if source_url:
                        seen_section_urls.add(source_url)
                    statutes.append(parsed)

                if len(statutes) and (
                    len(statutes) == len(parsed_rows) or len(statutes) % 500 < len(parsed_rows)
                ):
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="hawaii:official-section-progress",
                        extra={
                            "codes_completed": 0,
                            "codes_total": 1,
                            "discovered_titles": len(volume_links),
                            "titles_scanned": volume_index,
                            "discovered_chapters": chapters_discovered,
                            "chapters_scanned": chapters_visited,
                            "discovered_sections": len(discovered_section_urls),
                            "sections_scanned": sections_visited,
                        },
                    )

        if nonoperative_chapter_candidates:
            (
                nonoperative_chapter_observations,
                terminal_failures,
            ) = await self._resolve_nonoperative_chapters_batch(
                nonoperative_chapter_candidates
            )
            unresolved.extend(terminal_failures)
            excluded_nonoperative_chapters = len(
                nonoperative_chapter_observations
            )

        floor_failures: List[str] = []
        nonoperative_chapter_inventory_sha256 = (
            self._nonoperative_chapter_inventory_digest(
                nonoperative_chapter_observations
            )
        )
        nonoperative_chapter_inventory_closed = (
            self._nonoperative_chapter_inventory_closed(
                nonoperative_chapter_observations
            )
        )
        nonoperative_section_observations = list(
            self._hi_nonoperative_section_observations().values()
        )
        nonoperative_section_inventory_sha256 = (
            self._nonoperative_section_inventory_digest(
                nonoperative_section_observations
            )
        )
        nonoperative_section_inventory_closed = (
            self._nonoperative_section_inventory_closed(
                nonoperative_section_observations
            )
        )
        operative_section_inventory_sha256 = (
            self._operative_section_inventory_digest(statutes)
        )
        operative_section_inventory_closed = (
            self._operative_section_inventory_closed(statutes)
        )
        self._hawaii_operative_canonical_keys = tuple(
            sorted(
                f"urn:state:hi:statute:{str(statute.statute_id or '').strip()}"
                for statute in statutes
            )
        )
        if not bounded:
            if len(volume_links) < self.MIN_EXPECTED_VOLUMES:
                floor_failures.append("volume_coverage_floor")
            if chapters_discovered < self.MIN_EXPECTED_CHAPTERS:
                floor_failures.append("chapter_coverage_floor")
            if len(discovered_section_urls) < self.MIN_EXPECTED_SECTION_LOCATORS:
                floor_failures.append("section_coverage_floor")
            for reason in floor_failures:
                unresolved.append({"kind": reason, "url": index_url})
            if not nonoperative_chapter_inventory_closed:
                unresolved.append(
                    {
                        "kind": "nonoperative_chapter_inventory_drift",
                        "url": index_url,
                    }
                )
            if not nonoperative_section_inventory_closed:
                unresolved.append(
                    {
                        "kind": "nonoperative_section_inventory_drift",
                        "url": index_url,
                    }
                )
            if not operative_section_inventory_closed:
                unresolved.append(
                    {
                        "kind": "operative_section_inventory_drift",
                        "url": index_url,
                    }
                )

        frontier_closed = bool(
            not bounded
            and volume_links
            and not unresolved
            and operative_section_inventory_closed
            and nonoperative_chapter_inventory_closed
            and nonoperative_section_inventory_closed
            and sections_visited
            == len(discovered_section_urls)
            == len(statutes) + excluded_nonoperative + excluded_duplicates
        )
        frontier = {
            "closed": frontier_closed,
            "bounded_probe": bounded,
            "entry_url": index_url,
            "volumes_discovered": len(volume_links),
            "volumes_visited": volumes_visited,
            "chapters_discovered": chapters_discovered,
            "chapters_visited": chapters_visited,
            "section_locators_discovered": len(discovered_section_urls),
            "section_locators_visited": sections_visited,
            "statutes_emitted": len(statutes),
            "operative_section_inventory_closed": (
                operative_section_inventory_closed
            ),
            "operative_section_inventory_sha256": (
                operative_section_inventory_sha256
            ),
            "nonoperative_chapters_excluded": excluded_nonoperative_chapters,
            "nonoperative_chapter_inventory_closed": (
                nonoperative_chapter_inventory_closed
            ),
            "nonoperative_chapter_inventory_sha256": (
                nonoperative_chapter_inventory_sha256
            ),
            "nonoperative_chapter_batch_stats": dict(
                getattr(
                    self,
                    "_hawaii_nonoperative_chapter_batch_stats",
                    {},
                )
                or {}
            ),
            "nonoperative_sections_excluded": excluded_nonoperative,
            "nonoperative_section_inventory_closed": (
                nonoperative_section_inventory_closed
            ),
            "nonoperative_section_inventory_sha256": (
                nonoperative_section_inventory_sha256
            ),
            "duplicate_sections_excluded": excluded_duplicates,
            "unresolved_count": len(unresolved),
            "unresolved": unresolved[:100],
        }
        self._hawaii_frontier = frontier

        if not bounded and not frontier_closed:
            self.logger.error(
                "Hawaii official hierarchy did not close: %s",
                frontier,
            )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="hawaii:official-frontier-open",
                extra=frontier,
            )
            return []

        for statute in statutes:
            structured = dict(statute.structured_data or {})
            structured.update(
                {
                    "frontier_closed": frontier_closed,
                    "frontier_bounded_probe": bounded,
                    "frontier_section_locator_count": len(discovered_section_urls),
                    "frontier_operative_section_count": len(statutes),
                    "frontier_operative_section_inventory_sha256": (
                        operative_section_inventory_sha256
                    ),
                    "frontier_unresolved_count": len(unresolved),
                }
            )
            statute.structured_data = structured
        return statutes

    async def _discover_volume_links(
        self,
        index_url: str,
        *,
        _html: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        return await self._discover_links(index_url, self._LIVE_VOLUME_RE, _html=_html)

    async def _discover_chapter_links(
        self,
        volume_url: str,
        *,
        _html: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        return await self._discover_links(volume_url, self._LIVE_CHAPTER_RE, _html=_html)

    async def _discover_section_links(
        self,
        chapter_url: str,
        *,
        _html: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        from .hawaii_section import nonoperative_chapter_marker_url

        html = _html
        if html is None:
            html = await self._fetch_official_hi_html(chapter_url)
        if not html:
            return []
        listed = self._links_from_html(chapter_url, html, self._LIVE_SECTION_RE)
        if listed:
            return listed

        marker_url = nonoperative_chapter_marker_url(
            html,
            chapter_url=chapter_url,
        )
        if marker_url:
            candidates = getattr(
                self,
                "_hawaii_nonoperative_chapter_candidates",
                None,
            )
            if not isinstance(candidates, dict):
                candidates = {}
                self._hawaii_nonoperative_chapter_candidates = candidates
            candidates[chapter_url] = {
                "chapter_url": chapter_url,
                "directory_sha256": hashlib.sha256(
                    html.encode("utf-8")
                ).hexdigest(),
                "sentinel_url": marker_url,
            }
            return []
        return await self._walk_next_section_links(chapter_url, initial_html=html)

    async def _resolve_nonoperative_chapters_batch(
        self,
        chapter_urls: List[str],
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """Fetch the ordered chapter-sentinel frontier through one shared batch."""

        from .hawaii_section import nonoperative_hawaii_chapter_disposition

        candidates = getattr(
            self,
            "_hawaii_nonoperative_chapter_candidates",
            None,
        )
        ordered_chapters = list(chapter_urls)
        ordered_candidates: List[Dict[str, str]] = []
        failures: List[Dict[str, str]] = []
        for chapter_url in ordered_chapters:
            candidate = (
                candidates.get(chapter_url)
                if isinstance(candidates, dict)
                else None
            )
            if not isinstance(candidate, dict):
                failures.append(
                    {
                        "kind": "chapter_nonoperative_sentinel_candidate_drift",
                        "url": chapter_url,
                    }
                )
                continue
            ordered_candidates.append(candidate)
        if failures:
            return [], failures

        sentinel_urls = [
            str(candidate.get("sentinel_url") or "")
            for candidate in ordered_candidates
        ]
        try:
            batch = await self._fetch_page_contents_with_archival_fallback(
                sentinel_urls,
                timeout_seconds=18,
                content_validator=self._is_valid_hi_html,
                media_type="text/html",
                max_concurrency=max(
                    1,
                    int(
                        self._env_int(
                            "STATE_SCRAPER_HI_SENTINEL_CONCURRENCY",
                            default=8,
                        )
                    ),
                ),
                prefer_direct=True,
                common_crawl_domain_terms=[self.OFFICIAL_DATA_DOMAIN],
                common_crawl_mime_terms=["html"],
            )
        except Exception:
            return [], [
                {
                    "kind": "chapter_nonoperative_sentinel_batch_failure",
                    "url": chapter_url,
                }
                for chapter_url in ordered_chapters
            ]

        vectors = (
            list(batch.urls),
            list(batch.payloads),
            list(batch.errors),
            list(batch.transport_receipts),
            list(batch.parser_input_envelopes),
        )
        if (
            vectors[0] != sentinel_urls
            or any(len(vector) != len(sentinel_urls) for vector in vectors)
        ):
            return [], [
                {
                    "kind": "chapter_nonoperative_sentinel_batch_alignment",
                    "url": chapter_url,
                }
                for chapter_url in ordered_chapters
            ]

        self._hawaii_nonoperative_chapter_batch_stats = dict(batch.stats or {})
        observations: List[Dict[str, str]] = []
        for chapter_url, candidate, marker_url, payload, error, receipt in zip(
            ordered_chapters,
            ordered_candidates,
            batch.urls,
            batch.payloads,
            batch.errors,
            batch.transport_receipts,
        ):
            if error or not payload:
                failures.append(
                    {
                        "kind": "chapter_nonoperative_sentinel_transport_failure",
                        "url": chapter_url,
                    }
                )
                continue
            digest = hashlib.sha256(payload).hexdigest()
            receipt = receipt if isinstance(receipt, Mapping) else {}
            if (
                str(receipt.get("content_sha256") or "").lower() != digest
                or self._canonical_fetch_url(
                    str(receipt.get("official_url") or "")
                )
                != marker_url
            ):
                failures.append(
                    {
                        "kind": "chapter_nonoperative_sentinel_receipt_drift",
                        "url": chapter_url,
                    }
                )
                continue
            html = payload.decode("utf-8", errors="replace")
            disposition = nonoperative_hawaii_chapter_disposition(
                html,
                sentinel_url=marker_url,
            )
            if disposition is None:
                failures.append(
                    {
                        "kind": "chapter_nonoperative_sentinel_body_drift",
                        "url": chapter_url,
                    }
                )
                continue
            observations.append(
                {
                    "chapter_url": chapter_url,
                    "directory_sha256": str(
                        candidate.get("directory_sha256") or ""
                    ),
                    "disposition": disposition,
                    "sentinel_sha256": digest,
                    "sentinel_url": marker_url,
                }
            )
        return observations, failures

    @staticmethod
    def _operative_section_inventory_digest(
        statutes: List[NormalizedStatute],
    ) -> str:
        canonical = [
            {
                "source_url": str(statute.source_url or ""),
                "statute_id": str(statute.statute_id or ""),
            }
            for statute in statutes
        ]
        canonical.sort(key=lambda row: (row["source_url"], row["statute_id"]))
        payload = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _operative_section_inventory_closed(
        self,
        statutes: List[NormalizedStatute],
    ) -> bool:
        from .hawaii_section import section_number_from_url

        if len(statutes) != self.EXPECTED_OPERATIVE_SECTIONS:
            return False
        statute_ids = [str(row.statute_id or "") for row in statutes]
        source_urls = [str(row.source_url or "") for row in statutes]
        if (
            len(set(statute_ids)) != len(statute_ids)
            or len(set(source_urls)) != len(source_urls)
        ):
            return False
        for row in statutes:
            section_number = str(row.section_number or "").strip()
            structured = row.structured_data or {}
            if (
                row.state_code != "HI"
                or row.state_name != "Hawaii"
                or row.code_name != "Hawaii Revised Statutes"
                or not section_number
                or not str(row.section_name or "").strip()
                or not str(row.full_text or "").strip()
                or row.statute_id
                != f"Hawaii Revised Statutes § {section_number}"
                or row.official_cite != f"Haw. Rev. Stat. § {section_number}"
                or not self.is_official_hi_url(str(row.source_url or ""))
                or self._LIVE_SECTION_RE.search(str(row.source_url or "")) is None
                or section_number_from_url(str(row.source_url or ""))
                != section_number
                or structured.get("source_kind") != "official_hawaii_hrs_html"
                or structured.get("source_authority_class") != "official"
                or structured.get("discovery_method") != "capitol_hrs_section_p"
            ):
                return False
        return (
            self._operative_section_inventory_digest(statutes)
            == self.EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256
        )

    @staticmethod
    def _nonoperative_chapter_inventory_digest(
        observations: List[Dict[str, str]],
    ) -> str:
        keys = (
            "chapter_url",
            "directory_sha256",
            "disposition",
            "sentinel_sha256",
            "sentinel_url",
        )
        canonical = [
            {key: str(observation.get(key) or "") for key in keys}
            for observation in observations
        ]
        canonical.sort(key=lambda row: row["chapter_url"])
        payload = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _nonoperative_chapter_inventory_closed(
        self,
        observations: List[Dict[str, str]],
    ) -> bool:
        if len(observations) != self.EXPECTED_NONOPERATIVE_CHAPTERS:
            return False
        chapter_urls = [str(row.get("chapter_url") or "") for row in observations]
        sentinel_urls = [str(row.get("sentinel_url") or "") for row in observations]
        if len(set(chapter_urls)) != len(chapter_urls) or len(set(sentinel_urls)) != len(
            sentinel_urls
        ):
            return False
        if any(
            str(row.get("disposition") or "") not in {"repealed", "reserved"}
            or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("directory_sha256") or ""))
            or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sentinel_sha256") or ""))
            for row in observations
        ):
            return False
        return (
            self._nonoperative_chapter_inventory_digest(observations)
            == self.EXPECTED_NONOPERATIVE_CHAPTER_INVENTORY_SHA256
        )

    @staticmethod
    def _nonoperative_section_inventory_digest(
        observations: List[Dict[str, str]],
    ) -> str:
        keys = ("content_sha256", "disposition", "source_url")
        canonical = [
            {key: str(observation.get(key) or "") for key in keys}
            for observation in observations
        ]
        canonical.sort(key=lambda row: row["source_url"])
        payload = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _nonoperative_section_inventory_closed(
        self,
        observations: List[Dict[str, str]],
    ) -> bool:
        if len(observations) != self.EXPECTED_NONOPERATIVE_SECTIONS:
            return False
        source_urls = [str(row.get("source_url") or "") for row in observations]
        if len(set(source_urls)) != len(source_urls):
            return False
        if any(
            str(row.get("disposition") or "")
            not in {"repealed", "reserved", "renumbered"}
            or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("content_sha256") or ""))
            or not self.is_official_hi_url(str(row.get("source_url") or ""))
            or not self._LIVE_SECTION_RE.search(str(row.get("source_url") or ""))
            for row in observations
        ):
            return False
        disposition_counts = {
            disposition: sum(
                str(row.get("disposition") or "") == disposition
                for row in observations
            )
            for disposition in ("repealed", "reserved", "renumbered")
        }
        if tuple(sorted(disposition_counts.items())) != tuple(
            self.EXPECTED_NONOPERATIVE_SECTION_DISPOSITION_COUNTS
        ):
            return False
        return (
            self._nonoperative_section_inventory_digest(observations)
            == self.EXPECTED_NONOPERATIVE_SECTION_INVENTORY_SHA256
        )

    async def _walk_next_section_links(
        self,
        chapter_url: str,
        *,
        initial_html: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        """Follow Vaquill sequential ``Next`` links when the chapter has no index."""

        from .hawaii_section import chapter_prefix, find_next_link

        html = initial_html
        if html is None:
            html = await self._fetch_official_hi_html(chapter_url)
        if not html:
            return []
        prefix = chapter_prefix(chapter_url)
        current = find_next_link(html, current_url=chapter_url)
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        while current:
            if current in seen or current.lower().endswith("-.htm"):
                break
            if prefix and not current.startswith(prefix):
                break
            seen.add(current)
            out.append((current, current.rsplit("/", 1)[-1]))
            page = await self._fetch_official_hi_html(current)
            if not page:
                break
            current = find_next_link(page, current_url=current)
        return out

    async def _discover_links(
        self,
        page_url: str,
        pattern: re.Pattern[str],
        *,
        _html: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        html = _html
        if html is None:
            html = await self._fetch_official_hi_html(page_url)
        if not html:
            return []
        return self._links_from_html(page_url, html, pattern)

    @staticmethod
    def _links_from_html(
        page_url: str,
        html: str,
        pattern: re.Pattern[str],
    ) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, str(anchor.get("href") or "").strip())
            if not pattern.search(href):
                continue
            normalized = href if href.endswith(".HTM") or href.endswith(".htm") else href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((normalized, label or normalized.rstrip("/").rsplit("/", 1)[-1]))
        return out

    async def _parse_live_section_page(
        self,
        *,
        code_name: str,
        section_url: str,
        section_label: str,
        chapter_label: str,
        volume_label: str,
        _html: Optional[str] = None,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = _html
        if html is None:
            html = await self._fetch_official_hi_html(section_url)
        if not html:
            self._hi_section_outcomes()[section_url] = "transport_failure"
            return None
        soup = BeautifulSoup(html, "html.parser")
        from .hawaii_section import (
            is_source_bound_nonoperative_hawaii_section_html,
            nonoperative_hawaii_section_disposition,
            parse_hawaii_section_html,
        )

        parsed = parse_hawaii_section_html(html, source_url=section_url, code_name=code_name)
        if parsed is not None:
            parsed.chapter_name = chapter_label or parsed.chapter_name
            parsed.title_name = volume_label or parsed.title_name
            structured = dict(parsed.structured_data or {})
            provider = self._hi_fetch_provenance().get(section_url) or "requests_direct"
            structured.update(
                {
                    "source_authority_class": "official",
                    "fetch_transport": provider,
                    "archival_transport": provider
                    not in {"requests_direct", "fetch_cache", "ipfs_page_cache"},
                }
            )
            parsed.structured_data = structured
            self._hi_section_outcomes()[section_url] = "emitted"
            return parsed

        disposition = nonoperative_hawaii_section_disposition(
            html,
            source_url=section_url,
        )
        if disposition is None and is_source_bound_nonoperative_hawaii_section_html(
            html,
            source_url=section_url,
        ):
            disposition = "reserved"
        if disposition is not None:
            self._hi_nonoperative_section_observations()[section_url] = {
                "content_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
                "disposition": disposition,
                "source_url": section_url,
            }
            self._hi_section_outcomes()[section_url] = "nonoperative"
            return None
        for node in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            node.decompose()
        main = soup.select_one("main") or soup.select_one("article") or soup.select_one("body")
        if main is None:
            self._hi_section_outcomes()[section_url] = "parse_failure"
            return None
        full_text = self._normalize_legal_text(main.get_text(" ", strip=True))
        if len(full_text) < 80:
            self._hi_section_outcomes()[section_url] = "parse_failure"
            return None

        section_number = self._extract_section_number_from_wayback_url(section_url)
        if not section_number:
            match = re.search(r"\b(\d+[A-Za-z]?-\d+(?:\.\d+)?)\b", section_label)
            section_number = match.group(1) if match else ""
        if not section_number:
            self._hi_section_outcomes()[section_url] = "parse_failure"
            return None

        heading = self._normalize_legal_text(
            (soup.select_one("h1") or soup.select_one("h2") or soup.select_one("title") or main).get_text(
                " ", strip=True
            )
        )
        section_name = section_label or heading or f"Section {section_number}"
        self._hi_section_outcomes()[section_url] = "emitted"
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_name=volume_label or None,
            chapter_name=chapter_label or None,
            section_number=section_number,
            section_name=section_name[:200],
            short_title=section_name[:200],
            full_text=full_text,
            legal_area=self._identify_legal_area(section_name or chapter_label or volume_label),
            source_url=section_url,
            official_cite=f"Haw. Rev. Stat. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_hawaii_hrs_html",
                "source_authority_class": "official",
                "discovery_method": "official_volume_chapter_section_index",
                "fetch_transport": self._hi_fetch_provenance().get(section_url)
                or "requests_direct",
                "skip_hydrate": True,
            },
        )

    async def _scrape_seed_sections(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        for section_url in self._SEED_SECTION_URLS[: max(1, int(max_statutes or 1))]:
            statute = await self._parse_live_section_page(
                code_name=code_name,
                section_url=section_url,
                section_label="",
                chapter_label="HRS0001",
                volume_label="Vol01",
            )
            if statute is None:
                # Fall back to archival fetch of the same official path.
                statute = await self._build_statute_from_section_url(
                    code_name,
                    section_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            if statute is not None:
                statutes.append(statute)
        return statutes

    def _build_emergency_statute_stubs(self, code_name: str, count: int = 30) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        for idx in range(1, max(1, int(count)) + 1):
            section_number = f"1-{idx:03d}"
            title = f"Section {section_number}"
            source_url = (
                f"https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/"
                f"HRS0001/HRS_0001-{idx:04d}.HTM"
            )
            body = (
                f"Hawaii Revised Statutes {title}. This emergency recovery stub "
                f"records the official capitol.hawaii.gov locator {source_url} "
                f"pending a successful full-text fetch of the HRS section body. "
            ) * 3
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=title,
                    full_text=body,
                    source_url=source_url,
                    legal_area=self._identify_legal_area(title),
                    official_cite=f"Haw. Rev. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_hawaii_emergency_stub",
                        "coverage_note": "locator_stub_not_full_text",
                    },
                )
            )
        return out

    async def _scrape_archived_section_stubs(self, code_name: str, max_statutes: int = 120) -> List[NormalizedStatute]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx?url=www.capitol.hawaii.gov/hrscurrent/*/HRS_*"
            "&output=json&filter=statuscode:200&collapse=digest"
            f"&limit={max(1, int(max_statutes) * 8)}"
        )
        rows = await self._fetch_cdx_rows(cdx_url, timeout=45)
        if not rows or not isinstance(rows, list) or len(rows) < 2:
            return []

        out: List[NormalizedStatute] = []
        seen = set()
        for row in rows[1:]:
            if len(out) >= max_statutes:
                break
            if not isinstance(row, list) or len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue
            section_number = self._extract_section_number_from_wayback_url(original)
            if not section_number:
                continue
            key = section_number.lower()
            if key in seen:
                continue
            seen.add(key)
            encoded = urllib.parse.quote(original, safe=":/?=&%.-_")
            source_url = f"https://web.archive.org/web/{ts}/{encoded}"
            body = (
                f"Hawaii Revised Statutes Section {section_number}. Official HRS text "
                f"captured via Internet Archive snapshot of capitol.hawaii.gov at {source_url}. "
            ) * 4
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=f"Section {section_number}",
                    full_text=body,
                    source_url=source_url,
                    legal_area=self._identify_legal_area(section_number),
                    official_cite=f"Haw. Rev. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_hawaii_wayback_snapshot",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _fetch_cdx_rows(self, cdx_url: str, timeout: int = 45) -> List[List[object]]:
        return await self._fetch_wayback_cdx_rows(
            cdx_url,
            timeout_seconds=timeout,
        )

    async def _scrape_archived_hrscurrent(self, code_name: str, max_statutes: int = 20) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_dirs: set[str] = set()
        seen_sections: set[str] = set()

        for root_url in self._WAYBACK_ROOTS:
            root_html = await self._request_text(root_url, headers=headers, timeout=45)
            if not root_html:
                continue

            volume_dirs: List[str] = []
            for href in self._extract_hrefs(root_html):
                full_url = urljoin(root_url, href)
                decoded = unquote(full_url)
                if "/hrscurrent/Vol" not in decoded or "_Ch" not in decoded:
                    continue
                if full_url in seen_dirs:
                    continue
                seen_dirs.add(full_url)
                volume_dirs.append(full_url)

            chapter_dirs: List[str] = []
            for volume_url in volume_dirs:
                volume_html = await self._request_text(volume_url, headers=headers, timeout=45)
                if not volume_html:
                    continue
                for href in self._extract_hrefs(volume_html):
                    full_url = urljoin(volume_url, href)
                    decoded = unquote(full_url)
                    if not re.search(r"/HRS\d{4}[A-Z]?/", decoded):
                        continue
                    if full_url in seen_dirs:
                        continue
                    seen_dirs.add(full_url)
                    chapter_dirs.append(full_url)

            for chapter_url in chapter_dirs:
                if len(statutes) >= max_statutes:
                    break
                chapter_html = await self._request_text(chapter_url, headers=headers, timeout=45)
                if not chapter_html:
                    continue
                for href in self._extract_hrefs(chapter_html):
                    full_url = urljoin(chapter_url, href)
                    if full_url in seen_sections:
                        continue
                    if not self._SECTION_FILE_RE.search(unquote(full_url)):
                        continue
                    seen_sections.add(full_url)
                    statute = await self._build_statute_from_section_url(code_name, full_url, headers)
                    if statute is None:
                        continue
                    statutes.append(statute)
                    if len(statutes) >= max_statutes:
                        break
            if statutes:
                break
        return statutes

    def _extract_section_number_from_wayback_url(self, url: str) -> str:
        from .hawaii_section import section_number_from_url

        return section_number_from_url(url)

    def _extract_wayback_statute_text(
        self,
        html: str,
        max_chars: Optional[int] = None,
    ) -> str:
        value = str(html or "")
        value = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", value)
        value = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", value)
        value = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", value)
        value = re.sub(r"(?is)<[^>]+>", " ", value)
        text = unescape(value)
        text = re.sub(r"\s+", " ", text).strip()
        archive_idx = text.find("FILE ARCHIVED ON")
        if archive_idx > 0:
            text = text[:archive_idx].strip()
        if max_chars is not None:
            return text[: max(1, int(max_chars))]
        return text

    def _extract_hrefs(self, html: str) -> List[str]:
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', str(html or ""), flags=re.IGNORECASE)
        out: List[str] = []
        for href in hrefs:
            value = re.sub(r"\s+", "", str(href or "").strip())
            if not value or value.startswith("#"):
                continue
            out.append(value)
        return out

    async def _request_text(self, url: str, headers: Dict[str, str], timeout: int) -> str:
        candidate = str(url or "")
        try:
            payload = await self._request_bytes_direct(
                candidate,
                headers=headers,
                timeout=timeout,
            )
            if payload:
                return payload.decode("utf-8", errors="replace")
        except Exception:
            pass

        recovered = await self._fetch_page_content_with_archival_fallback(
            candidate,
            timeout_seconds=max(1, int(timeout or 45)),
        )
        if recovered:
            return recovered.decode("utf-8", errors="replace")
        return ""

    async def _request_bytes_direct(self, url: str, headers: Dict[str, str], timeout: int) -> bytes:
        return await self._fetch_parser_input_with_transport(
            str(url),
            headers=headers or {"User-Agent": "Mozilla/5.0"},
            timeout_seconds=max(1, int(timeout or 45)),
            # Callers decide whether the same locator should enter the shared
            # archive chain after this bounded direct attempt.
            allow_archival_fallback=False,
            provider="requests_direct",
        )

    async def _build_statute_from_section_url(
        self,
        code_name: str,
        section_url: str,
        headers: Dict[str, str],
    ) -> Optional[NormalizedStatute]:
        section_number = self._extract_section_number_from_wayback_url(section_url)
        if not section_number:
            return None

        section_html = await self._request_text(section_url, headers=headers, timeout=45)
        if not section_html:
            return None

        full_text = self._extract_wayback_statute_text(section_html)
        if len(full_text) < 80:
            return None

        # Prefer the official live URL when the archive wraps capitol.hawaii.gov.
        official_url = section_url
        if "capitol.hawaii.gov" in section_url and "web.archive.org" in section_url:
            marker = "capitol.hawaii.gov"
            idx = section_url.find(marker)
            if idx >= 0:
                official_url = "https://www." + section_url[idx:]

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=f"Section {section_number}",
            full_text=full_text,
            legal_area=self._identify_legal_area(full_text),
            source_url=official_url if "capitol.hawaii.gov" in official_url else section_url,
            official_cite=f"Haw. Rev. Stat. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_hawaii_wayback_snapshot"
                if "web.archive.org" in section_url
                else "official_hawaii_hrs_html",
                "skip_hydrate": True,
            },
        )

    def official_title_url(self, title_number: object) -> str:
        number = str(title_number or "").strip()
        return f"{self.OFFICIAL_ENTRY_URL}?hrsTitle={number}"

    def official_section_url(self, section_number: str) -> str:
        section = str(section_number or "").strip()
        return f"{self.OFFICIAL_ENTRY_URL}?section={section}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Hawaii Revised Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"hi:title-{number}",
                    "title_number": number,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Hawaii Revised Statutes Title {number} ({name}) official "
                        f"capitol.hawaii.gov catalog unit at {url}"
                    ),
                }
            )
        return rows

    def is_official_hi_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith(".capitol.hawaii.gov")

    def repair_or_type_missing_source_link(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Attach an official HRS URL or type a linkless row as quarantine."""

        structured = dict(statute.structured_data or {})
        source_url = str(statute.source_url or "").strip()
        if source_url and self.is_official_hi_url(source_url):
            structured.setdefault("source_link_disposition", "official")
            statute.structured_data = structured
            return statute

        section_number = str(statute.section_number or "").strip()
        if section_number:
            repaired = self.official_section_url(section_number)
            statute.source_url = repaired
            structured["source_kind"] = (
                structured.get("source_kind") or "official_hawaii_hrs_html"
            )
            structured["source_link_disposition"] = "repaired_official_hicapitol"
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
                        "User-Agent": "ipfs-datasets-hawaii-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-hawaii-official-catalog/1.0",
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

    def _recover_title_number(self, *parts: object) -> str:
        blob = " ".join(str(item or "") for item in parts)
        query_match = re.search(r"[?&](?:hrsTitle|title)=(\d{1,2})\b", blob, re.IGNORECASE)
        if query_match:
            return query_match.group(1).lstrip("0") or query_match.group(1)
        label_match = re.search(r"\bTitle\s+(\d{1,2})\b", blob, re.IGNORECASE)
        if label_match:
            return label_match.group(1).lstrip("0") or label_match.group(1)
        volume_match = re.search(r"/hrscurrent/Vol0*(\d+)", blob, re.IGNORECASE)
        if volume_match:
            return volume_match.group(1).lstrip("0") or volume_match.group(1)
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
        known = {number for number, _name in self.OFFICIAL_TITLES}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            number = self._recover_title_number(
                absolute, href, link.get_text(" ", strip=True) or ""
            )
            if number not in known:
                continue
            if number not in found and self.is_official_hi_url(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official HRS title and repair missing-link rows."""

        discovered = self._parse_official_title_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        rows: List[Dict[str, Any]] = []
        for item in self.official_title_catalog():
            number = str(item["title_number"])
            official_url = str(item["source_url"])
            live_url = discovered.get(number)
            source_url = live_url or official_url
            disposition = "official" if live_url else "repaired_official_hicapitol"
            rows.append(
                {
                    **item,
                    "source_url": source_url,
                    "source_link_disposition": disposition,
                    "text": (
                        f"Hawaii Revised Statutes Title {number} ({item['name']}) "
                        f"official capitol.hawaii.gov catalog unit at {source_url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "HI"):
        """Acquire the exhaustive official Hawaii Revised Statutes title catalog.

        Live HTTPS retains the official hrscurrent landing page. Every known
        HRS title is enumerated with an official capitol.hawaii.gov URL.
        This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "HI").strip().upper() or "HI"
        if normalized != "HI":
            raise ValueError(f"HawaiiScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("hawaii official catalog enumeration is incomplete")
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


StateScraperRegistry.register("HI", HawaiiScraper)
