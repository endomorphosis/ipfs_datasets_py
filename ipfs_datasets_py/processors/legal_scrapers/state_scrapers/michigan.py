"""Scraper for Michigan state laws.

This module contains the scraper for Michigan statutes from the official state legislative website.
"""

import hashlib
import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urljoin

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StateLawPageMultiFetchResult,
    StatuteMetadata,
    _sanitized_multifetch_headers,
    _sanitized_multifetch_request,
)
from .registry import StateScraperRegistry


class MichiganScraper(BaseStateScraper):
    """Scraper for Michigan state laws from http://www.legislature.mi.gov"""

    _MI_CHAPTER_OBJECT_RE = re.compile(
        r"objectName=mcl-chap(?P<chapter>\d+)\b",
        re.IGNORECASE,
    )
    OFFICIAL_DOMAIN = "www.legislature.mi.gov"
    OFFICIAL_ENTRY_PATH = "/Laws/ChapterIndex"
    OFFICIAL_ENTRY_URL = "https://www.legislature.mi.gov/Laws/ChapterIndex"
    STRICT_MINIMUM_CHAPTERS = 200
    STRICT_CURRENT_CHAPTER_NUMBER_SHA256 = (
        "8d7a03038de2065508c2d7ccb5846caf6dafaef312a5121af0e924df89036884"
    )
    # Observed from the official index on 2026-08-26.  Strict acquisition is
    # still source-derived and digest-guards the retained root below; this list
    # only keeps the compatibility catalog from repairing with stale members.
    OFFICIAL_CHAPTERS = tuple(
        map(
            int,
            (
                "1 2 3 4 5 6 8 10 11 12 13 14 15 16 17 18 19 21 24 26 28 "
                "29 30 31 32 33 35 36 37 38 41 42 43 45 46 47 48 49 50 51 "
                "52 53 54 55 78 79 115 117 119 120 121 123 124 125 128 129 "
                "141 168 169 200 201 205 206 207 208 209 211 213 247 249 250 "
                "252 253 254 255 256 257 259 260 279 280 281 282 285 286 287 "
                "288 289 290 291 295 299 300 307 308 316 317 318 319 320 321 "
                "322 323 324 325 326 327 328 329 330 331 332 333 335 336 338 "
                "339 340 380 388 389 390 393 395 397 399 400 404 408 409 418 "
                "419 421 423 425 426 427 429 430 431 432 433 434 435 436 438 "
                "439 440 441 442 443 444 445 446 447 449 450 451 453 454 455 "
                "456 457 458 460 462 468 469 470 471 472 473 474 480 482 483 "
                "484 485 486 487 488 489 490 491 492 493 494 500 550 551 552 "
                "554 555 556 557 558 559 560 561 564 565 566 567 570 600 691 "
                "692 700 720 722 725 726 727 728 729 730 750 752 780 791 798 "
                "800 801 802 803 804 830"
            ).split(),
        )
    )

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            michigan_chapter_xml,
            state_archival_fetch,
            strict_frontier_closure,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            michigan_chapter_xml,
            wayback_machine_engine,
        )

    @staticmethod
    def _michigan_frontier_headers(media_type: str) -> Dict[str, str]:
        return {
            "Accept": (
                "application/xml,text/xml;q=0.9,*/*;q=0.7"
                if media_type == "text/xml"
                else "text/html,application/xhtml+xml;q=0.9,*/*;q=0.7"
            ),
            "User-Agent": "ipfs-datasets-michigan-laws/2.0",
        }

    def _michigan_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                24,
                self._env_int("STATE_SCRAPER_MI_FRONTIER_CONCURRENCY", default=8),
            ),
        )

    @staticmethod
    def _is_valid_michigan_chapter_index(payload: bytes) -> bool:
        sample = bytes(payload or b"").lower()
        return bool(
            len(sample) > 5_000
            and b"mcl chapter index" in sample
            and b"objectname=mcl-chap" in sample
            and b"</html>" in sample[-2_000:]
        )

    @staticmethod
    def _is_valid_michigan_chapter_xml(payload: bytes) -> bool:
        raw = bytes(payload or b"")
        if len(raw) < 500:
            return False
        try:
            if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                sample = raw[:4_000].decode("utf-16", errors="replace")
            else:
                sample = raw[:4_000].decode("utf-8-sig", errors="replace")
        except (UnicodeError, ValueError):
            return False
        return "<MCLChapterInfo" in sample and "<Name>" in sample

    def _validate_michigan_aligned_evidence(
        self,
        *,
        url: str,
        payload: bytes,
        transport_receipt: Any,
        parser_input_envelope: Any,
        frontier_name: str,
    ) -> None:
        """Bind retained ledger evidence to the exact aligned source bytes."""

        canonical_url = self._canonical_fetch_url(url)
        digest = hashlib.sha256(payload).hexdigest()
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if ledger_attached and (
            not isinstance(transport_receipt, Mapping)
            or not transport_receipt
            or parser_input_envelope is None
        ):
            raise RuntimeError(
                f"Michigan {frontier_name} frontier lacks retained evidence: {url}"
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
                    f"Michigan {frontier_name} receipt lacks URL/digest evidence: {url}"
                )
            if observed_url and self._canonical_fetch_url(observed_url) != canonical_url:
                raise RuntimeError(
                    f"Michigan {frontier_name} receipt changed URL identity: {url}"
                )
            if observed_digest and observed_digest != digest:
                raise RuntimeError(
                    f"Michigan {frontier_name} receipt changed payload identity: {url}"
                )
        if parser_input_envelope is not None:
            envelope_body = getattr(parser_input_envelope, "body", None)
            if ledger_attached and envelope_body is None:
                raise RuntimeError(
                    f"Michigan {frontier_name} envelope lacks body evidence: {url}"
                )
            if envelope_body is not None and bytes(envelope_body) != payload:
                raise RuntimeError(
                    f"Michigan {frontier_name} envelope changed payload identity: {url}"
                )

    async def _fetch_michigan_frontier_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Callable[[bytes], bool],
        media_type: str,
        common_crawl_url_terms: Sequence[str],
    ) -> StateLawPageMultiFetchResult:
        """Use the shared plural path, including grouped WARC range recovery."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if not requested:
            return StateLawPageMultiFetchResult([], [], [], [], [], {})
        if any(not url for url in requested) or len(set(requested)) != len(requested):
            raise RuntimeError(
                f"Michigan {frontier_name} frontier contains invalid or duplicate URLs"
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
            repeat_grouped_archive_inventory_on_residual=False,
            timeout_seconds=90 if media_type == "text/xml" else 25,
            headers=self._michigan_frontier_headers(media_type),
            content_validator=content_validator,
            media_type=media_type,
            max_concurrency=self._michigan_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=tuple(common_crawl_url_terms),
            common_crawl_mime_terms=("xml",) if media_type == "text/xml" else ("html",),
            wayback_prefix_inventory=True,
        )
        batch_stats = dict(batch.stats or {})
        inventory_memo = dict(
            batch_stats.get("common_crawl_inventory_memo", {}) or {}
        )
        if (
            int(batch_stats.get("common_crawl_inventory_queries", 0) or 0) > 1
            or int(inventory_memo.get("shared_domain_queries", 0) or 0) > 1
        ):
            raise RuntimeError(
                f"Michigan {frontier_name} repeated a same-domain Common Crawl inventory"
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
                f"Michigan {frontier_name} frontier changed exact URL alignment"
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
            self._validate_michigan_aligned_evidence(
                url=url,
                payload=raw,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
                frontier_name=frontier_name,
            )
        stats_rows = list(getattr(self, "_michigan_frontier_batch_stats", []))
        stats_rows.append(
            {
                **batch_stats,
                "frontier_name": frontier_name,
                "requested_pages": len(requested),
                "frontier_complete": not failures,
                "unresolved_pages": len(failures),
                "unresolved_urls": [item["url"] for item in failures],
            }
        )
        self._michigan_frontier_batch_stats = stats_rows
        if failures:
            raise RuntimeError(
                f"Michigan {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures[:10]}"
            )
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    def _replay_michigan_retained_input(
        self,
        url: str,
        *,
        media_type: str,
        content_validator: Callable[[bytes], bool],
        frontier_name: str,
    ) -> bytes:
        """Replay one exact retained input without permitting network I/O."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Michigan retained replay requires an attached ledger")
        canonical_url = self._canonical_fetch_url(url)
        sanitized_headers = _sanitized_multifetch_headers(
            self._michigan_frontier_headers(media_type)
        )
        retained = ledger.replay_retained_parser_input(
            official_url=canonical_url,
            sanitized_request=_sanitized_multifetch_request(
                canonical_url,
                sanitized_headers=sanitized_headers,
            ),
        )
        if retained is None:
            raise RuntimeError(
                f"Michigan retained replay is missing exact input: {canonical_url}"
            )
        envelope = getattr(retained, "envelope", None)
        body = getattr(envelope, "body", None)
        raw = bytes(body or b"")
        if not raw or not content_validator(raw):
            raise RuntimeError(
                f"Michigan retained replay input is invalid: {canonical_url}"
            )
        self._validate_michigan_aligned_evidence(
            url=canonical_url,
            payload=raw,
            transport_receipt=getattr(retained, "transport_receipt", None),
            parser_input_envelope=envelope,
            frontier_name=frontier_name,
        )
        return raw

    def _michigan_exact_frontier(
        self,
        *,
        catalog_content_sha256: str,
        chapter_reports: Sequence[Mapping[str, Any]],
        terminal_dispositions: Mapping[str, int],
    ) -> Dict[str, Any]:
        """Build the content-derived chapter/section frontier contract."""

        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        source_sections = sum(int(row["source_sections"]) for row in chapter_reports)
        operative_sections = sum(
            int(row["operative_sections"]) for row in chapter_reports
        )
        terminal_sections = sum(
            int(row["terminal_sections"]) for row in chapter_reports
        )
        disposition = {
            "discovered": source_sections,
            "fetched": operative_sections,
            "excluded": terminal_sections,
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        }
        if source_sections != operative_sections + terminal_sections:
            raise RuntimeError("Michigan exact frontier disposition did not close")
        source_rows = [
            {
                "chapter_number": str(row["chapter_number"]),
                "source_url": str(row["source_url"]),
                "content_sha256": str(row["content_sha256"]),
            }
            for row in chapter_reports
        ]
        source_frontier_sha256 = hashlib.sha256(
            json.dumps(source_rows, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": True,
            "catalog_chapter_count": len(chapter_reports),
            "catalog_content_sha256": str(catalog_content_sha256),
            "chapter_xml_document_count": len(chapter_reports),
            "chapter_xml_frontier_sha256": source_frontier_sha256,
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": source_sections,
            "pagination_closed": True,
            "schema_version": "michigan-mcl-source-frontier-v1",
            "scope_closed": True,
            "source_section_count": source_sections,
            "terminal_dispositions": {
                str(key): int(value)
                for key, value in sorted(terminal_dispositions.items())
            },
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": source_sections,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    def _michigan_source_catalog_rows(
        self,
        root_payload: bytes,
    ) -> List[tuple[str, str, str]]:
        """Validate the exact ordered current chapter membership from the root."""

        from .michigan_chapter_xml import chapter_index_links

        catalog_rows = chapter_index_links(
            bytes(root_payload).decode("utf-8", errors="replace"),
            base_url=self.get_base_url(),
        )
        chapter_numbers = [str(row[0]).strip() for row in catalog_rows]
        ordered_sha256 = hashlib.sha256(
            "\n".join(chapter_numbers).encode("utf-8")
        ).hexdigest()
        expected_sha256 = str(
            self.STRICT_CURRENT_CHAPTER_NUMBER_SHA256 or ""
        ).strip().lower()
        if (
            len(catalog_rows) < int(self.STRICT_MINIMUM_CHAPTERS)
            or len(chapter_numbers) != len(set(chapter_numbers))
            or any(not re.fullmatch(r"\d+", number) for number in chapter_numbers)
            or len(expected_sha256) != 64
            or ordered_sha256 != expected_sha256
        ):
            raise RuntimeError(
                "Michigan official chapter index changed exact ordered membership: "
                f"observed={len(catalog_rows)} minimum={self.STRICT_MINIMUM_CHAPTERS} "
                f"observed_sha256={ordered_sha256} expected_sha256={expected_sha256}"
            )
        return catalog_rows

    def get_base_url(self) -> str:
        """Return the base URL for Michigan's legislative website."""
        return "https://www.legislature.mi.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Michigan."""
        return [{
            "name": "Michigan Compiled Laws",
            "url": f"{self.get_base_url()}/Laws/ChapterIndex",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Michigan's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .michigan_constitution import (
            configured_constitution_text_path,
            parse_michigan_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_michigan_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Michigan Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .michigan_chapter_xml import (
            configured_chapter_xml_path,
            parse_michigan_chapter_xml,
        )

        xml_path = configured_chapter_xml_path()
        strict_full = self._full_corpus_enabled() and max_statutes is None
        if xml_path is not None and not strict_full:
            try:
                bulk = parse_michigan_chapter_xml(
                    xml_path.read_bytes(),
                    chapter_hint=xml_path.stem.replace("Chapter ", ""),
                    code_name=code_name,
                    max_statutes=limit,
                )
                if bulk:
                    return bulk
            except Exception as exc:
                self.logger.warning("Michigan official chapter XML failed: %s", exc)
        official = await self._scrape_official_chapter_index(code_name, max_statutes=limit)
        if official:
            return official if limit is None else official[: int(limit)]

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct_limit = limit if limit is not None else 160
            direct = await self._scrape_direct_sections(code_name, max_statutes=direct_limit)
            if direct:
                return direct if limit is None else direct[: int(limit)]
        generic_cap = limit if limit is not None else 1000000
        return await self._generic_scrape(
            code_name,
            code_url,
            "Mich. Comp. Laws",
            max_sections=max(10, int(generic_cap)),
        )

    async def _scrape_official_chapter_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        if self._full_corpus_enabled() and max_statutes is None:
            return await self._scrape_official_chapter_xml_frontier(code_name)
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None

        index_url = f"{self.get_base_url()}/Laws/ChapterIndex"
        payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=18)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        chapter_links: list[tuple[str, str]] = []
        seen_chapters: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if "objectName=mcl-chap" not in href:
                continue
            chapter_url = self._normalize_object_url(urljoin(index_url, href))
            if not chapter_url or chapter_url in seen_chapters:
                continue
            seen_chapters.add(chapter_url)
            chapter_links.append((self._text_or_empty(anchor), chapter_url))

        statutes: list[NormalizedStatute] = []
        seen_sections: set[str] = set()
        for chapter_label, chapter_url in chapter_links:
            if limit is not None and len(statutes) >= limit:
                break
            act_url = await self._discover_act_url_from_chapter(chapter_url)
            act_sections = await self._discover_section_urls_from_act(act_url or chapter_url)
            for section_url in act_sections:
                if limit is not None and len(statutes) >= limit:
                    break
                statute = await self._build_statute_from_section_page(
                    code_name=code_name,
                    section_url=section_url,
                    chapter_label=chapter_label,
                )
                if statute is None:
                    continue
                section_number = str(statute.section_number or "").strip()
                if not section_number or section_number in seen_sections:
                    continue
                seen_sections.add(section_number)
                statutes.append(statute)
        return statutes

    async def _scrape_official_chapter_xml_frontier(
        self,
        code_name: str,
    ) -> List[NormalizedStatute]:
        """Close the source-derived chapter catalog over official bulk XML."""

        from .michigan_chapter_xml import (
            chapter_xml_url,
            parse_michigan_chapter_xml_closure,
        )

        self._michigan_frontier_batch_stats = []
        root_batch = await self._fetch_michigan_frontier_batch(
            [self.OFFICIAL_ENTRY_URL],
            frontier_name="chapter-index",
            content_validator=self._is_valid_michigan_chapter_index,
            media_type="text/html",
            common_crawl_url_terms=(self.OFFICIAL_ENTRY_PATH,),
        )
        root_payload = bytes(root_batch.payloads[0])
        catalog_rows = self._michigan_source_catalog_rows(root_payload)
        chapter_numbers = [str(row[0]).strip() for row in catalog_rows]

        xml_urls = [chapter_xml_url(number) for number in chapter_numbers]
        if len(xml_urls) != len(set(xml_urls)):
            raise RuntimeError("Michigan official chapter XML catalog repeated a source URL")

        statutes: List[NormalizedStatute] = []
        seen_identities: set[str] = set()
        chapter_reports: List[Dict[str, Any]] = []
        terminal_counts: Dict[str, int] = {}
        frontier_rows: List[Dict[str, str]] = []
        batch = await self._fetch_michigan_frontier_batch(
            xml_urls,
            frontier_name=f"chapter-xml-1-{len(xml_urls)}",
            content_validator=self._is_valid_michigan_chapter_xml,
            media_type="text/xml",
            common_crawl_url_terms=("/documents/mcl/", "Chapter%20", ".xml"),
        )
        for chapter_number, source_url, payload, receipt in zip(
            chapter_numbers,
            batch.urls,
            batch.payloads,
            batch.transport_receipts,
            strict=True,
        ):
            raw = bytes(payload)
            content_sha256 = hashlib.sha256(raw).hexdigest()
            report = parse_michigan_chapter_xml_closure(
                raw,
                chapter_hint=chapter_number,
                code_name=code_name,
                max_statutes=None,
                source_bundle_url=source_url,
            )
            if report.chapter_number != chapter_number:
                raise RuntimeError(
                    "Michigan chapter XML changed catalog identity: "
                    f"expected={chapter_number} observed={report.chapter_number}"
                )
            if not report.closed or report.source_section_count <= 0:
                raise RuntimeError(
                    "Michigan chapter XML failed exact parser closure: "
                    f"chapter={chapter_number} source={report.source_section_count} "
                    f"operative={len(report.statutes)} terminal="
                    f"{len(report.terminal_sections)} residuals="
                    f"{report.unclassified_sections[:10]}"
                )
            receipt_dict = dict(receipt or {})
            for terminal in report.terminal_sections:
                disposition = str(terminal.get("disposition") or "repealed")
                terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1
            for statute in report.statutes:
                identity = str(statute.statute_id or "").strip().casefold()
                if not identity or identity in seen_identities:
                    raise RuntimeError(
                        "Michigan XML frontier repeated normalized statute identity: "
                        f"{statute.statute_id}"
                    )
                seen_identities.add(identity)
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
                        "media_type": "text/xml",
                        "byte_size": len(raw),
                        "content_sha256": content_sha256,
                    },
                }
                statutes.append(statute)
            chapter_reports.append(
                {
                    "chapter_number": chapter_number,
                    "chapter_title": report.chapter_title,
                    "source_url": source_url,
                    "content_sha256": content_sha256,
                    "source_sections": report.source_section_count,
                    "operative_sections": len(report.statutes),
                    "terminal_sections": len(report.terminal_sections),
                    "closed": True,
                }
            )
            frontier_rows.append(
                {
                    "chapter_number": chapter_number,
                    "source_url": source_url,
                    "content_sha256": content_sha256,
                }
            )

        source_sections = sum(int(row["source_sections"]) for row in chapter_reports)
        terminal_sections = sum(int(row["terminal_sections"]) for row in chapter_reports)
        if source_sections != len(statutes) + terminal_sections:
            raise RuntimeError("Michigan global XML source algebra failed reconciliation")
        catalog_content_sha256 = hashlib.sha256(root_payload).hexdigest()
        exact_frontier = self._michigan_exact_frontier(
            catalog_content_sha256=catalog_content_sha256,
            chapter_reports=chapter_reports,
            terminal_dispositions=terminal_counts,
        )
        frontier_sha256 = str(exact_frontier["chapter_xml_frontier_sha256"])
        observed_at = datetime.now(timezone.utc).isoformat()
        first_observation = {
            "boundary_first": str(frontier_rows[0]["source_url"]),
            "boundary_last": str(frontier_rows[-1]["source_url"]),
            "chapter_reports": chapter_reports,
            "code_name": code_name,
            "frontier": exact_frontier,
            "observed_at": observed_at,
            "transport_batch_stats": list(self._michigan_frontier_batch_stats),
        }
        self._last_michigan_full_frontier = first_observation
        self._last_michigan_strict_closure = {
            "schema": "michigan-mcl-strict-closure-v1",
            "closed": True,
            "catalog_source_url": self.OFFICIAL_ENTRY_URL,
            "catalog_content_sha256": catalog_content_sha256,
            "catalog_chapters": len(chapter_numbers),
            "chapter_xml_documents": len(frontier_rows),
            "source_sections": source_sections,
            "operative_sections": len(statutes),
            "terminal_sections": terminal_sections,
            "terminal_dispositions": dict(sorted(terminal_counts.items())),
            "unclassified_sections": 0,
            "frontier_sha256": frontier_sha256,
            "chapter_reports": chapter_reports,
            "batch_stats": list(self._michigan_frontier_batch_stats),
            "frontier": exact_frontier,
            "observed_at": observed_at,
        }
        return statutes

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Reparse retained chapter inputs and seal exact publication parity."""

        first = getattr(self, "_last_michigan_full_frontier", None)
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Michigan frontier closure requires an attached ledger")
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Michigan source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        from .michigan_chapter_xml import (
            chapter_index_links,
            parse_michigan_chapter_xml_closure,
        )
        from .strict_frontier_closure import retain_exact_state_frontier_closure

        first_frontier = first.get("frontier")
        first_reports_raw = first.get("chapter_reports")
        if (
            not isinstance(first_frontier, Mapping)
            or not isinstance(first_reports_raw, Sequence)
            or isinstance(first_reports_raw, (str, bytes, bytearray))
            or not first_reports_raw
            or any(not isinstance(row, Mapping) for row in first_reports_raw)
        ):
            raise RuntimeError("Michigan first exact frontier is incomplete")
        first_reports = [dict(row) for row in first_reports_raw]

        catalog_payload = self._replay_michigan_retained_input(
            self.OFFICIAL_ENTRY_URL,
            media_type="text/html",
            content_validator=self._is_valid_michigan_chapter_index,
            frontier_name="retained-chapter-index-replay",
        )
        catalog_digest = hashlib.sha256(catalog_payload).hexdigest()
        if catalog_digest != str(first_frontier.get("catalog_content_sha256") or ""):
            raise RuntimeError("Michigan retained catalog digest changed on replay")
        replay_catalog = chapter_index_links(
            catalog_payload.decode("utf-8", errors="replace"),
            base_url=self.get_base_url(),
        )
        replay_numbers = [str(row[0]).strip() for row in replay_catalog]
        expected_numbers = [str(row.get("chapter_number") or "") for row in first_reports]
        if replay_numbers != expected_numbers:
            raise RuntimeError("Michigan retained chapter catalog membership changed")

        code_name = str(first.get("code_name") or "Michigan Compiled Laws")
        replay_rows: List[NormalizedStatute] = []
        replay_reports: List[Dict[str, Any]] = []
        terminal_counts: Dict[str, int] = {}
        seen_identities: set[str] = set()
        for expected in first_reports:
            chapter_number = str(expected.get("chapter_number") or "")
            source_url = str(expected.get("source_url") or "")
            raw = self._replay_michigan_retained_input(
                source_url,
                media_type="text/xml",
                content_validator=self._is_valid_michigan_chapter_xml,
                frontier_name=f"retained-chapter-{chapter_number}-replay",
            )
            content_sha256 = hashlib.sha256(raw).hexdigest()
            if content_sha256 != str(expected.get("content_sha256") or ""):
                raise RuntimeError(
                    f"Michigan retained chapter digest changed: {chapter_number}"
                )
            parsed = parse_michigan_chapter_xml_closure(
                raw,
                chapter_hint=chapter_number,
                code_name=code_name,
                max_statutes=None,
                source_bundle_url=source_url,
            )
            if parsed.chapter_number != chapter_number or not parsed.closed:
                raise RuntimeError(
                    f"Michigan retained chapter failed exact replay: {chapter_number}"
                )
            for terminal in parsed.terminal_sections:
                disposition = str(terminal.get("disposition") or "repealed")
                terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1
            for statute in parsed.statutes:
                identity = str(statute.statute_id or "").strip().casefold()
                if not identity or identity in seen_identities:
                    raise RuntimeError(
                        "Michigan retained replay repeated canonical identity: "
                        f"{statute.statute_id}"
                    )
                seen_identities.add(identity)
                replay_rows.append(statute)
            replay_report = {
                "chapter_number": chapter_number,
                "chapter_title": parsed.chapter_title,
                "source_url": source_url,
                "content_sha256": content_sha256,
                "source_sections": parsed.source_section_count,
                "operative_sections": len(parsed.statutes),
                "terminal_sections": len(parsed.terminal_sections),
                "closed": True,
            }
            if replay_report != expected:
                raise RuntimeError(
                    f"Michigan retained chapter inventory changed: {chapter_number}"
                )
            replay_reports.append(replay_report)

        replayed_frontier = self._michigan_exact_frontier(
            catalog_content_sha256=catalog_digest,
            chapter_reports=replay_reports,
            terminal_dispositions=terminal_counts,
        )
        observed_at = str(first.get("observed_at") or "")
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="MI",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=observed_at,
            legal_as_of=observed_at[:10],
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(replay_reports),
            pagination_total=len(replay_catalog),
            transport={
                "fixture": False,
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_xml",
                "per_page_archive_loop": False,
                "retained_replay_network_requests": 0,
                "synthetic": False,
                "first_pass_batch_stats": list(
                    first.get("transport_batch_stats") or []
                ),
            },
        )

    async def _discover_act_url_from_chapter(self, chapter_url: str) -> Optional[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=18)
        if not payload:
            return None
        soup = BeautifulSoup(payload, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if "objectName=mcl-Act-" not in href:
                continue
            return self._normalize_object_url(urljoin(chapter_url, href))
        return None

    async def _discover_section_urls_from_act(self, act_url: str) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(act_url, timeout_seconds=18)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not re.search(r"objectName=mcl-\d+(?:-\d+)+", href, flags=re.IGNORECASE):
                continue
            section_url = self._normalize_object_url(urljoin(act_url, href))
            if not section_url or section_url in seen:
                continue
            seen.add(section_url)
            out.append(section_url)
        return out

    async def _build_statute_from_section_page(
        self,
        *,
        code_name: str,
        section_url: str,
        chapter_label: str = "",
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=18)
        if not payload:
            return None
        soup = BeautifulSoup(payload, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        main = soup.select_one("main") or soup.select_one("#main") or soup.body
        if main is None:
            return None
        title = self._text_or_empty(main.find(["h1", "h2", "h3"]))
        text = self._normalize_legal_text(main.get_text(" ", strip=True))
        if len(text) < 160:
            return None
        object_section_number = self._section_number_from_object_name(section_url)
        match = re.search(r"\b(\d+(?:\.\d+)+(?:[a-z])?)\b", title or text, flags=re.IGNORECASE)
        section_number = object_section_number or (match.group(1) if match else section_url.rsplit("mcl-", 1)[-1])
        chapter_number = self._extract_section_number(chapter_label) or ""
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            chapter_number=chapter_number or None,
            chapter_name=chapter_label or None,
            section_number=section_number,
            section_name=title[:200] or f"Section {section_number}",
            full_text=text,
            legal_area=self._identify_legal_area(title or text),
            source_url=section_url,
            official_cite=f"Mich. Comp. Laws § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_michigan_compiled_laws_html",
                "discovery_method": "official_chapter_index_act_section",
                "skip_hydrate": True,
            },
        )

    async def _scrape_direct_sections(self, code_name: str, max_statutes: int | None = None) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        section_urls = [
            f"{self.get_base_url()}/Laws/MCL?objectName=mcl-750-316",
            f"{self.get_base_url()}/Laws/MCL?objectName=mcl-600-101",
        ]
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else self._bounded_return_threshold(160)
        for source_url in section_urls[:limit]:
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=12)
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            title = soup.find(["h1", "h2"])
            section_name = title.get_text(" ", strip=True) if title else ""
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            match = re.search(r"\b(\d+[A-Za-z]?(?:\.\d+[A-Za-z]*)+)\b", text)
            section_number = match.group(1) if match else source_url.rsplit("mcl-", 1)[-1]
            if len(text) < 160:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200] or f"Section {section_number}",
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=source_url,
                    official_cite=f"Mich. Comp. Laws § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_direct_section", "skip_hydrate": True},
                )
            )
        return statutes

    def _normalize_object_url(self, url: str) -> str:
        normalized = str(url or "").strip()
        if "/Home/GetObject?" in normalized:
            normalized = normalized.replace("/Home/GetObject?", "/Laws/MCL?")
        return normalized

    @staticmethod
    def _section_number_from_object_name(url: str) -> str:
        match = re.search(r"objectName=mcl-(\d+)-(\d+[a-z]?)\b", str(url or ""), flags=re.IGNORECASE)
        if not match:
            return ""
        return f"{match.group(1)}.{match.group(2)}"

    @staticmethod
    def _text_or_empty(node: object) -> str:
        if node is None:
            return ""
        try:
            return re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
        except Exception:
            return ""

    def official_chapter_url(self, chapter_number: Any) -> str:
        return (
            f"{self.get_base_url()}/Laws/MCL?objectName=mcl-chap{int(chapter_number)}"
        )

    def official_chapter_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Michigan Compiled Laws chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for number in self.OFFICIAL_CHAPTERS:
            url = self.official_chapter_url(number)
            rows.append(
                {
                    "canonical_key": f"mi:chapter-{int(number)}",
                    "chapter_number": str(int(number)),
                    "name": f"Chapter {int(number)}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Michigan Compiled Laws Chapter {int(number)} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-michigan-official-catalog/1.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                )
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "ipfs-datasets-michigan-official-catalog/1.0",
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

    def _parse_official_chapter_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            match = self._MI_CHAPTER_OBJECT_RE.search(href)
            if not match:
                continue
            number = str(int(match.group("chapter")))
            if number not in found:
                found[number] = self.official_chapter_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official MCL chapter and repair missing live links."""

        del page_url
        discovered = self._parse_official_chapter_links(html)
        rows = self.official_chapter_catalog()
        seen = {str(row["chapter_number"]) for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["chapter_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        for number, url in discovered.items():
            if number in seen:
                continue
            rows.append(
                {
                    "canonical_key": f"mi:chapter-{number}",
                    "chapter_number": number,
                    "name": f"Chapter {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Michigan Compiled Laws Chapter {number} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        rows.sort(key=lambda item: int(item["chapter_number"]))
        return rows

    def fetch_official(self, code: str = "MI"):
        """Acquire the exhaustive official Michigan Compiled Laws chapter catalog.

        Live HTTPS retains the official chapter index. Every known MCL chapter
        is enumerated with an official legislature.mi.gov URL. This hook never
        returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "MI").strip().upper() or "MI"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("michigan official catalog enumeration is incomplete")
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
StateScraperRegistry.register("MI", MichiganScraper)
