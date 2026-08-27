"""Scraper for Maine state laws.

This module contains the scraper for Maine statutes from the official state legislative website.
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MaineScraper(BaseStateScraper):
    """Scraper for Maine state laws from http://legislature.maine.gov"""

    OFFICIAL_DOMAIN = "legislature.maine.gov"
    OFFICIAL_ENTRY_URL = "https://legislature.maine.gov/statutes/"
    OFFICIAL_TITLE_COUNT = 64
    CORPUS_EDITION = "2026"
    CORPUS_LEGAL_AS_OF = "2026-07-01T00:00:00Z"

    _ME_SECTION_URL_RE = re.compile(
        r"/statutes/[0-9A-Za-z\-]+/title[0-9A-Za-z\-]+sec[0-9A-Za-z\-]+\.html$", re.IGNORECASE
    )
    _ME_CHAPTER_INDEX_RE = re.compile(
        r"/title[0-9A-Za-z\-]+ch[0-9A-Za-z\-]+sec0\.html$", re.IGNORECASE
    )
    _ME_OFFICIAL_TITLE_RE = re.compile(
        r"^https://legislature\.maine\.gov/statutes/(?P<title>[0-9A-Za-z\-]+)/"
        r"title(?P=title)ch0sec0\.html$",
        re.IGNORECASE,
    )
    _ME_OFFICIAL_CHAPTER_RE = re.compile(
        r"^https://legislature\.maine\.gov/statutes/(?P<title>[0-9A-Za-z\-]+)/"
        r"title(?P=title)ch(?P<chapter>[0-9A-Za-z\-]+)sec0\.html$",
        re.IGNORECASE,
    )
    _ME_OFFICIAL_SECTION_RE = re.compile(
        r"^https://legislature\.maine\.gov/(?:legis/)?statutes/"
        r"(?P<title>[0-9A-Za-z\-]+)/title(?P=title)sec"
        r"(?P<section>[0-9A-Za-z\-]+)\.html$",
        re.IGNORECASE,
    )

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind every module that determines retained Maine replay output."""

        from . import maine_section, strict_frontier_closure

        return (maine_section, strict_frontier_closure)

    @staticmethod
    def _maine_report_digest(rows: Sequence[Mapping[str, Any]]) -> str:
        """Digest one ordered, source-derived Maine frontier inventory."""

        return hashlib.sha256(
            json.dumps(
                [dict(row) for row in rows],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _maine_values_digest(values: Sequence[str]) -> str:
        return hashlib.sha256(
            json.dumps(
                [str(value) for value in values],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def _maine_section_identity(
        self,
        *,
        code_name: str,
        source_url: str,
    ) -> tuple[str, str, str]:
        """Return the source title, section, and final JSON-LD identity."""

        match = self._ME_OFFICIAL_SECTION_RE.fullmatch(str(source_url or "").strip())
        if match is None:
            raise RuntimeError(
                f"Maine strict frontier has an invalid official section URL: {source_url}"
            )
        title_number = match.group("title")
        section_number = match.group("section")
        statute_id = (
            f"{code_name} Me. Rev. Stat. tit. {title_number}, § {section_number}"
        )
        return (
            title_number,
            section_number,
            f"urn:state:me:statute:{statute_id}",
        )

    def _maine_input_evidence_context(
        self,
        *,
        source_url: str,
        payload: bytes,
        transport_receipt: Optional[Dict[str, Any]],
        parser_input_envelope: Any,
    ) -> Dict[str, Any]:
        """Verify one aligned retained parser input when a ledger is attached."""

        body = bytes(payload)
        content_sha256 = hashlib.sha256(body).hexdigest()
        envelope = parser_input_envelope
        if not isinstance(envelope, Mapping):
            to_dict = getattr(envelope, "to_dict", None)
            if callable(to_dict):
                envelope = to_dict()
        if isinstance(envelope, Mapping) and isinstance(
            envelope.get("parser_input_envelope"), Mapping
        ):
            envelope = envelope["parser_input_envelope"]
        acquisition = (
            envelope.get("acquisition", {})
            if isinstance(envelope, Mapping)
            else {}
        )
        receipt = (
            acquisition.get("receipt", {})
            if isinstance(acquisition, Mapping)
            else {}
        )
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if not isinstance(receipt, Mapping) or not receipt:
            if ledger_attached:
                raise RuntimeError(
                    "Maine strict parser input lacks retained acquisition evidence: "
                    f"{source_url}"
                )
            return {
                "content_sha256": content_sha256,
                "parser_input_receipt_sha256": "",
                "source_retrieved_at": "",
                "source_transport": "",
                "source_transport_chain": [],
                "transport_receipt": {},
            }
        retained_sha256 = str(
            (receipt.get("content") or {}).get("sha256")
            if isinstance(receipt.get("content"), Mapping)
            else ""
        ).strip().lower()
        if (
            str(receipt.get("endpoint") or "").strip().rstrip("/")
            != source_url.rstrip("/")
            or retained_sha256 != content_sha256
            or str(acquisition.get("body_sha256") or "").strip().lower()
            != content_sha256
        ):
            raise RuntimeError(
                "Maine retained acquisition evidence changed parser identity: "
                f"{source_url}"
            )
        retained_transport = (
            (receipt.get("metadata") or {}).get("transport_receipt", {})
            if isinstance(receipt.get("metadata"), Mapping)
            else {}
        )
        if not isinstance(retained_transport, Mapping) or not retained_transport:
            raise RuntimeError(
                f"Maine retained parser input lacks transport evidence: {source_url}"
            )
        from ...legal_data.state_laws_source_provenance import (
            StateLawTransportReceiptError,
            verify_state_law_transport_receipt,
        )

        try:
            verified = verify_state_law_transport_receipt(
                retained_transport,
                official_url=source_url,
                content_sha256=content_sha256,
            )
            if isinstance(transport_receipt, Mapping) and transport_receipt:
                aligned = verify_state_law_transport_receipt(
                    transport_receipt,
                    official_url=source_url,
                    content_sha256=content_sha256,
                )
                if aligned != verified:
                    raise StateLawTransportReceiptError(
                        "unaligned_transport_receipt",
                        "retained and aligned Maine receipts disagree",
                    )
        except StateLawTransportReceiptError as exc:
            raise RuntimeError(
                f"Maine parser input transport identity is incomplete: {source_url}"
            ) from exc
        receipt_sha256 = str(receipt.get("receipt_sha256") or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", receipt_sha256) is None:
            raise RuntimeError(
                f"Maine retained parser input lacks an exact receipt digest: {source_url}"
            )
        retrieved_at = str(receipt.get("retrieved_at") or "").strip()
        try:
            retrieved_time = datetime.fromisoformat(retrieved_at)
        except ValueError as exc:
            raise RuntimeError(
                f"Maine retained parser input lacks an exact observation time: {source_url}"
            ) from exc
        if retrieved_time.tzinfo is None:
            raise RuntimeError(
                f"Maine retained parser input observation time is naive: {source_url}"
            )
        retrieved_at = (
            retrieved_time.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        return {
            "content_sha256": content_sha256,
            "parser_input_receipt_sha256": receipt_sha256,
            "source_retrieved_at": retrieved_at,
            "source_transport": verified.leaf_transport,
            "source_transport_chain": list(verified.transport_chain),
            "transport_receipt": verified.to_dict(),
        }

    def _maine_exact_frontier(
        self,
        *,
        root_content_sha256: str,
        expected_title_count: int,
        title_reports: Sequence[Mapping[str, Any]],
        chapter_reports: Sequence[Mapping[str, Any]],
        section_reports: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Seal exact root/title/chapter/section membership and disposition."""

        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        if not re.fullmatch(r"[0-9a-f]{64}", str(root_content_sha256 or "")):
            raise RuntimeError("Maine exact frontier lacks a root content digest")
        if not title_reports or not chapter_reports or not section_reports:
            raise RuntimeError("Maine exact frontier has an empty hierarchy level")
        if len(title_reports) != int(expected_title_count):
            raise RuntimeError(
                "Maine exact title catalog parity failed: "
                f"expected={expected_title_count} observed={len(title_reports)}"
            )
        for label, reports in (
            ("title", title_reports),
            ("chapter", chapter_reports),
            ("section", section_reports),
        ):
            urls = [str(row.get("source_url") or "").strip() for row in reports]
            if any(not url for url in urls) or len(urls) != len(set(urls)):
                raise RuntimeError(
                    f"Maine exact {label} frontier repeated or lost source URLs"
                )

        active_chapter_count = 0
        terminal_chapter_dispositions: Dict[str, int] = {}
        for row in chapter_reports:
            chapter_disposition = str(row.get("disposition") or "").strip()
            raw_section_count = row.get("section_count")
            if isinstance(raw_section_count, bool):
                raise RuntimeError("Maine chapter frontier has an invalid section count")
            try:
                chapter_section_count = int(raw_section_count)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "Maine chapter frontier has an invalid section count"
                ) from exc
            if chapter_disposition == "section_frontier":
                if chapter_section_count <= 0:
                    raise RuntimeError(
                        "Maine active chapter lacks a nonempty section frontier"
                    )
                active_chapter_count += 1
                continue
            if chapter_disposition not in {
                "never_effective_chapter",
                "repealed_chapter",
            }:
                raise RuntimeError(
                    "Maine chapter lacks an exact active or terminal disposition"
                )
            if chapter_section_count != 0:
                raise RuntimeError(
                    "Maine terminal chapter unexpectedly exposes a section frontier"
                )
            terminal_chapter_dispositions[chapter_disposition] = (
                terminal_chapter_dispositions.get(chapter_disposition, 0) + 1
            )

        operative_reports = [
            row
            for row in section_reports
            if str(row.get("disposition") or "") == "operative"
        ]
        terminal_reports = [
            row
            for row in section_reports
            if str(row.get("disposition") or "") != "operative"
        ]
        operative_keys = [
            str(row.get("canonical_identity") or "").strip()
            for row in operative_reports
        ]
        terminal_keys = [
            str(row.get("canonical_identity") or "").strip()
            for row in terminal_reports
        ]
        if (
            any(not key for key in [*operative_keys, *terminal_keys])
            or len(operative_keys) != len(set(operative_keys))
            or len(terminal_keys) != len(set(terminal_keys))
            or set(operative_keys) & set(terminal_keys)
        ):
            raise RuntimeError(
                "Maine operative and terminal canonical identities are not disjoint and exact"
            )
        terminal_dispositions: Dict[str, int] = {}
        for row in terminal_reports:
            disposition = str(row.get("disposition") or "").strip()
            if not disposition:
                raise RuntimeError("Maine terminal section lacks an exact disposition")
            terminal_dispositions[disposition] = (
                terminal_dispositions.get(disposition, 0) + 1
            )
        disposition = {
            "discovered": len(section_reports),
            "fetched": len(operative_reports),
            "excluded": len(terminal_reports),
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        }
        if disposition["discovered"] != sum(
            disposition[field]
            for field in (
                "fetched",
                "excluded",
                "quarantined",
                "failed_final",
                "duplicates",
            )
        ):
            raise RuntimeError("Maine exact section disposition algebra did not close")

        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": False,
            "catalog_expected_units": int(expected_title_count),
            "catalog_observed_units": len(title_reports),
            "catalog_parity": True,
            "active_chapter_document_count": active_chapter_count,
            "chapter_document_count": len(chapter_reports),
            "chapter_frontier_sha256": self._maine_report_digest(chapter_reports),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": len(section_reports),
            "operative_canonical_key_count": len(operative_keys),
            "operative_canonical_keys_sha256": self._maine_values_digest(
                operative_keys
            ),
            "pagination_closed": True,
            "root_content_sha256": root_content_sha256,
            "root_url": self.OFFICIAL_ENTRY_URL,
            "schema_version": "maine-source-derived-html-frontier-v2",
            "scope_closed": True,
            "section_input_frontier_sha256": self._maine_report_digest(
                section_reports
            ),
            "source_section_count": len(section_reports),
            "terminal_canonical_key_count": len(terminal_keys),
            "terminal_canonical_keys_sha256": self._maine_values_digest(
                terminal_keys
            ),
            "terminal_chapter_document_count": sum(
                terminal_chapter_dispositions.values()
            ),
            "terminal_chapter_dispositions": dict(
                sorted(terminal_chapter_dispositions.items())
            ),
            "terminal_dispositions": dict(sorted(terminal_dispositions.items())),
            "title_document_count": len(title_reports),
            "title_frontier_sha256": self._maine_report_digest(title_reports),
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(section_reports),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._ME_SECTION_URL_RE.search(source) and not self._ME_CHAPTER_INDEX_RE.search(
                source
            ):
                if str(statute.section_number or "").startswith("Section-"):
                    m = re.search(
                        r"title[0-9A-Za-z\-]+sec([0-9A-Za-z\-]+)\.html$", source, re.IGNORECASE
                    )
                    if m:
                        statute.section_number = m.group(1)
                filtered.append(statute)
        return filtered

    def get_base_url(self) -> str:
        """Return the base URL for Maine's legislative website."""
        return "http://legislature.maine.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Maine."""
        return [
            {"name": "Maine Revised Statutes", "url": f"{self.get_base_url()}/", "type": "Code"}
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Maine's legislative website.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .maine_constitution import (
            configured_constitution_html_path,
            parse_maine_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_maine_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Maine Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .maine_section import (
            configured_section_html_path,
            parse_maine_section_html,
        )

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_maine_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://legislature.maine.gov/legis/statutes/17-A/title17-Asec201.html",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        official = await self._scrape_official_title_chapter_section_tree(
            code_name,
            max_statutes=limit,
        )
        if official:
            return official if limit is None else official[: int(limit)]

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=max(1, int(limit or 2)),
            )
            if direct:
                return direct if limit is None else direct[: int(limit)]

        if self._full_corpus_enabled() and max_statutes is None:
            return []

        return_threshold = int(limit) if limit is not None else 160
        candidate_urls = [
            "https://legislature.maine.gov/statutes/1/title1ch1sec0.html",
            "https://legislature.maine.gov/statutes/17-A/title17-Ach1sec0.html",
            "https://legislature.maine.gov/statutes/",
            code_url,
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            if "justia.com" in str(candidate).lower() or "findlaw.com" in str(candidate).lower():
                continue

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Me. Rev. Stat.",
                        max_sections=max(10, return_threshold),
                        wait_for_selector="a[href*='sec'][href$='.html'], a[href*='ch'][href$='sec0.html']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if limit is not None and len(statutes) >= int(limit):
                        return statutes[: int(limit)]
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name, candidate, "Me. Rev. Stat.", max_sections=max(10, return_threshold)
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if limit is not None and len(statutes) >= int(limit):
                return statutes[: int(limit)]

        return best_statutes if limit is None else best_statutes[: int(limit)]

    async def _scrape_official_title_chapter_section_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
        *,
        record_primary: bool = True,
        write_checkpoints: bool = True,
        retained_only: bool = False,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        if retained_only and limit is not None:
            raise RuntimeError("Maine retained replay must traverse the uncapped frontier")
        root_url = self.OFFICIAL_ENTRY_URL
        input_evidence_by_url: Dict[str, Dict[str, Any]] = {}
        frontier_batch_stats: List[Dict[str, Any]] = []

        def _write_checkpoint(*args: Any, **kwargs: Any) -> bool:
            if not write_checkpoints:
                return False
            return bool(self._write_partial_checkpoint(*args, **kwargs))

        if retained_only:
            from .strict_frontier_closure import replay_exact_retained_state_input

            root_raw = replay_exact_retained_state_input(
                self,
                official_url=root_url,
                sanitized_request={"method": "GET", "url": root_url},
                frontier_name="Maine root catalog",
                refresh=False,
            )
            input_evidence_by_url[root_url] = {
                "content_sha256": hashlib.sha256(root_raw).hexdigest(),
                "parser_input_receipt_sha256": "",
                "source_retrieved_at": "",
                "source_transport": "retained_parser_input",
                "source_transport_chain": ["retained_parser_input"],
                "transport_receipt": {},
            }
        else:
            root_raw = await self._fetch_page_content_with_archival_fallback(
                root_url, timeout_seconds=25
            )
        if not root_raw:
            if limit is None:
                raise RuntimeError("Maine official root catalog is empty")
            return []
        if not retained_only:
            input_evidence_by_url[root_url] = self._maine_input_evidence_context(
                source_url=root_url,
                payload=bytes(root_raw),
                transport_receipt=dict(
                    getattr(self, "_last_page_fetch_transport_evidence", {}) or {}
                ),
                parser_input_envelope=getattr(
                    self, "_last_page_parser_input_envelope", None
                ),
            )
        root_html = (
            root_raw.decode("utf-8", errors="replace")
            if isinstance(root_raw, bytes)
            else str(root_raw)
        )
        root_soup = BeautifulSoup(root_html, "html.parser")

        # An uncapped production replay rebuilds semantic rows from retained
        # parser inputs.  Parser changes must never inherit rows or positional
        # cursors produced by an older admission policy.
        if limit is None:
            resumed: List[NormalizedStatute] = []
            checkpoint_progress: Dict[str, object] = {}
        else:
            resumed = self._load_partial_checkpoint_statutes(
                code_name=code_name, max_statutes=max_statutes
            )
            checkpoint_progress = self._load_partial_checkpoint_progress()
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        seen_keys: set[str] = set()
        title_reports: List[Dict[str, Any]] = []
        chapter_reports: List[Dict[str, Any]] = []
        section_reports: List[Dict[str, Any]] = []

        def _extend_unique(batch: List[NormalizedStatute]) -> None:
            for statute in batch:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                source_url = str(statute.source_url or "").strip()
                if key and key in seen_keys:
                    if limit is None:
                        raise RuntimeError(
                            f"Maine strict frontier repeated statute identity: {statute.statute_id}"
                        )
                    continue
                if source_url and source_url in seen_sections:
                    if limit is None:
                        raise RuntimeError(
                            f"Maine strict frontier repeated section URL: {source_url}"
                        )
                    continue
                if key:
                    seen_keys.add(key)
                if source_url:
                    seen_sections.add(source_url)
                statutes.append(statute)
                if limit is not None and len(statutes) >= limit:
                    break

        if resumed:
            _extend_unique(resumed)
            self.logger.info(
                "Maine official tree: resumed %s statutes from partial checkpoint",
                len(statutes),
            )
        resume_titles_scanned = max(0, int(checkpoint_progress.get("titles_scanned") or 0))
        resume_chapters_scanned = max(0, int(checkpoint_progress.get("chapters_scanned") or 0))
        resume_sections_scanned = max(0, int(checkpoint_progress.get("sections_scanned") or 0))
        resume_discovered_sections = max(
            0, int(checkpoint_progress.get("discovered_sections") or 0)
        )
        title_rewind = max(0, int(self._env_int("STATE_SCRAPER_ME_RESUME_TITLE_REWIND", default=1)))
        chapter_rewind = max(
            0, int(self._env_int("STATE_SCRAPER_ME_RESUME_CHAPTER_REWIND", default=10))
        )
        resume_title_floor = max(0, resume_titles_scanned - title_rewind)
        resume_chapter_floor = max(0, resume_chapters_scanned - chapter_rewind)
        title_urls = []
        seen_titles = set()
        for link in root_soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not re.search(
                r"/?statutes/[0-9A-Za-z\-]+/title[0-9A-Za-z\-]+ch0sec0\.html$|^[0-9A-Za-z\-]+/title[0-9A-Za-z\-]+ch0sec0\.html$",
                href,
                re.IGNORECASE,
            ):
                continue
            full_url = urljoin(root_url, href)
            if full_url in seen_titles:
                continue
            seen_titles.add(full_url)
            title_urls.append(full_url)

        self.logger.info(
            "Maine official tree: discovered_titles=%s max_statutes=%s",
            len(title_urls),
            limit or "unbounded",
        )
        if limit is None and not title_urls:
            raise RuntimeError("Maine official root catalog produced no title frontier")
        if limit is None:
            title_identities: List[str] = []
            for title_url in title_urls:
                match = self._ME_OFFICIAL_TITLE_RE.fullmatch(title_url)
                if match is None:
                    raise RuntimeError(
                        f"Maine title frontier has an invalid official URL: {title_url}"
                    )
                title_identities.append(match.group("title").casefold())
            if len(title_identities) != len(set(title_identities)):
                raise RuntimeError("Maine title frontier repeats a title identity")
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        expected_title_count = (
            int(self.OFFICIAL_TITLE_COUNT) if ledger_attached else len(title_urls)
        )
        if limit is None and len(title_urls) != expected_title_count:
            raise RuntimeError(
                "Maine official title catalog parity failed: "
                f"expected={expected_title_count} observed={len(title_urls)}"
            )
        terminal_sections: List[Dict[str, str]] = []
        terminal_chapters: List[Dict[str, str]] = []

        def _terminal_checkpoint_fields() -> Dict[str, object]:
            section_counts: Dict[str, int] = {}
            for record in terminal_sections:
                disposition = str(record.get("disposition") or "").strip()
                if disposition:
                    section_counts[disposition] = (
                        section_counts.get(disposition, 0) + 1
                    )
            chapter_counts: Dict[str, int] = {}
            for record in terminal_chapters:
                disposition = str(record.get("disposition") or "").strip()
                if disposition:
                    chapter_counts[disposition] = (
                        chapter_counts.get(disposition, 0) + 1
                    )
            return {
                "terminal_sections_classified": len(terminal_sections),
                "terminal_disposition_counts": dict(sorted(section_counts.items())),
                "terminal_section_dispositions": list(terminal_sections),
                "terminal_chapters_classified": len(terminal_chapters),
                "terminal_chapter_disposition_counts": dict(
                    sorted(chapter_counts.items())
                ),
                "terminal_chapter_dispositions": list(terminal_chapters),
            }

        _write_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="maine:title-discovery",
            replace_existing_rows=limit is None,
            extra={
                "titles_scanned": 0,
                "discovered_titles": int(len(title_urls)),
                "chapters_scanned": 0,
                "sections_scanned": int(max(len(statutes), resume_sections_scanned)),
                "discovered_sections": int(max(len(statutes), resume_discovered_sections)),
                "codes_completed": 0,
                "codes_total": 1,
                **_terminal_checkpoint_fields(),
            },
        )

        processed_chapters = 0
        sections_scanned_total = int(max(len(statutes), resume_sections_scanned))
        sections_discovered_total = int(max(len(statutes), resume_discovered_sections))
        section_concurrency = max(
            1, int(self._env_int("STATE_SCRAPER_ME_SECTION_CONCURRENCY", default=8))
        )

        async def _fetch_aligned_frontier(
            frontier_urls: List[str],
            *,
            frontier_name: str,
        ) -> List[bytes]:
            if not frontier_urls:
                return []
            if retained_only:
                from .strict_frontier_closure import replay_exact_retained_state_input

                payloads: List[bytes] = []
                for official_url in frontier_urls:
                    raw = replay_exact_retained_state_input(
                        self,
                        official_url=official_url,
                        sanitized_request={"method": "GET", "url": official_url},
                        frontier_name=f"Maine {frontier_name} frontier",
                        refresh=False,
                    )
                    payloads.append(raw)
                    input_evidence_by_url[official_url] = {
                        "content_sha256": hashlib.sha256(raw).hexdigest(),
                        "parser_input_receipt_sha256": "",
                        "source_retrieved_at": "",
                        "source_transport": "retained_parser_input",
                        "source_transport_chain": ["retained_parser_input"],
                        "transport_receipt": {},
                    }
                frontier_batch_stats.append(
                    {
                        "frontier_name": frontier_name,
                        "network_requested_pages": 0,
                        "requested_pages": len(frontier_urls),
                        "retained_replay_pages": len(frontier_urls),
                    }
                )
                return payloads
            batch = await self._fetch_page_contents_with_archival_fallback(
                frontier_urls,
                timeout_seconds=25,
                max_concurrency=section_concurrency,
                prefer_direct=True,
            )
            aligned_lengths = {
                len(batch.urls),
                len(batch.payloads),
                len(batch.errors),
                len(batch.transport_receipts),
                len(batch.parser_input_envelopes),
            }
            if aligned_lengths != {len(frontier_urls)}:
                raise RuntimeError(
                    f"Maine {frontier_name} frontier returned unaligned acquisition rows"
                )
            if list(batch.urls) != frontier_urls:
                raise RuntimeError(
                    f"Maine {frontier_name} frontier changed URL order or identity"
                )
            if limit is None:
                failures = [
                    {
                        "url": url,
                        "error": error or "empty parser input",
                    }
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
                        f"Maine {frontier_name} frontier is incomplete; "
                        f"unresolved exact URLs: {failures}"
                    )
            payloads = []
            for url, payload, receipt, envelope in zip(
                batch.urls,
                batch.payloads,
                batch.transport_receipts,
                batch.parser_input_envelopes,
                strict=True,
            ):
                raw = bytes(payload or b"")
                if raw:
                    input_evidence_by_url[url] = self._maine_input_evidence_context(
                        source_url=url,
                        payload=raw,
                        transport_receipt=(dict(receipt) if isinstance(receipt, Mapping) else None),
                        parser_input_envelope=envelope,
                    )
                payloads.append(raw)
            frontier_batch_stats.append(
                {
                    "frontier_name": frontier_name,
                    **dict(batch.stats or {}),
                }
            )
            return payloads

        # The root page gives us every title locator up front.  For an
        # uncapped production crawl, submit that known same-domain frontier in
        # one aligned request so the shared archive layer can query inventory
        # once and coalesce title pages that share a WARC object.  Bounded
        # crawls retain their lazy behavior and do not fetch beyond the cap.
        title_payload_by_url: Dict[str, bytes] = {}
        if limit is None:
            title_frontier_urls = [
                title_url
                for title_index, title_url in enumerate(title_urls, start=1)
                if title_index >= resume_title_floor
            ]
            title_payloads = await _fetch_aligned_frontier(
                title_frontier_urls,
                frontier_name="title-index",
            )
            title_payload_by_url = dict(
                zip(title_frontier_urls, title_payloads, strict=True)
            )

        for title_index, title_url in enumerate(title_urls, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            if title_index < resume_title_floor:
                continue
            title_raw = title_payload_by_url.get(title_url)
            if title_raw is None:
                title_raw = await self._fetch_page_content_with_archival_fallback(
                    title_url, timeout_seconds=25
                )
            if not title_raw:
                continue
            title_html = (
                title_raw.decode("utf-8", errors="replace")
                if isinstance(title_raw, bytes)
                else str(title_raw)
            )
            title_soup = BeautifulSoup(title_html, "html.parser")
            strict_title_match = self._ME_OFFICIAL_TITLE_RE.fullmatch(title_url)
            strict_title_number = (
                strict_title_match.group("title")
                if strict_title_match is not None
                else ""
            )
            from .maine_section import title_toc_chapter_links

            toc_chapter_links = title_toc_chapter_links(
                title_html,
                base_url=title_url,
            )
            toc_chapter_labels = {
                href: " ".join(str(name or "").split())
                for href, name in toc_chapter_links
            }
            chapter_urls = []
            chapter_labels: Dict[str, str] = {}
            seen_chapters = set()
            for link in title_soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                if not re.search(
                    r"title[0-9A-Za-z\-]+ch[0-9A-Za-z\-]+sec0\.html$", href, re.IGNORECASE
                ):
                    continue
                full_url = urljoin(title_url, href)
                if full_url in seen_chapters or full_url.endswith("ch0sec0.html"):
                    continue
                seen_chapters.add(full_url)
                chapter_urls.append(full_url)
                chapter_labels[full_url] = str(
                    toc_chapter_labels.get(full_url)
                    or " ".join(link.get_text(" ", strip=True).split())
                )

            for href, name in toc_chapter_links:
                if href in seen_chapters or href.endswith("ch0sec0.html"):
                    continue
                seen_chapters.add(href)
                chapter_urls.append(href)
                chapter_labels[href] = " ".join(str(name or "").split())
            if limit is None and not chapter_urls:
                raise RuntimeError(
                    f"Maine official title page produced no chapter frontier: {title_url}"
                )
            if limit is None:
                for chapter_url in chapter_urls:
                    chapter_match = self._ME_OFFICIAL_CHAPTER_RE.fullmatch(chapter_url)
                    if (
                        chapter_match is None
                        or chapter_match.group("chapter") == "0"
                        or chapter_match.group("title").casefold()
                        != strict_title_number.casefold()
                    ):
                        raise RuntimeError(
                            "Maine title page changed its chapter hierarchy identity: "
                            f"{title_url} -> {chapter_url}"
                        )
                title_reports.append(
                    {
                        "chapter_count": len(chapter_urls),
                        "content_sha256": str(
                            input_evidence_by_url.get(title_url, {}).get(
                                "content_sha256"
                            )
                            or hashlib.sha256(bytes(title_raw)).hexdigest()
                        ),
                        "source_url": title_url,
                    }
                )

            chapter_payload_by_url: Dict[str, bytes] = {}
            if limit is None:
                chapter_frontier_urls = [
                    chapter_url
                    for offset, chapter_url in enumerate(chapter_urls, start=1)
                    if processed_chapters + offset >= resume_chapter_floor
                ]
                chapter_payloads = await _fetch_aligned_frontier(
                    chapter_frontier_urls,
                    frontier_name="chapter-index",
                )
                chapter_payload_by_url = dict(
                    zip(chapter_frontier_urls, chapter_payloads, strict=True)
                )

            self.logger.info(
                "Maine official tree: title_url=%s discovered_chapters=%s statutes_so_far=%s",
                title_url,
                len(chapter_urls),
                len(statutes),
            )
            _write_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="maine:title-scan",
                replace_existing_rows=limit is None,
                extra={
                    "titles_scanned": int(title_index),
                    "discovered_titles": int(len(title_urls)),
                    "chapters_scanned": int(processed_chapters),
                    "sections_scanned": int(sections_scanned_total),
                    "discovered_sections": int(sections_discovered_total),
                    "discovered_chapters": int(len(chapter_urls)),
                    "codes_completed": 0,
                    "codes_total": 1,
                    **_terminal_checkpoint_fields(),
                },
            )

            for chapter_url in chapter_urls:
                if limit is not None and len(statutes) >= limit:
                    break
                processed_chapters += 1
                if processed_chapters < resume_chapter_floor:
                    continue
                chapter_raw = chapter_payload_by_url.get(chapter_url)
                if chapter_raw is None:
                    chapter_raw = await self._fetch_page_content_with_archival_fallback(
                        chapter_url, timeout_seconds=25
                    )
                if not chapter_raw:
                    continue
                chapter_html = (
                    chapter_raw.decode("utf-8", errors="replace")
                    if isinstance(chapter_raw, bytes)
                    else str(chapter_raw)
                )
                chapter_soup = BeautifulSoup(chapter_html, "html.parser")
                chapter_catalog_label = str(
                    chapter_labels.get(chapter_url) or ""
                ).strip()
                chapter_content_sha256 = str(
                    input_evidence_by_url.get(chapter_url, {}).get(
                        "content_sha256"
                    )
                    or hashlib.sha256(bytes(chapter_raw)).hexdigest()
                )
                section_candidates: List[str] = []
                seen_local_candidates: set[str] = set()
                for link in chapter_soup.find_all("a", href=True):
                    href = str(link.get("href") or "").strip()
                    if not re.search(
                        r"title[0-9A-Za-z\-]+sec[0-9A-Za-z\-]+\.html$", href, re.IGNORECASE
                    ):
                        continue
                    section_url = urljoin(chapter_url, href)
                    if section_url.endswith("sec0.html"):
                        continue
                    if section_url in seen_sections or section_url in seen_local_candidates:
                        continue
                    seen_local_candidates.add(section_url)
                    section_candidates.append(section_url)
                sections_discovered_total += len(section_candidates)
                from .maine_section import (
                    source_bound_maine_chapter_disposition,
                    source_bound_maine_section_disposition,
                )

                chapter_disposition = "section_frontier"
                if not section_candidates:
                    chapter_disposition = str(
                        source_bound_maine_chapter_disposition(
                            chapter_html,
                            source_url=chapter_url,
                            title_catalog_label=chapter_catalog_label,
                        )
                        or ""
                    )
                    if limit is None and not chapter_disposition:
                        raise RuntimeError(
                            "Maine official chapter page produced no section frontier "
                            "and has no source-bound terminal disposition: "
                            f"{chapter_url}"
                        )
                    if chapter_disposition:
                        terminal_chapters.append(
                            {
                                "catalog_label": chapter_catalog_label,
                                "catalog_label_sha256": hashlib.sha256(
                                    chapter_catalog_label.encode("utf-8")
                                ).hexdigest(),
                                "content_sha256": chapter_content_sha256,
                                "disposition": chapter_disposition,
                                "source_url": chapter_url,
                                "title_source_url": title_url,
                            }
                        )
                if limit is None:
                    for section_url in section_candidates:
                        section_title, _section, _canonical = (
                            self._maine_section_identity(
                                code_name=code_name,
                                source_url=section_url,
                            )
                        )
                        if section_title.casefold() != strict_title_number.casefold():
                            raise RuntimeError(
                                "Maine chapter page changed its section hierarchy identity: "
                                f"{chapter_url} -> {section_url}"
                            )
                    chapter_reports.append(
                        {
                            "catalog_label": chapter_catalog_label,
                            "content_sha256": chapter_content_sha256,
                            "disposition": chapter_disposition,
                            "section_count": len(section_candidates),
                            "source_url": chapter_url,
                            "title_source_url": title_url,
                        }
                    )

                def _record_section(statute: Optional[NormalizedStatute]) -> None:
                    if statute is None:
                        return
                    _extend_unique([statute])
                    if len(statutes) == 1 or len(statutes) % 25 == 0:
                        self.logger.info(
                            "Maine official tree: chapters_processed=%s statutes_so_far=%s",
                            processed_chapters,
                            len(statutes),
                        )
                        _write_checkpoint(
                            statutes,
                            code_name=code_name,
                            stage_label="maine:section-scan",
                            replace_existing_rows=limit is None,
                            extra={
                                "titles_scanned": int(title_index),
                                "discovered_titles": int(len(title_urls)),
                                "chapters_scanned": int(processed_chapters),
                                "sections_scanned": int(sections_scanned_total),
                                "discovered_sections": int(sections_discovered_total),
                                "codes_completed": 0,
                                "codes_total": 1,
                                **_terminal_checkpoint_fields(),
                            },
                        )

                scanned_sections = 0
                if section_candidates:
                    section_payloads = await _fetch_aligned_frontier(
                        section_candidates,
                        frontier_name="section",
                    )
                    for section_url, raw in zip(
                        section_candidates,
                        section_payloads,
                        strict=True,
                    ):
                        if limit is not None and len(statutes) >= limit:
                            break
                        scanned_sections += 1
                        sections_scanned_total += 1
                        html = (
                            raw.decode("utf-8", errors="replace")
                            if isinstance(raw, bytes)
                            else str(raw or "")
                        )
                        disposition = source_bound_maine_section_disposition(
                            html,
                            source_url=section_url,
                        )
                        title_number, section_number, canonical_identity = (
                            self._maine_section_identity(
                                code_name=code_name,
                                source_url=section_url,
                            )
                        )
                        input_evidence = dict(
                            input_evidence_by_url.get(section_url, {})
                        )
                        content_sha256 = str(
                            input_evidence.get("content_sha256")
                            or hashlib.sha256(bytes(raw)).hexdigest()
                        )
                        if disposition is not None:
                            section_match = re.search(
                                r"sec(?P<section>[0-9A-Za-z\-]+)\.html$",
                                section_url,
                                flags=re.IGNORECASE,
                            )
                            terminal_sections.append(
                                {
                                    "content_sha256": hashlib.sha256(
                                        raw
                                        if isinstance(raw, bytes)
                                        else str(raw).encode("utf-8")
                                    ).hexdigest(),
                                    "disposition": disposition,
                                    "section_number": (
                                        section_match.group("section")
                                        if section_match is not None
                                        else ""
                                    ),
                                    "source_url": section_url,
                                }
                            )
                            seen_sections.add(section_url)
                            if limit is None:
                                section_reports.append(
                                    {
                                        "canonical_identity": canonical_identity,
                                        "content_sha256": content_sha256,
                                        "disposition": disposition,
                                        "section_number": section_number,
                                        "source_url": section_url,
                                        "title_number": title_number,
                                    }
                                )
                            continue
                        statute = (
                            self._parse_official_section_statute(
                                code_name,
                                section_url,
                                raw,
                                allow_legacy_fallback=limit is not None,
                            )
                            if raw
                            else None
                        )
                        if statute is None and limit is None:
                            raise RuntimeError(
                                "Maine retained section body failed primary MRS "
                                "parsing and has no source-bound terminal "
                                f"disposition: {section_url}"
                            )
                        if statute is not None and limit is None:
                            if (
                                str(statute.state_code or "").strip().upper() != "ME"
                                or str(statute.source_url or "").strip() != section_url
                                or str(statute.title_number or "").strip().casefold()
                                != title_number.casefold()
                                or str(statute.section_number or "").strip().casefold()
                                != section_number.casefold()
                                or f"urn:state:me:statute:{statute.statute_id}"
                                != canonical_identity
                            ):
                                raise RuntimeError(
                                    "Maine normalized section changed its source-derived "
                                    f"identity: {section_url}"
                                )
                            statute.structured_data = {
                                **dict(statute.structured_data or {}),
                                "content_sha256": content_sha256,
                                "parser_input_receipt_sha256": str(
                                    input_evidence.get(
                                        "parser_input_receipt_sha256"
                                    )
                                    or ""
                                ),
                                "source_retrieved_at": str(
                                    input_evidence.get("source_retrieved_at") or ""
                                ),
                                "source_transport": str(
                                    input_evidence.get("source_transport") or ""
                                ),
                                "source_transport_chain": list(
                                    input_evidence.get("source_transport_chain") or []
                                ),
                                "transport_receipt": dict(
                                    input_evidence.get("transport_receipt") or {}
                                ),
                            }
                        _record_section(statute)
                        if statute is not None and limit is None:
                            section_reports.append(
                                {
                                    "canonical_identity": canonical_identity,
                                    "content_sha256": content_sha256,
                                    "disposition": "operative",
                                    "section_number": section_number,
                                    "source_url": section_url,
                                    "title_number": title_number,
                                }
                            )
                if scanned_sections and (
                    scanned_sections == len(section_candidates) or scanned_sections % 200 == 0
                ):
                    _write_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="maine:section-scan",
                        replace_existing_rows=limit is None,
                        extra={
                            "titles_scanned": int(title_index),
                            "discovered_titles": int(len(title_urls)),
                            "chapters_scanned": int(processed_chapters),
                            "sections_scanned": int(sections_scanned_total),
                            "discovered_sections": int(sections_discovered_total),
                            "codes_completed": 0,
                            "codes_total": 1,
                            **_terminal_checkpoint_fields(),
                        },
                    )

        strict_frontier: Optional[Dict[str, Any]] = None
        if limit is None:
            if not statutes:
                raise RuntimeError(
                    "Maine exact official frontier produced no operative statutes"
                )
            if len(title_reports) != len(title_urls):
                raise RuntimeError("Maine exact title traversal did not close")
            if len(chapter_reports) != processed_chapters:
                raise RuntimeError("Maine exact chapter traversal did not close")
            if len(section_reports) != sections_discovered_total:
                raise RuntimeError(
                    "Maine exact section traversal changed discovered membership: "
                    f"expected={sections_discovered_total} observed={len(section_reports)}"
                )
            root_content_sha256 = str(
                input_evidence_by_url.get(root_url, {}).get("content_sha256")
                or hashlib.sha256(bytes(root_raw)).hexdigest()
            )
            strict_frontier = self._maine_exact_frontier(
                root_content_sha256=root_content_sha256,
                expected_title_count=expected_title_count,
                title_reports=title_reports,
                chapter_reports=chapter_reports,
                section_reports=section_reports,
            )
            replayed_at = datetime.now(timezone.utc).isoformat()
            retained_observation_times = sorted(
                str(evidence.get("source_retrieved_at") or "").strip()
                for evidence in input_evidence_by_url.values()
                if str(evidence.get("source_retrieved_at") or "").strip()
            )
            if ledger_attached and not retained_only and len(
                retained_observation_times
            ) != len(input_evidence_by_url):
                raise RuntimeError(
                    "Maine strict frontier lost retained source observation times"
                )
            if retained_observation_times:
                observed_at = retained_observation_times[-1]
                source_observation = {
                    "first_retrieved_at": retained_observation_times[0],
                    "last_retrieved_at": retained_observation_times[-1],
                    "unique_parser_input_count": len(input_evidence_by_url),
                }
            elif retained_only:
                primary_observation = getattr(
                    self, "_last_maine_full_frontier", {}
                )
                source_observation = dict(
                    primary_observation.get("source_observation") or {}
                ) if isinstance(primary_observation, Mapping) else {}
                observed_at = str(
                    source_observation.get("last_retrieved_at")
                    or (
                        primary_observation.get("observed_at")
                        if isinstance(primary_observation, Mapping)
                        else ""
                    )
                    or ""
                ).strip()
                if not observed_at or not source_observation:
                    raise RuntimeError(
                        "Maine retained replay lost its first source observation"
                    )
            else:
                observed_at = replayed_at
                source_observation = {
                    "first_retrieved_at": observed_at,
                    "last_retrieved_at": observed_at,
                    "unique_parser_input_count": len(input_evidence_by_url),
                }
            terminal_canonical_keys = [
                str(row["canonical_identity"])
                for row in section_reports
                if str(row.get("disposition") or "") != "operative"
            ]
            observation = {
                "boundary_first": str(section_reports[0]["source_url"]),
                "boundary_last": str(section_reports[-1]["source_url"]),
                "code_name": code_name,
                "edition": self.CORPUS_EDITION,
                "frontier": strict_frontier,
                "legal_as_of": self.CORPUS_LEGAL_AS_OF,
                "observed_at": observed_at,
                "replayed_at": replayed_at,
                "source_observation": source_observation,
                "terminal_canonical_keys": terminal_canonical_keys,
                "terminal_chapter_dispositions": list(terminal_chapters),
                "transport_batch_stats": list(frontier_batch_stats),
            }
            setattr(
                self,
                (
                    "_last_maine_full_frontier"
                    if record_primary
                    else "_last_maine_replayed_frontier"
                ),
                observation,
            )
            self._last_maine_strict_closure = {
                "active_chapter_documents": int(
                    strict_frontier["active_chapter_document_count"]
                ),
                "chapter_documents": len(chapter_reports),
                "closed": True,
                "frontier": strict_frontier,
                "observed_at": observed_at,
                "operative_sections": len(statutes),
                "schema": "maine-source-derived-strict-closure-v2",
                "source_sections": len(section_reports),
                "terminal_chapter_dispositions": dict(
                    strict_frontier["terminal_chapter_dispositions"]
                ),
                "terminal_chapters": int(
                    strict_frontier["terminal_chapter_document_count"]
                ),
                "terminal_sections": len(terminal_canonical_keys),
                "title_documents": len(title_reports),
                "unclassified_sections": 0,
            }

        _write_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="maine:complete",
            force=True,
            replace_existing_rows=limit is None,
            extra={
                "titles_scanned": int(len(title_urls)),
                "discovered_titles": int(len(title_urls)),
                "chapters_scanned": int(processed_chapters),
                "sections_scanned": int(sections_scanned_total),
                "discovered_sections": int(sections_discovered_total),
                "codes_completed": 1,
                "codes_total": 1,
                **(
                    {
                        "disposition": dict(strict_frontier["disposition"]),
                        "frontier_digest_sha256": str(
                            strict_frontier["frontier_digest_sha256"]
                        ),
                    }
                    if strict_frontier is not None
                    else {}
                ),
                **_terminal_checkpoint_fields(),
            },
        )
        return statutes

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Replay retained Maine hierarchy inputs and seal exact row parity."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Maine frontier closure requires an attached ledger")
        first = getattr(self, "_last_maine_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Maine source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        replay_rows = await self._scrape_official_title_chapter_section_tree(
            str(first.get("code_name") or "Maine Revised Statutes"),
            max_statutes=None,
            record_primary=False,
            write_checkpoints=False,
            retained_only=True,
        )
        replay = getattr(self, "_last_maine_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("Maine retained strict frontier replay was not observed")
        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier, Mapping
        ):
            raise RuntimeError("Maine strict frontier observations are incomplete")

        output_keys_raw = canonical_output_projection.get("canonical_keys")
        if not isinstance(output_keys_raw, Sequence) or isinstance(
            output_keys_raw, (str, bytes, bytearray)
        ):
            raise RuntimeError("Maine canonical output lacks exact identities")
        output_keys = [str(key).strip() for key in output_keys_raw]
        terminal_keys_raw = first.get("terminal_canonical_keys")
        if not isinstance(terminal_keys_raw, Sequence) or isinstance(
            terminal_keys_raw, (str, bytes, bytearray)
        ):
            raise RuntimeError("Maine strict frontier lacks terminal identities")
        terminal_keys = [str(key).strip() for key in terminal_keys_raw]
        if (
            any(not key for key in terminal_keys)
            or len(terminal_keys) != len(set(terminal_keys))
            or set(output_keys) & set(terminal_keys)
        ):
            raise RuntimeError(
                "Maine terminal canonical identities escaped into final output"
            )
        if len(terminal_keys) != int(
            first_frontier.get("terminal_canonical_key_count") or 0
        ):
            raise RuntimeError("Maine terminal identity count changed before closure")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        batch_stats = [
            row
            for row in list(first.get("transport_batch_stats") or [])
            if isinstance(row, Mapping)
        ]
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="ME",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("legal_as_of") or ""),
            edition=str(first.get("edition") or ""),
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=int(first_frontier.get("source_section_count") or 0),
            pagination_total=(
                int(first_frontier.get("title_document_count") or 0)
                + int(first_frontier.get("chapter_document_count") or 0)
            ),
            transport={
                "fixture": False,
                "first_pass_request_batches": len(batch_stats),
                "first_pass_requested_pages": sum(
                    int(row.get("requested_pages") or 0) for row in batch_stats
                ),
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_root_and_plural_html",
                "per_page_archive_loop": False,
                "retained_source_observation": dict(
                    first.get("source_observation") or {}
                ),
                "retained_replay_network_requests": 0,
                "retained_replayed_at": str(replay.get("replayed_at") or ""),
                "synthetic": False,
            },
        )

    async def _build_official_section_statute(
        self,
        code_name: str,
        url: str,
    ) -> Optional[NormalizedStatute]:
        raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
        return self._parse_official_section_statute(code_name, url, raw)

    def _parse_official_section_statute(
        self,
        code_name: str,
        url: str,
        raw: bytes,
        *,
        allow_legacy_fallback: bool = True,
    ) -> Optional[NormalizedStatute]:
        """Parse one already-retained official section response."""
        if not raw:
            return None
        html = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        from .maine_section import (
            parse_maine_section_html,
            source_bound_maine_section_disposition,
        )

        if source_bound_maine_section_disposition(html, source_url=url) is not None:
            return None

        parsed = parse_maine_section_html(html, source_url=url, code_name=code_name)
        if parsed is not None:
            return parsed
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None
        soup = BeautifulSoup(html, "html.parser")
        if soup.select_one("div.MRSSection") is not None or not allow_legacy_fallback:
            return None
        heading = self._normalize_legal_text(
            (soup.select_one(".heading_section") or soup.find("title") or soup).get_text(
                " ", strip=True
            )
        )
        body_node = soup.select_one("div.row.section-content") or soup.select_one("div.MRSSection")
        body = self._normalize_legal_text(body_node.get_text(" ", strip=True) if body_node else "")
        if len(body) < 160:
            text_nodes = [
                self._normalize_legal_text(node.get_text(" ", strip=True))
                for node in soup.select("div.mrs-text, div.qhistory")
            ]
            body = self._normalize_legal_text(" ".join(text_nodes))
        if len(body) < 160:
            return None

        title_match = re.search(r"/title([0-9A-Za-z\-]+)sec", url, flags=re.IGNORECASE)
        section_match = re.search(r"sec([0-9A-Za-z\-]+)\.html$", url, flags=re.IGNORECASE)
        title_number = title_match.group(1) if title_match else None
        section_number = (
            section_match.group(1)
            if section_match
            else (self._extract_section_number(heading) or "")
        )
        section_name = re.sub(r"^§\s*[\w\-]+\.?\s*", "", heading).strip() or heading
        official_cite = (
            f"Me. Rev. Stat. tit. {title_number}, § {section_number}"
            if title_number
            else f"Me. Rev. Stat. § {section_number}"
        )
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} {official_cite}",
            code_name=code_name,
            title_number=title_number,
            section_number=section_number,
            section_name=section_name,
            full_text=body,
            legal_area=self._identify_legal_area(body[:1200]),
            source_url=url,
            official_cite=official_cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_maine_revised_statutes_html",
                "discovery_method": "official_title_chapter_section",
                "skip_hydrate": True,
            },
        )

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        """Parse official Maine section pages into full statute records."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            "https://legislature.maine.gov/statutes/1/title1sec1.html",
            "https://legislature.maine.gov/statutes/17-A/title17-Asec1.html",
        ]
        out: List[NormalizedStatute] = []
        for url in seeds[: max(1, int(max_statutes or 1))]:
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            try:
                html = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            heading = self._normalize_legal_text(
                (soup.select_one(".heading_section") or soup.find("title") or soup).get_text(
                    " ", strip=True
                )
            )
            body_node = soup.select_one("div.row.section-content") or soup.select_one(
                "div.MRSSection"
            )
            body = self._normalize_legal_text(
                body_node.get_text(" ", strip=True) if body_node else ""
            )
            if len(body) < 160:
                text_nodes = [
                    self._normalize_legal_text(node.get_text(" ", strip=True))
                    for node in soup.select("div.mrs-text, div.qhistory")
                ]
                body = self._normalize_legal_text(" ".join(text_nodes))
            if len(body) < 160:
                continue

            title_match = re.search(r"/title([0-9A-Za-z\-]+)sec", url, flags=re.IGNORECASE)
            section_match = re.search(r"sec([0-9A-Za-z\-]+)\.html$", url, flags=re.IGNORECASE)
            title_number = title_match.group(1) if title_match else None
            section_number = (
                section_match.group(1)
                if section_match
                else (self._extract_section_number(heading) or "")
            )
            section_name = re.sub(r"^§\s*[\w\-]+\.?\s*", "", heading).strip() or heading
            official_cite = (
                f"Me. Rev. Stat. tit. {title_number}, § {section_number}"
                if title_number
                else f"Me. Rev. Stat. § {section_number}"
            )
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} {official_cite}",
                    code_name=code_name,
                    title_number=title_number,
                    section_number=section_number,
                    section_name=section_name,
                    full_text=body,
                    legal_area=self._identify_legal_area(body[:1200]),
                    source_url=url,
                    official_cite=official_cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_maine_revised_statutes_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def _official_ssl_context(self, *, unverified: bool = False):
        import ssl

        if unverified:
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    def _official_http_get(self, url: str, timeout: int = 20) -> tuple[bytes, bytes, bytes]:
        """Fetch one official Maine URL and retain request/response/body bytes."""
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
                "User-Agent": "ipfs-datasets-open-us-law-maine/1.0",
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
            raise RuntimeError(f"official Maine GET failed for {url}: {last_exc}") from last_exc
        if status != 200 or not body:
            raise RuntimeError(f"official Maine GET returned HTTP {status} for {url}")
        response_bytes = f"HTTP/1.1 {status} OK\n{header_block}\n".encode("utf-8") + body
        return request_bytes, response_bytes, body

    def _parse_official_title_index(self, html: str, index_url: str) -> List[Dict[str, str]]:
        """Parse every official MRS title unit from the live statutes index."""
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for official Maine discovery") from exc

        soup = BeautifulSoup(html, "html.parser")
        units: List[Dict[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not re.search(
                r"statutes/[0-9A-Za-z\-]+/title[0-9A-Za-z\-]+ch0sec0\.html|"
                r"title[0-9A-Za-z\-]+ch0sec0\.html",
                href,
                re.IGNORECASE,
            ):
                continue
            full_url = urljoin(index_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            title_match = re.search(
                r"/statutes/([0-9A-Za-z\-]+)/title", full_url, flags=re.IGNORECASE
            ) or re.search(r"title([0-9A-Za-z\-]+)ch0sec0", full_url, flags=re.IGNORECASE)
            title_number = title_match.group(1) if title_match else ""
            if not title_number:
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not label:
                label = f"Title {title_number}"
            units.append(
                {
                    "canonical_key": f"me:title-{title_number.lower()}",
                    "source_url": full_url,
                    "label": label,
                    "text": (
                        f"Maine Revised Statutes Title {title_number} {label} "
                        f"official title index entry retained from {full_url}"
                    ),
                }
            )
        return units

    def fetch_official(self, code: str = "ME"):
        """Acquire the uncapped official Maine title frontier."""
        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or self.state_code or "ME").strip().upper()
        if normalized != "ME":
            raise ValueError(f"MaineScraper cannot acquire {normalized}")
        index_url = "https://legislature.maine.gov/statutes/"
        request_bytes, response_bytes, index_body = self._official_http_get(index_url)
        html = index_body.decode("utf-8", errors="replace")
        units = self._parse_official_title_index(html, index_url)
        if len(units) < 3:
            raise RuntimeError(
                f"official Maine title index is incomplete: {len(units)} units"
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
            jurisdiction_code="ME",
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            body_bytes=catalog,
            source_domain="legislature.maine.gov",
            source_path="/statutes/",
            frontier=frontier,
            rows=rows,
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=rows[0]["canonical_key"],
            last_hierarchy_unit=rows[-1]["canonical_key"],
        )


# Register this scraper with the registry
StateScraperRegistry.register("ME", MaineScraper)
