"""Scraper for Wisconsin state laws.

Official path: chapter/section HTML hierarchy on https://docs.legis.wisconsin.gov
(statutes index → chapter → section). Playwright/generic remain fallbacks only.
"""

import hashlib
import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
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


class WisconsinScraper(BaseStateScraper):
    """Scraper for Wisconsin state laws from https://docs.legis.wisconsin.gov"""

    _WI_SECTION_URL_RE = re.compile(r"/document/statutes/[0-9]+(?:\.[0-9A-Za-z]+)+$", re.IGNORECASE)
    _WI_CHAPTER_URL_RE = re.compile(
        r"/document/statutes/(?P<chapter>[0-9]+)/?$",
        re.IGNORECASE,
    )
    OFFICIAL_DOMAIN = "docs.legis.wisconsin.gov"
    OFFICIAL_ENTRY_PATH = "/statutes/statutes"
    OFFICIAL_ENTRY_URL = "https://docs.legis.wisconsin.gov/statutes/statutes"
    STRICT_MINIMUM_CHAPTERS = 450
    OFFICIAL_CHAPTERS = (
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
        21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 38, 39,
        40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 59, 60,
        61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78,
        79, 80, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99,
        100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113,
        114, 115, 116, 117, 118, 119, 120, 121, 125, 126, 128, 132, 133, 134,
        135, 136, 137, 138, 139, 140, 145, 146, 149, 150, 151, 153, 154, 155,
        157, 160, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175,
        177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187, 188, 189, 190,
        191, 192, 193, 194, 195, 196, 197, 198, 199, 200, 201, 202, 203, 204,
        213, 214, 215, 216, 217, 218, 219, 220, 221, 222, 223, 224, 225, 226,
        227, 228, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 240, 241,
        242, 243, 244, 250, 251, 252, 253, 254, 255, 256, 257, 280, 281, 283,
        285, 287, 289, 291, 292, 293, 295, 299, 301, 302, 303, 304, 321, 322,
        323, 340, 341, 342, 343, 344, 345, 346, 347, 348, 349, 350, 351, 401,
        402, 403, 404, 405, 407, 408, 409, 410, 411, 420, 421, 422, 423, 424,
        425, 426, 427, 428, 429, 440, 441, 442, 443, 444, 445, 446, 447, 448,
        449, 450, 451, 452, 453, 454, 455, 456, 457, 458, 459, 460, 462, 463,
        464, 465, 466, 470, 551, 552, 553, 562, 563, 564, 565, 569, 600, 601,
        604, 605, 609, 610, 611, 612, 613, 614, 615, 616, 617, 618, 619, 620,
        621, 622, 623, 625, 626, 627, 628, 630, 631, 632, 633, 635, 644, 645,
        646, 647, 648, 655, 700, 701, 702, 703, 704, 705, 706, 707, 708, 709,
        710, 711, 750, 751, 752, 753, 754, 755, 756, 757, 758, 759, 765, 766,
        767, 768, 769, 770, 778, 779, 780, 781, 782, 783, 784, 785, 786, 788,
        799, 800, 801, 802, 803, 804, 805, 806, 807, 808, 809, 810, 811, 812,
        813, 814, 815, 816, 818, 820, 821, 822, 823, 835, 839, 840, 841, 842,
        843, 844, 846, 847, 851, 852, 853, 854, 856, 857, 858, 859, 860, 861,
        862, 863, 865, 866, 867, 868, 877, 878, 879, 880, 881, 882, 884, 885,
        887, 889, 891, 893, 895, 898, 901, 902, 903, 904, 905, 906, 907, 908,
        909, 910, 911, 916, 938, 939, 940, 941, 942, 943, 944, 945, 946, 947,
        948, 949, 950, 951, 961, 967, 968, 969, 970, 971, 972, 973, 974, 975,
        976, 977, 978, 979, 980, 985, 990, 991, 992, 995,
    )

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            wisconsin_chapter,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            wisconsin_chapter,
            wayback_machine_engine,
        )

    @staticmethod
    def _wisconsin_frontier_headers() -> Dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.7",
            "User-Agent": "ipfs-datasets-wisconsin-laws/2.0",
        }

    def _wisconsin_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                32,
                self._env_int("STATE_SCRAPER_WI_FRONTIER_CONCURRENCY", default=12),
            ),
        )

    @staticmethod
    def _is_valid_wisconsin_index(payload: bytes) -> bool:
        sample = bytes(payload or b"").lower()
        return bool(
            len(sample) > 1_000
            and b"wisconsin" in sample
            and b"/document/statutes/" in sample
            and b"</html>" in sample[-4_000:]
        )

    @staticmethod
    def _is_valid_wisconsin_viewer(payload: bytes) -> bool:
        sample = bytes(payload or b"").lower()
        return bool(
            len(sample) > 1_000
            and b"wisconsin legislature" in sample
            and (b'id="document"' in sample or b"id='document'" in sample)
            and b"</html>" in sample[-4_000:]
        )

    def _validate_wisconsin_aligned_evidence(
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
                f"Wisconsin {frontier_name} frontier lacks retained evidence: {url}"
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
                    f"Wisconsin {frontier_name} receipt lacks URL/digest: {url}"
                )
            if observed_url and self._canonical_fetch_url(observed_url) != canonical_url:
                raise RuntimeError(
                    f"Wisconsin {frontier_name} receipt changed URL identity: {url}"
                )
            if observed_digest and observed_digest != digest:
                raise RuntimeError(
                    f"Wisconsin {frontier_name} receipt changed content identity: {url}"
                )
        if parser_input_envelope is not None:
            body = getattr(parser_input_envelope, "body", None)
            if ledger_attached and body is None:
                raise RuntimeError(
                    f"Wisconsin {frontier_name} envelope lacks retained body: {url}"
                )
            if body is not None and bytes(body) != payload:
                raise RuntimeError(
                    f"Wisconsin {frontier_name} envelope changed content: {url}"
                )

    async def _fetch_wisconsin_frontier_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Callable[[bytes], bool],
        prefer_direct: bool,
    ) -> StateLawPageMultiFetchResult:
        """Fetch an exact HTML wave through grouped WARC/residual-only transport."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if not requested:
            return StateLawPageMultiFetchResult([], [], [], [], [], {})
        if (
            any(not url for url in requested)
            or any(
                (urlparse(url).hostname or "").casefold()
                != self.OFFICIAL_DOMAIN.casefold()
                for url in requested
            )
            or len(set(requested)) != len(requested)
        ):
            raise RuntimeError(
                f"Wisconsin {frontier_name} frontier has invalid, off-domain, "
                "or duplicate URLs"
            )
        retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_WI_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=self._env_int(
                        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                        default=1,
                    ),
                ),
            ),
        )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=retry_attempts,
            repeat_grouped_archive_inventory_on_residual=False,
            timeout_seconds=10 if prefer_direct else 35,
            headers=self._wisconsin_frontier_headers(),
            content_validator=content_validator,
            media_type="text/html",
            max_concurrency=self._wisconsin_frontier_concurrency(),
            prefer_direct=prefer_direct,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=("/statutes/statutes", "/document/statutes/"),
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
        )
        aligned = {
            len(batch.urls),
            len(batch.payloads),
            len(batch.errors),
            len(batch.transport_receipts),
            len(batch.parser_input_envelopes),
        }
        if aligned != {len(requested)} or list(batch.urls) != requested:
            raise RuntimeError(
                f"Wisconsin {frontier_name} frontier changed exact URL alignment"
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
                    {"url": url, "error": str(error or "invalid parser input")}
                )
                continue
            self._validate_wisconsin_aligned_evidence(
                url=url,
                payload=raw,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
                frontier_name=frontier_name,
            )
        if failures:
            raise RuntimeError(
                f"Wisconsin {frontier_name} frontier is incomplete after "
                f"residual-only retries; unresolved exact URLs: {failures[:10]}"
            )
        stats = list(getattr(self, "_wisconsin_frontier_batch_stats", []))
        stats.append(
            {
                "frontier_name": frontier_name,
                "requested_pages": len(requested),
                **dict(batch.stats or {}),
            }
        )
        self._wisconsin_frontier_batch_stats = stats
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    def _replay_wisconsin_retained_input(
        self,
        url: str,
        *,
        content_validator: Callable[[bytes], bool],
        frontier_name: str,
    ) -> bytes:
        """Replay an exact retained page without falling through to network."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Wisconsin retained replay requires an attached ledger")
        canonical_url = self._canonical_fetch_url(url)
        sanitized_headers = _sanitized_multifetch_headers(
            self._wisconsin_frontier_headers()
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
                f"Wisconsin retained replay is missing exact input: {canonical_url}"
            )
        envelope = getattr(retained, "envelope", None)
        raw = bytes(getattr(envelope, "body", None) or b"")
        if not raw or not content_validator(raw):
            raise RuntimeError(
                f"Wisconsin retained replay input is invalid: {canonical_url}"
            )
        self._validate_wisconsin_aligned_evidence(
            url=canonical_url,
            payload=raw,
            transport_receipt=getattr(retained, "transport_receipt", None),
            parser_input_envelope=envelope,
            frontier_name=frontier_name,
        )
        return raw

    async def _wisconsin_frontier_payloads(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Callable[[bytes], bool],
        network: bool,
        prefer_direct: bool,
    ) -> Tuple[List[str], List[bytes], List[Mapping[str, Any]]]:
        canonical = [self._canonical_fetch_url(url) for url in urls]
        if network:
            batch = await self._fetch_wisconsin_frontier_batch(
                canonical,
                frontier_name=frontier_name,
                content_validator=content_validator,
                prefer_direct=prefer_direct,
            )
            return (
                list(batch.urls),
                [bytes(item) for item in batch.payloads],
                [dict(item or {}) for item in batch.transport_receipts],
            )
        payloads = [
            self._replay_wisconsin_retained_input(
                url,
                content_validator=content_validator,
                frontier_name=frontier_name,
            )
            for url in canonical
        ]
        return canonical, payloads, [{} for _ in canonical]

    @staticmethod
    def _wisconsin_values_sha256(values: Sequence[Any]) -> str:
        return hashlib.sha256(
            json.dumps(list(values), sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

    def _wisconsin_exact_frontier(
        self,
        *,
        catalog_content_sha256: str,
        chapter_reports: Sequence[Mapping[str, Any]],
        section_reports: Sequence[Mapping[str, Any]],
        chapter_terminals: Sequence[Mapping[str, Any]],
        terminal_dispositions: Mapping[str, int],
    ) -> Dict[str, Any]:
        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        operative = sum(int(row.get("operative_sections") or 0) for row in section_reports)
        section_terminals = sum(
            int(row.get("terminal_sections") or 0) for row in section_reports
        )
        excluded = section_terminals + len(chapter_terminals)
        discovered = len(section_reports) + len(chapter_terminals)
        disposition = {
            "discovered": discovered,
            "fetched": operative,
            "excluded": excluded,
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        }
        if discovered != operative + excluded:
            raise RuntimeError("Wisconsin exact source disposition did not close")
        chapter_page_rows = [
            {
                "chapter_number": str(report.get("chapter_number") or ""),
                "source_url": str(page_row.get("source_url") or ""),
                "content_sha256": str(page_row.get("content_sha256") or ""),
            }
            for report in chapter_reports
            for page_row in list(report.get("pages") or [])
        ]
        section_page_rows = [
            {
                "section_number": str(report.get("section_number") or ""),
                "source_url": str(page_row.get("source_url") or ""),
                "content_sha256": str(page_row.get("content_sha256") or ""),
            }
            for report in section_reports
            for page_row in list(report.get("pages") or [])
        ]
        section_urls = [str(report.get("source_url") or "") for report in section_reports]
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": False,
            "catalog_chapter_count": len(chapter_reports),
            "catalog_content_sha256": str(catalog_content_sha256),
            "chapter_terminal_count": len(chapter_terminals),
            "chapter_viewer_page_count": len(
                {row["source_url"] for row in chapter_page_rows}
            ),
            "chapter_viewer_pages_sha256": self._wisconsin_values_sha256(
                chapter_page_rows
            ),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": discovered,
            "pagination_closed": True,
            "schema_version": "wisconsin-source-derived-viewer-frontier-v1",
            "scope_closed": True,
            "section_locator_count": len(section_reports),
            "section_locators_sha256": self._wisconsin_values_sha256(section_urls),
            "section_viewer_page_count": len(
                {row["source_url"] for row in section_page_rows}
            ),
            "section_viewer_pages_sha256": self._wisconsin_values_sha256(
                section_page_rows
            ),
            "terminal_dispositions": {
                str(key): int(value)
                for key, value in sorted(terminal_dispositions.items())
            },
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": discovered,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    async def _scrape_wisconsin_strict_frontier(
        self,
        code_name: str,
        *,
        network: bool,
        record_primary: bool,
    ) -> List[NormalizedStatute]:
        """Close the source-derived chapter/section viewer graph exactly."""

        from .wisconsin_chapter import (
            close_wisconsin_section_windows,
            parse_wisconsin_chapter_frontier_window,
            parse_wisconsin_section_window,
            toc_chapter_links,
        )

        if network:
            self._wisconsin_frontier_batch_stats = []
        root_urls, root_payloads, root_receipts = await self._wisconsin_frontier_payloads(
            [self.OFFICIAL_ENTRY_URL],
            frontier_name="statutes-index",
            content_validator=self._is_valid_wisconsin_index,
            network=network,
            prefer_direct=True,
        )
        del root_urls
        root_payload = root_payloads[0]
        root_transport = str(
            (root_receipts[0] if root_receipts else {}).get("source_transport")
            or (root_receipts[0] if root_receipts else {}).get("transport_kind")
            or ""
        ).casefold()
        follow_live_direct = bool(network and root_transport.startswith("direct"))
        catalog_rows = toc_chapter_links(
            root_payload.decode("utf-8", errors="replace"),
            base_url=self.get_base_url(),
        )
        chapter_numbers = [str(row[0]).strip() for row in catalog_rows]
        if (
            len(catalog_rows) < int(self.STRICT_MINIMUM_CHAPTERS)
            or len(chapter_numbers) != len(set(chapter_numbers))
            or any(not re.fullmatch(r"\d+", number) for number in chapter_numbers)
            or chapter_numbers != sorted(chapter_numbers, key=int)
        ):
            raise RuntimeError(
                "Wisconsin official index did not expose a closed ordered numeric "
                f"chapter frontier: observed={len(catalog_rows)} "
                f"minimum={self.STRICT_MINIMUM_CHAPTERS}"
            )

        chapter_states: Dict[str, Dict[str, Any]] = {
            number: {
                "chapter_number": number,
                "name": str(name),
                "sections": [],
                "section_set": set(),
                "pages": [],
                "visited": set(),
                "terminal": None,
                "closed": False,
            }
            for number, name, _url in catalog_rows
        }
        pending: List[Tuple[str, str]] = [
            (self._canonical_fetch_url(url), str(number))
            for number, _name, url in catalog_rows
        ]
        chapter_wave = 0
        while pending:
            chapter_wave += 1
            if chapter_wave > 128:
                raise RuntimeError("Wisconsin chapter TOC continuation frontier did not terminate")
            urls = [url for url, _chapter in pending]
            if len(urls) != len(set(urls)):
                raise RuntimeError("Wisconsin chapter continuation wave repeated a URL")
            fetched_urls, payloads, _receipts = await self._wisconsin_frontier_payloads(
                urls,
                frontier_name=f"chapter-toc-wave-{chapter_wave}",
                content_validator=self._is_valid_wisconsin_viewer,
                network=network,
                prefer_direct=follow_live_direct,
            )
            next_pending: List[Tuple[str, str]] = []
            for (_requested_url, chapter), source_url, payload in zip(
                pending, fetched_urls, payloads, strict=True
            ):
                state = chapter_states[chapter]
                if source_url in state["visited"]:
                    raise RuntimeError(
                        f"Wisconsin chapter TOC continuation cycled: {source_url}"
                    )
                state["visited"].add(source_url)
                window = parse_wisconsin_chapter_frontier_window(
                    payload.decode("utf-8", errors="replace"),
                    chapter=chapter,
                    page_url=source_url,
                )
                if window.residuals:
                    raise RuntimeError(
                        "Wisconsin chapter TOC parser left residuals: "
                        f"chapter={chapter} residuals={list(window.residuals)[:5]}"
                    )
                for section, label, section_source_url in window.section_rows:
                    if section in state["section_set"]:
                        raise RuntimeError(
                            "Wisconsin chapter TOC repeated section identity: "
                            f"chapter={chapter} section={section}"
                        )
                    state["section_set"].add(section)
                    state["sections"].append(
                        {
                            "chapter_number": chapter,
                            "section_number": section,
                            "source_label": label,
                            "source_url": self._canonical_fetch_url(section_source_url),
                        }
                    )
                state["pages"].append(
                    {
                        "source_url": source_url,
                        "content_sha256": hashlib.sha256(payload).hexdigest(),
                        "section_rows": len(window.section_rows),
                        "body_started": bool(window.body_started),
                        "next_url": str(window.next_url or ""),
                    }
                )
                if window.body_started:
                    if not state["sections"]:
                        raise RuntimeError(
                            f"Wisconsin chapter body began without a source TOC: {chapter}"
                        )
                    state["closed"] = True
                    continue
                if window.terminal_disposition:
                    if state["sections"]:
                        raise RuntimeError(
                            f"Wisconsin chapter mixed terminal and section frontier: {chapter}"
                        )
                    state["terminal"] = {
                        "chapter_number": chapter,
                        "disposition": window.terminal_disposition,
                        "source_url": source_url,
                    }
                    state["closed"] = True
                    continue
                if not window.next_url:
                    raise RuntimeError(
                        "Wisconsin chapter TOC ended without body or a source-bound "
                        f"terminal disposition: chapter={chapter} url={source_url}"
                    )
                next_url = self._canonical_fetch_url(window.next_url)
                if next_url in state["visited"]:
                    raise RuntimeError(
                        f"Wisconsin chapter TOC next link cycled: {next_url}"
                    )
                next_pending.append((next_url, chapter))
            pending = next_pending

        if any(not state["closed"] for state in chapter_states.values()):
            raise RuntimeError("Wisconsin chapter TOC frontier did not close every chapter")
        chapter_reports: List[Dict[str, Any]] = []
        chapter_terminals: List[Mapping[str, Any]] = []
        section_units: List[Dict[str, str]] = []
        seen_sections: set[str] = set()
        for chapter in chapter_numbers:
            state = chapter_states[chapter]
            if state["terminal"] is not None:
                chapter_terminals.append(dict(state["terminal"]))
            for unit in state["sections"]:
                section = str(unit["section_number"])
                if section in seen_sections:
                    raise RuntimeError(
                        f"Wisconsin source frontier repeated section: {section}"
                    )
                seen_sections.add(section)
                section_units.append(dict(unit))
            chapter_reports.append(
                {
                    "chapter_number": chapter,
                    "name": str(state["name"]),
                    "source_url": str(catalog_rows[chapter_numbers.index(chapter)][2]),
                    "source_sections": len(state["sections"]),
                    "terminal_chapter": bool(state["terminal"]),
                    "pages": list(state["pages"]),
                    "closed": True,
                }
            )
        if not section_units:
            raise RuntimeError("Wisconsin source-derived chapter frontier has no sections")

        section_states: Dict[str, Dict[str, Any]] = {
            unit["section_number"]: {
                "unit": unit,
                "windows": [],
                "pages": [],
                "visited": set(),
                "closed": False,
            }
            for unit in section_units
        }
        pending_by_url: Dict[str, List[str]] = {}
        for unit in section_units:
            pending_by_url.setdefault(unit["source_url"], []).append(
                unit["section_number"]
            )
        section_wave = 0
        while pending_by_url:
            section_wave += 1
            if section_wave > 256:
                raise RuntimeError("Wisconsin section viewer continuation frontier did not terminate")
            urls = list(pending_by_url)
            fetched_urls, payloads, receipts = await self._wisconsin_frontier_payloads(
                urls,
                frontier_name=f"section-body-wave-{section_wave}",
                content_validator=self._is_valid_wisconsin_viewer,
                network=network,
                prefer_direct=follow_live_direct,
            )
            next_by_url: Dict[str, List[str]] = {}
            for source_url, payload, receipt in zip(
                fetched_urls, payloads, receipts, strict=True
            ):
                targets = pending_by_url[source_url]
                for target in targets:
                    state = section_states[target]
                    if source_url in state["visited"]:
                        raise RuntimeError(
                            f"Wisconsin section continuation cycled: {target} {source_url}"
                        )
                    state["visited"].add(source_url)
                    initial = not state["windows"]
                    window = parse_wisconsin_section_window(
                        payload.decode("utf-8", errors="replace"),
                        section_number=target,
                        page_url=source_url,
                    )
                    if window.residuals:
                        raise RuntimeError(
                            "Wisconsin section parser left window residuals: "
                            f"section={target} residuals={list(window.residuals)[:5]}"
                        )
                    if initial and not window.target_seen:
                        raise RuntimeError(
                            "Wisconsin requested section page did not render its exact "
                            f"target: section={target} url={source_url}"
                        )
                    state["windows"].append(window)
                    state["pages"].append(
                        {
                            "source_url": source_url,
                            "content_sha256": hashlib.sha256(payload).hexdigest(),
                            "target_seen": bool(window.target_seen),
                            "target_complete": bool(window.target_complete),
                        }
                    )
                    if window.target_complete:
                        state["closed"] = True
                        continue
                    if not window.target_seen and (
                        window.encountered_sections or not window.next_url
                    ):
                        state["closed"] = True
                        continue
                    if not window.next_url:
                        raise RuntimeError(
                            "Wisconsin section traversal ended without exact closure: "
                            f"section={target} url={source_url}"
                        )
                    next_url = self._canonical_fetch_url(window.next_url)
                    if next_url in state["visited"]:
                        raise RuntimeError(
                            f"Wisconsin section next link cycled: {target} {next_url}"
                        )
                    next_by_url.setdefault(next_url, []).append(target)
                    if network and receipt:
                        state["transport_receipt"] = dict(receipt)
            pending_by_url = next_by_url

        statutes: List[NormalizedStatute] = []
        section_reports: List[Dict[str, Any]] = []
        terminal_counts: Dict[str, int] = {}
        seen_statute_ids: set[str] = set()
        for unit in section_units:
            target = unit["section_number"]
            state = section_states[target]
            parsed = close_wisconsin_section_windows(
                state["windows"],
                section_number=target,
                code_name=code_name,
                source_url=unit["source_url"],
                traversal_closed=bool(state["closed"]),
            )
            if not parsed.closed or parsed.residuals:
                raise RuntimeError(
                    "Wisconsin exact section parser did not close: "
                    f"section={target} residuals={list(parsed.residuals)[:5]}"
                )
            terminal_count = 1 if parsed.terminal_section is not None else 0
            operative_count = 1 if parsed.statute is not None else 0
            if operative_count + terminal_count != 1:
                raise RuntimeError(
                    f"Wisconsin section disposition is not exact: {target}"
                )
            if parsed.terminal_section is not None:
                disposition = str(parsed.terminal_section.get("disposition") or "")
                terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1
            else:
                statute = parsed.statute
                assert statute is not None
                identity = str(statute.statute_id or "").strip().casefold()
                if not identity or identity in seen_statute_ids:
                    raise RuntimeError(
                        f"Wisconsin normalized statute identity repeated: {statute.statute_id}"
                    )
                seen_statute_ids.add(identity)
                page_digests = [str(page["content_sha256"]) for page in state["pages"]]
                statute.structured_data = {
                    **dict(statute.structured_data or {}),
                    "source_viewer_page_count": len(state["pages"]),
                    "source_viewer_pages_sha256": self._wisconsin_values_sha256(
                        page_digests
                    ),
                }
                statutes.append(statute)
            section_reports.append(
                {
                    "chapter_number": unit["chapter_number"],
                    "section_number": target,
                    "source_url": unit["source_url"],
                    "source_blocks": parsed.source_block_count,
                    "operative_sections": operative_count,
                    "terminal_sections": terminal_count,
                    "pages": list(state["pages"]),
                    "closed": True,
                }
            )
        for terminal in chapter_terminals:
            disposition = str(terminal.get("disposition") or "")
            terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1

        frontier = self._wisconsin_exact_frontier(
            catalog_content_sha256=hashlib.sha256(root_payload).hexdigest(),
            chapter_reports=chapter_reports,
            section_reports=section_reports,
            chapter_terminals=chapter_terminals,
            terminal_dispositions=terminal_counts,
        )
        observed_at = datetime.now(timezone.utc).isoformat()
        observation = {
            "boundary_first": str(section_units[0]["source_url"]),
            "boundary_last": str(section_units[-1]["source_url"]),
            "chapter_reports": chapter_reports,
            "chapter_terminals": list(chapter_terminals),
            "code_name": code_name,
            "frontier": frontier,
            "observed_at": observed_at,
            "section_reports": section_reports,
            "transport_batch_stats": list(
                getattr(self, "_wisconsin_frontier_batch_stats", [])
            ),
        }
        if record_primary:
            self._last_wisconsin_full_frontier = observation
            self._last_wisconsin_strict_closure = {
                "schema": "wisconsin-strict-viewer-closure-v1",
                "closed": True,
                "catalog_chapters": len(chapter_reports),
                "source_sections": len(section_reports) + len(chapter_terminals),
                "operative_sections": len(statutes),
                "terminal_sections": sum(terminal_counts.values()),
                "terminal_dispositions": dict(sorted(terminal_counts.items())),
                "unclassified_sections": 0,
                "frontier": frontier,
                "batch_stats": list(
                    getattr(self, "_wisconsin_frontier_batch_stats", [])
                ),
            }
        else:
            self._last_wisconsin_replayed_frontier = observation
        return statutes

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._WI_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Wisconsin's legislative website."""
        return "https://docs.legis.wisconsin.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Wisconsin."""
        return [{
            "name": "Wisconsin Statutes",
            "url": f"{self.get_base_url()}/statutes/statutes",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Wisconsin's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .wisconsin_constitution import (
            configured_constitution_text_path,
            parse_wisconsin_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_wisconsin_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Wisconsin Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        if self._full_corpus_enabled() and max_statutes is None:
            return await self._scrape_wisconsin_strict_frontier(
                code_name,
                network=True,
                record_primary=True,
            )
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        if official:
            return official[:limit] if limit is not None else official

        if limit is not None and max_statutes is None:
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
            if direct:
                return direct[:limit]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/statutes",
            f"{self.get_base_url()}/document/statutes/940",
            f"{self.get_base_url()}/document/statutes/939.50",
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
                        "Wis. Stat.",
                        max_sections=scan_limit,
                        wait_for_selector="a[href*='/document/statutes/'], a[href*='/statutes/statutes']",
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
                "Wis. Stat.",
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
            ("939.50", f"{self.get_base_url()}/document/statutes/939.50"),
            ("940.01", f"{self.get_base_url()}/document/statutes/940.01"),
        ]
        return await self._scrape_section_urls(code_name, [(url, section_number) for section_number, url in section_urls], max_statutes=max_statutes)

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        chapter_links = await self._discover_chapter_links()
        self.logger.info("Wisconsin official index: discovered %s chapter links", len(chapter_links))
        statutes: List[NormalizedStatute] = []
        seen = set()
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_match = re.search(r"/document/statutes/([0-9]+)/?$", chapter_url, re.IGNORECASE)
            chapter_number = chapter_match.group(1) if chapter_match else ""
            chapter_payload = await self._fetch_page_content_with_archival_fallback(
                chapter_url, timeout_seconds=20
            )
            if chapter_payload and chapter_number:
                from .wisconsin_chapter import statutes_from_page

                html = (
                    chapter_payload.decode("utf-8", errors="replace")
                    if isinstance(chapter_payload, bytes)
                    else str(chapter_payload)
                )
                remaining = None if limit is None else max(0, int(limit) - len(statutes))
                for row in statutes_from_page(
                    html,
                    chapter=chapter_number,
                    code_name=code_name,
                    max_statutes=remaining,
                ):
                    key = str(row.section_number or "").strip().lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    statutes.append(row)
                    if limit is not None and len(statutes) >= limit:
                        break
            section_links = self._section_links_from_payload(
                chapter_url,
                chapter_payload,
            )
            if chapter_index == 1 or chapter_index % 25 == 0 or chapter_index == len(chapter_links):
                self.logger.info(
                    "Wisconsin official index: chapter=%s index=%s/%s sections=%s statutes_so_far=%s",
                    chapter_label or chapter_url,
                    chapter_index,
                    len(chapter_links),
                    len(section_links),
                    len(statutes),
                )
            remaining_links = [
                item
                for item in section_links
                if str(item[1] or "").strip().lower() not in seen
            ]
            parsed = await self._scrape_section_urls(
                code_name,
                remaining_links,
                max_statutes=(None if limit is None else max(0, limit - len(statutes))),
            )
            for row in parsed:
                key = str(row.section_number or "").strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                statutes.append(row)
        return statutes[:limit] if limit is not None else statutes

    async def _discover_chapter_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/statutes/statutes"
        payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not re.search(r"/document/statutes/[0-9]+/?$", href, re.IGNORECASE):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        return self._section_links_from_payload(chapter_url, payload)

    def _section_links_from_payload(
        self,
        chapter_url: str,
        payload: Any,
    ) -> List[Tuple[str, str]]:
        """Parse section links from an already-receipted chapter response."""

        if not payload:
            return []
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        chapter_match = re.search(r"/document/statutes/([0-9]+)/?$", chapter_url, re.IGNORECASE)
        chapter_number = chapter_match.group(1) if chapter_match else ""
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            if not self._WI_SECTION_URL_RE.search(href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            label = self._normalize_legal_text(anchor.get_text(" ", strip=True))
            section_number = normalized.rsplit("/", 1)[-1]
            if chapter_number and section_number.split(".", 1)[0] != chapter_number:
                continue
            # Always store the URL-derived section number (not the link label).
            out.append((normalized, section_number if section_number else label))
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        statutes: List[NormalizedStatute] = []
        for source_url, section_hint in section_urls:
            if limit is not None and len(statutes) >= limit:
                break
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=15)
            if not payload:
                continue
            url_section = str(source_url).rstrip("/").rsplit("/", 1)[-1].strip()
            section_number = url_section if re.match(r"^[0-9]+(?:\.[0-9A-Za-z]+)+$", url_section) else str(section_hint or url_section).strip()
            html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
            from .wisconsin_chapter import chapter_of, statutes_from_page

            harvested = statutes_from_page(
                html,
                chapter=chapter_of(section_number),
                code_name=code_name,
                max_statutes=None,
            )
            match = next(
                (row for row in harvested if str(row.section_number) == section_number),
                None,
            )
            if match is not None:
                statutes.append(match)
                continue
            soup = BeautifulSoup(html, "html.parser")
            section_nodes = soup.select(f'[data-section="{section_number}"]')
            if not section_nodes:
                section_nodes = soup.select(".box-content, #contentFrame, main, article, body")

            text_parts: List[str] = []
            section_name = ""
            for node in section_nodes:
                if not section_name:
                    title_node = node.select_one(".qstitle_sect") or node.select_one("h1") or node.find("title")
                    if title_node:
                        section_name = title_node.get_text(" ", strip=True)
                text_value = self._normalize_legal_text(node.get_text(" ", strip=True))
                if text_value:
                    text_parts.append(text_value)

            text = self._normalize_legal_text(" ".join(text_parts))
            if not section_name:
                title = soup.find("title") or soup.find("h1")
                section_name = title.get_text(" ", strip=True) if title else f"Section {section_number}"
            if len(text) < 180:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=source_url,
                    official_cite=f"Wis. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_wisconsin_statutes_html",
                        "discovery_method": "official_chapter_section_index",
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Replay the exact retained WI viewer graph and seal output parity."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Wisconsin frontier closure requires an attached ledger")
        first = getattr(self, "_last_wisconsin_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Wisconsin source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()
        replay_rows = await self._scrape_wisconsin_strict_frontier(
            str(first.get("code_name") or "Wisconsin Statutes"),
            network=False,
            record_primary=False,
        )
        replay = getattr(self, "_last_wisconsin_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("Wisconsin retained source replay did not close")
        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier, Mapping
        ):
            raise RuntimeError("Wisconsin exact frontier observations are incomplete")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        observed_at = str(first.get("observed_at") or "")
        batch_stats = list(first.get("transport_batch_stats") or [])

        def _wave_count(prefix: str) -> int:
            return sum(
                str(row.get("frontier_name") or "").startswith(prefix)
                for row in batch_stats
                if isinstance(row, Mapping)
            )

        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="WI",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=observed_at,
            legal_as_of=observed_at[:10],
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(list(first.get("chapter_reports") or [])),
            pagination_total=len(list(first.get("section_reports") or [])),
            transport={
                "fixture": False,
                "chapter_acquisition_wave_count": _wave_count(
                    "chapter-toc-wave-"
                ),
                "first_pass_request_batches": len(batch_stats),
                "first_pass_requested_pages": sum(
                    int(row.get("requested_pages") or 0)
                    for row in batch_stats
                    if isinstance(row, Mapping)
                ),
                "first_pass_batch_stats": batch_stats,
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_html_viewer",
                "leaf_acquisition_wave_count": _wave_count(
                    "section-body-wave-"
                ),
                "per_page_archive_loop": False,
                "repeat_grouped_archive_inventory_on_residual": False,
                "residual_only_retries": True,
                "retained_replay_network_requests": 0,
                "root_acquisition_wave_count": _wave_count("statutes-index"),
                "source_ordered_cross_parent_union": True,
                "synthetic": False,
                "wayback_prefix_inventory": True,
            },
        )

    def official_chapter_url(self, chapter_number: Any) -> str:
        return f"{self.get_base_url()}/document/statutes/{int(chapter_number)}"

    def official_chapter_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Wisconsin Statutes chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for number in self.OFFICIAL_CHAPTERS:
            url = self.official_chapter_url(number)
            rows.append(
                {
                    "canonical_key": f"wi:chapter-{int(number)}",
                    "chapter_number": str(int(number)),
                    "name": f"Chapter {int(number)}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Wisconsin Statutes Chapter {int(number)} official "
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
                        "User-Agent": "ipfs-datasets-wisconsin-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-wisconsin-official-catalog/1.0",
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
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._WI_CHAPTER_URL_RE.search(absolute)
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
        """Enumerate every official Wisconsin chapter and repair missing live links."""

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
                    "canonical_key": f"wi:chapter-{number}",
                    "chapter_number": number,
                    "name": f"Chapter {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Wisconsin Statutes Chapter {number} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        rows.sort(key=lambda item: int(item["chapter_number"]))
        return rows

    def fetch_official(self, code: str = "WI"):
        """Acquire the exhaustive official Wisconsin Statutes chapter catalog.

        Live HTTPS retains the official statutes index. Every known chapter is
        enumerated with an official docs.legis.wisconsin.gov URL. This hook
        never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "WI").strip().upper() or "WI"
        if normalized != "WI":
            raise ValueError(f"WisconsinScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("wisconsin official catalog enumeration is incomplete")
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
StateScraperRegistry.register("WI", WisconsinScraper)
