"""Scraper for Louisiana state laws.

This module contains the scraper for Louisiana statutes from the official state legislative website.
"""

import re
import hashlib
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ipfs_datasets_py.utils import anyio_compat as asyncio
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class LouisianaScraper(BaseStateScraper):
    """Scraper for Louisiana state laws from http://www.legis.la.gov"""

    _TOC_TITLE_POSTBACK_RE = re.compile(
        r"^\s*javascript:\s*__doPostBack\(\s*'"
        r"(?P<target>[^']*ListViewTOC1\$ctrl\d+\$LinkButton1a)'"
        r"\s*,\s*''\s*\)\s*;?\s*$",
        re.IGNORECASE,
    )
    _LAW_LINK_RE = re.compile(r"Law\.aspx\?d=\d+", re.IGNORECASE)

    last_official_quarantines: List[Dict[str, str]] = []

    _ARCHIVE_LAW_URLS = [
        "http://web.archive.org/web/20240407200045/https://legis.la.gov/Legis/law.aspx?d=100114",
        "http://web.archive.org/web/20250523231945/https://legis.la.gov/Legis/Law.aspx?d=100115",
        "http://web.archive.org/web/20250501013708/https://legis.la.gov/Legis/Law.aspx?d=100117",
        "http://web.archive.org/web/20230825044518/http://legis.la.gov/legis/Law.aspx?d=100122",
        "http://web.archive.org/web/20250501064333/https://legis.la.gov/Legis/Law.aspx?d=100124",
        "http://web.archive.org/web/20240809002954/https://legis.la.gov/Legis/Law.aspx?d=100148",
    ]

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            louisiana_law,
            state_archival_fetch,
            strict_frontier_closure,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            louisiana_law,
            wayback_machine_engine,
        )

    def get_base_url(self) -> str:
        """Return the base URL for Louisiana's legislative website."""
        return "https://legis.la.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Louisiana."""
        return [
            {
                "name": "Louisiana Revised Statutes",
                "url": f"{self.get_base_url()}/legis/Laws.aspx",
                "type": "Code",
            }
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Louisiana's legislative website.

        Louisiana live endpoints can be brittle in automation contexts.
        Prefer official Law.aspx pages; full-corpus mode must not clamp or
        sole-admit archival/Justia mirrors.
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .louisiana_constitution import (
            configured_constitution_text_path,
            parse_louisiana_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_louisiana_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Louisiana Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .louisiana_law import parse_configured_louisiana_law

        local_rows = parse_configured_louisiana_law(
            code_name=code_name or "Louisiana Revised Statutes",
            max_statutes=limit,
        )
        if local_rows:
            return local_rows if limit is None else local_rows[: int(limit)]
        skip_live_toc = str(
            os.getenv("STATE_SCRAPER_LA_SKIP_LIVE_TOC", "0") or "0"
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        toc: List[NormalizedStatute] = []
        if skip_live_toc:
            self.logger.info(
                "Louisiana live TOC discovery skipped (STATE_SCRAPER_LA_SKIP_LIVE_TOC enabled)"
            )
        else:
            toc = await self._scrape_live_toc_pages(
                code_name=code_name, max_statutes=limit
            )
        if toc:
            return toc if limit is None else toc[: int(limit)]

        live: List[NormalizedStatute] = []
        if not self._full_corpus_enabled() or max_statutes is not None:
            live = await self._scrape_live_law_pages(
                code_name=code_name, max_statutes=limit
            )
        if live and (
            not self._full_corpus_enabled() or max_statutes is not None
        ):
            return live if limit is None else live[: int(limit)]

        # Full-corpus runs must not sole-admit Wayback/Justia/generic sources.
        if self._full_corpus_enabled() and max_statutes is None:
            return []

        fallback_cap = int(limit) if limit is not None else 160
        archival = await self._scrape_archived_law_pages(
            code_name=code_name, max_statutes=max(10, fallback_cap)
        )
        if archival and (
            not self._full_corpus_enabled() or max_statutes is not None
        ):
            self.logger.info(f"Louisiana archival fallback: Scraped {len(archival)} sections")
            return archival if limit is None else archival[: int(limit)]

        playwright = await self._playwright_scrape(
            code_name,
            code_url,
            "La. Rev. Stat.",
            wait_for_selector="a[href*='RS'], .law-link",
            timeout=45000,
            max_sections=max(10, fallback_cap),
        )
        if playwright:
            return playwright if limit is None else playwright[: int(limit)]
        return []

    async def _scrape_live_toc_pages(
        self, code_name: str, max_statutes: Optional[int] = None
    ) -> List[NormalizedStatute]:
        title_pages = await self._discover_live_toc_title_pages(limit=max_statutes)
        if not title_pages:
            return []
        return await self._scrape_law_page_urls(
            code_name=code_name,
            law_urls=title_pages,
            max_statutes=max_statutes,
            source_kind="official_louisiana_toc_law_page",
            discovery_method="live_toc_postback",
        )

    async def _scrape_live_law_pages(
        self, code_name: str, max_statutes: Optional[int] = None
    ) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        live_urls = [
            "https://legis.la.gov/Legis/Law.aspx?d=100114",
            "https://legis.la.gov/Legis/Law.aspx?d=100115",
        ]
        if max_statutes is not None:
            live_urls = live_urls[: max(1, int(max_statutes))]
        for live_url in live_urls:
            law_html = await self._request_text(
                law_url=live_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12
            )
            if not law_html:
                continue
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            from .louisiana_law import statute_from_law_html

            parsed = statute_from_law_html(law_html, source_url=live_url, code_name=code_name)
            if parsed is not None:
                statutes.append(parsed)
                continue
            section_number = self._extract_section_number(law_html)
            body_html = self._extract_law_body_html(law_html)
            full_text = self._clean_html_text(body_html)
            if not section_number or len(full_text) < 280:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=f"RS {section_number}",
                    full_text=full_text,
                    legal_area=self._identify_legal_area(full_text),
                    source_url=live_url,
                    official_cite=f"La. Rev. Stat. {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_live_law_page",
                        "discovery_method": "official_live_law_seed",
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    async def _scrape_archived_law_pages(
        self, code_name: str, max_statutes: Optional[int] = None
    ) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_sections = set()

        candidate_urls = list(self._ARCHIVE_LAW_URLS)
        discovered = await self._discover_archived_law_urls(
            limit=2000 if self._full_corpus_enabled() else 160
        )
        for url in discovered:
            if url not in candidate_urls:
                candidate_urls.append(url)

        heartbeat_every_raw = str(
            os.getenv("STATE_SCRAPER_LA_ARCHIVE_SCAN_HEARTBEAT_EVERY", "") or ""
        ).strip()
        try:
            heartbeat_every = int(heartbeat_every_raw) if heartbeat_every_raw else 50
        except Exception:
            heartbeat_every = 50
        heartbeat_every = max(10, min(2000, heartbeat_every))
        discovered_total = len(candidate_urls)

        for law_index, law_url in enumerate(candidate_urls, start=1):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            if law_index == 1 or law_index % heartbeat_every == 0:
                self.logger.info(
                    "Louisiana archival crawl: scanned_laws=%s/%s statutes_so_far=%s",
                    law_index,
                    discovered_total,
                    len(statutes),
                )
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="louisiana:archival-law-scan",
                    extra={
                        "scanned_laws": int(law_index),
                        "discovered_laws": int(discovered_total),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )

            law_html = await self._request_text(law_url=law_url, headers=headers, timeout=45)
            if not law_html:
                continue

            section_number = self._extract_section_number(law_html)
            if not section_number or section_number in seen_sections:
                continue

            body_html = self._extract_law_body_html(law_html)
            if not body_html:
                continue

            full_text = self._clean_html_text(body_html)
            if len(full_text) < 280:
                continue

            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § {section_number}",
                code_name=code_name,
                section_number=section_number,
                section_name=f"RS {section_number}",
                full_text=full_text,
                legal_area=self._identify_legal_area(full_text),
                source_url=law_url,
                official_cite=f"La. Rev. Stat. {section_number}",
            )
            statutes.append(statute)
            seen_sections.add(section_number)
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="louisiana:archival-complete",
            force=True,
            extra={
                "scanned_laws": int(discovered_total),
                "discovered_laws": int(discovered_total),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return statutes

    def _fail_louisiana_full_frontier(
        self,
        message: str,
        **evidence: Any,
    ) -> None:
        frontier = dict(
            getattr(self, "_last_louisiana_full_frontier", {}) or {}
        )
        frontier["closed"] = False
        frontier.update(evidence)
        errors = list(frontier.get("errors") or [])
        errors.append(str(message))
        frontier["errors"] = errors
        self._last_louisiana_full_frontier = frontier
        self._last_full_corpus_frontier = frontier
        details = " ".join(
            f"{key}={value}" for key, value in sorted(evidence.items())
        )
        raise RuntimeError(f"{message}{': ' + details if details else ''}")

    def _canonical_louisiana_law_receipt(
        self,
        *,
        law_url: str,
        payload: bytes,
        receipt: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Verify and minimize one aligned law-page byte receipt."""

        from ...legal_data.state_laws_source_provenance import (
            StateLawTransportReceiptError,
            canonicalize_state_law_transport_receipt,
        )

        digest = hashlib.sha256(payload).hexdigest()
        if not isinstance(receipt, Mapping):
            raise RuntimeError("aligned transport receipt is missing")
        try:
            return canonicalize_state_law_transport_receipt(
                receipt,
                official_url=law_url,
                content_sha256=digest,
            )
        except StateLawTransportReceiptError as exc:
            raise RuntimeError(
                f"aligned transport receipt was rejected: {exc.code}"
            ) from exc

    def _retained_louisiana_toc_reports(
        self,
    ) -> tuple[List[Dict[str, Any]], List[str]]:
        """Reconstruct the complete ASP.NET TOC solely from retained inputs."""

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from .strict_frontier_closure import replay_exact_retained_state_input

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Louisiana TOC replay requires an attached ledger")
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()
        toc_url = self._canonical_fetch_url(
            f"{self.get_base_url()}/legis/Laws_Toc.aspx?folder=75&level=Parent"
        )
        candidates: List[tuple[int, Mapping[str, Any], Any]] = []
        for retained in ledger.entries:
            receipt = retained.receipt
            if self._canonical_fetch_url(str(receipt.endpoint or "")) != toc_url:
                continue
            request = dict(receipt.sanitized_request or {})
            method = str(request.get("method") or "").upper()
            pagination = dict(receipt.pagination or {})
            if method == "GET" and pagination.get("step") == "root":
                order = 0
            elif method == "POST" and pagination.get("kind") == "aspnet_postback":
                order = int(pagination.get("page_index") or 0)
                if order <= 0:
                    raise RuntimeError(
                        "Louisiana retained TOC postback lacks a positive page index"
                    )
            else:
                continue
            candidates.append((order, request, receipt))
        candidates.sort(key=lambda row: row[0])
        if not candidates or candidates[0][0] != 0:
            raise RuntimeError("Louisiana retained TOC root input is missing")
        page_orders = [order for order, _request, _receipt in candidates]
        if page_orders != list(range(len(candidates))):
            raise RuntimeError("Louisiana retained TOC pagination is ambiguous")

        reports: List[Dict[str, Any]] = []
        law_urls: List[str] = []
        seen_laws: set[str] = set()
        expected_postbacks = 0
        declared_page_counts: set[int] = set()
        for order, request, receipt in candidates:
            body = replay_exact_retained_state_input(
                self,
                official_url=toc_url,
                sanitized_request=request,
                frontier_name=f"Louisiana TOC page {order}",
                refresh=False,
            )
            html = body.decode("utf-8", errors="replace")
            if order == 0:
                expected_postbacks = len(self._title_postback_targets(html))
            pagination = dict(receipt.pagination or {})
            if order > 0:
                declared_page_count = int(pagination.get("page_count") or 0)
                if declared_page_count <= 0:
                    raise RuntimeError(
                        "Louisiana retained TOC postback lacks a positive page count"
                    )
                declared_page_counts.add(declared_page_count)
            page_members: List[str] = []
            try:
                from bs4 import BeautifulSoup
            except ImportError as exc:
                raise RuntimeError(
                    "BeautifulSoup is required for Louisiana retained TOC replay"
                ) from exc
            page = BeautifulSoup(html, "html.parser")
            for anchor in page.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                if not self._LAW_LINK_RE.search(href):
                    continue
                source_url = self._canonical_fetch_url(
                    urllib.parse.urljoin(toc_url, href)
                )
                if not source_url:
                    continue
                if source_url in seen_laws:
                    # The official title views render the same Law.aspx anchor
                    # in two parallel presentation blocks.  Live discovery
                    # admits the first source-order occurrence only; retained
                    # replay must reproduce that exact source-derived union.
                    continue
                seen_laws.add(source_url)
                page_members.append(source_url)
                law_urls.append(source_url)
            reports.append(
                {
                    "content_sha256": hashlib.sha256(body).hexdigest(),
                    "law_member_count": len(page_members),
                    "law_members_sha256": hashlib.sha256(
                        canonical_json_bytes(page_members)
                    ).hexdigest(),
                    "method": str(request.get("method") or "").upper(),
                    "page_index": order,
                    "request_sha256": hashlib.sha256(
                        canonical_json_bytes(request)
                    ).hexdigest(),
                }
            )
        postback_count = len(candidates) - 1
        if (
            expected_postbacks <= 0
            or postback_count != expected_postbacks
            or declared_page_counts != {expected_postbacks}
            or not law_urls
        ):
            raise RuntimeError(
                "Louisiana retained TOC hierarchy is incomplete: "
                f"root_targets={expected_postbacks} retained_posts={postback_count} "
                f"declared_posts={sorted(declared_page_counts)} laws={len(law_urls)}"
            )
        return reports, law_urls

    def _louisiana_exact_frontier(
        self,
        *,
        toc_reports: Sequence[Mapping[str, Any]],
        leaf_reports: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Build the deterministic root/hierarchy/leaf disposition algebra."""

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        leaves = [dict(row) for row in leaf_reports]
        toc = [dict(row) for row in toc_reports]
        operative = sum(row.get("disposition") == "operative" for row in leaves)
        excluded = len(leaves) - operative
        disposition = {
            "discovered": len(leaves),
            "duplicates": 0,
            "excluded": excluded,
            "failed_final": 0,
            "fetched": operative,
            "quarantined": 0,
        }
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": False,
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "leaf_input_count": len(leaves),
            "leaf_inputs_sha256": hashlib.sha256(
                canonical_json_bytes(leaves)
            ).hexdigest(),
            "method": "source_derived_aspnet_toc_and_law_pages",
            "pagination_closed": bool(toc),
            "remaining_bundle_members": [],
            "scope_closed": True,
            "source_membership_sha256": hashlib.sha256(
                canonical_json_bytes(
                    [str(row.get("source_url") or "") for row in leaves]
                )
            ).hexdigest(),
            "toc_exhausted": bool(toc),
            "toc_input_count": len(toc),
            "toc_inputs_sha256": hashlib.sha256(
                canonical_json_bytes(toc)
            ).hexdigest(),
            "unvisited_continuation_links": [],
            "visited_index_units": len(leaves),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    async def _fetch_louisiana_law_frontier(
        self,
        law_urls: Sequence[str],
        *,
        max_concurrency: int,
    ):
        """Acquire the complete ordered Law.aspx frontier as one plural wave.

        The ASP.NET TOC emits law locators in parent-page/source order.  Exact
        production preserves that cross-parent union in a single archive-aware
        request so Wayback prefix inventory and Common Crawl WARC grouping are
        shared across the whole Louisiana frontier.  Only unresolved rows are
        eligible for bounded retries; those retries do not repeat archive
        inventory discovery.
        """

        requested = list(law_urls)
        canonical = [self._canonical_fetch_url(url) for url in requested]
        if not requested or any(not url for url in canonical):
            raise RuntimeError(
                "Louisiana law-page frontier contains an empty or invalid exact URL"
            )
        if len(set(canonical)) != len(canonical):
            raise RuntimeError(
                "Louisiana law-page frontier contains duplicate exact URLs"
            )

        residual_retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_LA_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=self._env_int(
                        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                        default=1,
                    ),
                ),
            ),
        )
        result = (
            await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
                requested,
                residual_retry_attempts=residual_retry_attempts,
                repeat_grouped_archive_inventory_on_residual=False,
                timeout_seconds=45,
                media_type="text/html",
                max_concurrency=max(1, min(32, int(max_concurrency or 1))),
                prefer_direct=True,
                common_crawl_domain_terms=("legis.la.gov",),
                common_crawl_url_terms=("/legis/Law.aspx",),
                common_crawl_mime_terms=("html",),
                wayback_prefix_inventory=True,
            )
        )
        aligned_lengths = {
            len(result.urls),
            len(result.payloads),
            len(result.errors),
            len(result.transport_receipts),
            len(result.parser_input_envelopes),
        }
        if aligned_lengths != {len(requested)}:
            raise RuntimeError(
                "Louisiana law-page frontier returned unaligned acquisition rows"
            )
        result_canonical = [
            self._canonical_fetch_url(url) for url in result.urls
        ]
        if result_canonical != canonical:
            raise RuntimeError(
                "Louisiana law-page frontier changed URL order or identity"
            )
        return result

    async def _scrape_law_page_urls(
        self,
        *,
        code_name: str,
        law_urls: List[str],
        max_statutes: Optional[int] = None,
        source_kind: str = "official_louisiana_toc_law_page",
        discovery_method: str = "live_toc_postback",
    ) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_sections = set()
        self.logger.info(
            "Louisiana law-page crawl: discovered_law_urls=%s max_statutes=%s source_kind=%s",
            len(law_urls),
            max_statutes,
            source_kind,
        )
        heartbeat_every_raw = str(
            os.getenv("STATE_SCRAPER_LA_SCAN_HEARTBEAT_EVERY", "") or ""
        ).strip()
        try:
            heartbeat_every = int(heartbeat_every_raw) if heartbeat_every_raw else 25
        except Exception:
            heartbeat_every = 25
        heartbeat_every = max(25, min(2000, heartbeat_every))
        discovered_total = len(law_urls)

        exact_full_frontier = self._full_corpus_enabled() and max_statutes is None
        strict_frontier: Optional[Dict[str, Any]] = None
        terminal_dispositions: List[Dict[str, Any]] = []
        leaf_reports: List[Dict[str, Any]] = []
        seen_legal_identities: Dict[str, str] = {}
        if exact_full_frontier:
            from .louisiana_law import (
                source_bound_terminal_disposition_from_law_html,
                statute_from_law_html,
                terminal_disposition_from_law_html,
            )

            strict_frontier = {
                "closed": False,
                "source_kind": source_kind,
                "discovery_method": discovery_method,
                "law_pages_discovered": discovered_total,
                "law_pages_requested": 0,
                "law_pages_fetched": 0,
                "law_pages_classified": 0,
                "statutes_emitted": 0,
                "terminal_pages_excluded": 0,
                "terminal_disposition_counts": {},
                "terminal_dispositions": terminal_dispositions,
                "leaf_reports": leaf_reports,
                "unresolved_law_pages": [],
                "errors": [],
            }
            self._last_louisiana_full_frontier = strict_frontier
            self._last_full_corpus_frontier = strict_frontier
            if discovered_total == 0:
                self._fail_louisiana_full_frontier(
                    "Louisiana strict law-page frontier is empty"
                )
            seen_urls: set[str] = set()
            duplicate_urls: List[str] = []
            invalid_urls: List[str] = []
            for law_url in law_urls:
                canonical_url = self._canonical_fetch_url(law_url)
                if not canonical_url or not self._LAW_LINK_RE.search(canonical_url):
                    invalid_urls.append(str(law_url or ""))
                    continue
                if canonical_url in seen_urls:
                    duplicate_urls.append(canonical_url)
                seen_urls.add(canonical_url)
            if invalid_urls or duplicate_urls:
                self._fail_louisiana_full_frontier(
                    "Louisiana strict law-page discovery did not enumerate a unique official frontier",
                    invalid_law_urls=invalid_urls,
                    duplicate_law_urls=duplicate_urls,
                )
        batch_size_raw = str(
            os.getenv("STATE_SCRAPER_LA_FRONTIER_BATCH_SIZE", "") or ""
        ).strip()
        concurrency_raw = str(
            os.getenv("STATE_SCRAPER_LA_FRONTIER_CONCURRENCY", "") or ""
        ).strip()
        try:
            frontier_batch_size = int(batch_size_raw) if batch_size_raw else 64
        except Exception:
            frontier_batch_size = 64
        try:
            frontier_concurrency = int(concurrency_raw) if concurrency_raw else 8
        except Exception:
            frontier_concurrency = 8
        frontier_batch_size = (
            max(2, min(512, frontier_batch_size)) if exact_full_frontier else 1
        )
        frontier_concurrency = max(1, min(32, frontier_concurrency))
        acquisition_stats = {
            "frontier_batches": 0,
            "frontier_pages": 0,
            "leaf_acquisition_wave_count": 0,
            "residual_retry_rounds_executed": 0,
            "residual_retry_requested_pages": 0,
            "direct_initial_successes": 0,
            "warc_range_fetch_calls": 0,
            "warc_naive_range_fetches": 0,
            "warc_range_fetches_avoided": 0,
        }
        self.logger.info(
            "Louisiana law-page acquisition: batch_size=%s max_concurrency=%s direct_first=%s",
            frontier_batch_size,
            frontier_concurrency,
            exact_full_frontier,
        )

        exact_payloads: List[bytes] = []
        exact_errors: List[Optional[str]] = []
        exact_receipts: List[Optional[Dict[str, Any]]] = []
        if exact_full_frontier:
            try:
                exact_result = await self._fetch_louisiana_law_frontier(
                    law_urls,
                    max_concurrency=frontier_concurrency,
                )
            except Exception as exc:
                self._fail_louisiana_full_frontier(
                    "Louisiana strict law-page acquisition wave failed",
                    failed_batch_start=0,
                    failed_batch_size=discovered_total,
                    batch_error=f"{type(exc).__name__}: {exc}",
                )
            exact_payloads = [bytes(payload or b"") for payload in exact_result.payloads]
            exact_errors = list(exact_result.errors or [])
            exact_receipts = list(exact_result.transport_receipts or [])
            assert strict_frontier is not None
            strict_frontier["law_pages_requested"] = discovered_total
            stats = dict(exact_result.stats or {})
            common_crawl = dict(stats.get("common_crawl") or {})
            acquisition_stats.update(
                {
                    "frontier_batches": 1,
                    "frontier_pages": discovered_total,
                    "leaf_acquisition_wave_count": 1,
                    "residual_retry_rounds_executed": int(
                        stats.get("residual_retry_rounds_executed") or 0
                    ),
                    "residual_retry_requested_pages": int(
                        stats.get("residual_retry_requested_pages") or 0
                    ),
                    "direct_initial_successes": int(
                        stats.get("direct_initial_successes") or 0
                    ),
                    "warc_range_fetch_calls": int(
                        common_crawl.get("range_fetch_calls") or 0
                    ),
                    "warc_naive_range_fetches": int(
                        common_crawl.get("naive_range_fetches") or 0
                    ),
                    "warc_range_fetches_avoided": int(
                        common_crawl.get("range_fetches_avoided") or 0
                    ),
                }
            )

        stop_requested = False
        for batch_start in range(0, discovered_total, frontier_batch_size):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            frontier_urls = law_urls[
                batch_start : batch_start + frontier_batch_size
            ]
            if exact_full_frontier:
                batch_stop = batch_start + len(frontier_urls)
                frontier_payloads = exact_payloads[batch_start:batch_stop]
                frontier_errors = exact_errors[batch_start:batch_stop]
                frontier_receipts = exact_receipts[batch_start:batch_stop]
                frontier_html = [
                    payload.decode("utf-8", errors="replace") if payload else ""
                    for payload in frontier_payloads
                ]
            else:
                frontier_payloads = []
                frontier_errors = []
                frontier_receipts = []
                frontier_html = [
                    await self._request_text(
                        law_url=url,
                        headers=headers,
                        timeout=45,
                    )
                    for url in frontier_urls
                ]

            for offset, (law_url, law_html) in enumerate(
                zip(frontier_urls, frontier_html),
                start=1,
            ):
                law_index = batch_start + offset
                if max_statutes is not None and len(statutes) >= int(max_statutes):
                    stop_requested = True
                    break

                if law_index == 1 or law_index % heartbeat_every == 0:
                    self.logger.info(
                        "Louisiana law-page crawl: scanned_laws=%s/%s statutes_so_far=%s",
                        law_index,
                        discovered_total,
                        len(statutes),
                    )
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="louisiana-law-page-scan",
                        extra={
                            "scanned_laws": int(law_index),
                            "discovered_laws": int(discovered_total),
                            "codes_completed": 0,
                            "codes_total": 1,
                            "source_kind": source_kind,
                            "discovery_method": discovery_method,
                            **(
                                {
                                    "law_pages_fetched": int(
                                        strict_frontier["law_pages_fetched"]
                                    ),
                                    "law_pages_classified": int(
                                        strict_frontier["law_pages_classified"]
                                    ),
                                    "terminal_pages_excluded": int(
                                        strict_frontier["terminal_pages_excluded"]
                                    ),
                                    "frontier_closed": False,
                                }
                                if strict_frontier is not None
                                else {}
                            ),
                            **acquisition_stats,
                        },
                    )

                if exact_full_frontier:
                    payload = bytes(frontier_payloads[offset - 1] or b"")
                    fetch_error = frontier_errors[offset - 1]
                    if fetch_error or not payload:
                        self._fail_louisiana_full_frontier(
                            "Louisiana strict law-page fetch left an official locator unresolved",
                            unresolved_law_pages=[
                                {
                                    "source_url": law_url,
                                    "error": str(fetch_error or "empty parser input"),
                                }
                            ],
                        )
                    try:
                        transport_receipt = self._canonical_louisiana_law_receipt(
                            law_url=law_url,
                            payload=payload,
                            receipt=frontier_receipts[offset - 1],
                        )
                    except RuntimeError as exc:
                        self._fail_louisiana_full_frontier(
                            "Louisiana strict law-page fetch lacked exact byte provenance",
                            unresolved_law_pages=[
                                {
                                    "source_url": law_url,
                                    "error": str(exc),
                                }
                            ],
                        )

                    assert strict_frontier is not None
                    strict_frontier["law_pages_fetched"] = int(
                        strict_frontier["law_pages_fetched"]
                    ) + 1
                    digest = hashlib.sha256(payload).hexdigest()
                    parsed = statute_from_law_html(
                        law_html,
                        source_url=law_url,
                        code_name=code_name,
                        content_sha256=digest,
                    )
                    if parsed is not None:
                        body_prefix = str(
                            (parsed.structured_data or {}).get("body_prefix") or ""
                        ).strip()
                        legal_identity = "|".join(
                            (
                                body_prefix,
                                str(parsed.title_number or "").strip(),
                                str(parsed.section_number or "").strip(),
                            )
                        )
                        first_source = seen_legal_identities.get(legal_identity)
                        if not legal_identity.strip("|") or first_source is not None:
                            self._fail_louisiana_full_frontier(
                                "Louisiana strict law-page parser emitted a duplicate or empty legal identity",
                                duplicate_legal_identity=legal_identity,
                                first_source_url=first_source,
                                second_source_url=law_url,
                            )
                        seen_legal_identities[legal_identity] = law_url
                        structured_data = dict(parsed.structured_data or {})
                        structured_data.update(
                            {
                                "source_kind": source_kind,
                                "discovery_method": discovery_method,
                                "content_sha256": digest,
                                "transport_receipt": transport_receipt,
                                "official_frontier_closed": False,
                                "skip_hydrate": True,
                            }
                        )
                        parsed.structured_data = structured_data
                        parsed.legal_area = self._identify_legal_area(parsed.full_text)
                        statutes.append(parsed)
                        leaf_reports.append(
                            {
                                "canonical_identity": legal_identity,
                                "content_sha256": digest,
                                "disposition": "operative",
                                "source_url": law_url,
                            }
                        )
                        strict_frontier["statutes_emitted"] = len(statutes)
                        strict_frontier["law_pages_classified"] = int(
                            strict_frontier["law_pages_classified"]
                        ) + 1
                    else:
                        # Preserve the most specific retained-evidence
                        # disposition when an exact URL/body contract exists;
                        # use the grammar classifier for the remaining
                        # official pages in the same terminal family.
                        disposition = source_bound_terminal_disposition_from_law_html(
                            law_html,
                            source_url=law_url,
                            content_sha256=digest,
                        )
                        if not disposition:
                            disposition = terminal_disposition_from_law_html(law_html)
                        if not disposition:
                            unresolved = {
                                "source_url": law_url,
                                "content_sha256": digest,
                                "label": self._extract_section_number(law_html),
                                "error": "untyped parser miss",
                            }
                            strict_frontier["unresolved_law_pages"] = [unresolved]
                            self._fail_louisiana_full_frontier(
                                "Louisiana strict law-page parser left an official locator untyped",
                                unresolved_law_pages=[unresolved],
                            )
                        terminal_entry = {
                            "source_url": law_url,
                            "content_sha256": digest,
                            "disposition": disposition,
                            "transport_receipt": transport_receipt,
                        }
                        terminal_dispositions.append(terminal_entry)
                        leaf_reports.append(
                            {
                                "canonical_identity": "",
                                "content_sha256": digest,
                                "disposition": disposition,
                                "source_url": law_url,
                            }
                        )
                        counts = dict(
                            strict_frontier.get("terminal_disposition_counts") or {}
                        )
                        counts[disposition] = int(counts.get(disposition) or 0) + 1
                        strict_frontier["terminal_disposition_counts"] = counts
                        strict_frontier["terminal_pages_excluded"] = len(
                            terminal_dispositions
                        )
                        strict_frontier["law_pages_classified"] = int(
                            strict_frontier["law_pages_classified"]
                        ) + 1
                    continue

                if not law_html:
                    continue

                section_number = self._extract_section_number(law_html)
                if not section_number or section_number in seen_sections:
                    continue

                body_html = self._extract_law_body_html(law_html)
                if not body_html:
                    continue

                full_text = self._clean_html_text(body_html)
                if len(full_text) < 280:
                    continue

                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=f"RS {section_number}",
                        full_text=full_text,
                        legal_area=self._identify_legal_area(full_text),
                        source_url=law_url,
                        official_cite=f"La. Rev. Stat. {section_number}",
                        metadata=StatuteMetadata(),
                        structured_data={
                            "source_kind": source_kind,
                            "discovery_method": discovery_method,
                            "skip_hydrate": True,
                        },
                    )
                )
                seen_sections.add(section_number)
                if len(statutes) == 1 or len(statutes) % 50 == 0:
                    self.logger.info(
                        "Louisiana law-page crawl: scanned_laws=%s/%s statutes_so_far=%s",
                        law_index,
                        len(law_urls),
                        len(statutes),
                    )
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="louisiana-law-page-progress",
                        extra={
                            "scanned_laws": int(law_index),
                            "discovered_laws": int(discovered_total),
                            "codes_completed": 0,
                            "codes_total": 1,
                            "source_kind": source_kind,
                            "discovery_method": discovery_method,
                            **acquisition_stats,
                        },
                    )
            if stop_requested:
                break

        if exact_full_frontier:
            assert strict_frontier is not None
            strict_frontier.update(acquisition_stats)
            strict_frontier["statutes_emitted"] = len(statutes)
            strict_frontier["terminal_pages_excluded"] = len(
                terminal_dispositions
            )
            unresolved = list(strict_frontier.get("unresolved_law_pages") or [])
            reconciled = bool(
                not unresolved
                and discovered_total
                == int(strict_frontier["law_pages_requested"])
                == int(strict_frontier["law_pages_fetched"])
                == int(strict_frontier["law_pages_classified"])
                == len(statutes) + len(terminal_dispositions)
            )
            if not reconciled:
                self._fail_louisiana_full_frontier(
                    "Louisiana strict law-page frontier did not reconcile",
                    law_pages_discovered=discovered_total,
                    law_pages_requested=int(
                        strict_frontier["law_pages_requested"]
                    ),
                    law_pages_fetched=int(strict_frontier["law_pages_fetched"]),
                    law_pages_classified=int(
                        strict_frontier["law_pages_classified"]
                    ),
                    statutes_emitted=len(statutes),
                    terminal_pages_excluded=len(terminal_dispositions),
                    unresolved_law_pages=unresolved,
                )
            ledger = getattr(self, "_state_law_acquisition_ledger", None)
            toc_reports: List[Dict[str, Any]] = []
            toc_law_urls: List[str] = []
            if callable(getattr(ledger, "replay_retained_parser_input", None)):
                toc_reports, toc_law_urls = self._retained_louisiana_toc_reports()
                report_urls = [
                    str(row.get("source_url") or "") for row in leaf_reports
                ]
                if toc_law_urls != report_urls:
                    raise RuntimeError(
                        "Louisiana retained TOC membership changed before closure"
                    )
            exact_frontier = self._louisiana_exact_frontier(
                toc_reports=toc_reports,
                leaf_reports=leaf_reports,
            )
            strict_frontier["closed"] = True
            strict_frontier["frontier"] = exact_frontier
            strict_frontier["toc_reports"] = toc_reports
            strict_frontier["code_name"] = code_name
            strict_frontier["boundary_first"] = law_urls[0]
            strict_frontier["boundary_last"] = law_urls[-1]
            strict_frontier["observed_at"] = datetime.now(timezone.utc).isoformat()
            self._last_louisiana_full_frontier = strict_frontier
            self._last_full_corpus_frontier = strict_frontier
            for statute in statutes:
                structured_data = dict(statute.structured_data or {})
                structured_data.update(
                    {
                        "official_frontier_closed": True,
                        "official_law_pages_discovered": discovered_total,
                        "official_law_pages_fetched": int(
                            strict_frontier["law_pages_fetched"]
                        ),
                        "official_terminal_pages_excluded": len(
                            terminal_dispositions
                        ),
                    }
                )
                statute.structured_data = structured_data

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="louisiana-law-page-complete",
            force=True,
            extra={
                "scanned_laws": int(discovered_total),
                "discovered_laws": int(discovered_total),
                "codes_completed": 1,
                "codes_total": 1,
                "source_kind": source_kind,
                "discovery_method": discovery_method,
                **(
                    {
                        "frontier_closed": True,
                        "law_pages_fetched": int(
                            strict_frontier["law_pages_fetched"]
                        ),
                        "law_pages_classified": int(
                            strict_frontier["law_pages_classified"]
                        ),
                        "terminal_pages_excluded": len(terminal_dispositions),
                        "terminal_disposition_counts": dict(
                            strict_frontier["terminal_disposition_counts"]
                        ),
                    }
                    if strict_frontier is not None
                    else {}
                ),
                **acquisition_stats,
            },
        )
        return statutes

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Reparse the retained ASP.NET TOC and every retained law page."""

        first = getattr(self, "_last_louisiana_full_frontier", None)
        if not isinstance(first, Mapping) or first.get("closed") is not True:
            raise RuntimeError(
                "Louisiana strict source frontier was not closed before output"
            )
        first_frontier = first.get("frontier")
        first_toc_raw = first.get("toc_reports")
        first_leaf_raw = first.get("leaf_reports")
        if (
            not isinstance(first_frontier, Mapping)
            or not isinstance(first_toc_raw, Sequence)
            or isinstance(first_toc_raw, (str, bytes, bytearray))
            or not first_toc_raw
            or any(not isinstance(row, Mapping) for row in first_toc_raw)
            or not isinstance(first_leaf_raw, Sequence)
            or isinstance(first_leaf_raw, (str, bytes, bytearray))
            or not first_leaf_raw
            or any(not isinstance(row, Mapping) for row in first_leaf_raw)
        ):
            raise RuntimeError("Louisiana first exact frontier is incomplete")
        first_toc = [dict(row) for row in first_toc_raw]
        first_leaves = [dict(row) for row in first_leaf_raw]

        replay_toc, replay_urls = self._retained_louisiana_toc_reports()
        if replay_toc != first_toc:
            raise RuntimeError("Louisiana retained TOC inputs changed on replay")
        expected_urls = [str(row.get("source_url") or "") for row in first_leaves]
        if replay_urls != expected_urls:
            raise RuntimeError("Louisiana retained TOC law membership changed on replay")

        from .louisiana_law import (
            source_bound_terminal_disposition_from_law_html,
            statute_from_law_html,
            terminal_disposition_from_law_html,
        )
        from .strict_frontier_closure import (
            replay_exact_retained_state_input,
            retain_exact_state_frontier_closure,
        )

        code_name = str(first.get("code_name") or "Louisiana Revised Statutes")
        replay_rows: List[NormalizedStatute] = []
        replay_leaves: List[Dict[str, Any]] = []
        identities: set[str] = set()
        for source_url, expected in zip(replay_urls, first_leaves, strict=True):
            body = replay_exact_retained_state_input(
                self,
                official_url=source_url,
                sanitized_request={"method": "GET", "url": source_url},
                frontier_name="Louisiana law-page frontier",
                refresh=False,
            )
            digest = hashlib.sha256(body).hexdigest()
            html = body.decode("utf-8", errors="replace")
            statute = statute_from_law_html(
                html,
                source_url=source_url,
                code_name=code_name,
                content_sha256=digest,
            )
            if statute is not None:
                body_prefix = str(
                    (statute.structured_data or {}).get("body_prefix") or ""
                ).strip()
                identity = "|".join(
                    (
                        body_prefix,
                        str(statute.title_number or "").strip(),
                        str(statute.section_number or "").strip(),
                    )
                )
                if not identity.strip("|") or identity in identities:
                    raise RuntimeError(
                        "Louisiana retained replay repeated or lost a legal identity: "
                        f"{identity}"
                    )
                identities.add(identity)
                disposition = "operative"
                replay_rows.append(statute)
            else:
                identity = ""
                disposition = source_bound_terminal_disposition_from_law_html(
                    html,
                    source_url=source_url,
                    content_sha256=digest,
                ) or terminal_disposition_from_law_html(html)
                if not disposition:
                    raise RuntimeError(
                        "Louisiana retained replay left a law page unclassified: "
                        f"{source_url}"
                    )
            report = {
                "canonical_identity": identity,
                "content_sha256": digest,
                "disposition": disposition,
                "source_url": source_url,
            }
            if report != expected:
                raise RuntimeError(
                    "Louisiana retained law-page report changed on replay: "
                    f"{source_url}"
                )
            replay_leaves.append(report)

        replayed_frontier = self._louisiana_exact_frontier(
            toc_reports=replay_toc,
            leaf_reports=replay_leaves,
        )
        observed_at = str(first.get("observed_at") or "")
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="LA",
            source_domain="legis.la.gov",
            official_source_url=(
                f"{self.get_base_url()}/legis/Laws_Toc.aspx?folder=75&level=Parent"
            ),
            observed_at=observed_at,
            legal_as_of=observed_at[:10],
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(first_leaves),
            pagination_total=len(first_toc),
            transport={
                "fixture": False,
                "first_pass_request_batches": int(
                    first.get("frontier_batches") or 0
                ),
                "first_pass_requested_pages": len(first_leaves),
                "grouped_warc_recovery": True,
                "kind": "stateful_toc_plus_shared_archive_aware_plural_html",
                "leaf_acquisition_wave_count": int(
                    first.get("leaf_acquisition_wave_count") or 0
                ),
                "per_page_archive_loop": False,
                "repeat_grouped_archive_inventory_on_residual": False,
                "residual_only_retries": True,
                "residual_retry_requested_pages": int(
                    first.get("residual_retry_requested_pages") or 0
                ),
                "retained_replay_network_requests": 0,
                "source_ordered_cross_parent_union": True,
                "synthetic": False,
                "warc_range_fetches_avoided": int(
                    first.get("warc_range_fetches_avoided") or 0
                ),
                "wayback_prefix_inventory": True,
            },
        )

    async def _discover_live_toc_title_pages(self, limit: Optional[int] = None) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        root_url = f"{self.get_base_url()}/legis/Laws_Toc.aspx?folder=75&level=Parent"

        heartbeat_every_raw = str(
            os.getenv("STATE_SCRAPER_LA_TOC_HEARTBEAT_EVERY", "") or ""
        ).strip()
        try:
            heartbeat_every = int(heartbeat_every_raw) if heartbeat_every_raw else 25
        except Exception:
            heartbeat_every = 25
        heartbeat_every = max(5, min(250, heartbeat_every))

        timeout_raw = str(
            os.getenv("STATE_SCRAPER_LA_TOC_DISCOVERY_TIMEOUT_SECONDS", "") or ""
        ).strip()
        try:
            discovery_timeout_seconds = float(timeout_raw) if timeout_raw else 600.0
        except Exception:
            discovery_timeout_seconds = 600.0
        discovery_timeout_seconds = max(30.0, min(7200.0, discovery_timeout_seconds))

        session = self._new_stateful_parser_input_session(verify_tls=True)

        async def _crawl() -> List[str]:
            root_body = await self._fetch_parser_input_with_transport(
                root_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                },
                timeout_seconds=30,
                allow_archival_fallback=False,
                verify_tls=True,
                media_type="text/html",
                provider="louisiana_stateful_toc_direct",
                pagination={"kind": "aspnet_toc", "step": "root"},
                stateful_session=session,
            )
            if not root_body:
                return []
            soup = BeautifulSoup(
                root_body.decode("utf-8", errors="replace"),
                "html.parser",
            )

            base_payload: Dict[str, str] = {}
            for inp in soup.select("input[name]"):
                name = inp.get("name")
                if name:
                    base_payload[str(name)] = str(inp.get("value") or "")

            event_targets = self._title_postback_targets(
                root_body.decode("utf-8", errors="replace")
            )

            law_urls: List[str] = []
            seen_laws = set()
            title_limit = (
                len(event_targets)
                if self._full_corpus_enabled() and (limit is None or int(limit) >= 1000000)
                else min(len(event_targets), max(1, int(limit or 1)))
            )
            for title_index, target in enumerate(event_targets[:title_limit], start=1):
                if title_index == 1 or title_index % heartbeat_every == 0:
                    self._write_partial_checkpoint(
                        [],
                        code_name="Louisiana Revised Statutes",
                        stage_label="louisiana:toc-discovery",
                        extra={
                            "titles_scanned": int(title_index),
                            "discovered_titles": int(title_limit),
                            "discovered_laws": int(len(law_urls)),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )
                post_payload = dict(base_payload)
                post_payload["__EVENTTARGET"] = target
                post_payload["__EVENTARGUMENT"] = ""
                encoded = urllib.parse.urlencode(post_payload).encode("utf-8")
                post_body = await self._fetch_parser_input_with_transport(
                    root_url,
                    method="POST",
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    request_body=encoded,
                    timeout_seconds=45,
                    allow_archival_fallback=False,
                    verify_tls=True,
                    media_type="text/html",
                    provider="louisiana_stateful_toc_direct",
                    pagination={
                        "kind": "aspnet_postback",
                        "page_index": title_index,
                        "page_count": title_limit,
                    },
                    stateful_session=session,
                )
                if not post_body:
                    continue
                page = BeautifulSoup(
                    post_body.decode("utf-8", errors="replace"),
                    "html.parser",
                )
                for anchor in page.find_all("a", href=True):
                    href = str(anchor.get("href") or "").strip()
                    if not self._LAW_LINK_RE.search(href):
                        continue
                    full_url = urllib.parse.urljoin(root_url, href)
                    if full_url in seen_laws:
                        continue
                    seen_laws.add(full_url)
                    law_urls.append(full_url)
            return law_urls

        try:
            started_at = time.time()
            law_urls = await asyncio.wait_for(
                _crawl(),
                timeout=discovery_timeout_seconds,
            )
            elapsed = max(0.0, time.time() - started_at)
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                self.logger.warning(
                    "Louisiana live TOC discovery timed out after %.1fs; falling back to alternate sources",
                    discovery_timeout_seconds,
                )
            else:
                self.logger.debug(f"Louisiana live TOC discovery failed: {exc}")
            self._write_partial_checkpoint(
                [],
                code_name="Louisiana Revised Statutes",
                stage_label="louisiana:toc-discovery-failed",
                force=True,
                extra={
                    "titles_scanned": 0,
                    "discovered_titles": 0,
                    "discovered_laws": 0,
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )
            return []
        finally:
            await self._close_stateful_parser_input_session(session)

        self.logger.info(
            "Louisiana live TOC: discovered %s law pages in %.1fs",
            len(law_urls),
            elapsed,
        )
        self._write_partial_checkpoint(
            [],
            code_name="Louisiana Revised Statutes",
            stage_label="louisiana:toc-discovery-complete",
            force=True,
            extra={
                "titles_scanned": int(max(1, len(law_urls))),
                "discovered_titles": int(max(1, len(law_urls))),
                "discovered_laws": int(len(law_urls)),
                "codes_completed": 0,
                "codes_total": 1,
            },
        )
        if not law_urls:
            self.logger.debug("Louisiana live TOC discovery completed with zero law urls")
        return law_urls

    async def _discover_archived_law_urls(self, limit: int = 120) -> List[str]:
        """Discover additional archived Law.aspx pages via Wayback CDX."""
        cdx_url = (
            "http://web.archive.org/cdx/search/cdx?url=legis.la.gov/Legis/Law.aspx?d=*"
            "&output=json&filter=statuscode:200&collapse=digest"
            f"&limit={max(1, int(limit))}"
        )

        try:
            rows = await self._fetch_wayback_cdx_rows(
                cdx_url,
                timeout_seconds=45,
            )
            if len(rows) < 2:
                return []

            discovered: List[str] = []
            for row in rows[1:]:
                if not isinstance(row, list) or len(row) < 3:
                    continue
                ts = str(row[1]).strip()
                original = str(row[2]).strip()
                if not ts or not original:
                    continue
                encoded = urllib.parse.quote(original, safe=":/?=&%.-_")
                discovered.append(f"http://web.archive.org/web/{ts}/{encoded}")
            return discovered
        except Exception as exc:
            self.logger.debug(f"Louisiana CDX discovery failed: {exc}")
            return []

    def _extract_law_body_html(self, html: str) -> str:
        marker = re.search(
            r'<span[^>]+id=["\']ctl00_PageBody_LabelDocument["\'][^>]*>(.*?)</span>',
            str(html or ""),
            flags=re.IGNORECASE | re.DOTALL,
        )
        return marker.group(1) if marker else ""

    def _extract_section_number(self, html: str) -> str:
        marker = re.search(
            r'<span[^>]+id=["\']ctl00_PageBody_LabelName["\'][^>]*>(.*?)</span>',
            str(html or ""),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not marker:
            return ""

        text = self._clean_html_text(marker.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        return text

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

        text = unescape(value)
        text = text.replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s*\n\s*", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()
        if max_chars is not None:
            return text[: max(1, int(max_chars))]
        return text

    async def _request_text(self, law_url: str, headers: Dict[str, str], timeout: int) -> str:
        candidates = [str(law_url or "")]
        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        for candidate in candidates:
            try:
                if "web.archive.org/web/" in candidate:
                    payload = await self._fetch_parser_input_with_transport(
                        candidate,
                        headers=headers,
                        timeout_seconds=max(1, int(timeout)),
                        # This locator is already an archive replay.  A second
                        # archive-discovery pass would not preserve semantics.
                        allow_archival_fallback=False,
                        media_type="text/html",
                        provider="louisiana_wayback_direct",
                    )
                    if payload:
                        return payload.decode("utf-8", errors="replace")
                payload = await self._fetch_page_content_with_archival_fallback(
                    candidate,
                    timeout_seconds=timeout,
                )
                if not payload:
                    continue
                return payload.decode("utf-8", errors="replace")
            except Exception:
                continue
        return ""

    MISSING_LINK_DISPOSITION = "missing_official_source_link"
    _LA_LAWID_RE = re.compile(
        r"(?:Law\.aspx\?d=|['\"]d['\"]\s*[:=]\s*|['\"]d=)(\d+)",
        re.IGNORECASE,
    )
    _LA_LINKLESS_LABEL_RE = re.compile(
        r"\b(?:RS|R\.S\.)\s+\d|Title\s+\d+|Chapter\s+\d+",
        re.IGNORECASE,
    )

    def _official_ssl_context(self, *, unverified: bool = False):
        import ssl

        if unverified:
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    def _official_http_get(self, url: str, timeout: int = 20) -> tuple[bytes, bytes, bytes]:
        """Fetch one official Louisiana URL and retain request/response/body bytes."""
        import ssl
        import urllib.error
        import urllib.request

        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        request_bytes = (
            f"GET {path} HTTP/1.1\n"
            f"host: {host}\n"
            "accept: text/html,application/xhtml+xml;q=0.9,*/*;q=0.8\n"
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ipfs-datasets-open-us-law-louisiana/1.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        last_exc: Exception | None = None
        body = b""
        status = 0
        header_block = ""
        for unverified in (False, True):
            try:
                with urllib.request.urlopen(
                    req,
                    timeout=max(5, int(timeout)),
                    context=self._official_ssl_context(unverified=unverified),
                ) as resp:
                    body = bytes(resp.read() or b"")
                    status = int(getattr(resp, "status", 200) or 200)
                    header_block = "".join(
                        f"{key}: {value}\n" for key, value in resp.headers.items()
                    )
                last_exc = None
                break
            except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as exc:
                last_exc = exc
                continue
        if last_exc is not None:
            raise RuntimeError(f"official Louisiana GET failed for {url}: {last_exc}") from last_exc
        if status != 200 or not body:
            raise RuntimeError(f"official Louisiana GET returned HTTP {status} for {url}")
        response_bytes = f"HTTP/1.1 {status} OK\n{header_block}\n".encode("utf-8") + body
        return request_bytes, response_bytes, body

    def _official_http_post(
        self,
        url: str,
        payload: Dict[str, str],
        timeout: int = 45,
    ) -> bytes:
        import ssl
        import urllib.error
        import urllib.request

        encoded = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=encoded,
            headers={
                "User-Agent": "ipfs-datasets-open-us-law-louisiana/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            method="POST",
        )
        last_exc: Exception | None = None
        body = b""
        status = 0
        for unverified in (False, True):
            try:
                with urllib.request.urlopen(
                    req,
                    timeout=max(5, int(timeout)),
                    context=self._official_ssl_context(unverified=unverified),
                ) as resp:
                    body = bytes(resp.read() or b"")
                    status = int(getattr(resp, "status", 200) or 200)
                last_exc = None
                break
            except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as exc:
                last_exc = exc
                continue
        if last_exc is not None:
            raise RuntimeError(f"official Louisiana POST failed for {url}: {last_exc}") from last_exc
        if status != 200 or not body:
            raise RuntimeError(f"official Louisiana POST returned HTTP {status} for {url}")
        return body

    def _official_law_url(self, law_id: str, page_url: str = "") -> str:
        law_id = str(law_id or "").strip()
        if not law_id:
            return ""
        return f"https://legis.la.gov/Legis/Law.aspx?d={law_id}"

    def classify_official_index_rows(
        self,
        html: str,
        *,
        page_url: str,
    ) -> Dict[str, List[Dict[str, str]]]:
        """Repair official Law.aspx links or quarantine linkless rows.

        Returns ``{"repaired": [...], "quarantines": [...]}``. Each quarantine
        carries a typed ``missing_official_source_link`` disposition plus an
        evidence hash of the raw HTML fragment.
        """
        import hashlib

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for official Louisiana discovery") from exc

        soup = BeautifulSoup(html, "html.parser")
        repaired: List[Dict[str, str]] = []
        quarantines: List[Dict[str, str]] = []
        seen_ids: set[str] = set()
        seen_quarantine: set[str] = set()

        def _digits(value: object) -> str:
            match = re.search(r"(\d+)", str(value or ""))
            return match.group(1) if match else ""

        def _record_official(law_id: str, label: str, source: str) -> None:
            law_id = _digits(law_id)
            if not law_id or law_id in seen_ids:
                return
            seen_ids.add(law_id)
            official_url = self._official_law_url(law_id, page_url)
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip() or f"RS law {law_id}"
            repaired.append(
                {
                    "canonical_key": f"la:law-{law_id}",
                    "law_id": law_id,
                    "source_url": official_url,
                    "label": cleaned,
                    "repair_source": source,
                    "text": (
                        f"Louisiana Revised Statutes {cleaned} official Law.aspx "
                        f"unit {law_id} retained from {official_url}"
                    ),
                }
            )

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            match = self._LAW_LINK_RE.search(href) or self._LA_LAWID_RE.search(href)
            if match:
                law_id = match.group(1) if match.lastindex else match.group(0)
                _record_official(law_id, label, "official_href")
                continue
            nearby = " ".join(
                str(item or "")
                for item in (
                    href,
                    link.get("onclick"),
                    link.get("id"),
                    link.get("data-d"),
                    link.get("data-id"),
                    label,
                )
            )
            repaired_id = self._LA_LAWID_RE.search(nearby) or _digits(
                link.get("data-d") or link.get("data-id")
            )
            if repaired_id:
                law_id = repaired_id.group(1) if hasattr(repaired_id, "group") else repaired_id
                _record_official(law_id, label, "repaired_from_attributes")

        for node in soup.find_all(["span", "td", "li", "div"]):
            label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
            if not label or not self._LA_LINKLESS_LABEL_RE.search(label):
                continue
            if node.find("a", href=True):
                continue
            attr_id = _digits(node.get("data-d") or node.get("data-id"))
            blob = " ".join(
                str(item or "")
                for item in (
                    node.get("onclick"),
                    node.get("id"),
                    node.get("data-d"),
                    node.get("data-id"),
                    label,
                    str(node),
                )
            )
            repaired_id = self._LA_LAWID_RE.search(blob)
            if attr_id or repaired_id:
                _record_official(
                    attr_id or repaired_id.group(1),
                    label,
                    "repaired_from_linkless_row",
                )
                continue
            unit_id = f"la:missing-{hashlib.sha256(label.encode('utf-8')).hexdigest()[:16]}"
            if unit_id in seen_quarantine:
                continue
            seen_quarantine.add(unit_id)
            evidence = hashlib.sha256(str(node).encode("utf-8")).hexdigest()
            quarantines.append(
                {
                    "unit_id": unit_id,
                    "reason": self.MISSING_LINK_DISPOSITION,
                    "label": label[:240],
                    "page_url": page_url,
                    "evidence_sha256": evidence,
                }
            )
        return {"repaired": repaired, "quarantines": quarantines}

    def _form_payload(self, html: str) -> Dict[str, str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return {}
        soup = BeautifulSoup(html, "html.parser")
        payload: Dict[str, str] = {}
        for inp in soup.select("input[name]"):
            name = inp.get("name")
            if name:
                payload[str(name)] = str(inp.get("value") or "")
        return payload

    def _title_postback_targets(self, html: str) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        targets: List[str] = []
        seen: set[str] = set()
        page = BeautifulSoup(str(html or ""), "html.parser")
        for anchor in page.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            match = self._TOC_TITLE_POSTBACK_RE.fullmatch(href)
            if not match:
                continue
            target = match.group("target")
            if target in seen:
                continue
            seen.add(target)
            targets.append(target)
        return targets

    def discover_official_law_catalog(self) -> Dict[str, object]:
        """Walk the live official TOC and return repaired units plus quarantines."""
        index_url = f"{self.get_base_url()}/legis/Laws.aspx"
        toc_url = f"{self.get_base_url()}/legis/Laws_Toc.aspx?folder=75&level=Parent"
        request_bytes, response_bytes, index_body = self._official_http_get(index_url)
        pages: List[tuple[str, str]] = [
            (index_url, index_body.decode("utf-8", errors="replace")),
        ]
        try:
            _, _, toc_body = self._official_http_get(toc_url)
            pages.append((toc_url, toc_body.decode("utf-8", errors="replace")))
        except Exception:
            toc_body = b""

        repaired: List[Dict[str, str]] = []
        quarantines: List[Dict[str, str]] = []
        seen_keys: set[str] = set()
        seen_quarantine: set[str] = set()

        def _merge(page_url: str, html: str) -> None:
            classified = self.classify_official_index_rows(html, page_url=page_url)
            for unit in classified["repaired"]:
                key = unit["canonical_key"]
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                repaired.append(unit)
            for item in classified["quarantines"]:
                unit_id = item["unit_id"]
                if unit_id in seen_quarantine:
                    continue
                seen_quarantine.add(unit_id)
                quarantines.append(item)

        for page_url, html in pages:
            _merge(page_url, html)

        toc_html = pages[-1][1] if pages else ""
        targets = self._title_postback_targets(toc_html)
        payload = self._form_payload(toc_html)
        for target in targets:
            if not payload:
                break
            post_payload = dict(payload)
            post_payload["__EVENTTARGET"] = target
            post_payload["__EVENTARGUMENT"] = ""
            try:
                posted = self._official_http_post(toc_url, post_payload)
            except Exception:
                continue
            _merge(toc_url, posted.decode("utf-8", errors="replace"))

        if len(repaired) < 3:
            for archive_url in self._ARCHIVE_LAW_URLS:
                digits = re.search(r"[?&]d=(\d+)", str(archive_url), flags=re.IGNORECASE)
                if not digits:
                    continue
                law_id = digits.group(1)
                official_url = self._official_law_url(law_id)
                if any(item.get("law_id") == law_id for item in repaired):
                    continue
                try:
                    _, _, law_body = self._official_http_get(official_url)
                except Exception:
                    continue
                classified = self.classify_official_index_rows(
                    law_body.decode("utf-8", errors="replace"),
                    page_url=official_url,
                )
                if classified["repaired"]:
                    _merge(official_url, law_body.decode("utf-8", errors="replace"))
                    continue
                section_number = self._extract_section_number(
                    law_body.decode("utf-8", errors="replace")
                ) or f"RS law {law_id}"
                repaired.append(
                    {
                        "canonical_key": f"la:law-{law_id}",
                        "law_id": law_id,
                        "source_url": official_url,
                        "label": section_number,
                        "repair_source": "official_law_id_repair",
                        "text": (
                            f"Louisiana Revised Statutes {section_number} official "
                            f"Law.aspx unit {law_id} retained from {official_url}"
                        ),
                    }
                )

        return {
            "index_url": index_url,
            "request_bytes": request_bytes,
            "response_bytes": response_bytes,
            "index_body": index_body,
            "repaired": repaired,
            "quarantines": quarantines,
        }

    def fetch_official(self, code: str = "LA"):
        """Acquire the uncapped official Louisiana RS index with link repair.

        Missing-link rows are repaired to official ``Law.aspx?d=`` URLs when a
        law identifier can be recovered. Remaining linkless rows are quarantined
        with typed ``missing_official_source_link`` disposition.
        """
        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or self.state_code or "LA").strip().upper()
        if normalized != "LA":
            raise ValueError(f"LouisianaScraper cannot acquire {normalized}")
        catalog = self.discover_official_law_catalog()
        units = list(catalog["repaired"])
        quarantines = list(catalog["quarantines"])
        self.last_official_quarantines = quarantines
        if len(units) < 3:
            raise RuntimeError(
                f"official Louisiana law index is incomplete: {len(units)} repaired units"
            )
        rows = tuple(
            {
                "canonical_key": unit["canonical_key"],
                "source_url": unit["source_url"],
                "text": unit["text"],
            }
            for unit in units
        )
        catalog_lines = [
            f"{unit['canonical_key']}\t{unit['source_url']}\t{unit['label']}"
            for unit in units
        ]
        for item in quarantines:
            catalog_lines.append(
                f"{item['unit_id']}\tQUARANTINE\t{item['reason']}\t{item['label']}"
            )
        body_bytes = "\n".join(catalog_lines).encode("utf-8")
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
            "la_missing_link_quarantines": quarantines,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code="LA",
            request_bytes=bytes(catalog["request_bytes"]),
            response_bytes=bytes(catalog["response_bytes"]),
            body_bytes=body_bytes,
            source_domain="legis.la.gov",
            source_path="/legis/Laws.aspx",
            frontier=frontier,
            rows=rows,
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=rows[0]["canonical_key"],
            last_hierarchy_unit=rows[-1]["canonical_key"],
        )


# Register this scraper with the registry
StateScraperRegistry.register("LA", LouisianaScraper)
