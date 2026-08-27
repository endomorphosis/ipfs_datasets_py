"""Scraper for Kentucky state laws.

This module contains the scraper for Kentucky statutes from the official state legislative website.
"""

import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class KentuckyScraper(BaseStateScraper):
    """Scraper for Kentucky state laws from https://legislature.ky.gov"""

    _KY_STATUTES_BASE = "https://apps.legislature.ky.gov/law/statutes/"
    _KY_SECTION_URL_RE = re.compile(r"/law/statutes/statute\.aspx\?id=\d+$", re.IGNORECASE)
    _KY_CHAPTER_URL_RE = re.compile(r"/law/statutes/chapter\.aspx\?id=\d+$", re.IGNORECASE)
    _CHAPTER_LABEL_RE = re.compile(r"^\s*chapter\s+(\d+[A-Za-z]?)\b", re.IGNORECASE)
    _SECTION_LABEL_RE = re.compile(
        r"^\s*(?:KRS\s+)?(?:§\s*)?(\d+\.\d+[A-Za-z0-9\.-]*|\.\d+[A-Za-z0-9\.-]*)\b"
    )

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            kentucky_section,
            state_archival_fetch,
            strict_frontier_closure,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            kentucky_section,
            wayback_machine_engine,
        )

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._KY_SECTION_URL_RE.search(source):
                section_name = str(statute.section_name or "")
                if str(statute.section_number or "").startswith("Section-"):
                    # KRS section rows often start with ".010" style identifiers.
                    m = re.search(r"^\.(\d+[A-Za-z0-9\.-]*)\b", section_name)
                    if m:
                        statute.section_number = m.group(1)
                filtered.append(statute)
        return filtered

    def get_base_url(self) -> str:
        """Return the base URL for Kentucky's legislative website."""
        return "https://apps.legislature.ky.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Kentucky."""
        return [
            {"name": "Kentucky Revised Statutes", "url": self._KY_STATUTES_BASE, "type": "Code"}
        ]

    async def _fetch_official_ky_bytes(self, url: str, timeout_seconds: int = 5) -> bytes:
        """Fetch one Kentucky KRS page through the retained transport seam.

        Bounded probes keep this single-page API.  Unbounded production uses
        :meth:`_fetch_official_ky_frontier` so same-domain archive inventory
        and same-WARC ranges are shared across the whole known frontier.
        """
        timeout = max(1, int(timeout_seconds or 5))
        return await self._fetch_parser_input_with_transport(
            url,
            headers={
                "User-Agent": "ipfs-datasets-kentucky-krs-scraper/2.0",
                "Accept": "text/html,application/pdf,*/*;q=0.8",
            },
            timeout_seconds=timeout,
            allow_archival_fallback=True,
            provider="requests_direct",
        )

    async def _fetch_official_ky_frontier(
        self,
        urls: List[str],
        *,
        frontier_name: str,
        timeout_seconds: int,
        content_validator: Optional[Callable[[bytes], bool]] = None,
    ) -> List[bytes]:
        """Fetch a known KRS frontier with exact order and retained replay.

        Early Kentucky evidence used the state adapter's explicit ``Accept``
        header in its sanitized request identity.  Replay that contract first,
        then submit only genuine misses to the shared plural fetcher.  New
        responses use the plural fetcher's ordinary GET contract and therefore
        remain directly replayable by that shared implementation on restart.
        """

        requested = [self._canonical_fetch_url(url) for url in urls]
        if any(not url for url in requested):
            raise RuntimeError(
                f"Kentucky {frontier_name} frontier contains an invalid URL"
            )
        if len(set(requested)) != len(requested):
            raise RuntimeError(
                f"Kentucky {frontier_name} frontier contains duplicate URLs"
            )
        if not requested:
            return []

        def _valid(payload: bytes) -> bool:
            if not payload:
                return False
            if content_validator is None:
                return True
            try:
                return bool(content_validator(payload))
            except Exception:
                return False

        retained: Dict[str, bytes] = {}
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is not None:
            accept = "text/html,application/pdf,*/*;q=0.8"
            retained_replay_only = bool(
                getattr(ledger, "retained_replay_only", False)
            )
            for url in requested:
                request_variants = [
                    {
                        "headers": {"Accept": accept},
                        "method": "GET",
                        "url": url,
                    }
                ]
                if retained_replay_only:
                    request_variants.append({"method": "GET", "url": url})
                prior = self._replay_retained_ky_request_variants(
                    ledger=ledger,
                    official_url=url,
                    request_variants=request_variants,
                )
                if prior is None:
                    continue
                payload = bytes(prior.envelope.body or b"")
                if not _valid(payload):
                    raise RuntimeError(
                        f"Kentucky retained {frontier_name} payload failed validation: {url}"
                    )
                retained[url] = payload

        missing = [url for url in requested if url not in retained]
        fetched: Dict[str, bytes] = {}
        if missing:
            concurrency = max(
                1,
                int(os.getenv("STATE_SCRAPER_KY_FRONTIER_CONCURRENCY", "8") or "8"),
            )
            residual_retry_attempts = max(
                0,
                min(
                    3,
                    self._env_int(
                        "STATE_SCRAPER_KY_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                        default=self._env_int(
                            "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                            default=1,
                        ),
                    ),
                ),
            )
            batch = await (
                self._fetch_page_contents_with_archival_fallback_retrying_residuals(
                    missing,
                    residual_retry_attempts=residual_retry_attempts,
                    repeat_grouped_archive_inventory_on_residual=False,
                    timeout_seconds=max(1, int(timeout_seconds or 20)),
                    content_validator=_valid,
                    max_concurrency=concurrency,
                    prefer_direct=True,
                    common_crawl_domain_terms=("apps.legislature.ky.gov",),
                    common_crawl_url_terms=("/law/statutes/",),
                    common_crawl_mime_terms=("html", "pdf"),
                    wayback_prefix_inventory=True,
                )
            )
            aligned_lengths = {
                len(batch.urls),
                len(batch.payloads),
                len(batch.errors),
                len(batch.transport_receipts),
                len(batch.parser_input_envelopes),
            }
            if aligned_lengths != {len(missing)}:
                raise RuntimeError(
                    f"Kentucky {frontier_name} frontier returned unaligned acquisition rows"
                )
            if list(batch.urls) != missing:
                raise RuntimeError(
                    f"Kentucky {frontier_name} frontier changed URL order or identity"
                )
            failures = [
                {"url": url, "error": error or "empty or invalid payload"}
                for url, payload, error in zip(
                    batch.urls,
                    batch.payloads,
                    batch.errors,
                    strict=True,
                )
                if error is not None or not _valid(payload)
            ]
            if failures:
                raise RuntimeError(
                    f"Kentucky {frontier_name} frontier is incomplete: {failures[:5]}"
                )
            fetched = dict(zip(batch.urls, batch.payloads, strict=True))

        payloads = [retained.get(url, fetched.get(url, b"")) for url in requested]
        if any(not _valid(payload) for payload in payloads):
            raise RuntimeError(
                f"Kentucky {frontier_name} frontier failed final aligned validation"
            )
        return payloads

    @staticmethod
    def _replay_retained_ky_request_variants(
        *,
        ledger: Any,
        official_url: str,
        request_variants: Sequence[Mapping[str, Any]],
    ) -> Any:
        """Replay the first retained Kentucky request variant without network.

        A replay-only ledger must fail on an individual exact-request miss.
        Kentucky has two historical GET identities, however, so probe both
        known variants before treating the official URL itself as absent.
        Ordinary live ledgers retain their existing optional-miss behavior.
        """

        from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
            StateLawRetainedReplayOnlyError,
        )

        replay_only = bool(getattr(ledger, "retained_replay_only", False))
        last_replay_only_miss: Optional[Exception] = None
        for sanitized_request in request_variants:
            try:
                retained = ledger.replay_retained_parser_input(
                    official_url=official_url,
                    sanitized_request=sanitized_request,
                )
            except StateLawRetainedReplayOnlyError as exc:
                if not replay_only:
                    raise
                last_replay_only_miss = exc
                continue
            if retained is not None:
                return retained
        if replay_only:
            raise StateLawRetainedReplayOnlyError(
                "retained-replay-only ledger miss for every exact Kentucky "
                f"parser request variant: {official_url}"
            ) from last_replay_only_miss
        return None

    def _replay_official_ky_frontier(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Optional[Callable[[bytes], bool]] = None,
    ) -> List[bytes]:
        """Replay an exact KRS page frontier without permitting network I/O."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Kentucky retained replay requires an attached ledger")
        requested = [self._canonical_fetch_url(url) for url in urls]
        if (
            any(not url for url in requested)
            or len(requested) != len(set(requested))
        ):
            raise RuntimeError(
                f"Kentucky retained {frontier_name} frontier is invalid"
            )

        def _valid(payload: bytes) -> bool:
            if not payload:
                return False
            if content_validator is None:
                return True
            try:
                return bool(content_validator(payload))
            except Exception:
                return False

        accept = "text/html,application/pdf,*/*;q=0.8"
        payloads: List[bytes] = []
        for url in requested:
            retained = self._replay_retained_ky_request_variants(
                ledger=ledger,
                official_url=url,
                request_variants=(
                    {"method": "GET", "url": url},
                    {
                        "headers": {"Accept": accept},
                        "method": "GET",
                        "url": url,
                    },
                ),
            )
            if retained is None:
                raise RuntimeError(
                    "Kentucky retained replay is missing an exact parser input: "
                    f"{url}"
                )
            envelope = getattr(retained, "envelope", None)
            raw = bytes(getattr(envelope, "body", None) or b"")
            if not _valid(raw):
                raise RuntimeError(
                    "Kentucky retained replay input failed validation: "
                    f"{url}"
                )
            payloads.append(raw)
        return payloads

    @staticmethod
    def _looks_like_kentucky_root_payload(payload: bytes) -> bool:
        sample = bytes(payload or b"")[:500_000].lower()
        return bool(sample) and b"<html" in sample and b"chapter.aspx" in sample

    @staticmethod
    def _looks_like_kentucky_chapter_payload(payload: bytes) -> bool:
        sample = bytes(payload or b"")[:500_000].lower()
        return bool(sample) and b"<html" in sample and any(
            marker in sample
            for marker in (
                b"statute.aspx",
                b"kentucky revised statutes",
                b"repealed",
                b"reserved",
                b"chapter",
            )
        )

    @staticmethod
    def _looks_like_kentucky_section_payload(payload: bytes) -> bool:
        if len(payload) < 32:
            return False
        sample = bytes(payload)[:4096].lstrip().lower()
        return (
            sample.startswith(b"%pdf-")
            or b"<html" in sample
            or b"<!doctype" in sample
        )

    @staticmethod
    def _kentucky_frontier_member_digest(rows: Sequence[Mapping[str, Any]]) -> str:
        payload = json.dumps(
            [dict(row) for row in rows],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _kentucky_exact_frontier(
        self,
        *,
        root_payload: bytes,
        chapter_units: Sequence[Mapping[str, Any]],
        chapter_payloads: Sequence[bytes],
        section_frontier: Sequence[Tuple[str, str, str, str, str, str]],
        section_content_sha256: Mapping[str, str],
        structural_container_exclusions: Sequence[Mapping[str, Any]],
        empty_chapter_exclusions: Sequence[Mapping[str, Any]],
        concurrent_section_groups: Mapping[str, Sequence[Any]],
        section_batch_size: int,
    ) -> Dict[str, Any]:
        """Build the exact source-derived KRS leaf/disposition contract."""

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        if (
            not root_payload
            or len(chapter_units) != len(chapter_payloads)
            or len(section_content_sha256) != len(section_frontier)
        ):
            raise RuntimeError("Kentucky exact frontier inputs are incomplete")
        chapter_reports = [
            {
                "chapter_label": str(unit.get("chapter_label") or ""),
                "chapter_number": str(unit.get("chapter_number") or ""),
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "is_structural_container": bool(
                    unit.get("is_structural_container")
                ),
                "source_url": str(unit.get("url") or ""),
                "unit_kind": str(unit.get("unit_kind") or ""),
                "unit_label": str(unit.get("unit_label") or ""),
            }
            for unit, payload in zip(chapter_units, chapter_payloads, strict=True)
        ]
        section_reports = [
            {
                "chapter_label": chapter_label,
                "chapter_number": chapter_number,
                "chapter_url": chapter_url,
                "content_sha256": str(section_content_sha256.get(section_url) or ""),
                "section_label": section_label,
                "section_number": section_number,
                "source_record_id": self._source_record_id_from_section_url(
                    section_url
                ),
                "source_url": section_url,
            }
            for (
                section_url,
                section_label,
                section_number,
                chapter_url,
                chapter_label,
                chapter_number,
            ) in section_frontier
        ]
        if any(not row["content_sha256"] for row in section_reports):
            raise RuntimeError("Kentucky section frontier lacks a content digest")
        excluded = len(empty_chapter_exclusions)
        fetched = len(section_reports)
        discovered = fetched + excluded
        disposition = {
            "discovered": discovered,
            "duplicates": 0,
            "excluded": excluded,
            "failed_final": 0,
            "fetched": fetched,
            "quarantined": 0,
        }
        frontier: Dict[str, Any] = {
            "algebra_closed": discovered == fetched + excluded,
            "bundle_closed": False,
            "chapter_frontier_sha256": self._kentucky_frontier_member_digest(
                chapter_reports
            ),
            "chapter_unit_count": len(chapter_reports),
            "closed": True,
            "concurrent_section_group_count": len(concurrent_section_groups),
            "concurrent_source_record_count": sum(
                len(records) for records in concurrent_section_groups.values()
            ),
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": discovered,
            "leaf_acquisition_wave_count": 1,
            "pagination_closed": True,
            "request_batch_count": 3,
            "root_content_sha256": hashlib.sha256(root_payload).hexdigest(),
            "schema_version": "kentucky-source-derived-krs-frontier-v1",
            "scope_closed": True,
            "section_parse_batch_count": (
                len(section_reports) + section_batch_size - 1
            )
            // section_batch_size,
            "section_locator_count": len(section_reports),
            "section_record_frontier_sha256": (
                self._kentucky_frontier_member_digest(section_reports)
            ),
            "structural_container_count": len(structural_container_exclusions),
            "toc_exhausted": True,
            "typed_empty_chapter_count": excluded,
            "unvisited_continuation_links": [],
            "visited_index_units": discovered,
        }
        if frontier["algebra_closed"] is not True:
            raise RuntimeError("Kentucky source disposition algebra did not close")
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    async def _fetch_html(self, url: str, timeout_seconds: int = 5) -> str:
        payload = await self._fetch_official_ky_bytes(url, timeout_seconds=timeout_seconds)
        if not payload:
            return ""
        return payload.decode("utf-8", errors="replace")

    def _extract_chapter_number(self, label: str) -> str:
        match = self._CHAPTER_LABEL_RE.search(str(label or ""))
        return match.group(1).strip() if match else ""

    def _section_number_from_label(self, label: str, chapter_number: str) -> str:
        match = self._SECTION_LABEL_RE.search(str(label or ""))
        if not match:
            return ""

        value = match.group(1).strip()
        if value.startswith("."):
            return f"{chapter_number}{value}" if chapter_number else value.lstrip(".")
        return value

    def _source_record_id_from_section_url(self, section_url: str) -> str:
        """Return the exact official identity for one KRS source record.

        Kentucky deliberately publishes concurrent current, future-effective,
        contingent, and predecessor records under the same printed section
        number.  The numeric ``statute.aspx?id=...`` locator distinguishes
        those official records; the printed citation does not.
        """

        raw_url = str(section_url or "").strip()
        raw_parsed = urlparse(raw_url)
        canonical = self._canonical_fetch_url(raw_url)
        parsed = urlparse(canonical)
        query = parse_qs(parsed.query, keep_blank_values=True)
        source_ids = query.get("id") or []
        if (
            parsed.scheme.lower() != "https"
            or parsed.netloc.lower() != "apps.legislature.ky.gov"
            or parsed.path.lower() != "/law/statutes/statute.aspx"
            or raw_parsed.fragment
            or parsed.fragment
            or set(query) != {"id"}
            or len(source_ids) != 1
            or not re.fullmatch(r"\d+", str(source_ids[0] or ""))
            or not self._KY_SECTION_URL_RE.search(canonical)
        ):
            raise RuntimeError(
                f"Kentucky section URL lacks an exact official source-record identity: {section_url}"
            )
        return f"kentucky-statute-{source_ids[0]}"

    def _section_name_from_label(self, label: str, section_number: str) -> str:
        value = re.sub(r"\s+", " ", str(label or "")).strip()
        if not value:
            return ""
        variants = [
            rf"^\s*KRS\s+{re.escape(section_number)}\s*",
            rf"^\s*§\s*{re.escape(section_number)}\s*",
        ]
        if "." in section_number:
            suffix = "." + section_number.split(".", 1)[1]
            variants.append(rf"^\s*{re.escape(suffix)}\s*")
        variants.append(r"^\s*\.\d+[A-Za-z0-9\.-]*\s*")
        for pattern in variants:
            value = re.sub(pattern, "", value, count=1, flags=re.IGNORECASE).strip()
        return value

    def _looks_like_failed_pdf_extraction(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        if value.startswith("%PDF-") or " startxref " in value[:4000] or " endobj " in value[:4000]:
            return True
        sample = value[:2000]
        controlish = sum(
            1 for char in sample if char == "\ufffd" or (ord(char) < 32 and char not in "\n\r\t")
        )
        return bool(sample) and (controlish / len(sample)) > 0.05

    def _chapter_units_from_html(self, html: str) -> List[Dict[str, object]]:
        """Parse every official chapter/subchapter unit in root order.

        Eleven KRS chapters delegate some or all of their section inventories
        to sibling ``chapter.aspx`` pages labelled as subchapters, subtitles,
        or articles.  Treating only labels that begin with ``CHAPTER`` as the
        frontier silently omits those laws.  Parent context is carried forward
        only across the exact structural labels published by the root index.
        """

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html, "html.parser")
        units: List[Dict[str, object]] = []
        seen: set[str] = set()
        current_parent: Optional[Dict[str, object]] = None
        for link in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            href = urljoin(self._KY_STATUTES_BASE, str(link.get("href") or ""))
            if not self._KY_CHAPTER_URL_RE.search(href):
                continue

            chapter_number = self._extract_chapter_number(label)
            unit: Optional[Dict[str, object]] = None
            if chapter_number and label.upper().startswith("CHAPTER "):
                unit = {
                    "chapter_label": label,
                    "chapter_number": chapter_number,
                    "is_structural_container": False,
                    "unit_kind": "chapter",
                    "unit_label": label,
                    "url": href,
                }
                current_parent = unit
            elif re.match(r"^(?:subchapter|subtitle|article)\b", label, re.IGNORECASE):
                if current_parent is None:
                    raise RuntimeError(
                        f"Kentucky root index contains an orphan structural unit: {label!r}"
                    )
                current_parent["is_structural_container"] = True
                parent_label = str(current_parent["chapter_label"])
                unit = {
                    "chapter_label": parent_label,
                    "chapter_number": str(current_parent["chapter_number"]),
                    "is_structural_container": False,
                    "unit_kind": label.split(" ", 1)[0].lower(),
                    "unit_label": label,
                    "url": href,
                }
            elif label.casefold() == "kentucky rules of evidence":
                current_parent = None
                unit = {
                    "chapter_label": label,
                    "chapter_number": "KRE",
                    "is_structural_container": False,
                    "unit_kind": "rules",
                    "unit_label": label,
                    "url": href,
                }
            elif (
                href == "https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=39344"
                and label.startswith("Chapter titles, centered headings,")
            ):
                # Exact root-index explanatory cross-reference to KRS 446.
                continue
            else:
                raise RuntimeError(
                    "Kentucky root index contains an unclassified official chapter unit: "
                    f"label={label!r} url={href}"
                )

            if href in seen:
                raise RuntimeError(
                    f"Kentucky root index duplicated an official chapter unit: {href}"
                )
            seen.add(href)
            units.append(unit)
        return units

    async def _discover_chapter_units(self) -> List[Dict[str, object]]:
        """Discover the exact official KRS chapter and nested-unit frontier."""

        payloads = await self._fetch_official_ky_frontier(
            [self._KY_STATUTES_BASE],
            frontier_name="root-index",
            timeout_seconds=15,
            content_validator=self._looks_like_kentucky_root_payload,
        )
        if not payloads:
            return []
        self._last_kentucky_root_payload = bytes(payloads[0])
        return self._chapter_units_from_html(
            payloads[0].decode("utf-8", errors="replace")
        )

    async def _discover_chapter_links(self) -> List[Tuple[str, str, str]]:
        """Return flattened chapter links for bounded compatibility crawls."""

        units = await self._discover_chapter_units()
        links: List[Tuple[str, str, str]] = []
        for unit in units:
            chapter_label = str(unit["chapter_label"])
            unit_label = str(unit["unit_label"])
            display_label = (
                chapter_label
                if chapter_label == unit_label
                else f"{chapter_label} -- {unit_label}"
            )
            links.append(
                (str(unit["url"]), display_label, str(unit["chapter_number"]))
            )
        return links

    async def _discover_section_links(
        self,
        chapter_url: str,
        chapter_label: str,
        chapter_number: str,
    ) -> List[Tuple[str, str, str, str]]:
        """Discover section-level KRS PDF endpoints from one official chapter page."""
        html = await self._fetch_html(chapter_url, timeout_seconds=5)
        if not html:
            return []

        return self._section_links_from_html(
            chapter_url=chapter_url,
            chapter_label=chapter_label,
            chapter_number=chapter_number,
            html=html,
        )

    def _section_links_from_html(
        self,
        *,
        chapter_url: str,
        chapter_label: str,
        chapter_number: str,
        html: str,
    ) -> List[Tuple[str, str, str, str]]:
        """Parse the section frontier from one already-retained chapter page."""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html, "html.parser")
        section_links: List[Tuple[str, str, str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            href = urljoin(chapter_url, str(link.get("href") or ""))
            if not self._KY_SECTION_URL_RE.search(href):
                continue
            if href in seen:
                continue
            section_number = self._section_number_from_label(label, chapter_number)
            if not section_number:
                continue
            seen.add(href)
            section_links.append((href, label, section_number, chapter_label))
        return section_links

    async def _build_statute_from_section_page(
        self,
        code_name: str,
        section_url: str,
        section_label: str,
        section_number: str,
        chapter_url: str,
        chapter_label: str,
        chapter_number: str,
    ) -> Optional[NormalizedStatute]:
        raw_bytes = await self._fetch_official_ky_bytes(section_url, timeout_seconds=5)
        return await self._build_statute_from_section_bytes(
            code_name=code_name,
            section_url=section_url,
            section_label=section_label,
            section_number=section_number,
            chapter_url=chapter_url,
            chapter_label=chapter_label,
            chapter_number=chapter_number,
            raw_bytes=raw_bytes,
            require_extracted_text=False,
        )

    async def _build_statute_from_section_bytes(
        self,
        *,
        code_name: str,
        section_url: str,
        section_label: str,
        section_number: str,
        chapter_url: str,
        chapter_label: str,
        chapter_number: str,
        raw_bytes: bytes,
        require_extracted_text: bool,
    ) -> Optional[NormalizedStatute]:
        """Normalize one exact retained KRS section response."""

        extracted_text = ""
        method = "unknown"
        if raw_bytes:
            document_extraction = await self._extract_text_from_document_bytes(
                source_url=section_url,
                raw_bytes=raw_bytes,
            )
            if isinstance(document_extraction, dict):
                extracted_text = self._normalize_legal_text(
                    str(document_extraction.get("text") or "")
                )
                method = str(document_extraction.get("method") or "document_processor")
            else:
                try:
                    extracted_text = self._normalize_legal_text(
                        self._extract_best_content_text(raw_bytes.decode("utf-8", errors="replace"))
                    )
                    method = "html_text"
                except Exception:
                    extracted_text = ""
        if self._looks_like_failed_pdf_extraction(extracted_text):
            extracted_text = ""
            method = "failed_pdf_extraction"
        if require_extracted_text and not extracted_text:
            raise RuntimeError(
                "official KRS section response did not yield statutory text: "
                f"section={section_number} url={section_url} method={method}"
            )

        section_name = self._section_name_from_label(section_label, section_number)
        if extracted_text:
            first_line = re.sub(
                r"\s+",
                " ",
                extracted_text.splitlines()[0] if "\n" in extracted_text else extracted_text[:240],
            ).strip()
            parsed_name = self._section_name_from_label(first_line, section_number)
            if parsed_name:
                section_name = parsed_name[:200]

        effective_date = None
        history: List[str] = []
        if extracted_text:
            effective_match = re.search(
                r"\bEffective:\s*(.*?)(?:\s+History:|$)", extracted_text, re.IGNORECASE | re.DOTALL
            )
            if effective_match:
                effective_date = effective_match.group(1).strip()
            history_match = re.search(
                r"\bHistory:\s*(.+)$", extracted_text, re.IGNORECASE | re.DOTALL
            )
            if history_match:
                history = [self._normalize_legal_text(history_match.group(1))]

        source_record_id = self._source_record_id_from_section_url(section_url)
        is_evidence_rule = str(chapter_number or "").upper() == "KRE"
        printed_number = (
            section_number.split(".", 1)[1]
            if is_evidence_rule and "." in section_number
            else section_number
        )
        printed_statute_id = (
            f"KRE-{printed_number}" if is_evidence_rule else f"KRS-{section_number}"
        )
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{printed_statute_id}:record:{source_record_id}",
            code_name="Kentucky Rules of Evidence" if is_evidence_rule else code_name,
            chapter_number=chapter_number,
            chapter_name=chapter_label,
            section_number=section_number,
            section_name=section_name or section_label[:200],
            short_title=section_name or section_label[:200],
            full_text=extracted_text or f"KRS {section_number}: {section_label}",
            legal_area=self._identify_legal_area(code_name),
            source_url=section_url,
            official_cite=(
                f"Ky. R. Evid. {printed_number}"
                if is_evidence_rule
                else f"Ky. Rev. Stat. § {section_number}"
            ),
            metadata=StatuteMetadata(effective_date=effective_date, history=history),
            structured_data={
                "source_kind": (
                    "official_kentucky_rules_of_evidence_pdf"
                    if is_evidence_rule
                    else "official_krs_section_pdf"
                ),
                "discovery_method": "official_chapter_index",
                "chapter_url": chapter_url,
                "extraction_method": method,
                "printed_statute_id": printed_statute_id,
                "source_record_id": source_record_id,
                "source_record_identity_kind": "official_statute_query_id",
                "skip_hydrate": bool(extracted_text) or method == "failed_pdf_extraction",
            },
        )

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Kentucky's legislative website.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .kentucky_constitution import parse_configured_kentucky_constitution

        constitution_rows = parse_configured_kentucky_constitution(
            code_name=code_name or "Kentucky Constitution",
            max_statutes=limit,
        )
        if constitution_rows:
            return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .kentucky_section import parse_configured_kentucky_section

        local_row = parse_configured_kentucky_section(code_name=code_name)
        if local_row is not None:
            return [local_row]
        official = await self._scrape_official_krs_tree(code_name, max_statutes=limit)
        if official:
            kept = [
                statute
                for statute in official
                if self._KY_SECTION_URL_RE.search(str(statute.source_url or ""))
            ] or official
            return kept if limit is None else kept[: int(limit)]

        # Full-corpus runs must not sole-admit generic/Justia mirrors.
        if self._full_corpus_enabled() and max_statutes is None:
            return []

        fallback_limit = int(limit) if limit is not None else 200
        fallback_candidates = [self._KY_STATUTES_BASE]
        if code_url and code_url not in fallback_candidates:
            fallback_candidates.append(code_url)

        best_statutes: List[NormalizedStatute] = []
        for candidate in fallback_candidates:
            if "justia.com" in str(candidate).lower() or "findlaw.com" in str(candidate).lower():
                continue
            try:
                generic_statutes = await self._generic_scrape(
                    code_name,
                    candidate,
                    "Ky. Rev. Stat.",
                    max_sections=fallback_limit,
                )
            except Exception:
                continue
            filtered = self._filter_section_level(generic_statutes)
            generic_statutes = [
                statute
                for statute in (filtered or generic_statutes)
                if self._KY_SECTION_URL_RE.search(str(statute.source_url or ""))
            ][:fallback_limit]
            if len(generic_statutes) > len(best_statutes):
                best_statutes = generic_statutes
            if limit is not None and len(best_statutes) >= limit:
                break

        return best_statutes[:fallback_limit]

    async def _scrape_official_krs_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Walk the official KRS chapter/section tree without silent clamps."""
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        statutes: List[NormalizedStatute] = []

        chapter_cap_raw = str(os.getenv("KENTUCKY_FULL_CORPUS_MAX_CHAPTERS", "") or "").strip()
        chapter_cap = 0
        if chapter_cap_raw:
            try:
                chapter_cap = max(0, int(chapter_cap_raw))
            except Exception:
                chapter_cap = 0

        if limit is None:
            if chapter_cap > 0:
                raise RuntimeError(
                    "KENTUCKY_FULL_CORPUS_MAX_CHAPTERS cannot cap an unbounded production crawl"
                )
            self._last_kentucky_root_payload = None
            chapter_units = await self._discover_chapter_units()
            root_payload = getattr(self, "_last_kentucky_root_payload", None)
            return await self._scrape_official_krs_tree_batched(
                code_name=code_name,
                chapter_units=chapter_units,
                root_payload=root_payload,
                record_primary=True,
            )

        chapter_links = await self._discover_chapter_links()
        if chapter_cap > 0:
            chapter_links = chapter_links[:chapter_cap]
        total_chapters = len(chapter_links)
        self.logger.info(
            "Kentucky official KRS discovery: chapters=%s limit=%s fetch_cache=%s",
            total_chapters,
            limit or "unbounded",
            "on" if getattr(self, "_fetch_cache_enabled", False) else "off",
        )
        heartbeat_seconds = max(
            1,
            int(os.getenv("KENTUCKY_SCRAPER_HEARTBEAT_SECONDS", "30") or "30"),
        )
        section_heartbeat_every = max(
            1,
            int(os.getenv("KENTUCKY_SCRAPER_SECTION_HEARTBEAT_EVERY", "100") or "100"),
        )
        last_heartbeat = time.monotonic()
        total_sections_seen = 0

        for chapter_index, (chapter_url, chapter_label, chapter_number) in enumerate(
            chapter_links, start=1
        ):
            if limit is not None and len(statutes) >= limit:
                break

            chapter_started_at = time.monotonic()
            self.logger.info(
                "Kentucky KRS chapter start: index=%s/%s chapter=%s statutes_so_far=%s url=%s",
                chapter_index,
                total_chapters,
                chapter_label,
                len(statutes),
                chapter_url,
            )
            section_links = await self._discover_section_links(
                chapter_url=chapter_url,
                chapter_label=chapter_label,
                chapter_number=chapter_number,
            )
            self.logger.info(
                "Kentucky KRS chapter discovered sections: index=%s/%s chapter=%s sections=%s",
                chapter_index,
                total_chapters,
                chapter_label,
                len(section_links),
            )
            for section_index, (
                section_url,
                section_label,
                section_number,
                discovered_chapter_label,
            ) in enumerate(section_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                total_sections_seen += 1
                now = time.monotonic()
                if (
                    section_index == 1
                    or section_index % section_heartbeat_every == 0
                    or now - last_heartbeat >= heartbeat_seconds
                ):
                    self.logger.info(
                        "Kentucky KRS section progress: chapter_index=%s/%s chapter=%s section_index=%s/%s total_sections_seen=%s statutes_so_far=%s section=%s",
                        chapter_index,
                        total_chapters,
                        chapter_label,
                        section_index,
                        len(section_links),
                        total_sections_seen,
                        len(statutes),
                        section_number,
                    )
                    last_heartbeat = now
                try:
                    statute = await self._build_statute_from_section_page(
                        code_name=code_name,
                        section_url=section_url,
                        section_label=section_label,
                        section_number=section_number,
                        chapter_url=chapter_url,
                        chapter_label=discovered_chapter_label,
                        chapter_number=chapter_number,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Kentucky KRS section failed: chapter=%s section=%s url=%s error=%s",
                        chapter_label,
                        section_number,
                        section_url,
                        exc,
                    )
                    continue
                if statute is not None and self._KY_SECTION_URL_RE.search(
                    str(statute.source_url or "")
                ):
                    statute.structured_data = {
                        **(statute.structured_data or {}),
                        "chapter_url": chapter_url,
                    }
                    statutes.append(statute)
            self.logger.info(
                "Kentucky KRS chapter done: index=%s/%s chapter=%s sections=%s statutes_so_far=%s elapsed=%.2fs",
                chapter_index,
                total_chapters,
                chapter_label,
                len(section_links),
                len(statutes),
                time.monotonic() - chapter_started_at,
            )

        return statutes if limit is None else statutes[: int(limit)]

    async def _scrape_official_krs_tree_batched(
        self,
        *,
        code_name: str,
        chapter_units: List[Dict[str, object]],
        root_payload: bytes | None = None,
        record_primary: bool = True,
        replay_only: bool = False,
        write_checkpoints: bool = True,
    ) -> List[NormalizedStatute]:
        """Close uncapped hierarchy and leaf frontiers in source order.

        Chapter catalogs are acquired as one plural wave.  Their complete
        cross-chapter descendant union is then acquired as a second plural
        wave; ``STATE_SCRAPER_KY_SECTION_BATCH_SIZE`` bounds only subsequent
        parsing and checkpoint writes.
        """

        if not chapter_units:
            raise RuntimeError("Kentucky official KRS chapter frontier is empty")
        chapter_urls = [str(unit.get("url") or "") for unit in chapter_units]
        if (
            any(not url for url in chapter_urls)
            or len(set(chapter_urls)) != len(chapter_urls)
            or any(not str(unit.get("chapter_number") or "") for unit in chapter_units)
            or any(not str(unit.get("chapter_label") or "") for unit in chapter_units)
            or any(not str(unit.get("unit_label") or "") for unit in chapter_units)
        ):
            raise RuntimeError("Kentucky official chapter-unit frontier is invalid")

        if replay_only:
            chapter_payloads = self._replay_official_ky_frontier(
                chapter_urls,
                frontier_name="chapter-index",
                content_validator=self._looks_like_kentucky_chapter_payload,
            )
        else:
            chapter_payloads = await self._fetch_official_ky_frontier(
                chapter_urls,
                frontier_name="chapter-index",
                timeout_seconds=15,
                content_validator=self._looks_like_kentucky_chapter_payload,
            )
        section_frontier: List[Tuple[str, str, str, str, str, str]] = []
        seen_section_urls: set[str] = set()
        seen_source_record_ids: set[str] = set()
        section_records: Dict[str, List[Tuple[str, str, str, str]]] = {}
        empty_chapter_exclusions: List[Dict[str, str]] = []
        structural_container_exclusions: List[Dict[str, str]] = []
        for unit, payload in zip(chapter_units, chapter_payloads, strict=True):
            chapter_url = str(unit["url"])
            root_chapter_label = str(unit["chapter_label"])
            unit_label = str(unit["unit_label"])
            chapter_number = str(unit["chapter_number"])
            chapter_label = (
                root_chapter_label
                if root_chapter_label == unit_label
                else f"{root_chapter_label} -- {unit_label}"
            )
            html = payload.decode("utf-8", errors="replace")
            links = self._section_links_from_html(
                chapter_url=chapter_url,
                chapter_label=chapter_label,
                chapter_number=chapter_number,
                html=html,
            )
            if not links:
                if bool(unit.get("is_structural_container")):
                    structural_container_exclusions.append(
                        {
                            "chapter_label": root_chapter_label,
                            "chapter_number": chapter_number,
                            "disposition": "structural_container",
                            "source_url": chapter_url,
                        }
                    )
                    continue
                disposition = re.search(
                    r"\b(repealed|reserved|superseded|transferred|renumbered)\b",
                    unit_label,
                    flags=re.IGNORECASE,
                )
                if disposition is None:
                    raise RuntimeError(
                        "Kentucky official chapter produced no section frontier and no "
                        f"typed nonoperative marker: chapter={chapter_label!r} url={chapter_url}"
                    )
                empty_chapter_exclusions.append(
                    {
                        "chapter_label": chapter_label,
                        "chapter_number": chapter_number,
                        "disposition": disposition.group(1).lower(),
                        "source_url": chapter_url,
                    }
                )
                continue
            for section_url, section_label, section_number, discovered_label in links:
                if section_url in seen_section_urls:
                    raise RuntimeError(
                        f"Kentucky section frontier duplicated URL: {section_url}"
                    )
                source_record_id = self._source_record_id_from_section_url(section_url)
                if source_record_id in seen_source_record_ids:
                    raise RuntimeError(
                        "Kentucky section frontier duplicated official source-record identity: "
                        f"{source_record_id}"
                    )
                seen_section_urls.add(section_url)
                seen_source_record_ids.add(source_record_id)
                section_records.setdefault(section_number, []).append(
                    (chapter_url, chapter_number, section_label, source_record_id)
                )
                section_frontier.append(
                    (
                        section_url,
                        section_label,
                        section_number,
                        chapter_url,
                        discovered_label,
                        chapter_number,
                    )
                )

        concurrent_section_groups = {
            section_number: records
            for section_number, records in section_records.items()
            if len(records) > 1
        }
        for section_number, records in concurrent_section_groups.items():
            chapter_identities = {(row[0], row[1]) for row in records}
            labels = [row[2] for row in records]
            source_record_ids = [row[3] for row in records]
            if (
                len(chapter_identities) != 1
                or len(set(labels)) != len(labels)
                or len(set(source_record_ids)) != len(source_record_ids)
            ):
                raise RuntimeError(
                    "Kentucky concurrent source records are not exactly distinguishable: "
                    f"section={section_number}"
                )

        if not section_frontier:
            raise RuntimeError("Kentucky official KRS section frontier is empty")
        self.logger.info(
            "Kentucky aligned frontier: chapters=%s typed_empty_chapters=%s sections=%s concurrent_section_groups=%s",
            len(chapter_units),
            len(empty_chapter_exclusions),
            len(section_frontier),
            len(concurrent_section_groups),
        )
        if write_checkpoints:
            self._write_partial_checkpoint(
                [],
                code_name=code_name,
                stage_label="kentucky:section-discovery",
                force=True,
                extra={
                    "chapters_scanned": len(chapter_units),
                    "discovered_chapters": len(chapter_units),
                    "discovered_sections": len(section_frontier),
                    "sections_scanned": 0,
                    "structural_containers": len(structural_container_exclusions),
                    "typed_empty_chapters": len(empty_chapter_exclusions),
                    "concurrent_section_groups": len(concurrent_section_groups),
                    "concurrent_source_records": sum(
                        len(records) for records in concurrent_section_groups.values()
                    ),
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )

        section_batch_size = max(
            1,
            int(os.getenv("STATE_SCRAPER_KY_SECTION_BATCH_SIZE", "256") or "256"),
        )
        section_urls = [row[0] for row in section_frontier]
        if replay_only:
            section_payloads = self._replay_official_ky_frontier(
                section_urls,
                frontier_name="section",
                content_validator=self._looks_like_kentucky_section_payload,
            )
        else:
            section_payloads = await self._fetch_official_ky_frontier(
                section_urls,
                frontier_name="section",
                timeout_seconds=20,
                content_validator=self._looks_like_kentucky_section_payload,
            )
        if len(section_payloads) != len(section_frontier):
            raise RuntimeError(
                "Kentucky section frontier returned unaligned parser inputs"
            )

        statutes: List[NormalizedStatute] = []
        section_content_sha256: Dict[str, str] = {}
        for batch_start in range(0, len(section_frontier), section_batch_size):
            batch_rows = section_frontier[batch_start : batch_start + section_batch_size]
            payloads = section_payloads[
                batch_start : batch_start + len(batch_rows)
            ]
            for (
                section_url,
                section_label,
                section_number,
                chapter_url,
                chapter_label,
                chapter_number,
            ), payload in zip(batch_rows, payloads, strict=True):
                section_content_sha256[section_url] = hashlib.sha256(payload).hexdigest()
                statute = await self._build_statute_from_section_bytes(
                    code_name=code_name,
                    section_url=section_url,
                    section_label=section_label,
                    section_number=section_number,
                    chapter_url=chapter_url,
                    chapter_label=chapter_label,
                    chapter_number=chapter_number,
                    raw_bytes=payload,
                    require_extracted_text=True,
                )
                if statute is None:
                    raise RuntimeError(
                        f"Kentucky section parser returned no row: {section_url}"
                    )
                source_record_count = len(section_records[section_number])
                if source_record_count > 1:
                    statute.structured_data = {
                        **(statute.structured_data or {}),
                        "concurrent_source_record_count": source_record_count,
                    }
                statutes.append(statute)

            scanned = min(batch_start + len(batch_rows), len(section_frontier))
            self.logger.info(
                "Kentucky aligned section progress: scanned=%s/%s statutes=%s",
                scanned,
                len(section_frontier),
                len(statutes),
            )
            if write_checkpoints and (
                scanned == len(section_frontier)
                or (batch_start // section_batch_size + 1) % 4 == 0
            ):
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="kentucky:section-batch",
                    force=scanned == len(section_frontier),
                    extra={
                        "chapters_scanned": len(chapter_units),
                        "discovered_chapters": len(chapter_units),
                        "discovered_sections": len(section_frontier),
                        "sections_scanned": scanned,
                        "structural_containers": len(
                            structural_container_exclusions
                        ),
                        "typed_empty_chapters": len(empty_chapter_exclusions),
                        "concurrent_section_groups": len(concurrent_section_groups),
                        "concurrent_source_records": sum(
                            len(records) for records in concurrent_section_groups.values()
                        ),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )

        statute_ids = [str(row.statute_id or "").strip() for row in statutes]
        source_urls = [str(row.source_url or "").strip() for row in statutes]
        statute_source_record_ids = [
            str((row.structured_data or {}).get("source_record_id") or "").strip()
            for row in statutes
        ]
        frontier_source_record_ids = [
            self._source_record_id_from_section_url(row[0]) for row in section_frontier
        ]
        if (
            any(not value for value in statute_ids)
            or any(not value for value in statute_source_record_ids)
            or len(set(statute_ids)) != len(statute_ids)
            or len(set(source_urls)) != len(source_urls)
            or len(set(statute_source_record_ids)) != len(statute_source_record_ids)
            or statute_source_record_ids != frontier_source_record_ids
            or len(statutes) != len(section_frontier)
        ):
            raise RuntimeError(
                "Kentucky final statute identities do not exactly match the section frontier"
            )
        summary = {
            "chapters_discovered": len(chapter_units),
            "chapters_scanned": len(chapter_units),
            "closed": True,
            "section_locators_discovered": len(section_frontier),
            "section_locators_visited": len(section_frontier),
            "statutes_emitted": len(statutes),
            "concurrent_section_groups": len(concurrent_section_groups),
            "concurrent_source_records": sum(
                len(records) for records in concurrent_section_groups.values()
            ),
            "structural_container_exclusions": structural_container_exclusions,
            "typed_empty_chapter_exclusions": empty_chapter_exclusions,
        }
        if record_primary:
            self._last_kentucky_full_frontier = summary
        if root_payload is not None:
            frontier = self._kentucky_exact_frontier(
                root_payload=root_payload,
                chapter_units=chapter_units,
                chapter_payloads=chapter_payloads,
                section_frontier=section_frontier,
                section_content_sha256=section_content_sha256,
                structural_container_exclusions=structural_container_exclusions,
                empty_chapter_exclusions=empty_chapter_exclusions,
                concurrent_section_groups=concurrent_section_groups,
                section_batch_size=section_batch_size,
            )
            observed_at = datetime.now(UTC).isoformat()
            observation = {
                "boundary_first": section_frontier[0][0],
                "boundary_last": section_frontier[-1][0],
                "code_name": code_name,
                "frontier": frontier,
                "observed_at": observed_at,
            }
            setattr(
                self,
                (
                    "_last_kentucky_strict_observation"
                    if record_primary
                    else "_last_kentucky_replayed_observation"
                ),
                observation,
            )
        if write_checkpoints:
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="kentucky:complete",
                force=True,
                extra={
                    "chapters_scanned": len(chapter_units),
                    "discovered_chapters": len(chapter_units),
                    "discovered_sections": len(section_frontier),
                    "sections_scanned": len(section_frontier),
                    "structural_containers": len(structural_container_exclusions),
                    "typed_empty_chapters": len(empty_chapter_exclusions),
                    "concurrent_section_groups": len(concurrent_section_groups),
                    "concurrent_source_records": sum(
                        len(records) for records in concurrent_section_groups.values()
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
        """Reparse retained KRS pages and seal exact leaf/output parity."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "Kentucky frontier closure requires an attached acquisition ledger"
            )
        first = getattr(self, "_last_kentucky_strict_observation", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Kentucky strict KRS frontier was not observed before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        first_frontier = first.get("frontier")
        if not isinstance(first_frontier, Mapping):
            raise RuntimeError("Kentucky first exact frontier is incomplete")
        replay_root = self._replay_official_ky_frontier(
            [self._KY_STATUTES_BASE],
            frontier_name="root-index",
            content_validator=self._looks_like_kentucky_root_payload,
        )[0]
        if hashlib.sha256(replay_root).hexdigest() != str(
            first_frontier.get("root_content_sha256") or ""
        ):
            raise RuntimeError("Kentucky retained root index changed on replay")
        replay_units = self._chapter_units_from_html(
            replay_root.decode("utf-8", errors="replace")
        )
        replay_rows = await self._scrape_official_krs_tree_batched(
            code_name=str(first.get("code_name") or "Kentucky Revised Statutes"),
            chapter_units=replay_units,
            root_payload=replay_root,
            record_primary=False,
            replay_only=True,
            write_checkpoints=False,
        )
        replay = getattr(self, "_last_kentucky_replayed_observation", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("Kentucky retained KRS replay was not observed")
        replayed_frontier = replay.get("frontier")
        if not isinstance(replayed_frontier, Mapping):
            raise RuntimeError("Kentucky replayed exact frontier is incomplete")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="KY",
            source_domain="apps.legislature.ky.gov",
            official_source_url=self._KY_STATUTES_BASE,
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("observed_at") or ""),
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=int(first_frontier.get("request_batch_count") or 0),
            pagination_total=int(first_frontier.get("chapter_unit_count") or 0),
            transport={
                "chapter_frontier_requested_pages": int(
                    first_frontier.get("chapter_unit_count") or 0
                ),
                "fixture": False,
                "first_pass_requested_pages": (
                    1
                    + int(first_frontier.get("chapter_unit_count") or 0)
                    + int(first_frontier.get("section_locator_count") or 0)
                ),
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_html_pdf",
                "leaf_frontier_requested_pages": int(
                    first_frontier.get("section_locator_count") or 0
                ),
                "per_page_archive_loop": False,
                "residual_only_retries": True,
                "retained_replay_network_requests": 0,
                "root_catalog_requested_pages": 1,
                "synthetic": False,
            },
        )

    def _official_ssl_context(self, *, unverified: bool = False):
        import ssl

        if unverified:
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    def _official_http_get(self, url: str, timeout: int = 20) -> Tuple[bytes, bytes, bytes]:
        """Fetch one official Kentucky URL and retain request/response/body bytes."""
        import ssl
        import urllib.error
        import urllib.request
        from urllib.parse import urlparse

        parsed = urlparse(url)
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
                "User-Agent": "ipfs-datasets-open-us-law-kentucky/1.0",
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
            raise RuntimeError(f"official Kentucky GET failed for {url}: {last_exc}") from last_exc
        if status != 200 or not body:
            raise RuntimeError(f"official Kentucky GET returned HTTP {status} for {url}")
        response_bytes = f"HTTP/1.1 {status} OK\n{header_block}\n".encode("utf-8") + body
        return request_bytes, response_bytes, body

    def _parse_official_chapter_index(self, html: str, index_url: str) -> List[Dict[str, str]]:
        """Parse every official KRS chapter unit from the live statutes index."""
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for official Kentucky discovery") from exc

        soup = BeautifulSoup(html, "html.parser")
        units: List[Dict[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            href = urljoin(index_url, str(link.get("href") or ""))
            if not self._KY_CHAPTER_URL_RE.search(href):
                continue
            if href in seen:
                continue
            chapter_number = self._extract_chapter_number(label)
            if not chapter_number:
                id_match = re.search(r"[?&]id=(\d+)", href, flags=re.IGNORECASE)
                if not id_match or not re.match(r"^\d+[A-Za-z]?$", label):
                    continue
                chapter_number = label
            if not label.upper().startswith("CHAPTER ") and not re.match(
                r"^\d+[A-Za-z]?$", label
            ):
                if "CHAPTER" not in label.upper():
                    continue
            seen.add(href)
            units.append(
                {
                    "canonical_key": f"ky:chapter-{chapter_number.lower()}",
                    "source_url": href,
                    "label": label,
                    "chapter_number": chapter_number,
                    "text": (
                        f"Kentucky Revised Statutes {label} official chapter index "
                        f"entry retained from {href}"
                    ),
                }
            )
        return units

    def fetch_official(self, code: str = "KY"):
        """Acquire the uncapped official KRS chapter frontier.

        Returns an ``OfficialFetch`` whose rows enumerate every official
        chapter unit discovered from ``apps.legislature.ky.gov``. The
        retained body is the compact official catalog derived from the
        live index response.
        """
        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or self.state_code or "KY").strip().upper()
        if normalized != "KY":
            raise ValueError(f"KentuckyScraper cannot acquire {normalized}")
        index_url = self._KY_STATUTES_BASE
        request_bytes, response_bytes, index_body = self._official_http_get(index_url)
        html = index_body.decode("utf-8", errors="replace")
        units = self._parse_official_chapter_index(html, index_url)
        if len(units) < 3:
            raise RuntimeError(
                f"official Kentucky chapter index is incomplete: {len(units)} units"
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
            jurisdiction_code="KY",
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            body_bytes=catalog,
            source_domain="apps.legislature.ky.gov",
            source_path="/law/statutes/",
            frontier=frontier,
            rows=rows,
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=rows[0]["canonical_key"],
            last_hierarchy_unit=rows[-1]["canonical_key"],
        )


# Register this scraper with the registry
StateScraperRegistry.register("KY", KentuckyScraper)
