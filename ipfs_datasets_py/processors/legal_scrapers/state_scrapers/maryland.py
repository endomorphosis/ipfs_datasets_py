"""Scraper for Maryland state laws.

This module contains the scraper for Maryland statutes from the official state
legislative website.
"""

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
import urllib.parse
import urllib.request

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StateLawPageMultiFetchResult,
    StatuteMetadata,
)
from .registry import StateScraperRegistry


_MARYLAND_UNFETCHED = object()


class MarylandScraper(BaseStateScraper):
    """Scraper for Maryland state laws from http://mgaleg.maryland.gov"""

    _MD_ARTICLE_CODE_RE = re.compile(r"\(([A-Za-z0-9]+)\)\s*$")
    _MD_NEXT_TRAIL_RE = re.compile(r"\s+Next\s*$", re.IGNORECASE)
    _MD_SECTION_CITE_RE = re.compile(r"§\s*([0-9A-Za-z\-\u2010-\u2015\.]+)")

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            maryland_section,
            state_archival_fetch,
            strict_frontier_closure,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            maryland_section,
            wayback_machine_engine,
        )

    def get_base_url(self) -> str:
        """Return the base URL for Maryland's legislative website."""
        return "https://mgaleg.maryland.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Maryland."""
        return [
            {
                "name": "Maryland Code",
                "url": f"{self.get_base_url()}/mgawebsite/Laws/Statutes",
                "type": "Code",
            }
        ]

    def _extract_article_code(self, display_text: str, value: str) -> str:
        match = self._MD_ARTICLE_CODE_RE.search(str(display_text or ""))
        if match:
            return match.group(1).upper()
        return str(value or "").strip().upper()

    def _normalize_section_code(self, value: str) -> str:
        normalized = str(value or "").strip()
        for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212"):
            normalized = normalized.replace(dash, "-")
        normalized = re.sub(r"\s+", "", normalized)
        return normalized.strip(".")

    def _is_maryland_api_record(self, statute: NormalizedStatute) -> bool:
        if not isinstance(statute, NormalizedStatute):
            return False
        structured = getattr(statute, "structured_data", {}) or {}
        return str(structured.get("record_type") or "").strip().lower() == "maryland_api_section"

    def _statute_article_rows(self, payload: object) -> List[Dict[str, str]]:
        """Normalize the exact statutory subset of GetArticles in source order."""

        if not isinstance(payload, list):
            return []
        from .maryland_section import is_statute_article_code

        rows: List[Dict[str, str]] = []
        seen: set[str] = set()
        for article in payload:
            if not isinstance(article, dict):
                continue
            value = str(article.get("Value") or "").strip()
            display = str(article.get("DisplayText") or "").strip()
            code = self._extract_article_code(display, value)
            normalized = code.casefold()
            if (
                not is_statute_article_code(normalized)
                or not normalized
            ):
                continue
            if normalized in seen:
                raise RuntimeError(
                    "Maryland GetArticles repeated a statutory article identity"
                )
            seen.add(normalized)
            rows.append(
                {
                    "article_code": code,
                    "display_text": display,
                    "value": value,
                }
            )
        return rows

    def _section_rows_from_payload(self, payload: object) -> List[tuple[str, str]]:
        """Normalize one complete GetSections response in source order."""

        if not isinstance(payload, list):
            return []
        rows: List[tuple[str, str]] = []
        seen: set[str] = set()
        for section in payload:
            if not isinstance(section, dict):
                continue
            label = str(section.get("DisplayText") or "").strip()
            code = self._normalize_section_code(
                label or str(section.get("Value") or "")
            )
            normalized = code.casefold()
            if not normalized or normalized in seen:
                raise RuntimeError(
                    "Maryland GetSections exposed an empty or duplicate identity"
                )
            seen.add(normalized)
            rows.append((label or code, code))
        return rows

    def _retained_maryland_catalog_reports(
        self,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
        """Replay GetArticles/GetSections and derive the exact leaf membership."""

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from .strict_frontier_closure import replay_exact_retained_state_input

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Maryland catalog replay requires an attached ledger")
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()
        articles_url = self._canonical_fetch_url(
            f"{self.get_base_url()}/mgawebsite/api/Laws/GetArticles?enactments=false"
        )
        articles_raw = replay_exact_retained_state_input(
            self,
            official_url=articles_url,
            sanitized_request={"method": "GET", "url": articles_url},
            frontier_name="Maryland article catalog",
            refresh=False,
        )
        try:
            articles_payload = json.loads(articles_raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Maryland retained article catalog is not JSON") from exc
        articles = self._statute_article_rows(articles_payload)
        if not articles:
            raise RuntimeError("Maryland retained statutory article catalog is empty")
        reports: List[Dict[str, Any]] = [
            {
                "article_count": len(articles),
                "content_sha256": hashlib.sha256(articles_raw).hexdigest(),
                "kind": "articles",
                "membership_sha256": hashlib.sha256(
                    canonical_json_bytes(articles)
                ).hexdigest(),
                "source_url": articles_url,
            }
        ]
        units: List[Dict[str, str]] = []
        seen_urls: set[str] = set()
        for article in articles:
            article_code = article["article_code"]
            article_value = article["value"] or article_code.lower()
            sections_url = self._canonical_fetch_url(
                f"{self.get_base_url()}/mgawebsite/api/Laws/GetSections"
                f"?articleCode={article_value}&enactments=false"
            )
            sections_raw = replay_exact_retained_state_input(
                self,
                official_url=sections_url,
                sanitized_request={"method": "GET", "url": sections_url},
                frontier_name=f"Maryland {article_code} section catalog",
                refresh=False,
            )
            try:
                sections_payload = json.loads(sections_raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"Maryland retained {article_code} section catalog is not JSON"
                ) from exc
            section_rows = self._section_rows_from_payload(sections_payload)
            if not section_rows:
                raise RuntimeError(
                    f"Maryland retained {article_code} section catalog is empty"
                )
            article_units: List[Dict[str, str]] = []
            for section_label, section_number in section_rows:
                source_url = self._canonical_fetch_url(
                    f"{self.get_base_url()}/mgawebsite/Laws/StatuteText"
                    f"?article={article_code}&section={section_number}"
                    "&enactments=false"
                )
                if source_url in seen_urls:
                    raise RuntimeError(
                        "Maryland retained hierarchy repeated a section URL: "
                        f"{source_url}"
                    )
                seen_urls.add(source_url)
                unit = {
                    "article_code": article_code,
                    "article_display": article["display_text"],
                    "section_label": section_label,
                    "section_number": section_number,
                    "source_url": source_url,
                }
                article_units.append(unit)
                units.append(unit)
            reports.append(
                {
                    "article_code": article_code,
                    "content_sha256": hashlib.sha256(sections_raw).hexdigest(),
                    "kind": "sections",
                    "membership_sha256": hashlib.sha256(
                        canonical_json_bytes(article_units)
                    ).hexdigest(),
                    "section_count": len(article_units),
                    "source_url": sections_url,
                }
            )
        return reports, units

    def _maryland_exact_frontier(
        self,
        *,
        catalog_reports: Sequence[Mapping[str, Any]],
        section_reports: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Build Maryland's deterministic hierarchy/leaf disposition closure."""

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        catalogs = [dict(row) for row in catalog_reports]
        sections = [dict(row) for row in section_reports]
        operative = sum(row.get("disposition") == "operative" for row in sections)
        disposition = {
            "discovered": len(sections),
            "duplicates": 0,
            "excluded": len(sections) - operative,
            "failed_final": 0,
            "fetched": operative,
            "quarantined": 0,
        }
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": False,
            "catalog_input_count": len(catalogs),
            "catalog_inputs_sha256": hashlib.sha256(
                canonical_json_bytes(catalogs)
            ).hexdigest(),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "leaf_input_count": len(sections),
            "leaf_inputs_sha256": hashlib.sha256(
                canonical_json_bytes(sections)
            ).hexdigest(),
            "method": "source_derived_articles_sections_api",
            "pagination_closed": bool(catalogs),
            "remaining_bundle_members": [],
            "scope_closed": True,
            "source_membership_sha256": hashlib.sha256(
                canonical_json_bytes(
                    [str(row.get("source_url") or "") for row in sections]
                )
            ).hexdigest(),
            "toc_exhausted": bool(catalogs),
            "unvisited_continuation_links": [],
            "visited_index_units": len(sections),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    async def _fetch_json(self, url: str) -> object:
        def _is_json_payload(payload: bytes) -> bool:
            try:
                json.loads(payload.decode("utf-8", errors="ignore"))
            except Exception:
                return False
            return True

        payload = await self._fetch_parser_input_with_transport(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout_seconds=45,
            content_validator=_is_json_payload,
            allow_archival_fallback=True,
            media_type="application/json",
            provider="maryland_api_direct",
        )
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8", errors="ignore"))
        except Exception:
            return None

    def _maryland_section_catalog_url(
        self,
        *,
        article_value: str,
        article_code: str,
    ) -> str:
        article_token = str(article_value or article_code.lower()).strip()
        return self._canonical_fetch_url(
            f"{self.get_base_url()}/mgawebsite/api/Laws/GetSections"
            f"?articleCode={article_token}&enactments=false"
        )

    async def _fetch_maryland_section_catalog_frontier(
        self,
        urls: Sequence[str],
        *,
        residual_retry_attempts: int,
    ) -> Dict[str, object]:
        """Acquire every deterministic GetSections catalog as one JSON wave."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if len(requested) != len(set(requested)):
            raise RuntimeError(
                "Maryland GetSections frontier contains duplicate exact URLs"
            )
        if not requested:
            return {}

        def _is_json_payload(payload: bytes) -> bool:
            try:
                json.loads(payload.decode("utf-8", errors="ignore"))
            except Exception:
                return False
            return True

        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=residual_retry_attempts,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout_seconds=45,
            content_validator=_is_json_payload,
            media_type="application/json",
            max_concurrency=min(32, len(requested)),
            prefer_direct=True,
            common_crawl_domain_terms=("mgaleg.maryland.gov",),
            common_crawl_url_terms=("/mgawebsite/api/Laws/GetSections",),
            common_crawl_mime_terms=("json",),
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
                "Maryland GetSections frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                "Maryland GetSections frontier changed URL order or identity"
            )
        failures = [
            {"url": url, "error": str(error or "empty parser input")}
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
                "Maryland GetSections frontier is incomplete; unresolved exact "
                f"URLs: {failures}"
            )

        strict_evidence = getattr(self, "_state_law_acquisition_ledger", None) is not None
        parsed_by_url: Dict[str, object] = {}
        for url, payload, receipt, envelope in zip(
            batch.urls,
            batch.payloads,
            batch.transport_receipts,
            batch.parser_input_envelopes,
            strict=True,
        ):
            body = bytes(payload)
            if strict_evidence:
                from ...legal_data.state_laws_source_provenance import (
                    StateLawTransportReceiptError,
                    canonicalize_state_law_transport_receipt,
                )

                try:
                    canonicalize_state_law_transport_receipt(
                        receipt,
                        official_url=url,
                        content_sha256=hashlib.sha256(body).hexdigest(),
                    )
                except StateLawTransportReceiptError as exc:
                    raise RuntimeError(
                        "Maryland GetSections frontier returned an unbound "
                        "transport receipt"
                    ) from exc
                if (
                    envelope is None
                    or bytes(getattr(envelope, "body", b"") or b"") != body
                ):
                    raise RuntimeError(
                        "Maryland GetSections frontier returned an unbound "
                        "parser-input envelope"
                    )
            try:
                parsed_by_url[url] = json.loads(
                    body.decode("utf-8", errors="ignore")
                )
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"Maryland GetSections frontier returned invalid JSON: {url}"
                ) from exc
        return parsed_by_url

    async def _fetch_api_section_code(self, url: str) -> Optional[str]:
        """Parse GetNext/GetPrevious JSON or the .NET XML ``<string>`` envelope."""

        from .maryland_section import parse_get_next_envelope

        payload = await self._fetch_json(url)
        if isinstance(payload, str) and payload.strip() and payload.strip().lower() != "null":
            return payload.strip()
        text = await self._fetch_text_direct(url, timeout=20)
        return parse_get_next_envelope(text)

    def _articles_from_toc_html(self, html: str) -> List[Dict[str, str]]:
        from .maryland_section import statute_articles

        out: List[Dict[str, str]] = []
        for code, name in statute_articles(html):
            out.append({"DisplayText": f"{name} - ({code})", "Value": code})
        return out

    async def _fetch_text_direct(self, url: str, timeout: int = 45) -> str:
        payload = await self._fetch_parser_input_with_transport(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout_seconds=max(1, int(timeout or 45)),
            allow_archival_fallback=True,
            media_type="text/html",
            provider="maryland_direct",
        )
        return payload.decode("utf-8", errors="ignore") if payload else ""

    async def _list_article_payload(self) -> List[Dict[str, str]]:
        from .maryland_section import TOC_URL, configured_toc_html_path

        toc_path = configured_toc_html_path()
        if toc_path is not None:
            return self._articles_from_toc_html(
                toc_path.read_text(encoding="utf-8", errors="replace")
            )
        articles_url = f"{self.get_base_url()}/mgawebsite/api/Laws/GetArticles?enactments=false"
        articles_payload = await self._fetch_json(articles_url)
        if isinstance(articles_payload, list) and articles_payload:
            filtered = [
                {
                    "DisplayText": row["display_text"],
                    "Value": row["value"],
                }
                for row in self._statute_article_rows(articles_payload)
            ]
            if filtered:
                return filtered
        toc_html = await self._fetch_text_direct(TOC_URL, timeout=45)
        if not toc_html:
            return []
        return self._articles_from_toc_html(toc_html)

    async def _list_section_codes(
        self,
        *,
        article_value: str,
        article_code: str,
        budget: Optional[int],
        sections_payload: object = _MARYLAND_UNFETCHED,
    ) -> List[tuple[str, str]]:
        """Return ``(label, section_code)`` from GetSections JSON or GetNext XML."""

        from .maryland_section import (
            first_section_seeds,
            get_next_url,
            get_previous_url,
        )

        sections_url = self._maryland_section_catalog_url(
            article_value=article_value,
            article_code=article_code,
        )
        if sections_payload is _MARYLAND_UNFETCHED:
            sections_payload = await self._fetch_json(sections_url)
        out: List[tuple[str, str]] = []
        if isinstance(sections_payload, list):
            normalized_rows = self._section_rows_from_payload(sections_payload)
            out = (
                normalized_rows
                if budget is None
                else normalized_rows[: max(0, int(budget))]
            )
            if out:
                return out

        seed = None
        article_token = article_value or article_code.lower()
        for candidate in first_section_seeds():
            nxt = await self._fetch_api_section_code(get_next_url(article_token, candidate))
            if nxt:
                seed = candidate
                break
            prev = await self._fetch_api_section_code(get_previous_url(article_token, candidate))
            if prev:
                seed = prev
                break
        if seed is None:
            return []
        current = seed
        previous_seen: set[str] = set()
        while current not in previous_seen:
            previous_seen.add(current)
            prev = await self._fetch_api_section_code(get_previous_url(article_token, current))
            if not prev:
                break
            current = prev
        seen: set[str] = set()
        requested_limit = None if budget is None else max(0, int(budget))
        while (
            current
            and current not in seen
            and (requested_limit is None or len(out) < requested_limit)
        ):
            seen.add(current)
            out.append((current, current))
            current = await self._fetch_api_section_code(get_next_url(article_token, current))
        return out

    async def _scrape_api_sections(
        self, code_name: str, max_statutes: Optional[int] = None
    ) -> List[NormalizedStatute]:
        articles_payload = await self._list_article_payload()
        if not isinstance(articles_payload, list) or not articles_payload:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        self.logger.info(
            "Maryland API scrape: discovered_articles=%s max_statutes=%s",
            len(articles_payload),
            limit or "unbounded",
        )

        statutes: List[NormalizedStatute] = []
        seen_urls = set()
        section_concurrency = max(
            1,
            min(
                64,
                int(
                    self._env_int(
                        "STATE_SCRAPER_MD_SECTION_CONCURRENCY",
                        default=8,
                    )
                    or 8
                ),
            ),
        )
        sem = asyncio.Semaphore(section_concurrency)
        residual_retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_MD_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=self._env_int(
                        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                        default=0,
                    ),
                ),
            ),
        )
        section_batch_size = self._env_int(
            "STATE_SCRAPER_MD_SECTION_BATCH_SIZE",
            default=40,
        )
        section_batch_size = max(8, min(256, int(section_batch_size or 40)))
        strict_catalog_payloads: Dict[str, object] = {}
        if limit is None:
            catalog_urls: List[str] = []
            for article in articles_payload:
                if not isinstance(article, dict):
                    continue
                article_display = str(article.get("DisplayText") or "").strip()
                article_value = str(article.get("Value") or "").strip()
                article_code = self._extract_article_code(
                    article_display,
                    article_value,
                )
                if not article_code:
                    continue
                catalog_urls.append(
                    self._maryland_section_catalog_url(
                        article_value=article_value,
                        article_code=article_code,
                    )
                )
            strict_catalog_payloads = (
                await self._fetch_maryland_section_catalog_frontier(
                    catalog_urls,
                    residual_retry_attempts=residual_retry_attempts,
                )
            )

        discovered_candidates = 0
        scanned_candidates = 0
        terminal_sections: List[Dict[str, str]] = []
        section_reports: List[Dict[str, Any]] = []

        def _closure_checkpoint_fields(
            unresolved: Optional[List[Dict[str, str]]] = None,
        ) -> Dict[str, object]:
            disposition_counts: Dict[str, int] = {}
            for record in terminal_sections:
                disposition = str(record.get("disposition") or "").strip()
                if disposition:
                    disposition_counts[disposition] = (
                        disposition_counts.get(disposition, 0) + 1
                    )
            unresolved_rows = list(unresolved or [])
            return {
                "terminal_sections_classified": len(terminal_sections),
                "terminal_disposition_counts": dict(sorted(disposition_counts.items())),
                "terminal_section_dispositions": list(terminal_sections),
                "unresolved_sections_count": len(unresolved_rows),
                "unresolved_section_dispositions": unresolved_rows,
            }

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="maryland:article-discovery",
            extra={
                "titles_scanned": 0,
                "discovered_titles": int(len(articles_payload)),
                "scanned_candidates": 0,
                "discovered_candidates": 0,
                "codes_completed": 0,
                "codes_total": 1,
                **_closure_checkpoint_fields(),
            },
        )

        # Exact production first derives the complete ordered leaf union from
        # every article catalog, then submits that union through one plural
        # archive-aware call.  Keeping one logical same-domain wave allows the
        # shared transport to perform Common Crawl/CDX discovery once and to
        # coalesce pointers that share a WARC object across article boundaries.
        # Parsing/checkpoint work below remains bounded by ``section_batch_size``
        # and direct/archive replay concurrency remains bounded by
        # ``section_concurrency``.
        strict_section_codes_by_url: Dict[str, List[tuple[str, str]]] = {}
        strict_leaf_rows_by_url: Dict[str, tuple[bytes, Optional[str], Any, Any]] = {}
        strict_leaf_batch_stats: Dict[str, Any] = {}
        if limit is None:
            strict_leaf_urls: List[str] = []
            strict_leaf_seen: set[str] = set()
            discovered_before_leaf_wave = 0
            for article_index, article in enumerate(articles_payload, start=1):
                if not isinstance(article, dict):
                    continue
                article_display = str(article.get("DisplayText") or "").strip()
                article_value = str(article.get("Value") or "").strip()
                article_code = self._extract_article_code(
                    article_display,
                    article_value,
                )
                if not article_code:
                    continue
                sections_url = self._maryland_section_catalog_url(
                    article_value=article_value,
                    article_code=article_code,
                )
                if sections_url not in strict_catalog_payloads:
                    raise RuntimeError(
                        "Maryland strict GetSections frontier omitted an article: "
                        f"{article_code}"
                    )
                section_codes = await self._list_section_codes(
                    article_value=article_value,
                    article_code=article_code,
                    budget=None,
                    sections_payload=strict_catalog_payloads[sections_url],
                )
                strict_section_codes_by_url[sections_url] = list(section_codes)
                if not section_codes:
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="maryland:empty-section-frontier",
                        force=True,
                        extra={
                            "titles_scanned": int(article_index),
                            "discovered_titles": int(len(articles_payload)),
                            "scanned_candidates": 0,
                            "discovered_candidates": int(
                                discovered_before_leaf_wave
                            ),
                            "codes_completed": 0,
                            "codes_total": 1,
                            **_closure_checkpoint_fields(),
                        },
                    )
                    raise RuntimeError(
                        "Maryland exact article exposed no section frontier: "
                        f"article={article_code}"
                    )
                discovered_before_leaf_wave += len(section_codes)
                for _section_label, section_code in section_codes:
                    if not section_code:
                        continue
                    section_url = self._canonical_fetch_url(
                        f"{self.get_base_url()}/mgawebsite/Laws/StatuteText"
                        f"?article={article_code}&section={section_code}"
                        "&enactments=false"
                    )
                    if section_url in strict_leaf_seen:
                        continue
                    strict_leaf_seen.add(section_url)
                    strict_leaf_urls.append(section_url)

            if strict_leaf_urls:
                strict_leaf_batch = (
                    await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
                        strict_leaf_urls,
                        residual_retry_attempts=residual_retry_attempts,
                        timeout_seconds=35,
                        media_type="text/html",
                        max_concurrency=section_concurrency,
                        prefer_direct=True,
                        common_crawl_domain_terms=("mgaleg.maryland.gov",),
                        common_crawl_url_terms=("/mgawebsite/Laws/StatuteText",),
                        common_crawl_mime_terms=("html",),
                        wayback_prefix_inventory=True,
                    )
                )
                aligned_lengths = {
                    len(strict_leaf_batch.urls),
                    len(strict_leaf_batch.payloads),
                    len(strict_leaf_batch.errors),
                    len(strict_leaf_batch.transport_receipts),
                    len(strict_leaf_batch.parser_input_envelopes),
                }
                if aligned_lengths != {len(strict_leaf_urls)}:
                    raise RuntimeError(
                        "Maryland section frontier returned unaligned acquisition rows"
                    )
                if list(strict_leaf_batch.urls) != strict_leaf_urls:
                    raise RuntimeError(
                        "Maryland section frontier changed URL order or identity"
                    )
                strict_leaf_batch_stats = dict(strict_leaf_batch.stats or {})
                strict_leaf_rows_by_url = {
                    url: (payload, error, receipt, envelope)
                    for url, payload, error, receipt, envelope in zip(
                        strict_leaf_batch.urls,
                        strict_leaf_batch.payloads,
                        strict_leaf_batch.errors,
                        strict_leaf_batch.transport_receipts,
                        strict_leaf_batch.parser_input_envelopes,
                        strict=True,
                    )
                }

        async def _build_one(
            *,
            article_display: str,
            section_label: str,
            section_code: str,
            section_url: str,
        ) -> NormalizedStatute | None:
            async with sem:
                return await self._build_statute_from_section_page(
                    code_name=code_name,
                    article_label=article_display,
                    section_label=section_label,
                    section_number=section_code,
                    section_url=section_url,
                )

        for article_index, article in enumerate(articles_payload, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            if not isinstance(article, dict):
                continue

            article_display = str(article.get("DisplayText") or "").strip()
            article_value = str(article.get("Value") or "").strip()
            article_code = self._extract_article_code(article_display, article_value)
            if not article_code:
                continue

            if limit is None:
                budget = None
            else:
                remaining = max(0, int(limit) - len(statutes))
                section_budget_cap = self._env_int(
                    "STATE_SCRAPER_MD_MAX_SECTION_BUDGET_PER_ARTICLE",
                    default=240,
                )
                section_budget_cap = max(40, min(2000, int(section_budget_cap or 240)))
                budget = min(max(remaining * 3, 40), section_budget_cap)
            if limit is None:
                sections_url = self._maryland_section_catalog_url(
                    article_value=article_value,
                    article_code=article_code,
                )
                if sections_url not in strict_section_codes_by_url:
                    raise RuntimeError(
                        "Maryland strict GetSections frontier omitted an article: "
                        f"{article_code}"
                    )
                section_codes = list(strict_section_codes_by_url[sections_url])
            else:
                section_codes = await self._list_section_codes(
                    article_value=article_value,
                    article_code=article_code,
                    budget=budget,
                )
            if limit is None and not section_codes:
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="maryland:empty-section-frontier",
                    force=True,
                    extra={
                        "titles_scanned": int(article_index),
                        "discovered_titles": int(len(articles_payload)),
                        "scanned_candidates": int(scanned_candidates),
                        "discovered_candidates": int(discovered_candidates),
                        "codes_completed": 0,
                        "codes_total": 1,
                        **_closure_checkpoint_fields(),
                    },
                )
                raise RuntimeError(
                    "Maryland exact article exposed no section frontier: "
                    f"article={article_code}"
                )
            discovered_candidates += int(len(section_codes))
            section_inputs: List[tuple[str, str, str, str]] = []
            for section_label, section_code in section_codes:
                if not section_code:
                    continue

                section_url = self._canonical_fetch_url(
                    f"{self.get_base_url()}/mgawebsite/Laws/StatuteText"
                    f"?article={article_code}&section={section_code}"
                    "&enactments=false"
                )
                if section_url in seen_urls:
                    continue

                seen_urls.add(section_url)
                section_inputs.append(
                    (
                        article_display,
                        section_label,
                        section_code,
                        section_url,
                    )
                )

            self.logger.info(
                "Maryland API scrape: article=%s queued_sections=%s statutes_so_far=%s",
                article_code,
                len(section_inputs),
                len(statutes),
            )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="maryland:article-scan",
                extra={
                    "titles_scanned": int(article_index),
                    "discovered_titles": int(len(articles_payload)),
                    "scanned_candidates": int(scanned_candidates),
                    "discovered_candidates": int(discovered_candidates),
                    "codes_completed": 0,
                    "codes_total": 1,
                    **_closure_checkpoint_fields(),
                },
            )

            try:
                asyncio.get_running_loop()
                parallel = True
            except RuntimeError:
                parallel = False
            for batch_start in range(0, len(section_inputs), section_batch_size):
                if limit is not None and len(statutes) >= limit:
                    break
                batch_inputs = section_inputs[batch_start : batch_start + section_batch_size]
                if limit is None:
                    batch_urls = [item[3] for item in batch_inputs]
                    try:
                        retained_rows = [
                            strict_leaf_rows_by_url[url] for url in batch_urls
                        ]
                    except KeyError as exc:
                        raise RuntimeError(
                            "Maryland unioned section frontier omitted an exact URL"
                        ) from exc
                    batch = StateLawPageMultiFetchResult(
                        urls=list(batch_urls),
                        payloads=[row[0] for row in retained_rows],
                        errors=[row[1] for row in retained_rows],
                        transport_receipts=[row[2] for row in retained_rows],
                        parser_input_envelopes=[row[3] for row in retained_rows],
                        stats=dict(strict_leaf_batch_stats),
                    )
                    aligned_lengths = {
                        len(batch.urls),
                        len(batch.payloads),
                        len(batch.errors),
                        len(batch.transport_receipts),
                        len(batch.parser_input_envelopes),
                    }
                    if aligned_lengths != {len(batch_inputs)}:
                        raise RuntimeError(
                            "Maryland section frontier returned unaligned acquisition rows"
                        )
                    if list(batch.urls) != batch_urls:
                        raise RuntimeError(
                            "Maryland section frontier changed URL order or identity"
                        )
                    batch_results = []
                    batch_unresolved: List[Dict[str, str]] = []
                    strict_evidence = (
                        getattr(self, "_state_law_acquisition_ledger", None)
                        is not None
                    )
                    for item, payload, error, receipt, envelope in zip(
                        batch_inputs,
                        batch.payloads,
                        batch.errors,
                        batch.transport_receipts,
                        batch.parser_input_envelopes,
                        strict=True,
                    ):
                        if error is not None or not payload:
                            batch_results.append(None)
                            batch_unresolved.append(
                                {
                                    "article_code": article_code,
                                    "error": str(error or "empty parser input"),
                                    "section_number": item[2],
                                    "source_url": item[3],
                                }
                            )
                            continue
                        body = bytes(payload)
                        if strict_evidence:
                            from ...legal_data.state_laws_source_provenance import (
                                StateLawTransportReceiptError,
                                canonicalize_state_law_transport_receipt,
                            )

                            try:
                                canonicalize_state_law_transport_receipt(
                                    receipt,
                                    official_url=item[3],
                                    content_sha256=hashlib.sha256(body).hexdigest(),
                                )
                            except StateLawTransportReceiptError as exc:
                                raise RuntimeError(
                                    "Maryland section frontier returned an "
                                    "unbound transport receipt"
                                ) from exc
                            if (
                                envelope is None
                                or bytes(getattr(envelope, "body", b"") or b"")
                                != body
                            ):
                                raise RuntimeError(
                                    "Maryland section frontier returned an "
                                    "unbound parser-input envelope"
                                )
                        try:
                            html_text = body.decode("utf-8", errors="ignore")
                            parsed = self._build_statute_from_section_html(
                                code_name=code_name,
                                article_label=item[0],
                                section_label=item[1],
                                section_number=item[2],
                                section_url=item[3],
                                html_text=html_text,
                            )
                            if parsed is not None:
                                normalized_identity = self._normalize_section_code(
                                    str(parsed.section_number or "")
                                )
                                expected_identity = self._normalize_section_code(item[2])
                                if normalized_identity != expected_identity:
                                    raise RuntimeError(
                                        "Maryland retained body changed its API-selected "
                                        f"identity: expected={expected_identity} "
                                        f"observed={normalized_identity}"
                                    )
                                section_reports.append(
                                    {
                                        "article_code": article_code,
                                        "canonical_identity": (
                                            f"{article_code}|{normalized_identity}"
                                        ),
                                        "content_sha256": hashlib.sha256(body).hexdigest(),
                                        "disposition": "operative",
                                        "section_label": item[1],
                                        "section_number": item[2],
                                        "source_url": item[3],
                                    }
                                )
                                batch_results.append(parsed)
                                continue

                            from .maryland_section import (
                                source_bound_maryland_terminal_disposition,
                            )

                            disposition = source_bound_maryland_terminal_disposition(
                                html_text,
                                source_url=item[3],
                                expected_article_code=article_code,
                            )
                            if disposition is not None:
                                terminal_sections.append(
                                    {
                                        "article_code": article_code,
                                        "content_sha256": hashlib.sha256(body).hexdigest(),
                                        "disposition": disposition,
                                        "section_number": item[2],
                                        "source_url": item[3],
                                    }
                                )
                                section_reports.append(
                                    {
                                        "article_code": article_code,
                                        "canonical_identity": "",
                                        "content_sha256": hashlib.sha256(body).hexdigest(),
                                        "disposition": disposition,
                                        "section_label": item[1],
                                        "section_number": item[2],
                                        "source_url": item[3],
                                    }
                                )
                                batch_results.append(None)
                                continue
                            batch_results.append(None)
                            batch_unresolved.append(
                                {
                                    "article_code": article_code,
                                    "error": (
                                        "retained body produced neither an operative "
                                        "row nor a source-bound terminal disposition"
                                    ),
                                    "section_number": item[2],
                                    "source_url": item[3],
                                }
                            )
                        except Exception as exc:
                            batch_results.append(exc)
                            batch_unresolved.append(
                                {
                                    "article_code": article_code,
                                    "error": f"{type(exc).__name__}: {exc}",
                                    "section_number": item[2],
                                    "source_url": item[3],
                                }
                            )
                elif parallel:
                    batch_jobs = [
                        _build_one(
                            article_display=item[0],
                            section_label=item[1],
                            section_code=item[2],
                            section_url=item[3],
                        )
                        for item in batch_inputs
                    ]
                    batch_results = await asyncio.gather(*batch_jobs, return_exceptions=True)
                else:
                    batch_results = []
                    for item in batch_inputs:
                        try:
                            batch_results.append(
                                await self._build_statute_from_section_page(
                                    code_name=code_name,
                                    article_label=item[0],
                                    section_label=item[1],
                                    section_number=item[2],
                                    section_url=item[3],
                                )
                            )
                        except Exception as exc:
                            batch_results.append(exc)
                for statute in batch_results:
                    scanned_candidates += 1
                    if isinstance(statute, Exception):
                        continue
                    if statute is None:
                        continue
                    if not self._is_maryland_api_record(
                        statute
                    ) and self._is_low_quality_statute_record(statute):
                        continue

                    statutes.append(statute)
                    if len(statutes) == 1 or len(statutes) % 50 == 0:
                        self.logger.info(
                            "Maryland API scrape: statutes_so_far=%s",
                            len(statutes),
                        )
                    if limit is not None and len(statutes) >= limit:
                        break

                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="maryland:section-progress",
                    extra={
                        "titles_scanned": int(article_index),
                        "discovered_titles": int(len(articles_payload)),
                        "scanned_candidates": int(scanned_candidates),
                        "discovered_candidates": int(discovered_candidates),
                        "codes_completed": 0,
                        "codes_total": 1,
                        **_closure_checkpoint_fields(
                            batch_unresolved if limit is None else None
                        ),
                    },
                )
                if limit is None and batch_unresolved:
                    first = batch_unresolved[0]
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="maryland:unresolved-section",
                        force=True,
                        extra={
                            "titles_scanned": int(article_index),
                            "discovered_titles": int(len(articles_payload)),
                            "scanned_candidates": int(scanned_candidates),
                            "discovered_candidates": int(discovered_candidates),
                            "codes_completed": 0,
                            "codes_total": 1,
                            **_closure_checkpoint_fields(batch_unresolved),
                        },
                    )
                    raise RuntimeError(
                        "Maryland exact section frontier has unresolved retained "
                        f"outcome: {first['source_url']}: {first['error']}"
                    )
                if limit is not None and len(statutes) >= limit:
                    break

        if limit is None:
            classified_candidates = len(statutes) + len(terminal_sections)
            if scanned_candidates != discovered_candidates:
                raise RuntimeError(
                    "Maryland exact frontier closure mismatch: "
                    f"discovered={discovered_candidates} scanned={scanned_candidates}"
                )
            if classified_candidates != scanned_candidates:
                raise RuntimeError(
                    "Maryland exact outcome closure mismatch: "
                    f"scanned={scanned_candidates} operative={len(statutes)} "
                    f"terminal={len(terminal_sections)}"
                )
            if len(section_reports) != scanned_candidates:
                raise RuntimeError(
                    "Maryland exact input-report closure mismatch: "
                    f"reports={len(section_reports)} scanned={scanned_candidates}"
                )
            catalog_reports: List[Dict[str, Any]] = []
            catalog_units: List[Dict[str, str]] = []
            ledger = getattr(self, "_state_law_acquisition_ledger", None)
            if callable(getattr(ledger, "replay_retained_parser_input", None)):
                catalog_reports, catalog_units = (
                    self._retained_maryland_catalog_reports()
                )
                expected_units = [
                    {
                        "article_code": str(row.get("article_code") or ""),
                        "article_display": next(
                            (
                                str(article.get("DisplayText") or "")
                                for article in articles_payload
                                if self._extract_article_code(
                                    str(article.get("DisplayText") or ""),
                                    str(article.get("Value") or ""),
                                )
                                == str(row.get("article_code") or "")
                            ),
                            "",
                        ),
                        "section_label": str(row.get("section_label") or ""),
                        "section_number": str(row.get("section_number") or ""),
                        "source_url": str(row.get("source_url") or ""),
                    }
                    for row in section_reports
                ]
                if catalog_units != expected_units:
                    raise RuntimeError(
                        "Maryland retained API catalog membership changed before closure"
                    )
            exact_frontier = self._maryland_exact_frontier(
                catalog_reports=catalog_reports,
                section_reports=section_reports,
            )
            observed_at = datetime.now(timezone.utc).isoformat()
            self._last_maryland_full_frontier = {
                "boundary_first": str(section_reports[0]["source_url"]),
                "boundary_last": str(section_reports[-1]["source_url"]),
                "catalog_reports": catalog_reports,
                "code_name": code_name,
                "frontier": exact_frontier,
                "observed_at": observed_at,
                "section_reports": section_reports,
            }

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="maryland:complete",
            force=True,
            extra={
                "scanned_candidates": int(scanned_candidates),
                "discovered_candidates": int(discovered_candidates),
                "codes_completed": 1,
                "codes_total": 1,
                **_closure_checkpoint_fields(),
            },
        )
        return statutes

    async def _build_statute_from_section_page(
        self,
        *,
        code_name: str,
        article_label: str,
        section_label: str,
        section_number: str,
        section_url: str,
    ) -> NormalizedStatute | None:
        try:
            html_text = await self._fetch_text_direct(section_url, timeout=35)
        except Exception:
            return None
        if not html_text:
            return None
        return self._build_statute_from_section_html(
            code_name=code_name,
            article_label=article_label,
            section_label=section_label,
            section_number=section_number,
            section_url=section_url,
            html_text=html_text,
        )

    def _build_statute_from_section_html(
        self,
        *,
        code_name: str,
        article_label: str,
        section_label: str,
        section_number: str,
        section_url: str,
        html_text: str,
    ) -> NormalizedStatute | None:
        """Parse one already-retained, exactly aligned official section body."""

        from .maryland_section import (
            is_statute_article_code,
            maryland_section_page_identity,
            parse_maryland_section_html,
        )

        section_query = urllib.parse.parse_qs(
            urllib.parse.urlparse(section_url).query
        )
        source_article_code = str(
            (section_query.get("article") or [""])[0] or ""
        ).strip().upper()
        caller_article_code = self._extract_article_code(article_label, "")
        if not is_statute_article_code(source_article_code.lower()):
            return None
        if caller_article_code and caller_article_code != source_article_code:
            return None
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None
        if not html_text:
            return None

        soup = BeautifulSoup(html_text, "html.parser")
        parsed = parse_maryland_section_html(
            html_text,
            source_url=section_url,
            code_name=code_name,
            expected_article_code=source_article_code,
        )
        if parsed is not None:
            return parsed
        if maryland_section_page_identity(
            html_text,
            source_url=section_url,
            expected_article_code=source_article_code,
        ) != (source_article_code, self._normalize_section_code(section_number)):
            return None
        text_node = soup.select_one("#StatuteText") or soup.select_one("#mainBody")
        if text_node is None:
            return None

        text = " ".join(text_node.get_text(" ", strip=True).split())
        text = self._MD_NEXT_TRAIL_RE.sub("", text).strip()
        if len(text) < 220:
            return None

        cite_match = self._MD_SECTION_CITE_RE.search(text)
        normalized_section = self._normalize_section_code(section_number)
        if not normalized_section and cite_match:
            normalized_section = self._normalize_section_code(cite_match.group(1))
        if not normalized_section:
            return None
        article_name = str(article_label or "").split(" - ", 1)[0].strip() or "Maryland Code"
        article_name = re.sub(r"\s*\([A-Za-z0-9]+\)\s*$", "", article_name).strip() or article_name
        article_code = source_article_code
        display_label = str(section_label or normalized_section).strip()
        section_name = f"{article_name} § {display_label}"
        statute_id = f"{code_name} [{article_code or article_name}] § {normalized_section}"
        official_cite = (
            f"Md. Code, {article_name} § {normalized_section}"
            if article_name
            else f"Md. Code § {normalized_section}"
        )

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=statute_id,
            code_name=code_name,
            section_number=normalized_section,
            section_name=section_name[:200],
            full_text=text,
            source_url=section_url,
            legal_area=self._identify_legal_area(article_name),
            official_cite=official_cite,
            metadata=StatuteMetadata(),
            structured_data={
                "skip_hydrate": True,
                "record_type": "maryland_api_section",
                "source_kind": "official_maryland_api_section_html",
                "discovery_method": "official_articles_sections_api",
                "article_name": article_name,
                "article_code": article_code,
            },
        )

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Replay retained article/section catalogs and every exact leaf."""

        first = getattr(self, "_last_maryland_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Maryland strict API frontier was not closed before output"
            )
        first_frontier = first.get("frontier")
        first_catalog_raw = first.get("catalog_reports")
        first_section_raw = first.get("section_reports")
        if (
            not isinstance(first_frontier, Mapping)
            or not isinstance(first_catalog_raw, Sequence)
            or isinstance(first_catalog_raw, (str, bytes, bytearray))
            or not first_catalog_raw
            or any(not isinstance(row, Mapping) for row in first_catalog_raw)
            or not isinstance(first_section_raw, Sequence)
            or isinstance(first_section_raw, (str, bytes, bytearray))
            or not first_section_raw
            or any(not isinstance(row, Mapping) for row in first_section_raw)
        ):
            raise RuntimeError("Maryland first exact frontier is incomplete")
        first_catalogs = [dict(row) for row in first_catalog_raw]
        first_sections = [dict(row) for row in first_section_raw]

        replay_catalogs, replay_units = self._retained_maryland_catalog_reports()
        if replay_catalogs != first_catalogs:
            raise RuntimeError("Maryland retained API catalogs changed on replay")
        expected_membership = [
            (
                str(row.get("article_code") or ""),
                str(row.get("section_label") or ""),
                str(row.get("section_number") or ""),
                str(row.get("source_url") or ""),
            )
            for row in first_sections
        ]
        replay_membership = [
            (
                row["article_code"],
                row["section_label"],
                row["section_number"],
                row["source_url"],
            )
            for row in replay_units
        ]
        if replay_membership != expected_membership:
            raise RuntimeError(
                "Maryland retained section-catalog membership changed on replay"
            )

        from .maryland_section import source_bound_maryland_terminal_disposition
        from .strict_frontier_closure import (
            replay_exact_retained_state_input,
            retain_exact_state_frontier_closure,
        )

        code_name = str(first.get("code_name") or "Maryland Code")
        replay_rows: List[NormalizedStatute] = []
        replay_sections: List[Dict[str, Any]] = []
        seen_identities: set[str] = set()
        for unit, expected in zip(replay_units, first_sections, strict=True):
            source_url = unit["source_url"]
            body = replay_exact_retained_state_input(
                self,
                official_url=source_url,
                sanitized_request={"method": "GET", "url": source_url},
                frontier_name="Maryland section frontier",
                refresh=False,
            )
            digest = hashlib.sha256(body).hexdigest()
            html = body.decode("utf-8", errors="ignore")
            statute = self._build_statute_from_section_html(
                code_name=code_name,
                article_label=unit["article_display"],
                section_label=unit["section_label"],
                section_number=unit["section_number"],
                section_url=source_url,
                html_text=html,
            )
            if statute is not None:
                normalized = self._normalize_section_code(
                    str(statute.section_number or "")
                )
                if normalized != self._normalize_section_code(unit["section_number"]):
                    raise RuntimeError(
                        "Maryland retained section changed its API-selected identity: "
                        f"{source_url}"
                    )
                identity = f"{unit['article_code']}|{normalized}"
                if identity in seen_identities:
                    raise RuntimeError(
                        "Maryland retained replay repeated an identity: "
                        f"{identity}"
                    )
                seen_identities.add(identity)
                disposition = "operative"
                replay_rows.append(statute)
            else:
                identity = ""
                disposition = source_bound_maryland_terminal_disposition(
                    html,
                    source_url=source_url,
                    expected_article_code=unit["article_code"],
                )
                if not disposition:
                    raise RuntimeError(
                        "Maryland retained replay left a section unclassified: "
                        f"{source_url}"
                    )
            report = {
                "article_code": unit["article_code"],
                "canonical_identity": identity,
                "content_sha256": digest,
                "disposition": disposition,
                "section_label": unit["section_label"],
                "section_number": unit["section_number"],
                "source_url": source_url,
            }
            if report != expected:
                raise RuntimeError(
                    "Maryland retained section report changed on replay: "
                    f"{source_url}"
                )
            replay_sections.append(report)

        replayed_frontier = self._maryland_exact_frontier(
            catalog_reports=replay_catalogs,
            section_reports=replay_sections,
        )
        observed_at = str(first.get("observed_at") or "")
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="MD",
            source_domain="mgaleg.maryland.gov",
            official_source_url=(
                f"{self.get_base_url()}/mgawebsite/api/Laws/GetArticles"
                "?enactments=false"
            ),
            observed_at=observed_at,
            legal_as_of=observed_at[:10],
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(first_sections),
            pagination_total=len(first_catalogs),
            transport={
                "fixture": False,
                "catalog_frontier_requested_pages": max(
                    0,
                    len(first_catalogs) - 1,
                ),
                "first_pass_requested_pages": (
                    len(first_sections) + len(first_catalogs)
                ),
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_json_and_html",
                "leaf_frontier_requested_pages": len(first_sections),
                "per_page_archive_loop": False,
                "retained_replay_network_requests": 0,
                "root_catalog_requested_pages": 1,
                "synthetic": False,
            },
        )

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Maryland's legislative website.

        Maryland uses JavaScript for statute search, so we use Playwright.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .maryland_constitution import (
            configured_constitution_html_path,
            parse_configured_maryland_constitution,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_configured_maryland_constitution(
                    code_name=code_name or "Maryland Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .maryland_section import configured_section_html_path, parse_maryland_section_html

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_maryland_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gcr&section=2-201&enactments=false",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        allow_justia = str(
            os.getenv("STATE_SCRAPER_MD_ALLOW_JUSTIA_FALLBACK", "0") or "0"
        ).strip().lower() in {"1", "true", "yes", "on"}

        api_statutes = await self._scrape_api_sections(code_name, max_statutes=limit)
        if api_statutes:
            if limit is None:
                return api_statutes
            else:
                return api_statutes[: int(limit)]

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct_statutes = await self._scrape_direct_seed_sections(
                code_name, max_statutes=max(1, int(limit or 2))
            )
            if direct_statutes:
                return direct_statutes if limit is None else direct_statutes[: int(limit)]

        if self._full_corpus_enabled() and max_statutes is None and not allow_justia:
            return []

        return_threshold = int(limit) if limit is not None else 160
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/mgawebsite/Laws/Statutes",
            f"{self.get_base_url()}/mgawebsite/Laws/StatuteText?article=GSG&section=1-101&enactments=false",
            f"{self.get_base_url()}/mgawebsite/Laws/StatuteText?article=GCR&section=1-101&enactments=false",
        ]
        # Secondary Justia mirrors are never sole full-corpus admission unless
        # explicitly re-enabled; bounded probes may still use them as last resort.
        if allow_justia or (not self._full_corpus_enabled()):
            candidate_urls.append("https://law.justia.com/codes/maryland/")

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                source = str(statute.source_url or "").lower()
                if self._full_corpus_enabled() and not allow_justia:
                    if "justia.com" in source or "findlaw.com" in source:
                        continue
                if not self._is_maryland_api_record(
                    statute
                ) and self._is_low_quality_statute_record(statute):
                    continue
                merged_keys.add(key)
                merged.append(statute)

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            if (
                self._full_corpus_enabled()
                and not allow_justia
                and ("justia.com" in str(candidate).lower() or "findlaw.com" in str(candidate).lower())
            ):
                continue

            try:
                statutes = await self._playwright_scrape(
                    code_name,
                    candidate,
                    "Md. Code Ann.",
                    wait_for_selector="a[href*='statute'], a[href*='laws'], .article-link",
                    timeout=45000,
                    wait_until="domcontentloaded",
                    max_sections=max(10, return_threshold),
                )
            except Exception:
                statutes = []

            _merge(statutes)
            if limit is not None and len(merged) >= int(limit):
                return merged[: int(limit)]

            try:
                generic = await self._generic_scrape(
                    code_name, candidate, "Md. Code Ann.", max_sections=max(10, return_threshold)
                )
            except Exception:
                generic = []

            _merge(generic)
            if limit is not None and len(merged) >= int(limit):
                return merged[: int(limit)]

        return merged if limit is None else merged[: int(limit)]

    async def _scrape_direct_seed_sections(
        self, code_name: str, max_statutes: int
    ) -> List[NormalizedStatute]:
        seeds = [
            ("State Government", "GSG", "1-101"),
            ("Criminal Law", "GCR", "1-101"),
        ]
        out: List[NormalizedStatute] = []
        for article_label, article_code, section_code in seeds[: max(1, int(max_statutes or 1))]:
            section_url = (
                f"{self.get_base_url()}/mgawebsite/Laws/StatuteText"
                f"?article={article_code}&section={section_code}&enactments=false"
            )
            statute = await self._build_statute_from_section_page(
                code_name=code_name,
                article_label=article_label,
                section_label=section_code,
                section_number=section_code,
                section_url=section_url,
            )
            if statute is not None:
                out.append(statute)
        return out

    def _official_ssl_context(self, *, unverified: bool = False):
        import ssl

        if unverified:
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    def _official_http_get(self, url: str, timeout: int = 20) -> tuple[bytes, bytes, bytes]:
        """Fetch one official Maryland URL and retain request/response/body bytes."""
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
            "accept: application/json,text/html;q=0.9,*/*;q=0.8\n"
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ipfs-datasets-open-us-law-maryland/1.0",
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
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
            raise RuntimeError(f"official Maryland GET failed for {url}: {last_exc}") from last_exc
        if status != 200 or not body:
            raise RuntimeError(f"official Maryland GET returned HTTP {status} for {url}")
        response_bytes = f"HTTP/1.1 {status} OK\n{header_block}\n".encode("utf-8") + body
        return request_bytes, response_bytes, body

    def _parse_official_article_index(self, payload: object) -> List[Dict[str, str]]:
        """Parse every official Maryland Code article from the live articles API."""
        if not isinstance(payload, list):
            raise RuntimeError("official Maryland GetArticles payload is not a list")
        units: List[Dict[str, str]] = []
        seen: set[str] = set()
        for article in payload:
            if not isinstance(article, dict):
                continue
            display = str(article.get("DisplayText") or "").strip()
            value = str(article.get("Value") or "").strip()
            article_code = self._extract_article_code(display, value)
            if not article_code or article_code in seen:
                continue
            seen.add(article_code)
            source_url = (
                f"{self.get_base_url()}/mgawebsite/Laws/Statutes"
                f"?article={urllib.parse.quote(value or article_code)}"
            )
            label = display or f"Article {article_code}"
            units.append(
                {
                    "canonical_key": f"md:article-{article_code.lower()}",
                    "source_url": source_url,
                    "label": label,
                    "text": (
                        f"Maryland Code {label} official article index entry "
                        f"retained from {source_url}"
                    ),
                }
            )
        return units

    def fetch_official(self, code: str = "MD"):
        """Acquire the uncapped official Maryland article frontier."""
        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or self.state_code or "MD").strip().upper()
        if normalized != "MD":
            raise ValueError(f"MarylandScraper cannot acquire {normalized}")
        index_url = f"{self.get_base_url()}/mgawebsite/api/Laws/GetArticles?enactments=false"
        request_bytes, response_bytes, index_body = self._official_http_get(index_url)
        try:
            payload = json.loads(index_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("official Maryland GetArticles payload is not JSON") from exc
        units = self._parse_official_article_index(payload)
        if len(units) < 3:
            raise RuntimeError(
                f"official Maryland article index is incomplete: {len(units)} units"
            )
        rows = tuple(
            {
                "canonical_key": unit["canonical_key"],
                "source_url": unit["source_url"],
                "text": unit["text"],
            }
            for unit in units
        )
        catalog = "\n".join(
            f"{unit['canonical_key']}\t{unit['source_url']}\t{unit['label']}"
            for unit in units
        ).encode("utf-8")
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
            jurisdiction_code="MD",
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            body_bytes=catalog,
            source_domain="mgaleg.maryland.gov",
            source_path="/mgawebsite/Laws/Statutes",
            frontier=frontier,
            rows=rows,
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=rows[0]["canonical_key"],
            last_hierarchy_unit=rows[-1]["canonical_key"],
        )


# Register this scraper with the registry
StateScraperRegistry.register("MD", MarylandScraper)
